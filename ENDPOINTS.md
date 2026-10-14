# API and Route Reference

This Flask app uses a session-based admin workflow. All routes below are implemented in `app.py` and support the recruitment screening flow.

## Public routes

### GET /
- Redirects logged-in users to the dashboard.
- Redirects logged-out users to the login screen.
- Purpose: application entry point.

### GET /login
- Displays the login page.
- Purpose: HR/admin sign-in screen.

### POST /login
- Accepts email and password.
- Validates credentials against `admin_users` in SQLite.
- Creates a session on success and redirects to the dashboard.
- Purpose: authentication.

## Authenticated routes

### GET /logout
- Clears the session and redirects to `/login`.
- Purpose: sign-out.

### GET /dashboard
- Reads all candidates or a filtered set by status.
- Calculates summary counts for total, pending, shortlisted, rejected, and average score.
- Supports `?status=All|Pending|Shortlisted|Rejected`.
- Purpose: recruiting overview and quick screening filters.

### GET /candidates
- Displays the candidate list.
- Supports a search query via `?q=...` for name, email, or skill.
- Purpose: searchable candidate table for HR review.

### POST /candidates/add
- Accepts name, email, experience, and skills.
- Validates email and numeric experience input.
- Calculates the match score using the active job profile.
- Stores the new record with status `Pending`.
- Purpose: add a candidate to the pipeline.

### POST /candidates/<int:candidate_id>/status
- Updates the candidate status to `Pending`, `Shortlisted`, or `Rejected`.
- Purpose: move candidates through the hiring stages.

### POST /candidates/<int:candidate_id>/delete
- Deletes the selected candidate from the database.
- Purpose: remove candidates no longer in consideration.

### GET /jobs
- Displays all stored job requirements and the currently active job.
- Purpose: manage hiring roles and screening criteria.

### POST /jobs
- Supports several actions via the `action` form field:
  - `add`: creates a new job requirement with title, description, skills, and minimum experience
  - `edit`: updates an existing job record
  - `activate`: marks a specific job as the active one used for candidate scoring
  - `delete`: removes a non-required job profile
- Recalculates candidate scores whenever the active job changes.
- Purpose: maintain multiple roles and update screening logic safely.

## Matching logic summary

The app computes a match percentage using three main inputs:

- required skill set from the active job
- candidate skill set from the application profile
- years of experience versus the minimum experience requirement

The calculation is:

- overlap = number of skills present in both sets
- skill percentage = (overlap / total required skills) * 100
- experience bonus = +10 percentage points if the candidate meets the minimum experience
- final score is capped between 0 and 100

This gives recruiters a simple, explainable score for candidate prioritization without requiring machine learning.
