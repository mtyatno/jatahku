"""DDL aditif Kotak Struk untuk tabel `receipt_scans` (Postgres).

`create_all` membuat tabel baru (`household_merchants`, `merchant_envelope_map`)
tapi tidak pernah mengubah tabel yang sudah ada, dan deploy tidak menjalankan
alembic. Daftar ini dijalankan di `lifespan` (app/main.py) dan oleh migrasi
alembic a7c4e2b9d1f3 dan e7b3d5a9c1f4 (kolom `layout`). Semua statement idempoten; nama indeks sama dengan
konvensi SQLAlchemy (`ix_<tabel>_<kolom>`) supaya basis data baru dari
`create_all` tidak mendapat indeks ganda.
"""

_T = "receipt_scans"

# (kolom, tipe Postgres) — urutan sama dengan model ReceiptScan.
_COLUMNS: list[tuple[str, str]] = [
    ("source", "VARCHAR(20)"),
    ("status", "VARCHAR(16)"),
    ("doc_type", "VARCHAR(30)"),
    ("household_id", "UUID"),
    ("upload_id", "VARCHAR(64)"),
    ("file_sha256", "VARCHAR(64)"),
    ("content_type", "VARCHAR(60)"),
    ("pages", "INTEGER"),
    ("file_path", "VARCHAR(255)"),
    ("ref_hash", "VARCHAR(64)"),
    ("counterparty_key", "VARCHAR(80)"),
    ("paid_at", "TIMESTAMP WITH TIME ZONE"),
    ("document", "JSONB"),
    ("parser", "VARCHAR(40)"),
    ("attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("error", "VARCHAR(200)"),
    ("channel_meta", "JSONB"),
    ("processed_at", "TIMESTAMP WITH TIME ZONE"),
    ("expires_at", "TIMESTAMP WITH TIME ZONE"),
    ("transaction_ids", "JSONB"),
    # Kerangka tata letak bukti (belajar lintas user, migrasi e7b3d5a9c1f4): tanpa nama/nomor, dihapus 24 jam.
    ("layout", "JSONB"),
]

_INDEXED = ("status", "household_id", "file_sha256", "ref_hash", "counterparty_key")

KOTAK_DDL: list[str] = (
    [f"ALTER TABLE {_T} ADD COLUMN IF NOT EXISTS {col} {typ}" for col, typ in _COLUMNS]
    + [f"CREATE INDEX IF NOT EXISTS ix_{_T}_{col} ON {_T} ({col})" for col in _INDEXED]
    + [
        # Satu unggahan (upload_id dari klien) hanya satu item per user.
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{_T}_upload ON {_T} (user_id, upload_id) "
        "WHERE upload_id IS NOT NULL",
    ]
)
