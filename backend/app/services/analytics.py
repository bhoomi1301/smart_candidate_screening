"""Workspace-scoped dashboard analytics computed with SQL aggregates.

Every query filters on the caller's workspace_id, and every join also matches workspace_id,
so no row from another workspace can contribute to a count or appear in a label.
See README "Analytics" for metric definitions.
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import and_, case, exists, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from backend.app.models.application import APPLICATION_STATUSES, Application, ScreeningResult
from backend.app.models.audit import AuditLog
from backend.app.models.candidate import Candidate, CandidateSkill
from backend.app.models.job import Job, JobSkill
from backend.app.models.skill import Skill
from backend.app.models.user import User
from backend.app.screening.engine import SCORING_VERSION
from backend.app.services.screening import job_rankings

_STATUS_KEY = {"Pending": "pending", "Under Review": "under_review", "Shortlisted": "shortlisted", "Rejected": "rejected"}
ACTIVITY_CATEGORIES = ("candidate", "job", "application", "screening")


@dataclass(frozen=True)
class AnalyticsFilter:
    date_from: date | None = None
    date_to: date | None = None
    job_id: int | None = None
    department: str | None = None
    job_status: str | None = None

    def __post_init__(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise HTTPException(status_code=422, detail="date_from cannot be after date_to")

    def echo(self) -> dict:
        return asdict(self)

    def created_between(self, column) -> list:
        """Inclusive UTC date range on a timestamp column."""
        predicates = []
        if self.date_from:
            predicates.append(column >= datetime.combine(self.date_from, time.min, tzinfo=timezone.utc))
        if self.date_to:
            predicates.append(column < datetime.combine(self.date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))
        return predicates

    def job_predicates(self, workspace_id: int) -> list:
        predicates = [Job.workspace_id == workspace_id]
        if self.job_id is not None:
            predicates.append(Job.id == self.job_id)
        if self.department:
            predicates.append(func.lower(Job.department) == self.department.strip().lower())
        if self.job_status:
            predicates.append(Job.status == self.job_status)
        return predicates


def _round(value) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def require_job(db: Session, workspace_id: int, job_id: int) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.workspace_id == workspace_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _application_join(workspace_id: int, filters: AnalyticsFilter):
    """Join condition from Job to its applications in range (kept in ON so jobs without applications survive)."""
    return and_(Application.job_id == Job.id, Application.workspace_id == workspace_id, *filters.created_between(Application.created_at))


def _score_columns():
    scored = ScreeningResult.application_id.is_not(None)
    complete = and_(scored, ScreeningResult.assessment_status == "complete")
    stale = and_(scored, or_(ScreeningResult.is_stale.is_(True), ScreeningResult.scoring_version != SCORING_VERSION))
    return (
        func.count(Application.id),
        func.count(ScreeningResult.application_id),
        func.coalesce(func.sum(case((complete, 1), else_=0)), 0),
        func.coalesce(func.sum(case((and_(scored, ScreeningResult.assessment_status == "incomplete"), 1), else_=0)), 0),
        func.coalesce(func.sum(case((stale, 1), else_=0)), 0),
        # Sums, not SQL averages: division and half-up rounding happen in Decimal so SQLite and PostgreSQL agree.
        func.sum(ScreeningResult.score),
        func.sum(case((complete, ScreeningResult.score))),
    )


def _coverage(row) -> dict:
    applications, scored, complete, incomplete, stale, score_sum, complete_sum = row
    complete, incomplete, stale = int(complete), int(incomplete), int(stale)
    return {
        "application_count": applications,
        "scored_count": scored,
        "complete_count": complete,
        "incomplete_count": incomplete,
        "stale_count": stale,
        "unscored_count": applications - scored,
        "average_score": _round(Decimal(str(score_sum)) / scored) if scored else None,
        "average_complete_score": _round(Decimal(str(complete_sum)) / complete) if complete else None,
    }


def dashboard_summary(db: Session, workspace_id: int, filters: AnalyticsFilter) -> dict:
    if filters.job_id is not None:
        require_job(db, workspace_id, filters.job_id)
    job_predicates = filters.job_predicates(workspace_id)
    total_candidates = db.scalar(
        select(func.count(Candidate.id)).where(Candidate.workspace_id == workspace_id, *filters.created_between(Candidate.created_at))
    ) or 0
    active_jobs = db.scalar(select(func.count(Job.id)).where(*job_predicates, Job.status == "open")) or 0

    in_scope = select(Application).join(Job, and_(Job.id == Application.job_id, Job.workspace_id == Application.workspace_id)).where(
        Application.workspace_id == workspace_id, *job_predicates, *filters.created_between(Application.created_at)
    ).subquery()
    status_rows = db.execute(select(in_scope.c.status, func.count()).group_by(in_scope.c.status)).all()
    unique_applicants = db.scalar(select(func.count(func.distinct(in_scope.c.candidate_id)))) or 0
    counts = {key: 0 for key in _STATUS_KEY.values()}
    for status_name, count in status_rows:
        counts[_STATUS_KEY[status_name]] = count
    total_applications = sum(counts.values())
    distribution = [
        {
            "status": status_name,
            "count": counts[_STATUS_KEY[status_name]],
            "percentage": _round(Decimal(counts[_STATUS_KEY[status_name]]) * 100 / total_applications) if total_applications else Decimal("0.00"),
        }
        for status_name in APPLICATION_STATUSES
    ]

    joined = (
        select(Job.id, Job.title, Job.department, Job.status, *_score_columns())
        .select_from(Job)
        .outerjoin(Application, _application_join(workspace_id, filters))
        .outerjoin(ScreeningResult, and_(ScreeningResult.application_id == Application.id, ScreeningResult.workspace_id == workspace_id))
        .where(*job_predicates)
    )
    by_job = [
        {"job_id": row[0], "title": row[1], "department": row[2], "job_status": row[3], **_coverage(row[4:])}
        for row in db.execute(joined.group_by(Job.id, Job.title, Job.department, Job.status).order_by(Job.title, Job.id))
    ]
    overall = db.execute(
        select(*_score_columns())
        .select_from(Job)
        .join(Application, _application_join(workspace_id, filters))
        .outerjoin(ScreeningResult, and_(ScreeningResult.application_id == Application.id, ScreeningResult.workspace_id == workspace_id))
        .where(*job_predicates)
    ).one()
    return {
        "generated_at": datetime.now(timezone.utc),
        "filters": filters.echo(),
        "total_candidates": total_candidates,
        "active_job_openings": active_jobs,
        "total_applications": total_applications,
        "unique_applicants": unique_applicants,
        "application_statuses": counts,
        "status_distribution": distribution,
        "overall_scores": _coverage(overall),
        "average_scores_by_job": by_job,
    }


def top_applicants(db: Session, workspace_id: int, job_id: int, *, eligibility: str | None, limit: int) -> dict:
    job = require_job(db, workspace_id, job_id)
    page = job_rankings(db, workspace_id, job_id, eligibility=eligibility, skip=0, limit=limit)
    return {
        "job_id": job.id,
        "job_title": job.title,
        "job_status": job.status,
        "total_applicants": page["total"],
        "items": page["items"],
        "ordering": page["ordering"],
        "decision_notice": page["decision_notice"],
    }


def _describe(action: str, metadata: dict) -> str:
    metadata = metadata or {}
    if action in {"application.decision", "job.status"}:
        return f"Changed status from {metadata.get('previous_status')} to {metadata.get('new_status') or metadata.get('status')}"
    if action == "screening.evaluate":
        trigger = "manual refresh" if metadata.get("trigger") == "manual_refresh" else "new application"
        return f"Screened application ({trigger}): score {metadata.get('score')}, {metadata.get('eligibility')}"
    if action == "screening.recalculate":
        refreshed = len(metadata.get("refreshed_application_ids") or [])
        stale = len(metadata.get("stale_application_ids") or [])
        trigger = str(metadata.get("trigger", "")).replace("_", " ")
        return f"Recalculated {refreshed} screening result(s), marked {stale} stale ({trigger})"
    return {
        "candidate.create": "Added candidate",
        "candidate.update": "Updated candidate profile",
        "candidate.delete": "Deleted candidate",
        "candidate.resume_upload": "Uploaded a resume",
        "candidate.resume_delete": "Removed resume",
        "candidate.resume_download": "Downloaded a resume",
        "job.create": "Created job opening",
        "job.update": "Updated job criteria",
        "job.delete": "Deleted job opening",
        "application.create": "Applied candidate to job",
        "application.note": "Added a review note",
    }.get(action, action)


def recent_activity(db: Session, workspace_id: int, *, since: datetime | None, category: str | None, limit: int) -> dict:
    prefixes = [category] if category else list(ACTIVITY_CATEGORIES)
    predicates = [AuditLog.workspace_id == workspace_id, or_(*(AuditLog.action.startswith(f"{prefix}.") for prefix in prefixes))]
    if since is not None:
        predicates.append(AuditLog.created_at >= since)
    total = db.scalar(select(func.count(AuditLog.id)).where(*predicates)) or 0
    related_application = aliased(Application)
    related_candidate = aliased(Candidate)
    related_job = aliased(Job)
    is_application = AuditLog.resource_type == "application"
    rows = db.execute(
        select(AuditLog, User.full_name, related_candidate.full_name, related_job.title)
        .outerjoin(User, and_(User.id == AuditLog.actor_id, User.workspace_id == workspace_id))
        .outerjoin(related_application, and_(is_application, related_application.id == AuditLog.resource_id, related_application.workspace_id == workspace_id))
        .outerjoin(related_candidate, and_(
            related_candidate.workspace_id == workspace_id,
            related_candidate.id == case((AuditLog.resource_type == "candidate", AuditLog.resource_id), else_=related_application.candidate_id),
        ))
        .outerjoin(related_job, and_(
            related_job.workspace_id == workspace_id,
            related_job.id == case((AuditLog.resource_type == "job", AuditLog.resource_id), else_=related_application.job_id),
        ))
        .where(*predicates)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    ).all() if total else []
    return {
        "items": [
            {
                "id": log.id,
                "action": log.action,
                "category": log.action.split(".", 1)[0],
                "description": _describe(log.action, log.metadata_safe),
                "actor_id": log.actor_id,
                "actor_name": actor_name,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "candidate_name": candidate_name,
                "job_title": job_title,
                "created_at": log.created_at,
            }
            for log, actor_name, candidate_name, job_title in rows
        ],
        "total": total,
        "limit": limit,
    }


def skill_gaps(db: Session, workspace_id: int, filters: AnalyticsFilter, *, min_applications: int, limit: int) -> dict:
    """Required skills most often missing among applicants whose candidates have skill data."""
    if filters.job_id is not None:
        require_job(db, workspace_id, filters.job_id)
    has_skill_data = exists().where(CandidateSkill.workspace_id == workspace_id, CandidateSkill.candidate_id == Application.candidate_id)
    has_required_skill = exists().where(
        CandidateSkill.workspace_id == workspace_id,
        CandidateSkill.candidate_id == Application.candidate_id,
        CandidateSkill.skill_id == JobSkill.skill_id,
    )
    scope = [*filters.job_predicates(workspace_id), *filters.created_between(Application.created_at)]
    evaluated = func.count(Application.id)
    missing = func.coalesce(func.sum(case((~has_required_skill, 1), else_=0)), literal(0))
    rows = db.execute(
        select(Skill.display_name, func.count(func.distinct(JobSkill.job_id)), evaluated, missing)
        .select_from(JobSkill)
        .join(Skill, Skill.id == JobSkill.skill_id)
        .join(Job, and_(Job.id == JobSkill.job_id, Job.workspace_id == workspace_id))
        .join(Application, and_(Application.job_id == JobSkill.job_id, Application.workspace_id == workspace_id))
        .where(JobSkill.workspace_id == workspace_id, JobSkill.category == "required", has_skill_data, *scope)
        .group_by(Skill.id, Skill.display_name)
        .having(evaluated >= min_applications)
        .order_by(missing.desc(), evaluated.asc(), Skill.display_name)
    ).all()
    excluded = db.scalar(
        select(func.count(Application.id))
        .join(Job, and_(Job.id == Application.job_id, Job.workspace_id == workspace_id))
        .where(Application.workspace_id == workspace_id, ~has_skill_data, *scope)
    ) or 0
    items = [
        {"skill": name, "jobs_requiring": jobs, "evaluated_applications": count, "missing_count": int(gap), "missing_rate": _round(Decimal(int(gap)) * 100 / count)}
        for name, jobs, count, gap in rows
        if gap
    ][:limit]
    sufficient = bool(rows)
    if not sufficient:
        message = f"Not enough data: no required skill has at least {min_applications} evaluated applications."
    elif not items:
        message = "No required skills are missing among evaluated applications."
    else:
        message = f"Showing the {len(items)} most frequently missing required skill(s)."
    return {
        "filters": filters.echo(),
        "min_applications": min_applications,
        "sufficient_data": sufficient,
        "message": message,
        "excluded_without_skill_data": excluded,
        "items": items,
    }
