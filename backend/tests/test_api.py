"""HTTP 集成测试：FastAPI + SQLite，覆盖权限、校验、完整对账演练与导出。"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import src.config.database as database
from src.models.entities import Base, User, LogSet, CrashCase, Recovery, Alarm
from src.services.wal_engine import recover
from src.utils.security import hash_password

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
TestSession = sessionmaker(bind=engine, expire_on_commit=False)
Base.metadata.create_all(engine)
database.engine = engine
database.Session = TestSession

from src.main import app  # noqa: E402
from src.config.database import get_db  # noqa: E402


def override_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db
client = TestClient(app)
PASS = FAIL = 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  PASS {name}')
    else:
        FAIL += 1
        print(f'  FAIL {name} {detail}')


with TestSession() as db:
    for role in ('admin', 'operator', 'viewer'):
        db.add(User(email=f'{role}@haili.local', role=role, password_hash=hash_password('Recovery2026!')))
    db.commit()

RECORDS = [
    {'op': 'begin', 'tx': 'T1'}, {'op': 'write', 'tx': 'T1', 'key': 'sample_A', 'value': 75},
    {'op': 'commit', 'tx': 'T1'}, {'op': 'checkpoint'},
    {'op': 'begin', 'tx': 'T2'}, {'op': 'write', 'tx': 'T2', 'key': 'sample_B', 'value': 40},
    {'op': 'begin', 'tx': 'T3'}, {'op': 'write', 'tx': 'T3', 'key': 'sample_A', 'value': 60},
    {'op': 'commit', 'tx': 'T3'}, {'op': 'write', 'tx': 'T2', 'key': 'sample_B', 'value': 35},
    {'op': 'commit', 'tx': 'T2'},
]
with TestSession() as db:
    logs = LogSet(name='账本', initial={'sample_A': 100, 'sample_B': 50}, records=RECORDS, description='d')
    db.add(logs); db.flush()
    case = CrashCase(name='断电点10', log_set_id=logs.id, crash_after=10)
    db.add(case); db.flush()
    db.add(Recovery(crash_case_id=case.id, label='恢复', status='completed',
                    snapshot={'log_set': {'id': logs.id, 'initial': logs.initial, 'records': RECORDS},
                              'case': {'id': case.id, 'log_set_id': logs.id, 'crash_after': 10}},
                    result=recover(logs.initial, RECORDS, 10)))
    db.commit()
    log_set_id, case_id = logs.id, case.id


def token(role):
    r = client.post('/auth/login', json={'email': f'{role}@haili.local', 'password': 'Recovery2026!'})
    check(f'{role} 登录', r.status_code == 200, r.text)
    return r.json()['access_token']


op = {'Authorization': 'Bearer ' + token('operator')}
vw = {'Authorization': 'Bearer ' + token('viewer')}
ad = {'Authorization': 'Bearer ' + token('admin')}

print('test_alarm_crud_and_validation')
r = client.post('/alarms', headers=vw, json={'log_set_id': log_set_id, 'lsn': 2, 'key': 'sample_A',
                                             'threshold': 70, 'observed': 75})
check('观察员录入警报 403', r.status_code == 403, r.status_code)
r = client.post('/alarms', headers=op, json={'log_set_id': log_set_id, 'lsn': 3, 'key': 'sample_A',
                                             'threshold': 70, 'observed': 75})
check('锚定非 write 日志 422', r.status_code == 422 and 'write' in r.json()['detail'], r.text)
r = client.post('/alarms', headers=op, json={'log_set_id': log_set_id, 'lsn': 2, 'key': 'sample_B',
                                             'threshold': 70, 'observed': 75})
check('警报键与写入键不一致 422', r.status_code == 422, r.text)
r = client.post('/alarms', headers=op, json={'log_set_id': log_set_id, 'lsn': 2, 'key': 'sample_A',
                                             'threshold': 80, 'observed': 75})
check('未超限拒绝录入 422', r.status_code == 422, r.text)
r = client.post('/alarms', headers=op, json={'log_set_id': 999, 'lsn': 2, 'key': 'sample_A',
                                             'threshold': 70, 'observed': 75})
check('未知日志集 404', r.status_code == 404, r.text)
for lsn, key, thr, obs in [(2, 'sample_A', 70, 75), (8, 'sample_A', 55, 60), (10, 'sample_B', 30, 35)]:
    r = client.post('/alarms', headers=op, json={'log_set_id': log_set_id, 'lsn': lsn, 'key': key,
                                                 'threshold': thr, 'observed': obs, 'note': 'n'})
    check(f'录入 LSN{lsn} 警报 201', r.status_code == 201, r.text)
r = client.post('/alarms', headers=op, json={'log_set_id': log_set_id, 'lsn': 2, 'key': 'sample_A',
                                             'threshold': 70, 'observed': 75})
check('同位置重复警报 409', r.status_code == 409, r.text)
r = client.get('/alarms', headers=vw)
check('观察员可查看警报列表', r.status_code == 200 and len(r.json()) == 3, r.text)

print('test_reconciliation_flow')
with TestSession() as db:
    recovery_id = db.scalar(select(Recovery).where(Recovery.crash_case_id == case_id)).id
r = client.post('/reconciliations', headers=vw,
                json={'recovery_id': recovery_id, 'label': '对账演练'})
check('观察员发起对账 403', r.status_code == 403, r.status_code)
r = client.post('/reconciliations', headers=op,
                json={'recovery_id': 9999, 'label': '对账演练'})
check('未知恢复 404', r.status_code == 404, r.text)
r = client.post('/reconciliations', headers=op,
                json={'recovery_id': recovery_id, 'label': '对账', 'sim_late': True, 'sim_lost_ack': True})
check('创建对账 202', r.status_code == 202, r.text)
rid = r.json()['id']
check('初始 reconciling', r.json()['status'] == 'reconciling')
r = client.get(f'/reconciliations/{rid}', headers=vw)
detail = r.json()
check('观察员可查看对账（先看账本）', r.status_code == 200)
check('held 3 条迟到原始警报', sum(1 for m in detail['messages'] if m['status'] == 'held') == 3, str(detail['messages']))
check('计划含 false_alarm/valid 判定',
      {p['verdict'] for p in detail['snapshot']['plan']} == {'valid', 'false_alarm'}, str(detail['snapshot']['plan']))
# 先投递：补偿先到
r = client.post(f'/reconciliations/{rid}/deliver', headers=op)
check('首轮投递（丢回执模拟）', r.status_code == 200, r.text)
d1 = r.json()
check('补偿 lost_ack 且接收方已 withdrawn',
      any(m['msg_type'] == 'compensation' and m['status'] == 'failed' for m in d1['messages'])
      and any(s['alarm_state'] == 'withdrawn' for s in d1['receiver_states']), str(d1))
# 放行迟到原始警报
r = client.post(f'/reconciliations/{rid}/release-late', headers=op)
check('放行 held', r.status_code == 200 and sum(1 for m in r.json()['messages'] if m['status'] == 'held') == 0, r.text)
# 第二次投递：补偿重试幂等 acked；迟到原始警报首次投递同样模拟丢回执
r = client.post(f'/reconciliations/{rid}/deliver', headers=op)
d_mid = r.json()
check('补偿重试 acked 且迟到警报进入 failed 退避',
      next(m for m in d_mid['messages'] if m['msg_type'] == 'compensation')['status'] == 'acked'
      and sum(1 for m in d_mid['messages'] if m['status'] == 'failed') == 3, str(d_mid['messages']))
# 第三次投递：迟到警报重试命中 message_id 去重，全部 acked
r = client.post(f'/reconciliations/{rid}/deliver', headers=op)
d2 = r.json()
check('重试后全部 acked', all(m['status'] == 'acked' for m in d2['messages']), str(d2['messages']))
check('对账 confirmed（接收方确认后完成）', d2['status'] == 'confirmed', d2['status'])
check('终态与期望一致', d2['matches_expected'] is True, str(d2['matches_expected']))
withdrawn = [s for s in d2['receiver_states'] if s['alarm_state'] == 'withdrawn']
check('仅误报警报 withdrawn 且接收方无重复记录',
      len({s['alarm_id'] for s in withdrawn}) == 1 and len(d2['receiver_states']) == 4, str(d2['receiver_states']))
# 重复投递无副作用
r = client.post(f'/reconciliations/{rid}/deliver', headers=op)
check('confirmed 后再投递不改变状态', r.json()['status'] == 'confirmed' and len(r.json()['receiver_states']) == 4)

print('test_export_and_audit')
r = client.get(f'/reconciliations/{rid}/export', headers=vw)
check('观察员可导出对账 JSON', r.status_code == 200 and 'attachment' in r.headers.get('content-disposition', ''), r.text[:120])
payload = r.json()
check('导出含发件箱与接收方状态', {'messages', 'receiver_states', 'expected_final_state'} <= set(payload))
r = client.get('/audits', headers=ad)
actions = {a['action'].split(':')[0] for a in r.json()}
check('管理员审计含 alarm/reconciliation 记录', {'alarm', 'reconciliation'} <= actions, str(actions))
r = client.get('/audits', headers=op)
check('操作员查审计 403', r.status_code == 403)

print(f'\n{PASS} passed, {FAIL} failed')
sys.exit(1 if FAIL else 0)
