"""AI Advisor v2 S14 — halaman Alokasi (02-aturan.md §7 "Alokasi", §6E).

Rekomendasi tetap dari `allocation.py`; aturan AMP-01/04/05/06, TAG-04, TAB-02 menggeser
minimum/target amplopnya dan memberi alasan (render.alasan_alokasi); INC-04/INC-03 jadi
banner di atas form. Fixture `SnapshotBuilder` tanpa DB.
Run: python -m unittest app.tests.test_advisor_alokasi_v2 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.advisor import allocation, render
from app.services.advisor.allocation import (
    allocate_income_to_targets, banner_alokasi, build_allocation_recommendation, sesuaikan_dengan_aturan, sisa_ke,
)
from app.services.advisor.insight import Insight
from app.tests.test_advisor_aturan_s4 import TODAY, normal, periode_lalu, run, satu


def _input(id, minimum=0, target=0, priority=40, purpose="expense"):
    return {"id": id, "name": id, "minimum": D(minimum), "target": D(target), "priority": priority,
            "purpose": purpose, "is_locked": False}


def _ins(aturan, eid, **data):
    return Insight(aturan=aturan, entitas=eid, tone="info", slot=("alokasi",), data={"amplop_id": eid, **data},
                   amplop_id=eid)


class TestSesuaikanDenganAturan(unittest.TestCase):
    def test_amp01_minus_jadi_minimum(self):
        items = [_input("makan", minimum=100_000, target=500_000)]
        alasan = sesuaikan_dengan_aturan(items, [_ins("AMP-01", "makan", minus=D("250000.4"))])
        self.assertEqual(items[0]["minimum"], D("250000"))
        self.assertEqual(items[0]["priority"], 10)   # jadi kewajiban, diisi sebelum target lain
        self.assertEqual([i.aturan for i in alasan["makan"]], ["AMP-01"])

    def test_amp05_menaikkan_target_amp06_menurunkan(self):
        items = [_input("makan", target=3_000_000), _input("hiburan", minimum=200_000, target=1_000_000)]
        sesuaikan_dengan_aturan(items, [_ins("AMP-05", "makan", saran=D("4000000")),
                                        _ins("AMP-06", "hiburan", saran=D("150000"))])
        self.assertEqual(items[0]["target"], D("4000000"))
        self.assertEqual(items[1]["target"], D("200000"))  # tidak di bawah minimum

    def test_tag04_sisihan_dan_tab02_ditunda(self):
        items = [_input("tagihan"), _input("liburan", priority=90, purpose="saving")]
        sesuaikan_dengan_aturan(items, [_ins("TAG-04", "tagihan", per_bulan=D("400000")),
                                        _ins("TAB-02", "liburan", kurang=D("900000"), tunda=True)])
        self.assertEqual(items[0]["minimum"], D("400000"))
        self.assertEqual(items[1]["minimum"], D("0"))      # penekanan 7: tidak didorong saat defisit

    def test_amplop_tak_dikenal_diabaikan(self):
        items = [_input("makan")]
        self.assertEqual(sesuaikan_dengan_aturan(items, [_ins("AMP-01", "lain", minus=D("1"))]), {})


class TestMinimumProporsional(unittest.TestCase):
    def test_income_kecil_dibagi_proporsional_dalam_satu_prioritas(self):
        items = [_input("makan", minimum=600_000, priority=10), _input("transport", minimum=300_000, priority=10),
                 _input("tab", priority=90, purpose="saving")]
        out = allocate_income_to_targets(D("90050"), items)
        by = {i["id"]: i["recommended_amount"] for i in out["items"]}
        self.assertEqual(by["transport"], D("30000"))
        self.assertEqual(by["makan"], D("60050"))           # sisa pembulatan ke minimum terbesar
        self.assertEqual(by["tab"], D("0"))
        self.assertEqual(out["total_recommended"], D("90050"))
        self.assertTrue(out["warnings"])

    def test_prioritas_lebih_tinggi_dipenuhi_dulu(self):
        items = [_input("tagihan", minimum=500_000, priority=10), _input("tab", minimum=400_000, priority=90,
                                                                         purpose="saving")]
        out = allocate_income_to_targets(D("700000"), items)
        by = {i["id"]: i["recommended_amount"] for i in out["items"]}
        self.assertEqual((by["tagihan"], by["tab"]), (D("500000"), D("200000")))


class TestAlasanRender(unittest.TestCase):
    def test_amp06_dan_tag04(self):
        b = TestAlokasiFixture._riwayat(1_000_000, 3_000_000)
        b.envelope("tab", "Tabungan", purpose="saving")
        ctx, sel = run(b)
        self.assertEqual(render.alasan_alokasi(satu(sel, "AMP-06"), ctx),
                         "3 periode terakhir hanya terpakai 33% dari jatah; cukup Rp1.100.000.")

    def test_tab02_teks(self):
        ins = _ins("TAB-02", "liburan", nama="Liburan", butuh=D("3000000"), tenggat=date(2026, 12, 31), tunda=False)
        self.assertEqual(render.alasan_alokasi(ins, None),
                         "Mengejar target Liburan: perlu Rp3.000.000/bulan sampai 31 Des.")


class TestAlokasiFixture(unittest.TestCase):
    @staticmethod
    def _riwayat(terpakai_lalu, budget):
        b = normal()
        b.snap.envelopes[0].budget_amount = D(budget)
        for ps, _ in periode_lalu(b):
            b.fund("makan", budget, on=ps)
            b.txn("makan", terpakai_lalu, on=ps + timedelta(days=5), desc="belanja bulanan")
        return b

    def _rekomendasi(self, b, income):
        """build_allocation_recommendation dengan konteks v1 tiruan (amplop sama) + analisa v2 fixture."""
        hasil = run(b)
        envs = [SimpleNamespace(id=e.id, name=e.name, emoji=e.emoji, purpose=e.purpose,
                                budget_amount=e.budget_amount, is_locked=e.is_locked) for e in b.snap.envelopes]
        stats = {e.id: [{"allocated": D(0), "spent": D(0), "reserved": D(0), "rollover": D(0)}] for e in envs}
        with patch.object(allocation, "load_advisor_context", new=AsyncMock(return_value={"envelopes": envs,
                                                                                          "stats": stats})), \
             patch.object(allocation, "analisa_alokasi", new=AsyncMock(return_value=hasil)):
            return asyncio.run(build_allocation_recommendation(SimpleNamespace(id="u1"), D(income), db=None, household_id="h1"))

    def test_amp05_menaikkan_rekomendasi_dengan_alasan(self):
        out = self._rekomendasi(self._riwayat(4_000_000, 3_000_000), 5_000_000)
        makan = next(i for i in out["items"] if i["envelope_id"] == "makan")
        self.assertEqual(makan["recommended_amount"], 4_000_000)
        self.assertEqual([a["aturan"] for a in makan["alasan"]], ["AMP-05"])
        self.assertIn("di atas jatah Rp3.000.000", makan["alasan"][0]["teks"])
        self.assertIn(makan["keyakinan"], ("high", "medium", "low"))

    def test_amp06_sisanya_ke_tabungan(self):
        b = self._riwayat(1_000_000, 3_000_000)
        b.envelope("tab", "Tabungan", purpose="saving")
        out = self._rekomendasi(b, 3_000_000)
        by = {i["envelope_id"]: i["recommended_amount"] for i in out["items"]}
        self.assertEqual(by["makan"], 1_100_000)
        self.assertEqual(by["tab"], 1_900_000)
        self.assertEqual(out["sisa_ke"], {"envelope_id": "tab", "name": "Tabungan"})

    def test_inc04_jadi_banner(self):
        b = normal()
        b.income(1_000_000, on=TODAY - timedelta(days=3), alloc={"makan": 400_000},
                 created_at=datetime(2026, 10, 12, 3, tzinfo=timezone.utc))
        ctx, sel = run(b)
        banner = banner_alokasi(ctx, sel)
        self.assertEqual([x["aturan"] for x in banner], ["INC-04"])
        self.assertEqual(banner[0]["judul"], "Bagi Rp600 rb ke amplop")
        sel.disembunyikan.append(banner[0]["id"])
        self.assertEqual(banner_alokasi(ctx, sel), [])

    def test_tanpa_v2_tetap_rekomendasi_lama(self):
        envs = [SimpleNamespace(id="makan", name="Makan", emoji="", purpose="expense",
                                budget_amount=D(1_000_000), is_locked=False)]
        with patch.object(allocation, "load_advisor_context", new=AsyncMock(return_value={
                "envelopes": envs, "stats": {"makan": []}})), \
             patch.object(allocation, "analisa_alokasi", new=AsyncMock(return_value=None)):
            out = asyncio.run(build_allocation_recommendation(SimpleNamespace(id="u1"), D(2_000_000), db=None, household_id="h1"))
        self.assertEqual(out["items"][0]["recommended_amount"], 1_000_000)
        self.assertEqual(out["items"][0]["alasan"], [])
        self.assertEqual(out["banner"], [])
        self.assertEqual(out["sisa_ke"], {"envelope_id": None, "name": "Tabungan"})


class TestSisaKe(unittest.TestCase):
    def test_hanya_nama_tabungan_seperti_incomes(self):
        envs = [SimpleNamespace(id="a", name="Dana Darurat"), SimpleNamespace(id="b", name="Tabungan")]
        self.assertEqual(sisa_ke(envs)["envelope_id"], "b")
        self.assertIsNone(sisa_ke(envs[:1])["envelope_id"])


if __name__ == "__main__":
    unittest.main()
