from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings, get_settings


def build_engine(settings: Settings | None = None):
    configuration = settings or get_settings()
    options = {"pool_pre_ping": True}
    if configuration.database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if configuration.database_url.endswith(":memory:"):
            from sqlalchemy.pool import StaticPool

            options["poolclass"] = StaticPool
    engine = create_engine(configuration.database_url, **options)
    if configuration.database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


def build_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session
