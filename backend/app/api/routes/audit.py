from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_user, require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.audit import AuditLogPage
from backend.app.services.audit import list_audit_logs
from backend.app.schemas.common import MAX_DB_INT

router = APIRouter(tags=["activity"])


@router.get("/audit-logs", response_model=AuditLogPage)
def audit_logs(
    actor_id: int | None = Query(default=None, gt=0, le=MAX_DB_INT, description="Admins only, except your own ID"),
    action: str | None = Query(default=None, min_length=1, max_length=80, description="Exact action, or a prefix ending in '.' such as 'application.'"),
    resource_type: str | None = Query(default=None, min_length=1, max_length=80),
    resource_id: int | None = Query(default=None, gt=0, le=MAX_DB_INT),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    skip: int = Query(default=0, ge=0, le=MAX_DB_INT),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Workspace activity log, newest first. Admins see all users; HR users see only their own actions."""
    return list_audit_logs(db, user, actor_id=actor_id, action=action, resource_type=resource_type, resource_id=resource_id, since=since, until=until, skip=skip, limit=limit)


@router.get("/users/{user_id}/activity", response_model=AuditLogPage)
def user_activity(
    user_id: Annotated[int, Path(gt=0, le=MAX_DB_INT)],
    skip: int = Query(default=0, ge=0, le=MAX_DB_INT),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    """One workspace user's activity (Admin only). Unknown or other-workspace users return an empty page."""
    return list_audit_logs(db, admin, actor_id=user_id, skip=skip, limit=limit)
