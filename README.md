# TalentLens: Smart Candidate Screening System

TalentLens is a multi-tenant recruitment application. HR teams record candidates and job openings, apply candidates to jobs, and get a **deterministic, explainable screening score** for every application. A person then records each decision through an audited status workflow.

It consists of a FastAPI + PostgreSQL API and a React + TypeScript web app.

> **Deployment status:** the application is prepared for Vercel (frontend), Render (API) and Render PostgreSQL, and was verified locally in production mode. **No public deployment has been verified yet, so no public URLs are listed.** See [HOSTING_GUIDE.md](HOSTING_GUIDE.md) for the steps.

---

## Contents

1. [Business problem](#1-business-problem)
2. [Features and user roles](#2-features-and-user-roles)
3. [Architecture](#3-architecture)
4. [Technology stack](#4-technology-stack)
5. [Data model](#5-data-model)
6. [Local installation](#6-local-installation)
7. [PostgreSQL and Alembic](#7-postgresql-and-alembic)
8. [Environment variables](#8-environment-variables)
9. [Starting the backend and frontend](#9-starting-the-backend-and-frontend)
10. [Seed data](#10-seed-data)
11. [Deployment](#11-deployment)
12. [Registration and demo accounts](#12-registration-and-demo-accounts)
13. [API reference](#13-api-reference)
14. [Screening algorithm](#14-screening-algorithm)
15. [Authentication, authorization and tenant isolation](#15-authentication-authorization-and-tenant-isolation)
16. [Testing](#16-testing)
17. [Known limitations and future improvements](#17-known-limitations-and-future-improvements)

---

## 1. Business problem

Screening applicants against a job's requirements is slow and inconsistent when done by hand, and the scores produced by many automated tools can't be explained to a hiring manager or a candidate. TalentLens addresses three questions:

- **How well does this candidate match this job?** It answers with a transparent score that shows exactly which requirements were met, which were missed, and how each one counted.
- **Who should we look at first?** It answers with a stable, reproducible ranking for each job.
- **Who decided what, and why?** Every status change, along with its note, the person who made it and when, is recorded in an immutable history and activity log.

Scores support decisions; they never make them. Every status change is made by a person, and a rejection requires a written reason.

---

## 2. Features and user roles

### Features

| Area | What it does |
|---|---|
| Workspaces | Each registration creates an isolated workspace. All data is scoped to it. |
| Candidates | CRUD, case-insensitive duplicate-email prevention within a workspace, search by name, email or skill, filters (skill, experience range, application status, job), and server-side pagination. |
| Jobs | Required and preferred skills, minimum experience, mandatory or optional qualifications, configurable scoring weights (including per-skill weights), and open/closed status. |
| Applications | One per candidate and job. Each is screened as soon as it is created and has its own status and history. |
| Screening | A deterministic weighted score (0–100) with a per-component breakdown, matched and missing skills, eligibility, missing-data handling and a scoring version. |
| Rankings | Applicants ranked per job by score, with stable tie-breakers and an eligibility filter. |
| Workflow | Validated status transitions, mandatory rejection notes, protection against concurrent conflicting decisions, and a full history. |
| Activity log | Audit records for candidate, job, application, screening, user and authentication actions. |
| Analytics | A dashboard with totals, the status distribution, average score per job, top applicants, recent activity and skill gaps, with date and job filters. |
| Resumes | PDF upload stored in PostgreSQL, authenticated download, and text extraction that produces *unverified suggestions* for HR to review before saving. |

### User roles

| Role | How it is created | Can do |
|---|---|---|
| **HR** | Public registration (the first user of a new workspace) or added by an Admin | Manage candidates, jobs, applications, decisions and screening, and view the dashboard, including the workspace's recruitment activity feed. In the full activity log (`/api/audit-logs`) sees only their *own* entries. |
| **Admin** | Only through the protected seed command, or a direct database change by an operator. No API endpoint accepts or grants a role. | Everything HR can do, plus list, create (as HR) and activate/deactivate workspace users, and view every user's activity. |

---

## 3. Architecture

```mermaid
flowchart LR
    subgraph Browser
        UI["TalentLens SPA<br/>React + TypeScript<br/>TanStack Query"]
    end

    subgraph Vercel
        Static["Static assets<br/>(Vite build)"]
        Rewrite["Rewrite /api/* → Render<br/>SPA fallback → index.html"]
    end

    subgraph Render
        API["FastAPI (uvicorn)<br/>routes → services → engine"]
        DB[("PostgreSQL<br/>17 tables, Alembic-managed")]
    end

    UI -- "HTTPS, same origin" --> Static
    UI -- "/api/* + HttpOnly cookies<br/>+ X-CSRF-Token" --> Rewrite
    Rewrite -- "HTTPS proxy" --> API
    API -- "SQLAlchemy 2.0 / psycopg 3" --> DB
```

**Backend layers**, in `backend/app`:

```mermaid
flowchart TB
    R["api/routes<br/>HTTP, validation, auth dependencies"] --> S["services<br/>business rules, transactions, audit"]
    S --> E["screening/engine.py<br/>pure scoring function (no DB)"]
    S --> P["resumes/<br/>PDF validation + extraction (no DB)"]
    S --> M["models<br/>SQLAlchemy ORM"]
    R --> SC["schemas<br/>Pydantic request/response models"]
    M --> DB[(PostgreSQL)]
```

- **`api/`** contains the routers, the authentication dependencies (`dependencies.py`), the CSRF and Origin checks (`csrf.py`), and the uniform error envelope (`errors.py`).
- **`services/`** hold every query and mutation, always filtered by the caller's `workspace_id`.
- **`screening/engine.py`** is a pure function: given the same inputs it always produces the same output. It has no database access, randomness or external calls.
- **In production,** the browser calls `/api` on the frontend's own domain and Vercel proxies those calls to Render. This keeps the auth cookies first-party, because browsers increasingly block third-party cookies between `*.vercel.app` and `*.onrender.com`.

---

## 4. Technology stack

| Layer | Technology (version) | Why |
|---|---|---|
| API | FastAPI 0.115, Pydantic v2, uvicorn | Typed request validation, automatic OpenAPI docs at `/docs`, and a simple dependency system for authentication and tenancy. |
| ORM / DB | SQLAlchemy 2.0, PostgreSQL 15+, psycopg 3 | Relational integrity (composite foreign keys enforce tenancy), JSONB for score breakdowns, and row locks for concurrent decisions. |
| Migrations | Alembic 1.15 | Versioned schema changes. `alembic check` confirms the models and migrations match. |
| Security | argon2-cffi (Argon2id), opaque session tokens, CSRF tokens | No JWTs in browser storage. Tokens are revocable server-side and only their hashes are stored. |
| PDF | pypdf 5.1 | Pure-Python parsing for validation and text extraction. No external AI service. |
| Frontend | React 18.3, TypeScript 5.6, Vite 5.4 | Strict typing and fast builds with route-level code splitting. |
| UI | Tailwind CSS 3.4, Radix primitives (shadcn/ui-style), lucide icons | Accessible dialogs and menus with a consistent design system. |
| Data fetching / forms | TanStack Query 5, react-hook-form 7, zod 3 | Caching and retries, plus client-side validation that mirrors the API's rules. |
| Charts | Recharts 2.15 | Status distribution and score-comparison charts, loaded only on the dashboard. |
| Tests | pytest 8, Vitest 2, Testing Library | API, engine and component tests. |
| Deploy | Docker, Render Blueprint, Vercel | Reproducible image, managed PostgreSQL and a global CDN for the static app. |

---

## 5. Data model

17 tables, all created by Alembic. Every business table carries `workspace_id`. Child tables reference parents through **composite `(id, workspace_id)` foreign keys**, so the database itself rejects a link between records from different workspaces.

```mermaid
erDiagram
    WORKSPACES ||--o{ USERS : has
    WORKSPACES ||--o{ CANDIDATES : owns
    WORKSPACES ||--o{ JOBS : owns
    CANDIDATES ||--o{ CANDIDATE_SKILLS : has
    CANDIDATES ||--o{ CANDIDATE_EDUCATION : has
    CANDIDATES ||--o| CANDIDATE_RESUMES : has
    CANDIDATE_RESUMES ||--o| RESUME_FILES : stores
    SKILLS ||--o{ CANDIDATE_SKILLS : "is linked by"
    SKILLS ||--o{ JOB_SKILLS : "is linked by"
    JOBS ||--o{ JOB_SKILLS : requires
    JOBS ||--o{ JOB_QUALIFICATIONS : lists
    CANDIDATES ||--o{ APPLICATIONS : submits
    JOBS ||--o{ APPLICATIONS : receives
    APPLICATIONS ||--o| SCREENING_RESULTS : "is scored by"
    APPLICATIONS ||--o{ APPLICATION_STATUS_HISTORY : records
    USERS ||--o{ APPLICATION_STATUS_HISTORY : "changed by"
    USERS ||--o{ AUDIT_LOGS : performs
    USERS ||--o{ AUTH_SESSIONS : "signs in with"
    AUTH_SESSIONS ||--o{ REVOKED_REFRESH_TOKENS : rotates
```

| Table | Key columns and constraints |
|---|---|
| `workspaces` | `name`, unique `slug` |
| `users` | `role` ∈ {`admin`,`hr`}, `is_active`, Argon2id `password_hash`, **globally unique `lower(email)`** |
| `candidates` | `full_name`, `email`, `phone`, `total_experience` (0–80, nullable); **unique `(workspace_id, lower(email))`** |
| `candidate_skills`, `skills` | Skills are normalized into a shared `skills` catalogue; unique `(candidate_id, skill_id)` |
| `candidate_education` | `degree`, `field_of_study`, `institution`, `graduation_year` |
| `jobs` | `title`, `department`, `minimum_experience`, `criterion_weights` (JSON), `status` ∈ {`open`,`closed`} |
| `job_skills` | `category` ∈ {`required`,`preferred`}, optional per-skill `weight`; unique `(job_id, skill_id, category)` |
| `job_qualifications` | `name`, `is_mandatory`, optional `weight` |
| `applications` | `status`, `current_screening_score`, `decision_notes`; **unique `(candidate_id, job_id)`** |
| `screening_results` | One per application: `score`, `score_breakdown` (JSONB), `eligibility`, `assessment_status`, `scoring_version`, `evaluated_at`, `is_stale`, `stale_reason` |
| `application_status_history` | `previous_status`, `new_status`, `changed_by`, `notes`, `changed_at` |
| `audit_logs` | `actor_id`, `action`, `resource_type`, `resource_id`, safe `metadata` (secrets and personal data are excluded) |
| `candidate_resumes`, `resume_files` | Resume metadata, plus the PDF bytes (`bytea`, loaded lazily), `sha256` and `page_count` |
| `auth_sessions`, `revoked_refresh_tokens` | SHA-256 hashes of the access, refresh and CSRF tokens, expiry times, and detection of reused refresh tokens |

---

## 6. Local installation

**Prerequisites:**

- Python 3.12+ (the Docker image uses 3.12; development used 3.13);
- Node.js 20+ (development used 22) with npm;
- PostgreSQL 15+, or Docker to run it.

```powershell
git clone https://github.com/bhoomi1301/smart_candidate_screening.git
cd smart_candidate_screening

# Backend dependencies (requirements-dev.txt = production requirements + test tools)
py -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-dev.txt

# Frontend dependencies
cd frontend
npm install
cd ..

# Configuration
Copy-Item .env.example .env           # then edit the placeholder values (section 8)
```

---

## 7. PostgreSQL and Alembic

Start a local PostgreSQL with Docker Compose. It reads `POSTGRES_*` from `.env` and keeps the data in a named volume:

```powershell
docker compose up -d db
```

Or use an existing server: create a database and user, then set `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<database>
```

`postgresql://…` and `postgres://…` addresses (as given by Render or Heroku) are converted to the psycopg 3 driver automatically.

**Migrations.** The application never creates tables itself; Alembic does:

```powershell
python -m alembic upgrade head        # create/upgrade the schema
python -m alembic current             # show the applied revision (head: d4a8b1c9e3f2)
python -m alembic check               # verify models and migrations match
python -m alembic downgrade -1        # roll back one revision
```

Migration history:

1. `260a37100d3d`: tenant-scoped foundation.
2. `e748174ef80e`: opaque auth sessions.
3. `a3c9d2e7f415`: screening engine v2.
4. `b81f4c6e2d90`: audit actor index.
5. `d4a8b1c9e3f2`: resume files.

---

## 8. Environment variables

Template ([.env.example](.env.example)); **placeholders only, never commit real values**:

```dotenv
APP_ENV=development                       # development | test | production
POSTGRES_DB=screening                     # used by docker compose
POSTGRES_USER=screening
POSTGRES_PASSWORD=<choose-a-local-password>
DATABASE_URL=postgresql+psycopg://screening:<password>@localhost:5432/screening
ALLOWED_ORIGINS=["http://localhost:5173"] # JSON list of exact browser origins (no wildcard)
FRONTEND_URL=http://localhost:5173        # optional: GET / on the API redirects here
COOKIE_SECURE=false                       # must be true in production (HTTPS)
COOKIE_SAMESITE=lax                       # lax | strict | none (none requires COOKIE_SECURE=true)
ACCESS_TOKEN_TTL_SECONDS=900              # 60–3600
REFRESH_TOKEN_TTL_SECONDS=604800          # 3600–2592000
RESUME_MAX_BYTES=5242880                  # 1 KB–20 MB (use 4194304 behind the Vercel proxy)
RESUME_MAX_PAGES=50
# Only for the seed command:
ADMIN_EMAIL=<admin-email>
SEED_ADMIN_PASSWORD=<strong-password>
SEED_HR_PASSWORD=<strong-password>
```

**Production safeguards.** With `APP_ENV=production` the API refuses to start unless:

- `COOKIE_SECURE=true`;
- `ALLOWED_ORIGINS` is set and contains no `*`;
- `DATABASE_URL` points to PostgreSQL.

**Frontend** ([frontend/.env.example](frontend/.env.example)):

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Empty for same-origin calls (dev proxy or Vercel rewrite). Set to an absolute API URL only for a cross-site deployment. |
| `VITE_DEV_PROXY_TARGET` | Development only; where Vite proxies `/api` (default `http://127.0.0.1:8000`). |
| `VITE_RESUME_MAX_MB` | Client-side upload size check; keep it equal to the API limit. |

---

## 9. Starting the backend and frontend

```powershell
# Terminal 1: API on http://127.0.0.1:8000  (docs: /docs, health: /health)
python -m alembic upgrade head
uvicorn app:app --reload

# Terminal 2: web app on http://localhost:5173 (proxies /api to the API)
cd frontend
npm run dev
```

| Command | Purpose |
|---|---|
| `npm run build` | Type-check and build `frontend/dist` |
| `npm run preview` | Serve the production build on :4173 with the same `/api` proxy Vercel uses |
| `npm test` | Frontend unit and component tests |
| `docker build -t talentlens-api .` | Production API image (non-root; runs migrations, then uvicorn) |

---

## 10. Seed data

The seed is optional and **idempotent**: it creates the "Demo Hiring Workspace" once, and later runs report `created: False` without adding anything. It refuses to run unless both seed passwords are set.

```powershell
# with ADMIN_EMAIL, SEED_ADMIN_PASSWORD and SEED_HR_PASSWORD set in .env or the environment
python -m backend.app.seed
# {'created': True, 'workspace_id': 1, 'candidates': 4, 'jobs': 2, 'applications': 4}
```

It creates:

- an **Admin** (`ADMIN_EMAIL`) and an **HR** user (`hr@company.com`);
- 2 jobs (Senior Python Developer, Data Analyst) and 4 candidates;
- 4 screened applications.

Rebuilding the database and seeding again reproduces identical scores: 83.33, 20.00, 88.89 and 13.33.

---

## 11. Deployment

| Item | Status |
|---|---|
| Public frontend URL | **Not deployed yet.** None verified. |
| Public API health URL | **Not deployed yet.** It will be `https://<render-service>.onrender.com/health`. |
| API documentation URL | **Not deployed yet.** It will be `https://<render-service>.onrender.com/docs`. |

The configuration is in the repository:

- [`render.yaml`](render.yaml): Render Blueprint for the database and the API;
- [`Dockerfile`](Dockerfile) and [`scripts/start.sh`](scripts/start.sh): the image, with migrations run on start;
- [`frontend/vercel.json`](frontend/vercel.json): the `/api` proxy, SPA fallback and security headers;
- [`frontend/.env.production`](frontend/.env.production): production build settings.

[HOSTING_GUIDE.md](HOSTING_GUIDE.md) has the exact steps, every environment variable, and an 11-step production smoke test. The production configuration was verified locally:

- the Docker image ran with `APP_ENV=production` against PostgreSQL;
- the production frontend build was served through a Vercel-style proxy;
- registration, reload, creating records, screening, decisions, the dashboard and cross-workspace isolation all worked;
- data persisted across an API restart.

---

## 12. Registration and demo accounts

- **Self-registration:** open the web app → **Create a workspace**, and enter a company name, your name, email and a password of at least 12 characters. You become the first HR user of a new, empty, isolated workspace. Email addresses are unique across the whole system.
- **Demo workspace:** after running the seed (section 10), sign in as `ADMIN_EMAIL`, or as `hr@company.com` with `SEED_HR_PASSWORD`. Demo passwords are never stored in the repository, so share them out of band.
- **Adding team members:** an Admin opens **Account → Add HR member**.

---

## 13. API reference

Interactive OpenAPI docs are at **`/docs`** and the schema at **`/openapi.json`**. The full reference with every parameter is in [ENDPOINTS.md](ENDPOINTS.md).

### Conventions

- **Authentication:** HttpOnly cookies set by `register`, `login` and `refresh`. Every unsafe request (POST, PUT, PATCH, DELETE) must send `X-CSRF-Token`, obtained from the auth response or from `GET /api/auth/csrf` after a reload.
- **Errors** always use one envelope:
  ```json
  {"error": {"code": "not_found", "message": "Candidate not found"}}
  ```
  Validation errors add `details[]`, each with a `location`, `message` and `code`. The codes are `bad_request`, `unauthorized`, `forbidden`, `not_found`, `method_not_allowed`, `conflict`, `payload_too_large`, `unsupported_media_type`, `validation_error` (422), `database_unavailable` (503) and `internal_error` (500). 5xx responses never include internal details.
- **Lists** return `{items, total, skip, limit}`, with `limit` from 1 to 100.

### Endpoint summary (44 endpoints)

| Area | Method and path | Access |
|---|---|---|
| Auth | `GET /api/auth/csrf` · `POST /api/auth/register` · `POST /api/auth/login` · `POST /api/auth/refresh` · `POST /api/auth/logout` · `GET /api/auth/me` | public / session |
| Users | `GET /api/users` · `POST /api/users` · `PATCH /api/users/{id}/active?is_active=` | Admin |
| Candidates | `GET/POST /api/candidates` · `GET/PUT/DELETE /api/candidates/{id}` | read: any member · write: Admin/HR |
| Resumes | `POST/DELETE /api/candidates/{id}/resume` · `GET …/resume/file` · `GET …/resume/suggestions` · `POST /api/resumes/extract` | Admin/HR (download: any member) |
| Jobs | `GET/POST /api/jobs` · `GET/PUT/DELETE /api/jobs/{id}` · `PATCH /api/jobs/{id}/status` | read: any member · write: Admin/HR |
| Applications | `GET /api/applications/workflow` · `POST/GET /api/jobs/{id}/applications` · `GET /api/applications` · `GET/PATCH /api/applications/{id}` · `GET /api/applications/{id}/history` | write: Admin/HR |
| Screening | `GET/POST /api/applications/{id}/screening` · `POST /api/jobs/{id}/screening` · `GET /api/jobs/{id}/rankings` | refresh: Admin/HR |
| Activity | `GET /api/audit-logs` · `GET /api/users/{id}/activity` | HR: own entries · Admin: all |
| Analytics | `GET /api/analytics/dashboard` · `GET /api/analytics/jobs/{id}/top-applicants` · `GET /api/analytics/activity` · `GET /api/analytics/skill-gaps` | any member |
| Health | `GET /health` · `GET /api/health` | public |

### Representative examples

The examples below are actual responses captured from the running API; timestamps are shortened.

**Register**: `POST /api/auth/register` → `201`

```json
// request
{"workspace_name": "Acme Recruiting", "full_name": "Alex Morgan", "email": "alex@example.com",
 "password": "a-long-password-123", "password_confirmation": "a-long-password-123"}
// response (cookies screening_access + screening_refresh are set as HttpOnly)
{"user": {"id": 1, "workspace_id": 1, "full_name": "Alex Morgan", "email": "alex@example.com",
          "role": "hr", "is_active": true, "created_at": "2026-10-15T04:41:33"},
 "workspace_id": 1, "access_expires_in": 900, "refresh_expires_in": 604800, "csrf_token": "<token>"}
```

**Create candidate**: `POST /api/candidates` → `201`

```json
// request
{"full_name": "Jordan Rivera", "email": "jordan@example.com", "phone": "+1 555 010 2020",
 "total_experience": 5, "technical_skills": ["Python", "SQL", "Docker"],
 "education": [{"degree": "BSc", "field_of_study": "Computer Science",
                "institution": "State University", "graduation_year": 2019}]}
// response (excerpt)
{"id": 1, "full_name": "Jordan Rivera", "email": "jordan@example.com", "total_experience": "5",
 "technical_skills": ["Docker", "Python", "SQL"], "education": [{"id": 1, "degree": "BSc", ...}]}
```

A duplicate email in the same workspace (any letter case) returns `409 conflict`.

**Create job**: `POST /api/jobs` → `201`

```json
// request
{"title": "Backend Engineer", "department": "Engineering", "description": "Build APIs.",
 "required_skills": ["Python", "SQL", "Kubernetes"], "preferred_skills": ["Docker"],
 "minimum_experience": 4,
 "qualifications": [{"name": "BSc Computer Science", "is_mandatory": true}],
 "criterion_weights": {"required_skills": 50, "preferred_skills": 20, "experience": 20, "qualifications": 10}}
// response (excerpt)
{"id": 1, "title": "Backend Engineer", "required_skills": ["Kubernetes", "Python", "SQL"],
 "preferred_skills": ["Docker"], "minimum_experience": "4", "status": "open", "application_count": 0}
```

**Apply a candidate**: `POST /api/jobs/1/applications` with `{"candidate_id": 1}` → `201`. The application is screened immediately:

```json
{"id": 1, "candidate_id": 1, "job_id": 1, "status": "Pending", "current_screening_score": "83.33", ...}
```

**Score breakdown**: `GET /api/applications/1/screening` → `200` (excerpt)

```json
{"score": "83.33", "eligibility": "not_eligible", "assessment_status": "complete",
 "matched_skills": ["docker", "python", "sql"], "missing_mandatory_skills": ["kubernetes"],
 "scoring_version": "screening-v2", "is_stale": false,
 "score_breakdown": {
   "components": {
     "required_skills":  {"status": "evaluated", "configured_weight": 50.0, "effective_weight": 50.0, "score": 66.67, "points": 33.33},
     "preferred_skills": {"status": "evaluated", "configured_weight": 20.0, "effective_weight": 20.0, "score": 100.0, "points": 20.0},
     "experience":       {"status": "evaluated", "configured_weight": 20.0, "effective_weight": 20.0, "score": 100.0, "points": 20.0},
     "qualifications":   {"status": "evaluated", "configured_weight": 10.0, "effective_weight": 10.0, "score": 100.0, "points": 10.0}},
   "warnings": [{"code": "missing_mandatory_skills", "message": "Missing required skills: kubernetes"}],
   "score_upper_bound": 83.33, ...}}
```

**Record a decision**: `PATCH /api/applications/1` → `200`

```json
// request: expected_status protects against overwriting another reviewer's change
{"status": "Under Review", "notes": "Strong backend profile", "expected_status": "Pending"}
// response (excerpt)
{"id": 1, "status": "Under Review", "decision_notes": "Strong backend profile", ...}
```

Rules are enforced on the server:

```json
// Rejected without a note → 422
{"error": {"code": "validation_error", "message": "Request validation failed",
  "details": [{"location": ["body"], "code": "value_error",
   "message": "Value error, Rejecting an application requires an explanatory note of at least 10 characters"}]}}
// Under Review → Pending → 409
{"error": {"code": "conflict", "message": "Cannot move application from Under Review to Pending. Allowed: Shortlisted, Rejected"}}
```

**Status history**: `GET /api/applications/1/history` → `200`

```json
[{"id": 1, "previous_status": null, "new_status": "Pending", "changed_by": 1, "changed_by_name": "Alex Morgan",
  "notes": "Application created", "changed_at": "2026-10-15T04:41:33"},
 {"id": 2, "previous_status": "Pending", "new_status": "Under Review", "changed_by": 1, "changed_by_name": "Alex Morgan",
  "notes": "Strong backend profile", "changed_at": "2026-10-15T04:41:33"}]
```

**Dashboard**: `GET /api/analytics/dashboard` → `200` (excerpt)

```json
{"total_candidates": 1, "active_job_openings": 1, "total_applications": 1, "unique_applicants": 1,
 "application_statuses": {"pending": 0, "under_review": 1, "shortlisted": 0, "rejected": 0}, ...}
```

---

## 14. Screening algorithm

Implemented in [`backend/app/screening/engine.py`](backend/app/screening/engine.py) (version **`screening-v2`**) as a pure function using `Decimal` arithmetic.

### Weights

The defaults are **required skills 50, preferred skills 20, experience 20, qualifications 10**. Each job can set its own weights. A configuration is valid only if:

- it names exactly these four components;
- each weight is between 0 and 100;
- they total **exactly 100**;
- required skills is **above 0**.

Anything else is rejected with `422`; weights are never silently normalized.

**Optional per-skill weights** must cover every skill in that list and total 100. Without them, skills count equally. **Qualification weights** are all-or-none and total 100.

### Formula

For each *applicable* component *i*, with configured weight *wᵢ* and achievement *sᵢ* (0–100):

```
effective_weightᵢ = wᵢ × 100 / Σ w(applicable components)
pointsᵢ           = effective_weightᵢ × sᵢ / 100
score             = round_half_up(Σ pointsᵢ, 2)          ∈ [0, 100]
```

| Component | Achievement sᵢ |
|---|---|
| Required skills | Σ weight of matched required skills ÷ Σ weight of all required skills × 100 |
| Preferred skills | Same rule over preferred skills. **Not applicable** when the job lists none (no division by zero). |
| Experience | 100 when years ≥ minimum, otherwise 100 × years ÷ minimum. **Capped at 100**, so extra years earn nothing. **Not applicable** when the minimum is 0. |
| Qualifications | Σ weight of matched criteria ÷ Σ weight of all criteria × 100. Not applicable when the job lists none. |

A component that is **not applicable** has its weight shared proportionally among the others, and a `weights_redistributed` warning is added.

*Example:* a job requires Python, SQL and Docker with a minimum of 2 years, and has no preferred skills or qualifications. The applicable weights are 50 + 20 = 70, so the effective weights are 71.43 and 28.57. A candidate with Python, SQL and 10 years scores 71.43 × 2/3 + 28.57 = **76.19**.

### Matching

- **Skills:** lowercased and whitespace-collapsed, then mapped through an **explicit synonym table** (for example `js→javascript`, `postgres→postgresql`, `k8s→kubernetes`). There is **no fuzzy matching**, so `pythn` ≠ `python`.
- **Qualifications:** a criterion matches when all of its tokens appear in one of the candidate's education entries (degree plus field). Degree spellings are canonicalized (`B.Sc.`, `Bachelor of Science` → `bsc`) and connecting words such as "in" and "of" are ignored. Nothing is inferred: an MSc does not satisfy a BSc requirement.

### Eligibility (reported alongside the score)

- **`not_eligible`:** at least one confirmed failure. That means a required skill is missing, the candidate has fewer years than the minimum, or a *mandatory* qualification is missing.
- **`undetermined`:** there is no confirmed failure, but data needed for a mandatory check is missing.
- **`eligible`:** every mandatory check passes.

A missing required skill **lowers the score proportionally** and also makes the candidate not eligible. It does not zero the score.

### Missing data

If the candidate has no skills, no experience value, or no education for an applicable component, that component is marked `missing_data` and contributes 0 points, and the assessment becomes `incomplete`.

- **Not a failure:** missing data is never treated as a confirmed failure, and it never earns marks.
- **Upper bound:** the response includes `score_upper_bound`, the score the candidate would get if the missing data turned out perfect.

### Ranking and recalculation

- **Ranking** happens within a job: **score descending** (unscored last), then **application `created_at` ascending**, then **application `id` ascending**. The ranking is deterministic, and `score_tied` flags shared scores.
- **Recalculation:** editing a candidate, or an open job's criteria, rescores that candidate's or job's Pending, Under Review and Shortlisted applications. **Rejected** applications keep the score the decision was based on and are marked `is_stale` instead.
- **Old results:** results produced by an older scoring version are reported as stale.
- **Closed jobs** cannot be edited until they are reopened.

---

## 15. Authentication, authorization and tenant isolation

**Sessions.**

- **Passwords** are hashed with **Argon2id**; older PBKDF2 hashes are upgraded on login.
- **Login** issues opaque random access and refresh tokens in **HttpOnly** cookies. The database stores only their SHA-256 hashes, and no token is ever exposed to JavaScript.
- **Expiry:** access tokens last 15 minutes. Refresh tokens last 7 days of inactivity and **rotate on every refresh**; reusing an old refresh token revokes the whole session.
- **Revocation:** logging out or deactivating a user revokes their sessions immediately.

**CSRF and Origin.**

- Every unsafe authenticated request must carry a matching `X-CSRF-Token` *and* come from an allowed `Origin`.
- Registration and login also check the `Origin`.
- `GET /api/auth/csrf` lets the app recover a token after a page reload. It refuses cross-site requests (by `Origin`, or by `Sec-Fetch-Site` when `Origin` is absent).

**Authorization.** Roles are checked in route dependencies (`require_roles`). The API never accepts a role from a client: public registration always creates an HR user, and HR users cannot list, create or deactivate users, or read other users' activity.

**Tenant isolation**, in three layers:

1. **API:** no endpoint accepts a `workspace_id`. It is always taken from the authenticated user, and request bodies that contain unknown fields are rejected.
2. **Services:** every query filters by `workspace_id`. Another workspace's IDs return **404**, so the API never reveals whether a record exists.
3. **Database:** composite `(id, workspace_id)` foreign keys make links between workspaces impossible, even if a code path were wrong.

**Data protection.**

- Error responses never include stack traces; full details go to the server log.
- Audit metadata strips secret-like keys.
- Resume contents and file names are never logged.
- Resume downloads are authenticated, served as attachments, and never cached.

---

## 16. Testing

### Commands

```powershell
python -m pytest -q                                   # backend (SQLite; PostgreSQL-only tests skip)

# Full suite including PostgreSQL-only tests, against a DISPOSABLE migrated database:
$env:DATABASE_URL = "postgresql+psycopg://user:pass@127.0.0.1:5432/screening_test"
python -m alembic upgrade head
$env:TEST_POSTGRES_URL = $env:DATABASE_URL
python -m pytest -q

cd frontend; npm test; npm run build                  # frontend tests and production build
```

### Results from the latest run (2026-10-15, branch `deploy/talentlens-production`)

| Suite | Result |
|---|---|
| Backend on SQLite | **161 passed, 45 skipped** (the skips are PostgreSQL-only tests) |
| Backend with PostgreSQL 15 enabled | **206 passed, 0 failed, 0 skipped** |
| `alembic check` on a migrated PostgreSQL database | No differences between models and migrations |
| Frontend (Vitest) | **38 passed** in 5 files |
| Frontend production build (`tsc -b && vite build`) | Succeeded with no errors or warnings |

Passed tests per backend file, from the PostgreSQL run:

| File | Tests | Covers |
|---|---|---|
| `test_screening_engine.py` | 22 | Perfect, partial and zero matches; missing mandatory skills; no preferred skills; incomplete data; invalid weights; experience below and above the minimum; rounding; synonyms; qualifications. All checked against hand-calculated values. |
| `test_screening_api.py` | 8 | Persisted breakdowns, staleness, refresh, ranking ties, concurrent duplicate applications, permissions |
| `test_application_workflow.py` | 12 | Valid and invalid transitions, rejection notes, `expected_status` conflicts, rollback of status and history together, per-job independence, audit coverage, HR and Admin boundaries |
| `test_workflow_postgres.py` | 8 | Real concurrent decisions using row locks, persistence and rollback on PostgreSQL |
| `test_analytics.py` | 22 | Dashboard metrics against seeded, hand-calculated values; filters; skill gaps; activity; isolation (SQLite and PostgreSQL) |
| `test_candidate_job_modules.py` | 15 | CRUD, validation, duplicates, search, filters, pagination, closed jobs, query counts |
| `test_backend_api.py` | 20 | Registration, login, refresh rotation and replay, expiry, CSRF and Origin, roles, isolation |
| `test_resumes.py` | 22 | PDF validation (type, size, malformed, encrypted, page limit), storage, download headers, extraction outcomes, no personal data in logs, access control |
| `test_qa_regressions.py` | 52 | Error format for 404/405, out-of-range IDs rejected with 422, reuse of logged-out credentials, cross-workspace user management (SQLite and PostgreSQL) |
| `test_deployment_config.py` | 7 | Production settings, database address handling, errors logged without being exposed, CSRF recovery after reload, health check |
| `test_app.py`, `test_scoring.py`, `test_backend_models.py` | 12, 5, 1 | The legacy server-rendered app, the legacy scoring module, and model constraints |

Frontend tests by file:

- `client.test.ts` (8): CSRF handling, the single shared refresh on 401, the session-expiry signal, error parsing;
- `forms.test.ts` (15): form schemas that mirror the API's rules;
- `screening-components.test.tsx` (6): accessible score and breakdown output;
- `decision-panel.test.tsx` (5): the rejection-note rule, conflicts, terminal status;
- `resume-suggestions.test.ts` (4): merging suggestions into the form, file checks.

---

## 17. Known limitations and future improvements

**Limitations:**

- **Not publicly deployed yet.** The production configuration was verified locally, not on Render or Vercel.
- **No rate limiting** on login or registration. Add it at the edge before broad public use.
- **No password reset or email verification.** Admins create HR users with an initial password.
- **Skill matching is exact plus listed synonyms.** Unlisted variants (for example "ReactJS Native") won't match until they are added to the synonym table.
- **Resume extraction** uses fixed rules: no OCR for scanned PDFs, and suggestions can be incomplete on unusual layouts. They are always reviewed by HR.
- **Resume PDFs are stored in PostgreSQL.** That suits typical volumes (4–5 MB cap), but very large volumes would call for object storage.
- **Render free plan limits:** the database expires after 30 days, and the API sleeps when idle, so the first request can take about a minute.
- **React Router 6.30** carries two moderate advisories. The open-redirect one is mitigated in our own `next=` handling, and the other only affects server-side rendering, which isn't used. Upgrading to v7 is pending.
- **Legacy code:** the older server-rendered app (`fastapi_app.py`, `templates/`, `candidate_screening.db`) is kept for reference and is not part of the deployed system.

**Future improvements:**

- Rate limiting and account lockout, password reset, and email verification.
- Admin-managed synonym and skill-catalogue editing.
- S3-compatible resume storage with server-side encryption, and OCR for scanned resumes.
- CSV import and export of candidates; job-specific interview stages.
- A CI pipeline (GitHub Actions) running both test suites and the production build on each push.
- An end-to-end browser test suite (for example Playwright) for the full HR scenario.

---

**More documentation:**

- [ENDPOINTS.md](ENDPOINTS.md): full API reference;
- [HOSTING_GUIDE.md](HOSTING_GUIDE.md): deployment steps and the production smoke test;
- [docs/EMPLOYER_REVIEW.md](docs/EMPLOYER_REVIEW.md): review notes and the manual verification checklist.
