import sys

from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.db.session import build_engine, build_session_factory
from backend.app.models.workspace import Workspace
from backend.app.schemas.application import ApplicationCreate, ApplicationDecision
from backend.app.schemas.auth import RegisterInput, UserCreate
from backend.app.schemas.candidate import CandidateCreate, EducationInput
from backend.app.schemas.job import JobCreate, QualificationInput
from backend.app.services.applications import create_application, update_application
from backend.app.services.auth import add_workspace_user, register_workspace
from backend.app.services.candidates import create_candidate
from backend.app.services.jobs import create_job


def seed_database() -> dict[str, int | bool]:
    settings = get_settings()
    if settings.seed_admin_password is None or settings.seed_hr_password is None:
        raise RuntimeError("Set SEED_ADMIN_PASSWORD and SEED_HR_PASSWORD before running the seed command")
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    try:
        with session_factory.begin() as db:
            existing = db.scalar(select(Workspace).where(Workspace.slug == "demo-hiring-workspace"))
            if existing is not None:
                return {"created": False, "workspace_id": existing.id, "candidates": 0, "jobs": 0, "applications": 0}

            workspace, admin = register_workspace(
                db,
                RegisterInput(
                    workspace_name="Demo Hiring Workspace",
                    full_name="Morgan Admin",
                    email=settings.admin_email,
                    password=settings.seed_admin_password.get_secret_value(),
                    password_confirmation=settings.seed_admin_password.get_secret_value(),
                ),
            )
            workspace.slug = "demo-hiring-workspace"
            admin.role = "admin"
            hr = add_workspace_user(
                db,
                UserCreate(full_name="Riley HR", email="hr@company.com", password=settings.seed_hr_password.get_secret_value()),
                admin,
            )

            developer = create_job(
                db,
                workspace.id,
                admin,
                JobCreate(
                    title="Senior Python Developer",
                    department="Engineering",
                    description="Build and operate reliable backend services.",
                    required_skills=["Python", "SQL", "API Design"],
                    preferred_skills=["PostgreSQL", "Docker", "AWS"],
                    minimum_experience=3,
                    qualifications=[QualificationInput(name="Computer Science degree", is_mandatory=False)],
                ),
            )
            analyst = create_job(
                db,
                workspace.id,
                admin,
                JobCreate(
                    title="Data Analyst",
                    department="Analytics",
                    description="Turn business data into clear decisions.",
                    required_skills=["SQL", "Python", "Data Analysis"],
                    preferred_skills=["Tableau", "Statistics"],
                    minimum_experience=2,
                ),
            )

            candidates = [
                CandidateCreate(full_name="Ava Patel", email="ava.patel@example.com", phone="+1-555-0101", total_experience=5, technical_skills=["Python", "SQL", "API Design", "PostgreSQL", "Docker"], education=[EducationInput(degree="BSc", field_of_study="Computer Science")]),
                CandidateCreate(full_name="Noah Johnson", email="noah.johnson@example.com", total_experience=2, technical_skills=["JavaScript", "HTML", "CSS"], education=[EducationInput(degree="BSc", field_of_study="Information Systems")]),
                CandidateCreate(full_name="Mia Chen", email="mia.chen@example.com", total_experience=4, technical_skills=["Python", "SQL", "Data Analysis", "Statistics"], education=[EducationInput(degree="MSc", field_of_study="Data Science")]),
                CandidateCreate(full_name="Liam Rodriguez", email="liam.rodriguez@example.com", total_experience=7, technical_skills=["Leadership", "Communication", "Teamwork"], education=[EducationInput(degree="MBA")]),
            ]
            created_candidates = [create_candidate(db, workspace.id, hr, payload) for payload in candidates]
            jobs = [developer, analyst]
            for index, candidate in enumerate(created_candidates):
                job = analyst if index == 2 else developer
                application = create_application(db, workspace.id, job.id, hr, ApplicationCreate(candidate_id=candidate.id))
                if index == 0:
                    update_application(db, workspace.id, hr, application, ApplicationDecision(status="Under Review", notes="Sample review in progress"))
        return {"created": True, "workspace_id": workspace.id, "candidates": len(created_candidates), "jobs": len(jobs), "applications": 4}
    finally:
        engine.dispose()


def main() -> None:
    try:
        result = seed_database()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print(result)


if __name__ == "__main__":
    main()
