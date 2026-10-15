from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from backend.app.schemas.application import ApplicationStatus
from backend.app.schemas.common import OutputSchema
from backend.app.schemas.screening import RankedApplicationRead


class AnalyticsFilters(OutputSchema):
    date_from: date | None = Field(description="Inclusive UTC date applied to application/candidate creation time")
    date_to: date | None = Field(description="Inclusive UTC date applied to application/candidate creation time")
    job_id: int | None
    department: str | None
    job_status: Literal["open", "closed"] | None


class StatusCounts(OutputSchema):
    pending: int = 0
    under_review: int = 0
    shortlisted: int = 0
    rejected: int = 0


class StatusShare(OutputSchema):
    status: ApplicationStatus
    count: int
    percentage: Decimal = Field(description="Share of total_applications, 0-100, 2 decimals; 0 when there are no applications")


class ScoreCoverage(OutputSchema):
    application_count: int
    scored_count: int = Field(description="Applications with a stored screening result")
    complete_count: int = Field(description="Scored with complete candidate evidence")
    incomplete_count: int = Field(description="Scored, but some candidate evidence was missing; the score is a lower bound")
    stale_count: int = Field(description="Scored against older data or an older scoring version")
    unscored_count: int
    average_score: Decimal | None = Field(description="Mean over all scored applications (incomplete included); null when none are scored")
    average_complete_score: Decimal | None = Field(description="Mean over complete assessments only; null when there are none")


class JobScoreSummary(ScoreCoverage):
    job_id: int
    title: str
    department: str | None
    job_status: Literal["open", "closed"]


class DashboardSummary(OutputSchema):
    generated_at: datetime
    filters: AnalyticsFilters
    total_candidates: int = Field(description="Candidate records created in range (one per workspace email)")
    active_job_openings: int = Field(description="Jobs currently open (department filter applies, date filter does not)")
    total_applications: int = Field(description="Candidate-job applications created in range; a candidate applying to 3 jobs counts 3")
    unique_applicants: int = Field(description="Distinct candidates with at least one application in range")
    application_statuses: StatusCounts
    status_distribution: list[StatusShare]
    overall_scores: ScoreCoverage
    average_scores_by_job: list[JobScoreSummary]


class TopApplicantsRead(OutputSchema):
    job_id: int
    job_title: str
    job_status: Literal["open", "closed"]
    total_applicants: int
    items: list[RankedApplicationRead]
    ordering: str
    decision_notice: str


class ActivityItem(OutputSchema):
    id: int
    action: str
    category: Literal["candidate", "job", "application", "screening"]
    description: str
    actor_id: int | None
    actor_name: str | None
    resource_type: str
    resource_id: int | None
    candidate_name: str | None = Field(description="Current name of the related candidate, if it still exists")
    job_title: str | None = Field(description="Current title of the related job, if it still exists")
    created_at: datetime


class ActivityFeed(OutputSchema):
    items: list[ActivityItem]
    total: int
    limit: int


class SkillGap(OutputSchema):
    skill: str
    jobs_requiring: int = Field(description="Jobs in scope that list the skill as required")
    evaluated_applications: int = Field(description="Applications to those jobs whose candidate has skill data")
    missing_count: int
    missing_rate: Decimal = Field(description="missing_count / evaluated_applications * 100, 2 decimals")


class SkillGapSummary(OutputSchema):
    filters: AnalyticsFilters
    min_applications: int
    sufficient_data: bool
    message: str
    excluded_without_skill_data: int = Field(description="Applications skipped because the candidate has no skills recorded (unknown, not missing)")
    items: list[SkillGap]
