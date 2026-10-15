from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models.application import APPLICATION_STATUSES, Application, ApplicationStatusHistory
from backend.app.models.candidate import Candidate, CandidateSkill
from backend.app.models.job import Job
from backend.app.models.user import User
from backend.app.schemas.application import REJECTION_NOTE_MIN_LENGTH, ApplicationCreate, ApplicationDecision
from backend.app.services.audit import record_audit
from backend.app.services.screening import evaluate_application, screening_result_payload


_TRANSITIONS = {
    "Pending": {"Under Review", "Rejected"},
    "Under Review": {"Shortlisted", "Rejected"},
    "Shortlisted": {"Under Review", "Rejected"},
    "Rejected": set(),
}


def application_payload(application: Application) -> dict:
    candidate = application.candidate
    history = sorted(application.status_history, key=lambda item: (item.changed_at, item.id))
    return {
        "id": application.id,
        "workspace_id": application.workspace_id,
        "candidate_id": application.candidate_id,
        "job_id": application.job_id,
        "status": application.status,
        "current_screening_score": application.current_screening_score,
        "decision_notes": application.decision_notes,
        "created_at": application.created_at,
        "updated_at": application.updated_at,
        "screening_result": screening_result_payload(application.screening_result),
        "status_history": [
            {"previous_status": item.previous_status, "new_status": item.new_status, "changed_by": item.changed_by, "notes": item.notes, "changed_at": item.changed_at}
            for item in history
        ],
        "candidate": {
            "id": candidate.id,
            "full_name": candidate.full_name,
            "email": candidate.email,
            "total_experience": candidate.total_experience,
            "technical_skills": [link.skill.display_name for link in candidate.skills],
        },
    }


def get_application(db: Session, workspace_id: int, application_id: int) -> Application:
    application = db.scalar(
        select(Application)
        .options(
            selectinload(Application.screening_result),
            selectinload(Application.status_history),
            selectinload(Application.candidate).selectinload(Candidate.skills).joinedload(CandidateSkill.skill),
        )
        .where(Application.id == application_id, Application.workspace_id == workspace_id)
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def list_applications(db: Session, workspace_id: int, *, job_id: int | None, status_filter: str | None, skip: int, limit: int) -> list[dict]:
    query = select(Application).where(Application.workspace_id == workspace_id)
    if job_id is not None:
        query = query.where(Application.job_id == job_id)
    if status_filter is not None:
        if status_filter not in APPLICATION_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid application status")
        query = query.where(Application.status == status_filter)
    rows = db.scalars(
        query.options(
            selectinload(Application.screening_result),
            selectinload(Application.status_history),
            selectinload(Application.candidate).selectinload(Candidate.skills).joinedload(CandidateSkill.skill),
        )
        .order_by(Application.current_screening_score.desc().nullslast(), Application.created_at, Application.id)
        .offset(skip)
        .limit(limit)
    ).all()
    return [application_payload(row) for row in rows]


def existing_application_id(db: Session, workspace_id: int, candidate_id: int, job_id: int) -> int | None:
    return db.scalar(
        select(Application.id).where(
            Application.workspace_id == workspace_id,
            Application.candidate_id == candidate_id,
            Application.job_id == job_id,
        )
    )


def create_application(db: Session, workspace_id: int, job_id: int, actor: User, payload: ApplicationCreate) -> Application:
    candidate = db.scalar(select(Candidate).where(Candidate.id == payload.candidate_id, Candidate.workspace_id == workspace_id))
    job = db.scalar(select(Job).where(Job.id == job_id, Job.workspace_id == workspace_id))
    if candidate is None or job is None:
        raise HTTPException(status_code=404, detail="Candidate or job not found")
    if job.status != "open":
        raise HTTPException(status_code=409, detail="Applications cannot be added to a closed job")
    if existing_application_id(db, workspace_id, candidate.id, job.id):
        raise HTTPException(status_code=409, detail="Candidate already has an application for this job")
    application = Application(workspace_id=workspace_id, candidate_id=candidate.id, job_id=job.id, status="Pending")
    db.add(application)
    db.flush()
    evaluate_application(db, application)
    db.add(ApplicationStatusHistory(workspace_id=workspace_id, application_id=application.id, new_status="Pending", changed_by=actor.id, notes="Application created"))
    record_audit(db, workspace_id=workspace_id, actor=actor, action="application.create", resource_type="application", resource_id=application.id, metadata={"job_id": job.id, "candidate_id": candidate.id})
    record_audit(db, workspace_id=workspace_id, actor=actor, action="screening.evaluate", resource_type="application", resource_id=application.id, metadata={"score": str(application.current_screening_score), "eligibility": application.screening_result.eligibility, "trigger": "application_created"})
    return application


def workflow_description() -> dict:
    return {
        "statuses": list(APPLICATION_STATUSES),
        "initial_status": "Pending",
        "terminal_statuses": [name for name, allowed in _TRANSITIONS.items() if not allowed],
        "transitions": [{"from_status": name, "allowed": sorted(allowed, key=APPLICATION_STATUSES.index)} for name, allowed in _TRANSITIONS.items()],
        "rules": [
            "New applications start as Pending.",
            f"Rejecting requires an explanatory note of at least {REJECTION_NOTE_MIN_LENGTH} characters; notes are optional for other transitions.",
            "Rejected is terminal; its status cannot change.",
            "Sending the current status with a note records a note without changing status.",
            "Send expected_status to fail with 409 if another reviewer changed the application first.",
            "Every status change and note is recorded in the status history with actor, timestamp, and notes.",
            "Screening never changes status; decisions are made by people.",
        ],
    }


def lock_application(db: Session, workspace_id: int, application_id: int) -> Application:
    """Load an application for a decision, holding a row lock until commit (PostgreSQL; no-op on SQLite)."""
    application = db.scalar(
        select(Application)
        .where(Application.id == application_id, Application.workspace_id == workspace_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def update_application(db: Session, workspace_id: int, actor: User, application: Application, payload: ApplicationDecision) -> Application:
    previous = application.status
    if payload.expected_status is not None and payload.expected_status != previous:
        raise HTTPException(status_code=409, detail=f"Application is now {previous}, not {payload.expected_status}; reload before deciding")
    note_only = payload.status == previous
    if note_only and not payload.notes:
        raise HTTPException(status_code=409, detail=f"Application is already {previous}; add notes to record a comment")
    if not note_only and payload.status not in _TRANSITIONS[previous]:
        allowed = ", ".join(sorted(_TRANSITIONS[previous], key=APPLICATION_STATUSES.index)) or "none (terminal status)"
        raise HTTPException(status_code=409, detail=f"Cannot move application from {previous} to {payload.status}. Allowed: {allowed}")
    if not note_only:
        application.status = payload.status
        application.decision_notes = payload.notes
    # Status, history, and audit are flushed in the caller's single transaction: all commit or none do.
    db.add(
        ApplicationStatusHistory(
            workspace_id=workspace_id,
            application_id=application.id,
            previous_status=previous,
            new_status=application.status,
            changed_by=actor.id,
            notes=payload.notes,
        )
    )
    record_audit(
        db,
        workspace_id=workspace_id,
        actor=actor,
        action="application.note" if note_only else "application.decision",
        resource_type="application",
        resource_id=application.id,
        metadata={"job_id": application.job_id, "candidate_id": application.candidate_id, "previous_status": previous, "new_status": application.status, "has_notes": bool(payload.notes)},
    )
    return application


def status_history(db: Session, workspace_id: int, application_id: int) -> list[dict]:
    if db.scalar(select(Application.id).where(Application.id == application_id, Application.workspace_id == workspace_id)) is None:
        raise HTTPException(status_code=404, detail="Application not found")
    rows = db.execute(
        select(ApplicationStatusHistory, User.full_name)
        .outerjoin(User, (User.id == ApplicationStatusHistory.changed_by) & (User.workspace_id == ApplicationStatusHistory.workspace_id))
        .where(ApplicationStatusHistory.workspace_id == workspace_id, ApplicationStatusHistory.application_id == application_id)
        .order_by(ApplicationStatusHistory.changed_at, ApplicationStatusHistory.id)
    ).all()
    return [
        {
            "id": event.id,
            "application_id": event.application_id,
            "previous_status": event.previous_status,
            "new_status": event.new_status,
            "changed_by": event.changed_by,
            "changed_by_name": name,
            "notes": event.notes,
            "changed_at": event.changed_at,
        }
        for event, name in rows
    ]


def job_applications_page(db: Session, workspace_id: int, job_id: int, *, status_filter: str | None, skip: int, limit: int) -> dict:
    job_exists = db.scalar(select(Job.id).where(Job.id == job_id, Job.workspace_id == workspace_id))
    if job_exists is None:
        raise HTTPException(status_code=404, detail="Job not found")
    predicates = [Application.workspace_id == workspace_id, Application.job_id == job_id]
    if status_filter is not None:
        if status_filter not in APPLICATION_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid application status")
        predicates.append(Application.status == status_filter)
    total = db.scalar(select(func.count(Application.id)).where(*predicates)) or 0
    rows = db.scalars(
        select(Application)
        .where(*predicates)
        .options(
            selectinload(Application.screening_result),
            selectinload(Application.status_history),
            selectinload(Application.candidate).selectinload(Candidate.skills).joinedload(CandidateSkill.skill),
        )
        .order_by(Application.current_screening_score.desc().nullslast(), Application.created_at, Application.id)
        .offset(skip)
        .limit(limit)
    ).all()
    return {"items": [application_payload(row) for row in rows], "total": total, "skip": skip, "limit": limit}
