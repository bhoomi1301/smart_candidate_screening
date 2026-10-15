from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import build_engine
from backend.app.models.application import Application
from backend.app.models.candidate import Candidate
from backend.app.models.job import Job
from backend.app.models.workspace import Workspace


def test_database_constraints_prevent_cross_tenant_applications_and_duplicates():
    settings = Settings(_env_file=None, app_env="test", database_url="sqlite:///:memory:")
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            workspace_one = Workspace(name="Workspace One", slug="workspace-one")
            workspace_two = Workspace(name="Workspace Two", slug="workspace-two")
            db.add_all([workspace_one, workspace_two])
            db.flush()
            candidate = Candidate(workspace_id=workspace_one.id, full_name="Casey Candidate", email="casey@example.com")
            job_one = Job(workspace_id=workspace_one.id, title="Engineer One", description="", minimum_experience=Decimal("0"), criterion_weights={})
            job_two = Job(workspace_id=workspace_two.id, title="Engineer Two", description="", minimum_experience=Decimal("0"), criterion_weights={})
            db.add_all([candidate, job_one, job_two])
            db.flush()
            db.commit()

            cross_tenant = Application(workspace_id=workspace_two.id, candidate_id=candidate.id, job_id=job_two.id)
            db.add(cross_tenant)
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()

            candidate = db.query(Candidate).filter_by(workspace_id=workspace_one.id).one()
            job_one = db.query(Job).filter_by(workspace_id=workspace_one.id).one()
            first = Application(workspace_id=workspace_one.id, candidate_id=candidate.id, job_id=job_one.id)
            db.add(first)
            db.flush()
            db.add(Application(workspace_id=workspace_one.id, candidate_id=candidate.id, job_id=job_one.id))
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()
    finally:
        engine.dispose()
