"""audit log actor index for activity queries

Revision ID: b81f4c6e2d90
Revises: a3c9d2e7f415
Create Date: 2026-10-15 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b81f4c6e2d90'
down_revision: Union[str, None] = 'a3c9d2e7f415'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_audit_logs_workspace_actor_created', 'audit_logs', ['workspace_id', 'actor_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_audit_logs_workspace_actor_created', table_name='audit_logs')
