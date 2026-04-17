"""add whatsapp_id and phone columns to users table

Revision ID: ede372e1332d
Revises: 97afb8f817d6
Create Date: 2026-04-17 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'ede372e1332d'
down_revision: Union[str, None] = '97afb8f817d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('whatsapp_id', sa.String(50), nullable=True))
    op.create_index(op.f('ix_users_whatsapp_id'), 'users', ['whatsapp_id'], unique=True)
    op.add_column('users', sa.Column('phone', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'phone')
    op.drop_index(op.f('ix_users_whatsapp_id'), table_name='users')
    op.drop_column('users', 'whatsapp_id')
