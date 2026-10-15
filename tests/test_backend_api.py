from decimal import Decimal
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import build_engine
from backend.app.main import create_app
from backend.app.models.auth_session import AuthSession
from backend.app.models.user import User
from backend.app.services.audit import safe_metadata
from backend.app.services.sessions import issue_session, token_digest, utc_now
from security import hash_password as hash_legacy_password
from pdf_factory import text_pdf


class CsrfTestClient(TestClient):
    def request(self, method, url, *args, **kwargs):
        path = urlsplit(str(url)).path
        public_auth = path in {"/api/auth/register", "/api/auth/login"}
        if method.upper() not in {"GET", "HEAD", "OPTIONS"} and path.startswith("/api/") and not public_auth:
            headers = dict(kwargs.get("headers") or {})
            if not any(key.lower() == "x-csrf-token" for key in headers):
                if getattr(self, "csrf_token", None):
                    headers["X-CSRF-Token"] = self.csrf_token
                kwargs["headers"] = headers
        response = super().request(method, url, *args, **kwargs)
        if path in {"/api/auth/register", "/api/auth/login", "/api/auth/refresh"} and response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
            if isinstance(data, dict) and data.get("csrf_token"):
                self.csrf_token = data["csrf_token"]
        return response


@pytest.fixture
def backend_client():
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite:///:memory:",
        allowed_origins=["https://frontend.example.test"],
    )
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    application = create_app(settings, engine)
    with CsrfTestClient(application) as client:
        yield client


def register(client, workspace, email):
    return client.post("/api/auth/register", json={
        "workspace_name": workspace,
        "full_name": "Workspace Admin",
        "email": email,
        "password": "long-test-password-123",
        "password_confirmation": "long-test-password-123",
    })


def candidate_payload(email="candidate@example.com"):
    return {
        "full_name": "Jordan Candidate",
        "email": email,
        "phone": "+1-555-0142",
        "total_experience": 5,
        "technical_skills": ["Python", "SQL", "Postgres"],
        "education": [{"degree": "BSc", "field_of_study": "Computer Science", "graduation_year": 2020}],
    }


def job_payload():
    return {
        "title": "Backend Engineer",
        "department": "Engineering",
        "description": "Build secure APIs.",
        "required_skills": ["Python", "SQL"],
        "preferred_skills": ["PostgreSQL", "Docker"],
        "minimum_experience": 3,
        "qualifications": [{"name": "Computer Science", "is_mandatory": False}],
        "criterion_weights": {"required_skills": 50, "preferred_skills": 20, "experience": 20, "qualifications": 10},
    }


def test_registration_creates_workspace_admin_and_login_session(backend_client):
    response = register(backend_client, "Northwind Recruiting", "admin@northwind.example.com")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["role"] == "hr"
    assert body["workspace_id"] == body["user"]["workspace_id"]
    assert backend_client.get("/api/auth/me").json()["email"] == "admin@northwind.example.com"
    assert backend_client.post("/api/auth/logout").status_code == 204
    login = backend_client.post("/api/auth/login", json={"email": "ADMIN@NORTHWIND.EXAMPLE.COM", "password": "long-test-password-123"})
    assert login.status_code == 200
    assert login.json()["access_expires_in"] == 900
    assert login.json()["refresh_expires_in"] == 604800
    assert "access_token" not in login.json()
    assert "refresh_token" not in login.json()
    cookies = login.headers.get_list("set-cookie")
    assert any("screening_access" in cookie and "httponly" in cookie.lower() for cookie in cookies)
    with backend_client.app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "admin@northwind.example.com"))
        assert user.password_hash.startswith("$argon2id$")
        assert "long-test-password-123" not in user.password_hash


def test_registration_password_confirmation_is_validated(backend_client):
    mismatch = backend_client.post("/api/auth/register", json={
        "workspace_name": "Mismatch Workspace",
        "full_name": "Mismatched Password",
        "email": "mismatch@example.com",
        "password": "long-password-123",
        "password_confirmation": "different-password-123",
    })
    assert mismatch.status_code == 422


def test_root_points_to_api_docs_without_frontend_url(backend_client):
    response = backend_client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"
    for retired_path in ("/register", "/login", "/static/css/style.css"):
        assert backend_client.get(retired_path).status_code == 404


def test_root_redirects_to_frontend_url_when_configured():
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite:///:memory:",
        frontend_url="https://talentlens.example.test",
    )
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    with TestClient(create_app(settings, engine)) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "https://talentlens.example.test"
        assert client.get("/health").status_code == 200


def test_invalid_login_and_invalid_access_token_are_rejected(backend_client):
    register(backend_client, "Credentials Workspace", "credentials@example.com")
    backend_client.post("/api/auth/logout")
    invalid_login = backend_client.post("/api/auth/login", json={"email": "credentials@example.com", "password": "wrong-password"})
    assert invalid_login.status_code == 401
    backend_client.cookies.set("screening_access", "not-a-valid-token", path="/")
    assert backend_client.get("/api/auth/me").status_code == 401


def test_legacy_password_hash_is_upgraded_after_successful_login(backend_client):
    registered = register(backend_client, "Hash Upgrade Workspace", "hash-upgrade@example.com").json()
    with backend_client.app.state.session_factory() as db:
        user = db.get(User, registered["user"]["id"])
        user.password_hash = hash_legacy_password("long-test-password-123")
        db.commit()
    login = backend_client.post("/api/auth/login", json={"email": "hash-upgrade@example.com", "password": "long-test-password-123"})
    assert login.status_code == 200
    with backend_client.app.state.session_factory() as db:
        user = db.get(User, registered["user"]["id"])
        assert user.password_hash.startswith("$argon2id$")


def test_expired_access_token_can_be_refreshed_with_rotation(backend_client):
    register(backend_client, "Refresh Workspace", "refresh@example.com")
    old_access = backend_client.cookies.get("screening_access")
    old_refresh = backend_client.cookies.get("screening_refresh")
    with backend_client.app.state.session_factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.access_token_hash == token_digest(old_access)))
        session.access_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert backend_client.get("/api/auth/me").status_code == 401
    csrf = backend_client.get("/api/auth/csrf")
    assert csrf.status_code == 200
    backend_client.csrf_token = csrf.json()["csrf_token"]

    refreshed = backend_client.post("/api/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    new_access = backend_client.cookies.get("screening_access")
    new_refresh = backend_client.cookies.get("screening_refresh")
    assert new_access != old_access
    assert new_refresh != old_refresh
    assert backend_client.get("/api/auth/me").status_code == 200


def test_expired_refresh_is_rejected_and_refresh_replay_revokes_session(backend_client):
    register(backend_client, "Replay Workspace", "replay@example.com")
    old_refresh = backend_client.cookies.get("screening_refresh")
    with backend_client.app.state.session_factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == token_digest(old_refresh)))
        session.refresh_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert backend_client.post("/api/auth/refresh").status_code == 401
    assert backend_client.get("/api/auth/me").status_code == 401

    register(backend_client, "Rotation Workspace", "rotation@example.com")
    replayed_refresh = backend_client.cookies.get("screening_refresh")
    backend_client.cookies.set("screening_refresh", "invalid-refresh", path="/api/auth")
    assert backend_client.post("/api/auth/refresh").status_code == 401
    backend_client.cookies.set("screening_refresh", replayed_refresh, path="/api/auth")
    first_rotation = backend_client.post("/api/auth/refresh")
    assert first_rotation.status_code == 200
    current_access = backend_client.cookies.get("screening_access")
    backend_client.cookies.set("screening_refresh", replayed_refresh, path="/api/auth")
    replay = backend_client.post("/api/auth/refresh")
    assert replay.status_code == 401
    backend_client.cookies.set("screening_access", current_access, path="/")
    assert backend_client.get("/api/auth/me").status_code == 401


def test_registration_rejects_duplicate_email_and_invalid_weight_sum(backend_client):
    assert register(backend_client, "Workspace One", "same@example.com").status_code == 201
    duplicate = register(backend_client, "Workspace Two", "SAME@example.com")
    assert duplicate.status_code == 409
    invalid_job = backend_client.post("/api/jobs", json={**job_payload(), "criterion_weights": {"required_skills": 50, "preferred_skills": 20, "experience": 20, "qualifications": 9}})
    assert invalid_job.status_code == 422
    assert invalid_job.json()["error"]["code"] == "validation_error"
    assert "input" not in str(invalid_job.json())
    attempted_admin = backend_client.post("/api/auth/register", json={
        "workspace_name": "Role Escalation",
        "full_name": "Public Admin",
        "email": "public-admin@example.com",
        "password": "long-password-123",
        "password_confirmation": "long-password-123",
        "role": "admin",
    })
    assert attempted_admin.status_code == 422


def test_candidate_job_application_workflow_and_screening_result(backend_client):
    register(backend_client, "Recruiting Workspace", "admin@recruiting.example.com")
    forged_workspace = {**candidate_payload(), "workspace_id": 999}
    assert backend_client.post("/api/candidates", json=forged_workspace).status_code == 422
    candidate = backend_client.post("/api/candidates", json=candidate_payload())
    assert candidate.status_code == 201, candidate.text
    assert candidate.json()["technical_skills"] == ["Postgres", "Python", "SQL"]
    duplicate = backend_client.post("/api/candidates", json=candidate_payload("CANDIDATE@example.com"))
    assert duplicate.status_code == 409

    job = backend_client.post("/api/jobs", json=job_payload())
    assert job.status_code == 201, job.text
    created = backend_client.post(f"/api/jobs/{job.json()['id']}/applications", json={"candidate_id": candidate.json()["id"]})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "Pending"
    assert Decimal(body["current_screening_score"]) > 0
    assert body["screening_result"]["scoring_version"] == "screening-v2"
    assert "python" in body["screening_result"]["matched_skills"]
    assert body["status_history"][0]["new_status"] == "Pending"

    duplicate_application = backend_client.post(f"/api/jobs/{job.json()['id']}/applications", json={"candidate_id": candidate.json()["id"]})
    assert duplicate_application.status_code == 409
    invalid_transition = backend_client.patch(f"/api/applications/{body['id']}", json={"status": "Shortlisted", "notes": "Skip review"})
    assert invalid_transition.status_code == 409
    decision = backend_client.patch(f"/api/applications/{body['id']}", json={"status": "Under Review", "notes": "Review started"})
    assert decision.status_code == 200
    history = backend_client.get(f"/api/applications/{body['id']}/history")
    assert [event["new_status"] for event in history.json()] == ["Pending", "Under Review"]
    analytics = backend_client.get(f"/api/analytics/dashboard?job_id={job.json()['id']}")
    assert analytics.status_code == 200
    assert analytics.json()["total_applications"] == 1
    assert analytics.json()["application_statuses"]["under_review"] == 1


def test_candidate_crud_validation_duplicates_and_empty_page(backend_client):
    register(backend_client, "Candidate CRUD Workspace", "candidate-crud@example.com")
    empty = backend_client.get("/api/candidates?skip=0&limit=10")
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "total": 0, "skip": 0, "limit": 10}

    invalid_email = backend_client.post("/api/candidates", json={**candidate_payload(), "email": "not-an-email"})
    invalid_experience = backend_client.post("/api/candidates", json={**candidate_payload(), "email": "bad-exp@example.com", "total_experience": -1})
    invalid_skill = backend_client.post("/api/candidates", json={**candidate_payload(), "email": "bad-skill@example.com", "technical_skills": ["x" * 101]})
    assert invalid_email.status_code == invalid_experience.status_code == invalid_skill.status_code == 422

    first = backend_client.post("/api/candidates", json=candidate_payload("first-crud@example.com")).json()
    second = backend_client.post("/api/candidates", json=candidate_payload("second-crud@example.com")).json()
    duplicate_update = backend_client.put(f"/api/candidates/{first['id']}", json=candidate_payload("SECOND-CRUD@example.com"))
    assert duplicate_update.status_code == 409
    updated = backend_client.put(f"/api/candidates/{first['id']}", json={**candidate_payload("first-crud@example.com"), "full_name": "Updated Candidate", "technical_skills": ["Python"]})
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Updated Candidate"
    # Resume uploads are covered in depth by tests/test_resumes.py; this checks the profile wiring.
    pdf = text_pdf(["Updated Candidate", "Python developer"])
    stored_resume = backend_client.post(f"/api/candidates/{first['id']}/resume", files={"file": ("resume.pdf", pdf, "application/pdf")})
    assert stored_resume.status_code == 201
    assert stored_resume.json()["resume"]["original_filename"] == "resume.pdf"
    profile = backend_client.get(f"/api/candidates/{first['id']}").json()
    assert profile["resume"]["size_bytes"] == len(pdf)
    assert "storage_key" not in profile["resume"]
    assert backend_client.delete(f"/api/candidates/{first['id']}/resume").status_code == 204
    assert backend_client.get(f"/api/candidates/{first['id']}").json()["resume"] is None
    assert backend_client.get(f"/api/candidates/{second['id']}").status_code == 200
    assert backend_client.delete(f"/api/candidates/{first['id']}").status_code == 204
    assert backend_client.get(f"/api/candidates/{first['id']}").status_code == 404


def test_candidate_search_filters_status_pagination_and_profile_history(backend_client):
    register(backend_client, "Candidate Search Workspace", "candidate-search@example.com")
    job = backend_client.post("/api/jobs", json=job_payload()).json()
    people = [
        {"full_name": "Ava Example", "email": "ava-search@example.com", "total_experience": 5, "technical_skills": ["Python", "SQL"]},
        {"full_name": "Bea Example", "email": "bea-search@example.com", "total_experience": 2, "technical_skills": ["Python"]},
        {"full_name": "Cal Example", "email": "cal-search@example.com", "total_experience": 7, "technical_skills": ["Java"]},
    ]
    created = [backend_client.post("/api/candidates", json=person).json() for person in people]
    applications = []
    for person in created:
        applications.append(backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": person["id"]}).json())
    reviewed = backend_client.patch(f"/api/applications/{applications[0]['id']}", json={"status": "Under Review", "notes": "Reviewed"})
    assert reviewed.status_code == 200

    page = backend_client.get("/api/candidates?skill=python&min_experience=3&max_experience=6&status=Under%20Review&skip=0&limit=1")
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert [item["email"] for item in page.json()["items"]] == ["ava-search@example.com"]
    first_page = backend_client.get("/api/candidates?skip=0&limit=2")
    second_page = backend_client.get("/api/candidates?skip=2&limit=2")
    assert first_page.json()["total"] == 3
    assert len(first_page.json()["items"]) == 2
    assert len(second_page.json()["items"]) == 1
    assert first_page.json()["items"][0]["id"] != first_page.json()["items"][1]["id"]

    detail = backend_client.get(f"/api/candidates/{created[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["applications"][0]["job_title"] == job["title"]
    assert detail.json()["applications"][0]["status_history"][-1]["new_status"] == "Under Review"

    job_view = backend_client.get(f"/api/jobs/{job['id']}/applications?status=Under%20Review&skip=0&limit=1")
    assert job_view.status_code == 200
    assert job_view.json()["total"] == 1
    assert job_view.json()["items"][0]["candidate"]["email"] == "ava-search@example.com"
    invalid_status = backend_client.get("/api/candidates?status=Hired")
    assert invalid_status.status_code == 422
    assert backend_client.get("/api/candidates?min_experience=9&max_experience=2").status_code == 422
    assert backend_client.get("/api/candidates?limit=101").status_code == 422


def test_job_crud_skill_weights_close_and_application_history_retention(backend_client):
    register(backend_client, "Job Management Workspace", "job-management@example.com")
    candidate = backend_client.post("/api/candidates", json={
        "full_name": "Weighted Candidate", "email": "weighted@example.com", "technical_skills": ["Python"]
    }).json()
    payload = {
        **job_payload(),
        "required_skills": ["Python", "SQL"],
        "required_skill_weights": {"Python": 80, "SQL": 20},
    }
    created = backend_client.post("/api/jobs", json=payload)
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["required_skill_weights"] == {"Python": "80", "SQL": "20"}
    application = backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]})
    assert application.status_code == 201
    assert application.json()["screening_result"]["score_breakdown"]["components"]["required_skills"]["score"] == 80.0

    update = {**payload, "title": "Updated Backend Engineer", "required_skill_weights": {"Python": 40, "SQL": 60}}
    changed = backend_client.put(f"/api/jobs/{job['id']}", json=update)
    assert changed.status_code == 200, changed.text
    assert changed.json()["title"] == "Updated Backend Engineer"
    assert changed.json()["required_skill_weights"] == {"Python": "40", "SQL": "60"}
    ranking = backend_client.get(f"/api/jobs/{job['id']}/rankings?skip=0&limit=1")
    assert ranking.json()["items"][0]["application_id"] == application.json()["id"]
    breakdown = backend_client.get(f"/api/applications/{application.json()['id']}/screening").json()["score_breakdown"]
    assert breakdown["components"]["required_skills"]["score"] == 40.0

    invalid_weights = backend_client.post("/api/jobs", json={**payload, "required_skill_weights": {"Python": 60, "SQL": 20}})
    assert invalid_weights.status_code == 422
    incomplete_weights = backend_client.post("/api/jobs", json={**payload, "required_skill_weights": {"Python": 100}})
    assert incomplete_weights.status_code == 422
    missing_required_skills = backend_client.post("/api/jobs", json={**payload, "required_skills": []})
    assert missing_required_skills.status_code == 422
    closed = backend_client.patch(f"/api/jobs/{job['id']}/status", json={"status": "closed"})
    assert closed.status_code == 200
    assert backend_client.get("/api/jobs?status=open").json()["items"] == []
    closed_jobs = backend_client.get("/api/jobs?status=closed").json()
    assert closed_jobs["total"] == 1
    assert closed_jobs["items"][0]["application_count"] == 1
    assert backend_client.delete(f"/api/jobs/{job['id']}").status_code == 409
    assert backend_client.get(f"/api/jobs/{job['id']}/applications").json()["total"] == 1

    empty_job = backend_client.post("/api/jobs", json=job_payload()).json()
    assert backend_client.delete(f"/api/jobs/{empty_job['id']}").status_code == 204
    assert backend_client.get(f"/api/jobs/{empty_job['id']}").status_code == 404


def test_workspace_scoping_hides_other_tenant_resources(backend_client):
    register(backend_client, "Workspace One", "admin-one@example.com")
    candidate = backend_client.post("/api/candidates", json=candidate_payload("private@example.com")).json()
    job = backend_client.post("/api/jobs", json=job_payload()).json()
    backend_client.post("/api/auth/logout")

    second = register(backend_client, "Workspace Two", "admin-two@example.com")
    assert second.status_code == 201
    assert backend_client.get(f"/api/candidates/{candidate['id']}").status_code == 404
    assert backend_client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert backend_client.get("/api/candidates").json()["total"] == 0
    assert backend_client.get("/api/jobs").json()["total"] == 0
    assert backend_client.get(f"/api/jobs/{job['id']}/applications").status_code == 404
    assert backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]}).status_code == 404


def test_hr_role_can_manage_workspace_resources_but_not_users(backend_client):
    owner = register(backend_client, "Role Workspace", "owner@example.com").json()
    with backend_client.app.state.session_factory() as db:
        db.get(User, owner["user"]["id"]).role = "admin"
        db.commit()
    hr = backend_client.post("/api/users", json={"full_name": "HR Reviewer", "email": "hr@example.com", "password": "hr-test-password-123"})
    assert hr.status_code == 201
    assert hr.json()["role"] == "hr"
    backend_client.post("/api/auth/logout")
    login = backend_client.post("/api/auth/login", json={"email": "hr@example.com", "password": "hr-test-password-123"})
    assert login.status_code == 200
    assert backend_client.post("/api/candidates", json=candidate_payload()).status_code == 201
    assert backend_client.post("/api/jobs", json=job_payload()).status_code == 201
    assert backend_client.post("/api/users", json={"full_name": "Escalation", "email": "evil@example.net", "password": "long-password-123"}).status_code == 403
    forbidden_role = backend_client.post("/api/users", json={"full_name": "Escalation", "email": "evil@example.net", "password": "long-password-123", "role": "admin"})
    assert forbidden_role.status_code == 403


def test_admin_deactivation_revokes_the_user_session(backend_client):
    owner = register(backend_client, "Deactivation Workspace", "deactivation-admin@example.com").json()
    with backend_client.app.state.session_factory() as db:
        db.get(User, owner["user"]["id"]).role = "admin"
        db.commit()
    hr = backend_client.post("/api/users", json={"full_name": "Temporary HR", "email": "temporary-hr@example.com", "password": "temporary-hr-password-123"})
    assert hr.status_code == 201
    with backend_client.app.state.session_factory() as db:
        hr_user = db.scalar(select(User).where(User.email == "temporary-hr@example.com"))
        tokens = issue_session(db, hr_user, backend_client.app.state.settings)
        db.commit()
    deactivated = backend_client.patch(f"/api/users/{hr.json()['id']}/active?is_active=false")
    assert deactivated.status_code == 200

    backend_client.cookies.set("screening_access", tokens.access_token, path="/")
    assert backend_client.get("/api/auth/me").status_code == 401


def test_audit_metadata_removes_secret_fields():
    cleaned = safe_metadata({"resource_id": 17, "password": "not-stored", "nested": {"access_token": "not-stored", "action": "review"}})
    assert cleaned == {"resource_id": 17, "nested": {"action": "review"}}


def test_production_settings_require_secure_cookies_and_explicit_origins():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", database_url="postgresql+psycopg://localhost/db")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", database_url="postgresql+psycopg://localhost/db", cookie_secure=True, allowed_origins=["*"])
    settings = Settings(_env_file=None, app_env="production", database_url="postgresql+psycopg://localhost/db", cookie_secure=True, cookie_samesite="none", allowed_origins=["https://app.example.com"])
    assert settings.cookie_secure is True


def test_legacy_fastapi_app_refuses_production_start(monkeypatch):
    from fastapi_app import create_app as create_legacy_app

    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="not production-safe"):
        create_legacy_app("sqlite:///:memory:")


def test_unsafe_requests_require_csrf_and_allowed_origin(backend_client):
    register(backend_client, "CSRF Workspace", "csrf-owner@example.com")
    missing_token = backend_client.post("/api/candidates", json=candidate_payload(), headers={"X-CSRF-Token": ""})
    assert missing_token.status_code == 403
    bad_origin = backend_client.post("/api/candidates", json=candidate_payload(), headers={"Origin": "https://attacker.example"})
    assert bad_origin.status_code == 403
