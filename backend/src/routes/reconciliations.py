import json
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from src.config.database import get_db
from src.middlewares.auth import current_user, writable
from src.schemas.reconciliation import ReconciliationInput
from src.models.entities import OutboxMessage, Alarm
from src.services.reconcile_service import (list_reconciliations, get_reconciliation,
                                           create_reconciliation, release_held)
from src.services.outbox_service import deliver_due
from src.services import receiver_service
from src.controllers.actions import audit
from src.utils.serialize import record
router = APIRouter()


def _detail(db, obj):
    messages = [record(m) for m in db.scalars(
        select(OutboxMessage).where(OutboxMessage.reconciliation_id == obj.id).order_by(OutboxMessage.id))]
    alarms = {a.id: record(a) for a in db.scalars(select(Alarm)).all()}
    receiver = receiver_service.snapshot(db, obj.id)
    out = record(obj)
    out['messages'] = messages
    out['receiver_states'] = receiver
    out['alarms'] = {str(k): alarms.get(k) for k in {m['alarm_id'] for m in messages}}
    out['expected_final_state'] = obj.snapshot.get('expected_final_state', {})
    out['matches_expected'] = _matches_expected(obj, receiver)
    return out


def _matches_expected(obj, receiver):
    expected = obj.snapshot.get('expected_final_state') or {}
    if not expected:
        return False
    current = {}
    for row in receiver:
        current[row['alarm_id']] = row['alarm_state']
    return all(current.get(int(alarm_id)) == state for alarm_id, state in expected.items()) \
        and obj.status == 'confirmed'

@router.get('/reconciliations')
def listing(db=Depends(get_db), user=Depends(current_user)):
    return list_reconciliations(db)


@router.post('/reconciliations', status_code=202)
def create(data: ReconciliationInput, db=Depends(get_db), user=Depends(writable)):
    obj = create_reconciliation(db, data)
    audit(db, user, f'reconciliation:enqueue:{obj.id}')
    db.commit()
    return record(obj)


@router.get('/reconciliations/{ident}')
def detail(ident: int, db=Depends(get_db), user=Depends(current_user)):
    return _detail(db, get_reconciliation(db, ident))


@router.post('/reconciliations/{ident}/release-late')
def release_late(ident: int, db=Depends(get_db), user=Depends(writable)):
    obj = get_reconciliation(db, ident)
    count = release_held(db, obj)
    audit(db, user, f'reconciliation:release_late:{ident}:{count}')
    db.commit()
    return _detail(db, obj)


@router.post('/reconciliations/{ident}/deliver')
def deliver(ident: int, db=Depends(get_db), user=Depends(writable)):
    obj = get_reconciliation(db, ident)
    results = deliver_due(db, obj, ignore_backoff=True)
    audit(db, user, f'reconciliation:deliver:{ident}:{len(results)}')
    db.commit()
    return _detail(db, obj)


@router.get('/reconciliations/{ident}/export')
def export(ident: int, db=Depends(get_db), user=Depends(current_user)):
    obj = get_reconciliation(db, ident)
    payload = _detail(db, obj)
    return Response(json.dumps(payload, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="reconciliation-{ident}.json"'})
