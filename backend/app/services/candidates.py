from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from fastapi import HTTPException
from backend.app.models.application import APPLICATION_STATUSES, Application
from backend.app.models.candidate import Candidate, CandidateEducation, CandidateResume, CandidateSkill
from backend.app.models.skill import Skill
from backend.app.models.user import User
from backend.app.schemas.candidate import CandidateCreate, CandidateUpdate
from backend.app.services.audit import record_audit
from backend.app.services.resumes import resume_payload
from backend.app.services.screening import rescore_active_applications, screening_result_payload
from backend.app.services.skill_catalog import get_or_create_skill
from backend.app.screening.normalization import normalize_items


def like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def candidate_payload(candidate: Candidate) -> dict:
    return {
        "id": candidate.id,
        "workspace_id": candidate.workspace_id,
        "full_name": candidate.full_name,
        "email": candidate.email,
        "phone": candidate.phone,
        "total_experience": candidate.total_experience,
        "technical_skills": [link.skill.display_name for link in candidate.skills],
        "education": [
            {"id": item.id, "institution": item.institution, "degree": item.degree, "field_of_study": item.field_of_study, "graduation_year": item.graduation_year}
            for item in candidate.education
        ],
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
    }


def get_candidate(db: Session, workspace_id: int, candidate_id: int) -> Candidate:
    candidate = db.scalar(
        select(Candidate)
        .options(selectinload(Candidate.skills).joinedload(CandidateSkill.skill), selectinload(Candidate.education))
        .where(Candidate.id == candidate_id, Candidate.workspace_id == workspace_id)
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def get_candidate_profile(db: Session, workspace_id: int, candidate_id: int) -> Candidate:
    candidate = db.scalar(
        select(Candidate)
        .options(
            selectinload(Candidate.skills).joinedload(CandidateSkill.skill),
            selectinload(Candidate.education),
            selectinload(Candidate.resume).selectinload(CandidateResume.file),
            selectinload(Candidate.applications).selectinload(Application.job),
            selectinload(Candidate.applications).selectinload(Application.screening_result),
            selectinload(Candidate.applications).selectinload(Application.status_history),
        )
        .where(Candidate.id == candidate_id, Candidate.workspace_id == workspace_id)
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def candidate_profile_payload(candidate: Candidate) -> dict:
    payload = candidate_payload(candidate)
    payload["resume"] = resume_payload(candidate.resume)
    payload["applications"] = []
    for application in sorted(candidate.applications, key=lambda item: (item.created_at, item.id)):
        payload["applications"].append({
            "id": application.id,
            "job_id": application.job_id,
            "job_title": application.job.title,
            "job_status": application.job.status,
            "status": application.status,
            "current_screening_score": application.current_screening_score,
            "decision_notes": application.decision_notes,
            "screening_result": screening_result_payload(application.screening_result),
            "status_history": [
                {"previous_status": event.previous_status, "new_status": event.new_status, "changed_by": event.changed_by, "notes": event.notes, "changed_at": event.changed_at}
                for event in sorted(application.status_history, key=lambda event: (event.changed_at, event.id))
            ],
            "created_at": application.created_at,
        })
    return payload


def list_candidates(db: Session, workspace_id: int, *, q: str | None, skill: str | None, min_experience, max_experience, status_filter: str | None, job_id: int | None = None, skip: int, limit: int):
    if min_experience is not None and max_experience is not None and min_experience > max_experience:
        raise HTTPException(status_code=422, detail="min_experience cannot exceed max_experience")
    predicates = [Candidate.workspace_id == workspace_id]
    query_text = q.strip().lower() if q else ""
    if query_text:
        pattern = like_pattern(query_text)
        predicates.append(
            or_(
                func.lower(Candidate.full_name).like(pattern, escape="\\"),
                func.lower(Candidate.email).like(pattern, escape="\\"),
                Candidate.skills.any(CandidateSkill.skill.has(func.lower(Skill.normalized_name).like(pattern, escape="\\"))),
            )
        )
    if skill and skill.strip():
        normalized_items = normalize_items([skill])
        if normalized_items:
            normalized = next(iter(normalized_items))
            predicates.append(Candidate.skills.any(CandidateSkill.skill.has(Skill.normalized_name == normalized)))
    if min_experience is not None:
        predicates.append(Candidate.total_experience >= min_experience)
    if max_experience is not None:
        predicates.append(Candidate.total_experience <= max_experience)
    if status_filter is not None and status_filter not in APPLICATION_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid application status")
    if status_filter is not None or job_id is not None:
        # Status and job filters apply to the same application, e.g. "Shortlisted for job 3".
        application_predicates = [Application.workspace_id == workspace_id]
        if status_filter is not None:
            application_predicates.append(Application.status == status_filter)
        if job_id is not None:
            application_predicates.append(Application.job_id == job_id)
        predicates.append(Candidate.applications.any(and_(*application_predicates)))
    total = db.scalar(select(func.count(Candidate.id)).where(*predicates)) or 0
    if total == 0 or skip >= total:
        return [], total
    rows = db.scalars(
        select(Candidate).where(*predicates)
        .options(selectinload(Candidate.skills).joinedload(CandidateSkill.skill), selectinload(Candidate.education))
        .order_by(Candidate.created_at.desc(), Candidate.id.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return [candidate_payload(row) for row in rows], total


def _replace_candidate_details(db: Session, candidate: Candidate, payload: CandidateCreate | CandidateUpdate) -> None:
    candidate.full_name = payload.full_name
    candidate.email = payload.email.lower()
    candidate.phone = payload.phone
    candidate.total_experience = payload.total_experience
    candidate.skills.clear()
    candidate.education.clear()
    db.flush()
    for name in payload.technical_skills:
        skill = get_or_create_skill(db, name)
        candidate.skills.append(CandidateSkill(workspace_id=candidate.workspace_id, skill=skill))
    for item in payload.education:
        candidate.education.append(
            CandidateEducation(
                workspace_id=candidate.workspace_id,
                institution=item.institution,
                degree=item.degree,
                field_of_study=item.field_of_study,
                graduation_year=item.graduation_year,
            )
        )


def create_candidate(db: Session, workspace_id: int, actor: User, payload: CandidateCreate) -> Candidate:
    if db.scalar(select(Candidate.id).where(Candidate.workspace_id == workspace_id, func.lower(Candidate.email) == payload.email.lower())):
        raise HTTPException(status_code=409, detail="Candidate email already exists in this workspace")
    candidate = Candidate(workspace_id=workspace_id, full_name=payload.full_name, email=payload.email.lower())
    db.add(candidate)
    db.flush()
    _replace_candidate_details(db, candidate, payload)
    record_audit(db, workspace_id=workspace_id, actor=actor, action="candidate.create", resource_type="candidate", resource_id=candidate.id)
    return candidate


def update_candidate(db: Session, workspace_id: int, actor: User, candidate: Candidate, payload: CandidateUpdate) -> Candidate:
    if payload.email.lower() != candidate.email.lower() and db.scalar(
        select(Candidate.id).where(
            Candidate.workspace_id == workspace_id,
            func.lower(Candidate.email) == payload.email.lower(),
            Candidate.id != candidate.id,
        )
    ):
        raise HTTPException(status_code=409, detail="Candidate email already exists in this workspace")
    _replace_candidate_details(db, candidate, payload)
    db.flush()
    rescore_active_applications(db, workspace_id, actor, candidate_id=candidate.id, reason="candidate_profile_changed")
    record_audit(db, workspace_id=workspace_id, actor=actor, action="candidate.update", resource_type="candidate", resource_id=candidate.id)
    return candidate


def delete_candidate(db: Session, workspace_id: int, actor: User, candidate: Candidate) -> None:
    record_audit(db, workspace_id=workspace_id, actor=actor, action="candidate.delete", resource_type="candidate", resource_id=candidate.id)
    db.delete(candidate)


def remove_candidate_resume(db: Session, workspace_id: int, actor: User, candidate: Candidate) -> None:
    if candidate.resume is None:
        return
    db.delete(candidate.resume)
    record_audit(db, workspace_id=workspace_id, actor=actor, action="candidate.resume_delete", resource_type="candidate", resource_id=candidate.id)
