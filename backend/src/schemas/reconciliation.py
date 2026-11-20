from pydantic import BaseModel, Field


class ReconciliationInput(BaseModel):
    recovery_id: int = Field(gt=0)
    label: str = Field(min_length=2, max_length=120)
    sim_late: bool = False
    sim_lost_ack: bool = False
