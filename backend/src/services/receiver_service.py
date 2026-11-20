"""接收方幂等状态机。

规则（教学模型，状态全部落 PostgreSQL）：
1. message_id 去重：重复投递直接返回已保存的处理结果，不产生第二次状态迁移。
2. 乱序安全：撤警补偿先于原始警报到达时，警报落为 withdrawn；迟到的原始警报不能让它复活。
3. 同一警报重复撤警为无副作用操作，状态保持 withdrawn。
4. 每条处理过的消息一行；警报当前状态取该 alarm_id 到达序号最大的事件，全部处理在事务内完成。
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models.entities import ReceiverState
from src.models.entities import now


def _transition(alarm_state, msg_type):
    if msg_type == 'alarm':
        # 补偿先到（withdrawn）后，迟到的原始警报不得复活误报
        return alarm_state if alarm_state == 'withdrawn' else 'active'
    if msg_type == 'compensation':
        # 重复撤警无副作用；原始警报未到时直接登记为 withdrawn
        return 'withdrawn'
    raise ValueError('未知消息类型')


def latest_state(db, reconciliation_id, alarm_id):
    row = db.scalar(select(ReceiverState).where(
        ReceiverState.reconciliation_id == reconciliation_id,
        ReceiverState.alarm_id == alarm_id).order_by(ReceiverState.arrived_seq.desc()).limit(1))
    return row.alarm_state if row else 'absent'


def accept(db, message, reconciliation_id, seq):
    """处理一条入站消息，返回 (是否首次处理, 警报当前状态)。"""
    existing = db.scalar(select(ReceiverState).where(ReceiverState.message_id == message.message_id))
    if existing is not None:
        return False, existing.alarm_state
    prior = latest_state(db, reconciliation_id, message.alarm_id)
    row = ReceiverState(reconciliation_id=reconciliation_id, alarm_id=message.alarm_id,
                        message_id=message.message_id, msg_type=message.msg_type,
                        arrived_seq=seq, delivered_at=now(),
                        alarm_state=_transition(prior, message.msg_type))
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raced = db.scalar(select(ReceiverState).where(ReceiverState.message_id == message.message_id))
        if raced is not None:
            return False, raced.alarm_state
        raise HTTPException(500, '接收方状态冲突，请重试')
    return True, row.alarm_state


def snapshot(db, reconciliation_id):
    rows = db.scalars(select(ReceiverState).where(
        ReceiverState.reconciliation_id == reconciliation_id).order_by(ReceiverState.arrived_seq)).all()
    return [{'alarm_id': r.alarm_id, 'message_id': r.message_id, 'msg_type': r.msg_type,
             'alarm_state': r.alarm_state, 'arrived_seq': r.arrived_seq,
             'delivered_at': r.delivered_at.isoformat() if r.delivered_at else None} for r in rows]


def current_alarm_states(db, reconciliation_id):
    """每个警报的当前生效状态，取到达序号最大的事件。"""
    rows = db.scalars(select(ReceiverState).where(
        ReceiverState.reconciliation_id == reconciliation_id).order_by(ReceiverState.arrived_seq)).all()
    current = {}
    for row in rows:
        current[row.alarm_id] = row.alarm_state
    return current
