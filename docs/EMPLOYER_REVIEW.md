# TalentLens: Employer Review Notes

A short companion to the [README](../README.md) for a live review.

**Live app:** https://smart-candidate-screening.vercel.app · **API docs:** https://talentlens-api-o5pl.onrender.com/docs · **Health:** https://talentlens-api-o5pl.onrender.com/health

The free server sleeps when idle, so allow about a minute for the first request. Every number below comes from the latest test run (2026-10-15).

---

## 1. Two-minute architecture explanation

> TalentLens is a multi-tenant recruitment app. It is a **React + TypeScript** single-page app talking to a **FastAPI** service backed by **PostgreSQL**.
>
> - **Layers:** the API is split into routes (HTTP and validation), services (business rules and transactions), and a **pure scoring engine** that has no database access. That makes scoring deterministic and easy to test.
> - **Tenancy:** every workspace is isolated in three layers. No endpoint accepts a workspace ID; every query filters by the user's workspace; and the database's composite foreign keys make links between workspaces impossible.
> - **Authentication:** server-side sessions in HttpOnly cookies, with Argon2id passwords, refresh tokens that rotate and detect reuse, CSRF tokens, and Origin checks.
> - **Deployment:** Vercel serves the app and proxies `/api` to Render, so cookies stay first-party. Render runs the Docker image, which applies Alembic migrations on start, plus managed PostgreSQL.
> - **Audit trail:** every decision is recorded with who made it, when, and why. Concurrent reviewers can't overwrite each other: there's a row lock, plus an optional `expected_status` check.

## 2. One-minute scoring explanation

> Each job has four weighted components: **required skills 50, preferred skills 20, experience 20, qualifications 10** by default. Jobs can set their own weights; they must total exactly 100, and required skills must count for more than 0.
>
> - **Achievement:** each component gets a percentage. For skills it's the weighted share of matched skills. For experience it's years ÷ minimum, **capped at 100%**, so extra years don't inflate the score. For qualifications it's the share of criteria found in the candidate's education.
> - **Points:** a component earns *effective weight × achievement*, and the score is the sum, rounded to 2 decimals. If a job doesn't use a component (say it has no preferred skills), that weight is shared proportionally among the others rather than given away for free.
> - **Matching:** exact after normalization, plus an explicit synonym list (JS = JavaScript). There's no fuzzy guessing.
> - **Eligibility** is reported separately. A missing *required* skill lowers the score in proportion *and* marks the candidate not eligible, so a high score with "not eligible" means "close, but missing a must-have".
> - **Missing data:** if a candidate has no experience recorded, that component scores 0 and the assessment is marked *incomplete*, with an upper bound showing the best possible score. Missing data is never treated as a failure and never earns marks.
> - **Ranking:** score first, then earliest application, then ID, so ties are stable.
> - **Decisions:** scores support decisions but never make them. Every status change is made by a person, and a rejection needs a written reason.

**Worked example, as stored by the API.** The job requires Python, SQL and Kubernetes, prefers Docker, needs 4 years, and lists BSc Computer Science. The candidate has Python, SQL and Docker, 5 years, and a BSc in Computer Science.

| Component | Weight | Achievement | Points |
|---|---|---|---|
| Required skills | 50 | 2 of 3 = 66.67% | 33.33 |
| Preferred skills | 20 | 1 of 1 = 100% | 20.00 |
| Experience | 20 | 5 ≥ 4 → 100% | 20.00 |
| Qualifications | 10 | matched → 100% | 10.00 |
| **Total** | | | **83.33**, not eligible (missing Kubernetes) |

## 3. API at a glance (44 endpoints)

- **Auth:** `csrf`, `register`, `login`, `refresh`, `logout`, `me` under `/api/auth`.
- **Users (Admin):** list, create HR, activate/deactivate.
- **Candidates:** CRUD, search, filters and pagination; resume upload, download, suggestions and remove; `POST /api/resumes/extract`.
- **Jobs:** CRUD, open/close.
- **Applications:** apply, list (all or per job), get, decide (`PATCH`), history, workflow rules.
- **Screening:** get or refresh one application, refresh a whole job, rankings.
- **Activity:** `/api/audit-logs`, `/api/users/{id}/activity`.
- **Analytics:** `dashboard`, `top-applicants`, `activity`, `skill-gaps`.
- **Health:** `/health`, `/api/health`.

Interactive docs are at `/docs`, and the full reference is [ENDPOINTS.md](../ENDPOINTS.md).

## 4. Important automated tests and actual results

| Command | Result |
|---|---|
| `python -m pytest -q` (SQLite) | **161 passed, 45 skipped** (the skips are PostgreSQL-only) |
| `python -m pytest -q` with `TEST_POSTGRES_URL` set (PostgreSQL 15) | **206 passed, 0 failed, 0 skipped** |
| `python -m alembic check` | No differences between models and migrations |
| `npm test` (frontend) | **38 passed** |
| `npm run build` (frontend) | Succeeded, no errors or warnings |

Tests worth pointing to:

- **Scoring is exact.** `tests/test_screening_engine.py` (22 tests) compares the engine with hand calculations: a perfect match = 100, partial = 50.00, missing a mandatory skill = 76.19, no preferred skills = 87.50, incomplete data = 35.00 (upper bound 55.00), below the experience minimum = 92.86, plus invalid weights and rounding.
- **Workflow integrity.** `tests/test_application_workflow.py` covers invalid transitions (409), a rejection without a note (422), a stale `expected_status` (409), and the status and its history rolling back *together* when a write fails.
- **Real concurrency.** `tests/test_workflow_postgres.py` sends two simultaneous identical decisions and checks that exactly one succeeds and only one history entry is written. Removing the row lock makes this test fail.
- **Tenant isolation.** Several suites check that another workspace's candidates, jobs, applications, history, screening, rankings, resumes, analytics and users all return 404 or empty results, never data.
- **Dashboard correctness.** `tests/test_analytics.py` seeds known data and checks exact metrics, for example an overall average of 58.52 and a complete-only average of 71.30 with half-up rounding. It runs on both SQLite and PostgreSQL.
- **QA regressions.** `tests/test_qa_regressions.py` (52 tests) covers the error format for unknown routes, out-of-range IDs returning 422 instead of 500/503, credentials that stop working after logout, and an admin from another workspace being unable to manage users.
- **Production behaviour.** `tests/test_deployment_config.py` covers the production settings, errors logged without being exposed, and **recovering the CSRF token after a page reload in production mode**. That last one is a real defect found and fixed during deployment preparation.

## 5. Manual verification checklist

Run this against the deployed site (see [HOSTING_GUIDE.md](../HOSTING_GUIDE.md)), or locally with `npm run preview` and the production Docker image.

**Setup and access**

- [ ] `GET <api>/health` returns `{"status":"ok","database":"ok"}`, and `<api>/docs` loads.
- [ ] Visiting the site while signed out redirects to **Sign in**, and protected pages redirect back to the original URL after signing in.
- [ ] Register a new workspace; the dashboard shows the empty state with links to create a job and a candidate.

**Core flow**

- [ ] **Reload the page and stay signed in.** Create a candidate (skills, experience, education) and confirm it saves after the reload.
- [ ] The form validation shows inline errors (an invalid email, job weights that don't total 100, a duplicate email returning 409 on the email field).
- [ ] Create a job with required and preferred skills, a minimum experience and a mandatory qualification; the weights total shows 100.
- [ ] On the job page, **Add applicant**. The application page shows the score ring, points per component, matched and missing skill chips, eligibility and warnings, and the arithmetic behind the score.
- [ ] Move the application to **Under Review**, then **Shortlisted**. The history lists both changes with your name, time and notes. Rejecting without a reason is blocked.
- [ ] The dashboard counts, status chart, score-by-job chart and top applicants reflect the changes.
- [ ] The candidate search, filters and pagination work, and the job list's status tabs work.

**Security and persistence**

- [ ] Sign out, register a second workspace, and open the first workspace's application URL: it shows "Not found", and the second dashboard is empty.
- [ ] Sign back in as the first user: all candidates, jobs, applications and history are still present. Repeat after a redeploy or restart of the API.
- [ ] *(Admin, after seeding)* Account → add an HR member, then deactivate them; the deactivated user can no longer sign in.

**Quality**

- [ ] Mobile width (≈375 px): the navigation sheet opens and closes, and there's no horizontal scrolling on the dashboard, lists, forms or application page.
- [ ] The browser console shows no errors during the flow, apart from the expected 401 on the first signed-out check.
- [ ] *(Optional)* Upload a small PDF resume: suggestions appear for review, nothing changes until you save, and the download works.
