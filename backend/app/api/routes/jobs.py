from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_user, require_roles
from backend.app.api.csrf import verify_csrf
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.job import JobCreate, JobPage, JobRead, JobStatusInput, JobUpdate
from backend.app.services.jobs import create_job, delete_job, get_job, job_detail_payload, job_payload, list_jobs, set_job_status, update_job
from backend.app.schemas.common import MAX_DB_INT

router = APIRouter(prefix="/jobs", tags=["jobs"])

JobId = Annotated[int, Path(gt=0, le=MAX_DB_INT)]
manage_jobs = require_roles("admin", "hr")


@router.get("", response_model=JobPage)
def jobs_list(
    status_filter: Literal["open", "closed"] | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=120, description="Search title or department"),
    department: str | None = Query(default=None, min_length=1, max_length=120),
    skip: int = Query(default=0, ge=0, le=MAX_DB_INT),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows, total = list_jobs(db, user.workspace_id, status_filter=status_filter, q=q, department=department, skip=skip, limit=limit)
    return {"items": rows, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)])
def jobs_create(payload: JobCreate, db: Session = Depends(get_db), user: User = Depends(manage_jobs)):
    job = create_job(db, user.workspace_id, user, payload)
    db.commit()
    return job_payload(job)


@router.get("/{job_id}", response_model=JobRead)
def jobs_get(job_id: JobId, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return job_detail_payload(db, get_job(db, user.workspace_id, job_id))


@router.put("/{job_id}", response_model=JobRead, dependencies=[Depends(verify_csrf)])
def jobs_update(job_id: JobId, payload: JobUpdate, db: Session = Depends(get_db), user: User = Depends(manage_jobs)):
    job = get_job(db, user.workspace_id, job_id)
    update_job(db, user.workspace_id, user, job, payload)
    db.commit()
    return job_detail_payload(db, job)


@router.patch("/{job_id}/status", response_model=JobRead, dependencies=[Depends(verify_csrf)])
def jobs_change_status(job_id: JobId, payload: JobStatusInput, db: Session = Depends(get_db), user: User = Depends(manage_jobs)):
    job = get_job(db, user.workspace_id, job_id)
    set_job_status(db, user.workspace_id, user, job, payload.status)
    db.commit()
    return job_detail_payload(db, job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_csrf)])
def jobs_delete(job_id: JobId, db: Session = Depends(get_db), user: User = Depends(manage_jobs)):
    job = get_job(db, user.workspace_id, job_id)
    delete_job(db, user.workspace_id, user, job)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
