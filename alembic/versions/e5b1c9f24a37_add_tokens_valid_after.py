"""add users.tokens_valid_after for token revocation

Revision ID: e5b1c9f24a37
Revises: d3a9f1c5b820
Create Date: 2026-06-01 02:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e5b1c9f24a37'
down_revision: Union[str, None] = 'd3a9f1c5b820'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('tokens_valid_after', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'tokens_valid_after')
