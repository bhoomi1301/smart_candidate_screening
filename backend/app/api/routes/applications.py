from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_user, require_roles
from backend.app.api.csrf import verify_csrf
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.application import ApplicationCreate, ApplicationDecision, ApplicationRead, ApplicationStatus, JobApplicationPage, StatusHistoryEntryRead, WorkflowRead
from backend.app.services.applications import application_payload, create_application, get_application, job_applications_page, list_applications, lock_application, status_history, update_application, workflow_description
from backend.app.schemas.common import MAX_DB_INT

router = APIRouter(tags=["applications"])

ApplicationId = Annotated[int, Path(gt=0, le=MAX_DB_INT)]
JobId = Annotated[int, Path(gt=0, le=MAX_DB_INT)]
manage_applications = require_roles("admin", "hr")


@router.get("/applications/workflow", response_model=WorkflowRead)
def applications_workflow(user: User = Depends(get_current_user)):
    """Statuses, permitted transitions, and decision rules enforced by the API."""
    return workflow_description()


@router.post("/jobs/{job_id}/applications", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)])
def applications_create(job_id: JobId, payload: ApplicationCreate, db: Session = Depends(get_db), user: User = Depends(manage_applications)):
    """Apply a candidate to one job. Each job has its own application, status, and screening result."""
    # The unique (candidate_id, job_id) constraint is the final guard: a concurrent request that passes
    # the duplicate pre-check fails at flush/commit and is reported as the same 409.
    try:
        application = create_application(db, user.workspace_id, job_id, user, payload)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This candidate already has an application for the job") from None
    return application_payload(application)


@router.get("/applications", response_model=list[ApplicationRead])
def applications_list(
    job_id: int | None = Query(default=None, gt=0, le=MAX_DB_INT),
    status_filter: ApplicationStatus | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0, le=MAX_DB_INT),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return list_applications(db, user.workspace_id, job_id=job_id, status_filter=status_filter, skip=skip, limit=limit)


@router.get("/jobs/{job_id}/applications", response_model=JobApplicationPage)
def job_applications(
    job_id: JobId,
    status_filter: ApplicationStatus | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0, le=MAX_DB_INT),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return job_applications_page(db, user.workspace_id, job_id, status_filter=status_filter, skip=skip, limit=limit)


@router.get("/applications/{application_id}", response_model=ApplicationRead)
def applications_get(application_id: ApplicationId, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return application_payload(get_application(db, user.workspace_id, application_id))


@router.patch(
    "/applications/{application_id}",
    response_model=ApplicationRead,
    dependencies=[Depends(verify_csrf)],
    responses={409: {"description": "Transition not allowed, or the application changed since expected_status"}, 422: {"description": "Invalid status or missing rejection note"}},
)
def applications_decide(application_id: ApplicationId, payload: ApplicationDecision, db: Session = Depends(get_db), user: User = Depends(manage_applications)):
    """Record a recruitment decision. See GET /api/applications/workflow for permitted transitions.

    The status change, its history entry, and the audit record are committed in one transaction.
    """
    application = lock_application(db, user.workspace_id, application_id)
    update_application(db, user.workspace_id, user, application, payload)
    db.commit()
    return application_payload(get_application(db, user.workspace_id, application_id))


@router.get("/applications/{application_id}/history", response_model=list[StatusHistoryEntryRead])
def applications_history(application_id: ApplicationId, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Every status change and note for this application, oldest first."""
    return status_history(db, user.workspace_id, application_id)
