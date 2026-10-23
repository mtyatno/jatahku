"""AI Advisor v2 S9 — paritas bot & ringkasan (02-aturan.md §6H, §7 "Chat web & Telegram", §13).

- Paritas §13: dari snapshot yang sama, KPI web (`susun_dashboard`), chat "sisa", `/status`,
  dan ringkasan harian memakai angka yang identik.
- Skenario 6: hari terakhir periode tidak crash (v2 dan jawaban lama).
- Intent "kenapa boros", "kenapa {amplop} habis", "kenapa … hari ini", "aman beli" (SIM-01).
- Bot: jalur v2 hanya untuk user di flag; gagal → jawaban lama. Ringkasan v2 terkirim.

Run: python -m unittest app.tests.test_advisor_chat -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import re
import unittest
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from sqlalchemy.orm import configure_mappers

from app.bot import advisor_cmd, checkin_cmd, handlers, nlp_cmd
from app.services import summary
from app.services.advisor import chat, render
from app.services.advisor.dashboard import susun_dashboard
from app.services.advisor.metrics import SIMULASI_TXN_ID, compute_metrics, simulasi_belanja
from app.services.advisor.render import rp_penuh
from app.tests.advisor_v2_fixtures import SnapshotBuilder, contoh_15_okt
from app.tests.fakes import FakeResult

configure_mappers()  # jangan jatuh di event loop tes (asyncio debug: "took 0.1xx seconds")
JKT = ZoneInfo("Asia/Jakarta")


def jam(t: date, h=8) -> datetime:
    return datetime(t.year, t.month, t.day, h, tzinfo=JKT)


def analisa_dari(b: SnapshotBuilder, h=8) -> chat.Analisa:
    snap = b.build()
    return chat.analisa_snapshot(snap, now_local=jam(snap.today, h))


def polos(teks: str) -> str:
    """HTML Telegram → teks biasa untuk dibandingkan."""
    return re.sub(r"<[^>]+>", "", teks).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def hari_terakhir() -> SnapshotBuilder:
    """Periode 27 Sep – 26 Okt, hari ini 26 Okt (r = 0)."""
    b = SnapshotBuilder(date(2026, 10, 26), payday_day=27)
    b.envelope("makan", "Makan", classification="needs")
    b.envelope("hobi", "Hobi", classification="wants")
    b.income(3_000_000, alloc={"makan": 2_000_000, "hobi": 1_000_000})
    for i in range(29):
        b.txn("makan", 60_000, on=b.ps + timedelta(days=i))
    b.txn("hobi", 100_000, on=date(2026, 10, 26))
    return b


# ── paritas §13 ─────────────────────────────────────────────────────────
class ParitasTests(unittest.TestCase):
    def setUp(self):
        self.b = contoh_15_okt()
        self.a = analisa_dari(self.b)

    def test_angka_identik_di_web_chat_status_dan_ringkasan(self):
        payload, _ = susun_dashboard(self.b.build(), now_local=jam(date(2026, 10, 15)))
        m = payload["metrics"]
        blok = render.blok_angka(self.a.ctx)
        teks = {
            "sisa": chat.jawab_sisa(self.a),
            "status": chat.jawab_status(self.a),
            "ringkasan": chat.ringkasan_harian(self.a),
        }
        for nama, isi in teks.items():
            for baris in blok:
                self.assertIn(baris, isi, nama)
            p = polos(isi)
            self.assertIn(f"Sisa bebas  {rp_penuh(m['sisa_bebas'])}", p, nama)
            self.assertIn(f"Jaga {m['sisa_hari']} hari ke depan  {rp_penuh(m['j1'])}/hari", p, nama)
            self.assertIn(f"Jatah hari ini  {rp_penuh(m['j0'])} · belanja {rp_penuh(m['belanja_hari_ini'])}", p, nama)
            self.assertIn(f"Dana belanja  {rp_penuh(m['dana_belanja'])}", p, nama)
            self.assertIn(f"Terpakai  {rp_penuh(m['terpakai'])}", p, nama)

    def test_angka_contoh_12(self):
        p = polos(chat.jawab_sisa(self.a))
        self.assertIn("Dana belanja  Rp11.285.200", p)
        self.assertIn("Terpakai  Rp8.000.000", p)
        self.assertIn("Disisihkan tagihan  Rp1.600.000", p)
        self.assertIn("Sisa bebas  Rp1.685.200", p)       # 11.285.200 − 8.000.000 − 1.600.000
        self.assertIn("Jaga 11 hari ke depan  Rp153.200/hari", p)
        self.assertIn("Jatah hari ini  Rp165.100", p)

    def test_chip_dan_item_sama_dengan_web(self):
        payload, _ = susun_dashboard(self.b.build(), now_local=jam(date(2026, 10, 15)))
        status = polos(chat.jawab_status(self.a))
        self.assertIn(payload["kpi"]["jatah"]["chip"], status)
        self.assertIn(payload["advisor"]["items"][0]["judul"], status)
        sisa = polos(chat.jawab_sisa(self.a))
        self.assertIn(payload["kpi"]["sisa_bebas"]["chip"], sisa)
        ringkasan = polos(chat.ringkasan_harian(self.a))
        self.assertIn(payload["kpi"]["jatah"]["chip"], ringkasan)
        self.assertIn(payload["advisor"]["items"][0]["judul"], ringkasan)

    def test_limit_harian_dan_proyeksi_dari_metrics(self):
        m = self.a.ctx.m
        limit = polos(chat.jawab_limit_harian(self.a))
        self.assertIn(f"Jatah hari ini sejak pagi  {rp_penuh(m.j0)}", limit)
        self.assertIn(f"Lewat jatah  {rp_penuh(m.belanja_hari_ini - m.j0)}", limit)
        self.assertIn(f"Makan & Jajan · {rp_penuh(self.a.sel.batas['belanja'])}", limit)  # bebas_setelah_rencana
        proyeksi = polos(chat.jawab_proyeksi(self.a))
        self.assertIn("Perkiraan habis ±24 Okt", proyeksi)
        self.assertIn(f"Rata-rata 7 hari terakhir  {rp_penuh(m.laju_total)}/hari", proyeksi)

    def test_hari_ini_memakai_t5(self):
        p = polos(chat.jawab_hari_ini(self.a))
        self.assertIn("Belanja harian  Rp297.100 dari jatah Rp165.100", p)
        self.assertIn("Lewat jatah Rp132.000", p)

    def test_nama_amplop_di_escape(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("k", "Kopi & <Teh>")
        b.fund("k", 500_000)
        b.txn("k", 20_000)
        a = analisa_dari(b)
        for teks in (chat.jawab_sisa(a), chat.jawab_status(a), chat.jawab_hari_ini(a), chat.ringkasan_harian(a)):
            self.assertIn("Kopi &amp; &lt;Teh&gt;", teks)
            self.assertNotIn("<Teh>", teks)


# ── skenario 6: hari terakhir ───────────────────────────────────────────
class HariTerakhirTests(unittest.TestCase):
    def test_semua_jawaban_tidak_crash(self):
        a = analisa_dari(hari_terakhir())
        self.assertEqual(a.ctx.m.sisa_hari, 0)
        for f in (chat.jawab_status, chat.jawab_sisa, chat.jawab_limit_harian, chat.jawab_proyeksi,
                  chat.jawab_hari_ini, chat.jawab_kenapa_boros, chat.jawab_kenapa_hari_ini, chat.ringkasan_harian):
            self.assertTrue(f(a), f.__name__)
        self.assertTrue(chat.ringkasan_mingguan(a, {"label": "20–26 Okt", "total": D(0), "n": 0, "bagian": []}))
        self.assertTrue(chat.jawab_aman_beli(a, "hobi", 50_000))

    def test_j0_sama_dengan_sisa(self):
        a = analisa_dari(hari_terakhir())
        m = a.ctx.m
        self.assertIsNone(m.j1)
        limit = polos(chat.jawab_limit_harian(a))
        self.assertIn("hari terakhir periode", limit)
        # Fase 5: J0 = min(sisa harian awal hari, pagar ideal), dibulatkan ke bawah Rp100
        self.assertEqual(m.j0, min((m.sisa_bebas_harian + m.belanja_hari_ini) // 100 * 100, m.jatah_ideal))
        self.assertIn("Hari terakhir periode", polos(chat.jawab_sisa(a)))

    def test_jawaban_lama_tidak_membagi_nol(self):
        user = SimpleNamespace(payday_day=1)
        with patch("app.core.period.get_period_info",
                   return_value={"days_remaining": 0, "days_used": 31}):
            self.assertEqual(nlp_cmd._period_days(user), (1, 31))


class AwalPeriodeTests(unittest.TestCase):
    def test_proyeksi_belum_ada_di_hari_1_2(self):
        b = SnapshotBuilder(date(2026, 10, 2))
        b.envelope("makan", "Makan")
        b.fund("makan", 1_000_000)
        b.txn("makan", 50_000)
        p = polos(chat.jawab_proyeksi(analisa_dari(b)))
        self.assertIn("Belum ada proyeksi", p)
        self.assertIn("Proyeksi muncul mulai hari ke-3", p)


# ── "kenapa …" (§6H CHAT) ───────────────────────────────────────────────
class KenapaTests(unittest.TestCase):
    def setUp(self):
        self.a = analisa_dari(contoh_15_okt())

    def test_kenapa_boros_menampilkan_rincian_per01(self):
        p = polos(chat.jawab_kenapa(self.a, "kenapa boros?"))
        self.assertTrue(p.startswith("🟡 Rem belanja harian ke Rp153 rb"), p)
        self.assertIn("Penyumbang: Makan & Jajan", p)          # penyumbang M12
        self.assertIn("Sisa bebas harian: Rp1.685.200 ÷ 11 hari = Rp153.200/hari", p)
        self.assertIn("Rincian:", p)                          # AMP-03 & HAR-01 yang diserap
        self.assertIn("Lunasi KPR Rumah", p)                  # item lain di daftar

    def test_chip_tanya_web(self):
        b = contoh_15_okt()
        b.snap.envelopes[0].name = "Belanja"                # amplop bernama "Belanja"
        a = analisa_dari(b)
        self.assertIn("Rem belanja harian", polos(chat.jawab_kenapa(a, "Kenapa dana belanja kurang?")))
        hari = polos(chat.jawab_kenapa(a, "Kenapa belanja hari ini lewat jatah?"))
        self.assertTrue(hari.startswith("🔴 Belanja hari ini 1,8× jatah"), hari)
        self.assertIn("Jatah hari ini sejak pagi: Rp165.100", hari)

    def test_kenapa_amplop_habis(self):
        p = polos(chat.jawab_kenapa(self.a, "kenapa makan cepet habis"))
        self.assertTrue(p.startswith("🟡 Makan & Jajan: maksimal"), p)   # AMP-03 (diserap PER-01 di daftar)
        self.assertIn("Perlu sampai 26 Okt", p)
        tagihan = polos(chat.jawab_kenapa(self.a, "kok tagihan & cicilan habis?"))
        self.assertTrue(tagihan.startswith("🔴 Lunasi KPR Rumah"), tagihan)  # TAG-01 menyerap AMP-01

    def test_kenapa_amplop_yang_aman(self):
        b = contoh_15_okt()
        b.envelope("hobi", "Hobi", classification="wants")
        b.fund("hobi", 500_000, on=b.ps)
        b.txn("hobi", 10_000, on=date(2026, 10, 10))
        p = polos(chat.jawab_kenapa(analisa_dari(b), "kenapa hobi habis"))
        self.assertTrue(p.startswith("🟢 Hobi masih aman"), p)
        self.assertIn("Sisa bebas Rp490.000 dari dana Rp500.000", p)

    def test_cari_amplop(self):
        ctx = self.a.ctx
        self.assertEqual(chat.cari_amplop("kenapa makan & jajan habis", ctx), "belanja")
        self.assertEqual(chat.cari_amplop("kenapa jajan habis", ctx), "belanja")
        self.assertEqual(chat.cari_amplop("KENAPA CICILAN MINUS", ctx), "tagihan")
        self.assertIsNone(chat.cari_amplop("kenapa boros", ctx))
        self.assertIsNone(chat.cari_amplop("kenapa dana belanja kurang", ctx))

    def test_regex_intent(self):
        for t in ("kenapa boros?", "kok boros banget", "kenapa makan habis?", "Kenapa dana belanja kurang?",
                  "Kenapa belanja hari ini lewat jatah?", "knp jajan cepet abis"):
            self.assertTrue(nlp_cmd.is_kenapa(t), t)
        for t in ("kopi 35k", "sisa berapa", "kapan habis"):
            self.assertFalse(nlp_cmd.is_kenapa(t), t)


# ── SIM-01 "aman beli?" ─────────────────────────────────────────────────
class AmanBeliTests(unittest.TestCase):
    def setUp(self):
        self.b = contoh_15_okt()
        self.a = analisa_dari(self.b)

    def test_simulasi_memakai_rumus_metrics(self):
        snap = self.a.ctx.snap
        n = len(snap.transactions)
        m2 = simulasi_belanja(snap, "belanja", 100_000)
        self.assertEqual(len(snap.transactions), n)                     # snapshot asli tidak berubah
        self.assertEqual(m2.sisa_bebas, self.a.ctx.m.sisa_bebas - 100_000)
        self.assertEqual(m2.j1, (m2.sisa_bebas / 11) // 100 * 100)
        self.assertEqual(m2.jenis_transaksi[SIMULASI_TXN_ID], "variabel")
        self.assertEqual(compute_metrics(snap).sisa_bebas, self.a.ctx.m.sisa_bebas)

    def test_aman(self):
        sim = chat.simulasi(self.a, "belanja", 100_000)
        self.assertEqual(sim["hasil"], "aman")                          # J1 153.200 → 144.100 (94%)
        p = polos(chat.jawab_aman_beli(self.a, "belanja", 100_000))
        self.assertTrue(p.startswith("✅ Aman · beli Rp100.000 dari 📁 Makan & Jajan"), p)
        self.assertIn("Aman 11 hari ke depan  Rp153.200 → Rp144.100/hari", p)

    def test_jatah_harian_turun(self):
        self.assertEqual(chat.simulasi(self.a, "belanja", 300_000)["hasil"], "turun")
        self.assertTrue(polos(chat.jawab_aman_beli(self.a, "belanja", 300_000)).startswith("⚠️"))

    def test_tidak_cukup(self):
        sim = chat.simulasi(self.a, "belanja", 2_000_000)
        self.assertEqual(sim["hasil"], "kurang")
        p = polos(chat.jawab_aman_beli(self.a, "belanja", 2_000_000))
        self.assertTrue(p.startswith("❌ Belum cukup"), p)
        self.assertIn("habis sekarang", p)

    def test_amplop_tidak_yakin_ditebak(self):
        p = polos(chat.jawab_aman_beli(self.a, None, 50_000))
        self.assertIn("Makan & Jajan", p)                                # porsi 7 hari terbesar
        self.assertIn("Amplop ditebak", p)

    def test_tanpa_amplop_belanja(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("tab", "Tabungan", purpose="saving")
        self.assertIsNone(chat.jawab_aman_beli(analisa_dari(b), None, 50_000))


# ── bot ─────────────────────────────────────────────────────────────────
USER = SimpleNamespace(id=uuid.uuid4(), payday_day=27, timezone=None)


def fake_update(text):
    update = MagicMock()
    update.effective_user = SimpleNamespace(id=123, first_name="Tes")
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


class BotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.a = analisa_dari(contoh_15_okt())

    async def test_jawab_false_di_luar_flag(self):
        update = fake_update("sisa")
        with patch.object(advisor_cmd, "analisa", new=AsyncMock(return_value=None)):
            self.assertFalse(await advisor_cmd.jawab(update, USER, "sisa"))
        update.message.reply_text.assert_not_awaited()

    async def test_jawab_gagal_kembali_ke_jawaban_lama(self):
        update = fake_update("sisa")
        with patch.object(advisor_cmd, "analisa", new=AsyncMock(return_value=self.a)), \
                patch.object(chat, "jawab_sisa", side_effect=RuntimeError("x")), \
                patch.object(advisor_cmd.logger, "exception"):
            self.assertFalse(await advisor_cmd.jawab(update, USER, "sisa"))
        update.message.reply_text.assert_not_awaited()

    async def test_muat_none_bila_flag_mati(self):
        db = MagicMock()
        self.assertIsNone(await chat.muat(USER, db, pengaturan={"advisor_v2_users": "orang-lain"}))
        self.assertIsNone(await chat.muat(USER, db, pengaturan={}))

    async def test_handle_sisa_memakai_v2(self):
        update = fake_update("sisa berapa")
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(MagicMock())), \
                patch.object(nlp_cmd, "_get_user_envelopes", new=AsyncMock(return_value=(USER, uuid.uuid4(), []))), \
                patch.object(advisor_cmd, "analisa", new=AsyncMock(return_value=self.a)):
            await nlp_cmd.handle_sisa(update, None)
        update.message.reply_text.assert_awaited_once()
        args, kwargs = update.message.reply_text.await_args
        self.assertEqual(kwargs["parse_mode"], "HTML")
        self.assertIn("Sisa bebas  <b>Rp1.685.200</b>", args[0])

    async def test_cmd_status_v2_dengan_streak(self):
        update = fake_update("/status")
        env = {"envelope": SimpleNamespace(id=uuid.uuid4()), "allocated": D(1), "spent": D(0), "free": D(1)}
        with patch.object(handlers, "AsyncSessionLocal", new=lambda: FakeSession(MagicMock())), \
                patch.object(handlers, "get_or_create_user", new=AsyncMock(return_value=USER)), \
                patch.object(handlers, "get_household_id", new=AsyncMock(return_value=uuid.uuid4())), \
                patch.object(handlers, "get_envelopes_with_spent", new=AsyncMock(return_value=[env])), \
                patch.object(handlers, "_status_streak_lines", new=AsyncMock(return_value=["🔥 Streak <b>3 hari</b>"])), \
                patch.object(advisor_cmd, "analisa", new=AsyncMock(return_value=self.a)):
            await handlers.cmd_status(update, None)
        teks = update.message.reply_text.await_args.args[0]
        self.assertIn("📊 Budget · 27 Sep – 26 Okt", teks)
        self.assertIn("Lunasi KPR Rumah", teks)             # item #1 daftar
        self.assertTrue(teks.endswith("🔥 Streak <b>3 hari</b>"))

    async def test_whatif_tidak_yakin_dikirim_tanpa_amplop(self):
        update = fake_update("kalau beli sepatu 300k aman gak")
        envelope = SimpleNamespace(id=uuid.uuid4(), name="Hobi", emoji="🎮")
        jawab = AsyncMock(return_value=True)
        get_envs = AsyncMock(return_value=[])
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(MagicMock())), \
                patch.object(checkin_cmd, "get_or_create_user", new=AsyncMock(return_value=USER)), \
                patch.object(checkin_cmd, "_is_setup_complete", new=AsyncMock(return_value=(True, "ok"))), \
                patch.object(checkin_cmd, "get_household_id", new=AsyncMock(return_value=uuid.uuid4())), \
                patch.object(checkin_cmd, "find_best_envelope", new=AsyncMock(return_value=(envelope, False))), \
                patch.object(checkin_cmd, "get_envelopes_with_spent", new=get_envs), \
                patch.object(advisor_cmd, "jawab", new=jawab):
            await checkin_cmd.handle_whatif(update, None)
        self.assertIsNone(jawab.await_args.kwargs["amplop_id"])
        self.assertEqual(jawab.await_args.kwargs["jumlah"], D("300000"))
        self.assertEqual(get_envs.await_args.kwargs["payday_day"], 27)   # periode gajian, bukan bulan kalender

    async def test_kenapa_dirutekan_ke_jawaban_kenapa(self):
        update = fake_update("kenapa boros?")
        emosi = AsyncMock()
        with patch("redis.asyncio.from_url", new=MagicMock(side_effect=Exception("no redis"))), \
                patch.object(nlp_cmd, "handle_emosi", new=emosi):
            await handlers.handle_message(update, None)
        emosi.assert_awaited_once()

    async def test_handle_emosi_v2_mengirim_teks_pertanyaan(self):
        update = fake_update("kenapa makan cepet habis")
        jawab = AsyncMock(return_value=True)
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(MagicMock())), \
                patch.object(nlp_cmd, "_get_user_envelopes", new=AsyncMock(return_value=(USER, uuid.uuid4(), []))), \
                patch.object(advisor_cmd, "jawab", new=jawab):
            await nlp_cmd.handle_emosi(update, None)
        self.assertEqual(jawab.await_args.args[2], "kenapa")
        self.assertEqual(jawab.await_args.kwargs["teks"], "kenapa makan cepet habis")

    async def test_limit_harian_lama_hari_terakhir_tidak_crash(self):
        update = fake_update("limit harian")
        env = {"envelope": SimpleNamespace(id=uuid.uuid4(), name="Makan", emoji="🍜"), "free": D(90_000),
               "spent": D(0), "allocated": D(90_000)}
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(MagicMock())), \
                patch.object(nlp_cmd, "_get_user_envelopes", new=AsyncMock(return_value=(USER, uuid.uuid4(), [env]))), \
                patch.object(advisor_cmd, "analisa", new=AsyncMock(return_value=None)), \
                patch("app.core.period.get_period_info", return_value={"days_remaining": 0, "days_used": 30}):
            await nlp_cmd.handle_limit_harian(update, None)
        self.assertIn("Rp90rb", update.message.reply_text.await_args.args[0])


# ── ringkasan ───────────────────────────────────────────────────────────
class RingkasanV2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.a = analisa_dari(contoh_15_okt())
        self.user = SimpleNamespace(id=uuid.uuid4(), telegram_id="777", payday_day=27, timezone=None)

    async def kirim(self, sender, rows):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[FakeResult(rows=[self.user]), FakeResult(uuid.uuid4()), *rows])
        db.get = AsyncMock(return_value=None)
        bot_cls = MagicMock()
        bot_cls.return_value.send_message = AsyncMock()
        with patch.object(summary, "AsyncSessionLocal", new=lambda: FakeSession(db)), \
                patch.object(summary, "Bot", new=bot_cls), \
                patch.object(summary.settings, "TELEGRAM_BOT_TOKEN", "token"), \
                patch.object(summary, "_pengaturan_advisor", new=AsyncMock(return_value={"advisor_v2_users": "*"})), \
                patch.object(summary, "_analisa_v2", new=AsyncMock(return_value=self.a)), \
                patch.object(summary.logger, "error") as log_error:
            await sender(user_id=self.user.id)
        log_error.assert_not_called()
        kw = bot_cls.return_value.send_message.await_args.kwargs
        self.assertEqual(kw["parse_mode"], "HTML")
        return kw["text"]

    async def test_harian(self):
        teks = await self.kirim(summary.send_daily_summary, [])
        self.assertEqual(teks, chat.ringkasan_harian(self.a))
        p = polos(teks)
        self.assertIn("1,8× jatah", p)                         # chip Jatah hari ini
        self.assertIn("Lunasi KPR Rumah", p)                   # item #1 daftar
        self.assertIn("Sisa bebas  Rp1.685.200", p)

    async def test_mingguan(self):
        txn = SimpleNamespace(envelope_id="belanja", amount=D("297100"), transaction_date=date(2026, 10, 15))
        teks = await self.kirim(summary.send_weekly_summary, [FakeResult(rows=[txn])])
        p = polos(teks)
        self.assertIn("Total keluar Rp297.100 (1 transaksi)", p)
        self.assertIn("Makan Rp297 rb", p)
        self.assertIn("hari ke-19 dari 30", p)
        self.assertIn("Habis ±24 Okt", p)                      # chip Sisa bebas
        self.assertIn("1/7 hari", p)

    async def test_analisa_v2_flag_mati_tanpa_query(self):
        sesi = MagicMock(side_effect=AssertionError("tidak boleh membuka sesi"))
        with patch.object(summary, "AsyncSessionLocal", new=sesi):
            self.assertIsNone(await summary._analisa_v2(self.user, {"advisor_v2_users": "orang-lain"}))
            self.assertIsNone(await summary._analisa_v2(self.user, {}))

    async def test_analisa_v2_gagal_kembali_ke_ringkasan_lama(self):
        with patch.object(summary, "AsyncSessionLocal", new=lambda: FakeSession(MagicMock())), \
                patch.object(chat, "muat", new=AsyncMock(side_effect=RuntimeError("db"))), \
                patch.object(summary.logger, "error") as log_error:
            self.assertIsNone(await summary._analisa_v2(self.user, {"advisor_v2_users": "*"}))
        log_error.assert_called_once()

    def test_struktural_hanya_amp_tab(self):
        b = contoh_15_okt()
        a = analisa_dari(b)
        ins = chat.struktural(a)
        self.assertTrue(ins is None or ins["aturan"] in chat.STRUKTURAL)


if __name__ == "__main__":
    unittest.main()


# ── paritas end-to-end: database → web, chat, Telegram, ringkasan ───────
@unittest.skipUnless(importlib.util.find_spec("aiosqlite") is not None, "butuh aiosqlite")
class ParitasDatabaseTests(unittest.IsolatedAsyncioTestCase):
    """Dari data yang sama di database (SQLite), GET /advisor/dashboard, "sisa" di chat web,
    /status Telegram, dan ringkasan harian memakai angka identik (02-aturan.md §13)."""

    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.core.database import Base
        from app.models.models import (
            Allocation, AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, Income, Transaction, User,
        )
        self.engine = create_async_engine("sqlite+aiosqlite://")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        for p in (patch("redis.asyncio.from_url", side_effect=Exception("tanpa redis")),
                  patch("app.services.advisor.advisor_cache.logger")):   # cache/dismiss gagal → tetap jalan
            p.start()
            self.addCleanup(p.stop)
        today = datetime.now(JKT).date()
        async with self.Session() as db:
            me = User(name="Saya", payday_day=1, timezone="Asia/Jakarta")
            rina = User(name="Rina", payday_day=1)
            hh = Household(name="Rumah")
            db.add_all([me, rina, hh])
            await db.flush()
            db.add_all([HouseholdMember(user_id=me.id, household_id=hh.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=rina.id, household_id=hh.id, role=HouseholdRole.member)])
            makan = Envelope(household_id=hh.id, name="Makan", classification="needs", budget_amount=D("0"))
            rahasia = Envelope(household_id=hh.id, name="Rahasia Rina", owner_id=rina.id, budget_amount=D("0"))
            db.add_all([makan, rahasia])
            await db.flush()
            gaji = Income(household_id=hh.id, user_id=me.id, amount=D("3500000"), description="Gaji",
                          income_date=today)
            db.add(gaji)
            await db.flush()
            db.add_all([Allocation(income_id=gaji.id, envelope_id=makan.id, amount=D("3000000")),
                        Allocation(income_id=gaji.id, envelope_id=rahasia.id, amount=D("500000")),
                        Transaction(envelope_id=makan.id, user_id=me.id, amount=D("45000"), description="nasi",
                                    transaction_date=today),
                        Transaction(envelope_id=rahasia.id, user_id=rina.id, amount=D("99000"),
                                    description="kado", transaction_date=today),
                        AppSetting(key="advisor_v2_users", value=str(me.id))])
            await db.commit()
            self.me = me

    async def test_angka_identik(self):
        from app.api.routes import advisor as advisor_routes
        async with self.Session() as db:
            web = await advisor_routes.advisor_dashboard(user=self.me, db=db)
        async with self.Session() as db:
            a = await chat.muat(self.me, db)
        self.assertIsNotNone(a)
        m = web["metrics"]
        teks = {"sisa": chat.jawab_sisa(a), "status": chat.jawab_status(a), "ringkasan": chat.ringkasan_harian(a)}
        for nama, isi in teks.items():
            p = polos(isi)
            self.assertIn(f"Sisa bebas  {rp_penuh(m['sisa_bebas'])}", p, nama)
            self.assertIn(f"Jatah hari ini  {rp_penuh(m['j0'])} · belanja {rp_penuh(m['belanja_hari_ini'])}", p, nama)
            self.assertIn(f"Dana belanja  {rp_penuh(m['dana_belanja'])}", p, nama)
            self.assertNotIn("Rahasia", p, nama)                   # skenario 7: amplop pribadi anggota lain
            self.assertNotIn("kado", p, nama)
        self.assertEqual(m["dana_belanja"], 3_000_000)
        self.assertEqual(m["belanja_hari_ini"], 45_000)
        self.assertIn("nasi", polos(chat.jawab_hari_ini(a)))
