import logging
from datetime import date

import pytest
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import build_engine
from backend.app.main import create_app
from backend.app.models.audit import AuditLog
from backend.app.models.candidate import CandidateResume, ResumeFile
from backend.app.models.user import User
from backend.app.resumes.extraction import extract_details
from backend.app.services import resumes as resume_service
from pdf_factory import SAMPLE_RESUME_LINES, blank_pdf, encrypted_pdf, text_pdf
from test_backend_api import CsrfTestClient, register

MAX_BYTES = 64 * 1024
MAX_PAGES = 3


@pytest.fixture
def client():
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite:///:memory:",
        allowed_origins=["https://frontend.example.test"],
        resume_max_bytes=MAX_BYTES,
        resume_max_pages=MAX_PAGES,
    )
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    with CsrfTestClient(create_app(settings, engine)) as test_client:
        yield test_client


def new_candidate(client, email="candidate@example.com"):
    response = client.post("/api/candidates", json={"full_name": "Original Name", "email": email, "technical_skills": ["Excel"]})
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, candidate_id, data, filename="resume.pdf", content_type="application/pdf"):
    return client.post(f"/api/candidates/{candidate_id}/resume", files={"file": (filename, data, content_type)})


def stored_counts(client):
    with client.app.state.session_factory() as db:
        return db.scalar(select(func.count(CandidateResume.id))), db.scalar(select(func.count(ResumeFile.resume_id)))


# ---- Happy path -------------------------------------------------------------------------------


def test_upload_stores_pdf_and_returns_unverified_suggestions(client):
    register(client, "Resume Workspace", "resume-admin@example.com")
    candidate = new_candidate(client)
    pdf = text_pdf(SAMPLE_RESUME_LINES)
    response = upload(client, candidate["id"], pdf, filename="../../Priya CV.pdf")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["resume"] == {**body["resume"], "original_filename": "Priya CV.pdf", "content_type": "application/pdf", "size_bytes": len(pdf), "page_count": 1, "file_available": True}

    extraction = body["extraction"]
    assert extraction["status"] == "ok"
    assert "unverified" in extraction["notice"]
    suggestions = extraction["suggestions"]
    assert suggestions["full_name"] == {"value": "Priya Natarajan", "evidence": "Priya Natarajan", "confidence": "low"}
    assert [item["value"] for item in suggestions["emails"]] == ["priya.n@example.com"]
    assert [item["value"] for item in suggestions["phones"]] == ["+1 (555) 014-2233"]
    assert {"Python", "PostgreSQL", "Docker", "Kubernetes", "AWS", "Go"} <= {item["value"] for item in suggestions["skills"]}
    assert suggestions["education"][0] == {
        "degree": "BSc", "field_of_study": "Computer Science", "institution": "University of Toronto", "graduation_year": 2017,
        "evidence": "B.Sc. in Computer Science, University of Toronto, 2017",
    }
    assert suggestions["total_experience"]["value"] == 6.0 and suggestions["total_experience"]["method"] == "stated"

    # Suggestions are never applied automatically.
    profile = client.get(f"/api/candidates/{candidate['id']}").json()
    assert (profile["full_name"], profile["technical_skills"], profile["total_experience"]) == ("Original Name", ["Excel"], None)
    assert profile["resume"]["file_available"] is True and profile["resume"]["page_count"] == 1
    assert "storage_key" not in profile["resume"]

    # Re-extraction from the stored file returns the same suggestions.
    again = client.get(f"/api/candidates/{candidate['id']}/resume/suggestions")
    assert again.status_code == 200 and again.json()["suggestions"] == suggestions


def test_download_requires_workspace_access_and_is_sent_safely(client):
    register(client, "Download Workspace", "download-admin@example.com")
    candidate = new_candidate(client)
    pdf = text_pdf(SAMPLE_RESUME_LINES)
    upload(client, candidate["id"], pdf, filename="Résumé – Priya.pdf")
    response = client.get(f"/api/candidates/{candidate['id']}/resume/file")
    assert response.status_code == 200
    assert response.content == pdf
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith('attachment; filename="resume.pdf"; filename*=UTF-8\'\'R%C3%A9sum%C3%A9')
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]
    with client.app.state.session_factory() as db:
        actions = list(db.scalars(select(AuditLog.action).where(AuditLog.resource_id == candidate["id"]).order_by(AuditLog.id)))
        metadata = [log.metadata_safe for log in db.scalars(select(AuditLog).where(AuditLog.action.like("candidate.resume%")))]
    assert actions[-2:] == ["candidate.resume_upload", "candidate.resume_download"]
    assert all("filename" not in str(item).lower() and "Priya" not in str(item) for item in metadata)


def test_replacing_and_removing_a_resume(client):
    register(client, "Replace Workspace", "replace-admin@example.com")
    candidate = new_candidate(client)
    upload(client, candidate["id"], text_pdf(["First resume with Python skills and more text"]))
    second = text_pdf(SAMPLE_RESUME_LINES)
    assert upload(client, candidate["id"], second, filename="second.pdf").status_code == 201
    assert stored_counts(client) == (1, 1)
    assert client.get(f"/api/candidates/{candidate['id']}/resume/file").content == second
    assert client.delete(f"/api/candidates/{candidate['id']}/resume").status_code == 204
    assert stored_counts(client) == (0, 0)
    assert client.get(f"/api/candidates/{candidate['id']}/resume/file").status_code == 404
    assert client.get(f"/api/candidates/{candidate['id']}/resume/suggestions").status_code == 404

    upload(client, candidate["id"], second)
    assert client.delete(f"/api/candidates/{candidate['id']}").status_code == 204
    assert stored_counts(client) == (0, 0)  # deleting the candidate deletes the file


def test_extract_endpoint_prefills_without_storing(client):
    register(client, "Extract Workspace", "extract-admin@example.com")
    response = client.post("/api/resumes/extract", files={"file": ("cv.pdf", text_pdf(SAMPLE_RESUME_LINES), "application/pdf")})
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"]["emails"][0]["value"] == "priya.n@example.com"
    assert stored_counts(client) == (0, 0)
    invalid = client.post("/api/resumes/extract", files={"file": ("cv.pdf", b"not a pdf at all", "application/pdf")})
    assert invalid.status_code == 422


def test_workspace_skills_extend_the_skill_vocabulary(client):
    register(client, "Vocabulary Workspace", "vocabulary-admin@example.com")
    client.post("/api/jobs", json={"title": "Analyst", "required_skills": ["Looker Studio"]})
    candidate = new_candidate(client)
    response = upload(client, candidate["id"], text_pdf(["Dana Analyst", "Built dashboards in Looker Studio for five years."]))
    assert "Looker Studio" in {item["value"] for item in response.json()["extraction"]["suggestions"]["skills"]}


# ---- Invalid uploads --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename, data, content_type, status, message",
    [
        ("resume.docx", b"%PDF-1.4 fake", "application/pdf", 415, "must end in .pdf"),
        ("resume.pdf", b"%PDF-1.4 fake", "image/png", 415, "Only PDF files"),
        ("resume.pdf", b"\x89PNG\r\n\x1a\n" + b"0" * 200, "application/pdf", 422, "not a PDF"),
        ("resume.pdf", b"", "application/pdf", 422, "empty"),
        ("resume.pdf", b"%PDF-1.4\n1 0 obj << /Type /Catalog >> broken", "application/pdf", 422, "damaged or malformed"),
        ("resume.pdf", "encrypted", "application/pdf", 422, "Password-protected"),
        ("resume.pdf", "too_many_pages", "application/pdf", 422, "limited to 3"),
        ("resume.pdf", "oversized", "application/pdf", 413, "1 MB or smaller"),
    ],
)
def test_invalid_uploads_are_rejected_and_nothing_is_stored(client, filename, data, content_type, status, message):
    register(client, "Invalid Workspace", "invalid-admin@example.com")
    candidate = new_candidate(client)
    payload = {
        "encrypted": lambda: encrypted_pdf(),
        "too_many_pages": lambda: text_pdf([["page one"], ["page two"], ["page three"], ["page four"]]),
        "oversized": lambda: text_pdf(SAMPLE_RESUME_LINES)[:-6] + b"0" * (MAX_BYTES + 10) + b"%%EOF\n",
    }.get(data, lambda: data)()
    response = upload(client, candidate["id"], payload, filename=filename, content_type=content_type)
    assert response.status_code == status, response.text
    assert message in response.json()["error"]["message"]
    assert stored_counts(client) == (0, 0)


def test_missing_file_field_is_a_validation_error(client):
    register(client, "Missing Workspace", "missing-admin@example.com")
    candidate = new_candidate(client)
    response = client.post(f"/api/candidates/{candidate['id']}/resume", files={"other": ("x.pdf", b"%PDF-", "application/pdf")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---- Extraction outcomes ----------------------------------------------------------------------


def test_scanned_pdf_is_stored_with_a_no_text_result(client):
    register(client, "Scanned Workspace", "scanned-admin@example.com")
    candidate = new_candidate(client)
    response = upload(client, candidate["id"], blank_pdf(2))
    assert response.status_code == 201
    extraction = response.json()["extraction"]
    assert extraction["status"] == "no_text"
    assert "scanned" in extraction["message"]
    assert extraction["suggestions"] == {"full_name": None, "emails": [], "phones": [], "skills": [], "education": [], "total_experience": None}
    assert response.json()["resume"]["page_count"] == 2


def test_text_without_recognisable_details(client):
    register(client, "Plain Workspace", "plain-admin@example.com")
    candidate = new_candidate(client)
    response = upload(client, candidate["id"], text_pdf(["the quick brown fox jumps over the lazy dog again and again"]))
    assert response.json()["extraction"]["status"] == "no_suggestions"


@pytest.mark.parametrize("target", ["extract_text", "extract_details"])
def test_extraction_failures_do_not_block_upload_or_leak_content(client, monkeypatch, caplog, target):
    register(client, "Failure Workspace", "failure-admin@example.com")
    candidate = new_candidate(client)

    def explode(*args, **kwargs):
        raise RuntimeError("priya.n@example.com Priya Natarajan")  # content-bearing message must not be logged

    monkeypatch.setattr(resume_service, target, explode)
    caplog.set_level(logging.DEBUG)
    response = upload(client, candidate["id"], text_pdf(SAMPLE_RESUME_LINES))
    assert response.status_code == 201
    assert response.json()["extraction"]["status"] == "failed"
    assert response.json()["resume"]["file_available"] is True
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in logged
    assert "priya" not in logged.lower()


def test_successful_upload_logs_no_personal_information(client, caplog):
    register(client, "Logging Workspace", "logging-admin@example.com")
    candidate = new_candidate(client)
    caplog.set_level(logging.DEBUG)
    upload(client, candidate["id"], text_pdf(SAMPLE_RESUME_LINES))
    logged = " ".join(record.getMessage() for record in caplog.records).lower()
    assert "priya" not in logged and "555" not in logged


# ---- Access control ---------------------------------------------------------------------------


def test_resume_endpoints_require_authentication_csrf_and_workspace(client):
    for method, url in (
        ("POST", "/api/candidates/1/resume"),
        ("GET", "/api/candidates/1/resume/file"),
        ("GET", "/api/candidates/1/resume/suggestions"),
        ("DELETE", "/api/candidates/1/resume"),
        ("POST", "/api/resumes/extract"),
    ):
        assert client.request(method, url).status_code in {401, 403}, url

    owner = register(client, "Owner Workspace", "owner-resume@example.com").json()["user"]
    candidate = new_candidate(client)
    no_csrf = client.post(f"/api/candidates/{candidate['id']}/resume", files={"file": ("cv.pdf", text_pdf(SAMPLE_RESUME_LINES), "application/pdf")}, headers={"X-CSRF-Token": ""})
    assert no_csrf.status_code == 403
    bad_origin = client.post("/api/resumes/extract", files={"file": ("cv.pdf", text_pdf(SAMPLE_RESUME_LINES), "application/pdf")}, headers={"Origin": "https://attacker.example"})
    assert bad_origin.status_code == 403
    assert upload(client, candidate["id"], text_pdf(SAMPLE_RESUME_LINES)).status_code == 201

    # An HR member of the same workspace can read it.
    with client.app.state.session_factory() as db:
        db.get(User, owner["id"]).role = "admin"
        db.commit()
    client.post("/api/users", json={"full_name": "Hana HR", "email": "hana-resume@example.com", "password": "hana-password-123"})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "hana-resume@example.com", "password": "hana-password-123"})
    assert client.get(f"/api/candidates/{candidate['id']}/resume/file").status_code == 200
    client.post("/api/auth/logout")

    # Another workspace sees nothing and cannot change anything.
    register(client, "Intruder Workspace", "intruder-resume@example.com")
    for method, url in (
        ("GET", f"/api/candidates/{candidate['id']}/resume/file"),
        ("GET", f"/api/candidates/{candidate['id']}/resume/suggestions"),
        ("DELETE", f"/api/candidates/{candidate['id']}/resume"),
    ):
        assert client.request(method, url).status_code == 404, url
    assert upload(client, candidate["id"], text_pdf(SAMPLE_RESUME_LINES)).status_code == 404
    assert stored_counts(client) == (1, 1)


# ---- Extractor unit tests ---------------------------------------------------------------------


def test_extractor_avoids_common_false_positives():
    text = "\n".join([
        "Lee Chen",
        "Worked at Initech 2015 - 2018 and Globex 2017 - 2020.",
        "I like to go hiking and enjoy excellent coffee.",
        "Skills: Go, R",
    ])
    suggestions = extract_details(text, today=date(2026, 10, 15))
    assert suggestions.phones == []  # year ranges are not phone numbers
    skills = {item["value"] for item in suggestions.skills}
    assert skills == {"Go", "R"}  # short words only count in the Skills section
    assert "go hiking" not in str(suggestions.skills).lower()
    # Overlapping ranges merge: Jan 2015 – Dec 2020 = 72 months.
    assert suggestions.total_experience == {"value": 6.0, "method": "date_ranges", "evidence": "2015 - 2018; 2017 - 2020"}


def test_extractor_ignores_education_dates_and_handles_present():
    text = "Jane Doe\nBachelor of Arts in History, 2010 - 2014\nAnalyst, Mar 2024 - Present"
    suggestions = extract_details(text, today=date(2026, 3, 1))
    assert suggestions.total_experience == {"value": 2.0, "method": "date_ranges", "evidence": "Mar 2024 - Present"}
    assert suggestions.education[0]["degree"] == "BA" and suggestions.education[0]["field_of_study"] == "History"
