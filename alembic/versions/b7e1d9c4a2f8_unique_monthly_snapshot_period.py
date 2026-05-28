"""unique constraint on monthly_snapshots (envelope_id, year, month)

Snapshots are meant to be one-per-envelope-per-period. The app enforces this
with an existence check, but two concurrent runs could still race and insert
duplicates, which would make rollover lookups ambiguous. Add a DB-level unique
constraint as defense-in-depth (deduplicating any pre-existing rows first).

Revision ID: b7e1d9c4a2f8
Revises: ede372e1332d
Create Date: 2026-05-28 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'b7e1d9c4a2f8'
down_revision: Union[str, None] = 'ede372e1332d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove any pre-existing duplicate snapshots, keeping the most recently
    # created row per (envelope_id, year, month). ctid breaks created_at ties.
    op.execute(
        """
        DELETE FROM monthly_snapshots a
        USING monthly_snapshots b
        WHERE a.envelope_id = b.envelope_id
          AND a.year = b.year
          AND a.month = b.month
          AND (a.created_at < b.created_at
               OR (a.created_at = b.created_at AND a.ctid < b.ctid))
        """
    )
    op.create_unique_constraint(
        "uq_snapshot_envelope_period",
        "monthly_snapshots",
        ["envelope_id", "year", "month"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_snapshot_envelope_period", "monthly_snapshots", type_="unique"
    )
