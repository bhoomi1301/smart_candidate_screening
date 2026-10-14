# Hosting Guide for Free Deployment

This project is a Python Flask application. For a free public deployment, the best choices are Render, Railway, or PythonAnywhere. Vercel is usually better for JavaScript frontend apps and can be awkward for Flask unless you are using a more custom server setup.

## Best free options

### Option 1: Render (recommended)
Render is one of the easiest ways to deploy a Python web app for free.

#### Steps
1. Push the project to GitHub.
2. Create a free Render account.
3. Click New > Web Service.
4. Connect your GitHub repository.
5. Use these settings:
   - Name: `smart-candidate-screening`
   - Runtime: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
6. Add a port environment variable if needed:
   - `PORT=10000` (Render usually manages this automatically)
7. Deploy.

#### Important note
This project already has Flask and SQLite support, but for production hosting you should use Gunicorn instead of the development server. Add this to `requirements.txt`:

```
Flask==3.0.3
gunicorn==22.0.0
pytest==8.3.2
```

Then start the app with:

```
gunicorn app:app --bind 0.0.0.0:$PORT
```

### Option 2: Railway
Railway is also a strong free Python hosting option.

#### Steps
1. Sign up for Railway.
2. Create a new project.
3. Import the GitHub repository.
4. Set the service type to `Python`.
5. Use the root folder of the project.
6. Add install command:
   ```bash
   pip install -r requirements.txt
   ```
7. Add start command:
   ```bash
   gunicorn app:app --bind 0.0.0.0:$PORT
   ```
8. Deploy and copy the public URL.

### Option 3: PythonAnywhere
PythonAnywhere is beginner-friendly for Flask apps.

#### Steps
1. Sign up for a free account.
2. Upload or connect the GitHub repo.
3. Create a new web app.
4. Set the project folder and WSGI config.
5. Install requirements with pip.
6. Reload the web app.

## Why not Vercel as the first choice?
Vercel is great for frontend apps and serverless JavaScript projects, but Flask is a Python app with a long-lived web process. It is possible to deploy Python there in some cases, but it is not the easiest or most transparent path for this assignment. For a recruiter-facing Flask app, Render or Railway is usually better and more reliable.

## Tips for sharing with an employer
- Use the deployed public URL in the README.
- Keep the app stable and test the login flow before sending the link.
- Include the demo login credentials in a secure file or private message, not on the visible page.
- If you use a free hosting tier, make sure the app starts automatically and the database persists for demo purposes.

## Recommended final publish flow
For this assignment, the simplest final setup is:

1. Push the project to GitHub.
2. Deploy to Render.
3. Copy the live link.
4. Share the link and credentials privately with the employer.

## Example deployment command
If you want a command to run in a hosted environment, use:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

This is the standard way to run a Flask app in a production-like hosting service.
