"""AI Advisor v2 S17 — chat lengkap (02-aturan.md §6H CHAT & SIM-01).

- Intent "tagihan bulan ini" dan "target {nama}" dari metrics + insight TAG-*/TAB-*.
- SIM-01 "ganti amplop": tombol `sim:{jumlah}:{amplop_id}` saat amplop ditebak; pilihan
  amplop orang lain jatuh ke tebakan (privasi household).
- /tanya, BotCommand, intent yang dipelajari: satu daftar, semua handler terdaftar.

Run: python -m unittest app.tests.test_advisor_chat_s17 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import re
import unittest
import uuid
from datetime import date, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot import advisor_cmd, handlers, help_cmd, intent_learning, nlp_cmd
from app.services.advisor import chat, render
from app.services.advisor.dashboard import susun_dashboard
from app.tests.advisor_v2_fixtures import SnapshotBuilder, contoh_15_okt
from app.tests.test_advisor_chat import USER, FakeSession, analisa_dari, fake_update, jam, polos


def dengan_target() -> SnapshotBuilder:
    b = SnapshotBuilder(date(2026, 10, 15))
    b.envelope("makan", "Makan", classification="needs")
    b.envelope("hobi", "Hobi", classification="wants")
    b.envelope("tab", "Tabungan Liburan", purpose="saving")
    b.envelope("laptop", "Dana Laptop", purpose="saving")
    b.income(10_000_000, alloc={"makan": 3_000_000, "hobi": 1_000_000, "tab": 500_000, "laptop": 0})
    b.txn("makan", 50_000)
    b.goal("tab", "Liburan Bali", 6_000_000, target_date=date(2027, 4, 1))
    b.goal("laptop", "Laptop baru", 2_000_000)
    b.lifetime("tab", 1_500_000)
    b.lifetime("laptop", 2_000_000)
    return b


# ── "tagihan bulan ini" ─────────────────────────────────────────────────
class TagihanTests(unittest.TestCase):
    def setUp(self):
        self.b = contoh_15_okt()
        self.a = analisa_dari(self.b)

    def test_daftar_tagihan_dengan_status_dan_angka_metrics(self):
        m = self.a.ctx.m
        p = polos(chat.jawab_tagihan(self.a))
        self.assertTrue(p.startswith("📆 Tagihan · 27 Sep – 26 Okt"), p)
        self.assertIn(f"Belum dibayar  {render.rp_penuh(m.tagihan_sisa)}", p)       # M4
        self.assertIn("KPR Rumah · Rp1.600.000 · 🔴 telat 9 hari", p)

    def test_chip_dan_insight_sama_dengan_web(self):
        payload, _ = susun_dashboard(self.b.build(), now_local=jam(date(2026, 10, 15)))
        p = polos(chat.jawab_tagihan(self.a))
        self.assertIn(payload["kpi"]["tagihan"]["chip"], p)
        self.assertIn("Lunasi KPR Rumah", p)                                        # TAG-01

    def test_lunas_dan_belum_jatuh_tempo(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("makan", "Makan")
        b.envelope("rumah", "Rumah", purpose="debt")
        b.income(5_000_000, alloc={"makan": 3_000_000, "rumah": 2_000_000})
        b.recurring("rumah", 300_000, "Internet", date(2026, 10, 25), id="net")
        b.recurring("rumah", 150_000, "Listrik", date(2026, 10, 5), id="pln")
        b.txn("rumah", 150_000, on=date(2026, 10, 5), desc="Listrik")
        p = polos(chat.jawab_tagihan(analisa_dari(b)))
        self.assertIn("Listrik · Rp150.000 · ✅ lunas", p)
        self.assertIn("Internet · Rp300.000 · belum · 25 Okt", p)
        self.assertLess(p.index("Listrik"), p.index("Internet"))                   # urut jatuh tempo

    def test_tanpa_tagihan(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("makan", "Makan")
        b.income(1_000_000, alloc={"makan": 1_000_000})
        self.assertIn("Belum ada tagihan", polos(chat.jawab_tagihan(analisa_dari(b))))

    def test_nama_tagihan_di_escape(self):
        b = contoh_15_okt()
        b.snap.recurring[0].description = "<b>KPR</b>"
        self.assertIn("&lt;b&gt;KPR&lt;/b&gt;", chat.jawab_tagihan(analisa_dari(b)))


# ── "target {nama}" ─────────────────────────────────────────────────────
class TargetTests(unittest.TestCase):
    def setUp(self):
        self.a = analisa_dari(dengan_target())

    def test_cari_target_dari_nama_target_atau_amplop(self):
        self.assertEqual(chat.cari_target("target liburan", self.a.ctx)["nama"], "Liburan Bali")
        self.assertEqual(chat.cari_target("progres dana laptop", self.a.ctx)["nama"], "Laptop baru")
        self.assertEqual(chat.cari_target("target Liburan Bali gimana", self.a.ctx)["nama"], "Liburan Bali")
        self.assertIsNone(chat.cari_target("target", self.a.ctx))
        self.assertIsNone(chat.cari_target("progres tabungan", self.a.ctx))

    def test_satu_target_dengan_g4_g5(self):
        g = chat.cari_target("liburan", self.a.ctx)
        p = polos(chat.jawab_target(self.a, "target liburan"))
        self.assertTrue(p.startswith("🎯 Target Liburan Bali"), p)
        self.assertIn("Terkumpul  Rp1.500.000 dari Rp6.000.000", p)
        self.assertIn("25%", p)
        self.assertIn(f"Perlu  {render.rp_penuh(g['butuh_per_bulan'])}/bulan (sampai tenggat)", p)
        self.assertNotIn("Laptop", p)

    def test_semua_target(self):
        p = polos(chat.jawab_target(self.a, "target"))
        self.assertTrue(p.startswith("🎯 Target tabungan"), p)
        self.assertIn("Liburan Bali", p)
        self.assertIn("Laptop baru", p)
        self.assertIn("✅ Target tercapai", p)                                      # laptop 100%

    def test_insight_tab_untuk_target_itu(self):
        ins = [i for i in self.a.sel.semua if i.aturan in {"TAB-02", "TAB-03", "TAB-04", "TAB-05"}]
        self.assertTrue(ins)
        for i in ins:
            g = next(g for g in self.a.ctx.m.target if g["goal_id"] == i.entitas)
            item = chat.insight_target(self.a, g)
            self.assertIsNotNone(item)
            self.assertTrue(item["aturan"].startswith("TAB-"))

    def test_tanpa_target(self):
        a = analisa_dari(contoh_15_okt())
        self.assertIn("Belum ada target tabungan", polos(chat.jawab_target(a, "target")))


# ── SIM-01 ganti amplop ─────────────────────────────────────────────────
def amplop_dua() -> SnapshotBuilder:
    b = SnapshotBuilder(date(2026, 10, 15))
    b.envelope("makan", "Makan", classification="needs")
    b.envelope("hobi", "Hobi", classification="wants")
    b.envelope("tab", "Tabungan", purpose="saving")
    b.income(5_000_000, alloc={"makan": 3_000_000, "hobi": 1_000_000, "tab": 1_000_000})
    for i in range(7):
        b.txn("makan", 80_000, on=date(2026, 10, 15) - timedelta(days=i))
    b.txn("hobi", 20_000)
    return b


class GantiAmplopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.a = analisa_dari(amplop_dua())

    def test_pilihan_amplop_hanya_belanja_tanpa_yang_dipakai(self):
        self.assertEqual([e for e, _ in chat.pilihan_amplop(self.a)], ["makan", "hobi"])
        self.assertEqual([e for e, _ in chat.pilihan_amplop(self.a, kecuali="makan")], ["hobi"])

    def test_parse_sim(self):
        self.assertEqual(advisor_cmd.parse_sim("sim:300000:hobi"), (D(300000), "hobi"))
        for rusak in ("sim:", "sim:x:hobi", "sim:0:hobi", "sim:100:", "t_abc"):
            self.assertIsNone(advisor_cmd.parse_sim(rusak), rusak)

    def test_callback_data_muat_64_byte(self):
        eid = str(uuid.uuid4())
        self.assertLessEqual(len(f"sim:{999_999_999_999}:{eid}".encode()), 64)

    async def test_tombol_saat_amplop_ditebak(self):
        update = fake_update("aman gak beli sepatu 300k")
        with patch.object(advisor_cmd, "analisa", new=AsyncMock(return_value=self.a)):
            self.assertTrue(await advisor_cmd.jawab(update, USER, "aman_beli", amplop_id=None, jumlah=D(300000)))
        markup = update.message.reply_text.await_args.kwargs["reply_markup"]
        data = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertEqual(data, ["sim:300000:hobi"])                    # tebakan = Makan, tombol = lainnya
        self.assertIn("Pilih amplop lain", update.message.reply_text.await_args.args[0])

    async def test_tanpa_tombol_saat_amplop_yakin(self):
        update = fake_update("aman gak beli nasi 30k")
        with patch.object(advisor_cmd, "analisa", new=AsyncMock(return_value=self.a)):
            await advisor_cmd.jawab(update, USER, "aman_beli", amplop_id="makan", jumlah=D(30000))
        self.assertIsNone(update.message.reply_text.await_args.kwargs["reply_markup"])

    async def _klik(self, data):
        update = MagicMock()
        update.callback_query.data = data
        update.callback_query.from_user = SimpleNamespace(id=123)
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(MagicMock())), \
                patch("app.bot.channel.find_chat_user", new=AsyncMock(return_value=USER)), \
                patch.object(advisor_cmd, "analisa", new=AsyncMock(return_value=self.a)):
            await advisor_cmd.handle_sim_callback(update, None)
        return update.callback_query.edit_message_text.await_args

    async def test_pilih_amplop_lain(self):
        args = await self._klik("sim:300000:hobi")
        p = polos(args.args[0])
        self.assertIn("beli Rp300.000 dari 📁 Hobi", p)
        self.assertNotIn("Amplop ditebak", p)
        data = [b.callback_data for row in args.kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertEqual(data, ["sim:300000:makan"])                   # bisa ganti lagi

    async def test_amplop_tak_terlihat_jatuh_ke_tebakan(self):
        p = polos((await self._klik("sim:300000:amplop-pribadi-rina")).args[0])
        self.assertIn("dari 📁 Makan", p)
        self.assertIn("Amplop ditebak", p)

    async def test_callback_rusak_diabaikan(self):
        self.assertIsNone(await self._klik("sim:abc"))


# ── rute, /tanya, daftar perintah ───────────────────────────────────────
class RuteTests(unittest.IsolatedAsyncioTestCase):
    async def _kirim(self, teks, **target):
        update = fake_update(teks)
        mocks = {n: AsyncMock() for n in ("handle_tagihan", "handle_target", "handle_nabung", "handle_sisa")}
        with patch("redis.asyncio.from_url", new=MagicMock(side_effect=Exception("no redis"))), \
                patch.multiple(nlp_cmd, **mocks):
            await handlers.handle_message(update, None)
        return {n: m.await_count for n, m in mocks.items()}

    async def test_tagihan_dan_target(self):
        self.assertEqual((await self._kirim("tagihan bulan ini"))["handle_tagihan"], 1)
        self.assertEqual((await self._kirim("cicilan apa aja"))["handle_tagihan"], 1)
        self.assertEqual((await self._kirim("target liburan"))["handle_target"], 1)
        self.assertEqual((await self._kirim("progres tabungan"))["handle_target"], 1)

    async def test_nabung_tidak_tertangkap_target(self):
        hasil = await self._kirim("harus nyisih berapa buat target laptop")
        self.assertEqual(hasil["handle_target"], 0)
        self.assertEqual(hasil["handle_nabung"], 1)

    async def test_tagihan_di_luar_flag_ke_langganan(self):
        update = fake_update("tagihan bulan ini")
        lama = AsyncMock()
        with patch.object(nlp_cmd, "_user_siap", new=AsyncMock(return_value=USER)), \
                patch.object(advisor_cmd, "analisa", new=AsyncMock(return_value=None)), \
                patch("app.bot.recurring_cmd.cmd_langganan", new=lama):
            await nlp_cmd.handle_tagihan(update, None)
        lama.assert_awaited_once()

    async def test_target_v2_memakai_teks_pesan(self):
        update = fake_update("/target liburan")
        jawab = AsyncMock(return_value=True)
        with patch.object(nlp_cmd, "_user_siap", new=AsyncMock(return_value=USER)), \
                patch.object(advisor_cmd, "jawab", new=jawab):
            await nlp_cmd.handle_target(update, None)
        self.assertEqual(jawab.await_args.args[2], "target")
        self.assertEqual(jawab.await_args.kwargs["teks"], "/target liburan")

    async def test_kenapa_boros_dari_tombol_memakai_teks_tetap(self):
        update = fake_update("Mau tanya apa?")                          # teks pesan bot, bukan user
        jawab = AsyncMock(return_value=True)
        with patch.object(nlp_cmd, "_user_siap", new=AsyncMock(return_value=USER)), \
                patch.object(advisor_cmd, "jawab", new=jawab):
            await nlp_cmd.handle_kenapa_boros(update, None)
        self.assertEqual(jawab.await_args.kwargs["teks"], "kenapa boros")

    async def test_tanya_tombol_menjalankan_intent(self):
        update = fake_update("/tanya")
        await help_cmd.cmd_tanya(update, None)
        markup = update.message.reply_text.await_args.kwargs["reply_markup"]
        data = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("tanya:tagihan", data)
        h = AsyncMock()
        q = MagicMock()
        q.callback_query.data = "tanya:tagihan"
        q.callback_query.answer = AsyncMock()
        with patch.object(intent_learning, "intent_handlers", return_value={"tagihan": h}):
            await help_cmd.handle_tanya_callback(q, None)
        h.assert_awaited_once()

    def test_daftar_satu_sumber(self):
        handler = intent_learning.intent_handlers()
        self.assertLessEqual({k for k, _ in help_cmd.PERTANYAAN}, set(handler))
        self.assertLessEqual(set(intent_learning.INTENTS), set(handler))
        perintah = handlers.bot_commands()
        for nama, ket in help_cmd.BOT_COMMANDS:
            self.assertIn(nama, perintah)
            self.assertTrue(re.fullmatch(r"[a-z0-9_]{1,32}", nama))
            self.assertLessEqual(len(ket), 256)
        pola = [p for p, _ in handlers.bot_callbacks()]
        for data in ("sim:1000:makan", "tanya:sisa"):
            self.assertEqual(sum(bool(re.match(p, data)) for p in pola), 1, data)


if __name__ == "__main__":
    unittest.main()
