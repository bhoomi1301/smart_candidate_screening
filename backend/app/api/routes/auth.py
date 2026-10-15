from typing import Annotated

import secrets

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.csrf import verify_csrf, verify_origin, verify_refresh_csrf, verify_same_origin_read
from backend.app.api.dependencies import get_current_auth_session, get_current_user, require_roles
from backend.app.core.config import Settings
from backend.app.db.session import get_db
from backend.app.models.auth_session import AuthSession
from backend.app.models.user import User
from backend.app.schemas.auth import AuthResponse, LoginInput, RegisterInput, UserCreate, UserRead
from backend.app.services.audit import record_audit
from backend.app.services.auth import add_workspace_user, authenticate, register_workspace
from backend.app.services.sessions import clear_auth_cookies, find_access_session, is_expired, issue_session, revoke_session, rotate_refresh_session, set_auth_cookies, token_digest, utc_now
from backend.app.schemas.common import MAX_DB_INT

router = APIRouter(prefix="/auth", tags=["authentication"])
users_router = APIRouter(prefix="/users", tags=["users"])


def auth_response(user: User, tokens, settings: Settings) -> AuthResponse:
    return AuthResponse(
        user=user,
        workspace_id=user.workspace_id,
        access_expires_in=settings.access_token_ttl_seconds,
        refresh_expires_in=settings.refresh_token_ttl_seconds,
        csrf_token=tokens.csrf_token,
    )


@router.get("/csrf", dependencies=[Depends(verify_same_origin_read)])
def get_csrf_token(request: Request, response: Response, db: Session = Depends(get_db)):
    settings: Settings = request.app.state.settings
    access_token = request.cookies.get(settings.access_cookie_name)
    auth_session = find_access_session(db, access_token) if access_token else None
    if auth_session is None:
        refresh_token = request.cookies.get(settings.refresh_cookie_name)
        digest = token_digest(refresh_token) if refresh_token else None
        auth_session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == digest)) if digest else None
        if auth_session is None or auth_session.revoked_at is not None or is_expired(auth_session.refresh_expires_at):
            raise HTTPException(status_code=401, detail="Authentication required")
    token = secrets.token_urlsafe(32)
    auth_session.csrf_token_hash = token_digest(token)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": token}


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_origin)])
def register(payload: RegisterInput, request: Request, response: Response, db: Session = Depends(get_db)):
    settings: Settings = request.app.state.settings
    try:
        workspace, user = register_workspace(db, payload)
        tokens = issue_session(db, user, settings)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account or workspace already exists") from None
    set_auth_cookies(response, tokens, settings)
    return auth_response(user, tokens, settings)


@router.post("/login", response_model=AuthResponse, dependencies=[Depends(verify_origin)])
def login(payload: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    settings: Settings = request.app.state.settings
    user = authenticate(db, payload.email, payload.password)
    if user is None:
        db.rollback()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    tokens = issue_session(db, user, settings)
    db.commit()
    set_auth_cookies(response, tokens, settings)
    return auth_response(user, tokens, settings)


@router.post("/refresh", response_model=AuthResponse, dependencies=[Depends(verify_refresh_csrf)])
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    settings: Settings = request.app.state.settings
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh session is missing or expired")
    tokens, result = rotate_refresh_session(db, refresh_token, settings)
    if tokens is None:
        if result in {"replay", "expired"}:
            db.commit()
        raise HTTPException(status_code=401, detail="Refresh session is invalid, expired, or revoked")
    user = db.scalar(select(User).where(User.id == tokens.session.user_id, User.workspace_id == tokens.session.workspace_id))
    if user is None or not user.is_active:
        revoke_session(db, tokens.session)
        db.commit()
        raise HTTPException(status_code=401, detail="Authentication required")
    record_audit(db, workspace_id=user.workspace_id, actor=user, action="auth.refresh", resource_type="user", resource_id=user.id)
    db.commit()
    set_auth_cookies(response, tokens, settings)
    return auth_response(user, tokens, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_csrf)])
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    auth_session: AuthSession = Depends(get_current_auth_session),
):
    record_audit(db, workspace_id=user.workspace_id, actor=user, action="auth.logout", resource_type="user", resource_id=user.id)
    revoke_session(db, auth_session)
    db.commit()
    clear_auth_cookies(response, request.app.state.settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    response.body = b""
    return response


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user


@users_router.get("", response_model=list[UserRead])
def list_workspace_users(db: Session = Depends(get_db), admin: User = Depends(require_roles("admin"))):
    return db.scalars(select(User).where(User.workspace_id == admin.workspace_id).order_by(User.created_at)).all()


@users_router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)])
def create_workspace_user(payload: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_roles("admin"))):
    user = add_workspace_user(db, payload, admin)
    db.commit()
    return user


@users_router.patch("/{user_id}/active", response_model=UserRead, dependencies=[Depends(verify_csrf)])
def set_user_active(user_id: Annotated[int, Path(gt=0, le=MAX_DB_INT)], is_active: bool, db: Session = Depends(get_db), admin: User = Depends(require_roles("admin"))):
    if user_id == admin.id and not is_active:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own account")
    user = db.scalar(select(User).where(User.id == user_id, User.workspace_id == admin.workspace_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    changed = user.is_active != is_active
    user.is_active = is_active
    if changed:
        record_audit(db, workspace_id=admin.workspace_id, actor=admin, action="user.activate" if is_active else "user.deactivate", resource_type="user", resource_id=user.id)
    if not is_active:
        sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.workspace_id == admin.workspace_id, AuthSession.revoked_at.is_(None))).all()
        for auth_session in sessions:
            revoke_session(db, auth_session)
    db.commit()
    return user
