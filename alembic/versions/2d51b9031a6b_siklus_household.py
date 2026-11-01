"""Siklus anggaran per household: households.payday_day, monthly_snapshots.allocated_amount/spent_amount

- `households.payday_day` (INTEGER NULL): sumber kebenaran tanggal gajian semua anggota, owner yang
  menentukan. NULL = belum dimigrasi (diturunkan dari anggota saat pertama dibaca), jadi tanpa DEFAULT.
- `monthly_snapshots.allocated_amount` dan `spent_amount` (NUMERIC(15,2) NULL): alokasi dan pengeluaran
  periode itu. NULL = snapshot lama yang belum dihitung ulang.
- Backfill `households.payday_day` dari anggota yang paling berhak (owner, lalu admin, lalu yang tertua),
  hanya untuk household yang masih NULL.

Idempoten: startup app (main.py lifespan) juga menjalankan HOUSEHOLD_CYCLE_DDL, jadi migrasi ini aman
dijalankan sebelum ATAU sesudah deploy, dan tidak ada jendela 500 (kolom nullable, model menerima NULL).
Pernyataan SQL-nya satu sumber dengan lifespan: app/services/household_cycle_schema.py.

Riwayat snapshot lama dihitung ulang oleh skrip terpisah, bukan oleh migrasi ini:
`python -m app.scripts.siklus_household --dry-run`, lalu `--apply` (docs/siklus-household.md).

Revision ID: 2d51b9031a6b
Revises: b1d4a7c2e9f0
Create Date: 2026-11-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.household_cycle_schema import HOUSEHOLD_CYCLE_DDL

revision: str = '2d51b9031a6b'
down_revision: Union[str, None] = 'b1d4a7c2e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for stmt in HOUSEHOLD_CYCLE_DDL:
        op.execute(sa.text(stmt))


def downgrade() -> None:
    # Hanya bermakna bersama kode lama: kode versi ini menambahkan ketiga kolom lagi saat API restart (lifespan).
    # Tanpa DROP TYPE: migrasi ini tidak membuat tipe baru.
    op.execute("ALTER TABLE monthly_snapshots DROP COLUMN IF EXISTS spent_amount")
    op.execute("ALTER TABLE monthly_snapshots DROP COLUMN IF EXISTS allocated_amount")
    op.execute("ALTER TABLE households DROP COLUMN IF EXISTS payday_day")
