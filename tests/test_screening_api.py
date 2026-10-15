from decimal import Decimal

from sqlalchemy import func, select

from backend.app.models.application import Application, ScreeningResult
from backend.app.services import applications as application_service
from test_backend_api import backend_client, register  # noqa: F401  (fixture re-export)


def make_job(client, **overrides):
    body = {
        "title": "Backend Engineer",
        "required_skills": ["Python", "SQL"],
        "preferred_skills": ["Docker"],
        "minimum_experience": 4,
        "qualifications": [{"name": "BSc Computer Science", "is_mandatory": True}],
        **overrides,
    }
    response = client.post("/api/jobs", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def make_candidate(client, email, skills=("Python", "SQL", "Docker"), years=5, education=({"degree": "BSc", "field_of_study": "Computer Science"},)):
    response = client.post("/api/candidates", json={
        "full_name": email.split("@")[0].title(), "email": email,
        "total_experience": years, "technical_skills": list(skills), "education": list(education),
    })
    assert response.status_code == 201, response.text
    return response.json()


def apply(client, job, candidate):
    response = client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]})
    assert response.status_code == 201, response.text
    return response.json()


def test_screening_breakdown_is_persisted_with_expected_values(backend_client):
    register(backend_client, "Screening Workspace", "screening@example.com")
    job = make_job(backend_client)
    candidate = make_candidate(backend_client, "partial@example.com", skills=["Python"], years=3)
    application = apply(backend_client, job, candidate)

    response = backend_client.get(f"/api/applications/{application['id']}/screening")
    assert response.status_code == 200
    body = response.json()
    # required 1/2 -> 25; preferred 0/1 -> 0; experience 3/4 -> 15; qualification BSc Computer Science -> 10; total 50
    assert Decimal(body["score"]) == Decimal("50.00")
    assert body["eligibility"] == "not_eligible"
    assert body["assessment_status"] == "complete"
    assert body["scoring_version"] == "screening-v2"
    assert body["is_stale"] is False
    assert body["missing_mandatory_skills"] == ["sql"]
    assert "does not make hiring decisions" in body["decision_notice"]
    breakdown = body["score_breakdown"]
    assert {name: part["points"] for name, part in breakdown["components"].items()} == {
        "required_skills": 25.0, "preferred_skills": 0.0, "experience": 15.0, "qualifications": 10.0,
    }
    assert breakdown["experience"]["meets_requirement"] is False
    assert breakdown["qualification_evidence"][0]["evidence"] == "BSc Computer Science"
    assert {w["code"] for w in breakdown["warnings"]} == {"missing_mandatory_skills", "below_minimum_experience"}

    with backend_client.app.state.session_factory() as db:
        stored = db.get(ScreeningResult, application["id"])
        assert stored.score == Decimal("50.00")
        assert stored.eligibility == "not_eligible"
        assert stored.score_breakdown["components"]["experience"]["score"] == 75.0
        assert stored.evaluated_at is not None
        assert db.get(Application, application["id"]).current_screening_score == Decimal("50.00")


def test_incomplete_candidate_is_marked_and_rescored_when_profile_changes(backend_client):
    register(backend_client, "Incomplete Workspace", "incomplete@example.com")
    job = make_job(backend_client)
    candidate = make_candidate(backend_client, "sparse@example.com", skills=["Python", "SQL"], years=None, education=())
    application = apply(backend_client, job, candidate)
    before = backend_client.get(f"/api/applications/{application['id']}/screening").json()
    # required 100% -> 50; preferred 0 -> 0; experience missing -> 0 (+20 upper); qualifications missing -> 0 (+10 upper)
    assert Decimal(before["score"]) == Decimal("50.00")
    assert before["score_breakdown"]["score_upper_bound"] == 80.0
    assert before["assessment_status"] == "incomplete"
    assert before["eligibility"] == "undetermined"

    updated = backend_client.put(f"/api/candidates/{candidate['id']}", json={
        "full_name": "Sparse", "email": "sparse@example.com", "total_experience": 6,
        "technical_skills": ["Python", "SQL", "Docker"], "education": [{"degree": "BSc", "field_of_study": "Computer Science"}],
    })
    assert updated.status_code == 200
    after = backend_client.get(f"/api/applications/{application['id']}/screening").json()
    assert Decimal(after["score"]) == Decimal("100.00")
    assert after["assessment_status"] == "complete"
    assert after["eligibility"] == "eligible"
    assert after["evaluated_at"] >= before["evaluated_at"]


def test_rejected_results_become_stale_and_refresh_recalculates(backend_client):
    register(backend_client, "Stale Workspace", "stale@example.com")
    job = make_job(backend_client)
    candidate = make_candidate(backend_client, "rejected@example.com", skills=["Python"], years=5)
    application = apply(backend_client, job, candidate)
    backend_client.patch(f"/api/applications/{application['id']}", json={"status": "Rejected", "notes": "Missing SQL"})
    original = backend_client.get(f"/api/applications/{application['id']}/screening").json()

    backend_client.put(f"/api/jobs/{job['id']}", json={"title": "Backend Engineer", "required_skills": ["Python"], "minimum_experience": 4})
    stale = backend_client.get(f"/api/applications/{application['id']}/screening").json()
    assert stale["score"] == original["score"]
    assert stale["is_stale"] is True
    assert stale["stale_reason"] == "job_criteria_changed"
    ranked = backend_client.get(f"/api/jobs/{job['id']}/rankings").json()["items"][0]
    assert ranked["is_stale"] is True

    job_refresh = backend_client.post(f"/api/jobs/{job['id']}/screening")
    assert job_refresh.json() == {"job_id": job["id"], "refreshed": 0, "include_rejected": False}
    refreshed = backend_client.post(f"/api/applications/{application['id']}/screening")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["is_stale"] is False
    assert Decimal(refreshed.json()["score"]) == Decimal("100.00")
    assert refreshed.json()["application_status"] == "Rejected"  # refresh never changes the decision
    assert backend_client.post(f"/api/jobs/{job['id']}/screening?include_rejected=true").json()["refreshed"] == 1


def test_results_from_an_older_scoring_version_are_reported_stale(backend_client):
    register(backend_client, "Version Workspace", "version@example.com")
    application = apply(backend_client, make_job(backend_client), make_candidate(backend_client, "old@example.com"))
    with backend_client.app.state.session_factory() as db:
        db.get(ScreeningResult, application["id"]).scoring_version = "weighted-v1"
        db.commit()
    body = backend_client.get(f"/api/applications/{application['id']}/screening").json()
    assert body["is_stale"] is True
    assert body["stale_reason"] == "scoring_version_changed"
    assert backend_client.post(f"/api/jobs/{application['job_id']}/screening").json()["refreshed"] == 1
    assert backend_client.get(f"/api/applications/{application['id']}/screening").json()["is_stale"] is False


def test_rankings_are_per_job_with_stable_tie_breaks(backend_client):
    register(backend_client, "Ranking Workspace", "ranking@example.com")
    job = make_job(backend_client)
    other_job = make_job(backend_client, title="Other Role")
    tie_first = make_candidate(backend_client, "tie-first@example.com", skills=["Python"], years=5)
    strong = make_candidate(backend_client, "strong@example.com")
    tie_second = make_candidate(backend_client, "tie-second@example.com", skills=["SQL"], years=5)
    sparse = make_candidate(backend_client, "sparse@example.com", skills=["Python"], years=None, education=())
    for person in (tie_first, strong, tie_second, sparse):
        apply(backend_client, job, person)
    apply(backend_client, other_job, sparse)

    page = backend_client.get(f"/api/jobs/{job['id']}/rankings").json()
    assert page["total"] == 4
    assert "created_at asc" in page["ordering"] and "does not make hiring decisions" in page["decision_notice"]
    rows = [(item["rank"], item["candidate"]["email"], item["score"], item["score_tied"]) for item in page["items"]]
    # strong 100; tie-first and tie-second: required 1/2 -> 25 + experience 20 + qualification 10 = 55; sparse 25
    assert rows == [
        (1, "strong@example.com", "100.00", False),
        (2, "tie-first@example.com", "55.00", True),
        (3, "tie-second@example.com", "55.00", True),
        (4, "sparse@example.com", "25.00", False),
    ]
    second_page = backend_client.get(f"/api/jobs/{job['id']}/rankings?skip=2&limit=2").json()
    assert [(item["rank"], item["candidate"]["email"]) for item in second_page["items"]] == [(3, "tie-second@example.com"), (4, "sparse@example.com")]
    eligible = backend_client.get(f"/api/jobs/{job['id']}/rankings?eligibility=eligible").json()
    assert [item["candidate"]["email"] for item in eligible["items"]] == ["strong@example.com"]
    undetermined = backend_client.get(f"/api/jobs/{job['id']}/rankings?eligibility=undetermined").json()
    assert undetermined["total"] == 0  # sparse is missing SQL: a confirmed failure, so not_eligible
    assert backend_client.get(f"/api/jobs/{other_job['id']}/rankings").json()["total"] == 1
    assert backend_client.get(f"/api/jobs/{job['id']}/rankings?eligibility=hired").status_code == 422
    assert backend_client.get(f"/api/jobs/{job['id']}/rankings?limit=101").status_code == 422
    assert backend_client.get("/api/jobs/9999/rankings").status_code == 404


def test_application_status_is_never_changed_by_screening(backend_client):
    register(backend_client, "Decision Workspace", "decision@example.com")
    application = apply(backend_client, make_job(backend_client), make_candidate(backend_client, "perfect@example.com"))
    assert application["screening_result"]["eligibility"] == "eligible"
    assert application["status"] == "Pending"
    backend_client.post(f"/api/applications/{application['id']}/screening")
    assert backend_client.get(f"/api/applications/{application['id']}").json()["status"] == "Pending"


def test_concurrent_duplicate_application_is_rejected_by_database_constraint(backend_client, monkeypatch):
    register(backend_client, "Race Workspace", "race@example.com")
    job = make_job(backend_client)
    candidate = make_candidate(backend_client, "race@example.com")
    apply(backend_client, job, candidate)
    # Simulate a second request that ran its duplicate pre-check before the first one committed.
    monkeypatch.setattr(application_service, "existing_application_id", lambda *args, **kwargs: None)
    racing = backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]})
    assert racing.status_code == 409
    assert racing.json()["error"]["code"] == "conflict"
    with backend_client.app.state.session_factory() as db:
        assert db.scalar(select(func.count(Application.id)).where(Application.job_id == job["id"])) == 1
        assert db.scalar(select(func.count(ScreeningResult.application_id))) == 1
    # The session recovered: later requests still work.
    assert backend_client.get(f"/api/jobs/{job['id']}/rankings").json()["total"] == 1


def test_screening_endpoints_require_auth_csrf_and_workspace(backend_client):
    for method, url in (
        ("GET", "/api/applications/1/screening"), ("POST", "/api/applications/1/screening"),
        ("POST", "/api/jobs/1/screening"), ("GET", "/api/jobs/1/rankings"),
    ):
        assert backend_client.request(method, url).status_code in {401, 403}, url

    register(backend_client, "Owner Workspace", "owner-screen@example.com")
    job = make_job(backend_client)
    application = apply(backend_client, job, make_candidate(backend_client, "private@example.com"))
    assert backend_client.post(f"/api/applications/{application['id']}/screening", headers={"X-CSRF-Token": ""}).status_code == 403
    assert backend_client.post(f"/api/jobs/{job['id']}/screening", headers={"Origin": "https://attacker.example"}).status_code == 403
    backend_client.post("/api/auth/logout")

    register(backend_client, "Intruder Workspace", "intruder-screen@example.com")
    assert backend_client.get(f"/api/applications/{application['id']}/screening").status_code == 404
    assert backend_client.post(f"/api/applications/{application['id']}/screening").status_code == 404
    assert backend_client.post(f"/api/jobs/{job['id']}/screening").status_code == 404
    assert backend_client.get(f"/api/jobs/{job['id']}/rankings").status_code == 404
    assert backend_client.get("/api/applications/0/screening").status_code == 422
