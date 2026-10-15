from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_user
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.analytics import ActivityFeed, DashboardSummary, SkillGapSummary, TopApplicantsRead
from backend.app.schemas.screening import Eligibility
from backend.app.services.analytics import AnalyticsFilter, dashboard_summary, recent_activity, skill_gaps, top_applicants
from backend.app.schemas.common import MAX_DB_INT

router = APIRouter(prefix="/analytics", tags=["analytics"])


def analytics_filters(
    date_from: date | None = Query(default=None, description="Inclusive UTC date (YYYY-MM-DD) on creation time"),
    date_to: date | None = Query(default=None, description="Inclusive UTC date (YYYY-MM-DD) on creation time"),
    job_id: int | None = Query(default=None, gt=0, le=MAX_DB_INT),
    department: str | None = Query(default=None, min_length=1, max_length=120),
    job_status: Literal["open", "closed"] | None = Query(default=None),
) -> AnalyticsFilter:
    return AnalyticsFilter(date_from=date_from, date_to=date_to, job_id=job_id, department=department, job_status=job_status)


@router.get("/dashboard", response_model=DashboardSummary)
def analytics_dashboard(filters: AnalyticsFilter = Depends(analytics_filters), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Headline counts, status distribution, and score coverage by job for the caller's workspace."""
    return dashboard_summary(db, user.workspace_id, filters)


@router.get("/jobs/{job_id}/top-applicants", response_model=TopApplicantsRead)
def analytics_top_applicants(
    job_id: Annotated[int, Path(gt=0, le=MAX_DB_INT)],
    eligibility: Eligibility | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Highest-ranked applicants for one job (same ordering as /jobs/{job_id}/rankings). Decision support only."""
    return top_applicants(db, user.workspace_id, job_id, eligibility=eligibility, limit=limit)


@router.get("/activity", response_model=ActivityFeed)
def analytics_activity(
    since: datetime | None = Query(default=None, description="Only activity at or after this timestamp"),
    category: Literal["candidate", "job", "application", "screening"] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recent recruitment activity across the workspace (sign-ins and user administration are excluded)."""
    return recent_activity(db, user.workspace_id, since=since, category=category, limit=limit)


@router.get("/skill-gaps", response_model=SkillGapSummary)
def analytics_skill_gaps(
    filters: AnalyticsFilter = Depends(analytics_filters),
    min_applications: int = Query(default=3, ge=1, le=1000, description="Minimum evaluated applications before a skill is reported"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Required skills most frequently missing among applicants who have skill data."""
    return skill_gaps(db, user.workspace_id, filters, min_applications=min_applications, limit=limit)
