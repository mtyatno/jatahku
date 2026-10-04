"""add users.google_id (Masuk dengan Google)

Revision ID: a9c3e7d1f5b2
Revises: e4c8a1f9b2d6
Create Date: 2026-10-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a9c3e7d1f5b2'
down_revision: Union[str, None] = 'e4c8a1f9b2d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "google_id" not in {c["name"] for c in insp.get_columns("users")}:
        op.add_column("users", sa.Column("google_id", sa.String(255), nullable=True))
    if "ix_users_google_id" not in {i["name"] for i in insp.get_indexes("users")}:
        op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_google_id", table_name="users")
    op.drop_column("users", "google_id")
