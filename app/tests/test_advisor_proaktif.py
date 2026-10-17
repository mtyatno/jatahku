"""AI Advisor v2 S16 — notifikasi proaktif (02-aturan.md §9 "Notifikasi proaktif", §7 ringkasan).

- Maks 1 kiriman advisor per hari (item #1), hal yang sama ≤ 2 permukaan dan tidak dua kali ke
  permukaan yang sama; tagihan = satu hal per langganan (TAG-01/02/03 + pengingat jatuh tempo).
- Jam tenang 21.00–07.00 untuk peringatan; pengingat tagihan mulai 07.00 lokal.
- Status dismiss terbaru (#91): disembunyikan → tidak dikirim; dimunculkan lagi → boleh lagi.
- Pengingat tagihan patuh `subscription_due_tg`/`_web` dan tidak berulang tiap hari.
- `send_budget_warning` dari insight danger, patuh `budget_warning_tg`/`_web`.
- Ringkasan harian ke lonceng web (`daily_summary_web`) mencatat item #1 di buku.

Run: python -m unittest app.tests.test_advisor_proaktif -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import fnmatch
import unittest
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from sqlalchemy.orm import configure_mappers

from app.models.models import NotificationType, RecurringFrequency
from app.services import notification_service, recurring_processor, summary
from app.services.advisor import chat, proaktif, render
from app.tests.advisor_v2_fixtures import contoh_15_okt
from app.tests.fakes import FakeResult

configure_mappers()
JKT = ZoneInfo("Asia/Jakarta")
HARI = date(2026, 10, 15)


def jam(h=9, m=0, d=HARI) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=JKT)


def analisa(dismiss=None, h=9):
    snap = contoh_15_okt().build()
    return chat.analisa_snapshot(snap, now_local=jam(h), dismiss=dismiss)


DISMISS_KPR = {"TAG-01:kpr": {"pilihan": "nanti", "tone": "danger", "rupiah": "0"}}


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    async def hgetall(self, k):
        return {f.encode(): v.encode() for f, v in self.store.get(k, {}).items()}

    async def hset(self, k, mapping):
        self.store.setdefault(k, {}).update(mapping)

    async def expire(self, k, ttl):
        return True

    async def scan_iter(self, match="*", count=None):
        for k in list(self.store):
            if fnmatch.fnmatchcase(k, match):
                yield k

    async def mget(self, keys):
        return [None for _ in keys]

    async def aclose(self):
        pass


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def user(telegram_id="777"):
    return SimpleNamespace(id=uuid.uuid4(), telegram_id=telegram_id, timezone="Asia/Jakarta", payday_day=27)


def prefs(**kw):
    base = dict(budget_warning_tg=True, budget_warning_web=True, subscription_due_tg=True,
                subscription_due_web=True)
    base.update(kw)
    return SimpleNamespace(**base)


# ── murni ───────────────────────────────────────────────────────────────
class MurniTests(unittest.TestCase):
    def test_hal_tagihan_per_langganan(self):
        self.assertEqual(proaktif.hal("TAG-01:kpr"), "TAG:kpr")
        self.assertEqual(proaktif.hal("TAG-02:kpr"), proaktif.hal_tagihan("kpr"))
        self.assertEqual(proaktif.hal("PER-01:2026-09-27"), "PER-01:2026-09-27")

    def test_jam_tenang(self):
        self.assertTrue(proaktif.jam_tenang(jam(21)))
        self.assertTrue(proaktif.jam_tenang(jam(23, 30)))
        self.assertTrue(proaktif.jam_tenang(jam(6, 59)))
        self.assertFalse(proaktif.jam_tenang(jam(7)))
        self.assertFalse(proaktif.jam_tenang(jam(20, 59)))

    def test_maks_dua_permukaan_dan_tidak_dobel(self):
        buku = proaktif.Buku(tanggal=HARI)
        self.assertEqual(buku.permukaan_bebas("TAG-01:kpr", ("telegram", "web", "chat")), ["telegram", "web"])
        buku.hal["TAG:kpr"] = {"telegram"}
        self.assertEqual(buku.permukaan_bebas("TAG-02:kpr", ("telegram", "web", "chat")), ["web"])
        buku.hal["TAG:kpr"] = {"telegram", "web"}
        self.assertEqual(buku.permukaan_bebas("TAG-01:kpr", ("chat",)), [])
        self.assertEqual(buku.permukaan_bebas("PER-01:x", ("chat",)), ["chat"])

    def test_kuota_satu_per_hari(self):
        buku = proaktif.Buku(tanggal=HARI, advisor="TAG:kpr")
        self.assertTrue(buku.kuota_untuk("TAG-01:kpr"))
        self.assertFalse(buku.kuota_untuk("PER-01:2026-09-27"))

    def test_peringatan_hanya_item_1_danger(self):
        a = analisa()
        self.assertEqual(proaktif.pilih_peringatan(a, proaktif.Buku(tanggal=HARI)).id, "TAG-01:kpr")
        # TAG-01 disembunyikan → item #1 PER-01 (warn) → bukan peringatan.
        a2 = analisa(DISMISS_KPR)
        self.assertEqual(a2.sel.daftar[0].tone, "warn")
        self.assertIsNone(proaktif.pilih_peringatan(a2, proaktif.Buku(tanggal=HARI)))
        # Kuota hari ini sudah dipakai hal lain.
        self.assertIsNone(proaktif.pilih_peringatan(a, proaktif.Buku(tanggal=HARI, advisor="PER-01:2026-09-27")))

    def test_chat_mengikuti_kiriman_hari_ini_dan_dismiss_terbaru(self):
        buku = proaktif.Buku(tanggal=HARI, advisor="TAG:kpr")
        self.assertEqual(proaktif.pilih_chat(analisa(), buku).id, "TAG-01:kpr")
        # Disembunyikan sesudah dikirim (#91): chat tidak menampilkannya, dan tidak mengganti item lain.
        self.assertIsNone(proaktif.pilih_chat(analisa(DISMISS_KPR), buku))
        # Belum ada kiriman: item #1 danger/warn.
        self.assertEqual(proaktif.pilih_chat(analisa(DISMISS_KPR), proaktif.Buku(tanggal=HARI)).aturan, "PER-01")

    def test_teks_notifikasi_dari_render(self):
        a = analisa()
        item = chat._r(a, a.sel.daftar[0])
        judul, isi, html = render.notifikasi_insight(item)
        self.assertTrue(judul.startswith("🔴 "))
        self.assertIn(item["judul"], judul)
        self.assertEqual(isi, item["isi"])
        self.assertIn(f"<b>{item['judul']}</b>", html)


# ── alur dengan Redis palsu ─────────────────────────────────────────────
class AlurTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis = FakeRedis()
        self.dismiss = None
        self.kirim = AsyncMock(side_effect=lambda u, t, ti, m, permukaan, **kw: set(permukaan))
        for p in (patch.object(proaktif, "_redis", new=lambda: self.redis),
                  patch.object(proaktif, "_analisa", new=AsyncMock(side_effect=lambda u, now: analisa(self.dismiss))),
                  patch.object(notification_service, "kirim", new=self.kirim)):
            p.start()
            self.addCleanup(p.stop)
        self.u = user()

    async def test_peringatan_danger_sekali_sehari(self):
        terkirim = await proaktif.kirim_peringatan(self.u, prefs(), jam(9))
        self.assertEqual(terkirim, {"telegram", "web"})
        args, kw = self.kirim.await_args
        self.assertEqual(args[1], NotificationType.budget_warning)
        self.assertIn("KPR", args[2])
        self.assertEqual(kw["link"], "/")
        self.assertEqual(await proaktif.kirim_peringatan(self.u, prefs(), jam(10)), set())
        self.assertEqual(self.kirim.await_count, 1)
        # Besok kuota baru.
        besok = await proaktif.kirim_peringatan(self.u, prefs(), jam(9, d=date(2026, 10, 16)))
        self.assertEqual(besok, {"telegram", "web"})

    async def test_jam_tenang_tidak_mengirim(self):
        for h in (21, 22, 6):
            self.assertEqual(await proaktif.kirim_peringatan(self.u, prefs(), jam(h)), set())
        self.kirim.assert_not_awaited()

    async def test_patuh_preferensi_budget_warning(self):
        terkirim = await proaktif.kirim_peringatan(self.u, prefs(budget_warning_tg=False), jam(9))
        self.assertEqual(terkirim, {"web"})
        terkirim = await proaktif.kirim_peringatan(
            user(), prefs(budget_warning_tg=False, budget_warning_web=False), jam(9))
        self.assertEqual(terkirim, set())

    async def test_tanpa_telegram_hanya_lonceng(self):
        self.assertEqual(await proaktif.kirim_peringatan(user(None), prefs(), jam(9)), {"web"})

    async def test_dismiss_terbaru_lalu_dimunculkan_lagi(self):
        self.dismiss = DISMISS_KPR
        self.assertEqual(await proaktif.kirim_peringatan(self.u, prefs(), jam(9)), set())
        self.kirim.assert_not_awaited()
        self.dismiss = None   # Munculkan lagi (DELETE /advisor/dismiss) → boleh dikirim
        self.assertEqual(await proaktif.kirim_peringatan(self.u, prefs(), jam(10)), {"telegram", "web"})

    async def test_tagihan_sudah_diingatkan_tidak_jadi_permukaan_ketiga(self):
        buku = await proaktif.muat_buku(self.u.id, HARI)
        await proaktif.catat(self.u.id, buku, proaktif.hal_tagihan("kpr"), {"telegram", "web"}, advisor=False)
        self.assertEqual(await proaktif.kirim_peringatan(self.u, prefs(), jam(9)), set())
        self.assertIsNone(await proaktif.untuk_chat(self.u, now=jam(9)))
        self.kirim.assert_not_awaited()

    async def test_chat_web_sekali_dan_maks_dua_permukaan(self):
        # Peringatan hanya ke Telegram (lonceng dimatikan) → chat web boleh jadi permukaan kedua.
        await proaktif.kirim_peringatan(self.u, prefs(budget_warning_web=False), jam(9))
        teks = await proaktif.untuk_chat(self.u, now=jam(12))
        self.assertIn("KPR", teks)
        self.assertIsNone(await proaktif.untuk_chat(self.u, now=jam(13)))

    async def test_chat_web_tidak_ditambah_bila_sudah_dua_permukaan(self):
        await proaktif.kirim_peringatan(self.u, prefs(), jam(9))
        self.assertIsNone(await proaktif.untuk_chat(self.u, now=jam(12)))

    async def test_chat_web_pertama_memakai_kuota(self):
        teks = await proaktif.untuk_chat(self.u, now=jam(8))
        self.assertIn("KPR", teks)
        # Peringatan sesudahnya untuk hal yang sama hanya menambah satu permukaan.
        self.assertEqual(await proaktif.kirim_peringatan(self.u, prefs(), jam(9)), {"telegram"})

    async def test_redis_mati_tidak_mengirim(self):
        def rusak():
            raise ConnectionError("redis")
        with patch.object(proaktif, "_redis", new=rusak):
            self.assertEqual(await proaktif.kirim_peringatan(self.u, prefs(), jam(9)), set())
            self.assertIsNone(await proaktif.untuk_chat(self.u, now=jam(9)))
        self.kirim.assert_not_awaited()

    async def test_ringkasan_harian_memakai_kuota(self):
        self.dismiss = DISMISS_KPR   # item #1 = PER-01 (warn)
        await proaktif.catat_ringkasan(self.u, analisa(self.dismiss), HARI, {"telegram"})
        buku = await proaktif.muat_buku(self.u.id, HARI)
        self.assertEqual(buku.advisor, "PER-01:2026-09-27")
        self.dismiss = None          # TAG-01 danger muncul lagi, tapi kuota hari ini sudah terpakai
        self.assertEqual(await proaktif.kirim_peringatan(self.u, prefs(), jam(9)), set())


# ── send_budget_warning ─────────────────────────────────────────────────
class BudgetWarningTests(unittest.IsolatedAsyncioTestCase):
    def patch_sesi(self, db):
        p = patch.object(notification_service, "AsyncSessionLocal", new=lambda: FakeSession(db))
        p.start()
        self.addCleanup(p.stop)

    async def test_teks_dari_insight_tanpa_email(self):
        a = analisa()
        item = chat._r(a, a.sel.daftar[0])
        u = user()
        db = MagicMock()
        db.commit = AsyncMock()
        self.patch_sesi(db)
        bot_cls = MagicMock()
        bot_cls.return_value.send_message = AsyncMock()
        with patch.object(notification_service, "Bot", new=bot_cls), \
                patch.object(notification_service.settings, "TELEGRAM_BOT_TOKEN", "token"), \
                patch("app.services.email_service.send_email") as email:
            terkirim = await notification_service.send_budget_warning(u, item, prefs(), ("telegram", "web"))
        self.assertEqual(terkirim, {"telegram", "web"})
        notif = db.add.call_args.args[0]
        self.assertEqual(notif.type, NotificationType.budget_warning)
        self.assertEqual(notif.title, render.notifikasi_insight(item)[0])
        kw = bot_cls.return_value.send_message.await_args.kwargs
        self.assertEqual(kw["parse_mode"], "HTML")
        self.assertEqual(kw["text"], render.notifikasi_insight(item)[2])
        email.assert_not_called()

    async def test_telegram_gagal_tetap_lonceng(self):
        a = analisa()
        item = chat._r(a, a.sel.daftar[0])
        db = MagicMock()
        db.commit = AsyncMock()
        self.patch_sesi(db)
        bot_cls = MagicMock()
        bot_cls.return_value.send_message = AsyncMock(side_effect=RuntimeError("tg"))
        with patch.object(notification_service, "Bot", new=bot_cls), \
                patch.object(notification_service.settings, "TELEGRAM_BOT_TOKEN", "token"), \
                patch.object(notification_service.logger, "error"):
            terkirim = await notification_service.send_budget_warning(user(), item, prefs(), ("telegram", "web"))
        self.assertEqual(terkirim, {"web"})


# ── pengingat tagihan ───────────────────────────────────────────────────
class PengingatTagihanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis = FakeRedis()
        self.rec = SimpleNamespace(id=uuid.uuid4(), envelope_id=uuid.uuid4(), description="Netflix",
                                   amount=D("54000"), frequency=RecurringFrequency.monthly, next_run=HARI)
        self.env = SimpleNamespace(id=self.rec.envelope_id, name="Hiburan", emoji="🎬", owner_id=uuid.uuid4(),
                                   household_id=uuid.uuid4())
        self.u = user()
        self.prefs = prefs()
        self.kirim = AsyncMock(side_effect=lambda u, t, ti, m, permukaan, **kw: set(permukaan))
        for p in (patch.object(proaktif, "_redis", new=lambda: self.redis),
                  patch.object(notification_service, "kirim", new=self.kirim),
                  patch.object(notification_service, "get_or_create_prefs",
                               new=AsyncMock(side_effect=lambda uid, db: self.prefs))):
            p.start()
            self.addCleanup(p.stop)

    async def jalan(self, now_local: datetime):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[FakeResult(rows=[self.rec]), FakeResult(self.env),
                                            FakeResult(rows=[self.u])])
        with patch.object(recurring_processor, "AsyncSessionLocal", new=lambda: FakeSession(db)):
            await recurring_processor.process_recurring_transactions(now_utc=now_local.astimezone(timezone.utc))

    async def test_pagi_sekali_per_jatuh_tempo(self):
        await self.jalan(jam(6))            # jam tenang
        self.kirim.assert_not_awaited()
        await self.jalan(jam(7))
        self.assertEqual(self.kirim.await_count, 1)
        args, kw = self.kirim.await_args
        self.assertEqual(args[1], NotificationType.subscription_due)
        self.assertEqual(kw["permukaan"], ["telegram", "web"])
        self.assertEqual(kw["link"], "/langganan")
        self.assertIn(f"recpay_{self.rec.id}", str(kw["reply_markup"].to_dict()))
        await self.jalan(jam(8))            # jam berikutnya: tidak berulang
        await self.jalan(jam(7, d=date(2026, 10, 16)))   # besok, masih telat: tidak berulang
        self.assertEqual(self.kirim.await_count, 1)
        buku = await proaktif.muat_buku(self.u.id, HARI)
        self.assertEqual(buku.hal["TAG:" + str(self.rec.id)], {"telegram", "web"})
        self.assertIsNone(buku.advisor)     # pengingat tagihan tidak memakai kuota advisor

    async def test_jatuh_tempo_berikutnya_diingatkan_lagi(self):
        await self.jalan(jam(7))
        self.rec.next_run = date(2026, 11, 15)
        await self.jalan(jam(7, d=date(2026, 11, 15)))
        self.assertEqual(self.kirim.await_count, 2)

    async def test_belum_jatuh_tempo_di_zona_user(self):
        self.rec.next_run = date(2026, 10, 16)
        await self.jalan(jam(20))
        self.kirim.assert_not_awaited()

    async def test_patuh_subscription_due_tg(self):
        self.prefs = prefs(subscription_due_tg=False)
        await self.jalan(jam(7))
        self.assertEqual(self.kirim.await_args.kwargs["permukaan"], ["web"])

    async def test_semua_preferensi_mati_tidak_mengirim_dan_tidak_mengklaim(self):
        self.prefs = prefs(subscription_due_tg=False, subscription_due_web=False)
        await self.jalan(jam(7))
        self.kirim.assert_not_awaited()
        self.prefs = prefs()                # dinyalakan lagi hari itu → masih diingatkan
        await self.jalan(jam(9))
        self.assertEqual(self.kirim.await_count, 1)

    async def test_tanpa_telegram_lonceng_saja(self):
        self.u = user(None)
        await self.jalan(jam(7))
        self.assertEqual(self.kirim.await_args.kwargs["permukaan"], ["web"])


# ── ringkasan ke lonceng web ────────────────────────────────────────────
class RingkasanLoncengTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis = FakeRedis()
        self.a = analisa()
        self.u = user(None)
        self.kirim = AsyncMock(side_effect=lambda u, t, ti, m, permukaan, **kw: set(permukaan))
        for p in (patch.object(proaktif, "_redis", new=lambda: self.redis),
                  patch.object(notification_service, "kirim", new=self.kirim),
                  patch.object(summary, "_pengaturan_advisor", new=AsyncMock(return_value={"advisor_v2_users": "*"})),
                  patch.object(summary, "_analisa_v2", new=AsyncMock(return_value=self.a))):
            p.start()
            self.addCleanup(p.stop)

    async def test_harian_lonceng_tanpa_telegram(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[FakeResult(rows=[self.u]), FakeResult(uuid.uuid4())])
        bot_cls = MagicMock()
        with patch.object(summary, "AsyncSessionLocal", new=lambda: FakeSession(db)), \
                patch.object(summary, "Bot", new=bot_cls), \
                patch.object(summary.logger, "error") as log_error:
            await summary.send_daily_summary(user_id=self.u.id, telegram=False, web=True)
        log_error.assert_not_called()
        bot_cls.assert_not_called()
        args, kw = self.kirim.await_args
        self.assertEqual(args[1], NotificationType.daily_summary)
        self.assertEqual((args[2], args[3]), chat.lonceng_harian(self.a))
        self.assertIn("Lunasi KPR Rumah", args[3])           # item #1
        self.assertIn("Rp1.685.200", args[3])                # sisa bebas = KPI
        buku = await proaktif.muat_buku(self.u.id, HARI)
        self.assertEqual(buku.advisor, "TAG:kpr")
        self.assertEqual(buku.hal["TAG:kpr"], {"web"})

    async def test_mingguan_lonceng(self):
        txn = SimpleNamespace(envelope_id="belanja", amount=D("297100"), transaction_date=HARI)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[FakeResult(rows=[self.u]), FakeResult(uuid.uuid4()),
                                            FakeResult(rows=[txn])])
        with patch.object(summary, "AsyncSessionLocal", new=lambda: FakeSession(db)), \
                patch.object(summary.logger, "error") as log_error:
            await summary.send_weekly_summary(user_id=self.u.id, telegram=False, web=True)
        log_error.assert_not_called()
        args, _ = self.kirim.await_args
        self.assertEqual(args[1], NotificationType.weekly_summary)
        self.assertIn("Rp297.100 (1 transaksi)", args[3])

    def test_query_lonceng_tidak_mensyaratkan_telegram(self):
        from app.tests.fakes import sql
        self.assertNotIn("telegram_id IS NOT NULL", sql(summary._users_query(self.u.id, web=True)))
        self.assertIn("telegram_id IS NOT NULL", sql(summary._users_query(self.u.id, web=False)))
        self.assertIn("telegram_id IS NOT NULL", sql(summary._users_query(None, web=True)))


if __name__ == "__main__":
    unittest.main()
