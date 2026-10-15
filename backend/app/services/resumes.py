"""Resume upload, storage, and extraction.

Privacy rules: resume bytes and extracted text are never logged, never written to the audit log,
and only returned to authenticated users of the owning workspace. Extracted text is not stored;
suggestions are recomputed from the stored PDF on request.
"""

import hashlib
import logging
import uuid

from fastapi import HTTPException, Request, UploadFile
from sqlalchemy import select, union
from sqlalchemy.orm import Session, selectinload

from backend.app.core.config import Settings
from backend.app.models.candidate import Candidate, CandidateResume, CandidateSkill, ResumeFile
from backend.app.models.job import JobSkill
from backend.app.models.skill import Skill
from backend.app.models.user import User
from backend.app.resumes.extraction import ResumeSuggestions, extract_details
from backend.app.resumes.pdf import InvalidPdf, check_declared_type, extract_text, open_pdf, safe_filename
from backend.app.services.audit import record_audit

logger = logging.getLogger(__name__)

READ_CHUNK = 64 * 1024
MULTIPART_OVERHEAD = 64 * 1024
MIN_TEXT_CHARACTERS = 20
NOTICE = "Extracted automatically from the PDF. These are unverified suggestions: review and edit them before saving."


def _too_large(settings: Settings) -> HTTPException:
    return HTTPException(status_code=413, detail=f"The PDF must be {settings.resume_max_bytes // (1024 * 1024) or 1} MB or smaller.")


def read_upload(request: Request, upload: UploadFile, settings: Settings) -> tuple[bytes, str]:
    """Return (bytes, safe filename) after type and size checks. Never trusts the declared size alone."""
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > settings.resume_max_bytes + MULTIPART_OVERHEAD:
        raise _too_large(settings)
    try:
        check_declared_type(upload.content_type)
        filename = safe_filename(upload.filename)
    except InvalidPdf as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from None
    chunks: list[bytes] = []
    total = 0
    while chunk := upload.file.read(READ_CHUNK):
        total += len(chunk)
        if total > settings.resume_max_bytes:
            raise _too_large(settings)
        chunks.append(chunk)
    return b"".join(chunks), filename


def _validated_reader(data: bytes, settings: Settings):
    try:
        return open_pdf(data, max_pages=settings.resume_max_pages)
    except InvalidPdf as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def workspace_skill_vocabulary(db: Session, workspace_id: int) -> list[str]:
    """Display names of skills already used by this workspace's jobs and candidates."""
    skill_ids = union(
        select(JobSkill.skill_id).where(JobSkill.workspace_id == workspace_id),
        select(CandidateSkill.skill_id).where(CandidateSkill.workspace_id == workspace_id),
    ).subquery()
    return list(db.scalars(select(Skill.display_name).where(Skill.id.in_(select(skill_ids.c.skill_id))).order_by(Skill.display_name)))


def build_extraction(reader, vocabulary: list[str]) -> dict:
    """Run text and detail extraction. Failures become a status, never an exception."""
    page_count = len(reader.pages)
    empty = ResumeSuggestions().as_dict()
    try:
        extracted = extract_text(reader)
    except Exception as exc:
        logger.warning("Resume text extraction failed (%s)", type(exc).__name__)
        return {"status": "failed", "message": "Text could not be extracted from this PDF. Enter the candidate's details manually.", "page_count": page_count, "pages_scanned": 0, "text_characters": 0, "truncated": False, "suggestions": empty, "notice": NOTICE}
    base = {"page_count": extracted.page_count, "pages_scanned": extracted.pages_scanned, "text_characters": len(extracted.text), "truncated": extracted.truncated, "notice": NOTICE}
    if len(extracted.text.strip()) < MIN_TEXT_CHARACTERS:
        return {**base, "status": "no_text", "message": "No readable text was found. The PDF may be scanned or image-only; enter the details manually.", "suggestions": empty}
    try:
        suggestions = extract_details(extracted.text, skill_vocabulary=vocabulary)
    except Exception as exc:
        logger.warning("Resume detail extraction failed (%s)", type(exc).__name__)
        return {**base, "status": "failed", "message": "Details could not be extracted from this PDF. Enter them manually.", "suggestions": empty}
    if suggestions.is_empty():
        return {**base, "status": "no_suggestions", "message": "Text was read, but no recognisable details were found. Enter them manually.", "suggestions": empty}
    message = "Suggestions found. Review each one before applying it."
    if extracted.truncated:
        message += f" Only the first {extracted.pages_scanned} page(s) were read."
    return {**base, "status": "ok", "message": message, "suggestions": suggestions.as_dict()}


def analyse_upload(db: Session, workspace_id: int, data: bytes, settings: Settings) -> tuple[int, dict]:
    reader = _validated_reader(data, settings)
    return len(reader.pages), build_extraction(reader, workspace_skill_vocabulary(db, workspace_id))


def resume_payload(resume: CandidateResume | None) -> dict | None:
    if resume is None:
        return None
    file = resume.file
    return {
        "original_filename": resume.original_filename,
        "content_type": resume.content_type,
        "size_bytes": resume.size_bytes,
        "uploaded_at": resume.uploaded_at,
        "page_count": file.page_count if file else None,
        "file_available": file is not None,
    }


def store_resume(db: Session, workspace_id: int, actor: User, candidate: Candidate, data: bytes, filename: str, page_count: int) -> CandidateResume:
    """Create or replace the candidate's resume (metadata and bytes) in the caller's transaction."""
    resume = db.scalar(select(CandidateResume).options(selectinload(CandidateResume.file)).where(CandidateResume.candidate_id == candidate.id, CandidateResume.workspace_id == workspace_id))
    replaced = resume is not None
    if resume is None:
        resume = CandidateResume(candidate_id=candidate.id, workspace_id=workspace_id)
        db.add(resume)
    resume.original_filename = filename
    resume.content_type = "application/pdf"
    resume.size_bytes = len(data)
    resume.storage_key = f"db:resume_files/{uuid.uuid4()}"
    db.flush()
    file = resume.file or ResumeFile(resume_id=resume.id, workspace_id=workspace_id)
    file.content = data
    file.size_bytes = len(data)
    file.sha256 = hashlib.sha256(data).hexdigest()
    file.page_count = page_count
    resume.file = file
    db.flush()
    db.refresh(resume, attribute_names=["uploaded_at"])
    # Only sizes and counts are audited; never the filename or contents (they can identify the person).
    record_audit(db, workspace_id=workspace_id, actor=actor, action="candidate.resume_upload", resource_type="candidate", resource_id=candidate.id, metadata={"size_bytes": len(data), "page_count": page_count, "replaced": replaced})
    return resume


def get_stored_resume(db: Session, workspace_id: int, candidate_id: int, *, with_content: bool = False) -> tuple[CandidateResume, ResumeFile]:
    query = select(CandidateResume).where(CandidateResume.candidate_id == candidate_id, CandidateResume.workspace_id == workspace_id)
    resume = db.scalar(query.options(selectinload(CandidateResume.file)))
    if resume is None:
        raise HTTPException(status_code=404, detail="This candidate has no resume")
    if resume.file is None:
        raise HTTPException(status_code=404, detail="No stored file is available for this resume")
    if with_content:
        resume.file.content  # noqa: B018  (load the deferred column explicitly)
    return resume, resume.file
