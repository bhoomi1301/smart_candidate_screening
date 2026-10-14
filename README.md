# Smart Candidate Screening System

A lightweight Python Flask recruitment application for HR teams to add candidates, evaluate them against job requirements, and shortlist or reject applicants.

## Features
- HR/Admin login with demo credentials
- Candidate creation form with name, email, experience, and skills
- Searchable candidate table
- Job requirement configuration for required skills and minimum experience
- Automatic skill-match score calculation
- Candidate status tracking: Pending, Shortlisted, Rejected
- Dashboard summarizing counts by status and match quality
- Responsive layout for desktop and mobile screens
- SQLite database with seed data for testing

## Tech Stack
- Python 3.13
- Flask
- SQLite
- Jinja2 templates
- HTML/CSS

## Local Setup
1. Open a terminal in the project folder.
2. Create and activate a virtual environment if needed.
3. Install dependencies:
   ```bash
   c:/python313/python.exe -m pip install -r requirements.txt
   ```
4. Start the app:
   ```bash
   c:/python313/python.exe app.py
   ```
5. Open http://127.0.0.1:5000/login in a browser.
6. Use the credentials stored in `demo_credentials.txt` for the login flow.

## App Usage
- Log in with the demo credentials.
- Manage job requirements from the Jobs page.
- Add candidates from the Candidates page.
- Search and filter by name, email, or skill.
- Update candidate status and review match scores from the dashboard.

## Database
The app uses a local SQLite file called `candidate_screening.db` in the project root. It is pre-populated with sample admin and candidate records when the app first starts.

## Notes
This project was built as a Python-based alternative to a Node implementation and is ready for local testing in a standard Python environment.
