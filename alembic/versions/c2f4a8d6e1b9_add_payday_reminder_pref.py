"""add payday_reminder_tg to notification_preferences

Revision ID: c2f4a8d6e1b9
Revises: b7e1d9c4a2f8
Create Date: 2026-05-29 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c2f4a8d6e1b9'
down_revision: Union[str, None] = 'b7e1d9c4a2f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'notification_preferences',
        sa.Column('payday_reminder_tg', sa.Boolean(),
                  server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('notification_preferences', 'payday_reminder_tg')
