"""验收关卡路由：投运前五道关，按顺序流转。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import GateOut, GateStatusUpdate
from app import services

router = APIRouter(prefix="/units/{unit_id}/gates", tags=["验收关卡"])


@router.get("", response_model=list[GateOut])
def list_gates(unit_id: int, db: Session = Depends(get_db)):
    return services.list_gates(db, unit_id)


@router.post("/{stage}")
def update_gate_status(
    unit_id: int,
    stage: str,
    payload: GateStatusUpdate,
    db: Session = Depends(get_db),
):
    return services.update_gate_status(db, unit_id, stage, payload)
