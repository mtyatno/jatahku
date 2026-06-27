"""add user_streaks table and check-in nudge prefs

Revision ID: d3a9f1c5b820
Revises: c2f4a8d6e1b9
Create Date: 2026-06-01 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd3a9f1c5b820'
down_revision: Union[str, None] = 'c2f4a8d6e1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_streaks',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('current_streak', sa.Integer(), server_default='0', nullable=False),
        sa.Column('longest_streak', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_logged_days', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_log_date', sa.Date(), nullable=True),
        sa.Column('last_checkin_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.add_column(
        'notification_preferences',
        sa.Column('checkin_nudge_tg', sa.Boolean(),
                  server_default=sa.true(), nullable=False),
    )
    op.add_column(
        'notification_preferences',
        sa.Column('checkin_nudge_time', sa.String(length=5),
                  server_default='21:00', nullable=True),
    )


def downgrade() -> None:
    op.drop_column('notification_preferences', 'checkin_nudge_time')
    op.drop_column('notification_preferences', 'checkin_nudge_tg')
    op.drop_table('user_streaks')
