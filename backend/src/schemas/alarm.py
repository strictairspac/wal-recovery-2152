from pydantic import BaseModel, Field


class AlarmInput(BaseModel):
    log_set_id: int = Field(gt=0)
    lsn: int = Field(ge=1, le=200)
    key: str = Field(min_length=1, max_length=50, pattern=r'^[A-Za-z0-9_-]+$')
    threshold: int = Field(ge=-1000000000, le=1000000000)
    observed: int = Field(ge=-1000000000, le=1000000000)
    note: str = Field(default='', max_length=200)
