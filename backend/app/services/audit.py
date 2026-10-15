from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.audit import AuditLog
from backend.app.models.user import User


_BLOCKED_KEYS = {"password", "password_hash", "token", "access_token", "refresh_token", "secret", "authorization", "cookie", "resume_text"}


def safe_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    def clean(item: Any, key: str = "") -> Any:
        if any(blocked in key.lower() for blocked in _BLOCKED_KEYS):
            return None
        if isinstance(item, Mapping):
            return {str(name)[:80]: cleaned for name, raw in item.items() if (cleaned := clean(raw, str(name))) is not None}
        if isinstance(item, (list, tuple, set)):
            return [clean(child) for child in list(item)[:50]]
        if isinstance(item, str):
            return item[:500]
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return str(item)[:500]

    return clean(value or {})


def record_audit(
    db: Session,
    *,
    workspace_id: int,
    actor: User | None,
    action: str,
    resource_type: str,
    resource_id: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_id=actor.id if actor else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_safe=safe_metadata(metadata),
        )
    )


def list_audit_logs(
    db: Session,
    viewer: User,
    *,
    actor_id: int | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    skip: int = 0,
    limit: int = 50,
) -> dict:
    """Workspace activity, newest first. Admins see everyone's actions; other users see only their own."""
    if viewer.role != "admin":
        if actor_id is not None and actor_id != viewer.id:
            raise HTTPException(status_code=403, detail="Only admins can view other users' activity")
        actor_id = viewer.id
    predicates = [AuditLog.workspace_id == viewer.workspace_id]
    if actor_id is not None:
        predicates.append(AuditLog.actor_id == actor_id)
    if action:
        # "application." matches every application action; a full name matches exactly.
        predicates.append(AuditLog.action.startswith(action, autoescape=True) if action.endswith(".") else AuditLog.action == action)
    if resource_type:
        predicates.append(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        predicates.append(AuditLog.resource_id == resource_id)
    if since is not None:
        predicates.append(AuditLog.created_at >= since)
    if until is not None:
        predicates.append(AuditLog.created_at <= until)
    total = db.scalar(select(func.count(AuditLog.id)).where(*predicates)) or 0
    items: list[dict] = []
    if total and skip < total:
        rows = db.execute(
            select(AuditLog, User.full_name)
            .outerjoin(User, (User.id == AuditLog.actor_id) & (User.workspace_id == AuditLog.workspace_id))
            .where(*predicates)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(skip)
            .limit(limit)
        ).all()
        items = [
            {
                "id": log.id,
                "actor_id": log.actor_id,
                "actor_name": name,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "metadata": log.metadata_safe,
                "created_at": log.created_at,
            }
            for log, name in rows
        ]
    return {"items": items, "total": total, "skip": skip, "limit": limit}
