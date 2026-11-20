from fastapi import APIRouter, Depends, HTTPException
from src.config.database import get_db
from src.middlewares.auth import current_user, writable
from src.schemas.alarm import AlarmInput
from src.services.alarm_service import list_alarms, create_alarm
from src.controllers.actions import audit
router = APIRouter()


@router.get('/alarms')
def listing(db=Depends(get_db), user=Depends(current_user)):
    return list_alarms(db)


@router.post('/alarms', status_code=201)
def create(data: AlarmInput, db=Depends(get_db), user=Depends(writable)):
    try:
        out = create_alarm(db, data)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit(db, user, f'alarm:create:{out["id"]}')
    db.commit()
    return out
