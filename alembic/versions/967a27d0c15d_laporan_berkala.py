"""Laporan berkala tahap 1: tabel reports dan report_settings, kolom users.email_verified_at

- `reports`: satu laporan beku per user per (jenis, awal periode), unik `uq_reports_user_jenis_periode`; `data` JSONB
  (isi v1, dibangun sekali saat terbit oleh app/services/laporan/job.py). `user_id` ON DELETE CASCADE,
  `household_id` ON DELETE SET NULL (laporan mantan anggota tetap ada saat household dihapus). Kolom `email_*` dan
  indeks antrean `ix_reports_email_antrean` untuk email tahap 2; tahap 1 membiarkan `email_status` NULL.
- `report_settings`: satu baris per user (kunci utama `user_id`, ON DELETE CASCADE), dibuat saat pertama diubah;
  `kata_sandi_enc` = kata sandi PDF laporan terenkripsi Fernet (NULL = belum diatur), tiga toggle bawaan true.
- `users.email_verified_at` (TIMESTAMPTZ NULL, tanpa DEFAULT: akun lama tidak pernah dianggap terverifikasi), lewat
  LAPORAN_DDL (app/services/laporan/schema.py), satu sumber dengan lifespan.

Semua kolom tahap 2 dan 3 (email, kuartalan, tahunan) dibuat di sini, jadi tahap berikutnya tanpa migrasi.

Idempoten: tabel dan indeks lewat if_not_exists=True, kolom lewat ADD COLUMN IF NOT EXISTS, dan startup app (main.py
lifespan) menjalankan create_all untuk kedua tabel serta LAPORAN_DDL yang sama, jadi migrasi ini aman dijalankan
sebelum ATAU sesudah deploy dan tidak ada jendela 500 (kolom users nullable, model menerima NULL). Bentuk tabel sama
persis dengan model `Report` / `ReportSettings` (nama constraint dan indeks, NOT NULL, bawaan server); dijaga
`alembic check` di CI "Migrasi" dan app/tests/test_laporan_model.py (MigrationTests, termasuk bawaan server).

Revision ID: 967a27d0c15d
Revises: e7b3d5a9c1f4
Create Date: 2026-11-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.laporan.schema import LAPORAN_DDL

revision: str = '967a27d0c15d'
down_revision: Union[str, None] = 'e7b3d5a9c1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=True),
        sa.Column("jenis", sa.String(length=16), nullable=False),
        sa.Column("periode_mulai", sa.Date(), nullable=False),
        sa.Column("periode_akhir", sa.Date(), nullable=False),
        sa.Column("payday_day", sa.Integer(), nullable=False),
        sa.Column("data", _JSON, nullable=False),
        sa.Column("terbit_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_status", sa.String(length=16), nullable=True),
        sa.Column("email_alasan", sa.String(length=32), nullable=True),
        sa.Column("email_percobaan", sa.Integer(), server_default="0", nullable=False),
        sa.Column("email_terakhir_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_terkirim_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "jenis", "periode_mulai", name="uq_reports_user_jenis_periode"),
        if_not_exists=True,
    )
    op.create_index("ix_reports_email_antrean", "reports", ["email_status", "email_terakhir_at"],
                    if_not_exists=True)
    op.create_table(
        "report_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kata_sandi_enc", sa.Text(), nullable=True),
        sa.Column("email_on", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("kuartalan_on", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("tahunan_on", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        if_not_exists=True,
    )
    # users.email_verified_at (satu sumber dengan lifespan).
    for stmt in LAPORAN_DDL:
        op.execute(sa.text(stmt))


def downgrade() -> None:
    # Hanya bermakna bersama kode lama: kode versi ini membuat tabel (create_all) dan kolomnya lagi saat API restart
    # (lifespan). Laporan yang sudah terbit dan kata sandi laporan ikut terhapus. Tanpa DROP TYPE: tidak ada tipe baru.
    op.drop_table("report_settings", if_exists=True)
    op.drop_index("ix_reports_email_antrean", table_name="reports", if_exists=True)
    op.drop_table("reports", if_exists=True)
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verified_at")
