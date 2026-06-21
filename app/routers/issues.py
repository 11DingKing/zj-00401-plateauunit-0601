"""问题清单路由。"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import IssueAssign, IssueClose, IssueCreate, IssueOut
from app import services

router = APIRouter(prefix="/issues", tags=["问题清单"])


@router.get("", response_model=list[IssueOut])
def list_issues(
    status: Optional[str] = None,
    unit_id: Optional[int] = None,
    stage: Optional[str] = None,
    team: Optional[str] = None,
    overdue: Optional[bool] = Query(None, description="是否逾期：true 只看逾期 / false 只看不逾期"),
    db: Session = Depends(get_db),
):
    return services.list_issues(
        db,
        status_filter=status,
        unit_id=unit_id,
        stage=stage,
        team=team,
        overdue=overdue,
    )


@router.post("", response_model=IssueOut, status_code=status.HTTP_201_CREATED)
def create_issue(payload: IssueCreate, db: Session = Depends(get_db)):
    return services.create_issue(db, payload)


@router.post("/{issue_id}/assign", response_model=IssueOut, summary="分派责任班组 / 约定关闭时限")
def assign_issue(issue_id: int, payload: IssueAssign, db: Session = Depends(get_db)):
    return services.assign_issue(db, issue_id, payload)


@router.post("/{issue_id}/close", response_model=IssueOut)
def close_issue(issue_id: int, payload: IssueClose, db: Session = Depends(get_db)):
    return services.close_issue(db, issue_id, payload)
