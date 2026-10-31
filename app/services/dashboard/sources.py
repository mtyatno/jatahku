"""Sumber data kartu inti: endpoint yang dipanggil Beranda sekarang, dimuat sekali per permintaan.

Satu sumber angka (AGENTS.md "Plugin dan ruang" aturan 6): penyedia kartu inti tidak menghitung
apa pun. Setiap sumber memanggil handler endpoint lama yang sama dengan yang dipanggil
`Dashboard.jsx` (yang di dalamnya memakai `envelope_balance.py`, `advisor/snapshot.py`,
`advisor/metrics.py`, `recurring_status.py`), lalu menserialisasi hasilnya persis seperti FastAPI.
Jadi angka di `POST /dashboard/data` identik dengan endpoint lama, dan dikunci tes paritas.

Satu snapshot per permintaan: `Sumber` menyimpan hasil per nama, sehingga enam kartu KPI berbagi
satu muatan AI Advisor dan satu ringkasan amplop. Handler diimpor tertunda supaya modul ini tidak
membuat impor melingkar dengan `app.api.routes`. Memindahkan rumus dari route ke services adalah
refactor terpisah, bukan bagian B1.

Ruang: handler lama menentukan household dari keanggotaan user di server (R2 menggantinya dengan
`ruang_aktif`). Tidak ada parameter ruang dari klien yang diteruskan ke sini.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute
from pydantic import TypeAdapter

logger = logging.getLogger("jatahku.dashboard")


class SumberGagal(Exception):
    """Sumber data tidak bisa dimuat; kartu yang memakainya mendapat `error`."""


def _serialisasi(router, handler, hasil) -> Any:
    """Bentuk JSON yang sama dengan respons FastAPI untuk handler ini (response_model bila ada)."""
    model = next((r.response_model for r in router.routes
                  if isinstance(r, APIRoute) and r.endpoint is handler), None)
    if model is not None:
        adapter = TypeAdapter(model)
        return adapter.dump_python(adapter.validate_python(hasil, from_attributes=True), mode="json")
    return jsonable_encoder(hasil)


@dataclass
class Periode:
    """Periode anggaran yang diminta. `berjalan` = periode sekarang (klien mengirim `periode: null`)."""
    start: date
    end: date
    berjalan: bool

    @property
    def ps(self) -> date | None:
        # Dashboard.jsx mengirim null untuk periode berjalan supaya backend memakai default-nya sendiri.
        return None if self.berjalan else self.start

    @property
    def pe(self) -> date | None:
        return None if self.berjalan else self.end


@dataclass
class Sumber:
    user: Any
    db: Any
    periode: Periode
    _cache: dict = field(default_factory=dict)

    async def _muat(self, nama: str, router, handler, **kwargs) -> Any:
        if nama in self._cache:
            hasil = self._cache[nama]
        else:
            try:
                hasil = _serialisasi(router, handler, await handler(user=self.user, db=self.db, **kwargs))
            except HTTPException as exc:
                logger.warning("dashboard sumber %s gagal: %s %s", nama, exc.status_code, exc.detail)
                hasil = SumberGagal(nama)
            except Exception:
                logger.exception("dashboard sumber %s gagal", nama)
                hasil = SumberGagal(nama)
            self._cache[nama] = hasil
        if isinstance(hasil, SumberGagal):
            raise hasil
        return hasil

    # ── sumber yang ikut periode terpilih ──────────────────────────────
    async def ringkasan_amplop(self) -> list:
        from app.api.routes import envelopes as r
        return await self._muat("ringkasan_amplop", r.router, r.envelope_summary,
                                period_start=self.periode.ps, period_end=self.periode.pe)

    async def harian(self) -> list:
        from app.api.routes import analytics as r
        return await self._muat("harian", r.router, r.daily_spending,
                                period_start=self.periode.ps, period_end=self.periode.pe)

    async def rincian(self) -> list:
        from app.api.routes import analytics as r
        return await self._muat("rincian", r.router, r.envelope_breakdown,
                                period_start=self.periode.ps, period_end=self.periode.pe)

    async def transaksi(self, limit: int) -> list:
        from app.api.routes import transactions as r
        # Dashboard.jsx mengirim rentang periode lengkap (juga untuk periode berjalan).
        return await self._muat(f"transaksi:{limit}", r.router, r.list_transactions,
                                envelope_id=None, start_date=self.periode.start,
                                end_date=self.periode.end, limit=limit, offset=0)

    # ── sumber periode berjalan saja (Dashboard.jsx tidak memuatnya untuk periode lalu) ──
    async def prediksi(self) -> dict | None:
        if not self.periode.berjalan:
            return None
        from app.api.routes import analytics as r
        return await self._muat("prediksi", r.router, r.spending_prediction, period_start=None, period_end=None)

    async def tagihan(self) -> dict | None:
        if not self.periode.berjalan:
            return None
        from app.api.routes import recurring as r
        return await self._muat("tagihan", r.router, r.recurring_period_summary)

    async def advisor(self) -> dict | None:
        if not self.periode.berjalan:
            return None
        from app.api.routes import advisor as r
        return await self._muat("advisor", r.router, r.advisor_dashboard)

    async def insights(self) -> dict | None:
        if not self.periode.berjalan:
            return None
        from app.api.routes import advisor as r
        return await self._muat("insights", r.router, r.advisor_insights)

    async def pemasukan(self) -> list | None:
        if not self.periode.berjalan:
            return None
        from app.api.routes import incomes as r
        return await self._muat("pemasukan", r.router, r.list_incomes, period_start=None, period_end=None)

    # ── sumber tanpa periode ───────────────────────────────────────────
    async def target(self) -> list:
        from app.api.routes import goals as r
        return await self._muat("target", r.router, r.list_goals)

    async def langganan(self) -> list:
        from app.api.routes import recurring as r
        return await self._muat("langganan", r.router, r.list_recurring)

    async def saldo_cek(self) -> dict:
        from app.api.routes import balance_check as r
        return await self._muat("saldo_cek", r.router, r.balance_check_status)

    async def papan(self) -> list:
        from app.api.routes import household as r
        return await self._muat("papan", r.router, r.streak_leaderboard)


async def daftar_periode(user, jumlah: int = 24) -> list[dict]:
    """Periode yang boleh diminta: sama dengan `GET /analytics/periods` (pemilih periode Beranda)."""
    from app.api.routes import analytics as r
    return await r.available_periods(count=jumlah, user=user)
