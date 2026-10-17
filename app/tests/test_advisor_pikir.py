"""AI Advisor v2 S19 — aturan Pikir-Pikir PP-01..03 (02-aturan.md §6I).

Fungsi murni dengan fixture `SnapshotBuilder` (tanpa DB). Data refleksi/Incaran belum ada di
Snapshot (menunggu Pikir-Pikir Fase 2/3), jadi fixture memasang `snap.refleksi` / `snap.incaran`
langsung dengan bentuk `rules.pikir.RefleksiSnap` / `IncaranSnap`.
Run: python -m unittest app.tests.test_advisor_pikir -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import dataclasses
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from app.services.advisor import render
from app.services.advisor.dashboard import EVALUATOR, analisa
from app.services.advisor.insight import DEFAULT as KA, Konteks
from app.services.advisor.metrics import compute_metrics
from app.services.advisor.rules import pikir
from app.services.advisor.rules.pikir import IncaranSnap, RefleksiSnap
from app.services.advisor.select import pilih
from app.services.advisor.signals import compute_signals
from app.tests.advisor_v2_fixtures import SnapshotBuilder

JKT = ZoneInfo("Asia/Jakarta")
TODAY = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)  # 12.00 WIB


def builder() -> SnapshotBuilder:
    b = SnapshotBuilder(TODAY, payday_day=1)
    b.envelope("makan", "Makan", classification="needs")
    b.envelope("hobi", "Hobi", classification="wants")
    b.fund("makan", 3_000_000, on=b.ps)
    b.fund("hobi", 1_000_000, on=b.ps)
    b.txn("makan", 50_000, on=TODAY, desc="makan siang")
    return b


def snap_dengan(refleksi=(), incaran=(), now=NOW):
    snap = builder().build()
    snap.refleksi = list(refleksi)
    snap.incaran = list(incaran)
    snap.now = now
    return snap


def konteks(snap, ka=KA) -> Konteks:
    m = compute_metrics(snap)
    return Konteks(snap=snap, m=m, s=compute_signals(snap, m), jam=12, k=ka)


def refleksi(id, jumlah=150_000, tempo=TODAY, jawaban=None, env="hobi", tanggal=None, desc="sepatu"):
    return RefleksiSnap(id=id, txn_id=f"t-{id}", envelope_id=env, deskripsi=desc, jumlah=D(jumlah),
                        tanggal_txn=tanggal or (tempo - timedelta(days=7)), jatuh_tempo=tempo, jawaban=jawaban)


def incaran(id, nama="headphone", jumlah=850_000, sampai=NOW - timedelta(hours=1), status="menunggu", env="hobi"):
    return IncaranSnap(id=id, nama=nama, jumlah=D(jumlah), envelope_id=env, think_until=sampai, status=status)


class TanpaData(unittest.TestCase):
    def test_snapshot_hari_ini_tanpa_field_pikir_diam(self):
        """Snapshot belum punya `refleksi`/`incaran` (Pikir-Pikir Fase 2/3 belum ada) → tidak ada PP."""
        snap = builder().build()
        self.assertFalse(hasattr(snap, "refleksi"))
        self.assertEqual(pikir.evaluasi(konteks(snap)), [])

    def test_belum_terdaftar_di_dashboard(self):
        """Sampai loader Pikir-Pikir ada, PP-* tidak ikut dashboard walau datanya terpasang."""
        self.assertNotIn(pikir.evaluasi, EVALUATOR)
        snap = snap_dengan([refleksi("r1")], [incaran("i1")])
        _, sel = analisa(snap, now_local=NOW.astimezone(JKT))
        self.assertFalse([i for i in sel.semua if i.domain == "PP"])


class PP01(unittest.TestCase):
    def test_jatuh_tempo_belum_dijawab_satu_insight(self):
        xs = pikir.pp_01(konteks(snap_dengan([
            refleksi("r2", tempo=TODAY - timedelta(days=1), desc="kaos"),
            refleksi("r1", tempo=TODAY - timedelta(days=3), desc="sepatu", jumlah=400_000),
            refleksi("r3", tempo=TODAY + timedelta(days=1)),            # belum jatuh tempo
            refleksi("r4", tempo=TODAY - timedelta(days=5), jawaban="sepadan"),  # sudah dijawab
        ])))
        self.assertEqual(len(xs), 1)
        ins = xs[0]
        self.assertEqual((ins.id, ins.tone, ins.slot), ("PP-01:r1", "info", ("daftar",)))
        self.assertEqual(ins.data["n"], 2)
        self.assertEqual(ins.rupiah, D("550000"))
        self.assertEqual(ins.aksi, [{"kind": "pikir", "kode": "jawab_refleksi", "payload": {"refleksi_id": "r1"}}])

    def test_tidak_ada_yang_jatuh_tempo(self):
        self.assertEqual(pikir.pp_01(konteks(snap_dengan([refleksi("r1", tempo=TODAY + timedelta(days=2))]))), [])

    def test_render(self):
        ctx = konteks(snap_dengan([refleksi("r1", tempo=TODAY - timedelta(days=1)),
                                   refleksi("r2", tempo=TODAY)]))
        out = render.render_insight(pikir.pp_01(ctx)[0], ctx)
        self.assertEqual(out["chip"], "Sepadan?")
        self.assertEqual(out["judul"], "Sepadan? sepatu Rp150 rb (+1 lainnya)")
        self.assertIn("di Hobi pada 7 Okt", out["isi"])
        self.assertEqual(out["aksi"], [{"kind": "pikir", "label": "Jawab", "payload": {"refleksi_id": "r1"}}])


class PP02(unittest.TestCase):
    def test_lewat_think_until(self):
        xs = pikir.pp_02(konteks(snap_dengan(incaran=[
            incaran("i1"),
            incaran("i2", sampai=NOW + timedelta(hours=2)),     # masih dipikir
            incaran("i3", status="batal"),
            incaran("i4", sampai=NOW),                          # tepat now → siap
        ])))
        self.assertEqual([i.id for i in xs], ["PP-02:i1", "PP-02:i4"])
        ins = xs[0]
        self.assertEqual([a["kode"] for a in ins.aksi], ["beli_incaran", "nggak_jadi", "tunda_incaran"])
        self.assertEqual(ins.aksi[0]["kind"], "expense")
        self.assertEqual(ins.aksi[0]["payload"]["jumlah"], D("850000"))
        self.assertEqual((ins.rupiah, ins.amplop_id), (D("850000"), "hobi"))

    def test_tanpa_waktu_muat_diam(self):
        self.assertEqual(pikir.pp_02(konteks(snap_dengan(incaran=[incaran("i1")], now=None))), [])

    def test_render(self):
        ctx = konteks(snap_dengan(incaran=[incaran("i1")]))
        out = render.render_insight(pikir.pp_02(ctx)[0], ctx)
        self.assertEqual(out["judul"], "Waktunya memutuskan headphone")
        self.assertIn("Rp850.000", out["isi"])
        self.assertIn("beli dari Hobi", out["isi"])
        self.assertEqual([a["label"] for a in out["aksi"]], ["Beli → catat", "Nggak jadi", "Tunda"])


class PP03(unittest.TestCase):
    def _menyesal(self, n, env="hobi", tanggal=TODAY - timedelta(days=2)):
        return [refleksi(f"{env}{i}", jawaban="menyesal", env=env, tanggal=tanggal) for i in range(n)]

    def test_tiga_menyesal_di_amplop_sama(self):
        xs = pikir.pp_03(konteks(snap_dengan([*self._menyesal(3), *self._menyesal(2, env="makan"),
                                              refleksi("ok", jawaban="sepadan")])))
        self.assertEqual([i.id for i in xs], ["PP-03:hobi"])
        self.assertEqual(xs[0].data["n"], 3)
        self.assertEqual(xs[0].data["total"], D("450000"))
        self.assertEqual(xs[0].slot, ("daftar", "amplop"))

    def test_periode_sebelumnya_ikut_yang_lebih_lama_tidak(self):
        snap = snap_dengan()
        prev_start = snap.periods[-2][0]
        snap.refleksi = [*self._menyesal(2, tanggal=prev_start),
                         refleksi("lama", jawaban="menyesal", tanggal=prev_start - timedelta(days=1))]
        self.assertEqual(pikir.pp_03(konteks(snap)), [])
        snap.refleksi.append(refleksi("baru", jawaban="menyesal", tanggal=TODAY))
        self.assertEqual(len(pikir.pp_03(konteks(snap))), 1)

    def test_konstanta_bisa_ditimpa(self):
        ka = dataclasses.replace(KA, pola_menyesal_n=2)
        self.assertEqual(len(pikir.pp_03(konteks(snap_dengan(self._menyesal(2, env="makan")), ka=ka))), 1)

    def test_render(self):
        ctx = konteks(snap_dengan(self._menyesal(3)))
        out = render.render_insight(pikir.pp_03(ctx)[0], ctx)
        self.assertEqual(out["judul"], "3 belanja Hobi terasa menyesal")
        self.assertEqual(out["aksi"][0]["label"], "Pakai Incaran untuk Hobi")


class Seleksi(unittest.TestCase):
    def test_masuk_daftar_lewat_pilih(self):
        """Bila didaftarkan, PP-* lolos seleksi biasa (skor, batas 2 per domain) dan bisa di-dismiss."""
        snap = snap_dengan([refleksi("r1"), *[refleksi(f"m{i}", jawaban="menyesal",
                                                        tanggal=TODAY - timedelta(days=1)) for i in range(3)]],
                           [incaran("i1")])
        ctx = konteks(snap)
        semua = [ins for ev in (*EVALUATOR, pikir.evaluasi) for ins in ev(ctx)]
        sel = pilih(ctx, semua, {})
        pp = [i for i in sel.daftar + sel.sisa if i.domain == "PP"]
        self.assertEqual({i.aturan for i in pp}, {"PP-01", "PP-02", "PP-03"})
        self.assertLessEqual(sum(1 for i in sel.daftar if i.domain == "PP"), KA.daftar_per_domain)
        self.assertTrue(all(i.skor > 0 for i in pp))
        sel2 = pilih(konteks(snap), [ins for ev in (*EVALUATOR, pikir.evaluasi) for ins in ev(konteks(snap))],
                     {"PP-02:i1": {"pilihan": "nanti", "tone": "info", "rupiah": "850000"}})
        self.assertNotIn("PP-02:i1", [i.id for i in sel2.daftar + sel2.sisa])


if __name__ == "__main__":
    unittest.main()
