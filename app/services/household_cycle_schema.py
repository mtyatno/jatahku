"""DDL aditif siklus anggaran household (spec 2026-10-31-siklus-household, bagian 1).

`create_all` membuat tabel baru tapi tidak pernah mengubah tabel yang sudah ada, dan deploy
tidak menjalankan alembic. Daftar ini dijalankan di `lifespan` (app/main.py) dan oleh revisi
alembic siklus-household. Semua statement idempoten: `ADD COLUMN IF NOT EXISTS`, dan backfill
hanya menyentuh household yang payday_day-nya masih NULL.

NULL pada `households.payday_day` berarti "belum dimigrasi" (diturunkan dari owner saat
pertama dibaca), jadi kolomnya sengaja tanpa DEFAULT. NULL pada
`monthly_snapshots.allocated_amount` dan `spent_amount` berarti snapshot lama yang belum
dihitung ulang.

Modul ini tidak mengimpor apa pun supaya revisi alembic bisa memuatnya tanpa menarik aplikasi.
SQL di bawah satu-satunya yang mengisi payday_day; atribut payday_day (user dan household)
hanya di-assign di app/services/household_cycle.py.
"""

HOUSEHOLD_CYCLE_DDL: list[str] = [
    "ALTER TABLE households ADD COLUMN IF NOT EXISTS payday_day INTEGER",
    "ALTER TABLE monthly_snapshots ADD COLUMN IF NOT EXISTS allocated_amount NUMERIC(15,2)",
    "ALTER TABLE monthly_snapshots ADD COLUMN IF NOT EXISTS spent_amount NUMERIC(15,2)",
    # Backfill: payday household = payday anggota yang paling berhak (owner, lalu admin, lalu
    # member; sesama peran yang paling lama bergabung), urutan yang sama dengan pick_payday di
    # app/services/household_cycle.py. Household tanpa anggota tetap NULL. Label enum
    # householdrole di DB: 'owner' | 'admin' | 'member'.
    (
        "UPDATE households h SET payday_day = sub.payday_day "
        "FROM (SELECT DISTINCT ON (hm.household_id) hm.household_id, u.payday_day "
        "FROM household_members hm JOIN users u ON u.id = hm.user_id "
        "ORDER BY hm.household_id, "
        "CASE hm.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, hm.created_at) sub "
        "WHERE h.id = sub.household_id AND h.payday_day IS NULL"
    ),
]
