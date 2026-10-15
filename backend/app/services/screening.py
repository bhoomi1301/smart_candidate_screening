from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models.application import Application, ScreeningResult
from backend.app.models.candidate import Candidate, CandidateSkill
from backend.app.models.job import Job, JobSkill
from backend.app.models.user import User
from backend.app.screening.engine import DECISION_NOTICE, SCORING_VERSION, CandidateEvidence, JobCriteria, QualificationCriterion, evaluate
from backend.app.services.audit import record_audit

# Rejected is terminal: its score snapshot is kept as the record the decision was based on.
RESCORABLE_STATUSES = ("Pending", "Under Review", "Shortlisted")
RANKING_ORDER = "score desc (unscored last), then application created_at asc, then application id asc"


def evaluation_options():
    return (
        selectinload(Application.candidate).selectinload(Candidate.skills).joinedload(CandidateSkill.skill),
        selectinload(Application.candidate).selectinload(Candidate.education),
        selectinload(Application.job).selectinload(Job.skills).joinedload(JobSkill.skill),
        selectinload(Application.job).selectinload(Job.qualifications),
        selectinload(Application.screening_result),
    )


def candidate_evidence(candidate: Candidate) -> CandidateEvidence:
    return CandidateEvidence(
        skills=[link.skill.display_name for link in candidate.skills],
        experience_years=candidate.total_experience,
        education=[" ".join(filter(None, (item.degree, item.field_of_study))) for item in candidate.education],
    )


def job_criteria(job: Job) -> JobCriteria:
    skills: dict[str, list[str]] = {"required": [], "preferred": []}
    weights: dict[str, dict[str, Decimal]] = {"required": {}, "preferred": {}}
    for link in job.skills:
        skills[link.category].append(link.skill.display_name)
        if link.weight is not None:
            weights[link.category][link.skill.display_name] = link.weight
    return JobCriteria(
        required_skills=skills["required"],
        preferred_skills=skills["preferred"],
        required_skill_weights=weights["required"],
        preferred_skill_weights=weights["preferred"],
        minimum_experience=job.minimum_experience,
        qualifications=[QualificationCriterion(item.name, item.is_mandatory, item.weight) for item in job.qualifications],
        weights={key: Decimal(str(value)) for key, value in job.criterion_weights.items()},
    )


def evaluate_application(db: Session, application: Application) -> ScreeningResult:
    assessment = evaluate(candidate_evidence(application.candidate), job_criteria(application.job))
    screening = application.screening_result
    if screening is None:
        screening = ScreeningResult(application_id=application.id, workspace_id=application.workspace_id)
        application.screening_result = screening
    screening.score = assessment.score
    screening.score_breakdown = assessment.breakdown
    screening.matched_skills = assessment.matched_skills
    screening.missing_mandatory_skills = assessment.missing_mandatory_skills
    screening.eligibility = assessment.eligibility
    screening.assessment_status = assessment.assessment_status
    screening.scoring_version = SCORING_VERSION
    screening.evaluated_at = datetime.now(timezone.utc)
    screening.is_stale = False
    screening.stale_reason = None
    application.current_screening_score = assessment.score
    db.add(screening)
    return screening


def rescore_active_applications(db: Session, workspace_id: int, actor: User, *, candidate_id: int | None = None, job_id: int | None = None, reason: str = "criteria_changed") -> int:
    """Recalculate non-rejected applications affected by a change; mark rejected snapshots stale instead."""
    predicates = [Application.workspace_id == workspace_id]
    if candidate_id is not None:
        predicates.append(Application.candidate_id == candidate_id)
    if job_id is not None:
        predicates.append(Application.job_id == job_id)
    applications = db.scalars(select(Application).options(*evaluation_options()).where(*predicates)).all()
    refreshed: list[int] = []
    marked_stale: list[int] = []
    for application in applications:
        if application.status in RESCORABLE_STATUSES:
            evaluate_application(db, application)
            refreshed.append(application.id)
        elif application.screening_result is not None:
            application.screening_result.is_stale = True
            application.screening_result.stale_reason = reason
            marked_stale.append(application.id)
    if refreshed or marked_stale:
        resource_type, resource_id = ("candidate", candidate_id) if candidate_id is not None else ("job", job_id)
        record_audit(db, workspace_id=workspace_id, actor=actor, action="screening.recalculate", resource_type=resource_type, resource_id=resource_id, metadata={"trigger": reason, "refreshed_application_ids": refreshed, "stale_application_ids": marked_stale})
    return len(refreshed)


def is_stale(result: ScreeningResult) -> bool:
    return result.is_stale or result.scoring_version != SCORING_VERSION


def stale_reason(result: ScreeningResult) -> str | None:
    if result.is_stale:
        return result.stale_reason
    return "scoring_version_changed" if result.scoring_version != SCORING_VERSION else None


def screening_result_payload(result: ScreeningResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "score": result.score,
        "score_breakdown": result.score_breakdown,
        "matched_skills": result.matched_skills,
        "missing_mandatory_skills": result.missing_mandatory_skills,
        "eligibility": result.eligibility,
        "assessment_status": result.assessment_status,
        "evaluated_at": result.evaluated_at,
        "scoring_version": result.scoring_version,
        "is_stale": is_stale(result),
        "stale_reason": stale_reason(result),
    }


def _application_for_screening(db: Session, workspace_id: int, application_id: int, *, lock: bool = False) -> Application:
    query = select(Application).options(*evaluation_options()).where(Application.id == application_id, Application.workspace_id == workspace_id)
    if lock:
        # Serialize concurrent refreshes of one application (PostgreSQL row lock; no-op on SQLite).
        query = query.with_for_update(of=Application)
    application = db.scalar(query)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def screening_payload(application: Application) -> dict:
    result = application.screening_result
    if result is None:
        raise HTTPException(status_code=404, detail="Application has not been screened yet")
    return {
        "application_id": application.id,
        "job_id": application.job_id,
        "candidate_id": application.candidate_id,
        "application_status": application.status,
        **screening_result_payload(result),
        "decision_notice": DECISION_NOTICE,
    }


def get_screening(db: Session, workspace_id: int, application_id: int) -> dict:
    return screening_payload(_application_for_screening(db, workspace_id, application_id))


def refresh_application_screening(db: Session, workspace_id: int, actor: User, application_id: int) -> Application:
    application = _application_for_screening(db, workspace_id, application_id, lock=True)
    evaluate_application(db, application)
    record_audit(db, workspace_id=workspace_id, actor=actor, action="screening.evaluate", resource_type="application", resource_id=application.id, metadata={"score": str(application.current_screening_score), "eligibility": application.screening_result.eligibility, "trigger": "manual_refresh"})
    return application


def _require_job(db: Session, workspace_id: int, job_id: int) -> None:
    if db.scalar(select(Job.id).where(Job.id == job_id, Job.workspace_id == workspace_id)) is None:
        raise HTTPException(status_code=404, detail="Job not found")


def refresh_job_screening(db: Session, workspace_id: int, actor: User, job_id: int, *, include_rejected: bool) -> int:
    _require_job(db, workspace_id, job_id)
    predicates = [Application.workspace_id == workspace_id, Application.job_id == job_id]
    if not include_rejected:
        predicates.append(Application.status.in_(RESCORABLE_STATUSES))
    applications = db.scalars(select(Application).options(*evaluation_options()).where(*predicates).with_for_update(of=Application)).all()
    for application in applications:
        evaluate_application(db, application)
    record_audit(db, workspace_id=workspace_id, actor=actor, action="screening.recalculate", resource_type="job", resource_id=job_id, metadata={"trigger": "manual_refresh", "refreshed_application_ids": [item.id for item in applications], "include_rejected": include_rejected})
    return len(applications)


def job_rankings(db: Session, workspace_id: int, job_id: int, *, eligibility: str | None, skip: int, limit: int) -> dict:
    _require_job(db, workspace_id, job_id)
    predicates = [Application.workspace_id == workspace_id, Application.job_id == job_id]
    if eligibility is not None:
        predicates.append(Application.screening_result.has(ScreeningResult.eligibility == eligibility))
    total = db.scalar(select(func.count(Application.id)).where(*predicates)) or 0
    page = {"job_id": job_id, "items": [], "total": total, "skip": skip, "limit": limit, "ordering": RANKING_ORDER, "decision_notice": DECISION_NOTICE}
    if total == 0 or skip >= total:
        return page
    rows = db.scalars(
        select(Application)
        .where(*predicates)
        .options(
            selectinload(Application.screening_result),
            selectinload(Application.candidate).selectinload(Candidate.skills).joinedload(CandidateSkill.skill),
        )
        .order_by(Application.current_screening_score.desc().nullslast(), Application.created_at.asc(), Application.id.asc())
        .offset(skip)
        .limit(limit)
    ).all()
    tied_scores = set(db.scalars(
        select(Application.current_screening_score)
        .where(*predicates, Application.current_screening_score.is_not(None))
        .group_by(Application.current_screening_score)
        .having(func.count(Application.id) > 1)
    ))
    for position, application in enumerate(rows, start=skip + 1):
        result = application.screening_result
        candidate = application.candidate
        page["items"].append({
            "rank": position,
            "application_id": application.id,
            "application_status": application.status,
            "applied_at": application.created_at,
            "score": application.current_screening_score,
            "score_tied": application.current_screening_score in tied_scores,
            "eligibility": None if result is None else result.eligibility,
            "assessment_status": None if result is None else result.assessment_status,
            "missing_mandatory_skills": [] if result is None else result.missing_mandatory_skills,
            "is_stale": result is None or is_stale(result),
            "evaluated_at": None if result is None else result.evaluated_at,
            "candidate": {
                "id": candidate.id,
                "full_name": candidate.full_name,
                "email": candidate.email,
                "total_experience": candidate.total_experience,
                "technical_skills": [link.skill.display_name for link in candidate.skills],
            },
        })
    return page
