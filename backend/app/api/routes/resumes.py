from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session

from backend.app.api.csrf import verify_csrf
from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.resume import ResumeExtractionRead
from backend.app.services.resumes import analyse_upload, read_upload

router = APIRouter(prefix="/resumes", tags=["resumes"])


@router.post("/extract", response_model=ResumeExtractionRead, dependencies=[Depends(verify_csrf)])
def resumes_extract(request: Request, file: UploadFile = File(description="PDF resume"), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    """Validate a PDF and return unverified suggestions for a new candidate. The file is not stored."""
    data, _ = read_upload(request, file, request.app.state.settings)
    _, extraction = analyse_upload(db, user.workspace_id, data, request.app.state.settings)
    return extraction
