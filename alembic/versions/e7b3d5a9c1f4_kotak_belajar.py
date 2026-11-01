"""Kotak Struk belajar lintas user: receipt_scans.layout (+ tabel suara/aturan, ditambah Task L2)

- `receipt_scans.layout` (JSONB NULL): kerangka tata letak bukti bayar yang aman (label tersamar, jenis nilai,
  nominal/tanggal, HMAC nama; tanpa nomor dan nama polos), dibuat worker untuk QRIS/transfer/tidak dikenali dan
  dihapus 24 jam sejak dibaca untuk item selesai serta saat kedaluwarsa (app/services/kotak_struk/kerangka.py,
  maintenance.purge_layouts). Kolomnya ada di KOTAK_DDL (app/services/kotak_struk/schema.py).

Idempoten: setiap pernyataan IF NOT EXISTS, dan startup app (main.py lifespan) menjalankan KOTAK_DDL yang sama
(serta create_all untuk tabel baru), jadi migrasi ini aman dijalankan sebelum ATAU sesudah deploy dan tidak ada
jendela 500 (kolom nullable, model menerima NULL).

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
    # --- Task L2: tabel proof_rule_votes dan proof_rules (+ indeks) di sini, dengan if_not_exists=True. ---


def downgrade() -> None:
    # Hanya bermakna bersama kode lama: kode versi ini menambahkan kolomnya lagi saat API restart (lifespan).
    # --- Task L2: drop_table(..., if_exists=True) untuk proof_rules dan proof_rule_votes di sini. ---
    op.execute("ALTER TABLE receipt_scans DROP COLUMN IF EXISTS layout")
