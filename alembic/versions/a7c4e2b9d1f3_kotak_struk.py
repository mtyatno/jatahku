"""Kotak Struk: perluas receipt_scans + household_merchants + merchant_envelope_map

Idempoten: startup app (main.py lifespan) juga menjalankan KOTAK_DDL dan
create_all, jadi migrasi ini aman dijalankan sebelum ATAU sesudah deploy.

Revision ID: a7c4e2b9d1f3
Revises: a7c3e9d1f5b2
Create Date: 2026-10-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.kotak_struk.schema import KOTAK_DDL

revision: str = 'a7c4e2b9d1f3'
down_revision: Union[str, None] = 'a7c3e9d1f5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "household_merchants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("counterparty_key", sa.String(length=80), nullable=False),
        sa.Column("raw_name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=60), nullable=True),
        sa.Column("city", sa.String(length=60), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "counterparty_key", name="uq_hh_merchant"),
        if_not_exists=True,
    )
    op.create_table(
        "merchant_envelope_map",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("envelope_id", sa.Uuid(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("last_user_id", sa.Uuid(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["household_merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["envelope_id"], ["envelopes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "envelope_id", name="uq_merchant_env"),
        if_not_exists=True,
    )
    for stmt in KOTAK_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # aditif; tidak di-rollback
    pass
