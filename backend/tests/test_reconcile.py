"""端到端对账模型测试：SQLite 内存库，不依赖 Redis/PG。

覆盖：
1. 未提交写入的误报被撤警，同点有效（已提交）警报保留；
2. 补偿先于原始警报乱序到达，迟到原始警报不复活误报；
3. 丢回执后重试命中幂等，不重复撤警；
4. 重启后仅凭数据库状态继续对账直到 confirmed；
5. 未落盘警报（LSN 超过崩溃点）判 not_durable，不产生任何消息。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from src.models.entities import Base, LogSet, CrashCase, Recovery, Alarm, Reconciliation, OutboxMessage, ReceiverState
from src.services.wal_engine import recover
from src.services.reconcile_service import create_reconciliation, release_held, get_reconciliation
from src.services.outbox_service import deliver_due, deliver_one, due_messages
from src.services import receiver_service
from src.schemas.reconciliation import ReconciliationInput

RECORDS = [
    {'op': 'begin', 'tx': 'T1'}, {'op': 'write', 'tx': 'T1', 'key': 'sample_A', 'value': 75},
    {'op': 'commit', 'tx': 'T1'}, {'op': 'checkpoint'},
    {'op': 'begin', 'tx': 'T2'}, {'op': 'write', 'tx': 'T2', 'key': 'sample_B', 'value': 40},
    {'op': 'begin', 'tx': 'T3'}, {'op': 'write', 'tx': 'T3', 'key': 'sample_A', 'value': 60},
    {'op': 'commit', 'tx': 'T3'}, {'op': 'write', 'tx': 'T2', 'key': 'sample_B', 'value': 35},
    {'op': 'commit', 'tx': 'T2'},
]
INITIAL = {'sample_A': 100, 'sample_B': 50}
ALARM_LSNS = (2, 8, 10)
engine = create_engine('sqlite://')
Session = sessionmaker(bind=engine, expire_on_commit=False)
Base.metadata.create_all(engine)
PASS, FAIL = 0, 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  PASS {name}')
    else:
        FAIL += 1
        print(f'  FAIL {name} {detail}')


def setup(crash_after, sim_late=False, sim_lost_ack=False):
    db = Session()
    logs = LogSet(name=f'L-{crash_after}-{sim_late}-{sim_lost_ack}-{PASS}{FAIL}', initial=INITIAL, records=RECORDS, description='t')
    db.add(logs); db.flush()
    case = CrashCase(name=f'C-{crash_after}-{sim_late}-{sim_lost_ack}-{PASS}{FAIL}', log_set_id=logs.id, crash_after=crash_after)
    db.add(case); db.flush()
    result = recover(INITIAL, RECORDS, crash_after)
    rec = Recovery(crash_case_id=case.id, label='r', status='completed',
                   snapshot={'log_set': {'id': logs.id, 'initial': INITIAL, 'records': RECORDS},
                             'case': {'id': case.id, 'log_set_id': logs.id, 'crash_after': crash_after}},
                   result=result)
    db.add(rec); db.flush()
    for lsn, key, thr, obs in [(2, 'sample_A', 70, 75), (8, 'sample_A', 55, 60), (10, 'sample_B', 30, 35)]:
        db.add(Alarm(log_set_id=logs.id, lsn=lsn, key=key, threshold=thr, observed=obs, note='n'))
    db.flush()
    lsn_to_id = {a.lsn: a.id for a in db.scalars(select(Alarm).where(Alarm.log_set_id == logs.id)).all()}
    recon = create_reconciliation(db, ReconciliationInput(recovery_id=rec.id, label='对账',
                                                          sim_late=sim_late, sim_lost_ack=sim_lost_ack))
    db.commit()
    return db, recon.id, lsn_to_id


def test_basic_compensation():
    print('test_basic_compensation: 断电点10，T2未提交误报撤警，T1/T3有效保留')
    db, rid, aid = setup(10)
    recon = get_reconciliation(db, rid)
    msgs = db.scalars(select(OutboxMessage).where(OutboxMessage.reconciliation_id == rid).order_by(OutboxMessage.id)).all()
    check('共4条消息（3原始+1补偿）', len(msgs) == 4, str(len(msgs)))
    comp = [m for m in msgs if m.msg_type == 'compensation']
    check('仅LSN10警报有补偿', len(comp) == 1 and comp[0].alarm_id == aid[10], str(comp))
    deliver_due(db, recon, ignore_backoff=True)
    db.commit()
    states = receiver_service.current_alarm_states(db, rid)
    check('LSN2警报(T1已提交) active', states[aid[2]] == 'active', str(states))
    check('LSN8警报(T3已提交) active', states[aid[8]] == 'active', str(states))
    check('LSN10警报(T2未提交) withdrawn', states[aid[10]] == 'withdrawn', str(states))
    check('对账 confirmed', get_reconciliation(db, rid).status == 'confirmed')
    check('全部消息 acked', all(m.status == 'acked' for m in db.scalars(select(OutboxMessage).where(OutboxMessage.reconciliation_id == rid))))
    db.close()


def test_out_of_order():
    print('test_out_of_order: 补偿先到，迟到原始警报不复活')
    db, rid, aid = setup(10, sim_late=True)
    recon = get_reconciliation(db, rid)
    held = db.scalars(select(OutboxMessage).where(OutboxMessage.reconciliation_id == rid, OutboxMessage.status == 'held')).all()
    check('3条原始警报 held 模拟迟到', len(held) == 3, str(len(held)))
    # 先投递非 held（此时只有补偿可投）
    deliver_due(db, recon, ignore_backoff=True)
    db.commit()
    states = receiver_service.current_alarm_states(db, rid)
    check('补偿先到：LSN10警报 withdrawn', states.get(aid[10]) == 'withdrawn', str(states))
    check('对账仍 reconciling', get_reconciliation(db, rid).status == 'reconciling')
    # 放行迟到的原始警报
    count = release_held(db, recon)
    check('放行3条 held', count == 3)
    db.commit()
    deliver_due(db, recon, ignore_backoff=True)
    db.commit()
    rows = receiver_service.snapshot(db, rid)
    states = receiver_service.current_alarm_states(db, rid)
    check('迟到原始警报未复活误报（LSN10仍withdrawn）', states[aid[10]] == 'withdrawn', str(states))
    check('LSN2/LSN8 警报生效', states[aid[2]] == 'active' and states[aid[8]] == 'active', str(states))
    seq10 = sorted((r['arrived_seq'], r['msg_type']) for r in rows if r['alarm_id'] == aid[10])
    check('到达顺序记录补偿先于原始', seq10[0][1] == 'compensation' and seq10[1][1] == 'alarm', str(seq10))
    check('对账 confirmed', get_reconciliation(db, rid).status == 'confirmed')
    db.close()


def test_lost_ack_retry():
    print('test_lost_ack_retry: 丢回执后重试幂等，不重复撤警')
    db, rid, aid = setup(10, sim_lost_ack=True)
    recon = get_reconciliation(db, rid)
    first = deliver_due(db, recon, ignore_backoff=True)
    db.commit()
    lost = [r for r in first if r['outcome'] == 'lost_ack']
    check('首轮每条消息模拟一次丢回执', len(lost) == 4, str([(r['message_id'], r['outcome']) for r in first]))
    # 接收方其实已处理
    check('接收方已有4条去重记录', len(receiver_service.snapshot(db, rid)) == 4)
    msgs = db.scalars(select(OutboxMessage).where(OutboxMessage.reconciliation_id == rid)).all()
    check('发件箱侧全部 failed 待重试', all(m.status == 'failed' and m.attempts == 1 for m in msgs))
    # 退避未到：普通投递捞不到
    check('退避期内 due 为空', due_messages(db, rid, include_backoff=True) == [])
    # 退避后重试（ignore_backoff 模拟时间到或页面重试）
    second = deliver_due(db, recon, ignore_backoff=True)
    db.commit()
    check('重试全部 duplicate（幂等命中）', all(r['outcome'] == 'duplicate' for r in second), str(second))
    states = receiver_service.current_alarm_states(db, rid)
    check('误报仍 withdrawn 未重复撤警', states[aid[10]] == 'withdrawn', str(states))
    check('接收方记录仍为4条（无重复）', len(receiver_service.snapshot(db, rid)) == 4)
    check('对账 confirmed', get_reconciliation(db, rid).status == 'confirmed')
    msgs = db.scalars(select(OutboxMessage).where(OutboxMessage.reconciliation_id == rid)).all()
    check('每条 attempts==2 且 acked', all(m.status == 'acked' and m.attempts == 2 for m in msgs))
    db.close()


def test_restart_resume():
    print('test_restart_resume: 模拟进程重启，仅凭库内状态继续对账')
    db, rid, _ = setup(10, sim_lost_ack=True)
    recon = get_reconciliation(db, rid)
    deliver_due(db, recon, ignore_backoff=True)  # 全丢回执
    db.commit(); db.close()
    # 新 session 模拟重启
    db2 = Session()
    recon2 = get_reconciliation(db2, rid)
    check('重启后状态仍 reconciling', recon2.status == 'reconciling')
    check('重试计数持久化', all(m.attempts == 1 for m in db2.scalars(select(OutboxMessage).where(OutboxMessage.reconciliation_id == rid))))
    deliver_due(db2, recon2, ignore_backoff=True)
    db2.commit()
    check('重启后继续投递至 confirmed', get_reconciliation(db2, rid).status == 'confirmed')
    db2.close()


def test_not_durable():
    print('test_not_durable: 崩溃点0，所有警报锚定写入均未落盘，不产生任何消息')
    db, rid, _ = setup(0)
    recon = get_reconciliation(db, rid)
    plan = recon.snapshot['plan']
    check('三条警报均 not_durable', all(p['verdict'] == 'not_durable' for p in plan), str(plan))
    msgs = db.scalars(select(OutboxMessage).where(OutboxMessage.reconciliation_id == rid)).all()
    check('发件箱无消息（未落盘不发警）', len(msgs) == 0, str(len(msgs)))
    check('无消息即对账 confirmed', get_reconciliation(db, rid).status == 'confirmed')
    expected = recon.snapshot['expected_final_state']
    check('期望终态全 absent', set(expected.values()) == {'absent'}, str(expected))
    rows = receiver_service.snapshot(db, rid)
    check('接收方无记录，与期望 absent 一致', rows == [])
    db.close()


def test_idempotent_direct():
    print('test_idempotent_direct: 同一消息重复 accept 无副作用')
    db, rid, aid = setup(10)
    recon = get_reconciliation(db, rid)
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.reconciliation_id == rid,
                                                OutboxMessage.alarm_id == aid[10],
                                                OutboxMessage.msg_type == 'compensation'))
    first, state1 = deliver_one(db, msg, False, ignore_backoff=True)
    db.commit()
    # 手动把状态打回 pending 模拟异常重投
    msg.status = 'pending'
    second, state2 = deliver_one(db, msg, False, ignore_backoff=True)
    db.commit()
    check('首次 acked', first == 'acked', first)
    check('重投 duplicate', second == 'duplicate', second)
    check('状态保持 withdrawn', state1 == state2 == 'withdrawn')
    check('接收方仅1条补偿记录', len(db.scalars(select(ReceiverState).where(ReceiverState.message_id == msg.message_id)).all()) == 1)
    db.close()


if __name__ == '__main__':
    test_basic_compensation()
    test_out_of_order()
    test_lost_ack_retry()
    test_restart_resume()
    test_not_durable()
    test_idempotent_direct()
    print(f'\n{PASS} passed, {FAIL} failed')
    sys.exit(1 if FAIL else 0)
