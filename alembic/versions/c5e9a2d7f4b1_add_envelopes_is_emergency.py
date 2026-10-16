"""add envelopes.is_emergency (dana darurat, AI Advisor S1) + backfill dari nama

Revision ID: c5e9a2d7f4b1
Revises: a9c3e7d1f5b2
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c5e9a2d7f4b1'
down_revision: Union[str, None] = 'a9c3e7d1f5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "is_emergency" not in {c["name"] for c in insp.get_columns("envelopes")}:
        op.add_column(
            "envelopes",
            sa.Column("is_emergency", sa.Boolean(), nullable=False,
                      server_default=sa.text("false")),
        )
    # Backfill (02-aturan.md §14): amplop tabungan yang namanya mengandung
    # "darurat"/"emergency". Setelah ini user yang menentukan lewat form amplop.
    op.execute(
        "UPDATE envelopes SET is_emergency = true "
        "WHERE purpose IN ('saving', 'sinking_fund') "
        "AND (name ILIKE '%darurat%' OR name ILIKE '%emergency%')"
    )


def downgrade() -> None:
    op.drop_column("envelopes", "is_emergency")
