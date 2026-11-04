"""DDL aditif laporan berkala (spec 2026-11-01-laporan-berkala-design, bagian 2b dan 9).

`create_all` membuat tabel baru (`reports`, `report_settings`) tapi tidak pernah mengubah tabel
yang sudah ada, dan deploy tidak menjalankan alembic. Daftar ini dijalankan di `lifespan`
(app/main.py) dan oleh revisi alembic laporan-berkala, supaya model `User` yang memetakan
`email_verified_at` tidak membuat API 500 sebelum migrasi jalan. Semua statement idempoten.

NULL pada `users.email_verified_at` berarti email belum (atau tidak lagi) terverifikasi, jadi
kolomnya sengaja tanpa DEFAULT dan akun lama tidak pernah dianggap terverifikasi.

Modul ini tidak mengimpor apa pun supaya revisi alembic bisa memuatnya tanpa menarik aplikasi.
"""

LAPORAN_DDL: list[str] = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP WITH TIME ZONE",
]
