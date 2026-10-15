FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini app.py ./
COPY backend ./backend
COPY scripts/start.sh ./scripts/start.sh

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser && chmod +x scripts/start.sh
USER appuser

EXPOSE 8000
CMD ["./scripts/start.sh"]
