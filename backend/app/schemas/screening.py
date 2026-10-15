from datetime import datetime
from decimal import Decimal
from typing import Literal

from backend.app.schemas.application import ApplicationCandidateRead, ApplicationStatus
from backend.app.schemas.common import OutputSchema

Eligibility = Literal["eligible", "not_eligible", "undetermined"]
AssessmentStatus = Literal["complete", "incomplete"]


class ScreeningRead(OutputSchema):
    application_id: int
    job_id: int
    candidate_id: int
    application_status: ApplicationStatus
    score: Decimal
    eligibility: Eligibility
    assessment_status: AssessmentStatus
    matched_skills: list[str]
    missing_mandatory_skills: list[str]
    score_breakdown: dict
    scoring_version: str
    evaluated_at: datetime
    is_stale: bool
    stale_reason: str | None = None
    decision_notice: str


class JobScreeningRefreshRead(OutputSchema):
    job_id: int
    refreshed: int
    include_rejected: bool


class RankedApplicationRead(OutputSchema):
    rank: int
    application_id: int
    application_status: ApplicationStatus
    applied_at: datetime
    score: Decimal | None
    score_tied: bool
    eligibility: Eligibility | None
    assessment_status: AssessmentStatus | None
    missing_mandatory_skills: list[str]
    is_stale: bool
    evaluated_at: datetime | None
    candidate: ApplicationCandidateRead


class RankingPage(OutputSchema):
    job_id: int
    items: list[RankedApplicationRead]
    total: int
    skip: int
    limit: int
    ordering: str
    decision_notice: str
