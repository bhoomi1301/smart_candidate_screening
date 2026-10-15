from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.models.types import JSON_DOCUMENT


APPLICATION_STATUSES = ("Pending", "Under Review", "Shortlisted", "Rejected")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        ForeignKeyConstraint(["candidate_id", "workspace_id"], ["candidates.id", "candidates.workspace_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["job_id", "workspace_id"], ["jobs.id", "jobs.workspace_id"], ondelete="RESTRICT"),
        UniqueConstraint("candidate_id", "job_id", name="uq_application_candidate_job"),
        UniqueConstraint("id", "workspace_id", name="uq_applications_id_workspace"),
        CheckConstraint("status IN ('Pending', 'Under Review', 'Shortlisted', 'Rejected')", name="ck_applications_status"),
        CheckConstraint("current_screening_score IS NULL OR (current_screening_score >= 0 AND current_screening_score <= 100)", name="ck_application_score_range"),
        Index("ix_applications_workspace_job_status", "workspace_id", "job_id", "status"),
        Index("ix_applications_workspace_score", "workspace_id", "current_screening_score"),
        Index("ix_applications_job_ranking", "workspace_id", "job_id", "current_screening_score", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Pending")
    current_screening_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    decision_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    candidate: Mapped["Candidate"] = relationship(back_populates="applications", foreign_keys=[candidate_id])
    job: Mapped["Job"] = relationship(back_populates="applications", foreign_keys=[job_id])
    screening_result: Mapped["ScreeningResult | None"] = relationship(back_populates="application", cascade="all, delete-orphan", uselist=False)
    status_history: Mapped[list["ApplicationStatusHistory"]] = relationship(back_populates="application", cascade="all, delete-orphan")


class ScreeningResult(Base):
    __tablename__ = "screening_results"
    __table_args__ = (
        ForeignKeyConstraint(["application_id", "workspace_id"], ["applications.id", "applications.workspace_id"], ondelete="CASCADE"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_screening_result_score_range"),
        CheckConstraint("eligibility IN ('eligible', 'not_eligible', 'undetermined')", name="ck_screening_result_eligibility"),
        CheckConstraint("assessment_status IN ('complete', 'incomplete')", name="ck_screening_result_assessment_status"),
        Index("ix_screening_results_workspace_evaluated", "workspace_id", "evaluated_at"),
    )

    application_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    score_breakdown: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    matched_skills: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    missing_mandatory_skills: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(40), nullable=False)
    eligibility: Mapped[str] = mapped_column(String(20), nullable=False, default="undetermined")
    assessment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="incomplete")
    # Set when candidate or job data changed after evaluation and the result was not recalculated.
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stale_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    application: Mapped[Application] = relationship(back_populates="screening_result")


class ApplicationStatusHistory(Base):
    __tablename__ = "application_status_history"
    __table_args__ = (
        ForeignKeyConstraint(["application_id", "workspace_id"], ["applications.id", "applications.workspace_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["changed_by", "workspace_id"], ["users.id", "users.workspace_id"], ondelete="RESTRICT"),
        CheckConstraint("previous_status IS NULL OR previous_status IN ('Pending', 'Under Review', 'Shortlisted', 'Rejected')", name="ck_status_history_previous"),
        CheckConstraint("new_status IN ('Pending', 'Under Review', 'Shortlisted', 'Rejected')", name="ck_status_history_new"),
        Index("ix_status_history_workspace_application_timestamp", "workspace_id", "application_id", "changed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, nullable=False)
    application_id: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    application: Mapped[Application] = relationship(back_populates="status_history")
