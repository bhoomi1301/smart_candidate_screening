# Smart Candidate Screening System

A lightweight Flask recruitment app for HR teams to manage job openings, score candidates, track status, and review shortlist decisions.

## Features
- HR/admin login with demo credentials
- Dashboard with total/pending/shortlisted/rejected summaries
- Clickable dashboard filters for candidate status views
- Multiple job profiles with title, description, required skills, and minimum experience
- Job activation so one role becomes the active screening benchmark at a time
- Candidate creation with email validation and experience checks
- Searchable candidate table by name, email, or skill
- Candidate status updates: Pending, Shortlisted, Rejected
- Candidate deletion support
- Automatic skill-match scoring against the active job requirements
- Responsive UI and SQLite-backed storage

## Tech Stack
- Python 3.13+
- Flask
- SQLite
- Jinja2
- HTML/CSS
- pytest for regression testing

## Local Setup
1. Open a terminal in the project folder.
2. Create and activate a virtual environment if needed.
3. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
4. Start the app:
   ```bash
   python app.py
   ```
5. Open http://127.0.0.1:5000/login in a browser.
6. Use the demo credentials in `demo_credentials.txt` or the default admin login:
   - Email: `admin@company.com`
   - Password: `admin123`

## App Usage
- Log in with the demo credentials.
- Open the Jobs page to add, edit, activate, or delete job requirements.
- Activate a job to set the active criteria used for candidate matching.
- Add candidates from the Candidates page.
- Search by candidate name, email, or skill.
- Update candidate status and review match percentages from the dashboard.
- Delete candidates if they are no longer needed in the pipeline.

## Database
The app uses a local SQLite database in the project root (`candidate_screening.db`). On first run it creates:
- `admin_users`
- `job_requirements`
- `candidates`

It also seeds default sample data for login and initial recruitment testing.

## Notes
This project keeps the original screening workflow intact while adding robust job management and candidate operations for a more realistic recruitment dashboard.
