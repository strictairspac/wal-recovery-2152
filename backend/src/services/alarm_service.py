from sqlalchemy import select
from fastapi import HTTPException
from src.models.entities import Alarm, LogSet
from src.services.reconcile_engine import validate_alarm
from src.utils.serialize import record


def list_alarms(db):
    return [record(x) for x in db.scalars(select(Alarm).order_by(Alarm.log_set_id, Alarm.lsn, Alarm.id))]


def create_alarm(db, data):
    logs = db.get(LogSet, data.log_set_id)
    if logs is None:
        raise HTTPException(404, '日志集不存在')
    values = data.model_dump()
    validate_alarm(logs.records, values['lsn'], values['key'], values['threshold'], values['observed'])
    dup = db.scalar(select(Alarm.id).where(Alarm.log_set_id == values['log_set_id'], Alarm.lsn == values['lsn']))
    if dup is not None:
        raise HTTPException(409, '该日志位置已录入警报，同一写入不重复建警')
    obj = Alarm(**values)
    db.add(obj)
    db.flush()
    return record(obj)
