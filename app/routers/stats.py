"""统计路由：首批投运、平均调试耗时、未关闭问题、专项配置覆盖率。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import StatsOut
from app import services

router = APIRouter(prefix="/stats", tags=["统计"])


@router.get("", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)):
    return services.compute_stats(db)
