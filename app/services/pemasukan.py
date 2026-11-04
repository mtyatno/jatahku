"""Definisi pemasukan seorang user: satu sumber untuk analitik (`analytics._income_totals`) dan laporan berkala
(`laporan/muat.py`), supaya angka pemasukan di halaman Alokasi dan di laporan tidak bisa menyimpang (spec
2026-11-01-laporan-berkala-design, bagian 2d)."""
from datetime import date

from app.models.models import Income


def filter_pemasukan_user(household_id, user_id, period_start: date, period_end: date) -> list:
    """Kondisi WHERE pemasukan household `household_id` yang dicatat `user_id` dengan `income_date` di jendela
    (kedua ujung ikut), tanpa penyesuaian cocokkan saldo (`balance_check_id` terisi).

    Transfer antar-amplop (nominal 0) sengaja TIDAK disaring di sini: analitik menghitungnya sebagai
    `transfer_count`. Pemakai yang hanya mau pemasukan nyata menambah `Income.amount > 0`."""
    return [
        Income.household_id == household_id,
        Income.user_id == user_id,
        Income.income_date >= period_start,
        Income.income_date <= period_end,
        Income.balance_check_id.is_(None),
    ]
