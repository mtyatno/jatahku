"""Plugin R1 — model ruang: households.type, incomes.kind (+ backfill), keanggotaan unik

- `households.type` (`rumah_tangga` | `usaha`, bawaan `rumah_tangga`): semua household
  lama adalah ruang keluarga.
- `incomes.kind` (`pemasukan` | `transfer` | `top-up` | `penyesuaian`) dengan backfill
  dari data lama (`app/services/ruang_schema.py`, `KIND_BACKFILL`).
- Unik `(user_id, household_id)` di `household_members`: satu user boleh anggota beberapa
  household, tapi sekali per household.

Kolom: idempoten; `lifespan` (app/main.py, `RUANG_DDL`) juga menambahkannya saat API
restart, jadi tidak ada jendela 500. Backfill dan constraint hanya di sini. Bila ada
keanggotaan ganda di data, migrasi berhenti dengan pesan, tanpa menghapus apa pun.

Revision ID: 1c7e5a9d3b20
Revises: a7c4e2b9d1f3
Create Date: 2026-11-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.ruang_schema import KIND_BACKFILL, RUANG_DDL

revision: str = '1c7e5a9d3b20'
down_revision: Union[str, None] = 'a7c4e2b9d1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UQ = "uq_household_members_user_household"


def upgrade() -> None:
    bind = op.get_bind()
    for stmt in RUANG_DDL:
        op.execute(sa.text(stmt))
    for stmt in KIND_BACKFILL:
        op.execute(sa.text(stmt))

    existing = {u["name"] for u in sa.inspect(bind).get_unique_constraints("household_members")}
    if _UQ not in existing:
        dupes = bind.execute(sa.text(
            "SELECT user_id, household_id, COUNT(*) FROM household_members "
            "GROUP BY user_id, household_id HAVING COUNT(*) > 1"
        )).all()
        if dupes:
            listing = ", ".join(f"user {u} × household {h} ({n} baris)" for u, h, n in dupes)
            raise RuntimeError(
                "Keanggotaan ganda di household_members, constraint unik tidak bisa dibuat. "
                f"Rapikan manual dulu (sisakan satu baris per pasangan): {listing}"
            )
        op.create_unique_constraint(_UQ, "household_members", ["user_id", "household_id"])


def downgrade() -> None:
    op.drop_constraint(_UQ, "household_members", type_="unique")
    op.drop_column("incomes", "kind")
    op.drop_column("households", "type")
