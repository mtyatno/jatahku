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
from datetime import date, timedelta
from decimal import Decimal as D
from unittest.mock import patch

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

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
        # Sumber "hari ini" yang sama dengan route prive dan `compute_envelope_summaries`: tanggal mesin (server
        # produksi UTC). Dulu tanggal WIB, sehingga tes merah di runner CI (UTC) pukul 17.00–24.00 UTC.
        self.today = date.today()

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
        import uuid
        lain.setdefault("client_ref", str(uuid.uuid4()))  # wajib (review ulang #177)
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

    async def test_admin_ditolak(self):
        await self._ditolak(self.adi, self._body(), 403, prive.KODE_HANYA_PEMILIK)

    async def test_karyawan_ditolak_gerbang_r5(self):
        # R5: karyawan di ruang usaha ditolak `ruang_amplop` (tolak-bawaan) sebelum cek pemilik prive.
        await self._ditolak(self.bagas, self._body(), 403, "khusus_admin")

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

    def _awal_periode(self):
        from app.core.period import get_budget_period
        return get_budget_period(1, date.today())[0]

    async def test_tanggal_awal_periode_dipakai(self):
        awal = self._awal_periode()
        r = await self._post(self.me, self._body(tanggal=awal.isoformat()))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(all(i.income_date == awal for i in await self._prive_rows()))

    async def test_tanggal_sebelum_periode_ditolak(self):
        # Review keamanan #177: tanggal mundur ke periode lalu melewati cek sisa amplop (rollover sudah dihitung).
        sebelum = self._awal_periode() - timedelta(days=1)
        r = await self._ditolak(self.me, self._body(tanggal=sebelum.isoformat()), 400)
        self.assertIn("awal periode berjalan", r.json()["detail"])
        jauh = self.today - timedelta(days=40)
        await self._ditolak(self.me, self._body(tanggal=jauh.isoformat(), jumlah="1000000"), 400)
        self.assertEqual(await self._sisa(self.me, self.usaha_id, "Prive"), D("1000000"))

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
        txn_key = f"txnref:{self.me.id}:ref-x"
        self.redis.store[txn_key] = "00000000-0000-0000-0000-000000000001"
        r = await self._post(self.me, self._body(client_ref="ref-x"))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(len(await self._prive_rows()), 2)
        # Kunci transaksi utuh; kunci prive di ruang nama sendiri, tidak ada kunci `txnref:…:prive:…`.
        self.assertEqual(self.redis.store[txn_key], "00000000-0000-0000-0000-000000000001")
        self.assertIn(f"priveref:{self.me.id}:ref-x", self.redis.store)
        self.assertFalse([k for k in self.redis.store if k.startswith(f"txnref:{self.me.id}:prive")])

    async def test_redis_mati_fail_closed(self):
        async def mati(*a, **k):
            raise ConnectionError("redis mati")
        with patch.object(self.redis, "set", mati), patch.object(self.redis, "get", mati):
            r = await self._post(self.me, self._body(client_ref="ref-mati"))
        self.assertEqual(r.status_code, 503, r.text)
        self.assertEqual(await self._prive_rows(), [])
        self.assertEqual(await self._sisa(self.me, self.usaha_id, "Prive"), D("1000000"))

    async def test_simpan_hasil_gagal_tidak_mencatat(self):
        asli = self.redis.set

        async def set_(k, v, nx=False, ex=None):
            if v != "pending":
                raise ConnectionError("redis putus sebelum commit")
            return await asli(k, v, nx=nx, ex=ex)
        with patch.object(self.redis, "set", set_):
            r = await self._post(self.me, self._body(client_ref="ref-putus"))
        self.assertEqual(r.status_code, 503, r.text)
        self.assertEqual(await self._prive_rows(), [])
        ulang = await self._post(self.me, self._body(client_ref="ref-putus"))
        self.assertEqual(ulang.status_code, 201, ulang.text)
        self.assertEqual(len(await self._prive_rows()), 2)

    async def test_client_ref_wajib(self):
        for ref in (None, ""):
            body = self._body()
            if ref is None:
                del body["client_ref"]
            else:
                body["client_ref"] = ref
            await self._ditolak(self.me, body, 422)

    async def test_redis_strict_memakai_timeout(self):
        import redis.asyncio
        await self._post(self.me, self._body())
        kw = [c.kwargs for c in redis.asyncio.from_url.call_args_list]
        self.assertTrue(kw and all(k.get("socket_timeout") == 2 and k.get("socket_connect_timeout") == 2 for k in kw))

    async def test_commit_ambigu_tidak_dobel(self):
        # Review ulang #177: COMMIT sampai di database tetapi jawabannya hilang → kiriman ulang tidak boleh mencatat lagi.
        from sqlalchemy.ext.asyncio import AsyncSession
        asli = AsyncSession.commit

        async def commit_lalu_putus(sess):
            await asli(sess)
            raise ConnectionError("koneksi putus sesudah COMMIT")
        with patch.object(AsyncSession, "commit", commit_lalu_putus):
            r = await self._post(self.me, self._body(client_ref="ref-ambigu"))
        self.assertEqual(r.status_code, 500)
        self.assertEqual(len(await self._prive_rows()), 2)
        ulang = await self._post(self.me, self._body(client_ref="ref-ambigu"))
        self.assertEqual(ulang.status_code, 201, ulang.text)
        self.assertEqual(len(await self._prive_rows()), 2)
        self.assertEqual(await self._sisa(self.me, self.usaha_id, "Prive"), D("750000"))

    async def test_kirim_ulang_sesudah_ganti_periode(self):
        a = await self._post(self.me, self._body(client_ref="ref-periode"))
        lama = (self.today - timedelta(days=60)).isoformat()   # di luar periode: hanya kiriman ulang yang lolos
        b = await self._post(self.me, self._body(client_ref="ref-periode", tanggal=lama))
        self.assertEqual((a.status_code, b.status_code), (201, 201))
        self.assertEqual(a.json(), b.json())
        self.assertEqual(len(await self._prive_rows()), 2)

    async def test_siklus_ruang_usaha_bukan_gajian_keluarga(self):
        # Review ulang #177 (PoC): gajian keluarga tgl 25, ruang usaha bulan kalender. Amplop usaha berisi Rp1 jt
        # dari rollover Oktober. Prive Rp1 jt pada 10 Nov sah; prive Rp1 jt lagi pada 26 Nov harus ditolak.
        from datetime import date as _date
        from app.models.models import MonthlySnapshot

        def pada(hari):
            class Hari(_date):
                @classmethod
                def today(cls):
                    return hari
            return Hari
        async with self.Session() as db:
            (await db.get(Household, self.rumah_id)).payday_day = 25
            (await db.get(Household, self.usaha_id)).payday_day = 1
            (await db.get(User, self.me.id)).payday_day = 25
            kas = Envelope(household_id=self.usaha_id, name="Kas Bulanan", emoji="💼", budget_amount=D("0"),
                           is_rollover=True)
            db.add(kas)
            await db.flush()
            db.add(MonthlySnapshot(envelope_id=kas.id, year=2026, month=10, opening_balance=D("0"),
                                   closing_balance=D("1000000"), rollover_amount=D("1000000")))
            # Isi amplop bertanggal 28 Okt (sudah masuk rollover Oktober). Dengan siklus keluarga (tgl 25) kode lama
            # membacanya sebagai alokasi periode 25 Okt–24 Nov lalu, sesudah 25 Nov, rollover Oktober lagi: 201, 201.
            isi = Income(household_id=self.usaha_id, user_id=self.me.id, amount=D("1000000"),
                         description="Omzet Oktober", income_date=_date(2026, 10, 28))
            db.add(isi)
            await db.flush()
            db.add(Allocation(income_id=isi.id, envelope_id=kas.id, amount=D("1000000")))
            await db.commit()
        self.me.payday_day = 25
        for hari, status in ((_date(2026, 11, 10), 201), (_date(2026, 11, 26), 400)):
            with patch("app.api.routes.prive.date", pada(hari)), \
                 patch("app.services.envelope_balance.date", pada(hari)):
                r = await self._post(self.me, self._body(kas.id, jumlah="1000000"))
            self.assertEqual(r.status_code, status, (hari, r.text))
        self.assertIn("Maksimal prive dari Kas Bulanan: Rp0", r.json()["detail"])
        self.assertEqual(len(await self._prive_rows()), 2)

    async def test_kunci_basi_dianggap_belum_tercatat(self):
        import json
        palsu = {"keluar": {"income_id": "00000000-0000-0000-0000-0000000000aa"}}
        self.redis.store[f"priveref:{self.me.id}:ref-basi"] = json.dumps(palsu)
        r = await self._post(self.me, self._body(client_ref="ref-basi"))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(len(await self._prive_rows()), 2)

    async def test_notifikasi_gagal_tetap_201(self):
        with patch("app.services.goal_notify.notify_goals_reached", side_effect=RuntimeError("smtp")):
            r = await self._post(self.me, self._body(client_ref="ref-notif"))
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
