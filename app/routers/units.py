"""机组档案与专项配置路由。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app import services
from app.schemas import (
    SpecialConfigOut,
    UnitCreate,
    UnitDetail,
    UnitSummary,
    UnitUpdate,
    SpecialConfigUpsert,
)

router = APIRouter(prefix="/units", tags=["机组档案"])


@router.get("", response_model=list[UnitSummary])
def list_units(db: Session = Depends(get_db)):
    return services.list_units(db)


@router.post("", response_model=UnitDetail, status_code=status.HTTP_201_CREATED)
def create_unit(payload: UnitCreate, db: Session = Depends(get_db)):
    return services.create_unit(db, payload)


@router.get("/{unit_id}", response_model=UnitDetail)
def get_unit(unit_id: int, db: Session = Depends(get_db)):
    return services.get_unit_detail(db, unit_id)


@router.put("/{unit_id}", response_model=UnitDetail)
def update_unit(unit_id: int, payload: UnitUpdate, db: Session = Depends(get_db)):
    return services.update_unit(db, unit_id, payload)


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(unit_id: int, db: Session = Depends(get_db)):
    services.delete_unit(db, unit_id)
    return None


# ---------- 专项配置 ----------
@router.get("/{unit_id}/configs", response_model=list[SpecialConfigOut])
def list_configs(unit_id: int, db: Session = Depends(get_db)):
    return services.list_configs(db, unit_id)


@router.post("/{unit_id}/configs", response_model=SpecialConfigOut)
def upsert_config(unit_id: int, payload: SpecialConfigUpsert, db: Session = Depends(get_db)):
    return services.upsert_config(db, unit_id, payload)


@router.delete("/{unit_id}/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_config(unit_id: int, config_id: int, db: Session = Depends(get_db)):
    services.delete_config(db, unit_id, config_id)
    return None
