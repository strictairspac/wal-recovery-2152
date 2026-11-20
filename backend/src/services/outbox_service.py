"""发件箱投递服务：至少一次投递 + 确定性幂等键，回执丢失可安全重试。

投递与接收方状态迁移在同一个数据库事务内提交。模拟“丢回执”时接收方实际已处理，
仅令本次投递在发件箱侧失败并退避重试；重试命中 message_id 去重，不会重复撤警。
"""
from datetime import timedelta
from sqlalchemy import select
from src.models.entities import OutboxMessage, ReceiverState, now
from src.services import receiver_service

RETRY_BACKOFF_SECONDS = 10


def _due(query, include_backoff=True):
    query = query.where(OutboxMessage.status.in_(['pending', 'failed']))
    if include_backoff:
        query = query.where(OutboxMessage.not_before <= now())
    return query


def due_messages(db, reconciliation_id=None, include_backoff=True):
    stmt = select(OutboxMessage).order_by(OutboxMessage.id)
    if reconciliation_id is not None:
        stmt = stmt.where(OutboxMessage.reconciliation_id == reconciliation_id)
    return db.scalars(_due(stmt, include_backoff)).all()


def _next_seq(db, reconciliation_id):
    last = db.scalar(select(ReceiverState.arrived_seq).where(
        ReceiverState.reconciliation_id == reconciliation_id
    ).order_by(ReceiverState.arrived_seq.desc()).limit(1))
    return (last or 0) + 1


def deliver_one(db, message, simulate_lost_ack, ignore_backoff=False):
    """投递单条消息。返回 (投递结果字符串, 接收方警报状态)。"""
    if message.status not in ('pending', 'failed'):
        return 'ignored', None
    if not ignore_backoff and message.not_before and message.not_before > now():
        return 'backoff', None
    message.attempts += 1
    first_delivery, alarm_state = receiver_service.accept(
        db, message, message.reconciliation_id, _next_seq(db, message.reconciliation_id))
    # 丢回执仅模拟“首次”投递；重复消息本身已被幂等去重，重试都应正常回执
    drop_ack = simulate_lost_ack and first_delivery and message.attempts == 1
    if drop_ack:
        message.status = 'failed'
        message.not_before = now() + timedelta(seconds=RETRY_BACKOFF_SECONDS)
        message.last_error = '模拟回执丢失：接收方已处理，等待退避后重试'
        return 'lost_ack', alarm_state
    message.status = 'acked'
    message.last_error = ''
    message.acked_at = now()
    return 'acked' if first_delivery else 'duplicate', alarm_state


def deliver_due(db, reconciliation, ignore_backoff=False):
    """投递一个对账下所有到期消息，返回逐条结果。"""
    results = []
    for message in due_messages(db, reconciliation.id, include_backoff=not ignore_backoff):
        outcome, state = deliver_one(db, message, reconciliation.sim_lost_ack, ignore_backoff)
        results.append({'message_id': message.message_id, 'msg_type': message.msg_type,
                        'alarm_id': message.alarm_id, 'outcome': outcome, 'alarm_state': state,
                        'attempts': message.attempts})
    db.flush()
    from src.services.reconcile_service import _refresh_status
    _refresh_status(db, reconciliation)
    return results
