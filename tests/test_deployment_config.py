"""Production configuration and operational behaviour."""

import logging

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import build_engine
from backend.app.main import create_app
from test_backend_api import CsrfTestClient

PRODUCTION = dict(_env_file=None, app_env="production", cookie_secure=True, allowed_origins=["https://talentlens.vercel.app"])


@pytest.mark.parametrize(
    "given, expected",
    [
        ("postgres://u:p@db.internal:5432/app", "postgresql+psycopg://u:p@db.internal:5432/app"),
        ("postgresql://u:p@db.internal/app", "postgresql+psycopg://u:p@db.internal/app"),
        ("postgresql+psycopg://u:p@db.internal/app", "postgresql+psycopg://u:p@db.internal/app"),
    ],
)
def test_managed_postgres_urls_use_the_installed_driver(given, expected):
    assert Settings(**PRODUCTION, database_url=given).database_url == expected


def test_production_refuses_sqlite_and_insecure_settings():
    with pytest.raises(ValidationError, match="PostgreSQL"):
        Settings(**PRODUCTION, database_url="sqlite:///./prod.db")
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings(**{**PRODUCTION, "cookie_secure": False}, database_url="postgresql://u:p@h/db")
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        Settings(**{**PRODUCTION, "allowed_origins": []}, database_url="postgresql://u:p@h/db")


def test_unexpected_errors_are_logged_but_not_exposed(caplog):
    settings = Settings(_env_file=None, app_env="test", database_url="sqlite:///:memory:", allowed_origins=["https://frontend.example.test"])
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    app = create_app(settings, engine)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret-internal-detail")

    caplog.set_level(logging.ERROR)
    with CsrfTestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "message": "An unexpected server error occurred"}}
    assert "secret-internal-detail" not in response.text and "Traceback" not in response.text
    record = next(record for record in caplog.records if record.name == "backend.app.errors")
    assert "GET /boom" in record.getMessage() and record.exc_info is not None


def test_health_endpoint_checks_the_database():
    settings = Settings(_env_file=None, app_env="test", database_url="sqlite:///:memory:", allowed_origins=["https://frontend.example.test"])
    with CsrfTestClient(create_app(settings, build_engine(settings))) as client:
        assert client.get("/health").json() == {"status": "ok", "database": "ok"}


def _production_like_client():
    """A production-mode app over HTTPS, so Origin is enforced and Secure cookies are sent (as on Render)."""
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import create_engine, event

    settings = Settings.model_construct(**{**Settings(_env_file=None, app_env="test", database_url="sqlite:///:memory:", allowed_origins=["https://talentlens.vercel.app"], cookie_secure=True).model_dump(), "app_env": "production"})
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda connection, record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return CsrfTestClient(create_app(settings, engine), base_url="https://talentlens.vercel.app")


def test_csrf_token_can_be_recovered_after_reload_in_production():
    origin = {"Origin": "https://talentlens.vercel.app"}
    with _production_like_client() as client:
        registered = client.post("/api/auth/register", headers=origin, json={
            "workspace_name": "Prod Workspace", "full_name": "Prod User", "email": "prod-user@example.com",
            "password": "long-test-password-123", "password_confirmation": "long-test-password-123",
        })
        assert registered.status_code == 201, registered.text
        client.csrf_token = None  # a page reload loses the in-memory token
        # Browsers send no Origin on same-origin GETs; previously this returned 403 in production.
        recovered = client.get("/api/auth/csrf", headers={"Sec-Fetch-Site": "same-origin"})
        assert recovered.status_code == 200, recovered.text
        token = recovered.json()["csrf_token"]
        created = client.post("/api/candidates", headers={**origin, "X-CSRF-Token": token}, json={"full_name": "After Reload", "email": "after-reload@example.com"})
        assert created.status_code == 201, created.text
        # Cross-site attempts are still refused.
        assert client.get("/api/auth/csrf", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert client.get("/api/auth/csrf", headers={"Origin": "https://attacker.example"}).status_code == 403
        assert client.post("/api/candidates", headers={"X-CSRF-Token": token}, json={"full_name": "No Origin", "email": "no-origin@example.com"}).status_code == 403
