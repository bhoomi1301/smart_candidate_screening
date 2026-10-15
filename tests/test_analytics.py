"""Dashboard analytics against a seeded workspace with hand-calculated expected values.

Seeded workspace "A" (default weights 50/20/20/10; jobs have no qualifications, so that weight is redistributed):

Jobs
  J1 Backend Engineer  (Engineering, open)   required Python, SQL; preferred Docker; min 3y   -> applicable 50+20+20 = 90
  J2 Data Analyst      (Analytics,   open)   required SQL, Excel; min 2y                       -> applicable 50+20 = 70
  J3 Platform Engineer (Engineering, closed) required Go, Kubernetes; no applications

Candidates (created 2026-01-05 unless noted)
  ann  Python, SQL, Docker, 5y
  ben  Python, 2y
  cat  no skills, no experience
  dan  SQL, Excel, 1y
  eve  Python, 3y (created 2026-05-01, never applies)

Applications (created date)               status         score
  ann -> J1 (2026-03-01)  100% everything    Shortlisted    100.00
  ben -> J1 (2026-03-02)  1/2 req, 2/3 exp   Rejected        42.59  = 55.5556*0.5 + 22.2222*(2/3)
  cat -> J1 (2026-03-03)  no evidence        Pending          0.00  (incomplete)
  ann -> J2 (2026-01-10)  1/2 req, exp ok    Pending         64.29  = 71.4286*0.5 + 28.5714
  dan -> J2 (2026-01-11)  2/2 req, 1/2 exp   Under Review    85.71  = 71.4286 + 28.5714*0.5
"""

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, text

from backend.app.models.application import Application
from backend.app.models.candidate import Candidate
from backend.app.models.user import User
from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import build_engine
from backend.app.main import create_app
from test_backend_api import CsrfTestClient, backend_client, register  # noqa: F401  (fixture re-export)

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

REJECTION_NOTE = "Not enough SQL experience for this role."


def at(year, month, day):
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


def seed_workspace(client, workspace="Analytics Workspace", email="analytics@example.com", prefix=""):
    owner = register(client, workspace, email).json()["user"]
    jobs = {
        "J1": {"title": f"{prefix}Backend Engineer", "department": "Engineering", "required_skills": ["Python", "SQL"], "preferred_skills": ["Docker"], "minimum_experience": 3},
        "J2": {"title": f"{prefix}Data Analyst", "department": "Analytics", "required_skills": ["SQL", "Excel"], "minimum_experience": 2},
        "J3": {"title": f"{prefix}Platform Engineer", "department": "Engineering", "required_skills": ["Go", "Kubernetes"]},
    }
    job_ids = {key: client.post("/api/jobs", json=body).json()["id"] for key, body in jobs.items()}
    people = {
        "ann": (["Python", "SQL", "Docker"], 5), "ben": (["Python"], 2), "cat": ([], None),
        "dan": (["SQL", "Excel"], 1), "eve": (["Python"], 3),
    }
    candidate_ids = {}
    for name, (skills, years) in people.items():
        response = client.post("/api/candidates", json={"full_name": f"{prefix}{name.title()} Person", "email": f"{prefix}{name}@example.com", "technical_skills": skills, "total_experience": years})
        assert response.status_code == 201, response.text
        candidate_ids[name] = response.json()["id"]
    plan = [("ann", "J1", at(2026, 3, 1)), ("ben", "J1", at(2026, 3, 2)), ("cat", "J1", at(2026, 3, 3)), ("ann", "J2", at(2026, 1, 10)), ("dan", "J2", at(2026, 1, 11))]
    applications = {}
    for name, job_key, _ in plan:
        response = client.post(f"/api/jobs/{job_ids[job_key]}/applications", json={"candidate_id": candidate_ids[name]})
        assert response.status_code == 201, response.text
        applications[(name, job_key)] = response.json()["id"]
    for (name, job_key), steps in {
        ("ann", "J1"): [("Under Review", ""), ("Shortlisted", "Strong match")],
        ("ben", "J1"): [("Rejected", REJECTION_NOTE)],
        ("dan", "J2"): [("Under Review", "")],
    }.items():
        for status, notes in steps:
            assert client.patch(f"/api/applications/{applications[(name, job_key)]}", json={"status": status, "notes": notes}).status_code == 200
    client.patch(f"/api/jobs/{job_ids['J3']}/status", json={"status": "closed"})

    with client.app.state.session_factory() as db:
        for (name, job_key, created) in plan:
            db.get(Application, applications[(name, job_key)]).created_at = created
        for name, candidate_id in candidate_ids.items():
            db.get(Candidate, candidate_id).created_at = at(2026, 5, 1) if name == "eve" else at(2026, 1, 5)
        db.commit()
    return {"owner": owner, "jobs": job_ids, "candidates": candidate_ids, "applications": applications}


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not set"))])
def client(request):
    """Every analytics test runs on SQLite, and also on PostgreSQL when TEST_POSTGRES_URL names a disposable, migrated database."""
    if request.param == "sqlite":
        yield request.getfixturevalue("backend_client")
        return
    settings = Settings(_env_file=None, app_env="test", database_url=POSTGRES_URL, allowed_origins=["https://frontend.example.test"])
    engine = build_engine(settings)
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with CsrfTestClient(create_app(settings, engine)) as pg_client:
        yield pg_client
    engine.dispose()


@pytest.fixture
def seeded(client):
    return seed_workspace(client)


def dashboard(client, query=""):
    response = client.get(f"/api/analytics/dashboard{query}")
    assert response.status_code == 200, response.text
    return response.json()


def test_dashboard_matches_hand_calculated_values(client, seeded):
    data = dashboard(client)
    assert data["total_candidates"] == 5
    assert data["active_job_openings"] == 2
    assert data["total_applications"] == 5
    assert data["unique_applicants"] == 4  # ann applied twice
    assert data["application_statuses"] == {"pending": 2, "under_review": 1, "shortlisted": 1, "rejected": 1}
    assert data["status_distribution"] == [
        {"status": "Pending", "count": 2, "percentage": "40.00"},
        {"status": "Under Review", "count": 1, "percentage": "20.00"},
        {"status": "Shortlisted", "count": 1, "percentage": "20.00"},
        {"status": "Rejected", "count": 1, "percentage": "20.00"},
    ]
    by_job = {item["title"]: item for item in data["average_scores_by_job"]}
    assert list(by_job) == ["Backend Engineer", "Data Analyst", "Platform Engineer"]
    # J1: (100 + 42.59 + 0) / 3 = 47.53; complete only (100 + 42.59) / 2 = 71.295 -> 71.30 (half-up)
    assert by_job["Backend Engineer"] == {
        "job_id": seeded["jobs"]["J1"], "title": "Backend Engineer", "department": "Engineering", "job_status": "open",
        "application_count": 3, "scored_count": 3, "complete_count": 2, "incomplete_count": 1, "stale_count": 0,
        "unscored_count": 0, "average_score": "47.53", "average_complete_score": "71.30",
    }
    # J2: (64.29 + 85.71) / 2 = 75.00
    assert (by_job["Data Analyst"]["average_score"], by_job["Data Analyst"]["average_complete_score"]) == ("75.00", "75.00")
    # J3: no applications -> zeros and nulls, still listed
    assert by_job["Platform Engineer"] == {**by_job["Platform Engineer"], "job_status": "closed", "application_count": 0, "scored_count": 0, "average_score": None, "average_complete_score": None}
    # Overall: 292.59 / 5 = 58.518 -> 58.52; complete 292.59 / 4 = 73.1475 -> 73.15
    assert data["overall_scores"] == {
        "application_count": 5, "scored_count": 5, "complete_count": 4, "incomplete_count": 1, "stale_count": 0,
        "unscored_count": 0, "average_score": "58.52", "average_complete_score": "73.15",
    }
    assert data["filters"] == {"date_from": None, "date_to": None, "job_id": None, "department": None, "job_status": None}


def test_individual_scores_used_by_the_dashboard(client, seeded):
    expected = {("ann", "J1"): "100.00", ("ben", "J1"): "42.59", ("cat", "J1"): "0.00", ("ann", "J2"): "64.29", ("dan", "J2"): "85.71"}
    for key, score in expected.items():
        assert client.get(f"/api/applications/{seeded['applications'][key]}/screening").json()["score"] == score, key


def test_dashboard_filters(client, seeded):
    engineering = dashboard(client, "?department=engineering")
    assert (engineering["total_applications"], engineering["active_job_openings"], engineering["unique_applicants"]) == (3, 1, 3)
    assert [item["title"] for item in engineering["average_scores_by_job"]] == ["Backend Engineer", "Platform Engineer"]
    assert engineering["total_candidates"] == 5  # the candidate pool is not a job-level metric

    analyst = dashboard(client, f"?job_id={seeded['jobs']['J2']}")
    assert analyst["application_statuses"] == {"pending": 1, "under_review": 1, "shortlisted": 0, "rejected": 0}
    assert analyst["overall_scores"]["average_score"] == "75.00"

    closed = dashboard(client, "?job_status=closed")
    assert closed["total_applications"] == 0 and closed["active_job_openings"] == 0
    assert all(item["percentage"] == "0.00" for item in closed["status_distribution"])
    assert closed["overall_scores"]["average_score"] is None

    january = dashboard(client, "?date_from=2026-01-01&date_to=2026-01-31")
    assert (january["total_candidates"], january["total_applications"], january["unique_applicants"]) == (4, 2, 2)
    assert {item["title"]: item["application_count"] for item in january["average_scores_by_job"]} == {"Backend Engineer": 0, "Data Analyst": 2, "Platform Engineer": 0}
    assert dashboard(client, "?date_from=2026-01-10&date_to=2026-01-10")["total_applications"] == 1  # inclusive day
    assert dashboard(client, "?date_from=2026-03-02")["total_applications"] == 2
    assert dashboard(client, "?date_to=2026-01-09")["total_applications"] == 0

    assert client.get("/api/analytics/dashboard?date_from=2026-02-01&date_to=2026-01-01").status_code == 422
    assert client.get("/api/analytics/dashboard?date_from=not-a-date").status_code == 422
    assert client.get("/api/analytics/dashboard?job_status=archived").status_code == 422
    assert client.get("/api/analytics/dashboard?job_id=999999").status_code == 404


def test_stale_and_unscored_results_are_counted_transparently(client, seeded):
    # Changing J1's criteria rescores active applications and marks the rejected one (ben) stale.
    client.put(f"/api/jobs/{seeded['jobs']['J1']}", json={"title": "Backend Engineer", "department": "Engineering", "required_skills": ["Python", "SQL"], "preferred_skills": ["Docker"], "minimum_experience": 3})
    j1 = next(item for item in dashboard(client)["average_scores_by_job"] if item["job_id"] == seeded["jobs"]["J1"])
    assert (j1["stale_count"], j1["scored_count"], j1["average_score"]) == (1, 3, "47.53")
    with client.app.state.session_factory() as db:
        db.get(Application, seeded["applications"][("cat", "J1")]).screening_result = None
        db.commit()
    j1 = next(item for item in dashboard(client)["average_scores_by_job"] if item["job_id"] == seeded["jobs"]["J1"])
    # Unscored applications are counted but excluded from averages: (100 + 42.59) / 2 = 71.295 -> 71.30
    assert (j1["application_count"], j1["scored_count"], j1["unscored_count"], j1["incomplete_count"], j1["average_score"]) == (3, 2, 1, 0, "71.30")


def test_top_applicants_for_a_job(client, seeded):
    response = client.get(f"/api/analytics/jobs/{seeded['jobs']['J1']}/top-applicants?limit=2")
    assert response.status_code == 200
    body = response.json()
    assert (body["job_title"], body["job_status"], body["total_applicants"]) == ("Backend Engineer", "open", 3)
    assert [(item["rank"], item["candidate"]["full_name"], item["score"], item["eligibility"]) for item in body["items"]] == [
        (1, "Ann Person", "100.00", "eligible"),
        (2, "Ben Person", "42.59", "not_eligible"),
    ]
    assert "does not make hiring decisions" in body["decision_notice"]
    eligible = client.get(f"/api/analytics/jobs/{seeded['jobs']['J1']}/top-applicants?eligibility=eligible").json()
    assert [item["candidate"]["full_name"] for item in eligible["items"]] == ["Ann Person"]
    empty = client.get(f"/api/analytics/jobs/{seeded['jobs']['J3']}/top-applicants").json()
    assert (empty["total_applicants"], empty["items"]) == (0, [])
    assert client.get(f"/api/analytics/jobs/{seeded['jobs']['J1']}/top-applicants?limit=51").status_code == 422
    assert client.get("/api/analytics/jobs/999999/top-applicants").status_code == 404


def test_skill_gaps(client, seeded):
    # Applications with skill data: ann-J1, ben-J1, ann-J2, dan-J2 (cat has none -> excluded).
    # SQL: required by J1 and J2, evaluated 4, missing 1 (ben) -> 25%
    # Python: evaluated 2 (below default minimum 3); Excel: evaluated 2, missing 1 (ann)
    default = client.get("/api/analytics/skill-gaps").json()
    assert default["sufficient_data"] is True
    assert default["excluded_without_skill_data"] == 1
    assert default["items"] == [{"skill": "SQL", "jobs_requiring": 2, "evaluated_applications": 4, "missing_count": 1, "missing_rate": "25.00"}]

    lower = client.get("/api/analytics/skill-gaps?min_applications=2").json()
    # Python is evaluated but never missing, so it is not a gap. Ties on missing_count -> higher rate first.
    assert [(item["skill"], item["missing_count"], item["evaluated_applications"], item["missing_rate"]) for item in lower["items"]] == [
        ("Excel", 1, 2, "50.00"), ("SQL", 1, 4, "25.00"),
    ]
    assert client.get("/api/analytics/skill-gaps?min_applications=2&limit=1").json()["items"][0]["skill"] == "Excel"

    scarce = client.get("/api/analytics/skill-gaps?min_applications=5").json()
    assert (scarce["sufficient_data"], scarce["items"]) == (False, [])
    assert "Not enough data" in scarce["message"]
    analyst = client.get(f"/api/analytics/skill-gaps?job_id={seeded['jobs']['J2']}&min_applications=1").json()
    assert [(item["skill"], item["evaluated_applications"]) for item in analyst["items"]] == [("Excel", 2)]
    assert analyst["excluded_without_skill_data"] == 0
    january = client.get("/api/analytics/skill-gaps?date_to=2026-01-31&min_applications=1").json()
    assert {item["skill"] for item in january["items"]} == {"Excel"}


def test_recent_activity_feed(client, seeded):
    feed = client.get("/api/analytics/activity?limit=100").json()
    actions = [item["action"] for item in feed["items"]]
    assert feed["total"] == len(feed["items"])
    assert not any(action.startswith(("auth.", "user.", "workspace.")) for action in actions)
    assert {"candidate.create", "job.create", "job.status", "application.create", "application.decision", "screening.evaluate"} <= set(actions)
    rejection = next(item for item in feed["items"] if item["action"] == "application.decision" and "Rejected" in item["description"])
    assert rejection["description"] == "Changed status from Pending to Rejected"
    assert (rejection["candidate_name"], rejection["job_title"], rejection["actor_name"]) == ("Ben Person", "Backend Engineer", "Workspace Admin")
    closed = next(item for item in feed["items"] if item["action"] == "job.status")
    assert (closed["description"], closed["job_title"], closed["candidate_name"]) == ("Changed status from open to closed", "Platform Engineer", None)
    keys = [(item["created_at"], item["id"]) for item in feed["items"]]
    assert keys == sorted(keys, reverse=True)

    only_jobs = client.get("/api/analytics/activity?category=job").json()
    assert {item["category"] for item in only_jobs["items"]} == {"job"} and only_jobs["total"] == 4
    assert len(client.get("/api/analytics/activity?limit=3").json()["items"]) == 3
    assert client.get("/api/analytics/activity?since=2100-01-01T00:00:00Z").json() == {"items": [], "total": 0, "limit": 20}

    # A deleted candidate keeps its activity, but its name is no longer shown.
    temp = client.post("/api/candidates", json={"full_name": "Temporary Person", "email": "temp@example.com"}).json()
    client.delete(f"/api/candidates/{temp['id']}")
    deleted = [item for item in client.get("/api/analytics/activity?category=candidate").json()["items"] if item["resource_id"] == temp["id"]]
    assert {item["action"] for item in deleted} == {"candidate.create", "candidate.delete"}
    assert {item["candidate_name"] for item in deleted} == {None}


def test_hr_users_see_workspace_dashboard_and_recruitment_activity(client, seeded):
    with client.app.state.session_factory() as db:
        db.get(User, seeded["owner"]["id"]).role = "admin"
        db.commit()
    client.post("/api/users", json={"full_name": "Hana HR", "email": "hana@example.com", "password": "hana-password-1234"})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "hana@example.com", "password": "hana-password-1234"})
    assert dashboard(client)["total_applications"] == 5
    feed = client.get("/api/analytics/activity").json()
    assert {item["actor_name"] for item in feed["items"]} == {"Workspace Admin"}  # recruitment work is shared
    assert client.get("/api/audit-logs").json()["total"] == 1  # the full audit log stays personal (just the login)


def test_empty_workspace_returns_zeros_not_errors(client):
    register(client, "Empty Workspace", "empty@example.com")
    data = dashboard(client)
    assert (data["total_candidates"], data["active_job_openings"], data["total_applications"], data["unique_applicants"]) == (0, 0, 0, 0)
    assert data["application_statuses"] == {"pending": 0, "under_review": 0, "shortlisted": 0, "rejected": 0}
    assert [item["percentage"] for item in data["status_distribution"]] == ["0.00"] * 4
    assert data["overall_scores"]["average_score"] is None and data["average_scores_by_job"] == []
    assert client.get("/api/analytics/activity").json() == {"items": [], "total": 0, "limit": 20}
    gaps = client.get("/api/analytics/skill-gaps").json()
    assert (gaps["sufficient_data"], gaps["items"], gaps["excluded_without_skill_data"]) == (False, [], 0)


def test_dashboards_never_expose_other_workspaces(client, seeded):
    client.post("/api/auth/logout")
    other = seed_workspace(client, "Other Workspace", "other@example.com", prefix="Zz")
    responses = [
        client.get("/api/analytics/dashboard"),
        client.get("/api/analytics/activity?limit=100"),
        client.get("/api/analytics/skill-gaps?min_applications=1"),
        client.get(f"/api/analytics/jobs/{other['jobs']['J1']}/top-applicants"),
    ]
    text = " ".join(response.text for response in responses)
    for leaked in ('"Ann Person"', '"ann@example.com"', '"Ben Person"', '"Dan Person"', '"Backend Engineer"', '"Data Analyst"'):
        assert leaked not in text, leaked
    assert seeded["owner"]["id"] not in {item["actor_id"] for item in responses[1].json()["items"]}
    data = responses[0].json()
    assert (data["total_candidates"], data["total_applications"]) == (5, 5)  # its own identical seed, not 10
    assert {item["job_id"] for item in data["average_scores_by_job"]}.isdisjoint(seeded["jobs"].values())
    for path in (f"/api/analytics/jobs/{seeded['jobs']['J1']}/top-applicants", f"/api/analytics/dashboard?job_id={seeded['jobs']['J1']}", f"/api/analytics/skill-gaps?job_id={seeded['jobs']['J1']}"):
        assert client.get(path).status_code == 404, path
    client.post("/api/auth/logout")
    for path in ("/api/analytics/dashboard", "/api/analytics/activity", "/api/analytics/skill-gaps", f"/api/analytics/jobs/{seeded['jobs']['J1']}/top-applicants"):
        assert client.get(path).status_code == 401, path


def test_dashboard_query_count_does_not_grow_with_data(client, seeded):
    def count_selects():
        statements = []
        engine = client.app.state.engine
        listener = lambda conn, cursor, statement, *args: statements.append(statement) if statement.lstrip().upper().startswith("SELECT") else None  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            for path in ("/api/analytics/dashboard", "/api/analytics/skill-gaps", "/api/analytics/activity?limit=100"):
                assert client.get(path).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(statements)

    before = count_selects()
    for index in range(15):
        candidate = client.post("/api/candidates", json={"full_name": f"Bulk {index}", "email": f"bulk{index}@example.com", "technical_skills": ["Python"], "total_experience": 4}).json()
        client.post(f"/api/jobs/{seeded['jobs']['J1']}/applications", json={"candidate_id": candidate["id"]})
    assert count_selects() == before
    assert dashboard(client)["total_applications"] == 20
