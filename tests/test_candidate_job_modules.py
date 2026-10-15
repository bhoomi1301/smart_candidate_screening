from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import event

from pdf_factory import text_pdf
from test_backend_api import backend_client, candidate_payload, job_payload, register  # noqa: F401  (fixture re-export)


def person(name, email, experience=None, skills=("Python",)):
    return {"full_name": name, "email": email, "total_experience": experience, "technical_skills": list(skills)}


@contextmanager
def count_queries(client):
    statements = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", before_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before_execute)


# Candidates ---------------------------------------------------------------


def test_candidate_validation_rejects_bad_input_with_consistent_errors(backend_client):
    register(backend_client, "Validation Workspace", "validation@example.com")
    cases = {
        "missing name": {k: v for k, v in candidate_payload().items() if k != "full_name"},
        "missing email": {k: v for k, v in candidate_payload().items() if k != "email"},
        "blank name": {**candidate_payload(), "full_name": "   "},
        "long name": {**candidate_payload(), "full_name": "x" * 161},
        "bad phone letters": {**candidate_payload(), "phone": "call me maybe"},
        "short phone": {**candidate_payload(), "phone": "12345"},
        "experience too high": {**candidate_payload(), "total_experience": 81},
        "experience precision": {**candidate_payload(), "total_experience": "2.555"},
        "empty skill": {**candidate_payload(), "technical_skills": [""]},
        "too many skills": {**candidate_payload(), "technical_skills": [f"skill-{i}" for i in range(101)]},
        "bad graduation year": {**candidate_payload(), "education": [{"degree": "BSc", "graduation_year": 1800}]},
        "unknown field": {**candidate_payload(), "status": "Shortlisted"},
    }
    for label, body in cases.items():
        response = backend_client.post("/api/candidates", json=body)
        assert response.status_code == 422, label
        error = response.json()["error"]
        assert error["code"] == "validation_error", label
        assert error["details"], label
    assert backend_client.get("/api/candidates").json()["total"] == 0


def test_candidate_input_is_normalized(backend_client):
    register(backend_client, "Normalize Workspace", "normalize@example.com")
    created = backend_client.post("/api/candidates", json={
        **candidate_payload("  Mixed.Case@Example.COM "),
        "full_name": "  Ada    Lovelace ",
        "phone": "",
        "technical_skills": ["python", "Python ", "PY", "  Machine   Learning "],
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == "mixed.case@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["phone"] is None
    assert body["technical_skills"] == ["Machine Learning", "python"]


def test_duplicate_candidates_are_scoped_per_workspace(backend_client):
    register(backend_client, "Duplicate One", "dup-one@example.com")
    assert backend_client.post("/api/candidates", json=candidate_payload("shared@example.com")).status_code == 201
    duplicate = backend_client.post("/api/candidates", json=candidate_payload("SHARED@example.com"))
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == {"code": "conflict", "message": "Candidate email already exists in this workspace"}
    backend_client.post("/api/auth/logout")

    register(backend_client, "Duplicate Two", "dup-two@example.com")
    assert backend_client.post("/api/candidates", json=candidate_payload("shared@example.com")).status_code == 201


def test_candidate_search_by_name_email_and_skill(backend_client):
    register(backend_client, "Search Workspace", "search@example.com")
    backend_client.post("/api/candidates", json=person("Grace Hopper", "grace@navy.example.com", 30, ["COBOL"]))
    backend_client.post("/api/candidates", json=person("Linus T", "linus@kernel.example.com", 25, ["C", "Git"]))
    backend_client.post("/api/candidates", json=person("Under_Score", "under@example.com", 1, ["Rust"]))

    def emails(query):
        response = backend_client.get(f"/api/candidates?{query}")
        assert response.status_code == 200, response.text
        return sorted(item["email"] for item in response.json()["items"])

    assert emails("q=hopper") == ["grace@navy.example.com"]
    assert emails("q=KERNEL.example") == ["linus@kernel.example.com"]
    assert emails("q=cobol") == ["grace@navy.example.com"]
    assert emails("skill=git") == ["linus@kernel.example.com"]
    assert emails("q=_") == ["under@example.com"]  # LIKE wildcards are matched literally
    assert emails("q=%25") == []
    assert emails("q=nobody") == []
    assert emails("min_experience=20") == ["grace@navy.example.com", "linus@kernel.example.com"]
    assert emails("max_experience=1") == ["under@example.com"]


def test_candidate_job_and_status_filters_apply_to_the_same_application(backend_client):
    register(backend_client, "Filter Workspace", "filter@example.com")
    first_job = backend_client.post("/api/jobs", json=job_payload()).json()
    second_job = backend_client.post("/api/jobs", json={**job_payload(), "title": "Data Engineer"}).json()
    ann = backend_client.post("/api/candidates", json=person("Ann", "ann@example.com", 4)).json()
    ben = backend_client.post("/api/candidates", json=person("Ben", "ben@example.com", 4)).json()
    ann_first = backend_client.post(f"/api/jobs/{first_job['id']}/applications", json={"candidate_id": ann["id"]}).json()
    backend_client.post(f"/api/jobs/{second_job['id']}/applications", json={"candidate_id": ben["id"]})
    backend_client.patch(f"/api/applications/{ann_first['id']}", json={"status": "Under Review"})

    by_job = backend_client.get(f"/api/candidates?job_id={first_job['id']}").json()
    assert [item["email"] for item in by_job["items"]] == ["ann@example.com"]
    pending_first_job = backend_client.get(f"/api/candidates?job_id={first_job['id']}&status=Pending").json()
    assert pending_first_job == {"items": [], "total": 0, "skip": 0, "limit": 25}
    pending_any_job = backend_client.get("/api/candidates?status=Pending").json()
    assert [item["email"] for item in pending_any_job["items"]] == ["ben@example.com"]
    assert backend_client.get("/api/candidates?job_id=0").status_code == 422


def test_candidate_pagination_is_stable_and_validated(backend_client):
    register(backend_client, "Pagination Workspace", "pagination@example.com")
    ids = [backend_client.post("/api/candidates", json=person(f"Person {i}", f"p{i}@example.com")).json()["id"] for i in range(7)]

    seen = []
    for skip in range(0, 7, 3):
        page = backend_client.get(f"/api/candidates?skip={skip}&limit=3").json()
        assert page["total"] == 7
        assert page["skip"] == skip and page["limit"] == 3
        seen.extend(item["id"] for item in page["items"])
    assert seen == sorted(ids, reverse=True)  # newest first, no duplicates or gaps

    beyond = backend_client.get("/api/candidates?skip=50&limit=3").json()
    assert beyond == {"items": [], "total": 7, "skip": 50, "limit": 3}
    for bad in ("limit=0", "limit=101", "skip=-1", "limit=abc"):
        assert backend_client.get(f"/api/candidates?{bad}").status_code == 422, bad


def test_candidate_list_and_profile_use_constant_query_counts(backend_client):
    register(backend_client, "Query Count Workspace", "queries@example.com")
    job = backend_client.post("/api/jobs", json=job_payload()).json()

    def add(count, offset):
        for i in range(offset, offset + count):
            created = backend_client.post("/api/candidates", json={**candidate_payload(f"q{i}@example.com"), "full_name": f"Query {i}"}).json()
            backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": created["id"]})
        return created["id"]

    add(2, 0)
    with count_queries(backend_client) as small:
        backend_client.get("/api/candidates?limit=100")
    last_id = add(20, 2)
    with count_queries(backend_client) as large:
        backend_client.get("/api/candidates?limit=100")
    assert len(large) == len(small)

    with count_queries(backend_client) as profile_queries:
        assert backend_client.get(f"/api/candidates/{last_id}").status_code == 200
    with count_queries(backend_client) as job_view:
        assert backend_client.get(f"/api/jobs/{job['id']}/applications?limit=100").json()["total"] == 22
    assert len(profile_queries) <= 12
    assert len(job_view) <= 12


def test_missing_candidate_records_return_not_found(backend_client):
    register(backend_client, "Missing Workspace", "missing@example.com")
    for method, url, body in (
        ("get", "/api/candidates/9999", None),
        ("put", "/api/candidates/9999", candidate_payload()),
        ("delete", "/api/candidates/9999", None),
        ("delete", "/api/candidates/9999/resume", None),
    ):
        response = backend_client.request(method.upper(), url, json=body)
        assert response.status_code == 404, url
        assert response.json()["error"] == {"code": "not_found", "message": "Candidate not found"}
    assert backend_client.get("/api/candidates/0").status_code == 422


# Jobs ---------------------------------------------------------------------


def test_job_validation_enforces_sensible_weights_and_criteria(backend_client):
    register(backend_client, "Job Validation Workspace", "job-validation@example.com")
    base = job_payload()
    cases = {
        "no required skills": {**base, "required_skills": []},
        "zero required weight": {**base, "criterion_weights": {"required_skills": 0, "preferred_skills": 40, "experience": 40, "qualifications": 20}},
        "negative weight": {**base, "criterion_weights": {"required_skills": 110, "preferred_skills": -10, "experience": 0, "qualifications": 0}},
        "weights over 100": {**base, "criterion_weights": {"required_skills": 60, "preferred_skills": 20, "experience": 20, "qualifications": 10}},
        "alias duplicate": {**base, "required_skills": ["Python", "py"]},
        "required and preferred overlap": {**base, "preferred_skills": ["python"]},
        "skill weights partial": {**base, "required_skill_weights": {"Python": 100}},
        "skill weights unknown skill": {**base, "required_skill_weights": {"Python": 50, "Go": 50}},
        "duplicate qualification": {**base, "qualifications": [{"name": "BSc"}, {"name": "bsc"}]},
        "qualification weights partial": {**base, "qualifications": [{"name": "BSc", "weight": 100}, {"name": "AWS"}]},
        "qualification weights sum": {**base, "qualifications": [{"name": "BSc", "weight": 30}, {"name": "AWS", "weight": 30}]},
        "experience negative": {**base, "minimum_experience": -1},
        "experience too high": {**base, "minimum_experience": 81},
        "blank title": {**base, "title": "  "},
        "title too long": {**base, "title": "x" * 181},
        "client workspace": {**base, "workspace_id": 1},
        "client status on create": {**base, "status": "closed"},
    }
    for label, body in cases.items():
        response = backend_client.post("/api/jobs", json=body)
        assert response.status_code == 422, label
        assert response.json()["error"]["code"] == "validation_error", label

    valid = backend_client.post("/api/jobs", json={
        **base,
        "department": "   ",
        "qualifications": [{"name": "BSc", "weight": 60}, {"name": "AWS", "weight": 40, "is_mandatory": False}],
    })
    assert valid.status_code == 201, valid.text
    assert valid.json()["department"] is None
    assert valid.json()["status"] == "open"
    assert valid.json()["application_count"] == 0
    assert backend_client.get("/api/jobs").json()["total"] == 1


def test_job_list_search_department_filter_and_pagination(backend_client):
    register(backend_client, "Job List Workspace", "job-list@example.com")
    titles = [("Backend Engineer", "Engineering"), ("Data Analyst", "Analytics"), ("Platform Engineer", "Engineering"), ("Recruiter", None)]
    created = [backend_client.post("/api/jobs", json={**job_payload(), "title": title, "department": dept}).json() for title, dept in titles]
    backend_client.patch(f"/api/jobs/{created[0]['id']}/status", json={"status": "closed"})

    def titles_for(query):
        response = backend_client.get(f"/api/jobs?{query}")
        assert response.status_code == 200, response.text
        return [item["title"] for item in response.json()["items"]]

    assert titles_for("q=engineer") == ["Platform Engineer", "Backend Engineer"]
    assert titles_for("q=analytics") == ["Data Analyst"]
    assert titles_for("department=engineering&status=open") == ["Platform Engineer"]
    assert titles_for("status=closed") == ["Backend Engineer"]
    first = backend_client.get("/api/jobs?skip=0&limit=3").json()
    second = backend_client.get("/api/jobs?skip=3&limit=3").json()
    assert first["total"] == second["total"] == 4
    assert [item["id"] for item in first["items"] + second["items"]] == [job["id"] for job in reversed(created)]
    for bad in ("status=archived", "limit=0", "limit=101", "skip=-1"):
        assert backend_client.get(f"/api/jobs?{bad}").status_code == 422, bad


def test_closed_jobs_reject_criteria_updates_and_new_applications(backend_client):
    register(backend_client, "Closed Job Workspace", "closed-job@example.com")
    job = backend_client.post("/api/jobs", json=job_payload()).json()
    candidate = backend_client.post("/api/candidates", json=candidate_payload()).json()
    application = backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]}).json()

    assert backend_client.put(f"/api/jobs/{job['id']}", json={**job_payload(), "status": "closed"}).status_code == 422
    closed = backend_client.patch(f"/api/jobs/{job['id']}/status", json={"status": "closed"})
    assert closed.json()["status"] == "closed"
    assert closed.json()["application_count"] == 1
    assert backend_client.patch(f"/api/jobs/{job['id']}/status", json={"status": "closed"}).status_code == 200
    assert backend_client.patch(f"/api/jobs/{job['id']}/status", json={"status": "archived"}).status_code == 422

    blocked = backend_client.put(f"/api/jobs/{job['id']}", json={**job_payload(), "title": "Changed"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "conflict"
    other = backend_client.post("/api/candidates", json=candidate_payload("other@example.com")).json()
    assert backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": other["id"]}).status_code == 409
    assert backend_client.delete(f"/api/jobs/{job['id']}").status_code == 409

    # History of a closed job stays readable.
    view = backend_client.get(f"/api/jobs/{job['id']}/applications").json()
    assert view["total"] == 1 and view["items"][0]["id"] == application["id"]
    assert backend_client.get(f"/api/applications/{application['id']}/history").json()[0]["new_status"] == "Pending"

    reopened = backend_client.patch(f"/api/jobs/{job['id']}/status", json={"status": "open"})
    assert reopened.json()["status"] == "open"
    assert backend_client.put(f"/api/jobs/{job['id']}", json={**job_payload(), "title": "Changed"}).json()["title"] == "Changed"


def test_job_update_keeps_score_snapshot_of_rejected_applications(backend_client):
    register(backend_client, "Snapshot Workspace", "snapshot@example.com")
    payload = {**job_payload(), "required_skills": ["Python", "SQL"], "required_skill_weights": {"Python": 80, "SQL": 20}}
    job = backend_client.post("/api/jobs", json=payload).json()
    active = backend_client.post("/api/candidates", json=person("Active", "active@example.com", 5, ["Python"])).json()
    rejected = backend_client.post("/api/candidates", json=person("Rejected", "rejected@example.com", 5, ["Python"])).json()
    active_app = backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": active["id"]}).json()
    rejected_app = backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": rejected["id"]}).json()
    backend_client.patch(f"/api/applications/{rejected_app['id']}", json={"status": "Rejected", "notes": "Not a fit for the SQL-heavy role"})
    original = Decimal(rejected_app["current_screening_score"])

    updated = backend_client.put(f"/api/jobs/{job['id']}", json={**payload, "required_skill_weights": {"Python": 20, "SQL": 80}})
    assert updated.status_code == 200, updated.text

    active_after = backend_client.get(f"/api/applications/{active_app['id']}").json()
    rejected_after = backend_client.get(f"/api/applications/{rejected_app['id']}").json()
    assert Decimal(active_after["current_screening_score"]) < Decimal(active_app["current_screening_score"])
    assert Decimal(rejected_after["current_screening_score"]) == original
    assert [event["new_status"] for event in rejected_after["status_history"]] == ["Pending", "Rejected"]


def test_job_specific_candidate_views(backend_client):
    register(backend_client, "Job View Workspace", "job-view@example.com")
    job = backend_client.post("/api/jobs", json=job_payload()).json()
    strong = backend_client.post("/api/candidates", json=person("Strong", "strong@example.com", 6, ["Python", "SQL", "PostgreSQL"])).json()
    weak = backend_client.post("/api/candidates", json=person("Weak", "weak@example.com", 1, ["Excel"])).json()
    for candidate in (weak, strong):
        backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]})

    view = backend_client.get(f"/api/jobs/{job['id']}/applications").json()
    assert [item["candidate"]["email"] for item in view["items"]] == ["strong@example.com", "weak@example.com"]
    rankings = backend_client.get(f"/api/jobs/{job['id']}/rankings").json()
    assert rankings["items"][0]["candidate"]["id"] == strong["id"]
    assert backend_client.get(f"/api/jobs/{job['id']}").json()["application_count"] == 2
    assert backend_client.get(f"/api/jobs/{job['id']}/applications?status=Hired").status_code == 422
    assert backend_client.get("/api/jobs/9999/applications").status_code == 404


# Permissions and tenant isolation -----------------------------------------


def test_candidate_and_job_endpoints_require_authentication(backend_client):
    for method, url in (
        ("GET", "/api/candidates"), ("POST", "/api/candidates"), ("GET", "/api/candidates/1"),
        ("PUT", "/api/candidates/1"), ("DELETE", "/api/candidates/1"),
        ("GET", "/api/jobs"), ("POST", "/api/jobs"), ("GET", "/api/jobs/1"), ("PUT", "/api/jobs/1"),
        ("PATCH", "/api/jobs/1/status"), ("DELETE", "/api/jobs/1"), ("GET", "/api/jobs/1/applications"),
    ):
        response = backend_client.request(method, url)
        assert response.status_code in {401, 403}, f"{method} {url}"


def test_cross_tenant_mutations_cannot_touch_other_workspace_records(backend_client):
    register(backend_client, "Tenant A", "tenant-a@example.com")
    candidate = backend_client.post("/api/candidates", json=candidate_payload("tenant-a-candidate@example.com")).json()
    job = backend_client.post("/api/jobs", json=job_payload()).json()
    backend_client.post("/api/auth/logout")

    register(backend_client, "Tenant B", "tenant-b@example.com")
    own_candidate = backend_client.post("/api/candidates", json=candidate_payload("tenant-b-candidate@example.com")).json()
    own_job = backend_client.post("/api/jobs", json=job_payload()).json()
    attempts = [
        backend_client.put(f"/api/candidates/{candidate['id']}", json=candidate_payload("hijack@example.com")),
        backend_client.delete(f"/api/candidates/{candidate['id']}"),
        backend_client.post(f"/api/candidates/{candidate['id']}/resume", files={"file": ("cv.pdf", text_pdf(["Hijack attempt with text"]), "application/pdf")}),
        backend_client.put(f"/api/jobs/{job['id']}", json=job_payload()),
        backend_client.patch(f"/api/jobs/{job['id']}/status", json={"status": "closed"}),
        backend_client.delete(f"/api/jobs/{job['id']}"),
        backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": own_candidate["id"]}),
        backend_client.post(f"/api/jobs/{own_job['id']}/applications", json={"candidate_id": candidate["id"]}),
    ]
    assert [response.status_code for response in attempts] == [404] * len(attempts)
    assert backend_client.get(f"/api/candidates?job_id={job['id']}").json()["total"] == 0
    assert backend_client.get("/api/candidates?q=tenant-a").json()["total"] == 0
    assert backend_client.get("/api/jobs").json()["total"] == 1
    backend_client.post("/api/auth/logout")

    backend_client.post("/api/auth/login", json={"email": "tenant-a@example.com", "password": "long-test-password-123"})
    original_candidate = backend_client.get(f"/api/candidates/{candidate['id']}").json()
    original_job = backend_client.get(f"/api/jobs/{job['id']}").json()
    assert original_candidate["email"] == "tenant-a-candidate@example.com"
    assert original_candidate["resume"] is None
    assert original_job["status"] == "open"
