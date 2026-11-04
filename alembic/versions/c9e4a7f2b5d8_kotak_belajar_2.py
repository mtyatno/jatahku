"""Kotak Struk belajar tahap 2: receipt_scans.sample_lines, tabel proof_sample_consents dan proof_samples, indeks G8

- `receipt_scans.sample_lines` (JSONB NULL): baris teks bukti TERSAMAR untuk donasi contoh, hanya untuk user yang
  setuju dan hanya saat saklar `features.kotak_donasi` menyala (app/services/kotak_struk/donasi.py); dihapus bersama
  `layout`, saat menarik persetujuan, hapus akun, dan gabung akun. Kolomnya ada di KOTAK_DDL
  (app/services/kotak_struk/schema.py).
- `proof_sample_consents`: persetujuan opt-in, satu baris per user (`user_id` PK, ON DELETE CASCADE).
- `proof_samples`: antrean tinjauan sampel donasi (menunggu | disetujui | ditolak), `user_id` ON DELETE CASCADE
  (indeks), `item_id` tanpa FK dan unik (uq_proof_sample_item: satu sampel per item), `decided_by` ON DELETE SET NULL,
  indeks status. Berumur SAMPLE_TTL (30 hari).
- `ux_proof_rules_satu_nilai`: indeks unik parsial proof_rules (kind, rule_key) WHERE status = 'disetujui' AND kind IN
  ('logo', 'arah') — G8: dua persetujuan bersamaan untuk satu kunci logo/arah tidak bisa sama-sama lolos
  (`belajar.decide` menjawab 409, bukan 500). Belum ada aturan logo/arah di produksi saat migrasi ini dibuat, jadi
  indeksnya tidak bisa gagal dibuat karena data lama.

Idempoten: setiap pernyataan IF NOT EXISTS (tabel dan indeks lewat if_not_exists=True), dan startup app (main.py
lifespan) menjalankan KOTAK_DDL yang sama serta create_all untuk kedua tabel baru (beserta indeksnya), jadi migrasi
ini aman dijalankan sebelum ATAU sesudah deploy dan tidak ada jendela 500 (kolom nullable, model menerima NULL).
Indeks G8 pada tabel lama hanya dibuat migrasi ini; tanpanya pemeriksaan NOT EXISTS di `decide` tetap berlaku.

Revision ID: c9e4a7f2b5d8
Revises: e7b3d5a9c1f4
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.kotak_struk.schema import KOTAK_DDL

revision: str = 'c9e4a7f2b5d8'
down_revision: Union[str, None] = 'e7b3d5a9c1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SATU_NILAI = "status = 'disetujui' AND kind IN ('logo', 'arah')"   # sama dengan model ProofRule


def upgrade() -> None:
    # receipt_scans: semua kolom Kotak Struk, termasuk `sample_lines` (satu sumber dengan lifespan).
    for stmt in KOTAK_DDL:
        op.execute(sa.text(stmt))
    # Persetujuan dan sampel donasi (sama persis dengan model ProofSampleConsent / ProofSample; `alembic check` di CI).
    op.create_table(
        "proof_sample_consents",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        if_not_exists=True,
    )
    op.create_table(
        "proof_samples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("rule_key", sa.String(length=60), nullable=True),
        sa.Column("doc_type", sa.String(length=30), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("lines", postgresql.JSONB(), nullable=False),
        sa.Column("user_name", sa.String(length=60), nullable=True),
        sa.Column("truth", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("today", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", name="uq_proof_sample_item"),
        if_not_exists=True,
    )
    op.create_index("ix_proof_samples_user_id", "proof_samples", ["user_id"], if_not_exists=True)
    op.create_index("ix_proof_samples_status", "proof_samples", ["status"], if_not_exists=True)
    op.create_index("ux_proof_rules_satu_nilai", "proof_rules", ["kind", "rule_key"], unique=True,
                    postgresql_where=sa.text(_SATU_NILAI), if_not_exists=True)


def downgrade() -> None:
    # Hanya bermakna bersama kode lama: kode versi ini menambahkan kolomnya lagi saat API restart (lifespan).
    op.drop_index("ux_proof_rules_satu_nilai", table_name="proof_rules", if_exists=True)
    op.drop_index("ix_proof_samples_status", table_name="proof_samples", if_exists=True)
    op.drop_index("ix_proof_samples_user_id", table_name="proof_samples", if_exists=True)
    op.drop_table("proof_samples", if_exists=True)
    op.drop_table("proof_sample_consents", if_exists=True)
    op.execute("ALTER TABLE receipt_scans DROP COLUMN IF EXISTS sample_lines")
