"""add envelope_groups.jenis (AI Advisor Fase 5: kolam harian vs bulanan)

Revision ID: a7c3e9d1f5b2
Revises: d3b8f1a6c2e9
Create Date: 2026-10-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a7c3e9d1f5b2'
down_revision: Union[str, None] = 'd3b8f1a6c2e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL = otomatis (02-aturan.md §3): purpose debt → bulanan, selain itu harian.
    op.add_column('envelope_groups', sa.Column('jenis', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('envelope_groups', 'jenis')
