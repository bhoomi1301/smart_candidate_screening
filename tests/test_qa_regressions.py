"""Regression tests for defects found in the pre-submission QA review, plus coverage gaps it identified.

Runs on SQLite, and on PostgreSQL too when TEST_POSTGRES_URL is set (via the `client` fixture).
"""

import pytest

from backend.app.models.user import User
from test_analytics import client  # noqa: F401  (fixture re-export: sqlite + optional postgres)
from test_backend_api import backend_client, register  # noqa: F401  (backend_client is used by the sqlite variant of `client`)

TOO_BIG = 2_147_483_648  # one above PostgreSQL integer max
HUGE = 99_999_999_999_999_999_999


# ---- Defect 1: routing errors did not use the standard error envelope ------------------------


def test_unknown_routes_and_methods_use_the_error_envelope(client):
    missing = client.get("/api/does-not-exist")
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "message": "Not Found"}}
    wrong_method = client.delete("/api/auth/me")
    assert wrong_method.status_code == 405
    assert wrong_method.json() == {"error": {"code": "method_not_allowed", "message": "Method Not Allowed"}}
    assert "allow" in {key.lower() for key in wrong_method.headers}


# ---- Defect 2: out-of-range IDs caused 500 (SQLite) / 503 "database unavailable" (PostgreSQL) -


@pytest.mark.parametrize(
    "method, url, body",
    [
        ("GET", f"/api/candidates/{TOO_BIG}", None),
        ("GET", f"/api/candidates/{HUGE}", None),
        ("PUT", f"/api/candidates/{TOO_BIG}", {"full_name": "Valid Name", "email": "valid@example.com"}),
        ("DELETE", f"/api/candidates/{TOO_BIG}", None),
        ("GET", f"/api/candidates/{TOO_BIG}/resume/file", None),
        ("GET", f"/api/candidates?job_id={TOO_BIG}", None),
        ("GET", f"/api/candidates?skip={HUGE}", None),
        ("GET", f"/api/jobs/{TOO_BIG}", None),
        ("GET", f"/api/jobs?skip={HUGE}", None),
        ("GET", f"/api/jobs/{TOO_BIG}/applications", None),
        ("GET", f"/api/jobs/{TOO_BIG}/rankings", None),
        ("POST", "/api/jobs/1/applications", {"candidate_id": TOO_BIG}),
        ("GET", f"/api/applications/{TOO_BIG}", None),
        ("GET", f"/api/applications?job_id={TOO_BIG}", None),
        ("PATCH", f"/api/applications/{TOO_BIG}", {"status": "Under Review"}),
        ("GET", f"/api/applications/{TOO_BIG}/history", None),
        ("GET", f"/api/applications/{TOO_BIG}/screening", None),
        ("GET", f"/api/analytics/dashboard?job_id={TOO_BIG}", None),
        ("GET", f"/api/analytics/jobs/{TOO_BIG}/top-applicants", None),
        ("GET", f"/api/audit-logs?resource_id={TOO_BIG}", None),
        ("GET", f"/api/audit-logs?skip={HUGE}", None),
        ("PATCH", f"/api/users/{TOO_BIG}/active?is_active=false", None),
    ],
)
def test_out_of_range_ids_are_validation_errors_not_server_errors(client, method, url, body):
    user = register(client, "Range Workspace", "range@example.com").json()["user"]
    with client.app.state.session_factory() as db:  # admin, so role checks pass and only the ID is under test
        db.get(User, user["id"]).role = "admin"
        db.commit()
    response = client.request(method, url, json=body)
    assert response.status_code == 422, (url, response.status_code, response.text)
    assert response.json()["error"]["code"] == "validation_error"


def test_largest_valid_id_is_a_normal_not_found(client):
    register(client, "Boundary Workspace", "boundary@example.com")
    for url in ("/api/candidates/2147483647", "/api/jobs/2147483647", "/api/applications/2147483647"):
        response = client.get(url)
        assert response.status_code == 404, url
        assert response.json()["error"]["code"] == "not_found"


# ---- Coverage gaps ----------------------------------------------------------------------------


def test_logged_out_credentials_cannot_be_reused(client):
    register(client, "Logout Workspace", "logout@example.com")
    stolen = {name: value for name, value in client.cookies.items()}
    assert {"screening_access", "screening_refresh"} <= set(stolen)
    assert client.post("/api/auth/logout").status_code == 204
    for name, value in stolen.items():
        client.cookies.set(name, value, path="/api/auth" if name == "screening_refresh" else "/")
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/candidates").status_code == 401
    assert client.get("/api/auth/csrf").status_code == 401  # the revoked refresh cookie cannot mint a CSRF token
    assert client.post("/api/auth/refresh").status_code in {401, 403}


def test_admins_cannot_manage_users_of_another_workspace(client):
    victim = register(client, "Victim Workspace", "victim-admin@example.com").json()["user"]
    client.post("/api/auth/logout")
    attacker = register(client, "Attacker Workspace", "attacker-admin@example.com").json()["user"]
    with client.app.state.session_factory() as db:
        db.get(User, attacker["id"]).role = "admin"
        db.commit()
    response = client.patch(f"/api/users/{victim['id']}/active?is_active=false")
    assert response.status_code == 404
    assert victim["email"] not in client.get("/api/users").text
    assert client.get(f"/api/users/{victim['id']}/activity").json()["total"] == 0
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "victim-admin@example.com", "password": "long-test-password-123"}).status_code == 200
