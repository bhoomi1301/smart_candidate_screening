from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.app.api.csrf import verify_csrf
from backend.app.api.dependencies import get_current_user, require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.screening import Eligibility, JobScreeningRefreshRead, RankingPage, ScreeningRead
from backend.app.services.screening import get_screening, job_rankings, refresh_application_screening, refresh_job_screening, screening_payload
from backend.app.schemas.common import MAX_DB_INT

router = APIRouter(tags=["screening"])

ApplicationId = Annotated[int, Path(gt=0, le=MAX_DB_INT)]
JobId = Annotated[int, Path(gt=0, le=MAX_DB_INT)]
run_screening = require_roles("admin", "hr")


@router.get("/applications/{application_id}/screening", response_model=ScreeningRead)
def screening_get(application_id: ApplicationId, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Full score breakdown, eligibility, warnings, and evidence for one application."""
    return get_screening(db, user.workspace_id, application_id)


@router.post("/applications/{application_id}/screening", response_model=ScreeningRead, dependencies=[Depends(verify_csrf)])
def screening_refresh(application_id: ApplicationId, db: Session = Depends(get_db), user: User = Depends(run_screening)):
    """Evaluate (or re-evaluate) an application against the job's current criteria. Does not change its status."""
    application = refresh_application_screening(db, user.workspace_id, user, application_id)
    db.commit()
    return screening_payload(application)


@router.post("/jobs/{job_id}/screening", response_model=JobScreeningRefreshRead, dependencies=[Depends(verify_csrf)])
def screening_refresh_job(
    job_id: JobId,
    include_rejected: bool = Query(default=False, description="Also re-score rejected applications, replacing their decision-time snapshot"),
    db: Session = Depends(get_db),
    user: User = Depends(run_screening),
):
    refreshed = refresh_job_screening(db, user.workspace_id, user, job_id, include_rejected=include_rejected)
    db.commit()
    return {"job_id": job_id, "refreshed": refreshed, "include_rejected": include_rejected}


@router.get("/jobs/{job_id}/rankings", response_model=RankingPage)
def screening_rankings(
    job_id: JobId,
    eligibility: Eligibility | None = Query(default=None),
    skip: int = Query(default=0, ge=0, le=MAX_DB_INT),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Applicants for one job ranked by score; ties broken by application time, then ID. Decision support only."""
    return job_rankings(db, user.workspace_id, job_id, eligibility=eligibility, skip=skip, limit=limit)
