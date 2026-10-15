import re
import secrets
import unicodedata

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.workspace import Workspace
from backend.app.schemas.auth import RegisterInput, UserCreate
from backend.app.services.audit import record_audit
from backend.app.core.security import hash_password, password_hash_needs_rehash, verify_password


def make_slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:160]
    return slug or "workspace"


def register_workspace(db: Session, payload: RegisterInput) -> tuple[Workspace, User]:
    existing = db.scalar(select(User.id).where(func.lower(User.email) == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    slug_base = make_slug(payload.workspace_name)
    slug = slug_base
    while db.scalar(select(Workspace.id).where(Workspace.slug == slug)):
        slug = f"{slug_base[:145]}-{secrets.token_hex(4)}"
    workspace = Workspace(name=payload.workspace_name, slug=slug)
    db.add(workspace)
    db.flush()
    user = User(
        workspace_id=workspace.id,
        full_name=payload.full_name,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role="hr",
        is_active=True,
    )
    db.add(user)
    db.flush()
    record_audit(db, workspace_id=workspace.id, actor=user, action="workspace.register", resource_type="workspace", resource_id=workspace.id)
    return workspace, user


def add_workspace_user(db: Session, payload: UserCreate, actor: User) -> User:
    if db.scalar(select(User.id).where(func.lower(User.email) == payload.email.lower())):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(
        workspace_id=actor.workspace_id,
        full_name=payload.full_name,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role="hr",
        is_active=True,
    )
    db.add(user)
    db.flush()
    record_audit(db, workspace_id=actor.workspace_id, actor=actor, action="user.create", resource_type="user", resource_id=user.id, metadata={"role": user.role})
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    if password_hash_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    record_audit(db, workspace_id=user.workspace_id, actor=user, action="auth.login", resource_type="user", resource_id=user.id)
    return user
