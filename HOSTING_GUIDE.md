# Hosting Guide

This project is a Flask-based recruitment dashboard. It can be hosted on any platform that supports Python web apps, but the recommended free choices are Render and Railway.

## Recommended free hosting options

### 1) Render
Render is the easiest option for a Flask app like this.

#### Setup steps
1. Push the project to GitHub.
2. Sign in to Render.
3. Click New > Web Service.
4. Connect the repository.
5. Use these settings:
   - Name: `smart-candidate-screening`
   - Runtime: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT`
6. Deploy.

#### Notes
- This app uses SQLite locally, so the database file will be created in the project root.
- For free hosting, keep in mind that the SQLite file may not persist across all providers unless your plan supports persistent storage.
- If you want a fully production-safe pattern, move SQLite to a managed database later.

### 2) Railway
Railway also works well for Python projects.

#### Setup steps
1. Sign up for Railway.
2. Create a new project and import the GitHub repo.
3. Choose a Python service.
4. Set the install command:
   ```bash
   pip install -r requirements.txt
   ```
5. Set the start command:
   ```bash
   gunicorn app:app --bind 0.0.0.0:$PORT
   ```
6. Deploy and copy the public URL.

### 3) PythonAnywhere
PythonAnywhere is also suitable for Flask apps and is beginner-friendly.

#### Setup steps
1. Create an account.
2. Upload or connect the project.
3. Configure a web app with Python.
4. Install requirements from `requirements.txt`.
5. Set the WSGI app to `app.app`.
6. Reload the app.

## Local production-like command
Use this when deploying to a host that supports Gunicorn:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

## Important app notes
- The app expects the database file to exist and initializes it automatically on first run.
- The app uses a session-based admin login.
- Job activation affects candidate scoring because the active job is the one used for match calculation.

## Recommended final flow
1. Push the code to GitHub.
2. Deploy to Render or Railway.
3. Test the login flow and candidate/job management pages.
4. Share the deployment URL and demo credentials privately.

## Suggested environment variables
If needed, you may set:

```bash
SECRET_KEY=your_secure_value
```

This custom secret can be used in place of the default app secret key for better security in hosted environments.
