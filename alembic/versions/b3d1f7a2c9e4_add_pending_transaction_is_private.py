"""add pending_transactions.is_private (privacy survives cooling)

Revision ID: b3d1f7a2c9e4
Revises: f2a7c9e4b1d3
Create Date: 2026-07-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b3d1f7a2c9e4'
down_revision: Union[str, None] = 'f2a7c9e4b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'pending_transactions',
        sa.Column('is_private', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_column('pending_transactions', 'is_private')
