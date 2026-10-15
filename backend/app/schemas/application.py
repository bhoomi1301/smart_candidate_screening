from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from backend.app.schemas.common import MAX_DB_INT, InputSchema, OutputSchema


ApplicationStatus = Literal["Pending", "Under Review", "Shortlisted", "Rejected"]
REJECTION_NOTE_MIN_LENGTH = 10


class ApplicationCreate(InputSchema):
    candidate_id: int = Field(gt=0, le=MAX_DB_INT)


class ApplicationDecision(InputSchema):
    """Move an application to a new status, or add a note without changing status (same status + notes)."""

    status: ApplicationStatus
    notes: str = Field(default="", max_length=5000, description=f"Required (at least {REJECTION_NOTE_MIN_LENGTH} characters) when rejecting")
    expected_status: ApplicationStatus | None = Field(
        default=None,
        description="Status the client last saw. If the application has changed since, the request fails with 409 instead of overwriting another reviewer's decision.",
    )

    @model_validator(mode="after")
    def rejection_requires_explanation(self):
        if self.status == "Rejected" and len(self.notes) < REJECTION_NOTE_MIN_LENGTH:
            raise ValueError(f"Rejecting an application requires an explanatory note of at least {REJECTION_NOTE_MIN_LENGTH} characters")
        return self


class WorkflowTransitionRead(OutputSchema):
    from_status: ApplicationStatus
    allowed: list[ApplicationStatus]


class WorkflowRead(OutputSchema):
    statuses: list[ApplicationStatus]
    initial_status: ApplicationStatus
    terminal_statuses: list[ApplicationStatus]
    transitions: list[WorkflowTransitionRead]
    rules: list[str]


class ScreeningResultRead(OutputSchema):
    score: Decimal
    score_breakdown: dict
    matched_skills: list[str]
    missing_mandatory_skills: list[str]
    eligibility: Literal["eligible", "not_eligible", "undetermined"]
    assessment_status: Literal["complete", "incomplete"]
    evaluated_at: datetime
    scoring_version: str
    is_stale: bool
    stale_reason: str | None = None


class ApplicationCandidateRead(OutputSchema):
    id: int
    full_name: str
    email: str
    total_experience: Decimal | None
    technical_skills: list[str]


class StatusHistoryRead(OutputSchema):
    previous_status: str | None
    new_status: str
    changed_by: int | None
    notes: str
    changed_at: datetime


class StatusHistoryEntryRead(StatusHistoryRead):
    id: int
    application_id: int
    changed_by_name: str | None


class ApplicationRead(OutputSchema):
    id: int
    workspace_id: int
    candidate_id: int
    job_id: int
    status: ApplicationStatus
    current_screening_score: Decimal | None
    decision_notes: str
    created_at: datetime
    updated_at: datetime
    screening_result: ScreeningResultRead | None = None
    status_history: list[StatusHistoryRead] = Field(default_factory=list)
    candidate: ApplicationCandidateRead


class JobApplicationPage(OutputSchema):
    items: list[ApplicationRead]
    total: int
    skip: int
    limit: int
