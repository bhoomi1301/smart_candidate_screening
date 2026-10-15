import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import EmailStr, Field, field_validator

from backend.app.schemas.application import ApplicationStatus, ScreeningResultRead, StatusHistoryRead
from backend.app.schemas.common import InputSchema, OutputSchema
from backend.app.screening.normalization import normalize_items


SkillName = Annotated[str, Field(min_length=1, max_length=100)]
_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()./-]{5,38}$")


def collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


class EducationInput(InputSchema):
    institution: str | None = Field(default=None, max_length=180)
    degree: str = Field(min_length=1, max_length=160)
    field_of_study: str | None = Field(default=None, max_length=160)
    graduation_year: int | None = Field(default=None, ge=1900, le=2100)


class EducationRead(EducationInput):
    id: int


class CandidateCreate(InputSchema):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    total_experience: Decimal | None = Field(default=None, ge=0, le=80, max_digits=5, decimal_places=2)
    technical_skills: list[SkillName] = Field(default_factory=list, max_length=100)
    education: list[EducationInput] = Field(default_factory=list, max_length=30)

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = collapse_whitespace(value)
        if len(value) < 2:
            raise ValueError("Full name must contain at least 2 characters")
        return value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        digits = sum(char.isdigit() for char in value)
        if not _PHONE_PATTERN.fullmatch(value) or not 6 <= digits <= 20:
            raise ValueError("Phone must contain 6-20 digits and only +, spaces, parentheses, dots, or dashes")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("technical_skills")
    @classmethod
    def clean_skills(cls, values: list[str]) -> list[str]:
        cleaned: dict[str, str] = {}
        for value in values:
            normalized_items = normalize_items([value])
            if normalized_items:
                normalized = next(iter(normalized_items))
                cleaned.setdefault(normalized, " ".join(value.split()))
        return [cleaned[key] for key in sorted(cleaned)]


class CandidateUpdate(CandidateCreate):
    pass


class CandidateRead(OutputSchema):
    id: int
    workspace_id: int
    full_name: str
    email: EmailStr
    phone: str | None
    total_experience: Decimal | None
    technical_skills: list[str]
    education: list[EducationRead]
    created_at: datetime
    updated_at: datetime


class CandidatePage(OutputSchema):
    items: list[CandidateRead]
    total: int
    skip: int
    limit: int


class CandidateResumeRead(OutputSchema):
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    page_count: int | None = None
    file_available: bool = False


class CandidateApplicationRead(OutputSchema):
    id: int
    job_id: int
    job_title: str
    job_status: str
    status: ApplicationStatus
    current_screening_score: Decimal | None
    decision_notes: str
    screening_result: ScreeningResultRead | None = None
    status_history: list[StatusHistoryRead] = Field(default_factory=list)
    created_at: datetime


class CandidateDetail(CandidateRead):
    resume: CandidateResumeRead | None = None
    applications: list[CandidateApplicationRead] = Field(default_factory=list)
