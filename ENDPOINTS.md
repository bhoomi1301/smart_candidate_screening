# API and Route Reference

This Flask app uses a simple session-based admin workflow. All routes below are implemented in `app.py` and serve the recruitment screening features.

## Public routes

### GET /
- Redirects logged-in users to the dashboard.
- Redirects logged-out users to the login screen.
- Purpose: app entry point.

### GET /login
- Displays the login page.
- Purpose: HR/admin sign-in screen.

### POST /login
- Receives email and password from the login form.
- Validates credentials against the SQLite `admin_users` table.
- Creates a session on success and redirects to the dashboard.
- Purpose: authentication.

## Authenticated routes

### GET /logout
- Clears the session and redirects to `/login`.
- Purpose: sign-out.

### GET /dashboard
- Fetches all candidate records from SQLite.
- Calculates summary values such as total, pending, shortlisted, rejected, and average score.
- Renders the dashboard view.
- Purpose: overview of recruitment progress and candidate status.

### GET /candidates
- Displays the candidate list.
- Supports a search query via `?q=...` for name, email, or skill filtering.
- Purpose: searchable candidate table for HR review.

### POST /candidates/add
- Accepts candidate details: name, email, experience, skills.
- Calculates a match score using the current job requirement values.
- Stores a new record with the status set to `Pending`.
- Purpose: add a new applicant to the shortlist workflow.

### POST /candidates/<int:candidate_id>/status
- Updates the selected candidate status to `Pending`, `Shortlisted`, or `Rejected`.
- Purpose: move candidates through screening stages.

### GET /jobs
- Shows the current job requirement configuration.
- Purpose: display the active job profile used for pairing candidates with the role.

### POST /jobs
- Updates the required skills and minimum experience.
- Recalculates all candidate match scores after the requirement change.
- Purpose: realign screening logic with the latest job description.

## Matching logic summary

The application computes a match percentage using:

- required skill set from the job requirements
- candidate skill set from the candidate profile
- years of experience compared to minimum experience

The formula is:

- overlap = number of skills present in both required and candidate skill sets
- skill percentage = (overlap / total required skills) * 100
- experience bonus = +10 percentage points if experience meets the minimum
- final score is clamped between 0 and 100

This produces a simple but useful score that helps HR prioritize applicants without requiring ML or advanced NLP.
