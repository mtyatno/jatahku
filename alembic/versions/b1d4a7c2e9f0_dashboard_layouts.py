"""Plugin B1: tabel dashboard_layouts (tata letak Beranda per user per ruang per permukaan)

Idempoten: startup app (main.py lifespan) juga menjalankan create_all, jadi migrasi ini aman
dijalankan sebelum ATAU sesudah deploy. Bentuk dokumen: docs/plugin/04-kontrak-api.md §4.

Revision ID: b1d4a7c2e9f0
Revises: 1c7e5a9d3b20
Create Date: 2026-11-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'b1d4a7c2e9f0'
down_revision: Union[str, None] = '1c7e5a9d3b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "dashboard_layouts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("surface", sa.String(length=30), server_default="beranda", nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("items", _JSON, nullable=False),
        sa.Column("parked", _JSON, nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "household_id", "surface", name="uq_dashboard_layout"),
        if_not_exists=True,
    )
    op.create_index("ix_dashboard_layouts_household_id", "dashboard_layouts", ["household_id"],
                    if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_dashboard_layouts_household_id", table_name="dashboard_layouts", if_exists=True)
    op.drop_table("dashboard_layouts", if_exists=True)
