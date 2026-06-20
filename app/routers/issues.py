"""问题清单路由。"""

from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import IssueClose, IssueCreate, IssueOut
from app import services

router = APIRouter(prefix="/issues", tags=["问题清单"])


@router.get("", response_model=list[IssueOut])
def list_issues(
    status: Optional[str] = None,
    unit_id: Optional[int] = None,
    stage: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return services.list_issues(db, status_filter=status, unit_id=unit_id, stage=stage)


@router.post("", response_model=IssueOut, status_code=status.HTTP_201_CREATED)
def create_issue(payload: IssueCreate, db: Session = Depends(get_db)):
    return services.create_issue(db, payload)


@router.post("/{issue_id}/close", response_model=IssueOut)
def close_issue(issue_id: int, payload: IssueClose, db: Session = Depends(get_db)):
    return services.close_issue(db, issue_id, payload.closed_by)
