"""resume files stored in PostgreSQL

Revision ID: d4a8b1c9e3f2
Revises: b81f4c6e2d90
Create Date: 2026-10-15 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4a8b1c9e3f2'
down_revision: Union[str, None] = 'b81f4c6e2d90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('resume_files',
    sa.Column('resume_id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('size_bytes > 0', name='ck_resume_file_size_positive'),
    sa.ForeignKeyConstraint(['resume_id'], ['candidate_resumes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('resume_id')
    )
    op.create_index('ix_resume_files_workspace', 'resume_files', ['workspace_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_resume_files_workspace', table_name='resume_files')
    op.drop_table('resume_files')
