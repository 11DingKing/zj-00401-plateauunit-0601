"""统计路由：首批投运、平均调试耗时、未关闭问题、专项配置覆盖率。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import StatsOut, SlopeReviewOut
from app import services

router = APIRouter(prefix="/stats", tags=["统计"])


@router.get("", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)):
    return services.compute_stats(db)


@router.get("/slope-review", response_model=SlopeReviewOut, summary="坡位适配复盘")
def get_slope_review(db: Session = Depends(get_db)):
    """
    坡位适配复盘：同一批机组按山脊坡位归组，对比低空气密度、强风乱流、
    温控和叶片优化几类配置的验收通过率、返工次数和平均调试耗时。
    机组档案、验收记录、专项配置和统计汇总都已串起来，
    输出风险评分帮助项目经理判断哪类坡位最容易拖慢投运。
    """
    return services.compute_slope_review(db)
