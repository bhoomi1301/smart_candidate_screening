from sqlalchemy import func, or_, select
from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

from backend.app.models.application import Application
from backend.app.models.job import Job, JobQualification, JobSkill
from backend.app.models.user import User
from backend.app.schemas.job import JobCreate, JobUpdate
from backend.app.services.audit import record_audit
from backend.app.services.candidates import like_pattern
from backend.app.services.screening import rescore_active_applications
from backend.app.services.skill_catalog import get_or_create_skill
from backend.app.screening.normalization import normalize_items


def job_payload(job: Job, application_count: int = 0) -> dict:
    skills = {"required": [], "preferred": []}
    skill_weights = {"required": {}, "preferred": {}}
    for link in job.skills:
        skills[link.category].append(link.skill.display_name)
        if link.weight is not None:
            skill_weights[link.category][link.skill.display_name] = link.weight
    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "title": job.title,
        "department": job.department,
        "description": job.description,
        "required_skills": sorted(skills["required"], key=str.casefold),
        "preferred_skills": sorted(skills["preferred"], key=str.casefold),
        "required_skill_weights": skill_weights["required"],
        "preferred_skill_weights": skill_weights["preferred"],
        "minimum_experience": job.minimum_experience,
        "qualifications": [
            {"id": item.id, "name": item.name, "is_mandatory": item.is_mandatory, "weight": item.weight}
            for item in job.qualifications
        ],
        "criterion_weights": job.criterion_weights,
        "status": job.status,
        "application_count": application_count,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def get_job(db: Session, workspace_id: int, job_id: int) -> Job:
    job = db.scalar(
        select(Job)
        .options(selectinload(Job.skills).joinedload(JobSkill.skill), selectinload(Job.qualifications))
        .where(Job.id == job_id, Job.workspace_id == workspace_id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def application_counts(db: Session, workspace_id: int, job_ids: list[int]) -> dict[int, int]:
    if not job_ids:
        return {}
    rows = db.execute(
        select(Application.job_id, func.count(Application.id))
        .where(Application.workspace_id == workspace_id, Application.job_id.in_(job_ids))
        .group_by(Application.job_id)
    ).all()
    return {job_id: count for job_id, count in rows}


def job_detail_payload(db: Session, job: Job) -> dict:
    return job_payload(job, application_counts(db, job.workspace_id, [job.id]).get(job.id, 0))


def list_jobs(db: Session, workspace_id: int, *, status_filter: str | None = None, q: str | None = None, department: str | None = None, skip: int = 0, limit: int = 25) -> tuple[list[dict], int]:
    predicates = [Job.workspace_id == workspace_id]
    if status_filter:
        predicates.append(Job.status == status_filter)
    query_text = q.strip().lower() if q else ""
    if query_text:
        pattern = like_pattern(query_text)
        predicates.append(or_(
            func.lower(Job.title).like(pattern, escape="\\"),
            func.lower(func.coalesce(Job.department, "")).like(pattern, escape="\\"),
        ))
    if department and department.strip():
        predicates.append(func.lower(Job.department) == department.strip().lower())
    total = db.scalar(select(func.count(Job.id)).where(*predicates)) or 0
    if total == 0 or skip >= total:
        return [], total
    rows = db.scalars(
        select(Job)
        .where(*predicates)
        .options(selectinload(Job.skills).joinedload(JobSkill.skill), selectinload(Job.qualifications))
        .order_by(Job.created_at.desc(), Job.id.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    counts = application_counts(db, workspace_id, [row.id for row in rows])
    return [job_payload(row, counts.get(row.id, 0)) for row in rows], total


def _replace_job_criteria(db: Session, job: Job, payload: JobCreate | JobUpdate) -> None:
    job.title = payload.title
    job.department = payload.department
    job.description = payload.description
    job.minimum_experience = payload.minimum_experience
    job.criterion_weights = {key: float(value) for key, value in payload.criterion_weights.model_dump().items()}
    job.skills.clear()
    job.qualifications.clear()
    db.flush()
    skill_weights = {
        "required": {next(iter(normalize_items([name]))): weight for name, weight in payload.required_skill_weights.items()},
        "preferred": {next(iter(normalize_items([name]))): weight for name, weight in payload.preferred_skill_weights.items()},
    }
    for category, names in (("required", payload.required_skills), ("preferred", payload.preferred_skills)):
        for name in names:
            skill = get_or_create_skill(db, name)
            normalized = next(iter(normalize_items([name])))
            weight = skill_weights[category].get(normalized)
            job.skills.append(JobSkill(workspace_id=job.workspace_id, skill=skill, category=category, weight=weight))
    for item in payload.qualifications:
        job.qualifications.append(
            JobQualification(
                workspace_id=job.workspace_id,
                name=item.name,
                is_mandatory=item.is_mandatory,
                weight=item.weight,
            )
        )


def create_job(db: Session, workspace_id: int, actor: User, payload: JobCreate) -> Job:
    job = Job(workspace_id=workspace_id, title=payload.title, criterion_weights={})
    db.add(job)
    db.flush()
    _replace_job_criteria(db, job, payload)
    record_audit(db, workspace_id=workspace_id, actor=actor, action="job.create", resource_type="job", resource_id=job.id)
    return job


def update_job(db: Session, workspace_id: int, actor: User, job: Job, payload: JobUpdate) -> Job:
    if job.status != "open":
        # Closed jobs keep the criteria their applications were screened against.
        raise HTTPException(status_code=409, detail="Reopen the job before changing its criteria")
    _replace_job_criteria(db, job, payload)
    db.flush()
    rescore_active_applications(db, workspace_id, actor, job_id=job.id, reason="job_criteria_changed")
    record_audit(db, workspace_id=workspace_id, actor=actor, action="job.update", resource_type="job", resource_id=job.id)
    return job


def set_job_status(db: Session, workspace_id: int, actor: User, job: Job, new_status: str) -> Job:
    if job.status == new_status:
        return job
    previous = job.status
    job.status = new_status
    record_audit(db, workspace_id=workspace_id, actor=actor, action="job.status", resource_type="job", resource_id=job.id, metadata={"previous_status": previous, "status": new_status})
    return job


def delete_job(db: Session, workspace_id: int, actor: User, job: Job) -> None:
    has_applications = db.scalar(select(Application.id).where(Application.workspace_id == workspace_id, Application.job_id == job.id).limit(1))
    if has_applications:
        raise HTTPException(status_code=409, detail="Close the job instead of deleting it after applications exist")
    record_audit(db, workspace_id=workspace_id, actor=actor, action="job.delete", resource_type="job", resource_id=job.id)
    db.delete(job)
