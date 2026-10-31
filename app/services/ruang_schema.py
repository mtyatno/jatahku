"""DDL aditif Plugin R1 (model ruang) untuk PostgreSQL.

`create_all` tidak pernah mengubah tabel yang sudah ada dan deploy tidak menjalankan
alembic, jadi `RUANG_DDL` dijalankan di `lifespan` (app/main.py) supaya model yang
memetakan kolom baru tidak membuat API 500 sebelum migrasi jalan. Migrasi alembic
1c7e5a9d3b20 menjalankan daftar yang sama, lalu `KIND_BACKFILL` dan constraint unik
keanggotaan. Semua statement idempoten.

`KIND_BACKFILL` hanya dijalankan migrasi (sekali), bukan tiap start: aturan teksnya
("Top-up …") menebak, dan pemasukan baru sudah ditulis dengan kind yang benar oleh
jalurnya masing-masing. Hanya baris yang masih `pemasukan` yang disentuh, sehingga
kind yang ditulis kode baru tidak pernah ditimpa. Urutan: penyesuaian, transfer,
top-up.
"""

RUANG_DDL: list[str] = [
    "ALTER TABLE households ADD COLUMN IF NOT EXISTS type VARCHAR(20) NOT NULL "
    "DEFAULT 'rumah_tangga'",
    "ALTER TABLE incomes ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL "
    "DEFAULT 'pemasukan'",
]

KIND_BACKFILL: list[str] = [
    # Cocokkan saldo (balance_check.py) selalu mengisi balance_check_id.
    "UPDATE incomes SET kind = 'penyesuaian' "
    "WHERE kind = 'pemasukan' AND balance_check_id IS NOT NULL",
    # Transfer antar-amplop dan refund/tutup minus saat hapus amplop: Income bernilai 0.
    "UPDATE incomes SET kind = 'transfer' WHERE kind = 'pemasukan' AND amount = 0",
    # Top-up dari bot (fund_shift.record_topup) dan bawaan modal web: "Top-up <amplop>";
    # form amplop baru: "Top-up".
    "UPDATE incomes SET kind = 'top-up' "
    "WHERE kind = 'pemasukan' AND (description = 'Top-up' OR description LIKE 'Top-up %')",
]
