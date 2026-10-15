import hmac

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_auth_session
from backend.app.core.config import Settings
from backend.app.db.session import get_db
from backend.app.models.auth_session import AuthSession, RevokedRefreshToken
from backend.app.services.sessions import token_digest


def verify_origin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    origin = request.headers.get("origin")
    if origin is None:
        if settings.app_env == "production":
            raise HTTPException(status_code=403, detail="Origin header is required")
        return
    allowed = {value.rstrip("/") for value in settings.allowed_origins}
    allowed.add(f"{request.url.scheme}://{request.url.netloc}".rstrip("/"))
    if origin.rstrip("/") not in allowed:
        raise HTTPException(status_code=403, detail="Origin is not allowed")


def verify_same_origin_read(request: Request) -> None:
    """For GET endpoints that hand out a CSRF token.

    Browsers omit the Origin header on same-origin GET requests, so it cannot be required here (that
    broke token recovery after a page reload in production). Cross-site requests are still refused:
    by Origin when present, otherwise by the browser-set Sec-Fetch-Site header. The token itself can
    only be read by same-origin script because CORS never exposes it to other origins.
    """
    if request.headers.get("origin") is not None:
        verify_origin(request)
        return
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in {"same-origin", "none"}:
        raise HTTPException(status_code=403, detail="Cross-site requests are not allowed")


def verify_csrf(request: Request, auth_session: AuthSession = Depends(get_current_auth_session)) -> None:
    verify_origin(request)
    supplied = request.headers.get("x-csrf-token")
    if not supplied or not hmac.compare_digest(token_digest(supplied), auth_session.csrf_token_hash):
        raise HTTPException(status_code=403, detail="CSRF token is missing or invalid")


def verify_refresh_csrf(request: Request, db: Session = Depends(get_db)) -> None:
    verify_origin(request)
    settings: Settings = request.app.state.settings
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh session is missing or expired")
    digest = token_digest(refresh_token)
    auth_session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == digest))
    if auth_session is None:
        revoked = db.scalar(select(RevokedRefreshToken).where(RevokedRefreshToken.token_hash == digest))
        auth_session = db.get(AuthSession, revoked.session_id) if revoked is not None else None
    supplied = request.headers.get("x-csrf-token")
    if auth_session is None:
        raise HTTPException(status_code=401, detail="Refresh session is invalid or expired")
    if not supplied or not hmac.compare_digest(token_digest(supplied), auth_session.csrf_token_hash):
        raise HTTPException(status_code=403, detail="CSRF token is missing or invalid")
