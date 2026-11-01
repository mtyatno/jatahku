"""Plugin B1 — Beranda berbasis registry: `/dashboard/layout`, `/dashboard/cards`, `/dashboard/data`.

Mengunci (docs/plugin/04-kontrak-api.md §4, ADR-P8, 03-workflow.md baris B1):
- Paritas angka: setiap sumber di `POST /dashboard/data` sama persis dengan respons HTTP endpoint
  lama yang dipanggil Beranda sekarang, untuk periode berjalan dan periode lalu, dengan AI Advisor
  aktif dan tidak.
- Tata letak: template bawaan versi 0, `if_version` (409 `versi_beda`), `instans_hilang`,
  validasi ukuran/kartu/pengaturan, kartu tanpa definisi diparkir lalu kembali.
- Keamanan: ruang ditentukan server, tata letak per user, amplop pribadi anggota lain tidak
  bocor lewat batch, `GET /dashboard/data/{id}` hanya membaca tata letak user sendiri.
- Galat satu penyedia hanya mengisi kartunya; anggaran batch p95 ≤ 500 ms.

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_dashboard_registry -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import time
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
JKT = ZoneInfo("Asia/Jakarta")

if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import select

    from app.api.routes import (
        advisor, analytics, balance_check, dashboard, envelopes, goals, household, incomes, recurring,
        transactions,
    )
    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        Allocation, AppSetting, DashboardLayout, Envelope, Goal, Household, HouseholdMember, HouseholdRole,
        Income, PurposeType, RecurringTransaction, Transaction, User,
    )
    from app.services.dashboard import registry
    from app.services.dashboard.providers import PROVIDERS
    from app.tests.test_advisor_dashboard_integration import FakeRedis

# Sumber → (path endpoint lama, query periode berjalan, query periode lalu). Sama dengan Dashboard.jsx.
def _endpoint_lama(nama, ps, pe, berjalan):
    q = "" if berjalan else f"?period_start={ps}&period_end={pe}"
    return {
        "ringkasan_amplop": f"/envelopes/summary{q}",
        "harian": f"/analytics/daily-spending{q}",
        "rincian": f"/analytics/envelope-breakdown{q}",
        "prediksi": "/analytics/prediction",
        "tagihan": "/recurring/summary/period",
        "advisor": "/advisor/dashboard",
        "insights": "/advisor/insights",
        "pemasukan": "/incomes/",
        "target": "/goals/",
        "langganan": "/recurring/",
        "saldo_cek": "/balance-check/status",
        "papan": "/household/leaderboard",
        "transaksi": f"/transactions/?limit=10&start_date={ps}&end_date={pe}",
    }[nama]


SUMBER_BERJALAN_SAJA = {"prediksi", "tagihan", "advisor", "insights", "pemasukan"}


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class DashboardRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.redis = FakeRedis()
        p = patch("redis.asyncio.from_url", return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)

        today = datetime.now(JKT).date()
        self.today = today
        async with self.Session() as db:
            me = User(name="Saya", payday_day=1, timezone="Asia/Jakarta")
            rina = User(name="Rina", payday_day=1, timezone="Asia/Jakarta")
            orang = User(name="Orang lain", payday_day=1, timezone="Asia/Jakarta")
            hh, hh2 = Household(name="Rumah"), Household(name="Rumah lain")
            db.add_all([me, rina, orang, hh, hh2])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=me.id, household_id=hh.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=rina.id, household_id=hh.id, role=HouseholdRole.member),
                HouseholdMember(user_id=orang.id, household_id=hh2.id, role=HouseholdRole.owner),
            ])
            makan = Envelope(household_id=hh.id, name="Makan", classification="needs", budget_amount=D("0"))
            tabung = Envelope(household_id=hh.id, name="Liburan", purpose=PurposeType.saving,
                              budget_amount=D("0"))
            rahasia = Envelope(household_id=hh.id, name="Rahasia Rina", owner_id=rina.id, budget_amount=D("0"))
            asing = Envelope(household_id=hh2.id, name="Asing", budget_amount=D("0"))
            db.add_all([makan, tabung, rahasia, asing])
            await db.flush()
            gaji = Income(household_id=hh.id, user_id=me.id, amount=D("5000000"), description="Gaji",
                          income_date=today)
            db.add(gaji)
            await db.flush()
            db.add_all([
                Allocation(income_id=gaji.id, envelope_id=makan.id, amount=D("4000000")),
                Allocation(income_id=gaji.id, envelope_id=tabung.id, amount=D("1000000")),
                Transaction(envelope_id=makan.id, user_id=me.id, amount=D("35000"), description="kopi",
                            transaction_date=today),
                Transaction(envelope_id=makan.id, user_id=rina.id, amount=D("120000"), description="sayur",
                            transaction_date=today),
                Transaction(envelope_id=rahasia.id, user_id=rina.id, amount=D("777000"), description="tas",
                            transaction_date=today),
                Transaction(envelope_id=asing.id, user_id=orang.id, amount=D("999000"), description="asing",
                            transaction_date=today),
                Goal(envelope_id=tabung.id, name="Bali", target_amount=D("6000000")),
                RecurringTransaction(envelope_id=makan.id, amount=D("150000"), description="Internet",
                                     next_run=today + timedelta(days=3)),
                AppSetting(key="advisor_v2_users", value="*"),
            ])
            await db.commit()
        self.me, self.rina, self.orang = me, rina, orang
        self.hid = hh.id

        self.current = me
        app = FastAPI()
        for mod, prefix in ((dashboard, "/dashboard"), (envelopes, "/envelopes"), (analytics, "/analytics"),
                            (recurring, "/recurring"), (advisor, "/advisor"), (incomes, "/incomes"),
                            (goals, "/goals"), (balance_check, "/balance-check"), (household, "/household"),
                            (transactions, "/transactions")):
            app.include_router(mod.router, prefix=prefix)

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    # ── pembantu ─────────────────────────────────────────────────────────
    async def batch(self, items=None, periode=None, user=None):
        self.current = user or self.me
        items = items if items is not None else [
            {"id": i["id"], "card": i["card"], "settings": {}} for i in registry.template("beranda")
        ]
        return await self.client.post("/dashboard/data", json={"periode": periode, "items": items})

    async def lama(self, path, user=None):
        self.current = user or self.me
        r = await self.client.get(path)
        self.assertEqual(r.status_code, 200, path)
        return r.json()

    async def periods(self):
        return await self.lama("/analytics/periods?count=24")

    def kumpulkan_sumber(self, data):
        """{nama sumber: payload} dari seluruh kartu; sumber yang sama harus identik antar kartu
        (kecuali `advisor`, yang sengaja dipotong per kartu dan dicek terpisah)."""
        out = {}
        for entri in data.values():
            for nama, payload in (entri.get("sumber") or {}).items():
                if nama in out and nama != "advisor":
                    self.assertEqual(out[nama], payload, f"sumber {nama} beda antar kartu")
                out[nama] = payload
        return out

    # ── registry ─────────────────────────────────────────────────────────
    def test_registry_lengkap(self):
        self.assertEqual(set(registry.REGISTRY), set(PROVIDERS), "setiap kartu punya penyedia, dan sebaliknya")
        for c in registry.REGISTRY.values():
            self.assertIn(c.size_bawaan, c.sizes, c.key)
            self.assertTrue(set(c.sizes) <= set(registry.SIZES), c.key)
            self.assertIn(c.shape, registry.SHAPES, c.key)
            self.assertTrue(c.key.startswith("core."), c.key)
        ids = [i["id"] for i in registry.template("beranda")]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i["card"] in registry.REGISTRY for i in registry.template("beranda")))

    async def test_katalog(self):
        r = await self.client.get("/dashboard/cards")
        self.assertEqual(r.status_code, 200)
        keys = [c["key"] for c in r.json()]
        self.assertEqual(keys, list(registry.REGISTRY))
        jatah = r.json()[0]
        self.assertEqual((jatah["judul"], jatah["asal"], jatah["hak"], jatah["size_bawaan"]),
                         ("Jatah hari ini", "inti", "ok", "S"))

    # ── paritas angka ────────────────────────────────────────────────────
    async def _cek_paritas(self, periode, user=None):
        r = await self.batch(periode=periode, user=user)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        sumber = self.kumpulkan_sumber(body["data"])
        p = body["periode"]
        self.assertGreaterEqual(len(sumber), 10)
        for nama, payload in sumber.items():
            if nama.startswith("advisor"):
                continue
            if not p["berjalan"] and nama in SUMBER_BERJALAN_SAJA:
                self.assertIsNone(payload, nama)
                continue
            self.assertEqual(payload, await self.lama(_endpoint_lama(nama, p["start"], p["end"], p["berjalan"]),
                                                      user), f"paritas {nama}")
        return body, sumber

    async def test_paritas_periode_berjalan_advisor_aktif(self):
        body, sumber = await self._cek_paritas(None)
        self.assertTrue(body["periode"]["berjalan"])
        adv = await self.lama("/advisor/dashboard")
        self.assertTrue(adv["enabled"])
        self.assertEqual(body["data"]["a9"]["sumber"]["advisor"], adv)
        # KPI: nilai utama langsung dari metrik advisor, potongan metrik tanpa deret harian.
        m = adv["metrics"]
        d = body["data"]
        self.assertEqual(d["a1"]["value"], m["belanja_hari_ini"])
        self.assertEqual(d["a2"]["value"], m["sisa_bebas_harian"] if m["sisa_bebas_harian"] is not None
                         else m["sisa_bebas"])
        self.assertEqual(d["a3"]["value"], m["terpakai"])
        self.assertEqual(d["a4"]["value"], m["pemasukan_rumah_tangga"])
        self.assertEqual(d["a5"]["value"], (await self.lama("/recurring/summary/period"))["amount_due"])
        self.assertIsNone(d["a6"]["value"])
        self.assertEqual(d["a1"]["sumber"]["advisor"]["metrics"], {k: v for k, v in m.items() if k != "harian"})
        self.assertEqual(d["a1"]["sumber"]["advisor"]["kpi"], adv["kpi"]["jatah"])
        self.assertEqual(d["a8"]["sumber"]["advisor"]["metrics"]["harian"], m["harian"])
        self.assertEqual(d["a8"]["sumber"]["advisor"]["grafik"], adv["grafik"])
        self.assertEqual(m["pemasukan_rumah_tangga"], 5_000_000)

    async def test_paritas_advisor_tidak_aktif(self):
        async with self.Session() as db:
            (await db.get(AppSetting, "advisor_v2_users")).value = ""
            await db.commit()
        body, sumber = await self._cek_paritas(None)
        d = body["data"]
        self.assertEqual(d["a1"]["sumber"]["advisor"], {"enabled": False})
        self.assertIsNone(d["a1"]["value"])
        self.assertEqual(d["a4"]["value"], (await self.lama("/analytics/prediction"))["total_income"])
        # UI lama Perlu perhatian mendapat sumbernya sendiri.
        self.assertEqual(set(d["a9"]["sumber"]),
                         {"advisor", "insights", "ringkasan_amplop", "langganan", "pemasukan", "prediksi"})

    async def test_paritas_periode_lalu(self):
        lalu = (await self.periods())[-2]
        body, sumber = await self._cek_paritas(lalu["period_start"])
        self.assertEqual(body["periode"], {"start": lalu["period_start"], "end": lalu["period_end"],
                                           "berjalan": False})
        self.assertIsNone(body["data"]["a1"]["sumber"]["advisor"])

    async def test_paritas_untuk_anggota_lain(self):
        await self._cek_paritas(None, user=self.rina)

    # ── keamanan ─────────────────────────────────────────────────────────
    async def test_amplop_pribadi_anggota_lain_tidak_bocor(self):
        body = (await self.batch()).json()
        nama = [e["name"] for e in body["data"]["a11"]["sumber"]["ringkasan_amplop"]]
        self.assertIn("Makan", nama)
        self.assertNotIn("Rahasia Rina", nama)
        self.assertNotIn("Asing", nama)
        desk = [t["description"] for t in body["data"]["a13"]["sumber"]["transaksi"]]
        self.assertNotIn("tas", desk)
        self.assertNotIn("asing", desk)
        harian = body["data"]["a8"]["sumber"]["harian"]
        self.assertEqual(sum(h["total"] for h in harian), 155000.0)

    async def test_body_tidak_bisa_memilih_ruang(self):
        # Field asing (mis. ruang_id) diabaikan; data tetap household user.
        self.current = self.orang
        r = await self.client.post("/dashboard/data", json={
            "ruang_id": str(self.hid), "household_id": str(self.hid),
            "items": [{"id": "x", "card": "core.amplop_pengeluaran", "settings": {}}]})
        nama = [e["name"] for e in r.json()["data"]["x"]["sumber"]["ringkasan_amplop"]]
        self.assertEqual(nama, ["Asing"])

    async def test_user_tanpa_household(self):
        async with self.Session() as db:
            sendiri = User(name="Baru", payday_day=1)
            db.add(sendiri)
            await db.commit()
        self.current = sendiri
        for r in (await self.client.get("/dashboard/layout"),
                  await self.client.post("/dashboard/data", json={"items": [{"id": "a1", "card": "core.kpi.jatah"}]})):
            self.assertEqual((r.status_code, r.json()["kode"]), (404, "ruang_tidak_ada"))

    # ── galat per kartu & validasi permintaan ────────────────────────────
    async def test_galat_per_kartu(self):
        r = await self.batch([
            {"id": "a", "card": "core.kpi.jatah"},
            {"id": "b", "card": "plugin.tidak_ada"},
            {"id": "c", "card": "core.transaksi_terbaru", "settings": {"limit": 999}},
            {"id": "d", "card": "core.langganan", "settings": {"warna": "merah"}},
            {"id": "e", "card": "core.transaksi_terbaru", "settings": {"limit": 3}},
        ])
        d = r.json()["data"]
        self.assertEqual(d["a"]["shape"], "kpi")
        self.assertEqual(d["b"]["error"]["kode"], "kartu_tidak_dikenal")
        self.assertEqual(d["c"]["error"]["kode"], "pengaturan_tidak_sah")
        self.assertEqual(d["d"]["error"]["kode"], "pengaturan_tidak_sah")
        self.assertLessEqual(len(d["e"]["sumber"]["transaksi"]), 3)

    async def test_sumber_gagal_hanya_kartunya(self):
        async def rusak(**_kw):
            raise RuntimeError("rusak")
        with patch.object(recurring, "recurring_period_summary", rusak):
            d = (await self.batch()).json()["data"]
        self.assertEqual(d["a5"]["error"]["kode"], "gagal_memuat")   # Tagihan
        self.assertEqual(d["a1"]["shape"], "kpi")
        self.assertIn("ringkasan_amplop", d["a11"]["sumber"])

    async def test_validasi_permintaan(self):
        self.current = self.me
        dup = await self.client.post("/dashboard/data", json={"items": [
            {"id": "a", "card": "core.kpi.jatah"}, {"id": "a", "card": "core.kpi.income"}]})
        self.assertEqual((dup.status_code, dup.json()["kode"]), (422, "instans_tidak_sah"))
        banyak = await self.client.post("/dashboard/data", json={"items": [
            {"id": f"x{i}", "card": "core.kpi.jatah"} for i in range(registry.MAX_ITEMS + 1)]})
        self.assertEqual(banyak.status_code, 422)
        kosong = await self.client.post("/dashboard/data", json={"items": []})
        self.assertEqual(kosong.status_code, 422)
        periode = await self.batch([{"id": "a", "card": "core.kpi.jatah"}], periode="2001-01-01")
        self.assertEqual((periode.status_code, periode.json()["kode"]), (422, "periode_tidak_dikenal"))
        sekarang = (await self.periods())[-1]["period_start"]
        self.assertTrue((await self.batch([{"id": "a", "card": "core.kpi.jatah"}],
                                          periode=sekarang)).json()["periode"]["berjalan"])

    # ── tata letak ───────────────────────────────────────────────────────
    async def test_layout_bawaan_lalu_simpan(self):
        r = await self.client.get("/dashboard/layout")
        doc = r.json()
        self.assertEqual((doc["surface"], doc["version"], doc["schema_version"]), ("beranda", 0, 1))
        self.assertEqual([i["card"] for i in doc["items"]], [i["card"] for i in registry.template("beranda")])
        self.assertTrue(all(i["visible"] for i in doc["items"]))
        async with self.Session() as db:
            self.assertIsNone((await db.execute(select(DashboardLayout))).scalar_one_or_none(),
                              "GET tidak menyimpan apa pun")

        items = doc["items"][::-1]
        items[0] = {**items[0], "size": "XL"}  # Langganan → XL tidak didukung
        bad = await self.client.put("/dashboard/layout", json={"if_version": 0, "items": items})
        self.assertEqual((bad.status_code, bad.json()["kode"]), (422, "ukuran_tidak_sah"))

        items[0] = {**items[0], "size": "M", "hidden": True}
        ok = await self.client.put("/dashboard/layout", json={"if_version": 0, "items": items})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()["version"], 1)
        again = (await self.client.get("/dashboard/layout")).json()
        self.assertEqual(again["version"], 1)
        self.assertEqual(again["items"][0]["card"], "core.langganan")
        self.assertEqual((again["items"][0]["size"], again["items"][0]["hidden"]), ("M", True))

        basi = await self.client.put("/dashboard/layout", json={"if_version": 0, "items": items})
        self.assertEqual((basi.status_code, basi.json()["kode"]), (409, "versi_beda"))
        basi2 = await self.client.put("/dashboard/layout", json={"if_version": 5, "items": items})
        self.assertEqual(basi2.status_code, 409)

    async def test_layout_flag_beranda_registry(self):
        # B2: field `enabled` = user ada di AppSetting beranda_registry_users (daftar id atau `*`).
        self.assertFalse((await self.client.get("/dashboard/layout")).json()["enabled"])
        async with self.Session() as db:
            db.add(AppSetting(key="beranda_registry_users", value=f" {self.me.id} ,x"))
            await db.commit()
        self.assertTrue((await self.client.get("/dashboard/layout")).json()["enabled"])
        self.current = self.rina
        self.assertFalse((await self.client.get("/dashboard/layout")).json()["enabled"])
        async with self.Session() as db:
            (await db.get(AppSetting, "beranda_registry_users")).value = "*"
            await db.commit()
        self.assertTrue((await self.client.get("/dashboard/layout")).json()["enabled"])

    async def test_layout_instans_hilang_dan_removed(self):
        doc = (await self.client.get("/dashboard/layout")).json()
        kurang = doc["items"][1:]
        r = await self.client.put("/dashboard/layout", json={"if_version": 0, "items": kurang})
        self.assertEqual((r.status_code, r.json()["kode"]), (422, "instans_hilang"))
        r = await self.client.put("/dashboard/layout",
                                  json={"if_version": 0, "items": kurang, "removed": [doc["items"][0]["id"]]})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("core.kpi.jatah", [i["card"] for i in r.json()["layout"]["items"]])

    async def test_layout_validasi(self):
        doc = (await self.client.get("/dashboard/layout")).json()
        kasus = [
            (doc["items"] + [{"id": "zz", "card": "core.kpi.jatah"}], "kartu_ganda"),
            (doc["items"] + [{"id": "zz", "card": "plugin.x.y"}], "kartu_tidak_dikenal"),
            (doc["items"] + [{"id": "z z", "card": "core.papan_disiplin"}], "instans_tidak_sah"),
            (doc["items"] + [{"id": "zz", "card": "core.papan_disiplin", "devices": "tv"}], "instans_tidak_sah"),
            (doc["items"] + [{"id": doc["items"][0]["id"], "card": "core.papan_disiplin"}], "instans_tidak_sah"),
            ([{**i, "settings": {"limit": 0}} if i["card"] == "core.transaksi_terbaru" else i
              for i in doc["items"]], "pengaturan_tidak_sah"),
        ]
        for items, kode in kasus:
            r = await self.client.put("/dashboard/layout", json={"if_version": 0, "items": items})
            self.assertEqual((r.status_code, r.json().get("kode")), (422, kode), kode)
        tambah = await self.client.put("/dashboard/layout", json={"if_version": 0, "items": doc["items"] + [
            {"id": "zz", "card": "core.papan_disiplin", "devices": "narrow"}]})
        self.assertEqual(tambah.status_code, 200)
        self.assertEqual(tambah.json()["layout"]["items"][-1]["devices"], "narrow")

    async def test_layout_per_user(self):
        doc = (await self.client.get("/dashboard/layout")).json()
        await self.client.put("/dashboard/layout", json={"if_version": 0, "items": doc["items"][::-1]})
        self.current = self.rina
        lain = (await self.client.get("/dashboard/layout")).json()
        self.assertEqual(lain["version"], 0)
        self.assertEqual(lain["items"][0]["card"], "core.kpi.jatah")

    async def test_kartu_tanpa_definisi_diparkir_lalu_kembali(self):
        async with self.Session() as db:
            db.add(DashboardLayout(user_id=self.me.id, household_id=self.hid, surface="beranda", version=3,
                                   items=[{"id": "a1", "card": "core.kpi.jatah", "size": "S"},
                                          {"id": "p1", "card": "buku_usaha.omzet", "size": "S"}],
                                   parked=[]))
            await db.commit()
        doc = (await self.client.get("/dashboard/layout")).json()
        self.assertEqual([i["id"] for i in doc["items"]], ["a1"])
        self.assertEqual([p["id"] for p in doc["parked"]], ["p1"])
        # Menyimpan tanpa p1 tidak dianggap kehilangan instans; p1 tetap di parked.
        r = await self.client.put("/dashboard/layout", json={"if_version": 3, "items": doc["items"]})
        self.assertEqual(r.status_code, 200, r.text)
        async with self.Session() as db:
            row = (await db.execute(select(DashboardLayout))).scalar_one()
            self.assertEqual([p["id"] for p in row.parked], ["p1"])
            self.assertEqual(row.version, 4)

    async def test_data_satu_instans_dari_tata_letak_sendiri(self):
        doc = (await self.client.get("/dashboard/layout")).json()
        items = [{**i, "settings": {"limit": 2}} if i["card"] == "core.transaksi_terbaru" else i
                 for i in doc["items"]]
        await self.client.put("/dashboard/layout", json={"if_version": 0, "items": items})
        r = await self.client.get("/dashboard/data/a13")
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.json()["sumber"]["transaksi"]), 2)
        self.assertEqual((await self.client.get("/dashboard/data/tidak-ada")).json()["kode"], "instans_tidak_ada")
        # Anggota lain memakai template bawaannya sendiri (limit 10), bukan pengaturan user ini.
        self.current = self.rina
        punya_rina = (await self.client.get("/dashboard/data/a13")).json()["sumber"]["transaksi"]
        self.assertEqual(len(punya_rina), 3)   # dua bersama + amplop pribadinya sendiri

    # ── anggaran ─────────────────────────────────────────────────────────
    async def test_log_anggaran_hanya_kartu_plugin_dan_batch(self):
        # Kartu inti pertama menanggung muat sumber bersama: bukan peringatan per penyedia (log produksi
        # 1 Nov: core.kpi.* 154–220 ms padahal batch di bawah 500 ms). Batch lambat mencatat sumber terlama.
        from app.services.dashboard import batch as batch_mod
        with patch.object(batch_mod, "ANGGARAN_PENYEDIA_MS", 0), \
                self.assertLogs("jatahku.dashboard", level="WARNING") as log:
            batch_mod.logger.warning("penanda")      # assertLogs butuh minimal satu baris
            await self.batch()
        self.assertFalse([l for l in log.output if "dashboard penyedia" in l], log.output)

        with patch.object(batch_mod, "ANGGARAN_BATCH_MS", 0), \
                self.assertLogs("jatahku.dashboard", level="WARNING") as log:
            await self.batch()
        baris = [l for l in log.output if "dashboard batch" in l]
        self.assertEqual(len(baris), 1, log.output)
        self.assertRegex(baris[0], r"sumber terlama: \w+ \d+")

        # Kartu plugin (asal bukan inti) tetap diperingatkan per penyedia.
        from dataclasses import replace
        plugin = replace(registry.REGISTRY["core.langganan"], asal="buku_usaha")
        with patch.dict(registry.REGISTRY, {"core.langganan": plugin}), \
                patch.object(batch_mod, "ANGGARAN_PENYEDIA_MS", 0), \
                self.assertLogs("jatahku.dashboard", level="WARNING") as log:
            await self.batch([{"id": "x", "card": "core.langganan"}])
        self.assertTrue([l for l in log.output if "dashboard penyedia core.langganan" in l], log.output)

    async def test_anggaran_p95(self):
        await self.batch()  # pemanasan (impor tertunda, cache advisor)
        durasi = []
        for _ in range(20):
            mulai = time.perf_counter()
            r = await self.batch()
            durasi.append((time.perf_counter() - mulai) * 1000)
            self.assertEqual(r.status_code, 200)
        durasi.sort()
        p95 = durasi[int(len(durasi) * 0.95) - 1]
        self.assertLess(p95, 500, f"p95 {p95:.0f} ms")


if __name__ == "__main__":
    unittest.main()
