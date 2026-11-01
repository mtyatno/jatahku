"""Plugin H1: host plugin — tabel plugin_installations, entitlements, plugin_audit_log

- `plugin_installations`: status plugin per ruang (installed, active, paused, uninstalled + `purge_after`
  untuk arsip 90 hari, ADR-P15). Keunikan per ruang lewat indeks parsial (`owner_id IS NULL`), karena
  UNIQUE biasa menganggap NULL selalu berbeda.
- `entitlements`: hak SKU per user atau per ruang (ADR-P12). Belum ada baris dan belum ada yang ditolak
  selama beta (ADR-P13).
- `plugin_audit_log`: jejak pasang, pulihkan, lanjut, jeda, copot, bersihkan.

Idempoten: startup app (main.py lifespan) juga menjalankan create_all, jadi migrasi ini aman dijalankan
sebelum ATAU sesudah deploy. Tidak ada tabel lama yang berubah. Bentuk API: docs/plugin/04-kontrak-api.md §5.

Revision ID: a7e3c1f5d9b2
Revises: 2d51b9031a6b
Create Date: 2026-11-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a7e3c1f5d9b2'
down_revision: Union[str, None] = '2d51b9031a6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "plugin_installations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("plugin_id", sa.String(length=40), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("installed_by", sa.Uuid(), nullable=True),
        sa.Column("granted_permissions", _JSON, nullable=False),
        sa.Column("settings", _JSON, nullable=False),
        sa.Column("data_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("disabled_reason", sa.String(length=40), nullable=True),
        sa.Column("uninstalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["installed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index("uq_plugin_installation_ruang", "plugin_installations", ["household_id", "plugin_id"],
                    unique=True, postgresql_where=sa.text("owner_id IS NULL"), if_not_exists=True)
    op.create_index("uq_plugin_installation_pribadi", "plugin_installations",
                    ["household_id", "plugin_id", "owner_id"], unique=True,
                    postgresql_where=sa.text("owner_id IS NOT NULL"), if_not_exists=True)
    op.create_index("ix_plugin_installations_household_status", "plugin_installations",
                    ["household_id", "status"], if_not_exists=True)

    op.create_table(
        "entitlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("household_id", sa.Uuid(), nullable=True),
        sa.Column("sku", sa.String(length=60), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="aktif", nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_ref", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("user_id IS NOT NULL OR household_id IS NOT NULL", name="ck_entitlement_pemilik"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_ref", name="uq_entitlement_sumber_rujukan"),
        if_not_exists=True,
    )
    op.create_index("ix_entitlements_household_sku", "entitlements", ["household_id", "sku"], if_not_exists=True)
    op.create_index("ix_entitlements_user_sku", "entitlements", ["user_id", "sku"], if_not_exists=True)

    op.create_table(
        "plugin_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("plugin_id", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("detail", _JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index("ix_plugin_audit_log_household_created", "plugin_audit_log", ["household_id", "created_at"],
                    if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_plugin_audit_log_household_created", table_name="plugin_audit_log", if_exists=True)
    op.drop_table("plugin_audit_log", if_exists=True)
    op.drop_index("ix_entitlements_user_sku", table_name="entitlements", if_exists=True)
    op.drop_index("ix_entitlements_household_sku", table_name="entitlements", if_exists=True)
    op.drop_table("entitlements", if_exists=True)
    op.drop_index("ix_plugin_installations_household_status", table_name="plugin_installations", if_exists=True)
    op.drop_index("uq_plugin_installation_pribadi", table_name="plugin_installations", if_exists=True)
    op.drop_index("uq_plugin_installation_ruang", table_name="plugin_installations", if_exists=True)
    op.drop_table("plugin_installations", if_exists=True)
