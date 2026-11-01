"""Plugin R5: ruang_batasan, ruang_undangan, ruang_draf, ruang_audit (peran, batasan, persetujuan ruang usaha)

Hanya tabel baru; tidak ada kolom baru di tabel lama, jadi tidak ada jendela 500 antara deploy dan migrasi.
Idempoten: startup app (main.py lifespan) juga menjalankan create_all, jadi migrasi ini aman dijalankan sebelum
ATAU sesudah deploy. Bentuk API: docs/plugin/04-kontrak-api.md §2.

Revision ID: c5r5a8e2d417
Revises: 2d51b9031a6b
Create Date: 2026-11-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c5r5a8e2d417'
down_revision: Union[str, None] = '2d51b9031a6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _waktu():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ruang_batasan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("jabatan", sa.String(length=50), nullable=True),
        sa.Column("jenis_catatan", _JSON, nullable=False),
        sa.Column("amplop_ids", _JSON, nullable=True),
        sa.Column("batas_nominal", sa.Numeric(15, 2), nullable=True),
        sa.Column("foto_nota_di_atas", sa.Numeric(15, 2), nullable=True),
        sa.Column("jendela_ubah", sa.String(length=20), server_default="hari_sama", nullable=False),
        sa.Column("lihat_saldo", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("jam_kerja", _JSON, nullable=True),
        sa.Column("diubah_oleh", sa.Uuid(), nullable=True),
        *_waktu(),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["diubah_oleh"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "user_id", name="uq_ruang_batasan"),
        if_not_exists=True,
    )
    op.create_index("ix_ruang_batasan_household_id", "ruang_batasan", ["household_id"], if_not_exists=True)

    op.create_table(
        "ruang_undangan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("kode", sa.String(length=20), nullable=False),
        sa.Column("peran", sa.String(length=10), nullable=False),
        sa.Column("dibuat_oleh", sa.Uuid(), nullable=True),
        sa.Column("kedaluwarsa", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dipakai_oleh", sa.Uuid(), nullable=True),
        sa.Column("dipakai_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dicabut_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dibuat_oleh"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dipakai_oleh"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kode"),
        if_not_exists=True,
    )
    op.create_index("ix_ruang_undangan_household_id", "ruang_undangan", ["household_id"], if_not_exists=True)

    op.create_table(
        "ruang_draf",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("jenis", sa.String(length=20), nullable=False),
        sa.Column("envelope_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("tanggal", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=20), server_default="webapp", nullable=False),
        sa.Column("is_private", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("receipt_item_id", sa.Uuid(), nullable=True),
        sa.Column("client_ref", sa.String(length=64), nullable=True),
        sa.Column("rincian", _JSON, nullable=False),
        sa.Column("status", sa.String(length=20), server_default="menunggu", nullable=False),
        sa.Column("diputus_oleh", sa.Uuid(), nullable=True),
        sa.Column("diputus_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alasan", sa.String(length=300), nullable=True),
        sa.Column("hasil_id", sa.Uuid(), nullable=True),
        *_waktu(),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["envelope_id"], ["envelopes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["diputus_oleh"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index("ix_ruang_draf_household_status", "ruang_draf", ["household_id", "status"], if_not_exists=True)
    op.create_index("uq_ruang_draf_client_ref", "ruang_draf", ["user_id", "client_ref"], unique=True,
                    postgresql_where=sa.text("client_ref IS NOT NULL"), sqlite_where=sa.text("client_ref IS NOT NULL"),
                    if_not_exists=True)

    op.create_table(
        "ruang_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("aksi", sa.String(length=40), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("rincian", _JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index("ix_ruang_audit_household_waktu", "ruang_audit", ["household_id", "created_at"],
                    if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_ruang_audit_household_waktu", table_name="ruang_audit", if_exists=True)
    op.drop_table("ruang_audit", if_exists=True)
    op.drop_index("uq_ruang_draf_client_ref", table_name="ruang_draf", if_exists=True)
    op.drop_index("ix_ruang_draf_household_status", table_name="ruang_draf", if_exists=True)
    op.drop_table("ruang_draf", if_exists=True)
    op.drop_index("ix_ruang_undangan_household_id", table_name="ruang_undangan", if_exists=True)
    op.drop_table("ruang_undangan", if_exists=True)
    op.drop_index("ix_ruang_batasan_household_id", table_name="ruang_batasan", if_exists=True)
    op.drop_table("ruang_batasan", if_exists=True)
