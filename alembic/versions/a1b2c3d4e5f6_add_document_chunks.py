"""add document_chunks (RAG)

Revision ID: a1b2c3d4e5f6
Revises: 68e81825a77d
Create Date: 2026-08-14 22:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '68e81825a77d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'document_chunks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('repository_url', sa.Text(), nullable=False),
        sa.Column('commit_sha', sa.String(length=64), nullable=False),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('language', sa.String(length=50), nullable=False),
        sa.Column('symbol', sa.Text(), nullable=False),
        sa.Column('chunk_type', sa.String(length=30), nullable=False),
        sa.Column('start_line', sa.Integer(), nullable=False),
        sa.Column('end_line', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', sa.JSON(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'repository_url',
            'commit_sha',
            'path',
            'start_line',
            name='uq_document_chunk_version',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_document_chunks_repository_url'),
        'document_chunks',
        ['repository_url'],
        unique=False,
    )
    op.create_index(
        op.f('ix_document_chunks_commit_sha'),
        'document_chunks',
        ['commit_sha'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_document_chunks_commit_sha'), table_name='document_chunks'
    )
    op.drop_index(
        op.f('ix_document_chunks_repository_url'),
        table_name='document_chunks',
    )
    op.drop_table('document_chunks')
