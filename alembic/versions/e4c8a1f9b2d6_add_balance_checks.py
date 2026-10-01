"""add balance_checks + transactions/incomes.balance_check_id (cocokkan saldo)

Idempoten: startup app (main.py lifespan) juga membuat tabel & kolom ini, jadi
migrasi ini aman dijalankan sebelum ATAU sesudah deploy.

Revision ID: e4c8a1f9b2d6
Revises: b3d1f7a2c9e4
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e4c8a1f9b2d6'
down_revision: Union[str, None] = 'b3d1f7a2c9e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LINKED = ("transactions", "incomes")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("balance_checks"):
        op.create_table(
            "balance_checks",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("household_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("actual_amount", sa.Numeric(15, 2), nullable=False),
            sa.Column("app_amount", sa.Numeric(15, 2), nullable=False),
            sa.Column("gap", sa.Numeric(15, 2), nullable=False),
            sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_balance_checks_household_id", "balance_checks", ["household_id"])
    for table in _LINKED:
        cols = {c["name"] for c in insp.get_columns(table)}
        if "balance_check_id" not in cols:
            op.add_column(table, sa.Column("balance_check_id", sa.Uuid(), nullable=True))
            op.create_foreign_key(
                f"{table}_balance_check_id_fkey", table, "balance_checks",
                ["balance_check_id"], ["id"],
            )
        idx = {i["name"] for i in insp.get_indexes(table)}
        if f"ix_{table}_balance_check_id" not in idx:
            op.create_index(f"ix_{table}_balance_check_id", table, ["balance_check_id"])


def downgrade() -> None:
    for table in _LINKED:
        op.drop_index(f"ix_{table}_balance_check_id", table_name=table)
        op.drop_column(table, "balance_check_id")
    op.drop_index("ix_balance_checks_household_id", table_name="balance_checks")
    op.drop_table("balance_checks")
