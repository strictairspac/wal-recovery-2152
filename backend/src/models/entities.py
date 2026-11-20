from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, JSON, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    email: Mapped[str]=mapped_column(String(120),unique=True)
    role: Mapped[str]=mapped_column(String(20))
    password_hash: Mapped[str]=mapped_column(String(250))
class LogSet(Base):
    __tablename__='log_sets'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(100),unique=True)
    initial: Mapped[dict]=mapped_column(JSON)
    records: Mapped[list]=mapped_column(JSON)
    description: Mapped[str]=mapped_column(String(500))
class CrashCase(Base):
    __tablename__='crash_cases'
    id: Mapped[int]=mapped_column(primary_key=True)
    log_set_id: Mapped[int]=mapped_column(ForeignKey('log_sets.id'))
    name: Mapped[str]=mapped_column(String(100),unique=True)
    crash_after: Mapped[int]=mapped_column(Integer)
class Recovery(Base):
    __tablename__='recoveries'
    id: Mapped[int]=mapped_column(primary_key=True)
    crash_case_id: Mapped[int]=mapped_column(ForeignKey('crash_cases.id'))
    label: Mapped[str]=mapped_column(String(120))
    status: Mapped[str]=mapped_column(String(20),default='queued')
    snapshot: Mapped[dict]=mapped_column(JSON)
    result: Mapped[dict | None]=mapped_column(JSON,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class Alarm(Base):
    __tablename__='alarms'
    __table_args__=(UniqueConstraint('log_set_id','lsn',name='uq_alarm_logset_lsn'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    log_set_id: Mapped[int]=mapped_column(ForeignKey('log_sets.id'))
    lsn: Mapped[int]=mapped_column(Integer)
    key: Mapped[str]=mapped_column(String(50))
    threshold: Mapped[int]=mapped_column(Integer)
    observed: Mapped[int]=mapped_column(Integer)
    note: Mapped[str]=mapped_column(String(200),default='')
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class Reconciliation(Base):
    __tablename__='reconciliations'
    id: Mapped[int]=mapped_column(primary_key=True)
    recovery_id: Mapped[int]=mapped_column(ForeignKey('recoveries.id'))
    label: Mapped[str]=mapped_column(String(120))
    status: Mapped[str]=mapped_column(String(20),default='reconciling')
    sim_late: Mapped[bool]=mapped_column(Boolean,default=False)
    sim_lost_ack: Mapped[bool]=mapped_column(Boolean,default=False)
    snapshot: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class OutboxMessage(Base):
    __tablename__='outbox_messages'
    __table_args__=(UniqueConstraint('message_id',name='uq_outbox_message_id'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    reconciliation_id: Mapped[int]=mapped_column(ForeignKey('reconciliations.id'))
    alarm_id: Mapped[int]=mapped_column(ForeignKey('alarms.id'))
    message_id: Mapped[str]=mapped_column(String(80))
    msg_type: Mapped[str]=mapped_column(String(20))
    payload: Mapped[dict]=mapped_column(JSON)
    status: Mapped[str]=mapped_column(String(20),default='pending')
    attempts: Mapped[int]=mapped_column(Integer,default=0)
    not_before: Mapped[datetime]=mapped_column(DateTime,default=now)
    last_error: Mapped[str]=mapped_column(String(300),default='')
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
    acked_at: Mapped[datetime | None]=mapped_column(DateTime,nullable=True)
class ReceiverState(Base):
    """接收方去重账本：每条处理过的消息一行（message_id 幂等），警报终态取同 alarm_id 最新事件。"""
    __tablename__='receiver_states'
    __table_args__=(UniqueConstraint('message_id',name='uq_receiver_message_id'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    reconciliation_id: Mapped[int]=mapped_column(ForeignKey('reconciliations.id'))
    alarm_id: Mapped[int]=mapped_column(ForeignKey('alarms.id'))
    message_id: Mapped[str]=mapped_column(String(80))
    msg_type: Mapped[str]=mapped_column(String(20))
    alarm_state: Mapped[str]=mapped_column(String(20),default='absent')
    arrived_seq: Mapped[int]=mapped_column(Integer,default=0)
    delivered_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class Audit(Base):
    __tablename__='audits'
    id: Mapped[int]=mapped_column(primary_key=True)
    actor: Mapped[str]=mapped_column(String(120))
    action: Mapped[str]=mapped_column(String(120))
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
