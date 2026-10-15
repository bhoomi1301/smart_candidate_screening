from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from backend.app.schemas.common import InputSchema, OutputSchema
from backend.app.schemas.candidate import collapse_whitespace
from backend.app.screening.normalization import normalize_items


class CriterionWeights(InputSchema):
    required_skills: Decimal = Field(default=Decimal("50"), ge=0, le=100, max_digits=5, decimal_places=2)
    preferred_skills: Decimal = Field(default=Decimal("20"), ge=0, le=100, max_digits=5, decimal_places=2)
    experience: Decimal = Field(default=Decimal("20"), ge=0, le=100, max_digits=5, decimal_places=2)
    qualifications: Decimal = Field(default=Decimal("10"), ge=0, le=100, max_digits=5, decimal_places=2)

    @model_validator(mode="after")
    def weights_total_one_hundred(self):
        if sum(self.model_dump().values()) != Decimal("100"):
            raise ValueError("Criterion weights must sum to 100")
        if self.required_skills <= 0:
            raise ValueError("Required skills criterion weight must be greater than 0")
        return self


class QualificationInput(InputSchema):
    name: str = Field(min_length=1, max_length=180)
    is_mandatory: bool = True
    weight: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return collapse_whitespace(value)


class QualificationRead(QualificationInput):
    id: int


SkillWeight = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]


class JobCreate(InputSchema):
    title: str = Field(min_length=2, max_length=180)
    department: str | None = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=20000)
    required_skills: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(min_length=1, max_length=100)
    preferred_skills: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=100)
    required_skill_weights: dict[str, SkillWeight] = Field(default_factory=dict)
    preferred_skill_weights: dict[str, SkillWeight] = Field(default_factory=dict)
    minimum_experience: Decimal = Field(default=Decimal("0"), ge=0, le=80, max_digits=5, decimal_places=2)
    qualifications: list[QualificationInput] = Field(default_factory=list, max_length=50)
    criterion_weights: CriterionWeights = Field(default_factory=CriterionWeights)

    @field_validator("title", "department")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = collapse_whitespace(value)
        return value or None

    @model_validator(mode="after")
    def validate_qualifications(self):
        names = [item.name.casefold() for item in self.qualifications]
        if len(set(names)) != len(names):
            raise ValueError("Qualifications cannot contain duplicates")
        weighted = [item.weight for item in self.qualifications if item.weight is not None]
        if weighted and len(weighted) != len(self.qualifications):
            raise ValueError("Qualification weights must be set for every qualification or none")
        if weighted and sum(weighted) != Decimal("100"):
            raise ValueError("Qualification weights must sum to 100")
        return self

    @model_validator(mode="after")
    def remove_duplicate_skills(self):
        required_values = [next(iter(normalize_items([value]))) for value in self.required_skills]
        preferred_values = [next(iter(normalize_items([value]))) for value in self.preferred_skills]
        required = set(required_values)
        preferred = set(preferred_values)
        if len(required) != len(required_values) or len(preferred) != len(preferred_values):
            raise ValueError("Required and preferred skill lists cannot contain duplicate skills or aliases")
        if required & preferred:
            raise ValueError("A skill cannot be both required and preferred")
        for weights, skills, label in (
            (self.required_skill_weights, required, "required"),
            (self.preferred_skill_weights, preferred, "preferred"),
        ):
            normalized_keys = {next(iter(normalize_items([name]))) for name in weights if normalize_items([name])}
            if len(normalized_keys) != len(weights) or (normalized_keys and normalized_keys != skills):
                raise ValueError(f"{label} skill weights must cover each configured skill exactly once")
            if weights and sum(weights.values()) != Decimal("100"):
                raise ValueError(f"{label} skill weights must sum to 100")
        return self


class JobUpdate(JobCreate):
    """Full replacement of a job's criteria. Status changes go through PATCH /jobs/{id}/status."""


class JobStatusInput(InputSchema):
    status: Literal["open", "closed"]


class JobRead(OutputSchema):
    id: int
    workspace_id: int
    title: str
    department: str | None
    description: str
    required_skills: list[str]
    preferred_skills: list[str]
    required_skill_weights: dict[str, Decimal]
    preferred_skill_weights: dict[str, Decimal]
    minimum_experience: Decimal
    qualifications: list[QualificationRead]
    criterion_weights: CriterionWeights
    status: Literal["open", "closed"]
    application_count: int = 0
    created_at: datetime
    updated_at: datetime


class JobPage(OutputSchema):
    items: list[JobRead]
    total: int
    skip: int
    limit: int
