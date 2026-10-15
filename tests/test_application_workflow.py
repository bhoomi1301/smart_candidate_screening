from sqlalchemy import func, select

from backend.app.models.application import Application, ApplicationStatusHistory
from backend.app.models.audit import AuditLog
from backend.app.models.user import User
from backend.app.services import applications as application_service
from test_backend_api import backend_client, register  # noqa: F401  (fixture re-export)

PASSWORD = "long-test-password-123"
HR_PASSWORD = "hr-workflow-password-123"
REJECTION_NOTE = "Lacks the required SQL experience for this role."


def make_admin(client, workspace, email):
    owner = register(client, workspace, email).json()
    with client.app.state.session_factory() as db:
        db.get(User, owner["user"]["id"]).role = "admin"
        db.commit()
    return owner["user"]


def login(client, email, password):
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def seed(client, suffix="", jobs=1):
    candidate = client.post("/api/candidates", json={
        "full_name": f"Casey Candidate{suffix}", "email": f"casey{suffix}@example.com",
        "total_experience": 4, "technical_skills": ["Python", "SQL"],
        "education": [{"degree": "BSc", "field_of_study": "Computer Science"}],
    }).json()
    created_jobs = []
    for index in range(jobs):
        created_jobs.append(client.post("/api/jobs", json={
            "title": f"Engineer {index}{suffix}",
            "required_skills": ["Python", "SQL"] if index == 0 else ["Python", "Go"],
            "minimum_experience": 3,
        }).json())
    applications = [client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": candidate["id"]}).json() for job in created_jobs]
    return candidate, created_jobs, applications


def decide(client, application_id, status, notes="", **extra):
    return client.patch(f"/api/applications/{application_id}", json={"status": status, "notes": notes, **extra})


def history(client, application_id):
    response = client.get(f"/api/applications/{application_id}/history")
    assert response.status_code == 200, response.text
    return response.json()


def test_workflow_is_documented_by_the_api(backend_client):
    register(backend_client, "Docs Workspace", "docs@example.com")
    workflow = backend_client.get("/api/applications/workflow").json()
    assert workflow["statuses"] == ["Pending", "Under Review", "Shortlisted", "Rejected"]
    assert workflow["initial_status"] == "Pending"
    assert workflow["terminal_statuses"] == ["Rejected"]
    assert {item["from_status"]: item["allowed"] for item in workflow["transitions"]} == {
        "Pending": ["Under Review", "Rejected"],
        "Under Review": ["Shortlisted", "Rejected"],
        "Shortlisted": ["Under Review", "Rejected"],
        "Rejected": [],
    }
    schema = backend_client.get("/openapi.json").json()
    for path in ("/api/applications/workflow", "/api/applications/{application_id}", "/api/applications/{application_id}/history", "/api/audit-logs", "/api/users/{user_id}/activity"):
        assert path in schema["paths"], path
    decision = schema["components"]["schemas"]["ApplicationDecision"]["properties"]
    assert {"status", "notes", "expected_status"} <= set(decision)
    assert "409" in schema["paths"]["/api/applications/{application_id}"]["patch"]["responses"]


def test_valid_transitions_are_recorded_in_history(backend_client):
    admin = make_admin(backend_client, "Valid Workspace", "valid-admin@example.com")
    _, _, (application,) = seed(backend_client)
    steps = [("Under Review", "Starting review"), ("Shortlisted", ""), ("Under Review", "Second look at SQL"), ("Shortlisted", "Confirmed"), ("Rejected", REJECTION_NOTE)]
    for status, notes in steps:
        response = decide(backend_client, application["id"], status, notes)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status

    events = history(backend_client, application["id"])
    assert [(e["previous_status"], e["new_status"], e["notes"]) for e in events] == [
        (None, "Pending", "Application created"),
        ("Pending", "Under Review", "Starting review"),
        ("Under Review", "Shortlisted", ""),
        ("Shortlisted", "Under Review", "Second look at SQL"),
        ("Under Review", "Shortlisted", "Confirmed"),
        ("Shortlisted", "Rejected", REJECTION_NOTE),
    ]
    assert {e["changed_by"] for e in events} == {admin["id"]}
    assert {e["changed_by_name"] for e in events} == {"Workspace Admin"}
    assert [e["changed_at"] for e in events] == sorted(e["changed_at"] for e in events)
    final = backend_client.get(f"/api/applications/{application['id']}").json()
    assert final["decision_notes"] == REJECTION_NOTE


def test_invalid_transitions_are_rejected_without_side_effects(backend_client):
    register(backend_client, "Invalid Workspace", "invalid@example.com")
    _, _, (application,) = seed(backend_client)

    skip_review = decide(backend_client, application["id"], "Shortlisted", "Skipping review")
    assert skip_review.status_code == 409
    assert skip_review.json()["error"] == {"code": "conflict", "message": "Cannot move application from Pending to Shortlisted. Allowed: Under Review, Rejected"}
    unknown = decide(backend_client, application["id"], "Hired")
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "validation_error"
    back_to_pending = decide(backend_client, application["id"], "Pending")
    assert back_to_pending.status_code == 409  # same status without a note is not a change
    assert decide(backend_client, application["id"], "Rejected", REJECTION_NOTE).status_code == 200
    for status in ("Pending", "Under Review", "Shortlisted"):
        terminal = decide(backend_client, application["id"], status, "Reopen please")
        assert terminal.status_code == 409, status
        assert "terminal" in terminal.json()["error"]["message"]
    assert backend_client.get(f"/api/applications/{application['id']}").json()["status"] == "Rejected"
    assert len(history(backend_client, application["id"])) == 2
    assert decide(backend_client, 999999, "Under Review").status_code == 404


def test_rejection_requires_an_explanatory_note(backend_client):
    register(backend_client, "Rejection Workspace", "rejection@example.com")
    _, _, (application,) = seed(backend_client)
    for notes in ("", "     ", "too short"):
        response = decide(backend_client, application["id"], "Rejected", notes)
        assert response.status_code == 422, repr(notes)
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        assert "explanatory note of at least 10 characters" in error["details"][0]["message"]
    assert backend_client.get(f"/api/applications/{application['id']}").json()["status"] == "Pending"
    rejected = decide(backend_client, application["id"], "Rejected", REJECTION_NOTE)
    assert rejected.status_code == 200
    assert history(backend_client, application["id"])[-1]["notes"] == REJECTION_NOTE


def test_note_only_entries_keep_status_and_decision_note(backend_client):
    register(backend_client, "Notes Workspace", "notes@example.com")
    _, _, (application,) = seed(backend_client)
    decide(backend_client, application["id"], "Under Review", "Decision note")
    comment = decide(backend_client, application["id"], "Under Review", "Called the candidate; strong on Python")
    assert comment.status_code == 200
    assert comment.json()["status"] == "Under Review"
    assert comment.json()["decision_notes"] == "Decision note"
    last = history(backend_client, application["id"])[-1]
    assert (last["previous_status"], last["new_status"], last["notes"]) == ("Under Review", "Under Review", "Called the candidate; strong on Python")


def test_expected_status_prevents_lost_updates_between_reviewers(backend_client):
    register(backend_client, "Concurrency Workspace", "concurrency@example.com")
    _, _, (application,) = seed(backend_client)
    # Reviewer A and B both loaded the application while it was Pending.
    first = decide(backend_client, application["id"], "Under Review", "Reviewer A starts", expected_status="Pending")
    assert first.status_code == 200
    second = decide(backend_client, application["id"], "Rejected", REJECTION_NOTE, expected_status="Pending")
    assert second.status_code == 409
    assert second.json()["error"]["message"] == "Application is now Under Review, not Pending; reload before deciding"
    assert backend_client.get(f"/api/applications/{application['id']}").json()["status"] == "Under Review"
    assert [e["new_status"] for e in history(backend_client, application["id"])] == ["Pending", "Under Review"]


def test_status_and_history_roll_back_together(backend_client, monkeypatch):
    register(backend_client, "Rollback Workspace", "rollback@example.com")
    _, _, (application,) = seed(backend_client)

    def failing_audit(db, **kwargs):
        # An audit row pointing at a non-existent actor violates a foreign key at commit time.
        db.add(AuditLog(workspace_id=kwargs["workspace_id"], actor_id=987654, action="broken", resource_type="application", metadata_safe={}))

    monkeypatch.setattr(application_service, "record_audit", failing_audit)
    failed = decide(backend_client, application["id"], "Under Review", "Should not persist")
    assert failed.status_code == 409
    monkeypatch.undo()

    with backend_client.app.state.session_factory() as db:
        assert db.get(Application, application["id"]).status == "Pending"
        entries = db.scalar(select(func.count(ApplicationStatusHistory.id)).where(ApplicationStatusHistory.application_id == application["id"]))
        assert entries == 1
    assert decide(backend_client, application["id"], "Under Review", "Now it works").status_code == 200


def test_applications_for_two_jobs_are_independent(backend_client):
    register(backend_client, "Independent Workspace", "independent@example.com")
    candidate, (first_job, second_job), (first, second) = seed(backend_client, jobs=2)
    assert first["candidate_id"] == second["candidate_id"] == candidate["id"]
    assert first["screening_result"]["score"] != second["screening_result"]["score"]  # SQL vs Go requirements

    decide(backend_client, first["id"], "Under Review", "Good fit")
    decide(backend_client, second["id"], "Rejected", REJECTION_NOTE)
    assert backend_client.get(f"/api/applications/{first['id']}").json()["status"] == "Under Review"
    assert backend_client.get(f"/api/applications/{second['id']}").json()["status"] == "Rejected"
    assert [e["new_status"] for e in history(backend_client, first["id"])] == ["Pending", "Under Review"]
    assert [e["new_status"] for e in history(backend_client, second["id"])] == ["Pending", "Rejected"]
    profile = backend_client.get(f"/api/candidates/{candidate['id']}").json()
    assert {app["job_id"]: app["status"] for app in profile["applications"]} == {first_job["id"]: "Under Review", second_job["id"]: "Rejected"}
    assert backend_client.get(f"/api/jobs/{first_job['id']}/applications?status=Rejected").json()["total"] == 0


def test_important_actions_are_recorded_in_the_activity_log(backend_client):
    admin = make_admin(backend_client, "Audit Workspace", "audit-admin@example.com")
    candidate, (job,), (application,) = seed(backend_client)
    backend_client.put(f"/api/candidates/{candidate['id']}", json={"full_name": "Casey Updated", "email": candidate["email"], "technical_skills": ["Python", "SQL"], "total_experience": 5})
    backend_client.put(f"/api/jobs/{job['id']}", json={"title": "Engineer Updated", "required_skills": ["Python"], "minimum_experience": 2})
    backend_client.patch(f"/api/jobs/{job['id']}/status", json={"status": "closed"})
    backend_client.post(f"/api/applications/{application['id']}/screening")
    decide(backend_client, application["id"], "Under Review", "Reviewing")
    decide(backend_client, application["id"], "Under Review", "Comment only")

    logs = backend_client.get("/api/audit-logs?limit=200").json()
    actions = [item["action"] for item in logs["items"]]
    for expected in ("candidate.create", "candidate.update", "job.create", "job.update", "job.status", "application.create",
                     "screening.evaluate", "screening.recalculate", "application.decision", "application.note"):
        assert expected in actions, expected
    assert actions == [item["action"] for item in sorted(logs["items"], key=lambda item: (item["created_at"], item["id"]), reverse=True)]
    decision = next(item for item in logs["items"] if item["action"] == "application.decision")
    assert decision["actor_id"] == admin["id"] and decision["actor_name"] == "Workspace Admin"
    assert decision["metadata"] == {"job_id": job["id"], "candidate_id": candidate["id"], "previous_status": "Pending", "new_status": "Under Review", "has_notes": True}
    recalculated = [item for item in logs["items"] if item["action"] == "screening.recalculate"]
    assert {item["metadata"]["trigger"] for item in recalculated} == {"candidate_profile_changed", "job_criteria_changed"}

    filtered = backend_client.get(f"/api/audit-logs?action=application.&resource_type=application&resource_id={application['id']}").json()
    assert {item["action"] for item in filtered["items"]} == {"application.create", "application.decision", "application.note"}
    assert backend_client.get("/api/audit-logs?action=application.decision").json()["total"] == 1
    paged = backend_client.get("/api/audit-logs?skip=1&limit=2").json()
    assert [item["id"] for item in paged["items"]] == [item["id"] for item in logs["items"][1:3]]
    assert backend_client.get("/api/audit-logs?limit=201").status_code == 422


def test_hr_users_cannot_reach_administrative_records(backend_client):
    admin = make_admin(backend_client, "Roles Workspace", "roles-admin@example.com")
    hr = backend_client.post("/api/users", json={"full_name": "Riley HR", "email": "riley-hr@example.com", "password": HR_PASSWORD})
    assert hr.status_code == 201
    _, _, (application,) = seed(backend_client)
    hr_user = login(backend_client, "riley-hr@example.com", HR_PASSWORD)

    # HR can run the recruitment workflow...
    assert decide(backend_client, application["id"], "Under Review", "HR review").status_code == 200
    assert history(backend_client, application["id"])[-1]["changed_by_name"] == "Riley HR"
    # ...but cannot manage users or read other people's activity.
    assert backend_client.get("/api/users").status_code == 403
    assert backend_client.post("/api/users", json={"full_name": "X", "email": "x@example.com", "password": HR_PASSWORD}).status_code == 403
    assert backend_client.patch(f"/api/users/{admin['id']}/active?is_active=false").status_code == 403
    assert backend_client.get(f"/api/users/{admin['id']}/activity").status_code == 403
    assert backend_client.get(f"/api/audit-logs?actor_id={admin['id']}").status_code == 403
    own = backend_client.get("/api/audit-logs").json()
    assert own["total"] > 0 and {item["actor_id"] for item in own["items"]} == {hr_user["id"]}
    assert backend_client.get(f"/api/audit-logs?actor_id={hr_user['id']}").json()["total"] == own["total"]

    login(backend_client, "roles-admin@example.com", PASSWORD)
    everyone = backend_client.get("/api/audit-logs?limit=200").json()
    assert {admin["id"], hr_user["id"]} <= {item["actor_id"] for item in everyone["items"]}
    hr_activity = backend_client.get(f"/api/users/{hr_user['id']}/activity").json()
    assert hr_activity["total"] == own["total"] + 1  # plus the login that followed
    deactivated = backend_client.patch(f"/api/users/{hr_user['id']}/active?is_active=false")
    assert deactivated.status_code == 200
    assert backend_client.get("/api/audit-logs?action=user.deactivate").json()["items"][0]["resource_id"] == hr_user["id"]


def test_unauthenticated_and_csrf_less_decisions_are_refused(backend_client):
    for method, url in (("PATCH", "/api/applications/1"), ("GET", "/api/applications/1/history"), ("GET", "/api/audit-logs"), ("GET", "/api/applications/workflow"), ("POST", "/api/jobs/1/applications")):
        assert backend_client.request(method, url, json={"status": "Under Review"}).status_code in {401, 403}, url
    register(backend_client, "CSRF Decisions", "csrf-decisions@example.com")
    _, _, (application,) = seed(backend_client)
    assert backend_client.patch(f"/api/applications/{application['id']}", json={"status": "Under Review"}, headers={"X-CSRF-Token": ""}).status_code == 403
    assert backend_client.patch(f"/api/applications/{application['id']}", json={"status": "Under Review"}, headers={"Origin": "https://attacker.example"}).status_code == 403
    assert backend_client.get(f"/api/applications/{application['id']}").json()["status"] == "Pending"


def test_cross_tenant_workflow_isolation(backend_client):
    register(backend_client, "Tenant One", "tenant-one@example.com")
    candidate, (job,), (application,) = seed(backend_client, suffix="-one")
    decide(backend_client, application["id"], "Under Review", "Tenant one review")
    backend_client.post("/api/auth/logout")

    make_admin(backend_client, "Tenant Two", "tenant-two@example.com")
    other_candidate, _, _ = seed(backend_client, suffix="-two")
    assert decide(backend_client, application["id"], "Rejected", REJECTION_NOTE).status_code == 404
    assert backend_client.get(f"/api/applications/{application['id']}/history").status_code == 404
    assert backend_client.get(f"/api/applications/{application['id']}").status_code == 404
    assert backend_client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": other_candidate["id"]}).status_code == 404
    leaked = backend_client.get(f"/api/audit-logs?resource_type=application&resource_id={application['id']}").json()
    assert leaked["total"] == 0
    tenant_one_users = backend_client.get("/api/users").json()
    assert {user["email"] for user in tenant_one_users} == {"tenant-two@example.com"}
    backend_client.post("/api/auth/logout")

    login(backend_client, "tenant-one@example.com", PASSWORD)
    assert backend_client.get(f"/api/applications/{application['id']}").json()["status"] == "Under Review"
    assert len(history(backend_client, application["id"])) == 2
