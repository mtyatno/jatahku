"""Kotak Struk belajar lintas user: receipt_scans.layout, tabel proof_rule_votes dan proof_rules

- `receipt_scans.layout` (JSONB NULL): kerangka tata letak bukti bayar yang aman (label tersamar, jenis nilai,
  nominal/tanggal, HMAC nama; tanpa nomor dan nama polos), dibuat worker untuk QRIS/transfer/tidak dikenali dan
  dihapus 24 jam sejak dibaca untuk item selesai serta saat kedaluwarsa (app/services/kotak_struk/kerangka.py,
  maintenance.purge_layouts). Kolomnya ada di KOTAK_DDL (app/services/kotak_struk/schema.py).
- `proof_rule_votes`: satu suara koreksi per user per aturan (jenis, kunci aplikasi, label; tanpa nama/nomor/nominal),
  `user_id` ON DELETE CASCADE, `household_id` tanpa FK (hanya dihitung).
- `proof_rules`: aturan dari >= 2 user berbeda, status menunggu | disetujui | ditolak | dicabut, unik
  (kind, rule_key, value), indeks status; `decided_by` ON DELETE SET NULL (app/services/kotak_struk/belajar.py).

Idempoten: setiap pernyataan IF NOT EXISTS (tabel dan indeks lewat if_not_exists=True), dan startup app (main.py
lifespan) menjalankan KOTAK_DDL yang sama serta create_all untuk kedua tabel baru, jadi migrasi ini aman dijalankan
sebelum ATAU sesudah deploy dan tidak ada jendela 500 (kolom nullable, model menerima NULL).

Revision ID: e7b3d5a9c1f4
Revises: 2d51b9031a6b
Create Date: 2026-11-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.kotak_struk.schema import KOTAK_DDL

revision: str = 'e7b3d5a9c1f4'
down_revision: Union[str, None] = '2d51b9031a6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # receipt_scans: semua kolom Kotak Struk, termasuk `layout` (satu sumber dengan lifespan).
    for stmt in KOTAK_DDL:
        op.execute(sa.text(stmt))
    # Suara dan aturan belajar (sama persis dengan model ProofRuleVote / ProofRule; `alembic check` di CI "Migrasi").
    op.create_table(
        "proof_rule_votes",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("rule_key", sa.String(length=60), nullable=False),
        sa.Column("value", sa.String(length=60), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("kind", "rule_key", "value", "user_id"),
        if_not_exists=True,
    )
    op.create_table(
        "proof_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("rule_key", sa.String(length=60), nullable=False),
        sa.Column("value", sa.String(length=60), nullable=False),
        sa.Column("users", sa.Integer(), nullable=False),
        sa.Column("households", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "rule_key", "value", name="uq_proof_rule"),
        if_not_exists=True,
    )
    op.create_index("ix_proof_rules_status", "proof_rules", ["status"], if_not_exists=True)


def downgrade() -> None:
    # Hanya bermakna bersama kode lama: kode versi ini menambahkan kolomnya lagi saat API restart (lifespan).
    op.drop_index("ix_proof_rules_status", table_name="proof_rules", if_exists=True)
    op.drop_table("proof_rules", if_exists=True)
    op.drop_table("proof_rule_votes", if_exists=True)
    op.execute("ALTER TABLE receipt_scans DROP COLUMN IF EXISTS layout")
