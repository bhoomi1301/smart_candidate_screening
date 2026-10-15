from typing import Annotated

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, Request, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_user, require_roles
from backend.app.api.csrf import verify_csrf
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.application import ApplicationStatus
from backend.app.core.config import Settings
from backend.app.schemas.candidate import CandidateCreate, CandidateDetail, CandidatePage, CandidateRead, CandidateUpdate
from backend.app.schemas.resume import ResumeExtractionRead, ResumeUploadRead
from backend.app.services.audit import record_audit
from backend.app.services.resumes import analyse_upload, get_stored_resume, read_upload, resume_payload, store_resume
from backend.app.services.candidates import candidate_payload, candidate_profile_payload, create_candidate, delete_candidate, get_candidate, get_candidate_profile, list_candidates, remove_candidate_resume, update_candidate
from backend.app.schemas.common import MAX_DB_INT

router = APIRouter(prefix="/candidates", tags=["candidates"])

CandidateId = Annotated[int, Path(gt=0, le=MAX_DB_INT)]
DUPLICATE_EMAIL = "Candidate email already exists in this workspace"
manage_candidates = require_roles("admin", "hr")


@router.get("", response_model=CandidatePage)
def candidates_list(
    q: str | None = Query(default=None, max_length=120, description="Search name, email, or skill"),
    skill: str | None = Query(default=None, min_length=1, max_length=100),
    selected_status: ApplicationStatus | None = Query(default=None, alias="status", description="Candidates with an application in this status"),
    job_id: int | None = Query(default=None, gt=0, le=MAX_DB_INT, description="Candidates who applied to this job"),
    min_experience: float | None = Query(default=None, ge=0, le=80),
    max_experience: float | None = Query(default=None, ge=0, le=80),
    skip: int = Query(default=0, ge=0, le=MAX_DB_INT),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows, total = list_candidates(db, user.workspace_id, q=q, skill=skill, min_experience=min_experience, max_experience=max_experience, status_filter=selected_status, job_id=job_id, skip=skip, limit=limit)
    return {"items": rows, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=CandidateRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)])
def candidates_create(payload: CandidateCreate, db: Session = Depends(get_db), user: User = Depends(manage_candidates)):
    try:
        candidate = create_candidate(db, user.workspace_id, user, payload)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_EMAIL) from None
    return candidate_payload(candidate)


@router.get("/{candidate_id}", response_model=CandidateDetail)
def candidates_get(candidate_id: CandidateId, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return candidate_profile_payload(get_candidate_profile(db, user.workspace_id, candidate_id))


@router.put("/{candidate_id}", response_model=CandidateRead, dependencies=[Depends(verify_csrf)])
def candidates_update(payload: CandidateUpdate, candidate_id: CandidateId, db: Session = Depends(get_db), user: User = Depends(manage_candidates)):
    try:
        candidate = get_candidate(db, user.workspace_id, candidate_id)
        update_candidate(db, user.workspace_id, user, candidate, payload)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_EMAIL) from None
    return candidate_payload(candidate)


@router.post("/{candidate_id}/resume", response_model=ResumeUploadRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)])
def candidates_resume_upload(request: Request, candidate_id: CandidateId, file: UploadFile = File(description="PDF resume"), db: Session = Depends(get_db), user: User = Depends(manage_candidates)):
    """Upload (or replace) the candidate's PDF resume and return unverified suggestions extracted from it.

    Suggestions are not applied: review them and save changes with PUT /api/candidates/{id}.
    """
    settings: Settings = request.app.state.settings
    candidate = get_candidate(db, user.workspace_id, candidate_id)
    data, filename = read_upload(request, file, settings)
    page_count, extraction = analyse_upload(db, user.workspace_id, data, settings)
    resume = store_resume(db, user.workspace_id, user, candidate, data, filename, page_count)
    db.commit()
    return {"resume": resume_payload(resume), "extraction": extraction}


@router.get(
    "/{candidate_id}/resume/file",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The stored PDF, as a download"}},
)
def candidates_resume_download(candidate_id: CandidateId, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Download the stored PDF. Workspace members only; always sent as an attachment, never rendered inline."""
    resume, stored = get_stored_resume(db, user.workspace_id, candidate_id)
    record_audit(db, workspace_id=user.workspace_id, actor=user, action="candidate.resume_download", resource_type="candidate", resource_id=candidate_id)
    db.commit()
    return Response(
        content=stored.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"resume.pdf\"; filename*=UTF-8''{quote(resume.original_filename)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


@router.get("/{candidate_id}/resume/suggestions", response_model=ResumeExtractionRead)
def candidates_resume_suggestions(request: Request, candidate_id: CandidateId, db: Session = Depends(get_db), user: User = Depends(manage_candidates)):
    """Re-run extraction on the stored PDF (nothing is saved)."""
    _, stored = get_stored_resume(db, user.workspace_id, candidate_id)
    _, extraction = analyse_upload(db, user.workspace_id, stored.content, request.app.state.settings)
    return extraction


@router.delete("/{candidate_id}/resume", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_csrf)])
def candidates_resume_delete(candidate_id: CandidateId, db: Session = Depends(get_db), user: User = Depends(manage_candidates)):
    candidate = get_candidate(db, user.workspace_id, candidate_id)
    remove_candidate_resume(db, user.workspace_id, user, candidate)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_csrf)])
def candidates_delete(candidate_id: CandidateId, db: Session = Depends(get_db), user: User = Depends(manage_candidates)):
    candidate = get_candidate(db, user.workspace_id, candidate_id)
    delete_candidate(db, user.workspace_id, user, candidate)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
