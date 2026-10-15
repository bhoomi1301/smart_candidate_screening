import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from backend.app.api.errors import install_error_handlers
from backend.app.api.router import api_router
from backend.app.api.routes.health import router as health_router
from backend.app.core.config import Settings, get_settings
from backend.app.db.session import build_engine, build_session_factory

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Send application logs to stdout (captured by the host's log stream) unless logging is already configured."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, engine=None) -> FastAPI:
    configuration = settings or get_settings()
    configure_logging()
    database_engine = engine or build_engine(configuration)
    session_factory = build_session_factory(database_engine)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            with database_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            logger.exception("Database connection failed during application startup")
            raise
        yield
        database_engine.dispose()

    application = FastAPI(
        title="Smart Candidate Screening API",
        version="1.0.0",
        description="Tenant-scoped recruitment management and explainable candidate screening.",
        lifespan=lifespan,
    )
    application.state.settings = configuration
    application.state.engine = database_engine
    application.state.session_factory = session_factory
    if configuration.allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=configuration.allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )
    install_error_handlers(application)
    application.include_router(api_router, prefix="/api")
    application.include_router(health_router)

    @application.get("/", include_in_schema=False)
    def root():
        if configuration.frontend_url:
            return RedirectResponse(configuration.frontend_url, status_code=307)
        return JSONResponse({"detail": "This is the API server. See /docs for the API reference.", "docs": "/docs"})

    return application


app = create_app()
