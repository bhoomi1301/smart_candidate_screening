"""screening engine v2: eligibility, assessment status, staleness, ranking index

Revision ID: a3c9d2e7f415
Revises: e748174ef80e
Create Date: 2026-10-15 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c9d2e7f415'
down_revision: Union[str, None] = 'e748174ef80e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('screening_results', sa.Column('eligibility', sa.String(length=20), nullable=False, server_default='undetermined'))
    op.add_column('screening_results', sa.Column('assessment_status', sa.String(length=20), nullable=False, server_default='incomplete'))
    op.add_column('screening_results', sa.Column('is_stale', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('screening_results', sa.Column('stale_reason', sa.String(length=200), nullable=True))
    op.create_check_constraint('ck_screening_result_eligibility', 'screening_results', "eligibility IN ('eligible', 'not_eligible', 'undetermined')")
    op.create_check_constraint('ck_screening_result_assessment_status', 'screening_results', "assessment_status IN ('complete', 'incomplete')")
    # Results produced by the previous engine stay visible but must be refreshed before they are trusted.
    op.execute(
        "UPDATE screening_results SET is_stale = true, stale_reason = 'scoring_version_changed' "
        "WHERE scoring_version <> 'screening-v2'"
    )
    op.create_index('ix_applications_job_ranking', 'applications', ['workspace_id', 'job_id', 'current_screening_score', 'created_at', 'id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_applications_job_ranking', table_name='applications')
    op.drop_constraint('ck_screening_result_assessment_status', 'screening_results', type_='check')
    op.drop_constraint('ck_screening_result_eligibility', 'screening_results', type_='check')
    op.drop_column('screening_results', 'stale_reason')
    op.drop_column('screening_results', 'is_stale')
    op.drop_column('screening_results', 'assessment_status')
    op.drop_column('screening_results', 'eligibility')
