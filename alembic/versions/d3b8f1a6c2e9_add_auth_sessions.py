"""add auth_sessions + users.tokens_revoked_at (sesi per perangkat, mobile 1.1)

Revision ID: d3b8f1a6c2e9
Revises: c5e9a2d7f4b1
Create Date: 2026-10-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd3b8f1a6c2e9'
down_revision: Union[str, None] = 'c5e9a2d7f4b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "tokens_revoked_at" not in {c["name"] for c in insp.get_columns("users")}:
        op.add_column("users", sa.Column("tokens_revoked_at", sa.DateTime(timezone=True), nullable=True))

    if not insp.has_table("auth_sessions"):
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("refresh_jti", sa.String(64), nullable=False),
            sa.Column("prev_refresh_jti", sa.String(64), nullable=True),
            sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_reason", sa.String(20), nullable=True),
            sa.Column("legacy_token_hash", sa.String(64), nullable=True),
            sa.Column("client", sa.String(100), nullable=True),
            sa.Column("user_agent", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_column("users", "tokens_revoked_at")
