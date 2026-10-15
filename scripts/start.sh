#!/bin/sh
# Production entry point. Migrations run first so a failed migration stops the deploy with the
# error in the service log, instead of serving requests against an out-of-date schema.
# On hosts with a separate pre-deploy step (e.g. Render paid plans) set RUN_MIGRATIONS_ON_START=false
# and run `python -m alembic upgrade head` there instead.
set -eu

if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ]; then
  echo "Applying database migrations..."
  python -m alembic upgrade head
  echo "Migrations complete."
fi

# --proxy-headers: trust X-Forwarded-Proto/For from the platform's load balancer so the app sees HTTPS.
exec uvicorn app:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
  --no-server-header
