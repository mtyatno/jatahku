"""Plugin H2 — PluginContext dan titik ekstensi server (03-workflow.md baris H2; ADR-P2, P3, P9, P11, P14).

1. Kode plugin: impor terlarang (AST, sebelum kode dijalankan), pencocokan kode ↔ manifest dan izin, pemuatan.
2. Manifest 1.1: `checks`, `nlp_kamus`, jadwal job, domain aturan advisor.
3. Keluaran plugin diperiksa: bentuk kartu, saran advisor, tautan hanya ke `/p/<id>`.
4. PluginContext (DB): izin = disetujui ∩ manifest ∩ fungsi, audit penolakan, ruang dari host, kontrak visibilitas,
   karyawan ditolak data keuangan, job tanpa user fail-closed.
5. Titik: kartu (tata letak + batch + HTTP), cek (bot + web), advisor (batas per plugin, cache), perintah bot
   (audience, nama ruang, karyawan), notifikasi (jam tenang, batas harian, penerima), job, kamus, field form.
   Plugin dijeda / saklar darurat / di luar flag tidak meninggalkan apa pun.

Run: python -m unittest app.tests.test_plugin_sdk -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import copy
import dataclasses
import importlib.util
import json
import pathlib
import tempfile
import textwrap
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from app.plugins.host import kode as kode_mod
from app.plugins.host import titik
from app.plugins.host.manifest import DOMAIN_ADVISOR_INTI, Manifest
from app.plugins.host.registry import ManifestTidakSah, Registry, muat, pakai_registry
from app.plugins.sdk import AksiRoute, IzinDitolak, NilaiTidakSah, Plugin, Saran

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

IZIN = ["envelopes:read", "transactions:read", "incomes:read", "members:read", "notifications:send"]
MF = {
    "id": "contoh", "name": "Contoh", "version": "1.0.0", "publisher": "Jatahku", "description": "Plugin uji SDK",
    "engines": {"plugin_api": ">=1.1 <2.0"},
    "space_types": ["usaha"],
    "permissions": IZIN,
    "contributes": {
        "cards": [{"key": "contoh.kas", "title": "Kas", "shape": "kpi", "sizes": ["S", "M"]},
                  {"key": "contoh.rusak", "title": "Rusak", "shape": "list", "sizes": ["M"]}],
        "checks": ["anggaran"],
        "advisor_rules": ["CT-01"],
        "bot_commands": [{"command": "kas", "help": "Cek kas", "kind": "read", "audience": "admin"},
                         {"command": "halo", "help": "Halo", "kind": "read", "audience": "semua"}],
        "jobs": [{"key": "pagi", "schedule": "daily 08:00"}],
        "notifications": ["contoh.pengingat"],
        "form_fields": [{"target": "transaction", "key": "proyek", "type": "text", "label": "Proyek"}],
        "nlp_kamus": {"Bahan Baku": ["tepung", "gula pasir"]},
    },
}


def mf(**ubah) -> dict:
    d = copy.deepcopy(MF)
    for k, v in ubah.items():
        if k == "contributes":
            d["contributes"].update(v)
        else:
            d[k] = v
    return d


# ── plugin contoh (kode server) ─────────────────────────────────────────
PERILAKU: dict = {}
JEJAK: list = []
plugin = Plugin("contoh")


@plugin.kartu("contoh.kas", izin=["transactions:read"])
async def _kas(ctx, pengaturan, periode):
    if PERILAKU.get("kartu_float"):
        return {"value": 1.5, "unit": "rp"}
    if PERILAKU.get("simpan_ctx"):              # bug multi-tenant: konteks disimpan di variabel modul
        ctx = PERILAKU.setdefault("ctx", ctx)
    if PERILAKU.get("ubah_periode"):
        periode.start = date(2000, 1, 1)          # review ulang #186 no. 4: salinan beku, bukan Periode batch
    txn = await ctx.transactions(periode.start, periode.end)
    return {"value": sum((t.jumlah for t in txn), D("0")), "unit": "rp", "tone": "ok", "footer": f"{len(txn)} catatan"}


@plugin.kartu("contoh.rusak")                    # tanpa izin: membaca amplop ditolak
async def _rusak(ctx, pengaturan, periode):
    await ctx.envelopes()
    return {"items": []}


@plugin.cek("anggaran", izin=["envelopes:read"])
async def _anggaran(ctx, rencana):
    if PERILAKU.get("cek_gagal"):
        raise RuntimeError("bug plugin")
    amplop = {a.id: a for a in await ctx.envelopes()}
    a = amplop.get(rencana.amplop_id)
    return [f"Melewati anggaran {a.nama}"] if a and rencana.jumlah > a.anggaran else []


@plugin.aturan_advisor("CT-01", izin=["incomes:read"])
async def _ct01(ctx):
    await ctx.incomes(date(2000, 1, 1), date(2100, 1, 1))
    return [Saran(entitas="kas", tone="warn", judul="Kas menipis", isi="Cek kas hari ini.", chip="Kas",
                  fakta=(("Kas", "Rp50rb"),), aksi=(AksiRoute("Buka kas", "/p/contoh/kas"),),
                  rupiah=D("50000"), urgensi=D("0.8"))]


@plugin.perintah_bot("kas", izin=["transactions:read"])
async def _cmd_kas(ctx):
    if PERILAKU.get("bot_gagal"):
        raise RuntimeError("bug plugin")
    return f"{len(await ctx.transactions(date(2000, 1, 1), date(2100, 1, 1)))} catatan"


@plugin.perintah_bot("halo")
async def _cmd_halo(ctx):
    return f"halo {ctx.peran}"


@plugin.job("pagi", izin=["envelopes:read", "notifications:send"])
async def _pagi(ctx):
    JEJAK.append(("job", ctx.user_id, ctx.ruang_id, sorted(a.nama for a in await ctx.envelopes())))
    await ctx.notify("contoh.pengingat", "Cek kas", "Jangan lupa cek kas.", link="/p/contoh")


@plugin.field_form("transaction", "proyek")
async def _proyek(ctx, nilai):
    if nilai == "x":
        raise NilaiTidakSah("tidak boleh x")
    return nilai.strip()


def registry_contoh(**ubah) -> Registry:
    return Registry(plugins={"contoh": Manifest.model_validate(mf(**ubah))}, kode={"contoh": plugin})


# ── 1. kode plugin ───────────────────────────────────────────────────────
class KodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)

    def tulis(self, pid, data, kode: dict[str, str]):
        (self.dir / pid).mkdir()
        (self.dir / pid / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        for nama, isi in kode.items():
            berkas = self.dir / pid / nama
            berkas.parent.mkdir(parents=True, exist_ok=True)
            berkas.write_text(textwrap.dedent(isi), encoding="utf-8")

    def manifest_kecil(self, pid="kecil", **ubah):
        d = {"id": pid, "name": "Kecil", "version": "1.0.0", "publisher": "Jatahku", "description": "x",
             "engines": {"plugin_api": ">=1.1 <2.0"}, "space_types": ["usaha"],
             "permissions": ["incomes:read"],
             "contributes": {"cards": [{"key": f"{pid}.a", "title": "A", "shape": "kpi", "sizes": ["S"]}]}}
        d.update(ubah)
        return d

    KODE_SAH = """
        from app.plugins.sdk import Plugin
        from .bantu import nilai
        plugin = Plugin("kecil")

        @plugin.kartu("kecil.a", izin=["incomes:read"])
        async def a(ctx, pengaturan, periode):
            return {"value": nilai()}
    """

    def test_kode_sah_dimuat(self):
        self.tulis("kecil", self.manifest_kecil(), {"__init__.py": self.KODE_SAH,
                                                    "bantu.py": "def nilai():\n    return 1\n"})
        reg = muat(self.dir, ketat=True)
        self.assertEqual(list(reg.kode), ["kecil"])
        self.assertIsNotNone(reg.kode_plugin("kecil").ambil("kartu", "kecil.a"))
        self.assertTrue(reg.punya("kartu"))
        self.assertFalse(reg.punya("job"))

    def test_impor_terlarang_ditolak_sebelum_kode_jalan(self):
        penanda = self.dir / "jalan.txt"
        jahat = f"""
            import pathlib
            pathlib.Path({str(penanda)!r}).write_text("jalan")
            from app.models.models import Transaction
            from app import models
            from app.services import ruang
            import importlib
            from ..host import siklus
            __import__("os")
            def curang(ctx):
                return ctx._db
            from app.plugins.lain import x
            from app.plugins.sdk import Plugin
            plugin = Plugin("kecil")
        """
        self.tulis("kecil", self.manifest_kecil(), {"__init__.py": jahat})
        with self.assertRaises(ManifestTidakSah) as cm:
            muat(self.dir, ketat=True)
        teks = "\n".join(cm.exception.galat)
        for bagian in ("'app.models.models' tidak boleh", "impor 'app' terlalu luas", "'app.services' tidak boleh",
                       "impor 'importlib' tidak ada di daftar pustaka", "'app.plugins' terlalu luas", "__import__() tidak boleh",
                       "'app.plugins.lain' dari plugin di luar requires", "atribut '._db' tidak boleh"):
            self.assertIn(bagian, teks)
        self.assertFalse(penanda.exists(), "kode plugin tidak boleh dijalankan sebelum impornya lolos")
        # Mode start: dilewati dengan log, API tetap jalan, kodenya tetap tidak dijalankan.
        with self.assertLogs("jatahku.plugins", level="ERROR"):
            reg = muat(self.dir)
        self.assertEqual(reg.plugins, {})
        self.assertFalse(penanda.exists())

    def test_impor_plugin_requires_boleh(self):
        m = Manifest.model_validate(self.manifest_kecil(requires=["induk"]))
        (self.dir / "kecil").mkdir()
        (self.dir / "kecil" / "__init__.py").write_text(
            "from app.plugins.induk.model import X\nfrom app.plugins.sdk import Plugin\nimport decimal\n")
        self.assertEqual(kode_mod.periksa_impor(self.dir / "kecil", m), [])

    def test_kode_harus_cocok_dengan_manifest(self):
        kode = """
            from app.plugins.sdk import Plugin
            plugin = Plugin("kecil")

            @plugin.kartu("kecil.lain", izin=["transactions:read"])
            async def lain(ctx, p, q):
                return {}
        """
        self.tulis("kecil", self.manifest_kecil(), {"__init__.py": kode})
        with self.assertRaises(ManifestTidakSah) as cm:
            muat(self.dir, ketat=True)
        teks = "\n".join(cm.exception.galat)
        self.assertIn("kartu 'kecil.lain' didaftarkan di kode tetapi tidak ada di manifest", teks)
        self.assertIn("cards 'kecil.a' di manifest tidak punya fungsi", teks)
        self.assertIn("meminta izin di luar manifest: transactions:read", teks)

    def test_kode_tanpa_objek_plugin_atau_id_salah(self):
        self.tulis("kecil", self.manifest_kecil(contributes={}), {"__init__.py": "x = 1\n"})
        self.tulis("dua", self.manifest_kecil("dua", contributes={}),
                   {"__init__.py": "from app.plugins.sdk import Plugin\nplugin = Plugin('bukan')\n"})
        with self.assertRaises(ManifestTidakSah) as cm:
            muat(self.dir, ketat=True)
        teks = "\n".join(cm.exception.galat)
        self.assertIn("kecil: kode gagal dimuat: TypeError", teks)
        self.assertIn("dua: Plugin('bukan') harus Plugin('dua')", teks)

    def test_izin_per_jenis(self):
        """Review #186 temuan 1: hanya job yang boleh mengirim; titik lain hanya membaca."""
        p = Plugin("contoh")
        for jenis, kunci in (("kartu", "contoh.kas"), ("kartu", "contoh.rusak"), ("cek", "anggaran"),
                             ("aturan_advisor", "CT-01"), ("perintah_bot", "kas"), ("perintah_bot", "halo"),
                             ("field_form", "transaction.proyek")):
            izin = ["notifications:send"] if (jenis, kunci) == ("perintah_bot", "halo") else []
            p._dekor(jenis, kunci, izin)(lambda *a: None)
        p.job("pagi", izin=["notifications:send", "envelopes:read"])(lambda c: None)
        galat = kode_mod.cocokkan(Manifest.model_validate(MF), p)
        self.assertEqual(galat, ["perintah_bot 'halo' meminta izin yang tidak boleh untuk perintah_bot: "
                                 "notifications:send (hanya baca; kirim hanya dari job)"])

    def test_jalan_pintas_ditolak(self):
        """Review #186 temuan 4: internal SDK, introspeksi, dan atribut dunder ditolak; pola biasa tetap boleh."""
        m = Manifest.model_validate(self.manifest_kecil())
        (self.dir / "kecil").mkdir()
        berkas = self.dir / "kecil" / "__init__.py"
        kasus = {
            "from app.plugins.sdk.context import sesi": "tidak boleh; pakai `from app.plugins.sdk import",
            "import app.plugins.sdk": "tidak boleh; pakai `from app.plugins.sdk import",
            "from app.plugins.sdk import _host": "'_host' bukan nama publik",
            "import sys": "impor 'sys' tidak ada di daftar pustaka",
            "import gc": "impor 'gc' tidak ada di daftar pustaka",
            "import inspect": "impor 'inspect' tidak ada di daftar pustaka",
            "import operator": "impor 'operator' tidak ada di daftar pustaka",
            "from pkgutil import resolve_name": "impor 'pkgutil' tidak ada di daftar pustaka",
            "import os": "impor 'os' tidak ada di daftar pustaka",
            "async def f(ctx):\n    await ctx._tolak('x', 'y')": "atribut '._tolak' tidak boleh",
            "from app.plugins.sdk import PluginContext\nPluginContext.ruang_id = 1": "tidak boleh diubah",
            "from app.plugins.sdk import PluginContext as P\ndel P.envelopes": "tidak boleh diubah",
            "from app.plugins.sdk import PluginContext\nclass X(PluginContext):\n    pass": "tidak boleh menurunkan",
            "x = getattr(ctx, '_d' + 'b')": "getattr() hanya dengan nama atribut tetap",
            "x = getattr(ctx, '_k')": "getattr() hanya dengan nama atribut tetap",
            "x = vars(ctx)": "vars() tidak boleh",
            "x = ctx.envelopes.__globals__": "atribut '.__globals__' tidak boleh",
            "x = ctx.__class__": "atribut '.__class__' tidak boleh",
            "x = eval('1')": "eval() tidak boleh",
            "async def f(ctx):\n    return ctx.envelopes().cr_frame.f_globals": "atribut '.cr_frame' tidak boleh",
            "def f(g):\n    return g.gi_frame.f_back": "atribut '.gi_frame' tidak boleh",
            "from functools import reduce\nx = reduce(getattr, ['envelopes'], 1)": "'getattr' hanya boleh dipanggil langsung",
            "import string": "impor 'string' tidak ada di daftar pustaka",
            "from typing import get_type_hints": "impor 'get_type_hints' tidak boleh",
            "import typing\nx = typing.get_type_hints": "atribut '.get_type_hints' tidak boleh",
            "x = '{0.envelopes}'.format(1)": ".format() tidak boleh",
            "x = '{a}'.format_map({})": ".format_map() tidak boleh",
            "f = '{0.envelopes}'.format\nx = f(1)": "atribut '.format' tidak boleh",
        }
        for kode, pesan in kasus.items():
            with self.subTest(kode=kode):
                berkas.write_text(kode + "\n")
                self.assertTrue(any(pesan in g for g in kode_mod.periksa_impor(self.dir / "kecil", m)),
                                kode_mod.periksa_impor(self.dir / "kecil", m))
        berkas.write_text("from app.plugins.sdk import Plugin, Saran, AksiRoute\nfrom decimal import Decimal\n"
                          "from collections import namedtuple\nfrom typing import Any\n"
                          "nama = type(Decimal(1)).__name__\nx = getattr(Saran, 'judul', None)\n"
                          "T = namedtuple('T', 'a b')\ny = T(1, 2)._replace(a=3)._asdict()\nz = f'{nama} {y}'\n"
                          "class A:\n    def __init__(self):\n        super().__init__()\n")
        self.assertEqual(kode_mod.periksa_impor(self.dir / "kecil", m), [])

    def test_plugin_contoh_cocok(self):
        self.assertEqual(kode_mod.cocokkan(Manifest.model_validate(MF), plugin), [])

    def test_daftar_dua_kali_dan_izin_string(self):
        p = Plugin("x")
        p.job("a")(lambda c: None)
        with self.assertRaises(ValueError):
            p.job("a")(lambda c: None)
        with self.assertRaises(TypeError):
            p.kartu("x.a", izin="incomes:read")


# ── 2. manifest 1.1 ──────────────────────────────────────────────────────
class ManifestH2Tests(unittest.TestCase):
    def gagal(self, bagian, **ubah):
        with self.assertRaises(ValidationError) as cm:
            Manifest.model_validate(mf(**ubah))
        self.assertIn(bagian, str(cm.exception))

    def test_manifest_contoh_sah(self):
        m = Manifest.model_validate(MF)
        self.assertEqual(m.contributes.checks, ["anggaran"])
        self.assertEqual(m.contributes.nlp_kamus, {"Bahan Baku": ["tepung", "gula pasir"]})

    def test_aturan_baru(self):
        self.gagal("String should match pattern", contributes={"jobs": [{"key": "a", "schedule": "daily 08:30"}]})
        self.gagal("String should match pattern", contributes={"jobs": [{"key": "a", "schedule": "*/5 * * * *"}]})
        self.gagal("domain aturan inti", contributes={"advisor_rules": ["PER-01"]})
        self.gagal("harus berbentuk", contributes={"advisor_rules": ["ct01"]})
        self.gagal("cek ganda", contributes={"checks": ["ab", "ab"]})
        self.gagal("huruf kecil/angka", contributes={"nlp_kamus": {"Bahan": ["Tepung"]}})
        self.gagal("1–100 kata", contributes={"nlp_kamus": {"Bahan": []}})
        Manifest.model_validate(mf(contributes={"jobs": [{"key": "pagi", "schedule": "hourly"}]}))

    def test_domain_inti_sama_dengan_render(self):
        from app.services.advisor.render import TEMPLATE
        self.assertEqual({k.split("-")[0] for k in TEMPLATE}, set(DOMAIN_ADVISOR_INTI))

    def test_versi_lama_tidak_cocok(self):
        # Satu minor di atas host sekarang (tidak perlu diubah lagi tiap Plugin API naik; U4 menaikkannya ke 1.5).
        from app.plugins.host.manifest import PLUGIN_API_VERSION
        besar, kecil = PLUGIN_API_VERSION[:2]
        self.gagal("tidak cocok", engines={"plugin_api": f">={besar}.{kecil + 1}"})


# ── 3. keluaran plugin ───────────────────────────────────────────────────
class KeluaranTests(unittest.TestCase):
    def test_kartu_kpi(self):
        out = titik.rapikan_kartu("kpi", {"value": D("1500.50"), "unit": "rp", "bar": D("0.5"), "tone": "warn"},
                                  "contoh")
        self.assertEqual(out["value"], "1500.50")         # Decimal → string desimal, bukan float
        self.assertEqual(out["bar"], 0.5)
        self.assertEqual(out["shape"], "kpi")

    def test_kartu_ditolak(self):
        salah = [
            ("kpi", {"value": 1.5}),                                       # float
            ("kpi", {"value": 1, "rahasia": "x"}),                         # field asing
            ("kpi", {"value": 1, "unit": "usd"}),
            ("kpi", {"value": 1, "bar": 2}),
            ("list", {"items": [{"judul": "a"}] * 9}),                     # > 8
            ("list", {"items": [{"judul": "a", "aksi": {"kind": "route", "payload": {"to": "/p/lain"}}}]}),
            ("list", {"items": [{"judul": "a", "aksi": {"kind": "route", "payload": {"to": "https://x.id"}}}]}),
            ("list", {"items": [{"judul": "a", "aksi": {"kind": "plan", "payload": {}}}]}),
            ("table", {"columns": ["a"], "rows": [["x", "y"]]}),
            ("series", {"x": ["1"], "series": [{"nama": "a", "values": [1, 2]}]}),
            ("alert", {"tone": "merah", "judul": "x"}),
            ("inti", {"sumber": {}}),
        ]
        for shape, data in salah:
            with self.subTest(shape=shape, data=data), self.assertRaises(titik.KeluaranTidakSah):
                titik.rapikan_kartu(shape, data, "contoh")

    def test_keluaran_ketat(self):
        """Review #186 temuan 7: float, NaN, dan baris baru di tautan ditolak."""
        m = Manifest.model_validate(MF)
        for ke in ("/p/contoh\n", "/p/contoh/x\n", "/p/contohlain"):
            with self.subTest(ke=ke), self.assertRaises(titik.KeluaranTidakSah):
                titik.rute_plugin(ke, "contoh")
        for data in ({"value": D("NaN")}, {"value": D("Infinity")}, {"value": 1, "bar": D("NaN")}):
            with self.subTest(data=data), self.assertRaises(titik.KeluaranTidakSah):
                titik.rapikan_kartu("kpi", data, "contoh")
        for ubah in ({"rupiah": 0.1}, {"urgensi": 0.5}, {"rupiah": D("NaN")}, {"entitas": "kas\n"}):
            with self.subTest(ubah=ubah), self.assertRaises(titik.KeluaranTidakSah):
                titik.ke_insight(m, "CT-01", Saran(**{"entitas": "kas", "tone": "ok", "judul": "a", "isi": "",
                                                       **ubah}))

    def test_kartu_bentuk_lain(self):
        out = titik.rapikan_kartu("list", {"items": [{"judul": "INV-1", "nominal": 2500, "aksi": {
            "kind": "route", "label": "Buka", "payload": {"to": "/p/contoh/faktur/inv-1"}}}]}, "contoh")
        self.assertEqual(out["items"][0]["aksi"]["payload"]["to"], "/p/contoh/faktur/inv-1")
        out = titik.rapikan_kartu("series", {"x": ["1", "2"], "series": [{"nama": "Kas", "values": [1, D("2")]}]},
                                  "contoh")
        self.assertEqual(out["series"][0]["values"], [1, "2"])
        titik.rapikan_kartu("table", {"columns": ["a", "b"], "rows": [["x", 1]]}, "contoh")
        titik.rapikan_kartu("progress", {"items": [{"label": "a", "value": 1, "target": 2}]}, "contoh")

    def test_saran_ke_insight(self):
        m = Manifest.model_validate(MF)
        ins = titik.ke_insight(m, "CT-01", Saran(entitas="kas", tone="warn", judul="Kas", isi="x",
                                                   aksi=(AksiRoute("Buka", "/p/contoh"),)))
        self.assertEqual((ins.asal, ins.slot, ins.aturan), ("contoh", ("daftar",), "CT-01"))
        for s in (Saran(entitas="kas", tone="x", judul="a", isi=""),
                  Saran(entitas="kas", tone="ok", judul="a", isi="", aksi=(AksiRoute("a", "/advisor/plan"),)),
                  Saran(entitas="k a s", tone="ok", judul="a", isi=""),
                  Saran(entitas="kas", tone="ok", judul="", isi="")):
            with self.subTest(s=s), self.assertRaises(titik.KeluaranTidakSah):
                titik.ke_insight(m, "CT-01", s)

    def test_insight_plugin_dibatasi_per_plugin_dan_tidak_di_chip(self):
        from app.services.advisor.insight import KonstantaAturan, Insight
        from app.services.advisor.render import render_insight
        from app.services.advisor.select import pilih_daftar, pilih_kpi
        m = Manifest.model_validate(MF)
        ins = [titik.ke_insight(m, "CT-01", Saran(entitas=f"e{i}", tone="danger", judul=f"J{i}", isi="",
                                                     aksi=(AksiRoute("Buka", "/p/contoh"),))) for i in range(3)]
        inti = Insight(aturan="PER-01", entitas="x", tone="warn", slot=("daftar", "kpi:terpakai"),
                       aksi=[{"kind": "plan", "kode": "tutup_minus", "payload": {}}])
        for i, x in enumerate(ins):
            x.skor = D(90 - i)
        inti.skor = D(10)
        tampil, sisa = pilih_daftar(ins + [inti], SimpleNamespace(k=KonstantaAturan()))
        self.assertEqual([x.id for x in tampil], ["CT-01:e0", "PER-01:x"])
        self.assertEqual(len(sisa), 2)
        self.assertIsNone(pilih_kpi(ins, "terpakai"))
        out = render_insight(ins[0], None)
        self.assertEqual(out["judul"], "J0")
        self.assertEqual(out["aksi"], [{"kind": "route", "label": "Buka", "payload": {"to": "/p/contoh"}}])

    def test_jadwal_dan_kamus(self):
        pagi = datetime(2026, 11, 4, 8, 23)
        self.assertEqual(titik.jatuh_tempo("daily 08:00", pagi), "2026-11-04")
        self.assertIsNone(titik.jatuh_tempo("daily 09:00", pagi))
        self.assertEqual(titik.jatuh_tempo("hourly", pagi), "2026-11-04T08")
        kamus = [("Bahan Baku", ["tepung", "gula pasir"])]
        self.assertEqual(titik.tebak_kamus(kamus, "Beli GULA PASIR 2kg"), "Bahan Baku")
        self.assertIsNone(titik.tebak_kamus(kamus, "kopi"))

    def test_tanpa_plugin_tanpa_kerja(self):
        """Tanpa plugin terdaftar, titik kembali seketika tanpa menyentuh DB (db=None akan gagal bila dipakai)."""
        import asyncio
        with pakai_registry(Registry()):
            env = SimpleNamespace(household_id="h", id="e")
            user = SimpleNamespace(id="u")
            self.assertEqual(asyncio.run(titik.kartu_ruang(None, user, "h")), {})
            self.assertEqual(asyncio.run(titik.peringatan_pengeluaran(None, user, env, 1, "x")), [])
            self.assertEqual(asyncio.run(titik.saran_advisor(None, user, "h")), [])
            self.assertEqual(asyncio.run(titik.kamus_ruang(None, "h", "u")), [])
            self.assertEqual(asyncio.run(titik.jalankan_job()), 0)
            self.assertEqual(titik.perintah_plugin(), {})


# ── 4–5. DB ──────────────────────────────────────────────────────────────
class _Redis:
    """Redis palsu untuk buku notifikasi dan klaim job."""

    def __init__(self):
        self.h: dict = {}
        self.s: dict = {}
        self.mati = False

    def _cek(self):
        if self.mati:
            raise ConnectionError("redis mati")

    async def hsetnx(self, k, f, v):
        self._cek()
        d = self.h.setdefault(k, {})
        if f in d:
            return 0
        d[f] = v
        return 1

    async def hlen(self, k):
        return len(self.h.get(k, {}))

    async def hdel(self, k, f):
        self.h.get(k, {}).pop(f, None)

    async def expire(self, k, t):
        return True

    async def set(self, k, v, nx=False, ex=None):
        self._cek()
        if nx and k in self.s:
            return None
        self.s[k] = v
        return True

    async def aclose(self):
        pass


if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import select

    from app.api.routes import dashboard as dashboard_route
    from app.api.routes import transactions as transactions_route
    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        Allocation, AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, HouseholdType, Income,
        PluginAuditLog, PluginInstallation, Transaction, User,
    )
    from app.plugins.host.keadaan import pakai_sesi
    from app.plugins.sdk.plugin import Pendaftaran
    from app.services import ruang


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class SdkDbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from app.tests.test_advisor_dashboard_integration import FakeRedis
        PERILAKU.clear()
        JEJAK.clear()
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        for ctx in (pakai_registry(registry_contoh()), pakai_sesi(self.Session)):
            ctx.__enter__()
            self.addCleanup(ctx.__exit__, None, None, None)
        self.redis = _Redis()
        for p in (patch.object(titik, "_redis", lambda: self.redis),
                  patch("redis.asyncio.from_url", return_value=FakeRedis())):
            p.start()
            self.addCleanup(p.stop)
        self.terkirim = []

        async def kirim(user, tipe, judul, isi, *, link=None, permukaan=(), **_):
            self.terkirim.append((user.name, judul, isi, link))
            return {"web"}
        p = patch("app.services.notification_service.kirim", kirim)
        p.start()
        self.addCleanup(p.stop)

        hari = date.today()
        async with self.Session() as db:
            pemilik, admin, karyawan, orang = (User(name=n, plan="pro", timezone="Asia/Jakarta")
                                               for n in ("Pemilik", "Admin", "Karyawan", "Orang"))
            usaha = Household(name="Dapur Nusa", type=HouseholdType.USAHA)
            rumah = Household(name="Rumah", type=HouseholdType.RUMAH_TANGGA)
            asing = Household(name="Usaha orang", type=HouseholdType.USAHA)
            db.add_all([pemilik, admin, karyawan, orang, usaha, rumah, asing])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=pemilik.id, household_id=usaha.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=admin.id, household_id=usaha.id, role=HouseholdRole.admin),
                HouseholdMember(user_id=karyawan.id, household_id=usaha.id, role=HouseholdRole.member),
                HouseholdMember(user_id=pemilik.id, household_id=rumah.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=orang.id, household_id=asing.id, role=HouseholdRole.owner),
                AppSetting(key="plugin_contoh_users", value="*"),
                AppSetting(key=ruang.FLAG_RUANG_USAHA, value="*"),
            ])
            bahan = Envelope(household_id=usaha.id, name="Bahan Baku", emoji="🧂", budget_amount=D("100000"))
            pribadi = Envelope(household_id=usaha.id, name="Pribadi Admin", budget_amount=D("1"), owner_id=admin.id)
            makan = Envelope(household_id=rumah.id, name="Makan", budget_amount=D("1"))
            kas_asing = Envelope(household_id=asing.id, name="Kas Orang", budget_amount=D("1"))
            db.add_all([bahan, pribadi, makan, kas_asing])
            await db.flush()
            for hid, uid, amp, isi in ((usaha.id, pemilik.id, bahan.id, D("500000")),
                                       (rumah.id, pemilik.id, makan.id, D("500000"))):
                inc = Income(household_id=hid, user_id=uid, amount=isi, description="Modal", income_date=hari)
                db.add(inc)
                await db.flush()
                db.add(Allocation(income_id=inc.id, envelope_id=amp, amount=isi))
            db.add_all([
                Transaction(envelope_id=bahan.id, user_id=pemilik.id, amount=D("30000"), description="tepung",
                            transaction_date=hari),
                Transaction(envelope_id=bahan.id, user_id=admin.id, amount=D("20000"), description="rahasia admin",
                            transaction_date=hari, is_private=True),
                Transaction(envelope_id=pribadi.id, user_id=admin.id, amount=D("5000"), description="pribadi",
                            transaction_date=hari),
                Transaction(envelope_id=kas_asing.id, user_id=orang.id, amount=D("99000"), description="asing",
                            transaction_date=hari),
            ])
            db.add(PluginInstallation(household_id=usaha.id, plugin_id="contoh", status="active",
                                      installed_by=pemilik.id, granted_permissions=list(IZIN), settings={}))
            await db.commit()
        self.pemilik, self.admin, self.karyawan, self.orang = pemilik, admin, karyawan, orang
        self.usaha, self.rumah, self.asing = usaha.id, rumah.id, asing.id
        self.bahan, self.makan = bahan.id, makan.id
        self.hari = hari

        self.current = pemilik
        app = FastAPI()
        ruang.install(app)
        app.include_router(dashboard_route.router, prefix="/dashboard")
        app.include_router(transactions_route.router, prefix="/transactions")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    # ── pembantu ──
    async def ctx(self, db, user, jenis="kartu", kunci="contoh.kas", hid=None, izin=None):
        """Konteks buatan host untuk fungsi plugin contoh; `izin` mengganti `izin=` fungsinya (tes saja)."""
        m = Manifest.model_validate(MF)
        hid = hid or self.usaha
        inst = (await db.execute(select(PluginInstallation).where(PluginInstallation.household_id == hid)
                                 )).scalar_one()
        ruang_ = await db.get(Household, hid)
        peran = await titik._peran(db, user.id, hid) if user else "sistem"
        d = plugin.ambil(jenis, kunci)
        if izin is not None:
            d = Pendaftaran(d.jenis, d.kunci, d.fn, tuple(izin))
        return titik.konteks(db, m, inst, ruang_, d, viewer=user, peran=peran, sumber=f"uji:{kunci}")

    async def set_setting(self, key, value):
        async with self.Session() as db:
            ada = await db.get(AppSetting, key)
            if ada:
                ada.value = value
            else:
                db.add(AppSetting(key=key, value=value))
            await db.commit()

    async def set_status(self, status):
        async with self.Session() as db:
            inst = (await db.execute(select(PluginInstallation))).scalar_one()
            inst.status = status
            await db.commit()

    async def audit(self):
        async with self.Session() as db:
            return [(a.action, a.detail) for a in (await db.execute(select(PluginAuditLog))).scalars()]

    def hdr(self, hid=None):
        return {"X-Jatahku-Ruang": str(hid or self.usaha)}

    # ── PluginContext ──
    async def test_ctx_visibilitas_dan_ruang(self):
        async with self.Session() as db:
            c = await self.ctx(db, self.pemilik, "perintah_bot", "kas")
            txn = await c.transactions(date(2000, 1, 1), date(2100, 1, 1))
            self.assertEqual(sorted(t.deskripsi for t in txn), ["Transaksi privat", "tepung"])
            self.assertEqual(sum(t.jumlah for t in txn), D("50000"))     # agregat tetap utuh
            c = await self.ctx(db, self.admin, "perintah_bot", "kas")
            txn = await c.transactions(date(2000, 1, 1), date(2100, 1, 1))
            self.assertEqual(sorted(t.deskripsi for t in txn), ["pribadi", "rahasia admin", "tepung"])

    async def test_ctx_izin_irisan_dan_audit(self):
        async with self.Session() as db:
            c = await self.ctx(db, self.pemilik, "kartu", "contoh.rusak")     # fungsi tanpa izin=
            with self.assertRaises(IzinDitolak) as cm:
                await c.envelopes()
            self.assertEqual(cm.exception.alasan, "tanpa_izin")
            with self.assertRaises(IzinDitolak):                               # dicatat sekali per jam
                await c.envelopes()
        self.assertEqual(await self.audit(), [("tolak:envelopes:read", {"alasan": "tanpa_izin",
                                                                         "sumber": "uji:contoh.rusak"})])
        # Izin di manifest dan fungsi, tetapi belum disetujui di instalasi (manifest versi baru) → ditolak.
        async with self.Session() as db:
            inst = (await db.execute(select(PluginInstallation))).scalar_one()
            inst.granted_permissions = ["envelopes:read"]
            await db.commit()
            c = await self.ctx(db, self.pemilik, "perintah_bot", "kas")
            with self.assertRaises(IzinDitolak):
                await c.transactions(date(2000, 1, 1), date(2100, 1, 1))

    async def test_ctx_tidak_bisa_diubah_atau_disalin(self):
        """Review #186 temuan 3–4: keadaan konteks di host; viewer bukan objek ORM."""
        import copy as copy_mod
        from app.plugins.host.keadaan import KonteksTidakSah
        from app.plugins.sdk import PenggunaView, PluginContext
        async with self.Session() as db:
            c = await self.ctx(db, self.pemilik, "kartu", "contoh.rusak")
            for attr, nilai in (("izin", frozenset(IZIN)), ("peran", "owner"), ("ruang_id", self.asing)):
                with self.subTest(attr=attr):
                    with self.assertRaises(AttributeError):
                        setattr(c, attr, nilai)
                    with self.assertRaises(AttributeError):
                        object.__setattr__(c, attr, nilai)
            self.assertFalse(hasattr(c, "__dict__"))
            with self.assertRaises(TypeError):
                dataclasses.replace(c, izin=frozenset(IZIN))
            for salin in (copy_mod.copy, copy_mod.deepcopy):
                with self.assertRaises(TypeError):
                    salin(c)
            with self.assertRaises(TypeError):
                PluginContext()
            palsu = object.__new__(PluginContext)
            with self.assertRaises(KonteksTidakSah):
                await palsu.envelopes()
            # Review ulang #186 no. 1, 3: kelas tidak bisa ditambal atau diturunkan; izin diperiksa host.
            for nama in ("ruang_id", "envelopes", "_perlu"):
                with self.subTest(tambal=nama), self.assertRaises(TypeError):
                    setattr(PluginContext, nama, property(lambda self: self.asing))
            with self.assertRaises(TypeError):
                delattr(PluginContext, "envelopes")
            with self.assertRaises(TypeError):
                type("Menyaru", (PluginContext,), {})
            self.assertFalse(hasattr(c, "_tolak") or hasattr(c, "_perlu"))
            # Kelas Plugin juga beku (review ulang kedua #186 no. 2): menambalnya mengubah semua plugin.
            Q = Plugin
            with self.assertRaises(TypeError):
                Q.ambil = lambda self, j, k: None
            with self.assertRaises(TypeError):
                type("PluginLain", (Plugin,), {})
            # Konteks ditutup sesudah fungsi plugin selesai (review ulang kedua #186 no. 1).
            from app.plugins.host import keadaan as keadaan_mod
            async def baca(ctx):
                return len(await ctx.envelopes())
            c2 = await self.ctx(db, self.pemilik, "kartu", "contoh.kas", izin=["envelopes:read"])
            self.assertEqual(await titik.panggil(c2, baca), 1)
            with self.assertRaises(KonteksTidakSah):
                keadaan_mod.ambil(c2)
            with self.assertRaises(KonteksTidakSah):
                await c2.envelopes()
            # Konteks hanya berlaku di task asyncio yang membuatnya (review ulang ketiga #186 no. 1): permintaan lain
            # yang berjalan bersamaan tidak bisa meminjamnya.
            import asyncio
            c3 = await self.ctx(db, self.pemilik, "kartu", "contoh.kas", izin=["envelopes:read"])
            self.assertEqual(len(await c3.envelopes()), 1)
            with self.assertRaises(KonteksTidakSah):
                await asyncio.create_task(c3.envelopes())
            self.assertIsInstance(c.viewer, PenggunaView)
            self.assertEqual((c.viewer.id, c.viewer.nama), (self.pemilik.id, "Pemilik"))
            self.assertFalse(hasattr(c.viewer, "email"))
            with self.assertRaises(IzinDitolak):
                await c.envelopes()

    async def test_ctx_karyawan_tanpa_data_keuangan(self):
        async with self.Session() as db:
            c = await self.ctx(db, self.karyawan, "perintah_bot", "kas")
            self.assertTrue(c.karyawan)
            with self.assertRaises(IzinDitolak) as cm:
                await c.transactions(date(2000, 1, 1), date(2100, 1, 1))
            self.assertEqual(cm.exception.alasan, "khusus_admin")

    async def test_ctx_job_tanpa_user_fail_closed(self):
        async with self.Session() as db:
            c = await self.ctx(db, None, "job", "pagi")
            self.assertEqual([a.nama for a in await c.envelopes()], ["Bahan Baku"])   # tanpa amplop pribadi
            c = await self.ctx(db, None, "job", "pagi", izin=["transactions:read"])
            txn = await c.transactions(date(2000, 1, 1), date(2100, 1, 1))
            self.assertEqual(sorted(t.deskripsi for t in txn), ["Transaksi privat", "Transaksi privat"])

    async def test_ctx_pemasukan_ruang_lain_none(self):
        async with self.Session() as db:
            c = await self.ctx(db, self.pemilik, "aturan_advisor", "CT-01")
            lain = (await db.execute(select(Income).where(Income.household_id == self.rumah))).scalar_one()
            self.assertIsNone(await c.income(lain.id))
            self.assertEqual(len(await c.incomes(date(2000, 1, 1), date(2100, 1, 1))), 1)

    # ── cards ──
    async def test_kartu_layout_dan_data_http(self):
        r = await self.client.put("/dashboard/layout", headers=self.hdr(), json={
            "surface": "beranda", "if_version": 0, "removed": [],
            "items": [*((await self.client.get("/dashboard/layout", headers=self.hdr())).json()["items"]),
                      {"id": "p1", "card": "contoh.kas", "size": "S"},
                      {"id": "p2", "card": "contoh.rusak", "size": "M"}]})
        self.assertEqual(r.status_code, 200, r.text)
        r = await self.client.post("/dashboard/data", headers=self.hdr(), json={"items": [
            {"id": "p1", "card": "contoh.kas"}, {"id": "p2", "card": "contoh.rusak"}]})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()["data"]
        self.assertEqual(data["p1"]["shape"], "kpi")
        self.assertEqual(data["p1"]["value"], "50000.00")
        self.assertEqual(data["p2"]["error"]["kode"], "gagal_memuat")         # izin ditolak → gagal sendiri
        r = await self.client.get("/dashboard/data/p1", headers=self.hdr())
        self.assertEqual(r.json()["shape"], "kpi")
        # Dijeda → kartu diparkir, datanya tidak bisa diminta, tidak bisa ditambahkan.
        await self.set_status("paused")
        doc = (await self.client.get("/dashboard/layout", headers=self.hdr())).json()
        self.assertNotIn("contoh.kas", [i["card"] for i in doc["items"]])
        self.assertIn("contoh.kas", [i["card"] for i in doc["parked"]])
        r = await self.client.post("/dashboard/data", headers=self.hdr(), json={"items": [{"id": "p1", "card": "contoh.kas"}]})
        self.assertEqual(r.json()["data"]["p1"]["error"]["kode"], "kartu_tidak_dikenal")
        r = await self.client.put("/dashboard/layout", headers=self.hdr(), json={
            "surface": "beranda", "if_version": doc["version"], "removed": [],
            "items": doc["items"] + [{"id": "p9", "card": "contoh.kas", "size": "S"}]})
        self.assertEqual(r.json()["kode"], "kartu_tidak_dikenal")

    async def test_kartu_saklar_flag_dan_ruang_lain(self):
        item = {"items": [{"id": "p1", "card": "contoh.kas"}]}
        await self.set_setting("plugin_saklar_darurat", "Contoh")
        r = await self.client.post("/dashboard/data", headers=self.hdr(), json=item)
        self.assertEqual(r.json()["data"]["p1"]["error"]["kode"], "kartu_tidak_dikenal")
        await self.set_setting("plugin_saklar_darurat", "")
        await self.set_setting("plugin_contoh_users", str(self.admin.id))           # pemilik di luar flag
        r = await self.client.post("/dashboard/data", headers=self.hdr(), json=item)
        self.assertEqual(r.json()["data"]["p1"]["error"]["kode"], "kartu_tidak_dikenal")
        await self.set_setting("plugin_contoh_users", "*")
        r = await self.client.post("/dashboard/data", headers=self.hdr(self.rumah), json=item)   # tidak terpasang
        self.assertEqual(r.json()["data"]["p1"]["error"]["kode"], "kartu_tidak_dikenal")
        # R6: karyawan membuka Beranda, tetapi kartu plugin selalu kartu umum: tanpa data, penyedia tidak dipanggil.
        self.current = self.karyawan
        PERILAKU["kartu_float"] = True        # bila penyedia sempat dipanggil, galatnya akan `gagal_memuat`
        r = await self.client.post("/dashboard/data", headers=self.hdr(), json=item)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["p1"]["error"]["kode"], "khusus_admin")
        r = await self.client.put("/dashboard/layout", headers=self.hdr(), json={
            "surface": "beranda", "if_version": 0, "removed": [], "items": [{"id": "p9", "card": "contoh.kas", "size": "S"}]})
        self.assertEqual(r.json()["kode"], "kartu_tidak_dikenal")

    async def test_konteks_simpanan_tidak_berlaku_untuk_user_lain(self):
        """Review ulang kedua #186 no. 1: konteks yang disimpan plugin tidak membuka data ruang lain untuk user lain."""
        PERILAKU["simpan_ctx"] = True
        item = {"items": [{"id": "p1", "card": "contoh.kas"}]}
        r = await self.client.post("/dashboard/data", headers=self.hdr(), json=item)
        self.assertEqual(r.json()["data"]["p1"]["value"], "50000.00")           # panggilan pertama: konteksnya sendiri
        async with self.Session() as db:
            db.add(PluginInstallation(household_id=self.asing, plugin_id="contoh", status="active",
                                      installed_by=self.orang.id, granted_permissions=list(IZIN), settings={}))
            await db.commit()
        self.current = self.orang
        with self.assertLogs("jatahku.dashboard", level="ERROR"):
            r = await self.client.post("/dashboard/data", headers=self.hdr(self.asing), json=item)
        self.assertEqual(r.json()["data"]["p1"]["error"]["kode"], "gagal_memuat")   # konteks lama sudah ditutup

    async def test_kartu_menerima_periode_beku(self):
        PERILAKU["ubah_periode"] = True
        r = await self.client.post("/dashboard/data", headers=self.hdr(), json={"items": [
            {"id": "p1", "card": "contoh.kas"}, {"id": "a1", "card": "core.cocokkan_saldo"}]})
        self.assertEqual(r.json()["data"]["p1"]["error"]["kode"], "gagal_memuat")
        self.assertNotEqual(r.json()["periode"]["start"], "2000-01-01")     # periode batch tidak berubah
        self.assertNotIn("error", r.json()["data"]["a1"])

    async def test_kartu_float_gagal_sendiri(self):
        PERILAKU["kartu_float"] = True
        r = await self.client.post("/dashboard/data", headers=self.hdr(), json={"items": [
            {"id": "p1", "card": "contoh.kas"}, {"id": "a1", "card": "core.cocokkan_saldo"}]})
        self.assertEqual(r.json()["data"]["p1"]["error"]["kode"], "gagal_memuat")
        self.assertNotIn("error", r.json()["data"]["a1"])

    # ── checks ──
    async def test_cek_web_dan_bot(self):
        r = await self.client.post("/transactions/", headers=self.hdr(), json={
            "envelope_id": str(self.bahan), "amount": "150000", "description": "tepung 10 karung"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["peringatan"], ["Melewati anggaran Bahan Baku"])
        r = await self.client.post("/transactions/", headers=self.hdr(), json={
            "envelope_id": str(self.bahan), "amount": "1000", "description": "garam"})
        self.assertIsNone(r.json()["peringatan"])
        PERILAKU["cek_gagal"] = True                                  # bug plugin tidak menggagalkan pencatatan
        with self.assertLogs("jatahku.plugins", level="ERROR"):
            r = await self.client.post("/transactions/", headers=self.hdr(), json={
                "envelope_id": str(self.bahan), "amount": "150000", "description": "x"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIsNone(r.json()["peringatan"])
        PERILAKU.clear()
        from app.services.expense_rules import check_expense
        async with self.Session() as db:
            env = await db.get(Envelope, self.bahan)
            hasil = await check_expense(env, self.pemilik, D("120000"), db, skip_plan_limit=True)
            self.assertTrue(hasil.allowed)
            self.assertEqual(hasil.peringatan, ["Melewati anggaran Bahan Baku"])
            self.assertEqual(await titik.peringatan_pengeluaran(db, self.karyawan, env, D("150000"), "x"), [])
            makan = await db.get(Envelope, self.makan)                # ruang keluarga: plugin tidak terpasang
            self.assertEqual(await titik.peringatan_pengeluaran(db, self.pemilik, makan, D("9999999"), "x"), [])

    # ── advisor ──
    async def test_saran_advisor_dan_cache(self):
        async with self.Session() as db:
            ins = await titik.saran_advisor(db, self.pemilik, self.usaha)
            self.assertEqual([i.id for i in ins], ["CT-01:kas"])
            self.assertEqual(await titik.saran_advisor(db, self.karyawan, self.usaha), [])
            self.assertEqual(await titik.saran_advisor(db, self.pemilik, self.rumah), [])
        payload = {"advisor": {"items": [{"aturan": "CT-01"}, {"aturan": "PER-01"}],
                               "sisa": [{"id": "CT-01:x"}], "disembunyikan": [], "total": 3}}
        async with self.Session() as db:
            self.assertEqual(await titik.saring_payload_advisor(db, self.pemilik, self.usaha, payload), payload)
        await self.set_setting("plugin_saklar_darurat", "contoh")
        async with self.Session() as db:
            out = await titik.saring_payload_advisor(db, self.pemilik, self.usaha, payload)
            self.assertEqual(out["advisor"]["items"], [{"aturan": "PER-01"}])
            self.assertEqual(out["advisor"]["total"], 1)
            self.assertEqual(await titik.saran_advisor(db, self.pemilik, self.usaha), [])

    async def test_saran_masuk_dashboard_advisor(self):
        from app.services.advisor import dashboard as adv
        async with self.Session() as db:
            db.add(AppSetting(key=adv.FLAG_KEY, value="*"))
            await db.commit()
            out = await adv.get_dashboard(self.pemilik, db, household_id=self.usaha)
        semua = [i["aturan"] for i in out["advisor"]["items"]] + [s["id"].split(":")[0] for s in out["advisor"]["sisa"]]
        self.assertIn("CT-01", semua)
        item = next((i for i in out["advisor"]["items"] if i["aturan"] == "CT-01"), None)
        if item is not None:
            self.assertEqual(item["aksi"], [{"kind": "route", "label": "Buka kas", "payload": {"to": "/p/contoh/kas"}}])

    # ── bot ──
    async def test_perintah_bot(self):
        async with self.Session() as db:
            self.assertEqual(await titik.perintah(db, self.pemilik, "contoh", "kas"), ["[Dapur Nusa] 2 catatan"])
            self.assertEqual(await titik.perintah(db, self.admin, "contoh", "kas"), ["[Dapur Nusa] 3 catatan"])
            self.assertEqual(await titik.perintah(db, self.karyawan, "contoh", "kas"),
                             ["Laporan Dapur Nusa hanya untuk admin ruang."])
            self.assertEqual(await titik.perintah(db, self.karyawan, "contoh", "halo"), ["[Dapur Nusa] halo member"])
            self.assertEqual(await titik.perintah(db, self.orang, "contoh", "kas"), [titik.PESAN_BELUM_ADA])
            PERILAKU["bot_gagal"] = True
            with self.assertLogs("jatahku.plugins", level="ERROR"):
                self.assertEqual(await titik.perintah(db, self.pemilik, "contoh", "kas"),
                                 [f"[Dapur Nusa] {titik.PESAN_GAGAL}"])
        await self.set_status("paused")
        async with self.Session() as db:
            self.assertEqual(await titik.perintah(db, self.pemilik, "contoh", "halo"), [titik.PESAN_BELUM_ADA])
        await self.set_status("active")
        await self.set_setting(ruang.FLAG_RUANG_USAHA, str(self.admin.id))       # ruang usaha tertutup untuk pemilik
        async with self.Session() as db:
            self.assertEqual(await titik.perintah(db, self.pemilik, "contoh", "halo"), [titik.PESAN_BELUM_ADA])

    async def test_bot_commands_memuat_perintah_plugin_tanpa_menimpa_inti(self):
        from app.bot.handlers import bot_commands, perintah_inti
        daftar = bot_commands()
        self.assertEqual(set(daftar) - set(perintah_inti()), {"kas", "halo"})
        self.assertIs(daftar["status"], perintah_inti()["status"])

    async def test_handler_bot_teks_polos(self):
        from app.bot.plugin_cmd import handler_perintah
        balasan = []

        class Pesan:
            async def reply_text(self, teks, **kw):
                balasan.append((teks, kw))
        async with self.Session() as db:
            u = await db.get(User, self.pemilik.id)
            u.telegram_id = "777"
            await db.commit()
        upd = SimpleNamespace(effective_user=SimpleNamespace(id=777), message=Pesan())
        with patch("app.bot.plugin_cmd.AsyncSessionLocal", self.Session):
            await handler_perintah("contoh", "kas")(upd, None)
        self.assertEqual(balasan, [("[Dapur Nusa] 2 catatan", {})])

    # ── notifikasi dan job ──
    async def test_job_dan_notifikasi(self):
        pagi = datetime(2026, 11, 4, 1, 23, tzinfo=timezone.utc)     # 08.23 WIB
        self.assertEqual(await titik.jalankan_job(pagi), 1)
        self.assertEqual(JEJAK, [("job", None, self.usaha, ["Bahan Baku"])])
        self.assertEqual(sorted(t[0] for t in self.terkirim), ["Admin", "Pemilik"])     # tanpa karyawan
        self.assertEqual(self.terkirim[0][1:], ("[Dapur Nusa] Cek kas", "Jangan lupa cek kas.", "/p/contoh"))
        self.assertEqual(await titik.jalankan_job(pagi), 0)           # klaim sekali per hari
        self.assertEqual(await titik.jalankan_job(datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)), 0)
        self.assertIn(("kirim:notifications", {"jenis": "contoh.pengingat", "kunci": "contoh.pengingat",
                                               "penerima": 2, "sumber": "job:pagi"}), await self.audit())
        await self.set_status("paused")
        self.assertEqual(await titik.jalankan_job(datetime(2026, 11, 5, 1, 23, tzinfo=timezone.utc)), 0)

    async def test_notifikasi_job_memakai_jam_jadwal(self):
        """Notifikasi dari job disaring dengan jam jadwal job, bukan jam sungguhan. Dulu `ctx.notify` membaca jam
        sungguhan, sehingga `test_job_dan_notifikasi` merah setiap kali CI berjalan pukul 21.00–07.00 WIB (jam tenang)."""
        class _JamTenang(datetime):
            @classmethod
            def now(cls, tz=None):
                malam = datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc)      # 22.30 WIB
                return malam.astimezone(tz) if tz else malam.replace(tzinfo=None)
        pagi = datetime(2026, 11, 4, 1, 23, tzinfo=timezone.utc)                  # 08.23 WIB
        with patch.object(titik, "datetime", _JamTenang):
            self.assertEqual(await titik.jalankan_job(pagi), 1)
        self.assertEqual(sorted(t[0] for t in self.terkirim), ["Admin", "Pemilik"])

    async def test_notifikasi_penyaring(self):
        async with self.Session() as db:
            c = await self.ctx(db, None, "job", "pagi")
            malam = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)   # 22.00 WIB
            self.assertEqual(await titik.kirim_notifikasi(c, "contoh.pengingat", "a", "b", link=None, kunci="k1",
                                                          now=malam), 0)
            siang = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)
            self.assertEqual(await titik.kirim_notifikasi(c, "contoh.pengingat", "a", "b", link=None, kunci="k1",
                                                          now=siang), 2)
            self.assertEqual(await titik.kirim_notifikasi(c, "contoh.pengingat", "a", "b", link=None, kunci="k1",
                                                          now=siang), 0)       # kunci sama hari itu
            self.assertEqual(await titik.kirim_notifikasi(c, "contoh.pengingat", "a", "b", link=None, kunci="k2",
                                                          now=siang), 2)
            self.assertEqual(await titik.kirim_notifikasi(c, "contoh.pengingat", "a", "b", link=None, kunci="k3",
                                                          now=siang), 0)       # batas 2 per hari
            self.redis.mati = True
            besok = datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc)
            self.assertEqual(await titik.kirim_notifikasi(c, "contoh.pengingat", "a", "b", link=None, kunci="k4",
                                                          now=besok), 0)       # Redis mati → tidak mengirim
            with self.assertRaises(titik.KeluaranTidakSah):
                await c.notify("contoh.pengingat", "a", "b", link="https://jahat.id")
            with self.assertRaises(IzinDitolak):
                await c.notify("lain.pengingat", "a", "b")
            c = await self.ctx(db, None, "job", "pagi", izin=[])
            with self.assertRaises(IzinDitolak):
                await c.notify("contoh.pengingat", "a", "b")

    async def test_notify_hanya_dari_job(self):
        """Review #186 temuan 1: konteks yang dipicu user (melihat data pribadinya) tidak bisa mengirim ke anggota lain."""
        async with self.Session() as db:
            c = await self.ctx(db, self.admin, "perintah_bot", "halo", izin=["notifications:send"])
            self.assertNotIn("notifications:send", c.izin)                 # disaring izin per jenis saat berjalan
            with self.assertRaises(IzinDitolak):
                await c.notify("contoh.pengingat", "a", "b")
            c = await self.ctx(db, self.admin, "job", "pagi")              # job, tetapi dengan user
            with self.assertRaises(IzinDitolak) as cm:
                await c.notify("contoh.pengingat", "rahasia admin", "b")
            self.assertEqual(cm.exception.alasan, "bukan_job")
        self.assertEqual(self.terkirim, [])

    async def test_pemasukan_anggota_lain_tidak_terbaca_di_ruang_keluarga(self):
        """Review #186 temuan 2 dan review ulang no. 5: seperti `GET /incomes/`, di ruang keluarga plugin hanya membaca
        pemasukan milik viewer; job tidak membaca pemasukan ruang keluarga. Ruang usaha tetap utuh."""
        async with self.Session() as db:
            adik = User(name="Adik", plan="pro", timezone="Asia/Jakarta")
            db.add(adik)
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=adik.id, household_id=self.rumah, role=HouseholdRole.member),
                PluginInstallation(household_id=self.rumah, plugin_id="contoh", status="active",
                                   installed_by=self.pemilik.id, granted_permissions=list(IZIN), settings={}),
                Income(household_id=self.rumah, user_id=adik.id, amount=D("100000"), description="uang jajan",
                       income_date=self.hari),
            ])
            await db.commit()
            semua = (date(2000, 1, 1), date(2100, 1, 1))
            c = await self.ctx(db, adik, "aturan_advisor", "CT-01", hid=self.rumah)
            lihat = [(i.deskripsi, i.user_id, i.jumlah) for i in await c.incomes(*semua)]
            self.assertEqual(lihat, [("uang jajan", adik.id, D("100000"))])
            modal = (await db.execute(select(Income).where(Income.household_id == self.rumah,
                                                           Income.user_id == self.pemilik.id))).scalar_one()
            self.assertIsNone(await c.income(modal.id))
            c = await self.ctx(db, self.pemilik, "aturan_advisor", "CT-01", hid=self.rumah)
            self.assertEqual([i.deskripsi for i in await c.incomes(*semua)], ["Modal"])
            c = await self.ctx(db, None, "job", "pagi", hid=self.rumah, izin=["incomes:read"])
            self.assertEqual(await c.incomes(*semua), [])
            c = await self.ctx(db, self.admin, "aturan_advisor", "CT-01")    # ruang usaha: data usaha, utuh
            self.assertEqual([(i.deskripsi, i.user_id) for i in await c.incomes(*semua)], [("Modal", self.pemilik.id)])

    async def test_job_lewati_ruang_usaha_tertutup(self):
        """Review #186 temuan 5: ruang usaha di luar flag `ruang_usaha_users` pemiliknya tidak menjalankan job."""
        await self.set_setting(ruang.FLAG_RUANG_USAHA, str(self.admin.id))
        self.assertEqual(await titik.jalankan_job(datetime(2026, 11, 4, 1, 23, tzinfo=timezone.utc)), 0)
        self.assertEqual(JEJAK, [])

    async def test_audit_kiriman_dan_batas_notify(self):
        """Review #186 temuan 6: hanya kiriman yang sampai dicatat; panggilan notify dibatasi per konteks."""
        from app.plugins.sdk.context import MAKS_NOTIFY_PER_KONTEKS
        malam = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
        with patch.object(titik, "datetime", SimpleNamespace(now=lambda tz=None: malam)):
            async with self.Session() as db:
                c = await self.ctx(db, None, "job", "pagi")
                for i in range(MAKS_NOTIFY_PER_KONTEKS):
                    self.assertEqual(await c.notify("contoh.pengingat", "a", "b", kunci=f"k{i}"), 0)
                with self.assertRaises(IzinDitolak) as cm:
                    await c.notify("contoh.pengingat", "a", "b", kunci="lagi")
                self.assertEqual(cm.exception.alasan, "batas_notify")
        self.assertEqual([a for a, _ in await self.audit()], ["tolak:notifications:send"])

    # ── kamus dan field ──
    async def test_kamus_hanya_di_ruang_yang_memasang(self):
        from app.services.txn_nlp import find_best_envelope
        async with self.Session() as db:
            db.add(Envelope(household_id=self.rumah, name="Bahan Baku", budget_amount=D("1")))
            await db.commit()
            env, yakin = await find_best_envelope("beli gula pasir", self.usaha, db, self.pemilik.id)
            self.assertEqual((env.name, env.household_id, yakin), ("Bahan Baku", self.usaha, True))
            env, _ = await find_best_envelope("beli gula pasir", self.rumah, db, self.pemilik.id)
            self.assertIsNone(env)
            env, _ = await find_best_envelope("beli gula pasir", self.usaha, db)    # tanpa user: tanpa kamus plugin
            self.assertIsNone(env)

    async def test_kamus_ruang_sebelum_kamus_plugin(self):
        """R7: urutan kata user → kamus ruang → kamus plugin → kamus kategori; sumber tebakan kamus plugin terpisah."""
        from app.models.models import RuangKamus
        from app.services.txn_nlp import cari_amplop
        async with self.Session() as db:
            t = await cari_amplop("beli gula pasir", self.usaha, db, self.pemilik.id)
            self.assertEqual((t.envelope.name, t.sumber), ("Bahan Baku", "kamus_plugin"))
            op = Envelope(household_id=self.usaha, name="Operasional", budget_amount=D("1"))
            db.add(op)
            await db.flush()
            db.add(RuangKamus(household_id=self.usaha, keyword="gula", envelope_id=op.id, count=2,
                              diajarkan_oleh=self.pemilik.id))
            await db.commit()
            t = await cari_amplop("beli gula pasir", self.usaha, db, self.pemilik.id)
            self.assertEqual((t.envelope.name, t.sumber, t.kali), ("Operasional", "kamus_ruang", 2))

    async def test_periksa_field(self):
        async with self.Session() as db:
            out = await titik.periksa_field(db, self.pemilik, self.usaha, "transaction",
                                            {"contoh": {"proyek": "  Toko A "}})
            self.assertEqual(out, {"contoh": {"proyek": "Toko A"}})
            self.assertEqual(await titik.periksa_field(db, self.pemilik, self.usaha, "transaction", {}), {})
            for kiriman, target in (({"contoh": {"proyek": "x"}}, "transaction"),
                                    ({"contoh": {"proyek": 5}}, "transaction"),
                                    ({"contoh": {"lain": "a"}}, "transaction"),
                                    ({"lain": {"proyek": "a"}}, "transaction"),
                                    ({"contoh": {"proyek": "a"}}, "income")):
                with self.subTest(kiriman=kiriman, target=target), self.assertRaises(titik.siklus.GalatPlugin) as cm:
                    await titik.periksa_field(db, self.pemilik, self.usaha, target, kiriman)
                self.assertEqual(cm.exception.status_code, 422)
            with self.assertRaises(titik.siklus.GalatPlugin):
                await titik.periksa_field(db, self.pemilik, self.rumah, "transaction", {"contoh": {"proyek": "a"}})


if __name__ == "__main__":
    unittest.main()
