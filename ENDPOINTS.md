# Backend API

OpenAPI is available at `/docs` and `/openapi.json`. Errors have a stable shape: `{"error":{"code":"...","message":"..."}}` where `code` is one of `bad_request` (400), `unauthorized` (401), `forbidden` (403), `not_found` (404), `conflict` (409), or `validation_error` (422); validation errors add safe field locations/details and never echo submitted values. Authentication uses opaque server-side sessions with 15-minute access cookies and rotating seven-day refresh cookies.

## CSRF and tenant rules

Passwords are stored with Argon2id; legacy PBKDF2 hashes are upgraded on successful login. Access and refresh cookies are HttpOnly; raw credentials are never returned in JSON. Access tokens expire after 15 minutes. `POST /api/auth/refresh` rotates the refresh token and access token; refresh tokens expire after seven days of inactivity. Reuse of a rotated refresh credential within its validity window revokes the session. Logout and user deactivation revoke sessions immediately.

Call `GET /api/auth/csrf` and send its `csrf_token` as `X-CSRF-Token` for unsafe authenticated API methods, including refresh and logout. Auth responses include a fresh CSRF token. The CSRF endpoint can reissue a token using a valid refresh cookie after the access cookie expires. Registration/login use exact Origin validation; authenticated writes validate both Origin and CSRF. Cross-origin browser clients require credentialed requests, exact CORS origins, `COOKIE_SECURE=true`, and `COOKIE_SAMESITE=none` over HTTPS.

Public workspace registration always creates an HR user, never an Admin. Admins are provisioned by the protected seed/provisioning path and may add HR users. HR users can manage candidates, jobs, and applications in their workspace. No endpoint accepts a workspace identifier as input; it is taken from the authenticated user. Tenant filters are applied in service queries and composite database foreign keys protect relationship integrity.

## Authentication and users

- `GET /api/auth/csrf`: issue a CSRF token for an active access or refresh session.
- `POST /api/auth/register`: `{ "workspace_name":"Acme Recruiting", "full_name":"Alex HR", "email":"alex@example.com", "password":"at-least-12-characters", "password_confirmation":"at-least-12-characters" }`; creates a workspace and an HR account. Role is never accepted from the client.
- `POST /api/auth/login`: `{ "email":"alex@example.com", "password":"..." }`.
- `POST /api/auth/refresh`: rotate both HttpOnly credentials.
- `POST /api/auth/logout`: revoke the server-side session and clear cookies.
- `GET /api/auth/me`: current active user.
- `GET /api/users`: list workspace users (Admin only).
- `POST /api/users`: create an HR member (Admin only; role cannot be elevated by input).
- `PATCH /api/users/{user_id}/active?is_active=false`: deactivate a workspace user (Admin only).

## Candidates

- `GET /api/candidates?q=alex&skill=python&min_experience=2&max_experience=8&job_id=3&status=Under%20Review&skip=0&limit=25`: workspace-scoped search/filter/pagination returning `{items,total,skip,limit}`. `q` matches name, email, or skill (wildcards are literal); `skill` matches a normalized skill or alias; `job_id` and `status` must match the same application. `total` is the count after all filters, `limit` is 1-100, and results order newest first (creation time, then ID). A page past the end returns empty `items` with the real `total`.
- `POST /api/candidates`: create a candidate with `full_name`, `email`, optional `phone`/`total_experience`, `technical_skills` array, and normalized `education` records.
- `GET /api/candidates/{candidate_id}`: detailed profile, resume metadata when present, applications, screening rationale, and status history.
- `PUT /api/candidates/{candidate_id}`: replace candidate profile; scores are recalculated for non-rejected applications (Rejected keeps the score snapshot its decision was based on).
- `POST /api/candidates/{candidate_id}/resume` (Admin/HR, multipart field `file`): upload or replace a PDF resume (max 5 MB, 50 pages; content-validated). Returns `201 {resume, extraction}`; `extraction` holds unverified suggestions that are **not** applied. Errors: 415 wrong type, 413 too large, 422 empty/malformed/encrypted/too many pages.
- `GET /api/candidates/{candidate_id}/resume/file`: download the stored PDF (workspace members only; attachment, `no-store`). Recorded in the activity log.
- `GET /api/candidates/{candidate_id}/resume/suggestions` (Admin/HR): re-run extraction on the stored PDF; nothing is saved.
- `DELETE /api/candidates/{candidate_id}/resume`: delete the resume and its stored file.
- `POST /api/resumes/extract` (Admin/HR, multipart `file`): validate a PDF and return suggestions for a new candidate without storing it.

Extraction responses: `{status: ok|no_text|no_suggestions|failed, message, page_count, pages_scanned, text_characters, truncated, suggestions: {full_name, emails, phones, skills, education, total_experience}, notice}`; each suggestion includes the `evidence` snippet it came from. See README "Resume upload and extraction".
- `DELETE /api/candidates/{candidate_id}`: remove candidate and dependent applications/history.

Candidate email uniqueness is case-insensitive within a workspace (unique index on `workspace_id, lower(email)`; 409 `conflict`). The same email may exist in different workspaces. `full_name` (2-160 chars, whitespace collapsed) and `email` are required; `phone` must have 6-20 digits using only `+`, spaces, parentheses, dots, or dashes (empty becomes null). Skill strings are trimmed, de-duplicated by alias, and limited to 100 characters/100 skills; experience must be between 0 and 80 years with two decimals. Request bodies cannot provide `workspace_id` or unknown fields. Candidate mutations require the Admin or HR role.

## Jobs

- `GET /api/jobs?status=open|closed&q=engineer&department=Engineering&skip=0&limit=25`: paginated `{items,total,skip,limit}`; `q` searches title and department, `department` is an exact case-insensitive match. Newest first. Each job includes `application_count`.
- `POST /api/jobs`: title, department, description, required/preferred skill arrays, optional per-skill weights, minimum experience, qualifications, and criterion weights. New jobs are `open`.
- `GET /api/jobs/{job_id}`
- `PUT /api/jobs/{job_id}`: replace criteria and recalculate non-rejected screening results. Returns 409 for a closed job (reopen first), so a closed job keeps the criteria its applications were screened against. Status is not accepted here.
- `PATCH /api/jobs/{job_id}/status`: `{ "status":"closed" }` or `{"status":"open"}`; idempotent. Closed jobs reject new applications (409) but their applications, rankings, and history stay readable.
- `DELETE /api/jobs/{job_id}`: 204 only when the job has no applications; otherwise 409 (close it instead).
- Job create/update/status/delete require the Admin or HR role within the authenticated workspace.

Example job body:

```json
{
  "title":"Backend Engineer",
  "department":"Engineering",
  "description":"Own APIs and data integrations.",
  "required_skills":["Python","SQL"],
  "preferred_skills":["PostgreSQL","Docker"],
  "required_skill_weights":{"Python":70,"SQL":30},
  "preferred_skill_weights":{"PostgreSQL":60,"Docker":40},
  "minimum_experience":3,
  "qualifications":[{"name":"Computer Science degree","is_mandatory":false}],
  "criterion_weights":{"required_skills":50,"preferred_skills":20,"experience":20,"qualifications":10}
}
```

Criterion weights must be non-negative, sum to 100, and give required skills a weight above 0. At least one required skill is needed; a skill (or alias) cannot repeat or be both required and preferred. If supplied, per-skill weights must cover every skill in that category exactly once and sum to 100; these weights affect the skill-component score. Qualification names must be unique; qualification weights are all-or-none and sum to 100 when set; they weight the qualifications component, and mandatory qualifications also drive eligibility. Skill links, education, and qualifications are normalized rows, not client-authored JSON documents.

## Applications

- `GET /api/applications/workflow`: statuses, permitted transitions, terminal statuses, and decision rules.
- `POST /api/jobs/{job_id}/applications` (Admin/HR): `{ "candidate_id": 12 }`; creates one application per candidate/job (409 on duplicates, including concurrent ones), its first history entry, and a versioned screening result. Closed jobs return 409.
- `GET /api/applications?job_id=3&status=Under%20Review&skip=0&limit=25`
- `GET /api/jobs/{job_id}/applications?status=Under%20Review&skip=0&limit=25`: paginated job-specific applications with candidate summaries and `total`.
- `GET /api/applications/{application_id}`
- `PATCH /api/applications/{application_id}` (Admin/HR): `{ "status":"Under Review", "notes":"Review started", "expected_status":"Pending" }`. Rejection requires `notes` of at least 10 characters (422). A disallowed transition, a stale `expected_status`, or the same status without notes returns 409. The same status with notes records a comment. The status, history entry, and audit record commit together or roll back together.
- `GET /api/applications/{application_id}/history`: oldest first; each entry has `id`, `previous_status`, `new_status`, `changed_by`, `changed_by_name`, `notes`, and `changed_at`.

## Activity log

- `GET /api/audit-logs?actor_id=&action=application.&resource_type=application&resource_id=&since=&until=&skip=0&limit=50`: `{items, total, skip, limit}`, newest first; `limit` is 1-200. Each item has `actor_id`, `actor_name`, `action`, `resource_type`, `resource_id`, `metadata`, and `created_at`. Admins see the whole workspace. HR users see only their own actions (another user's `actor_id` returns 403).
- `GET /api/users/{user_id}/activity` (Admin only): one user's activity.
- `GET /api/jobs/{job_id}/rankings?eligibility=eligible&skip=0&limit=25`: `{job_id, items, total, skip, limit, ordering, decision_notice}`; each item has `rank`, `score`, `score_tied`, `eligibility`, `assessment_status`, `missing_mandatory_skills`, `is_stale`, and a candidate summary. Order: score desc (unscored last), application `created_at` asc, application ID asc.

## Screening

- `GET /api/applications/{application_id}/screening`: score, eligibility (`eligible`/`not_eligible`/`undetermined`), assessment status (`complete`/`incomplete`), full `score_breakdown` (per-component weights, scores, points, matched/missing skills, experience comparison, qualification evidence, warnings, `score_upper_bound`), `scoring_version`, `evaluated_at`, `is_stale`/`stale_reason`.
- `POST /api/applications/{application_id}/screening`: re-evaluate against current candidate/job data (Admin/HR, CSRF). Never changes application status.
- `POST /api/jobs/{job_id}/screening?include_rejected=false`: re-evaluate all of a job's applications; `{job_id, refreshed, include_rejected}`.

The exact formula, eligibility rules, missing-data policy, and ranking logic are documented in README "Screening engine". Application and candidate-profile responses embed the same `screening_result` (including `eligibility`, `assessment_status`, `is_stale`).
- `GET /health`: database-backed readiness.
- `GET /`: redirects (307) to `FRONTEND_URL` when configured; otherwise returns `{"detail": "...", "docs": "/docs"}`. The API serves no HTML sign-in or registration pages; the TalentLens frontend (`frontend/`) is the browser UI.

Statuses are `Pending`, `Under Review`, `Shortlisted`, and `Rejected`. Allowed transitions are Pending to Under Review/Rejected, Under Review to Shortlisted/Rejected, and Shortlisted to Under Review/Rejected. Rejected is terminal. Each transition records actor, notes, and timestamp. See README "Recruitment workflow" for the full rules and the list of audited actions. Duplicate candidate/job applications return 409; cross-workspace IDs are not found and are also rejected by composite foreign keys.

## Analytics

All analytics endpoints require an authenticated user and are scoped to that user's workspace. Metric definitions are in README "Analytics". The examples below are real responses from the seeded data used in `tests/test_analytics.py`: 5 candidates; 3 jobs (one closed, with no applications); and 5 applications, one of them with incomplete candidate data.

Shared filters (dashboard, skill gaps): `date_from`, `date_to` (inclusive UTC `YYYY-MM-DD`), `job_id`, `department`, `job_status=open|closed`.

### `GET /api/analytics/dashboard`

```json
{
  "generated_at": "2026-10-15T00:00:18.629082Z",
  "filters": {"date_from": null, "date_to": null, "job_id": null, "department": null, "job_status": null},
  "total_candidates": 5,
  "active_job_openings": 2,
  "total_applications": 5,
  "unique_applicants": 4,
  "application_statuses": {"pending": 2, "under_review": 1, "shortlisted": 1, "rejected": 1},
  "status_distribution": [
    {"status": "Pending", "count": 2, "percentage": "40.00"},
    {"status": "Under Review", "count": 1, "percentage": "20.00"},
    {"status": "Shortlisted", "count": 1, "percentage": "20.00"},
    {"status": "Rejected", "count": 1, "percentage": "20.00"}
  ],
  "overall_scores": {
    "application_count": 5, "scored_count": 5, "complete_count": 4, "incomplete_count": 1,
    "stale_count": 0, "unscored_count": 0, "average_score": "58.52", "average_complete_score": "73.15"
  },
  "average_scores_by_job": [
    {
      "job_id": 1, "title": "Backend Engineer", "department": "Engineering", "job_status": "open",
      "application_count": 3, "scored_count": 3, "complete_count": 2, "incomplete_count": 1,
      "stale_count": 0, "unscored_count": 0, "average_score": "47.53", "average_complete_score": "71.30"
    },
    {
      "job_id": 3, "title": "Platform Engineer", "department": "Engineering", "job_status": "closed",
      "application_count": 0, "scored_count": 0, "complete_count": 0, "incomplete_count": 0,
      "stale_count": 0, "unscored_count": 0, "average_score": null, "average_complete_score": null
    }
  ]
}
```

### `GET /api/analytics/jobs/{job_id}/top-applicants?limit=5&eligibility=eligible`

`limit` is 1-50 (default 5). The ordering matches `/api/jobs/{job_id}/rankings`. An unknown or other-workspace job returns 404.

```json
{
  "job_id": 1, "job_title": "Backend Engineer", "job_status": "open", "total_applicants": 3,
  "items": [
    {
      "rank": 1, "application_id": 1, "application_status": "Shortlisted", "applied_at": "2026-03-01T12:00:00Z",
      "score": "100.00", "score_tied": false, "eligibility": "eligible", "assessment_status": "complete",
      "missing_mandatory_skills": [], "is_stale": false, "evaluated_at": "2026-10-15T00:00:18Z",
      "candidate": {"id": 1, "full_name": "Ann Person", "email": "ann@example.com", "total_experience": "5.00", "technical_skills": ["Python", "SQL", "Docker"]}
    }
  ],
  "ordering": "score desc (unscored last), then application created_at asc, then application id asc",
  "decision_notice": "This score ranks applicants to support HR review. It does not make hiring decisions; application status changes are always made by a person."
}
```

### `GET /api/analytics/activity?limit=20&category=application&since=2026-10-01T00:00:00Z`

`limit` is 1-100 (default 20). `category` is one of `candidate`, `job`, `application`, `screening`. Results are newest first, and `total` counts every matching entry.

```json
{
  "items": [
    {
      "id": 23, "action": "application.decision", "category": "application",
      "description": "Changed status from Pending to Under Review",
      "actor_id": 1, "actor_name": "Workspace Admin",
      "resource_type": "application", "resource_id": 5,
      "candidate_name": "Dan Person", "job_title": "Data Analyst",
      "created_at": "2026-10-15T00:00:18Z"
    }
  ],
  "total": 23,
  "limit": 20
}
```

### `GET /api/analytics/skill-gaps?min_applications=3&limit=10`

`min_applications` is 1-1000 (default 3) and `limit` is 1-50 (default 10). The shared filters also apply. Example with `min_applications=2`:

```json
{
  "filters": {"date_from": null, "date_to": null, "job_id": null, "department": null, "job_status": null},
  "min_applications": 2,
  "sufficient_data": true,
  "message": "Showing the 2 most frequently missing required skill(s).",
  "excluded_without_skill_data": 1,
  "items": [
    {"skill": "Excel", "jobs_requiring": 1, "evaluated_applications": 2, "missing_count": 1, "missing_rate": "50.00"},
    {"skill": "SQL", "jobs_requiring": 2, "evaluated_applications": 4, "missing_count": 1, "missing_rate": "25.00"}
  ]
}
```

When there is not enough data (here with `min_applications=5`), the response is `"sufficient_data": false`, `"items": []`, and `"message": "Not enough data: no required skill has at least 5 evaluated applications."`

