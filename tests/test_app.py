import pytest
from fastapi.testclient import TestClient

from fastapi_app import create_app


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "admin@company.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin123")
    monkeypatch.setenv("HR_PASSWORD", "hr123")
    application = create_app("sqlite:///:memory:")
    with TestClient(application) as client:
        yield client


def login(client, email="admin@company.com", password="admin123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_unauthenticated_api_access_is_rejected(app_client):
    response = app_client.get("/api/candidates")
    assert response.status_code == 401


def test_login_session_and_role_are_exposed(app_client):
    response = login(app_client)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert app_client.get("/api/auth/me").json()["email"] == "admin@company.com"


def test_invalid_credentials_are_rejected(app_client):
    response = login(app_client, password="wrong-password")
    assert response.status_code == 401


def test_hr_can_manage_candidates_but_cannot_manage_jobs(app_client):
    response = login(app_client, "hr@company.com", "hr123")
    assert response.status_code == 200
    created = app_client.post("/api/candidates", json={
        "name": "Jordan Lee",
        "email": "jordan.lee@example.com",
        "experience": 4,
        "skills": ["Python", "SQL"],
        "education": ["BSc Computer Science"],
    })
    assert created.status_code == 201
    denied = app_client.post("/api/jobs", json={"title": "Engineer", "required_skills": ["Python"]})
    assert denied.status_code == 403


def test_candidate_duplicate_is_conflict_and_filters_are_paginated(app_client):
    login(app_client)
    payload = {"name": "Jordan Lee", "email": "jordan.lee@example.com", "experience": 4, "skills": ["Python"]}
    assert app_client.post("/api/candidates", json=payload).status_code == 201
    duplicate = app_client.post("/api/candidates", json=payload)
    assert duplicate.status_code == 409
    results = app_client.get("/api/candidates?q=jordan&skip=0&limit=1")
    assert results.status_code == 200
    assert results.json()["count"] == 1
    assert results.json()["items"][0]["email"] == "jordan.lee@example.com"


def test_candidate_update_recalculates_application_and_delete_cascades(app_client):
    login(app_client)
    job = app_client.get("/api/jobs").json()["items"][0]
    candidate = app_client.post("/api/candidates", json={
        "name": "Taylor Morgan",
        "email": "taylor.morgan@example.com",
        "experience": 0,
        "skills": [],
        "education": [],
    }).json()
    application = app_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]}).json()
    updated = app_client.put(f"/api/candidates/{candidate['id']}", json={
        "name": "Taylor Morgan",
        "email": "taylor.morgan@example.com",
        "experience": 5,
        "skills": ["Python", "SQL", "API Design"],
        "education": ["BSc Computer Science"],
    })
    assert updated.status_code == 200
    ranking = app_client.get(f"/api/jobs/{job['id']}/rankings").json()["items"]
    changed = next(row for row in ranking if row["id"] == application["id"])
    assert changed["score"] > application["score"]
    assert app_client.delete(f"/api/candidates/{candidate['id']}").status_code == 204
    assert app_client.get(f"/api/candidates/{candidate['id']}").status_code == 404


def test_job_specific_application_has_explainable_score(app_client):
    login(app_client)
    job = app_client.get("/api/jobs").json()["items"][0]
    candidate = app_client.post("/api/candidates", json={
        "name": "Sam Rivera",
        "email": "sam.rivera@example.com",
        "experience": 5,
        "skills": ["Python", "SQL", "API Design", "Postgres"],
        "education": ["BSc Computer Science"],
    }).json()
    created = app_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]})
    assert created.status_code == 201
    result = created.json()
    assert result["job_id"] == job["id"]
    assert result["score"] > 0
    assert "required_skills" in result["score_breakdown"]["components"]
    assert result["score_breakdown"]["matched_skills"]
    duplicate = app_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]})
    assert duplicate.status_code == 409


def test_application_status_history_and_transition_validation(app_client):
    login(app_client)
    application = app_client.get("/api/applications").json()["items"][0]
    invalid = app_client.patch(f"/api/applications/{application['id']}", json={"status": "Shortlisted"})
    assert invalid.status_code == 409
    decision = app_client.patch(f"/api/applications/{application['id']}", json={"status": "Under Review", "notes": "Reviewing experience"})
    assert decision.status_code == 200
    assert decision.json()["status"] == "Under Review"
    assert decision.json()["notes"] == "Reviewing experience"
    history = app_client.get(f"/api/applications/{application['id']}/history").json()["items"]
    assert [entry["to_status"] for entry in history] == ["Pending", "Under Review"]
    shortlisted = app_client.patch(f"/api/applications/{application['id']}", json={"status": "Shortlisted"})
    assert shortlisted.status_code == 200


def test_analytics_uses_seeded_database_records(app_client):
    login(app_client)
    summary = app_client.get("/api/analytics/dashboard").json()
    assert summary["total_candidates"] == 4
    assert summary["active_vacancies"] == 2
    assert summary["average_scores_by_job"]
    assert summary["top_applicants"]


def test_job_edit_recalculates_scores_and_closed_jobs_reject_applications(app_client):
    login(app_client)
    job = app_client.get("/api/jobs").json()["items"][0]
    original = app_client.get(f"/api/jobs/{job['id']}/rankings").json()["items"][0]
    update = {
        "title": job["title"],
        "description": job["description"],
        "required_skills": ["Scala"],
        "preferred_skills": [],
        "required_qualifications": [],
        "min_experience": 0,
        "weights": {"required_skills": 100},
    }
    changed = app_client.put(f"/api/jobs/{job['id']}", json=update)
    assert changed.status_code == 200
    ranking = app_client.get(f"/api/jobs/{job['id']}/rankings").json()["items"]
    assert ranking[0]["score"] != original["score"]
    assert ranking[0]["score_breakdown"]["missing_skills"] == ["scala"]
    assert app_client.patch(f"/api/jobs/{job['id']}/status", json={"status": "CLOSED"}).status_code == 200
    candidate = app_client.post("/api/candidates", json={"name": "Rae Kim", "email": "rae.kim@example.com", "skills": ["Scala"]}).json()
    rejected = app_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]})
    assert rejected.status_code == 409


def test_candidate_profile_and_role_aware_job_pages_render(app_client):
    login(app_client)
    profile = app_client.get("/candidates/1")
    assert profile.status_code == 200
    assert b"Ava Patel" in profile.content
    assert b"Applications" in profile.content
    admin_jobs = app_client.get("/jobs")
    assert admin_jobs.status_code == 200
    assert b"Preferred Skills" in admin_jobs.content
    second_job = app_client.get("/api/jobs").json()["items"][1]
    created = app_client.post("/candidates/1/applications", data={"job_id": second_job["id"]}, follow_redirects=True)
    assert created.status_code == 200
    assert b"Data Analyst" in created.content
    application = next(row for row in app_client.get(f"/api/jobs/{second_job['id']}/rankings").json()["items"] if row["candidate_id"] == 1)
    decision = app_client.post(f"/applications/{application['id']}/decision", data={"status": "Under Review", "notes": "Screening completed"}, follow_redirects=True)
    assert decision.status_code == 200
    assert b"Screening completed" in decision.content
    app_client.post("/api/auth/logout")
    login(app_client, "hr@company.com", "hr123")
    hr_jobs = app_client.get("/jobs")
    assert hr_jobs.status_code == 200
    assert b"Add Job Requirement" not in hr_jobs.content
    assert b"Close" not in hr_jobs.content


def test_server_rendered_login_and_protected_dashboard(app_client):
    assert app_client.get("/login").status_code == 200
    assert app_client.get("/dashboard", follow_redirects=False).status_code == 303
    response = app_client.post("/login", data={"email": "admin@company.com", "password": "admin123"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Dashboard" in response.content
