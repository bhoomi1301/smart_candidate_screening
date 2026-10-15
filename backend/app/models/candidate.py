from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, LargeBinary, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_candidates_id_workspace"),
        Index("uq_candidates_workspace_email_lower", "workspace_id", func.lower(text("email")), unique=True),
        Index("ix_candidates_workspace_created", "workspace_id", "created_at"),
        CheckConstraint("total_experience IS NULL OR (total_experience >= 0 AND total_experience <= 80)", name="ck_candidates_experience_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    total_experience: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    workspace: Mapped["Workspace"] = relationship(back_populates="candidates")
    skills: Mapped[list["CandidateSkill"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    education: Mapped[list["CandidateEducation"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    resume: Mapped["CandidateResume | None"] = relationship(back_populates="candidate", cascade="all, delete-orphan", uselist=False)
    applications: Mapped[list["Application"]] = relationship(back_populates="candidate", foreign_keys="Application.candidate_id", cascade="all, delete-orphan", passive_deletes=True)


class CandidateSkill(Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (
        ForeignKeyConstraint(["candidate_id", "workspace_id"], ["candidates.id", "candidates.workspace_id"], ondelete="CASCADE"),
        UniqueConstraint("candidate_id", "skill_id", name="uq_candidate_skill"),
        Index("ix_candidate_skills_workspace_skill", "workspace_id", "skill_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_id: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False)
    skill: Mapped["Skill"] = relationship(back_populates="candidate_links")
    candidate: Mapped[Candidate] = relationship(back_populates="skills")


class CandidateEducation(Base):
    __tablename__ = "candidate_education"
    __table_args__ = (
        ForeignKeyConstraint(["candidate_id", "workspace_id"], ["candidates.id", "candidates.workspace_id"], ondelete="CASCADE"),
        Index("ix_candidate_education_workspace_candidate", "workspace_id", "candidate_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_id: Mapped[int] = mapped_column(Integer, nullable=False)
    institution: Mapped[str | None] = mapped_column(String(180), nullable=True)
    degree: Mapped[str] = mapped_column(String(160), nullable=False)
    field_of_study: Mapped[str | None] = mapped_column(String(160), nullable=True)
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate: Mapped[Candidate] = relationship(back_populates="education")


class CandidateResume(Base):
    __tablename__ = "candidate_resumes"
    __table_args__ = (
        ForeignKeyConstraint(["candidate_id", "workspace_id"], ["candidates.id", "candidates.workspace_id"], ondelete="CASCADE"),
        UniqueConstraint("candidate_id", name="uq_candidate_resume"),
        CheckConstraint("size_bytes > 0", name="ck_resume_size_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_id: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    candidate: Mapped[Candidate] = relationship(back_populates="resume")
    # Loaded only when the bytes are needed (download or re-extraction), never with candidate listings.
    file: Mapped["ResumeFile | None"] = relationship(back_populates="resume", cascade="all, delete-orphan", uselist=False, lazy="select", passive_deletes=True)


class ResumeFile(Base):
    """Resume bytes stored in PostgreSQL: durable across deploys, backed up with the database, and
    reachable only through the authenticated, workspace-scoped API."""

    __tablename__ = "resume_files"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_resume_file_size_positive"),
        Index("ix_resume_files_workspace", "workspace_id"),
    )

    resume_id: Mapped[int] = mapped_column(ForeignKey("candidate_resumes.id", ondelete="CASCADE"), primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resume: Mapped[CandidateResume] = relationship(back_populates="file")
