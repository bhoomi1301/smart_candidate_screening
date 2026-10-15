import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.sessions import SessionMiddleware

from database import Application, AuditLog, Base, Candidate, Job, StatusHistory, User, create_database, get_session
from scoring import DEFAULT_WEIGHTS, calculate_match_score, normalize_items
from security import hash_password, verify_password

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="templates")
STATUSES = {"Pending", "Under Review", "Shortlisted", "Rejected"}
TRANSITIONS = {
    "Pending": {"Under Review", "Rejected"},
    "Under Review": {"Shortlisted", "Rejected"},
    "Shortlisted": {"Under Review", "Rejected"},
    "Rejected": set(),
}


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class LoginInput(InputModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class CandidateInput(InputModel):
    name: str = Field(min_length=2, max_length=160)
    email: str = Field(min_length=3, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    experience: float | None = Field(default=None, ge=0, le=80)
    skills: list[str] = Field(default_factory=list, max_length=100)
    education: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("skills", "education")
    @classmethod
    def clean_items(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class JobInput(InputModel):
    title: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=10000)
    required_skills: list[str] = Field(min_length=1, max_length=100)
    preferred_skills: list[str] = Field(default_factory=list, max_length=100)
    required_qualifications: list[str] = Field(default_factory=list, max_length=30)
    min_experience: float = Field(default=0, ge=0, le=80)
    weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    @field_validator("required_skills", "preferred_skills", "required_qualifications")
    @classmethod
    def clean_items(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, values: dict[str, float]) -> dict[str, float]:
        if set(values) - set(DEFAULT_WEIGHTS) or any(value < 0 for value in values.values()):
            raise ValueError("Weights must be non-negative and use supported score components")
        if values and sum(values.values()) <= 0:
            raise ValueError("At least one score weight must be greater than zero")
        return values


class ApplicationInput(InputModel):
    candidate_id: int = Field(gt=0)


class ApplicationDecision(InputModel):
    status: Literal["Pending", "Under Review", "Shortlisted", "Rejected"]
    notes: str = Field(default="", max_length=5000)


class JobStatusInput(InputModel):
    status: Literal["OPEN", "CLOSED"]


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def roles_allowed(*roles: str):
    def authorize(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return authorize


def optional_html_user(request: Request, db: Session = Depends(get_session)) -> User | None:
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id else None


def write_audit(db: Session, user: User | None, action: str, entity_type: str, entity_id: int | None = None, details: dict | None = None):
    db.add(AuditLog(user_id=user.id if user else None, action=action, entity_type=entity_type, entity_id=entity_id, details=details or {}))


def candidate_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "name": candidate.name,
        "email": candidate.email,
        "phone": candidate.phone,
        "experience": candidate.experience,
        "skills": list(candidate.skills or []),
        "education": list(candidate.education or []),
        "created_at": candidate.created_at,
    }


def job_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "required_skills": list(job.required_skills or []),
        "preferred_skills": list(job.preferred_skills or []),
        "required_qualifications": list(job.required_qualifications or []),
        "min_experience": job.min_experience,
        "weights": job.weights or dict(DEFAULT_WEIGHTS),
        "status": job.status,
        "is_active": job.status == "OPEN",
        "created_at": job.created_at,
    }


def user_dict(user: User) -> dict[str, Any]:
    return {"id": user.id, "email": user.email, "role": user.role}


def application_dict(item: Application) -> dict[str, Any]:
    return {
        "id": item.id,
        "candidate_id": item.candidate_id,
        "candidate": candidate_dict(item.candidate),
        "job_id": item.job_id,
        "job": job_dict(item.job),
        "status": item.status,
        "score": item.score,
        "score_breakdown": item.score_breakdown or {},
        "notes": item.notes,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def create_application(db: Session, candidate: Candidate, job: Job, user: User | None = None) -> Application:
    result = calculate_match_score(candidate_dict(candidate), job_dict(job))
    item = Application(candidate_id=candidate.id, job_id=job.id, status="Pending", score=result["score"], score_breakdown=result)
    db.add(item)
    db.flush()
    db.add(StatusHistory(application_id=item.id, to_status="Pending", changed_by=user.id if user else None, notes="Application created"))
    write_audit(db, user, "application.create", "application", item.id)
    return item


def change_application_status(db: Session, item: Application, new_status: str, notes: str, user: User):
    if new_status != item.status and new_status not in TRANSITIONS[item.status]:
        raise HTTPException(status_code=409, detail=f"Cannot move application from {item.status} to {new_status}")
    previous = item.status
    item.status = new_status
    if notes:
        item.notes = notes
    if previous != new_status or notes:
        db.add(StatusHistory(application_id=item.id, from_status=previous, to_status=new_status, changed_by=user.id, notes=notes))
        write_audit(db, user, "application.decision", "application", item.id, {"from_status": previous, "to_status": new_status})


def recalculate_job_applications(db: Session, job: Job):
    rows = db.scalars(select(Application).options(joinedload(Application.candidate)).where(Application.job_id == job.id)).all()
    for item in rows:
        result = calculate_match_score(candidate_dict(item.candidate), job_dict(job))
        item.score, item.score_breakdown = result["score"], result


def analytics_summary(db: Session, selected_job_id: int | None = None) -> dict[str, Any]:
    open_jobs = db.scalars(select(Job).where(Job.status == "OPEN").order_by(Job.id)).all()
    total_candidates = db.scalar(select(func.count(Candidate.id))) or 0
    statement = select(Application)
    if selected_job_id is not None:
        statement = statement.where(Application.job_id == selected_job_id)
    selected_apps = db.scalars(statement).all()
    status_counts = {value: 0 for value in STATUSES}
    for item in selected_apps:
        status_counts[item.status] += 1
    score_summaries = []
    for job in open_jobs:
        applications = db.scalars(select(Application).where(Application.job_id == job.id)).all()
        score_summaries.append({
            "job_id": job.id,
            "title": job.title,
            "applications": len(applications),
            "average_score": round(sum(row.score for row in applications) / len(applications), 1) if applications else 0,
        })
    top = sorted(selected_apps, key=lambda row: row.score, reverse=True)[:5]
    return {
        "total_candidates": total_candidates,
        "active_vacancies": len(open_jobs),
        "application_statuses": status_counts,
        "average_scores_by_job": score_summaries,
        "top_applicants": [application_dict(row) for row in top],
    }


def create_app(database_url: str | None = None) -> FastAPI:
    if os.getenv("APP_ENV") == "production":
        raise RuntimeError("This legacy app is not production-safe. Deploy the modular app with `uvicorn app:app`.")
    if not os.getenv("SECRET_KEY"):
        logger.warning("SECRET_KEY is unset; sessions will not survive a process restart. Set it before deployment.")
    engine, session_factory = create_database(database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        Base.metadata.create_all(engine)
        with session_factory() as db:
            if not db.scalar(select(func.count(User.id))):
                admin_password = os.getenv("ADMIN_PASSWORD")
                hr_password = os.getenv("HR_PASSWORD")
                if not admin_password or not hr_password:
                    raise RuntimeError("Set ADMIN_PASSWORD and HR_PASSWORD before initializing an empty database.")
                db.add_all([
                    User(email=os.getenv("ADMIN_EMAIL", "admin@company.com").lower(), password_hash=hash_password(admin_password), role="admin"),
                    User(email="hr@company.com", password_hash=hash_password(hr_password), role="hr"),
                ])
                db.flush()
            if not db.scalar(select(func.count(Job.id))):
                jobs = [
                    Job(title="Senior Python Developer", description="Build reliable backend services.", required_skills=["Python", "SQL", "API Design"], preferred_skills=["PostgreSQL", "Docker", "AWS"], required_qualifications=["Computer Science"], min_experience=3),
                    Job(title="Data Analyst", description="Turn business data into clear decisions.", required_skills=["SQL", "Python", "Data Analysis"], preferred_skills=["Tableau", "Statistics"], min_experience=2),
                ]
                db.add_all(jobs)
                db.flush()
                candidates = [
                    Candidate(name="Ava Patel", email="ava.patel@example.com", experience=5, skills=["Python", "SQL", "API Design", "PostgreSQL", "Docker"], education=["BSc Computer Science"]),
                    Candidate(name="Noah Johnson", email="noah.johnson@example.com", experience=2, skills=["JavaScript", "HTML", "CSS"], education=["BSc Information Systems"]),
                    Candidate(name="Mia Chen", email="mia.chen@example.com", experience=4, skills=["Python", "SQL", "Data Analysis", "Statistics"], education=["MSc Data Science"]),
                    Candidate(name="Liam Rodriguez", email="liam.rodriguez@example.com", experience=7, skills=["Leadership", "Communication", "Teamwork"], education=["MBA"]),
                ]
                db.add_all(candidates)
                db.flush()
                for candidate in candidates:
                    job = jobs[1] if candidate.name == "Mia Chen" else jobs[0]
                    create_application(db, candidate, job)
            db.commit()
        yield
        engine.dispose()

    application = FastAPI(
        title="Smart Candidate Screening API",
        version="2.0.0",
        description="Role-protected recruitment APIs with transparent, job-specific screening scores.",
        lifespan=lifespan,
    )
    application.state.session_factory = session_factory
    application.state.engine = engine
    application.add_middleware(
        SessionMiddleware,
        secret_key=os.getenv("SECRET_KEY") or secrets.token_urlsafe(32),
        same_site="lax",
        https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        max_age=28800,
    )
    application.mount("/static", StaticFiles(directory="static"), name="static")

    def render(request: Request, name: str, **context: Any):
        return templates.TemplateResponse(request, name, {"session": request.session, **context})

    def require_html_login(request: Request):
        if not request.session.get("user_id"):
            return RedirectResponse("/login", status_code=303)
        return None

    def authenticate(db: Session, email: str, password: str, request: Request):
        user = db.scalar(select(User).where(User.email == email.lower()))
        if user is None or not verify_password(password, user.password_hash):
            return None
        request.session.clear()
        request.session["user_id"] = user.id
        request.session["role"] = user.role
        write_audit(db, user, "login", "user", user.id)
        db.commit()
        return user

    @application.get("/", include_in_schema=False)
    async def home(request: Request):
        return RedirectResponse("/dashboard" if request.session.get("user_id") else "/login", status_code=303)

    @application.get("/login", response_class=HTMLResponse, name="login")
    async def login_page(request: Request):
        return render(request, "login.html", error="")

    @application.post("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_form(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_session)):
        email = email.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            return render(request, "login.html", error="Please enter a valid email and password.")
        if authenticate(db, email, password, request):
            return RedirectResponse("/dashboard", status_code=303)
        return render(request, "login.html", error="Invalid email or password.")

    @application.post("/logout", include_in_schema=False, name="logout")
    async def logout_page(request: Request, db: Session = Depends(get_session), user: User = Depends(current_user)):
        write_audit(db, user, "logout", "user", user.id)
        db.commit()
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @application.get("/dashboard", response_class=HTMLResponse, name="dashboard")
    async def dashboard(request: Request, selected_status: str = Query("All", alias="status"), job_id: int | None = None, db: Session = Depends(get_session)):
        redirect = require_html_login(request)
        if redirect:
            return redirect
        job = db.get(Job, job_id) if job_id is not None else db.scalar(select(Job).where(Job.status == "OPEN").order_by(Job.id))
        query = select(Application).options(joinedload(Application.candidate)).order_by(Application.created_at.desc())
        if job:
            query = query.where(Application.job_id == job.id)
        if selected_status in STATUSES:
            query = query.where(Application.status == selected_status)
        else:
            selected_status = "All"
        rows = db.scalars(query).all()
        job_applications = db.scalars(select(Application).where(Application.job_id == job.id)).all() if job else []
        counts = {value: sum(row.status == value for row in job_applications) for value in STATUSES}
        average = round(sum(row.score for row in job_applications) / len(job_applications), 1) if job_applications else 0
        candidates = [dict(id=row.candidate.id, name=row.candidate.name, experience=row.candidate.experience or "Not provided", match_score=row.score, status=row.status) for row in rows]
        return render(request, "dashboard.html", candidates=candidates, total_candidates=db.scalar(select(func.count(Candidate.id))) or 0, pending=counts["Pending"], under_review=counts["Under Review"], shortlisted=counts["Shortlisted"], rejected=counts["Rejected"], avg_score=average, active_status=selected_status, job_requirements=job_dict(job) if job else None, analytics=analytics_summary(db, job.id if job else None), jobs=db.scalars(select(Job).order_by(Job.status, Job.title)).all(), selected_job_id=job.id if job else None)

    @application.get("/candidates", response_class=HTMLResponse, name="candidates")
    async def candidates_page(request: Request, q: str = "", skip: int = 0, limit: int = 50, success: str = "", error: str = "", db: Session = Depends(get_session)):
        redirect = require_html_login(request)
        if redirect:
            return redirect
        query = select(Candidate)
        if q.strip():
            pattern = f"%{q.strip().lower()}%"
            query = query.where(or_(func.lower(Candidate.name).like(pattern), func.lower(Candidate.email).like(pattern), func.lower(cast(Candidate.skills, String)).like(pattern)))
        records = db.scalars(query.order_by(Candidate.created_at.desc()).offset(max(skip, 0)).limit(min(max(limit, 1), 100))).all()
        job = db.scalar(select(Job).where(Job.status == "OPEN").order_by(Job.id))
        applications = {row.candidate_id: row for row in db.scalars(select(Application).where(Application.job_id == job.id)).all()} if job else {}
        display_rows = [dict(id=row.id, name=row.name, email=row.email, experience=row.experience if row.experience is not None else "Not provided", skills=", ".join(row.skills or []), match_score=applications[row.id].score if row.id in applications else 0, status=applications[row.id].status if row.id in applications else "Not Applied") for row in records]
        return render(request, "candidates.html", candidates=display_rows, job_requirements=job_dict(job) if job else None, search_term=q, error=error, success=success)

    @application.get("/candidates/{candidate_id}", response_class=HTMLResponse, name="candidate_detail")
    async def candidate_detail(candidate_id: int, request: Request, db: Session = Depends(get_session)):
        redirect = require_html_login(request)
        if redirect:
            return redirect
        candidate = db.scalar(select(Candidate).options(joinedload(Candidate.applications).joinedload(Application.job)).where(Candidate.id == candidate_id))
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        application_records = []
        for row in candidate.applications:
            record = application_dict(row)
            history = db.scalars(select(StatusHistory).where(StatusHistory.application_id == row.id).order_by(StatusHistory.changed_at)).all()
            record["history"] = [{"from_status": event.from_status, "to_status": event.to_status, "notes": event.notes, "changed_at": event.changed_at} for event in history]
            application_records.append(record)
        existing_job_ids = {row.job_id for row in candidate.applications}
        available_jobs = db.scalars(select(Job).where(Job.status == "OPEN").order_by(Job.title)).all()
        available_jobs = [job for job in available_jobs if job.id not in existing_job_ids]
        return render(request, "candidate_detail.html", candidate=candidate_dict(candidate), applications=application_records, available_jobs=available_jobs, error=request.query_params.get("error", ""), success=request.query_params.get("success", ""))

    @application.post("/candidates/{candidate_id}/applications", name="add_application_form", include_in_schema=False)
    async def add_application_form(candidate_id: int, job_id: int = Form(...), db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin", "hr"))):
        candidate, job = db.get(Candidate, candidate_id), db.get(Job, job_id)
        if candidate is None or job is None:
            raise HTTPException(status_code=404, detail="Candidate or job not found")
        if job.status != "OPEN":
            return RedirectResponse(f"/candidates/{candidate_id}?error=This+vacancy+is+closed", status_code=303)
        if db.scalar(select(Application.id).where(Application.candidate_id == candidate_id, Application.job_id == job_id)):
            return RedirectResponse(f"/candidates/{candidate_id}?error=This+candidate+already+has+an+application+for+the+vacancy", status_code=303)
        create_application(db, candidate, job, user)
        db.commit()
        return RedirectResponse(f"/candidates/{candidate_id}?success=Application+created", status_code=303)

    @application.post("/applications/{application_id}/decision", name="update_application_form", include_in_schema=False)
    async def update_application_form(application_id: int, status_value: str = Form(..., alias="status"), notes: str = Form(""), db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin", "hr"))):
        item = db.get(Application, application_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Application not found")
        candidate_id = item.candidate_id
        try:
            update_application_status(db, item, status_value, notes.strip(), user)
            db.commit()
        except HTTPException as exc:
            db.rollback()
            return RedirectResponse(f"/candidates/{candidate_id}?error={exc.detail.replace(' ', '+')}", status_code=303)
        return RedirectResponse(f"/candidates/{candidate_id}?success=Decision+saved", status_code=303)

    @application.post("/candidates/add", name="add_candidate", include_in_schema=False)
    async def add_candidate_form(request: Request, name: str = Form(...), email: str = Form(...), experience: str = Form(""), skills: str = Form(...), phone: str = Form(""), education: str = Form(""), db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin", "hr"))):
        try:
            years = float(experience)
            if years < 0 or years > 80:
                raise ValueError
        except ValueError:
            return RedirectResponse("/candidates?error=Experience+must+be+a+valid+non-negative+number", status_code=303)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()):
            return RedirectResponse("/candidates?error=Please+enter+a+valid+email+address", status_code=303)
        candidate = Candidate(name=name.strip(), email=email.strip().lower(), phone=phone.strip() or None, experience=years, skills=sorted(normalize_items(skills)), education=sorted(normalize_items(education)))
        db.add(candidate)
        try:
            db.flush()
            job = db.scalar(select(Job).where(Job.status == "OPEN").order_by(Job.id))
            if job:
                create_application(db, candidate, job, user)
            write_audit(db, user, "candidate.create", "candidate", candidate.id)
            db.commit()
        except IntegrityError:
            db.rollback()
            return RedirectResponse("/candidates?error=A+candidate+with+this+email+already+exists", status_code=303)
        return RedirectResponse("/candidates?success=Candidate+added+successfully", status_code=303)

    @application.post("/candidates/{candidate_id}/status", name="update_candidate_status", include_in_schema=False)
    async def update_candidate_form(candidate_id: int, status_value: str = Form(..., alias="status"), db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin", "hr"))):
        job = db.scalar(select(Job).where(Job.status == "OPEN").order_by(Job.id))
        item = db.scalar(select(Application).where(Application.candidate_id == candidate_id, Application.job_id == job.id)) if job else None
        if item is None:
            return RedirectResponse("/candidates?error=Application+not+found", status_code=303)
        try:
            update_application_status(db, item, status_value, "", user)
            db.commit()
        except HTTPException as exc:
            db.rollback()
            return RedirectResponse("/candidates?error=" + exc.detail.replace(" ", "+"), status_code=303)
        return RedirectResponse("/candidates?success=Application+status+updated", status_code=303)

    @application.post("/candidates/{candidate_id}/delete", name="delete_candidate", include_in_schema=False)
    async def delete_candidate_form(candidate_id: int, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin"))):
        candidate = db.get(Candidate, candidate_id)
        if candidate is None:
            return RedirectResponse("/candidates?error=Candidate+not+found", status_code=303)
        db.delete(candidate)
        write_audit(db, user, "candidate.delete", "candidate", candidate_id)
        db.commit()
        return RedirectResponse("/candidates?success=Candidate+deleted+successfully", status_code=303)

    @application.get("/jobs", response_class=HTMLResponse, name="jobs", include_in_schema=False)
    async def jobs_page(request: Request, db: Session = Depends(get_session)):
        redirect = require_html_login(request)
        if redirect:
            return redirect
        jobs = db.scalars(select(Job).order_by(Job.status, Job.created_at.desc())).all()
        active_job = next((row for row in jobs if row.status == "OPEN"), None)
        display_jobs = [job_dict(row) for row in jobs]
        return render(request, "jobs.html", jobs=display_jobs, job_requirements=job_dict(active_job) if active_job else None, error=request.query_params.get("error", ""), success=request.query_params.get("success", ""))

    @application.post("/jobs", include_in_schema=False)
    async def manage_job_form(request: Request, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin"))):
        form = await request.form()
        action = str(form.get("action", "")).lower()
        try:
            job_id = int(form.get("job_id", "0") or 0)
            if action in {"activate", "close"}:
                job = db.get(Job, job_id)
                if job is None:
                    raise ValueError("The selected job could not be found.")
                job.status = "OPEN" if action == "activate" else "CLOSED"
            elif action == "delete":
                job = db.get(Job, job_id)
                if job is None:
                    raise ValueError("The selected job could not be found.")
                if db.scalar(select(func.count(Job.id))) <= 1:
                    raise ValueError("At least one job must remain.")
                db.delete(job)
            elif action in {"add", "edit"}:
                title = str(form.get("title", "")).strip()
                required = sorted(normalize_items(str(form.get("required_skills", ""))))
                try:
                    minimum = float(form.get("min_experience", 0))
                    if minimum < 0:
                        raise ValueError
                except ValueError:
                    raise ValueError("Minimum experience must be a valid non-negative number.") from None
                if not title or not required:
                    raise ValueError("Job title and required skills are required.")
                job = db.get(Job, job_id) if action == "edit" else Job(title=title, required_skills=required)
                if job is None:
                    raise ValueError("The selected job could not be found.")
                if action == "add":
                    db.add(job)
                job.title = title
                job.description = str(form.get("description", "")).strip()
                job.required_skills = required
                job.preferred_skills = sorted(normalize_items(str(form.get("preferred_skills", ""))))
                job.required_qualifications = sorted(normalize_items(str(form.get("required_qualifications", ""))))
                job.min_experience = minimum
                if action == "edit":
                    recalculate_job_applications(db, job)
            else:
                raise ValueError("Unsupported job action.")
            write_audit(db, user, f"job.{action}", "job", job_id or None)
            db.commit()
            return RedirectResponse("/jobs?success=Job+saved+successfully", status_code=303)
        except ValueError as exc:
            db.rollback()
            return RedirectResponse("/jobs?error=" + str(exc).replace(" ", "+"), status_code=303)

    @application.post("/api/auth/login")
    async def api_login(payload: LoginInput, request: Request, db: Session = Depends(get_session)):
        user = authenticate(db, payload.email, payload.password, request)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        return {"user": user_dict(user), "expires_in": 28800}

    @application.post("/api/auth/logout")
    async def api_logout(request: Request, db: Session = Depends(get_session), user: User = Depends(current_user)):
        write_audit(db, user, "logout", "user", user.id)
        db.commit()
        request.session.clear()
        return {"message": "Logged out"}

    @application.get("/api/auth/me")
    async def api_me(user: User = Depends(current_user)):
        return user_dict(user)

    @application.get("/api/candidates")
    async def list_candidates(q: str = "", skill: str | None = None, min_experience: float | None = Query(default=None, ge=0), max_experience: float | None = Query(default=None, ge=0), skip: int = Query(default=0, ge=0), limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_session), user: User = Depends(current_user)):
        query = select(Candidate)
        conditions = []
        if q.strip():
            pattern = f"%{q.strip().lower()}%"
            conditions.append(or_(func.lower(Candidate.name).like(pattern), func.lower(Candidate.email).like(pattern), func.lower(cast(Candidate.skills, String)).like(pattern)))
        if skill:
            conditions.append(func.lower(cast(Candidate.skills, String)).like(f"%{skill.strip().lower()}%"))
        if min_experience is not None:
            conditions.append(Candidate.experience >= min_experience)
        if max_experience is not None:
            conditions.append(Candidate.experience <= max_experience)
        total = db.scalar(select(func.count(Candidate.id)).where(*conditions)) or 0
        rows = db.scalars(query.where(*conditions).order_by(Candidate.created_at.desc()).offset(skip).limit(limit)).all()
        return {"items": [candidate_dict(row) for row in rows], "skip": skip, "limit": limit, "count": total}

    @application.post("/api/candidates", status_code=201)
    async def create_candidate(payload: CandidateInput, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin", "hr"))):
        candidate = Candidate(**payload.model_dump())
        db.add(candidate)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="A candidate with this email already exists") from None
        write_audit(db, user, "candidate.create", "candidate", candidate.id)
        db.commit()
        db.refresh(candidate)
        return candidate_dict(candidate)

    @application.get("/api/candidates/{candidate_id}")
    async def get_candidate(candidate_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)):
        candidate = db.scalar(select(Candidate).options(joinedload(Candidate.applications).joinedload(Application.job)).where(Candidate.id == candidate_id))
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        result = candidate_dict(candidate)
        result["applications"] = [application_dict(row) for row in candidate.applications]
        return result

    @application.put("/api/candidates/{candidate_id}")
    async def edit_candidate(candidate_id: int, payload: CandidateInput, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin", "hr"))):
        candidate = db.get(Candidate, candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        for key, value in payload.model_dump().items():
            setattr(candidate, key, value)
        for item in candidate.applications:
            result = calculate_match_score(candidate_dict(candidate), job_dict(item.job))
            item.score, item.score_breakdown = result["score"], result
        write_audit(db, user, "candidate.update", "candidate", candidate.id)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="A candidate with this email already exists") from None
        return candidate_dict(candidate)

    @application.delete("/api/candidates/{candidate_id}", status_code=204)
    async def remove_candidate(candidate_id: int, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin"))):
        candidate = db.get(Candidate, candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        write_audit(db, user, "candidate.delete", "candidate", candidate.id)
        db.delete(candidate)
        db.commit()

    @application.get("/api/jobs")
    async def list_jobs(db: Session = Depends(get_session), user: User = Depends(current_user)):
        return {"items": [job_dict(row) for row in db.scalars(select(Job).order_by(Job.status, Job.created_at.desc())).all()]}

    @application.post("/api/jobs", status_code=201)
    async def create_job(payload: JobInput, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin"))):
        job = Job(**payload.model_dump())
        db.add(job)
        db.flush()
        write_audit(db, user, "job.create", "job", job.id)
        db.commit()
        db.refresh(job)
        return job_dict(job)

    @application.get("/api/jobs/{job_id}")
    async def get_job(job_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)):
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job_dict(job)

    @application.put("/api/jobs/{job_id}")
    async def edit_job(job_id: int, payload: JobInput, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin"))):
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        for key, value in payload.model_dump().items():
            setattr(job, key, value)
        recalculate_job_applications(db, job)
        write_audit(db, user, "job.update", "job", job.id)
        db.commit()
        return job_dict(job)

    @application.patch("/api/jobs/{job_id}/status")
    async def change_job_status(job_id: int, payload: JobStatusInput, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin"))):
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job.status = payload.status
        write_audit(db, user, "job.status", "job", job.id, {"status": payload.status})
        db.commit()
        return job_dict(job)

    @application.delete("/api/jobs/{job_id}", status_code=204)
    async def remove_job(job_id: int, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin"))):
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        write_audit(db, user, "job.delete", "job", job.id)
        db.delete(job)
        db.commit()

    @application.post("/api/jobs/{job_id}/applications", status_code=201)
    async def submit_application(job_id: int, payload: ApplicationInput, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin", "hr"))):
        job, candidate = db.get(Job, job_id), db.get(Candidate, payload.candidate_id)
        if job is None or candidate is None:
            raise HTTPException(status_code=404, detail="Job or candidate not found")
        if job.status != "OPEN":
            raise HTTPException(status_code=409, detail="Applications cannot be added to a closed job")
        exists = db.scalar(select(Application.id).where(Application.job_id == job_id, Application.candidate_id == candidate.id))
        if exists:
            raise HTTPException(status_code=409, detail="Candidate already has an application for this job")
        item = create_application(db, candidate, job, user)
        db.commit()
        db.refresh(item)
        return application_dict(item)

    @application.get("/api/applications")
    async def list_applications(job_id: int | None = None, selected_status: str | None = Query(default=None, alias="status"), skip: int = Query(default=0, ge=0), limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_session), user: User = Depends(current_user)):
        query = select(Application).options(joinedload(Application.candidate), joinedload(Application.job))
        if job_id is not None:
            query = query.where(Application.job_id == job_id)
        if selected_status:
            if selected_status not in STATUSES:
                raise HTTPException(status_code=422, detail="Invalid application status")
            query = query.where(Application.status == selected_status)
        rows = db.scalars(query.order_by(Application.score.desc(), Application.created_at).offset(skip).limit(limit)).all()
        return {"items": [application_dict(row) for row in rows], "skip": skip, "limit": limit}

    @application.get("/api/jobs/{job_id}/rankings")
    async def job_rankings(job_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)):
        if db.get(Job, job_id) is None:
            raise HTTPException(status_code=404, detail="Job not found")
        rows = db.scalars(select(Application).options(joinedload(Application.candidate), joinedload(Application.job)).where(Application.job_id == job_id).order_by(Application.score.desc(), Application.created_at)).all()
        return {"job_id": job_id, "items": [application_dict(row) for row in rows]}

    @application.patch("/api/applications/{application_id}")
    async def decide_application(application_id: int, payload: ApplicationDecision, db: Session = Depends(get_session), user: User = Depends(roles_allowed("admin", "hr"))):
        item = db.get(Application, application_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Application not found")
        update_application_status(db, item, payload.status, payload.notes, user)
        db.commit()
        db.refresh(item)
        return application_dict(item)

    @application.get("/api/applications/{application_id}/history")
    async def application_history(application_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)):
        if db.get(Application, application_id) is None:
            raise HTTPException(status_code=404, detail="Application not found")
        rows = db.scalars(select(StatusHistory).where(StatusHistory.application_id == application_id).order_by(StatusHistory.changed_at)).all()
        return {"items": [{"from_status": row.from_status, "to_status": row.to_status, "changed_by": row.changed_by, "notes": row.notes, "changed_at": row.changed_at} for row in rows]}

    @application.get("/api/analytics/dashboard")
    async def dashboard_analytics(job_id: int | None = None, db: Session = Depends(get_session), user: User = Depends(current_user)):
        return analytics_summary(db, job_id)

    @application.get("/health")
    async def health(db: Session = Depends(get_session)):
        try:
            db.execute(select(1))
        except Exception:
            logger.exception("Database health check failed")
            raise HTTPException(status_code=503, detail="Database unavailable") from None
        return {"status": "ok", "database": "ok"}

    return application


def update_application_status(db: Session, item: Application, new_status: str, notes: str, user: User):
    if new_status != item.status and new_status not in TRANSITIONS[item.status]:
        raise HTTPException(status_code=409, detail=f"Cannot move application from {item.status} to {new_status}")
    old_status = item.status
    item.status = new_status
    if notes:
        item.notes = notes
    if new_status != old_status or notes:
        db.add(StatusHistory(application_id=item.id, from_status=old_status, to_status=new_status, changed_by=user.id, notes=notes))
        write_audit(db, user, "application.decision", "application", item.id, {"from_status": old_status, "to_status": new_status})


app = create_app()
