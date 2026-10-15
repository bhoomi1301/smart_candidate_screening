from collections.abc import Callable
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.session import get_db
from backend.app.models.auth_session import AuthSession
from backend.app.models.user import User
from backend.app.services.sessions import find_access_session, revoke_session


def get_current_auth_session(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    settings: Settings = request.app.state.settings
    access_token = request.cookies.get(settings.access_cookie_name)
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    auth_session = find_access_session(db, access_token)
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access session is invalid or expired")
    return auth_session


def get_current_user(db: Session = Depends(get_db), auth_session: AuthSession = Depends(get_current_auth_session)) -> User:
    user = db.scalar(select(User).where(User.id == auth_session.user_id, User.workspace_id == auth_session.workspace_id))
    if user is None or not user.is_active:
        revoke_session(db, auth_session)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def require_roles(*roles: str) -> Callable:
    def check_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return check_role
