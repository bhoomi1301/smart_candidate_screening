"""Workflow checks against a real, Alembic-migrated PostgreSQL database.

Skipped unless TEST_POSTGRES_URL points at a disposable database migrated to head, e.g.
    DATABASE_URL=<url> python -m alembic upgrade head
    TEST_POSTGRES_URL=<url> python -m pytest tests/test_workflow_postgres.py
"""

import os
import threading
import uuid

import pytest
from sqlalchemy import text

from backend.app.core.config import Settings
from backend.app.db.session import build_engine
from backend.app.main import create_app
from test_backend_api import CsrfTestClient

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not set")
REJECTION_NOTE = "Not enough PostgreSQL experience for the role."


@pytest.fixture(scope="module")
def pg_app():
    settings = Settings(_env_file=None, app_env="test", database_url=POSTGRES_URL, allowed_origins=["https://frontend.example.test"])
    engine = build_engine(settings)
    assert engine.dialect.name == "postgresql"
    yield create_app(settings, engine)
    engine.dispose()


def new_client(app):
    return CsrfTestClient(app)


def setup_workspace(app):
    """Register a fresh workspace, add an HR user, and return logged-in admin/HR clients plus an application."""
    tag = uuid.uuid4().hex[:8]
    admin = new_client(app)
    owner = admin.post("/api/auth/register", json={
        "workspace_name": f"PG {tag}", "full_name": "PG Admin", "email": f"admin-{tag}@example.com",
        "password": "long-test-password-123", "password_confirmation": "long-test-password-123",
    }).json()
    with app.state.engine.begin() as connection:
        connection.execute(text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": owner["user"]["id"]})
    admin.post("/api/users", json={"full_name": "PG HR", "email": f"hr-{tag}@example.com", "password": "hr-test-password-123"}).raise_for_status()
    hr = new_client(app)
    hr.post("/api/auth/login", json={"email": f"hr-{tag}@example.com", "password": "hr-test-password-123"}).raise_for_status()
    candidate = admin.post("/api/candidates", json={"full_name": "PG Candidate", "email": f"cand-{tag}@example.com", "technical_skills": ["Python", "SQL"], "total_experience": 4}).json()
    job = admin.post("/api/jobs", json={"title": "PG Engineer", "required_skills": ["Python", "SQL"], "minimum_experience": 3}).json()
    application = admin.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]}).json()
    return admin, hr, owner["user"], candidate, job, application


def run_concurrently(*calls):
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def worker(index, call):
        barrier.wait()
        results[index] = call()

    threads = [threading.Thread(target=worker, args=(index, call)) for index, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


def history_rows(app, application_id):
    with app.state.engine.connect() as connection:
        return connection.execute(text(
            "SELECT previous_status, new_status, changed_by, notes, changed_at FROM application_status_history "
            "WHERE application_id = :id ORDER BY changed_at, id"
        ), {"id": application_id}).all()


def test_workflow_persists_status_history_and_audit_in_postgres(pg_app):
    admin, hr, owner, candidate, job, application = setup_workspace(pg_app)
    assert hr.patch(f"/api/applications/{application['id']}", json={"status": "Under Review", "notes": "HR review"}).status_code == 200
    assert admin.patch(f"/api/applications/{application['id']}", json={"status": "Rejected", "notes": "x"}).status_code == 422
    assert admin.patch(f"/api/applications/{application['id']}", json={"status": "Rejected", "notes": REJECTION_NOTE}).status_code == 200

    rows = history_rows(pg_app, application["id"])
    assert [(row.previous_status, row.new_status, row.notes) for row in rows] == [
        (None, "Pending", "Application created"), ("Pending", "Under Review", "HR review"), ("Under Review", "Rejected", REJECTION_NOTE),
    ]
    assert rows[1].changed_by != rows[2].changed_by and rows[2].changed_by == owner["id"]
    assert all(row.changed_at.tzinfo is not None for row in rows)
    with pg_app.state.engine.connect() as connection:
        stored = connection.execute(text("SELECT status, decision_notes FROM applications WHERE id = :id"), {"id": application["id"]}).one()
        assert tuple(stored) == ("Rejected", REJECTION_NOTE)
        actions = connection.execute(text(
            "SELECT action FROM audit_logs WHERE resource_type = 'application' AND resource_id = :id ORDER BY id"
        ), {"id": application["id"]}).scalars().all()
        assert actions == ["application.create", "screening.evaluate", "application.decision", "application.decision"]
        result = connection.execute(text("SELECT eligibility, is_stale, scoring_version FROM screening_results WHERE application_id = :id"), {"id": application["id"]}).one()
        assert tuple(result) == ("eligible", False, "screening-v2")
    assert admin.get(f"/api/applications/{application['id']}/history").json()[-1]["changed_by_name"] == "PG Admin"


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_identical_decisions_apply_exactly_once(pg_app, attempt):
    # Without the row lock both requests would read Pending and both write a Pending -> Under Review entry.
    admin, hr, _, _, _, application = setup_workspace(pg_app)
    body = {"status": "Under Review", "notes": ""}
    responses = run_concurrently(
        lambda: admin.patch(f"/api/applications/{application['id']}", json=body),
        lambda: hr.patch(f"/api/applications/{application['id']}", json=body),
    )
    assert sorted(response.status_code for response in responses) == [200, 409], [response.text for response in responses]
    rows = history_rows(pg_app, application["id"])
    assert [(row.previous_status, row.new_status) for row in rows] == [(None, "Pending"), ("Pending", "Under Review")]


def test_concurrent_conflicting_decisions_keep_history_consistent(pg_app):
    admin, hr, _, _, _, application = setup_workspace(pg_app)
    responses = run_concurrently(
        lambda: admin.patch(f"/api/applications/{application['id']}", json={"status": "Under Review", "notes": "Admin review", "expected_status": "Pending"}),
        lambda: hr.patch(f"/api/applications/{application['id']}", json={"status": "Rejected", "notes": REJECTION_NOTE, "expected_status": "Pending"}),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    rows = history_rows(pg_app, application["id"])
    assert len(rows) == 2 and rows[1].previous_status == "Pending" and rows[1].new_status == winner["status"]


def test_failed_history_write_rolls_back_status_in_postgres(pg_app, monkeypatch):
    from backend.app.models.audit import AuditLog
    from backend.app.services import applications as application_service

    admin, _, _, _, _, application = setup_workspace(pg_app)

    def failing_audit(db, **kwargs):
        db.add(AuditLog(workspace_id=kwargs["workspace_id"], actor_id=2_000_000_000, action="broken", resource_type="application", metadata_safe={}))

    monkeypatch.setattr(application_service, "record_audit", failing_audit)
    assert admin.patch(f"/api/applications/{application['id']}", json={"status": "Under Review", "notes": "Should roll back"}).status_code == 409
    monkeypatch.undo()
    with pg_app.state.engine.connect() as connection:
        assert connection.execute(text("SELECT status FROM applications WHERE id = :id"), {"id": application["id"]}).scalar() == "Pending"
    assert len(history_rows(pg_app, application["id"])) == 1
