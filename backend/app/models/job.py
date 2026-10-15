from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.models.types import JSON_DOCUMENT


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_jobs_id_workspace"),
        CheckConstraint("status IN ('open', 'closed')", name="ck_jobs_status"),
        CheckConstraint("minimum_experience >= 0 AND minimum_experience <= 80", name="ck_jobs_experience_range"),
        Index("ix_jobs_workspace_status_created", "workspace_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    minimum_experience: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    criterion_weights: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    workspace: Mapped["Workspace"] = relationship(back_populates="jobs")
    skills: Mapped[list["JobSkill"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    qualifications: Mapped[list["JobQualification"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(back_populates="job", foreign_keys="Application.job_id", passive_deletes="all")


class JobSkill(Base):
    __tablename__ = "job_skills"
    __table_args__ = (
        ForeignKeyConstraint(["job_id", "workspace_id"], ["jobs.id", "jobs.workspace_id"], ondelete="CASCADE"),
        CheckConstraint("category IN ('required', 'preferred')", name="ck_job_skill_category"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="ck_job_skill_weight_nonnegative"),
        UniqueConstraint("job_id", "skill_id", "category", name="uq_job_skill_category"),
        Index("ix_job_skills_workspace_category", "workspace_id", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_id: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    skill: Mapped["Skill"] = relationship(back_populates="job_links")
    job: Mapped[Job] = relationship(back_populates="skills")


class JobQualification(Base):
    __tablename__ = "job_qualifications"
    __table_args__ = (
        ForeignKeyConstraint(["job_id", "workspace_id"], ["jobs.id", "jobs.workspace_id"], ondelete="CASCADE"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="ck_job_qualification_weight_nonnegative"),
        Index("ix_job_qualifications_workspace_job", "workspace_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(nullable=False, default=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    job: Mapped[Job] = relationship(back_populates="qualifications")
