import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import Response

from backend.app.core.config import Settings
from backend.app.models.auth_session import AuthSession, RevokedRefreshToken
from backend.app.models.user import User


@dataclass(frozen=True)
class SessionTokens:
    session: AuthSession
    access_token: str
    refresh_token: str
    csrf_token: str


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_expired(value: datetime, now: datetime | None = None) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= (now or utc_now())


def issue_session(db: Session, user: User, settings: Settings) -> SessionTokens:
    now = utc_now()
    access_token = secrets.token_urlsafe(48)
    refresh_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    session = AuthSession(
        user_id=user.id,
        workspace_id=user.workspace_id,
        access_token_hash=token_digest(access_token),
        refresh_token_hash=token_digest(refresh_token),
        csrf_token_hash=token_digest(csrf_token),
        access_expires_at=now + timedelta(seconds=settings.access_token_ttl_seconds),
        refresh_expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
        last_used_at=now,
    )
    db.add(session)
    db.flush()
    return SessionTokens(session, access_token, refresh_token, csrf_token)


def find_access_session(db: Session, access_token: str) -> AuthSession | None:
    digest = token_digest(access_token)
    session = db.scalar(select(AuthSession).where(AuthSession.access_token_hash == digest, AuthSession.revoked_at.is_(None)))
    if session is None or is_expired(session.access_expires_at) or is_expired(session.refresh_expires_at):
        return None
    return session


def rotate_refresh_session(db: Session, refresh_token: str, settings: Settings):
    digest = token_digest(refresh_token)
    session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == digest).with_for_update())
    if session is None:
        previously_revoked = db.scalar(select(RevokedRefreshToken).where(RevokedRefreshToken.token_hash == digest))
        if previously_revoked is None:
            return None, "invalid"
        if is_expired(previously_revoked.expires_at):
            db.delete(previously_revoked)
            return None, "invalid"
        compromised_session = db.get(AuthSession, previously_revoked.session_id)
        if compromised_session is not None and compromised_session.revoked_at is None:
            compromised_session.revoked_at = utc_now()
        return None, "replay"
    now = utc_now()
    if session.revoked_at is not None:
        return None, "invalid"
    if is_expired(session.refresh_expires_at, now):
        session.revoked_at = now
        return None, "expired"

    db.add(RevokedRefreshToken(token_hash=digest, session_id=session.id, expires_at=session.refresh_expires_at))
    access_token = secrets.token_urlsafe(48)
    next_refresh_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    session.access_token_hash = token_digest(access_token)
    session.refresh_token_hash = token_digest(next_refresh_token)
    session.csrf_token_hash = token_digest(csrf_token)
    session.access_expires_at = now + timedelta(seconds=settings.access_token_ttl_seconds)
    session.refresh_expires_at = now + timedelta(seconds=settings.refresh_token_ttl_seconds)
    session.last_used_at = now
    db.flush()
    return SessionTokens(session, access_token, next_refresh_token, csrf_token), "rotated"


def revoke_session(db: Session, session: AuthSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = utc_now()
        db.add(RevokedRefreshToken(
            token_hash=session.refresh_token_hash,
            session_id=session.id,
            expires_at=session.refresh_expires_at,
        ))


def set_auth_cookies(response: Response, tokens: SessionTokens, settings: Settings) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.set_cookie(
        settings.access_cookie_name,
        tokens.access_token,
        max_age=settings.access_token_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    response.set_cookie(
        settings.refresh_cookie_name,
        tokens.refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/api/auth",
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.access_cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite=settings.cookie_samesite)
    response.delete_cookie(settings.refresh_cookie_name, path="/api/auth", secure=settings.cookie_secure, httponly=True, samesite=settings.cookie_samesite)
