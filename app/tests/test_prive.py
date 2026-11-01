"""Plugin R8 — prive dua sisi (04-kontrak-api.md §2; 05-desain-buku-usaha.md B1, B2; Gerbang R).

Dikunci lewat HTTP, di SQLite:
1. Pemilik ruang usaha: keluar dari amplop usaha (Income 0 + alokasi negatif, `kind` prive) dan masuk
   ke Tabungan ruang keluarganya (pemasukan sungguhan) dalam satu commit; tidak ada transaksi
   pengeluaran, jadi laba tidak berkurang.
2. Ruang tujuan selalu ruang keluarga pemanggil — header ruang tidak mengubahnya.
3. Admin dan karyawan ruang usaha ditolak (403 `prive_hanya_pemilik`); amplop ruang keluarga → 400
   `bukan_ruang_usaha`; amplop ruang orang lain dan amplop pribadi anggota lain → 404; melebihi sisa,
   tanggal masa depan, tanpa ruang keluarga → 400. Semua penolakan tidak meninggalkan baris.
4. `client_ref` yang sama dikirim ulang → kedua sisi tidak tercatat dua kali.
5. Gagal di tengah → tidak ada sisi yang tertinggal, dan `client_ref` bisa dicoba lagi.
6. Chat tidak punya jalur prive (ADR-P2).

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_prive -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import pathlib
import unittest
from datetime import datetime, timedelta
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
JKT = ZoneInfo("Asia/Jakarta")

if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import func, select

    from app.api.routes import envelopes, incomes, prive
    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        Allocation, AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, HouseholdType, Income, IncomeKind,
        Transaction, User,
    )
    from app.services import ruang
    from app.services.envelope_balance import compute_envelope_summaries
    from app.tests.test_advisor_dashboard_integration import FakeRedis


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class PriveTests(unittest.IsolatedAsyncioTestCase):
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
        self.today = datetime.now(JKT).date()

        async with self.Session() as db:
            def user(nama):
                return User(name=nama, payday_day=1, timezone="Asia/Jakarta", plan="pro")
            self.me, self.adi, self.bagas, self.orang, self.yatim = (
                user("Saya"), user("Adi"), user("Bagas"), user("Orang"), user("Tanpa Rumah"))
            rumah, usaha = Household(name="Rumah"), Household(name="Dapur Nusa", type=HouseholdType.USAHA)
            rumah_orang = Household(name="Rumah Orang")
            usaha_orang = Household(name="Toko Orang", type=HouseholdType.USAHA)
            usaha_yatim = Household(name="Kios Yatim", type=HouseholdType.USAHA)
            db.add_all([self.me, self.adi, self.bagas, self.orang, self.yatim,
                        rumah, usaha, rumah_orang, usaha_orang, usaha_yatim])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=self.me.id, household_id=rumah.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.me.id, household_id=usaha.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.adi.id, household_id=usaha.id, role=HouseholdRole.admin),
                HouseholdMember(user_id=self.bagas.id, household_id=usaha.id, role=HouseholdRole.member),
                HouseholdMember(user_id=self.orang.id, household_id=rumah_orang.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.orang.id, household_id=usaha_orang.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.yatim.id, household_id=usaha_yatim.id, role=HouseholdRole.owner),
            ])
            self.env_prive = await self._amplop(db, usaha.id, self.me.id, "Prive", D("1000000"))
            self.env_pribadi_adi = await self._amplop(db, usaha.id, self.adi.id, "Kas Adi", D("500000"),
                                                      owner_id=self.adi.id)
            self.env_rumah = await self._amplop(db, rumah.id, self.me.id, "Makan Rumah", D("2000000"))
            self.env_orang = await self._amplop(db, usaha_orang.id, self.orang.id, "Prive Orang", D("3000000"))
            self.env_yatim = await self._amplop(db, usaha_yatim.id, self.yatim.id, "Prive Kios", D("400000"))
            db.add(AppSetting(key=ruang.FLAG_RUANG_USAHA, value="*"))  # R4: ruang usaha dibuka
            await db.commit()
        self.rumah_id, self.usaha_id = rumah.id, usaha.id
        self.rumah_orang_id, self.usaha_orang_id = rumah_orang.id, usaha_orang.id

        self.current = self.me
        app = FastAPI()
        ruang.install(app)
        app.include_router(prive.router, prefix="/prive")
        app.include_router(incomes.router, prefix="/incomes")
        app.include_router(envelopes.router, prefix="/envelopes")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    async def _amplop(self, db, hid, uid, nama, isi, owner_id=None):
        env = Envelope(household_id=hid, name=nama, emoji="💼", budget_amount=D("0"), owner_id=owner_id)
        db.add(env)
        await db.flush()
        inc = Income(household_id=hid, user_id=uid, amount=isi, description=f"Isi {nama}", income_date=self.today)
        db.add(inc)
        await db.flush()
        db.add(Allocation(income_id=inc.id, envelope_id=env.id, amount=isi))
        await db.flush()
        return env.id

    async def _post(self, user, body, header=None):
        self.current = user
        headers = {ruang.RUANG_HEADER: str(header)} if header else {}
        return await self.client.post("/prive", json=body, headers=headers)

    def _body(self, amplop=None, jumlah="250000", **lain):
        return {"dari_amplop_id": str(amplop or self.env_prive), "jumlah": jumlah, **lain}

    async def _prive_rows(self):
        async with self.Session() as db:
            return (await db.execute(select(Income).where(Income.kind == IncomeKind.PRIVE))).scalars().all()

    async def _sisa(self, user, hid, nama):
        async with self.Session() as db:
            rows = await compute_envelope_summaries(user, db, household_id=hid)
        return next((D(str(r["remaining"])) for r in rows if r["name"] == nama), None)

    # ── 1, 2: jalur pemilik ─────────────────────────────────────────────
    async def test_pemilik_mencatat_dua_sisi(self):
        async with self.Session() as db:
            txn_sebelum = (await db.execute(select(func.count(Transaction.id)))).scalar_one()

        r = await self._post(self.me, self._body(catatan="gaji Oktober"))
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["jumlah"], "250000")
        self.assertEqual(body["tanggal"], self.today.isoformat())
        self.assertEqual(body["keluar"]["ruang_id"], str(self.usaha_id))
        self.assertEqual(body["keluar"]["amplop"], "Prive")
        self.assertEqual(body["masuk"]["ruang_id"], str(self.rumah_id))
        self.assertEqual(body["masuk"]["amplop"], "Tabungan")

        rows = {str(i.id): i for i in await self._prive_rows()}
        self.assertEqual(len(rows), 2)
        keluar, masuk = rows[body["keluar"]["income_id"]], rows[body["masuk"]["income_id"]]
        self.assertEqual((keluar.household_id, keluar.amount), (self.usaha_id, D("0")))
        self.assertEqual((masuk.household_id, masuk.amount), (self.rumah_id, D("250000")))
        self.assertEqual(keluar.description, "Prive ke Rumah tangga: gaji Oktober")
        self.assertEqual(masuk.description, "Prive dari Dapur Nusa: gaji Oktober")

        self.assertEqual(await self._sisa(self.me, self.usaha_id, "Prive"), D("750000"))
        self.assertEqual(await self._sisa(self.me, self.rumah_id, "Tabungan"), D("250000"))
        self.assertEqual(await self._sisa(self.me, self.rumah_id, "Makan Rumah"), D("2000000"))
        async with self.Session() as db:  # bukan pengeluaran → tidak pernah menjadi beban/laba berkurang
            self.assertEqual((await db.execute(select(func.count(Transaction.id)))).scalar_one(), txn_sebelum)

    async def test_header_tidak_mengubah_ruang_tujuan(self):
        r = await self._post(self.me, self._body(), header=self.usaha_id)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["masuk"]["ruang_id"], str(self.rumah_id))

    async def test_riwayat_pemasukan_per_ruang(self):
        await self._post(self.me, self._body())
        self.current = self.me
        keluarga = (await self.client.get("/incomes/")).json()
        prive_keluarga = [i for i in keluarga if i["kind"] == "prive"]
        self.assertEqual(len(prive_keluarga), 1)
        self.assertEqual((prive_keluarga[0]["type"], prive_keluarga[0]["amount"]), ("income", "250000.00"))
        usaha = (await self.client.get("/incomes/", headers={ruang.RUANG_HEADER: str(self.usaha_id)})).json()
        prive_usaha = [i for i in usaha if i["kind"] == "prive"]
        self.assertEqual(len(prive_usaha), 1)
        self.assertEqual(prive_usaha[0]["source"], "Prive ke Rumah tangga")

    async def test_tabungan_yang_ada_dipakai(self):
        async with self.Session() as db:
            db.add(Envelope(household_id=self.rumah_id, name="Tabungan", emoji="💰", budget_amount=D("0")))
            await db.commit()
        self.assertEqual((await self._post(self.me, self._body())).status_code, 201)
        async with self.Session() as db:
            n = (await db.execute(select(func.count(Envelope.id)).where(
                Envelope.household_id == self.rumah_id, Envelope.name == "Tabungan"))).scalar_one()
        self.assertEqual(n, 1)

    async def test_sisa_penuh_boleh(self):
        self.assertEqual((await self._post(self.me, self._body(jumlah="1000000"))).status_code, 201)
        self.assertEqual(await self._sisa(self.me, self.usaha_id, "Prive"), D("0"))

    # ── 3: penolakan tanpa jejak ────────────────────────────────────────
    async def _ditolak(self, user, body, status, kode=None, header=None):
        r = await self._post(user, body, header=header)
        self.assertEqual(r.status_code, status, r.text)
        if kode:
            self.assertEqual(r.json().get("kode"), kode)
        self.assertEqual(await self._prive_rows(), [])
        return r

    async def test_admin_dan_karyawan_ditolak(self):
        for u in (self.adi, self.bagas):
            await self._ditolak(u, self._body(), 403, prive.KODE_HANYA_PEMILIK)

    async def test_flag_ruang_usaha_tertutup_404(self):
        # R4: di luar flag `ruang_usaha_users`, objek ruang usaha tidak bisa ditulis — termasuk prive.
        async with self.Session() as db:
            setting = await db.get(AppSetting, ruang.FLAG_RUANG_USAHA)
            setting.value = str(self.adi.id)  # dibuka untuk orang lain, bukan pemilik
            await db.commit()
        await self._ditolak(self.me, self._body(), 404)

    async def test_amplop_ruang_keluarga_ditolak(self):
        await self._ditolak(self.me, self._body(self.env_rumah), 400, prive.KODE_BUKAN_USAHA)

    async def test_amplop_ruang_orang_lain_404(self):
        r = await self._ditolak(self.me, self._body(self.env_orang), 404)
        self.assertNotIn("Toko Orang", r.text)
        # pemilik ruang usaha lain juga tidak bisa menarik dari ruang usaha saya
        await self._ditolak(self.orang, self._body(self.env_prive), 404)

    async def test_amplop_tidak_ada_404(self):
        await self._ditolak(self.me, self._body("00000000-0000-0000-0000-000000000000"), 404)

    async def test_amplop_pribadi_anggota_lain_404(self):
        await self._ditolak(self.me, self._body(self.env_pribadi_adi), 404)

    async def test_amplop_nonaktif_404(self):
        async with self.Session() as db:
            env = await db.get(Envelope, self.env_prive)
            env.is_active = False
            await db.commit()
        await self._ditolak(self.me, self._body(), 404)

    async def test_melebihi_sisa_ditolak(self):
        r = await self._ditolak(self.me, self._body(jumlah="1000001"), 400)
        self.assertIn("Rp1.000.000", r.json()["detail"])

    async def test_jumlah_tidak_sah_ditolak(self):
        for j in ("0", "-5000", "abc"):
            await self._ditolak(self.me, self._body(jumlah=j), 422)

    async def test_tanggal_masa_depan_ditolak(self):
        besok = (self.today + timedelta(days=1)).isoformat()
        await self._ditolak(self.me, self._body(tanggal=besok), 400)

    async def test_tanggal_lampau_dipakai(self):
        kemarin = self.today - timedelta(days=1)
        r = await self._post(self.me, self._body(tanggal=kemarin.isoformat()))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(all(i.income_date == kemarin for i in await self._prive_rows()))

    async def test_tanpa_ruang_keluarga_ditolak(self):
        await self._ditolak(self.yatim, self._body(self.env_yatim), 400, prive.KODE_TANPA_KELUARGA)

    async def test_ruang_orang_lain_tidak_tersentuh(self):
        await self._post(self.me, self._body())
        async with self.Session() as db:
            n = (await db.execute(select(func.count(Income.id)).where(
                Income.household_id.in_([self.rumah_orang_id, self.usaha_orang_id])))).scalar_one()
        self.assertEqual(n, 1)  # hanya isi awal amplop orang itu

    # ── 4, 5: idempoten dan atomik ──────────────────────────────────────
    async def test_kirim_ulang_tidak_ganda(self):
        a = await self._post(self.me, self._body(client_ref="ref-1"))
        b = await self._post(self.me, self._body(client_ref="ref-1"))
        self.assertEqual((a.status_code, b.status_code), (201, 201))
        self.assertEqual(a.json(), b.json())
        self.assertEqual(len(await self._prive_rows()), 2)
        self.assertEqual(await self._sisa(self.me, self.usaha_id, "Prive"), D("750000"))
        c = await self._post(self.me, self._body(client_ref="ref-2"))
        self.assertEqual(c.status_code, 201)
        self.assertEqual(len(await self._prive_rows()), 4)

    async def test_ref_tidak_tertukar_dengan_transaksi(self):
        self.redis.store[f"txnref:{self.me.id}:ref-x"] = "00000000-0000-0000-0000-000000000001"
        r = await self._post(self.me, self._body(client_ref="ref-x"))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(len(await self._prive_rows()), 2)

    async def test_gagal_di_tengah_tidak_meninggalkan_sisi(self):
        from app.services import fund_shift
        asli = fund_shift.record_prive

        def rusak(db, **kw):
            asli(db, **kw)
            raise RuntimeError("putus")

        with patch.object(fund_shift, "record_prive", rusak):
            r = await self._post(self.me, self._body(client_ref="ref-gagal"))
        self.assertEqual(r.status_code, 500)
        self.assertEqual(await self._prive_rows(), [])
        self.assertEqual(await self._sisa(self.me, self.usaha_id, "Prive"), D("1000000"))
        ulang = await self._post(self.me, self._body(client_ref="ref-gagal"))
        self.assertEqual(ulang.status_code, 201, ulang.text)
        self.assertEqual(len(await self._prive_rows()), 2)


class PriveSumberTests(unittest.TestCase):
    def test_chat_tidak_punya_jalur_prive(self):
        bot = pathlib.Path(__file__).resolve().parents[1] / "bot"
        for p in bot.rglob("*.py"):
            teks = p.read_text()
            for nama in ("record_prive", "IncomeKind.PRIVE", "/prive"):
                self.assertNotIn(nama, teks, f"{p.name}: chat selalu ruang keluarga (ADR-P2)")

    def test_keterangan(self):
        from app.services.fund_shift import prive_descriptions
        self.assertEqual(prive_descriptions("Dapur Nusa"), ("Prive ke Rumah tangga", "Prive dari Dapur Nusa"))
        self.assertEqual(prive_descriptions("Dapur Nusa", "  "), ("Prive ke Rumah tangga", "Prive dari Dapur Nusa"))
        ket = prive_descriptions("X", "a" * 300)[0]
        self.assertEqual(len(ket), len("Prive ke Rumah tangga: ") + 200)


if __name__ == "__main__":
    unittest.main()
