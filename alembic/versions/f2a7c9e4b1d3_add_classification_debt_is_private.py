"""add envelope classification, transaction is_private (purpose debt = no DDL)

Revision ID: f2a7c9e4b1d3
Revises: d3a9f1c5b820
Create Date: 2026-07-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f2a7c9e4b1d3'
down_revision: Union[str, None] = 'd3a9f1c5b820'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'envelopes',
        sa.Column('classification', sa.String(length=20), nullable=True),
    )
    op.add_column(
        'transactions',
        sa.Column('is_private', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_column('transactions', 'is_private')
    op.drop_column('envelopes', 'classification')
