"""Plugin U1: tabel Buku Usaha (p_buku_usaha_kontak, _income_meta, _txn_meta, _alokasi)

Empat tabel plugin pertama (AGENTS.md "Plugin dan ruang" aturan 5; docs/plugin/01-kajian.md "Aturan wajib untuk
setiap tabel plugin"): kolom wajib `id`, `household_id`, `created_by`, `created_at`, `updated_at`, `deleted_at`;
indeks diawali `household_id`; enum sebagai String; FK ke inti hanya `households`, `users`, `envelopes`,
`transactions`, `incomes`. Dibuat sekaligus supaya U2–U6 tidak butuh migrasi lagi. Hanya tabel baru: tidak ada
kolom baru di tabel lama, jadi tidak ada jendela 500 antara deploy dan migrasi. Idempoten: startup app (main.py
lifespan) juga menjalankan create_all, jadi migrasi ini aman dijalankan sebelum ATAU sesudah deploy.

Meta 1:1 (`income_meta.income_id`, `txn_meta.transaction_id`) ikut terhapus bila pemasukan/transaksinya dihapus
permanen (CASCADE): meta tanpa induk tidak berarti. `created_by` SET NULL (hapus akun → "Mantan anggota").
Unik per ruang hanya di antara baris hidup (`deleted_at IS NULL`).

Revision ID: u1b0k0u5aha1
Revises: c9e4a7f2b5d8
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'u1b0k0u5aha1'
down_revision: Union[str, None] = 'c9e4a7f2b5d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _wajib():
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _fk_wajib():
    return [
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    ]


def _hidup():
    return {"postgresql_where": sa.text("deleted_at IS NULL"), "sqlite_where": sa.text("deleted_at IS NULL")}


def upgrade() -> None:
    op.create_table(
        "p_buku_usaha_kontak",
        *_wajib(),
        sa.Column("nama", sa.String(length=120), nullable=False),
        sa.Column("peran", sa.String(length=20), nullable=False),
        sa.Column("telepon", sa.String(length=30), nullable=True),
        sa.Column("catatan", sa.String(length=500), nullable=True),
        *_fk_wajib(),
        if_not_exists=True,
    )
    op.create_index("ix_p_buku_usaha_kontak_household_peran_nama", "p_buku_usaha_kontak",
                    ["household_id", "peran", "nama"], if_not_exists=True)

    op.create_table(
        "p_buku_usaha_income_meta",
        *_wajib(),
        sa.Column("income_id", sa.Uuid(), nullable=False),
        sa.Column("jenis", sa.String(length=20), nullable=False),
        sa.Column("kontak_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["income_id"], ["incomes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kontak_id"], ["p_buku_usaha_kontak.id"], ondelete="SET NULL"),
        *_fk_wajib(),
        if_not_exists=True,
    )
    op.create_index("uq_p_buku_usaha_income_meta_income", "p_buku_usaha_income_meta", ["household_id", "income_id"],
                    unique=True, if_not_exists=True, **_hidup())
    op.create_index("ix_p_buku_usaha_income_meta_household_kontak", "p_buku_usaha_income_meta",
                    ["household_id", "kontak_id"], if_not_exists=True)

    op.create_table(
        "p_buku_usaha_txn_meta",
        *_wajib(),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("kontak_id", sa.Uuid(), nullable=True),
        sa.Column("akun", sa.String(length=40), nullable=True),
        sa.Column("proyek", sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kontak_id"], ["p_buku_usaha_kontak.id"], ondelete="SET NULL"),
        *_fk_wajib(),
        if_not_exists=True,
    )
    op.create_index("uq_p_buku_usaha_txn_meta_transaction", "p_buku_usaha_txn_meta",
                    ["household_id", "transaction_id"], unique=True, if_not_exists=True, **_hidup())
    op.create_index("ix_p_buku_usaha_txn_meta_household_kontak", "p_buku_usaha_txn_meta",
                    ["household_id", "kontak_id"], if_not_exists=True)

    op.create_table(
        "p_buku_usaha_alokasi",
        *_wajib(),
        sa.Column("envelope_id", sa.Uuid(), nullable=False),
        sa.Column("persen", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["envelope_id"], ["envelopes.id"], ondelete="CASCADE"),
        *_fk_wajib(),
        if_not_exists=True,
    )
    op.create_index("uq_p_buku_usaha_alokasi_envelope", "p_buku_usaha_alokasi", ["household_id", "envelope_id"],
                    unique=True, if_not_exists=True, **_hidup())


def downgrade() -> None:
    for tabel, indeks in (
        ("p_buku_usaha_alokasi", ["uq_p_buku_usaha_alokasi_envelope"]),
        ("p_buku_usaha_txn_meta", ["ix_p_buku_usaha_txn_meta_household_kontak", "uq_p_buku_usaha_txn_meta_transaction"]),
        ("p_buku_usaha_income_meta", ["ix_p_buku_usaha_income_meta_household_kontak",
                                      "uq_p_buku_usaha_income_meta_income"]),
        ("p_buku_usaha_kontak", ["ix_p_buku_usaha_kontak_household_peran_nama"]),
    ):
        for ix in indeks:
            op.drop_index(ix, table_name=tabel, if_exists=True)
        op.drop_table(tabel, if_exists=True)
