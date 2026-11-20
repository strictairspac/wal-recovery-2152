from sqlalchemy import select
from fastapi import HTTPException
from src.models.entities import Alarm, LogSet, Recovery, Reconciliation, OutboxMessage
from src.services.reconcile_engine import build_plan, expected_final_state
from src.utils.serialize import record


def list_reconciliations(db):
    return [record(x) for x in db.scalars(select(Reconciliation).order_by(Reconciliation.id.desc()).limit(100))]


def get_reconciliation(db, ident):
    obj = db.get(Reconciliation, ident)
    if obj is None:
        raise HTTPException(404, '对账记录不存在')
    return obj


def _refresh_status(db, obj):
    messages = db.scalars(select(OutboxMessage).where(OutboxMessage.reconciliation_id == obj.id)).all()
    unacked = [m for m in messages if m.status != 'acked']
    if not unacked:
        obj.status = 'confirmed'
    else:
        obj.status = 'reconciling'
    return obj.status


def create_reconciliation(db, data):
    recovery = db.get(Recovery, data.recovery_id)
    if recovery is None:
        raise HTTPException(404, '恢复记录不存在')
    if recovery.status != 'completed' or not recovery.result or 'recovered' not in recovery.result:
        raise HTTPException(422, '恢复演算尚未完成，先取得恢复证据再发起对账')
    log_set_id = recovery.snapshot['case']['log_set_id']
    logs = db.get(LogSet, log_set_id)
    alarms = db.scalars(select(Alarm).where(Alarm.log_set_id == log_set_id).order_by(Alarm.lsn)).all()
    if not alarms:
        raise HTTPException(422, '该日志集还没有录入警报，先在演练页面登记超限警报及其日志位置')
    obj = Reconciliation(recovery_id=recovery.id, label=data.label,
                         sim_late=data.sim_late, sim_lost_ack=data.sim_lost_ack,
                         snapshot={'recovery_id': recovery.id, 'log_set_id': log_set_id,
                                   'crash_after': recovery.result['crash_after']})
    db.add(obj)
    db.flush()
    plan = build_plan([record(a) for a in alarms], recovery.result, logs.records, obj.id)
    for item in plan:
        for entry in item['messages']:
            alarm = next(a for a in alarms if a.id == entry['alarm_id'])
            held = data.sim_late and entry['msg_type'] == 'alarm'
            payload = {'alarm_id': alarm.id, 'lsn': alarm.lsn, 'key': alarm.key,
                       'threshold': alarm.threshold, 'observed': alarm.observed,
                       'verdict': entry['verdict'], 'note': alarm.note}
            if entry['msg_type'] == 'compensation':
                payload['reason'] = '崩溃恢复撤销未提交写入，撤回报请误报'
            db.add(OutboxMessage(reconciliation_id=obj.id, alarm_id=alarm.id,
                                 message_id=entry['message_id'], msg_type=entry['msg_type'],
                                 payload=payload, status='held' if held else 'pending'))
    db.flush()
    _refresh_status(db, obj)
    # JSON 列需整体重新赋值，SQLAlchemy 才会感知变更并持久化
    obj.snapshot = {**obj.snapshot,
                    'plan': [{'alarm_id': p['alarm']['id'], 'verdict': p['verdict'],
                              'messages': [m['message_id'] for m in p['messages']]} for p in plan],
                    'expected_final_state': expected_final_state(plan)}
    db.flush()
    return obj


def release_held(db, reconciliation):
    """迟到模拟：放行所有 held 的原始警报，进入正常待投递队列。"""
    held = db.scalars(select(OutboxMessage).where(
        OutboxMessage.reconciliation_id == reconciliation.id,
        OutboxMessage.status == 'held')).all()
    for msg in held:
        msg.status = 'pending'
    db.flush()
    return len(held)
