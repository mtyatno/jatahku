"""Plugin R7: ruang_kamus (kamus kata per ruang usaha, Catat cepat)

Kata → amplop yang dipelajari dari catatan anggota ruang usaha, dipakai semua anggota ruang itu sesudah kata user
sendiri (ADR-P5, docs/plugin/04-kontrak-api.md §2 dan §3). Hanya tabel baru; tidak ada kolom baru di tabel lama,
jadi tidak ada jendela 500 antara deploy dan migrasi. Idempoten: startup app (main.py lifespan) juga menjalankan
create_all, jadi migrasi ini aman dijalankan sebelum ATAU sesudah deploy.

Revision ID: d7r7k4a1m9c3
Revises: 967a27d0c15d
Create Date: 2026-11-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd7r7k4a1m9c3'
down_revision: Union[str, None] = '967a27d0c15d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ruang_kamus",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("keyword", sa.String(length=100), nullable=False),
        sa.Column("envelope_id", sa.Uuid(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("diajarkan_oleh", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["envelope_id"], ["envelopes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["diajarkan_oleh"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "keyword", "envelope_id", name="uq_ruang_kamus"),
        if_not_exists=True,
    )
    op.create_index("ix_ruang_kamus_household_keyword", "ruang_kamus", ["household_id", "keyword"],
                    if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_ruang_kamus_household_keyword", table_name="ruang_kamus", if_exists=True)
    op.drop_table("ruang_kamus", if_exists=True)
