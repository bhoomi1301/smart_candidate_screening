from datetime import datetime
from typing import Literal

from backend.app.schemas.common import OutputSchema

ExtractionStatus = Literal["ok", "no_text", "no_suggestions", "failed"]


class TextSuggestion(OutputSchema):
    value: str
    evidence: str


class NameSuggestion(TextSuggestion):
    confidence: Literal["low"]


class EducationSuggestion(OutputSchema):
    degree: str
    field_of_study: str | None
    institution: str | None
    graduation_year: int | None
    evidence: str


class ExperienceSuggestion(OutputSchema):
    value: float
    method: Literal["stated", "date_ranges"]
    evidence: str


class ResumeSuggestionsRead(OutputSchema):
    full_name: NameSuggestion | None
    emails: list[TextSuggestion]
    phones: list[TextSuggestion]
    skills: list[TextSuggestion]
    education: list[EducationSuggestion]
    total_experience: ExperienceSuggestion | None


class ResumeExtractionRead(OutputSchema):
    status: ExtractionStatus
    message: str
    page_count: int
    pages_scanned: int
    text_characters: int
    truncated: bool
    suggestions: ResumeSuggestionsRead
    notice: str


class ResumeFileRead(OutputSchema):
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    page_count: int | None
    file_available: bool


class ResumeUploadRead(OutputSchema):
    resume: ResumeFileRead
    extraction: ResumeExtractionRead
