# Deployment Guide

TalentLens is deployed in three parts:

| Part | Where | Config in this repo |
|---|---|---|
| Frontend (React + Vite) | Vercel | `frontend/vercel.json`, `frontend/.env.production` |
| API (FastAPI, `app:app`) | Render Web Service (Docker) | `render.yaml`, `Dockerfile`, `scripts/start.sh` |
| Database | Render managed PostgreSQL | `render.yaml` |

## How requests flow

The browser only ever talks to the Vercel domain. `frontend/vercel.json` rewrites `/api/*` (and `/health`) to the Render service, and serves `index.html` for every other path so client-side routes survive a reload.

Because the API is reached through the site's own origin, the HttpOnly auth cookies are **first-party**. That matters: `*.vercel.app` and `*.onrender.com` are different sites, and browsers increasingly block cross-site (third-party) cookies, so a direct cross-origin setup is unreliable. CSRF tokens, Origin checks, CORS restrictions and validation all stay enabled.

## 1. Prerequisites

- The code pushed to GitHub (`render.yaml`, `Dockerfile`, `scripts/`, `frontend/vercel.json` and `frontend/.env.production` included).
- Accounts on [Render](https://render.com) and [Vercel](https://vercel.com), each connected to the GitHub repository.
- No secrets are stored in Git. `.env` files are ignored; the values below are entered in the Render and Vercel dashboards.

## 2. Render: database and API

1. Render dashboard → **New → Blueprint** → choose this repository. Render reads `render.yaml` and proposes:
   - `talentlens-db`: PostgreSQL. The free plan expires after 30 days; choose a paid plan for anything longer-lived.
   - `talentlens-api`: a Docker web service with health check `/health`.
2. When prompted for the `sync: false` values, enter:
   - `ALLOWED_ORIGINS`: `["https://<your-project>.vercel.app"]`. This is a **JSON list** of exact origins, with no trailing slash and no wildcard.
   - `FRONTEND_URL`: `https://<your-project>.vercel.app`.

   If you don't know the Vercel URL yet, enter a placeholder and update both after step 3. Render redeploys when environment variables change.
3. Click **Apply**. In the service's **Logs** you should see:
   ```
   Applying database migrations...
   INFO  [alembic.runtime.migration] Running upgrade ... -> d4a8b1c9e3f2, resume files stored in PostgreSQL
   Migrations complete.
   INFO:     Application startup complete.
   ```
   - **If a migration fails,** the service does not start and the error is in this log.
   - **If a required setting is missing or unsafe** (for example `COOKIE_SECURE`, `ALLOWED_ORIGINS`, or a non-PostgreSQL `DATABASE_URL` while `APP_ENV=production`), startup stops with a clear validation error.
4. Note the service URL, for example `https://talentlens-api.onrender.com`. Check:
   - `https://talentlens-api.onrender.com/health` returns `{"status":"ok","database":"ok"}`;
   - `https://talentlens-api.onrender.com/docs` shows the OpenAPI documentation.

**Migrations** run on every start (`RUN_MIGRATIONS_ON_START=true`). This is idempotent: a database already at head logs only "Migrations complete." On Render plans that support a **pre-deploy command**, you can instead set `RUN_MIGRATIONS_ON_START=false` and use `python -m alembic upgrade head` as the pre-deploy command.

**Database URL:** Render provides `postgresql://…`. The app automatically uses its installed psycopg 3 driver for that address, so paste it as-is if you configure it by hand.

## 3. Vercel: frontend

1. **If the Render service URL is not `https://talentlens-api.onrender.com`,** edit the two `destination` values in `frontend/vercel.json` and push. Rewrites cannot read environment variables, so this hostname lives in the file.
2. Vercel dashboard → **Add New → Project** → import the repository, then:
   - **Root Directory:** `frontend`;
   - **Framework preset:** Vite (detected; build `npm run build`, output `dist`);
   - **Environment variables:** none are required, because `frontend/.env.production` sets `VITE_API_BASE_URL=` (empty, so same-origin through the rewrite) and `VITE_RESUME_MAX_MB=4`.
3. Deploy, then copy the production URL (for example `https://talentlens.vercel.app`).
4. Back in Render, set `ALLOWED_ORIGINS=["https://talentlens.vercel.app"]` and `FRONTEND_URL=https://talentlens.vercel.app` if they were placeholders. If you add a custom domain later, add it to `ALLOWED_ORIGINS` too.

## 4. Environment variables

### API (Render)

| Variable | Required | Value / notes |
|---|---|---|
| `DATABASE_URL` | yes | From the Render database (blueprint wires it). PostgreSQL only in production. |
| `APP_ENV` | yes | `production`. This enforces secure cookies, explicit origins and PostgreSQL. |
| `ALLOWED_ORIGINS` | yes | JSON list of exact frontend origins, e.g. `["https://talentlens.vercel.app"]`. |
| `COOKIE_SECURE` | yes | `true` (HTTPS only). |
| `COOKIE_SAMESITE` | yes | `lax`. Use `none` only for a direct cross-site setup without the Vercel rewrite. |
| `FRONTEND_URL` | recommended | The frontend URL; `GET /` on the API redirects there. |
| `RESUME_MAX_BYTES` | recommended | `4194304` (4 MB), below Vercel's ~4.5 MB proxied request-body limit. |
| `RESUME_MAX_PAGES` | optional | Default `50`. |
| `RUN_MIGRATIONS_ON_START` | optional | Default `true`; see above. |
| `ACCESS_TOKEN_TTL_SECONDS`, `REFRESH_TOKEN_TTL_SECONDS` | optional | Defaults are 900 (15 minutes) and 604800 (7 days). |
| `ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, `SEED_HR_PASSWORD` | only when seeding | See step 5. Never committed and never used as runtime defaults. |

`PORT` is provided by Render. The image runs as a non-root user and trusts the platform proxy's `X-Forwarded-*` headers so the app sees HTTPS.

### Frontend (Vercel, build time)

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | Empty (set in `frontend/.env.production`). Only set an absolute API URL for a cross-site setup without the rewrite. |
| `VITE_RESUME_MAX_MB` | `4` (set in `frontend/.env.production`); keep it equal to `RESUME_MAX_BYTES`. |

## 5. Demo accounts (optional)

Visitors can register their own workspace on the public site; this needs no setup. To also provide a prepared demo workspace, run the seed **once**. It is idempotent: a second run reports `created: False` and adds nothing. It creates:

- an Admin (`ADMIN_EMAIL`) and an HR user (`hr@company.com`) in the "Demo Hiring Workspace";
- 2 jobs, 4 candidates, and 4 screened applications.

How to run it:

- **From your computer (works on every plan):** copy the database's **External Database URL** from Render, then in PowerShell:
  ```powershell
  $env:DATABASE_URL = "<External Database URL>"
  $env:ADMIN_EMAIL = "demo.admin@yourdomain.com"
  $env:SEED_ADMIN_PASSWORD = "<a strong password>"
  $env:SEED_HR_PASSWORD = "<another strong password>"
  python -m backend.app.seed
  ```
  Do this only after the API has started once, so the migrations have run.
- **From the Render Shell (paid plans):** add the three seed variables to the service, run `python -m backend.app.seed` in the Shell, then remove the passwords from the environment.

Share the demo credentials with evaluators out of band. Do not commit them.

## 6. Production smoke test

Run this after every deployment against the public URLs:

1. `GET https://<api>/health` returns `{"status":"ok","database":"ok"}`, and `https://<api>/docs` loads.
2. `https://<frontend>/` redirects to `/login`. Register a new workspace, which lands on the dashboard with the empty state.
3. Reload the page and stay signed in. Create a candidate (skills, experience, education); it should save without errors. *A save failing after a reload means the CSRF recovery path is broken.*
4. Create a job with required and preferred skills, minimum experience, and a qualification.
5. On the job page, **Add applicant**. The application page shows a score, the breakdown and the eligibility.
6. Move the application to **Under Review**, then **Shortlisted**. The history shows both changes with your name.
7. The dashboard shows 1 candidate, 1 open job, 1 application and 1 Shortlisted, plus the charts.
8. Open the job and the application pages via their URLs in a new tab. Both load directly (SPA fallback).
9. Sign out. Register a second workspace, then open the first workspace's application URL: it should show "Not found". The second user's dashboard is empty.
10. Sign back in as the first user: all records are still there. Trigger a redeploy (or restart) of the API in Render, then reload: the records persist.
11. **Optional:** upload a small PDF resume on a candidate, check that the suggestions appear, and download it.

## 7. Operations

- **Logs:** Render → service → Logs. Migrations, startup, and every unhandled or database error (with traceback) are written there. Clients only ever receive a generic error message.
- **Free-plan behaviour:** the API sleeps after ~15 minutes idle, and the first request can take up to a minute while it wakes. Free databases expire after 30 days, so upgrade for longer evaluations.
- **Backups:** paid Render PostgreSQL plans include daily backups. Resume PDFs live in the database (`resume_files`), so they are included.
- **Not yet in place:** request-rate limiting for login and registration. Add it at the edge (for example a Vercel firewall rule or Render rate limiting) before broad public use.

## Local production check

To reproduce the production setup locally (Docker, PostgreSQL, the Vercel-style proxy):

```powershell
docker network create tl
docker run -d --name tl-db --network tl -e POSTGRES_USER=tl -e POSTGRES_PASSWORD=<pw> -e POSTGRES_DB=tl postgres:15-alpine
docker build -t talentlens-api .
docker run -d --name tl-api --network tl -p 127.0.0.1:8020:8000 -e DATABASE_URL=postgresql://tl:<pw>@tl-db:5432/tl -e APP_ENV=production -e COOKIE_SECURE=true -e COOKIE_SAMESITE=lax -e 'ALLOWED_ORIGINS=["http://localhost:4173"]' -e RESUME_MAX_BYTES=4194304 talentlens-api
cd frontend
"VITE_DEV_PROXY_TARGET=http://127.0.0.1:8020" | Out-File -Encoding ascii .env.production.local
npm run build
npm run preview   # http://localhost:4173 proxies /api like Vercel does
```
