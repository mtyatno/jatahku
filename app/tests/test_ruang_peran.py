"""Plugin R5 — peran, batasan, persetujuan di server (03-workflow.md "Keamanan lebih dulu": batasan ditegakkan di
server, karyawan tidak melihat laporan; 04-kontrak-api.md §2, §7; ADR-P4, P17, P18).

Pelaku: Saya (owner Dapur Nusa, punya ruang keluarga), Ani (admin), Dewi (karyawan, punya ruang keluarga sendiri),
Rina (anggota ruang keluarga Saya — tidak boleh ikut dibatasi), Orang (tidak terkait).

Dikunci:
1. Tolak-bawaan: setiap route ber-ruang menjawab 403 `khusus_admin` untuk karyawan, kecuali `KARYAWAN_BOLEH`;
   tulis dari objek juga (amplop, grup, transfer, target, langganan, cocokkan saldo).
2. Batasan per catatan berlaku di `POST /transactions`, antrean offline, kirim ulang `client_ref`, dan pemasukan.
3. Di atas batas nominal: 202 + draf, saldo tidak berubah; disetujui → transaksi atas nama pencatat; kiriman ulang
   tidak membuat draf atau transaksi kedua.
4. Jam kerja, jendela ubah, anggota/undangan, log audit, reset ruang usaha.
5. Ruang keluarga dan anggota household tidak berubah perilakunya.

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_ruang_peran -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
JKT = ZoneInfo("Asia/Jakarta")

from app.services import peran  # noqa: E402

if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from sqlalchemy import func, select

    from app.api.routes import (
        advisor, analytics, balance_check, dashboard, envelopes, export, goals, household, incomes,
        kotak_struk, notifications, recurring, snapshots, transactions, user_settings,
    )
    from app.api.routes import ruang as ruang_routes
    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        Allocation, Envelope, EnvelopeGroup, Goal, Household, HouseholdMember, HouseholdRole, HouseholdType, Income,
        PurposeType, RecurringTransaction, RuangAudit, RuangBatasan, RuangDraf, RuangUndangan, Transaction, User,
    )
    from app.services import ruang
    from app.tests.test_ruang_gerbang import ROUTERS, _Redis


if HAS_AIOSQLITE:
    class _RedisSetex(_Redis):
        """+ setex untuk `raise_daily_limit_today` (kunci bypass limit harian)."""
        async def setex(self, k, ttl, v):
            return await self.set(k, v, ex=ttl)


# ── Unit: aturan murni ─────────────────────────────────────────────────────
class AturanMurniTests(unittest.TestCase):
    def test_jam_kerja_biasa_dan_lewat_tengah_malam(self):
        jk = peran.validasi_jam_kerja({"mulai": "07:00", "selesai": "15:00", "hari": [1, 2, 3, 4, 5, 6]})
        senin_pagi = datetime(2026, 11, 2, 8, 0, tzinfo=JKT)       # Senin
        self.assertIsNone(peran.buka_lagi(jk, senin_pagi))
        senin_sore = datetime(2026, 11, 2, 16, 0, tzinfo=JKT)
        self.assertEqual(peran.buka_lagi(jk, senin_sore), datetime(2026, 11, 3, 7, 0, tzinfo=JKT))
        minggu = datetime(2026, 11, 8, 9, 0, tzinfo=JKT)             # Minggu libur → Senin 07.00
        self.assertEqual(peran.buka_lagi(jk, minggu), datetime(2026, 11, 9, 7, 0, tzinfo=JKT))
        malam = peran.validasi_jam_kerja({"mulai": "22:00", "selesai": "06:00", "hari": [1]})
        self.assertIsNone(peran.buka_lagi(malam, datetime(2026, 11, 2, 23, 0, tzinfo=JKT)))    # Senin malam
        self.assertIsNone(peran.buka_lagi(malam, datetime(2026, 11, 3, 5, 0, tzinfo=JKT)))     # lanjutan Senin
        self.assertIsNotNone(peran.buka_lagi(malam, datetime(2026, 11, 3, 23, 0, tzinfo=JKT)))  # Selasa malam

    def test_validasi_jam_kerja_menolak_yang_tidak_sah(self):
        for jk in ({"mulai": "07:00", "selesai": "07:00"}, {"mulai": "25:00", "selesai": "07:00"},
                   {"mulai": "07:00", "selesai": "15:00", "hari": [0]}, {"mulai": "07:00", "selesai": "15:00",
                                                                         "zona": "Bulan/Tengah"}):
            with self.assertRaises(Exception):
                peran.validasi_jam_kerja(jk)

    def test_cek_catat_urutan_dan_draf(self):
        b = peran.Batasan(jenis_catatan=["pengeluaran"], amplop_ids=["a"], batas_nominal=D("1000000"),
                          foto_nota_di_atas=D("300000"))
        self.assertIsNone(peran.cek_catat(None, jenis="penjualan", amplop_ids=["x"], jumlah=D("9e9"), ada_foto=False)
                          or None)
        with self.assertRaises(peran.PeranDitolak) as c:
            peran.cek_catat(b, jenis="penjualan", amplop_ids=["a"], jumlah=D("1"), ada_foto=False)
        self.assertEqual(c.exception.kode, "jenis_tidak_diizinkan")
        with self.assertRaises(peran.PeranDitolak) as c:
            peran.cek_catat(b, jenis="pengeluaran", amplop_ids=["b"], jumlah=D("1"), ada_foto=False)
        self.assertEqual(c.exception.kode, "amplop_tidak_diizinkan")
        with self.assertRaises(peran.PeranDitolak) as c:
            peran.cek_catat(b, jenis="pengeluaran", amplop_ids=["a"], jumlah=D("400000"), ada_foto=False)
        self.assertEqual((c.exception.kode, c.exception.status_code), ("perlu_foto_nota", 422))
        self.assertFalse(peran.cek_catat(b, jenis="pengeluaran", amplop_ids=["a"], jumlah=D("1000000"), ada_foto=True))
        self.assertTrue(peran.cek_catat(b, jenis="pengeluaran", amplop_ids=["a"], jumlah=D("1000001"), ada_foto=True))

    def test_jendela_ubah(self):
        b = peran.Batasan()
        now = datetime(2026, 11, 2, 10, 0, tzinfo=JKT)
        peran.cek_jendela_ubah(b, milik_sendiri=True, dibuat=now - timedelta(hours=2), sekarang=now)
        for kw in ({"milik_sendiri": False, "dibuat": now}, {"milik_sendiri": True, "dibuat": now - timedelta(days=1)}):
            with self.assertRaises(peran.PeranDitolak):
                peran.cek_jendela_ubah(b, sekarang=now, **kw)
        with self.assertRaises(peran.PeranDitolak):
            peran.cek_jendela_ubah(peran.Batasan(jendela_ubah="tidak_boleh"), milik_sendiri=True, dibuat=now,
                                   sekarang=now)
        peran.cek_jendela_ubah(None, milik_sendiri=False, dibuat=None)   # bukan karyawan: tidak dibatasi


# ── Integrasi HTTP ─────────────────────────────────────────────────────────
@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RuangPeranTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.redis = _RedisSetex()
        p = patch("redis.asyncio.from_url", return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)

        self.today = datetime.now(JKT).date()
        async with self.Session() as db:
            mk = lambda n: User(name=n, payday_day=1, timezone="Asia/Jakarta", plan="pro")  # noqa: E731
            self.me, self.ani, self.dewi, self.rina, self.orang = (mk(n) for n in ("Saya", "Ani", "Dewi", "Rina",
                                                                                    "Orang"))
            rumah, rumah_dewi, nusa = Household(name="Rumah"), Household(name="Rumah Dewi"), Household(
                name="Dapur Nusa", type=HouseholdType.USAHA)
            db.add_all([self.me, self.ani, self.dewi, self.rina, self.orang, rumah, rumah_dewi, nusa])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=self.me.id, household_id=rumah.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.rina.id, household_id=rumah.id, role=HouseholdRole.member),
                HouseholdMember(user_id=self.dewi.id, household_id=rumah_dewi.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.me.id, household_id=nusa.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.ani.id, household_id=nusa.id, role=HouseholdRole.admin),
                HouseholdMember(user_id=self.dewi.id, household_id=nusa.id, role=HouseholdRole.member),
            ])
            self.k = await self._isi(db, rumah.id, self.me.id, "Makan Rumah")
            self.kd = await self._isi(db, rumah_dewi.id, self.dewi.id, "Jajan Dewi")
            self.u = await self._isi(db, nusa.id, self.me.id, "Bahan")
            op = Envelope(household_id=nusa.id, name="Operasional", emoji="🧾", budget_amount=D("2000000"))
            db.add(op)
            await db.flush()
            inc = Income(household_id=nusa.id, user_id=self.me.id, amount=D("2000000"), description="modal op",
                         income_date=self.today)
            db.add(inc)
            await db.flush()
            db.add(Allocation(income_id=inc.id, envelope_id=op.id, amount=D("2000000")))
            await db.commit()
        self.rumah_id, self.rumah_dewi_id, self.nusa_id, self.op_id = rumah.id, rumah_dewi.id, nusa.id, op.id

        self.current = self.me
        app = FastAPI()
        ruang.install(app)
        for mod, prefix in ROUTERS:
            app.include_router(mod.router, prefix=prefix)
        app.include_router(ruang_routes.router)
        self.app = app

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    async def _isi(self, db, hid, uid, nama):
        env = Envelope(household_id=hid, name=nama, emoji="🍜", budget_amount=D("5000000"))
        tab = Envelope(household_id=hid, name=f"Tabungan {nama}", emoji="💰", budget_amount=D("0"),
                       purpose=PurposeType.saving)
        grp = EnvelopeGroup(household_id=hid, name=f"Grup {nama}")
        db.add_all([env, tab, grp])
        await db.flush()
        inc = Income(household_id=hid, user_id=uid, amount=D("6000000"), description=f"modal {nama}",
                     income_date=self.today)
        db.add(inc)
        await db.flush()
        txn = Transaction(envelope_id=env.id, user_id=uid, amount=D("10000"), description=f"lama {nama}",
                          transaction_date=self.today)
        goal = Goal(envelope_id=tab.id, name=f"Target {nama}", target_amount=D("1000000"))
        rec = RecurringTransaction(envelope_id=env.id, amount=D("150000"), description=f"Sewa {nama}",
                                   next_run=self.today + timedelta(days=3))
        db.add_all([Allocation(income_id=inc.id, envelope_id=env.id, amount=D("5000000")),
                    Allocation(income_id=inc.id, envelope_id=tab.id, amount=D("1000000")), txn, goal, rec])
        await db.flush()
        return {"env": env.id, "tab": tab.id, "grp": grp.id, "txn": txn.id, "goal": goal.id, "rec": rec.id}

    async def _req(self, method, path, json=None, params=None, header=None, user=None):
        self.current = user or self.me
        headers = {ruang.RUANG_HEADER: str(header)} if header else {}
        return await self.client.request(method, path, json=json, params=params, headers=headers)

    async def _batasan(self, **kw):
        r = await self._req("PUT", f"/ruang/{self.nusa_id}/anggota/{self.dewi.id}/batasan", kw, user=self.ani)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def _hitung(self, model, *where):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar()

    def _kode(self, r):
        try:
            return r.status_code, r.json().get("kode")
        except Exception:
            return r.status_code, None

    # 1. Tolak-bawaan ------------------------------------------------------
    async def test_karyawan_hanya_route_pencatatan_lewat_header(self):
        """Semua route ber-ruang (`ruang_aktif`), GET maupun bukan, menjawab 403 `khusus_admin` untuk karyawan dengan
        header ruang usaha, kecuali `KARYAWAN_BOLEH`. Route baru otomatis ikut tertolak."""
        def pakai(dep):
            return any(d.call is ruang.ruang_aktif or pakai(d) for d in dep.dependencies)
        diperiksa, bocor = 0, []
        for r in self.app.routes:
            if not isinstance(r, APIRoute) or "{" in r.path or not pakai(r.dependant):
                continue
            nama = f"{r.endpoint.__module__}.{r.endpoint.__name__}"
            for m in r.methods - {"HEAD"}:
                body = {} if m != "GET" else None
                res = await self._req(m, r.path, body, header=self.nusa_id, user=self.dewi)
                diperiksa += 1
                if nama in ruang.KARYAWAN_BOLEH:
                    if nama != "app.api.routes.envelopes.envelope_summary":   # menolak sendiri tanpa lihat_saldo
                        self.assertNotEqual(self._kode(res)[1], "khusus_admin", f"{m} {r.path}")
                elif self._kode(res) != (403, "khusus_admin"):
                    bocor.append((m, r.path, res.status_code))
        self.assertGreater(diperiksa, 40)
        self.assertEqual(bocor, [])

    async def test_karyawan_tidak_bisa_mengelola_objek_ruang_usaha(self):
        u = self.u
        cek = [
            ("PUT", f"/envelopes/{u['env']}", {"name": "Bahan", "budget_amount": "1"}, None),
            ("DELETE", f"/envelopes/{u['env']}", None, None),
            ("PATCH", f"/envelopes/groups/{u['grp']}", {"name": "x"}, None),
            ("DELETE", f"/envelopes/groups/{u['grp']}", None, None),
            ("POST", "/envelopes/transfer", None, {"from_id": str(u["env"]), "to_id": str(u["tab"]), "amount": "1"}),
            ("POST", "/goals/", {"envelope_id": str(u["tab"]), "name": "x", "target_amount": "1"}, None),
            ("PUT", f"/goals/{u['goal']}", {"name": "x"}, None),
            ("DELETE", f"/goals/{u['goal']}", None, None),
            ("POST", "/recurring/", {"envelope_id": str(u["env"]), "amount": "1", "description": "x",
                                     "next_run": str(self.today)}, None),
            ("POST", f"/recurring/{u['rec']}/skip", None, None),
            ("DELETE", f"/recurring/{u['rec']}", None, None),
        ]
        for method, path, body, params in cek:
            r = await self._req(method, path, body, params, user=self.dewi)
            self.assertEqual(self._kode(r), (403, "khusus_admin"), f"{method} {path}: {r.text[:200]}")
        r = await self._req("PUT", f"/envelopes/{u['env']}", {"name": "Bahan", "budget_amount": "5000000"},
                            user=self.ani)
        self.assertEqual(r.status_code, 200, r.text)   # admin tetap boleh

    async def test_ruang_keluarga_tidak_dibatasi(self):
        """Peran `member` di ruang keluarga (Rina) dan ruang keluarga karyawan (Dewi) tetap seperti sebelum R5."""
        r = await self._req("PUT", f"/envelopes/{self.k['env']}", {"name": "Makan Rumah", "budget_amount": "5000000"},
                            user=self.rina)
        self.assertEqual(r.status_code, 200, r.text)
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.k["env"]), "amount": "4000000",
                                                      "description": "belanja besar"}, user=self.rina)
        self.assertEqual(r.status_code, 201, r.text)
        await self._batasan(batas_nominal=1000, jam_kerja={"mulai": "00:00", "selesai": "00:01"})
        r = await self._req("GET", "/analytics/summary", user=self.dewi)   # tanpa header = ruang keluarganya
        self.assertNotEqual(self._kode(r)[1], "khusus_admin")
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.kd["env"]), "amount": "900000",
                                                      "description": "jajan besar"}, user=self.dewi)
        self.assertEqual(r.status_code, 201, r.text)

    # 2. Batasan per catatan ----------------------------------------------
    async def test_batasan_jenis_amplop_foto(self):
        await self._batasan(jenis_catatan=["pengeluaran"], amplop_ids=[str(self.u["env"])], foto_nota_di_atas=300000)
        ok = await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "250000",
                                                       "description": "terigu"}, user=self.dewi)
        self.assertEqual(ok.status_code, 201, ok.text)
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.op_id), "amount": "1000",
                                                      "description": "kardus"}, user=self.dewi)
        self.assertEqual(self._kode(r), (403, "amplop_tidak_diizinkan"))
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "400000",
                                                      "description": "terigu banyak"}, user=self.dewi)
        self.assertEqual(self._kode(r), (422, "perlu_foto_nota"))
        r = await self._req("POST", "/incomes/", {"amount": "100000", "source": "jual"}, header=self.nusa_id,
                            user=self.dewi)
        self.assertEqual(self._kode(r), (403, "jenis_tidak_diizinkan"))
        r = await self._req("POST", "/transactions/batch", {"items": [
            {"envelope_id": str(self.u["env"]), "amount": "1000", "description": "b1", "client_ref": "b-1"},
            {"envelope_id": str(self.op_id), "amount": "1000", "description": "b2", "client_ref": "b-2"},
            {"envelope_id": str(self.u["env"]), "amount": "400000", "description": "b3", "client_ref": "b-3"},
        ]}, user=self.dewi)
        hasil = sorted(r.json(), key=lambda x: x["index"])
        self.assertEqual([(x["ok"], x["kode"]) for x in hasil],
                         [(True, None), (False, "amplop_tidak_diizinkan"), (False, "perlu_foto_nota")])
        self.assertEqual(await self._hitung(Transaction, Transaction.description.in_(["b2", "b3", "kardus"])), 0)

    async def test_daftar_amplop_dan_transaksi_karyawan(self):
        async with self.Session() as db:
            db.add(Transaction(envelope_id=self.u["env"], user_id=self.dewi.id, amount=D("5000"),
                               description="catatan dewi", transaction_date=self.today))
            await db.commit()
        await self._batasan(amplop_ids=[str(self.u["env"])])
        r = await self._req("GET", "/envelopes/", header=self.nusa_id, user=self.dewi)
        self.assertEqual([(e["name"], e["budget_amount"]) for e in r.json()], [("Bahan", "0")])
        r = await self._req("GET", "/envelopes/summary", header=self.nusa_id, user=self.dewi)
        self.assertEqual(self._kode(r), (403, "khusus_admin"))
        r = await self._req("GET", "/transactions/", header=self.nusa_id, user=self.dewi)
        self.assertEqual([t["description"] for t in r.json()], ["catatan dewi"])   # bukan "lama Bahan" milik owner
        await self._batasan(amplop_ids=[str(self.u["env"])], lihat_saldo=True)
        r = await self._req("GET", "/envelopes/summary", header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([e["name"] for e in r.json()], ["Bahan"])
        r = await self._req("POST", "/transactions/suggest-envelope", {"description": "operasional"},
                            header=self.nusa_id, user=self.dewi)
        self.assertIn(r.json()["envelope_id"], (None, str(self.u["env"])))

    # 3. Antrean persetujuan ----------------------------------------------
    async def test_di_atas_batas_menjadi_draf_lalu_disetujui(self):
        await self._batasan(batas_nominal=1000000)
        body = {"envelope_id": str(self.u["env"]), "amount": "2500000", "description": "ayam 40kg",
                "client_ref": "ref-ayam"}
        r = await self._req("POST", "/transactions/", body, user=self.dewi)
        self.assertEqual((r.status_code, r.json()["kode"]), (202, "perlu_persetujuan"), r.text)
        draf_id = r.json()["draf_id"]
        r2 = await self._req("POST", "/transactions/", body, user=self.dewi)                # kirim ulang
        self.assertEqual((r2.status_code, r2.json()["draf_id"]), (202, draf_id))
        r3 = await self._req("POST", "/transactions/batch", {"items": [body]}, user=self.dewi)   # antrean offline
        self.assertEqual((r3.json()[0]["kode"], r3.json()[0]["draf_id"]), ("perlu_persetujuan", draf_id))
        self.assertEqual(await self._hitung(RuangDraf), 1)
        self.assertEqual(await self._hitung(Transaction, Transaction.description == "ayam 40kg"), 0)  # saldo tetap

        r = await self._req("GET", "/persetujuan/saya", header=self.nusa_id, user=self.dewi)
        self.assertEqual([(d["id"], d["status"]) for d in r.json()], [(draf_id, "menunggu")])
        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{draf_id}/setujui", user=self.dewi)
        self.assertEqual(self._kode(r), (403, "khusus_admin"))
        r = await self._req("GET", f"/ruang/{self.nusa_id}/persetujuan", user=self.ani)
        self.assertEqual([d["pencatat"] for d in r.json()], ["Dewi"])

        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{draf_id}/setujui", user=self.ani)
        self.assertEqual(r.status_code, 200, r.text)
        txn_id = r.json()["transaction_id"]
        async with self.Session() as db:
            txn = await db.get(Transaction, __import__("uuid").UUID(txn_id))
            d = await db.get(RuangDraf, __import__("uuid").UUID(draf_id))
        self.assertEqual((txn.user_id, txn.amount, d.status, str(d.hasil_id)), (self.dewi.id, D("2500000"),
                                                                                "disetujui", txn_id))
        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{draf_id}/setujui", user=self.ani)
        self.assertEqual(r.status_code, 409)
        r = await self._req("POST", "/transactions/", body, user=self.dewi)   # kirim ulang sesudah disetujui
        self.assertEqual((r.status_code, r.json()["id"]), (201, txn_id))
        self.assertEqual(await self._hitung(Transaction, Transaction.description == "ayam 40kg"), 1)
        self.assertEqual(await self._hitung(RuangAudit, RuangAudit.aksi == "draf_disetujui"), 1)

    async def test_draf_ditolak_dan_gagal_disetujui_kembali_menunggu(self):
        await self._batasan(batas_nominal=1000)
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "9000000",
                                                      "description": "melebihi dana"}, user=self.dewi)
        draf_id = r.json()["draf_id"]
        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{draf_id}/setujui", user=self.me)
        self.assertEqual(r.status_code, 403, r.text)          # dana tidak cukup: aturan pencatatan tetap berlaku
        async with self.Session() as db:
            self.assertEqual((await db.get(RuangDraf, __import__("uuid").UUID(draf_id))).status, "menunggu")
        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{draf_id}/tolak", {"alasan": "kebesaran"},
                            user=self.me)
        self.assertEqual(r.status_code, 200, r.text)
        r = await self._req("GET", "/persetujuan/saya", header=self.nusa_id, user=self.dewi)
        self.assertEqual([(d["status"], d["alasan"]) for d in r.json()], [("ditolak", "kebesaran")])
        self.assertEqual(await self._hitung(Transaction, Transaction.description == "melebihi dana"), 0)

    async def test_penjualan_di_atas_batas_disetujui_menjadi_pemasukan(self):
        await self._batasan(batas_nominal=500000)
        r = await self._req("POST", "/incomes/", {"amount": "900000", "source": "nasi box 30 pax", "allocations": [
            {"envelope_id": str(self.u["env"]), "amount": "900000"}]}, user=self.dewi)
        self.assertEqual((r.status_code, r.json()["kode"]), (202, "perlu_persetujuan"), r.text)
        self.assertEqual(await self._hitung(Income, Income.description == "nasi box 30 pax"), 0)
        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{r.json()['draf_id']}/setujui", user=self.ani)
        self.assertEqual(r.status_code, 200, r.text)
        async with self.Session() as db:
            inc = (await db.execute(select(Income).where(Income.description == "nasi box 30 pax"))).scalar_one()
            n_alloc = (await db.execute(select(func.count()).select_from(Allocation)
                                        .where(Allocation.income_id == inc.id))).scalar()
        self.assertEqual((inc.user_id, inc.household_id, str(inc.id), n_alloc),
                         (self.dewi.id, self.nusa_id, r.json()["income_id"], 1))

    # 4. Jam kerja, jendela ubah ------------------------------------------
    def _jendela(self, dari_jam, sampai_jam):
        now = datetime.now(JKT)
        return {"mulai": (now + timedelta(hours=dari_jam)).strftime("%H:%M"),
                "selesai": (now + timedelta(hours=sampai_jam)).strftime("%H:%M")}

    async def test_jam_kerja(self):
        await self._batasan(jam_kerja=self._jendela(2, 3), batas_nominal=100)
        r = await self._req("GET", "/envelopes/", header=self.nusa_id, user=self.dewi)
        self.assertEqual(self._kode(r), (403, "di_luar_jam_kerja"))
        self.assertIn("buka_lagi", r.json())
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "1",
                                                      "description": "di luar jam"}, user=self.dewi)
        self.assertEqual(self._kode(r), (403, "di_luar_jam_kerja"))
        r = await self._req("POST", "/transactions/batch", {"items": [
            {"envelope_id": str(self.u["env"]), "amount": "1", "description": "x", "client_ref": "jk-1"},
            {"envelope_id": str(self.kd["env"]), "amount": "1", "description": "rumah dewi", "client_ref": "jk-2"},
        ]}, user=self.dewi)
        self.assertEqual([x["kode"] for x in sorted(r.json(), key=lambda x: x["index"])], ["di_luar_jam_kerja", None])
        r = await self._req("GET", "/envelopes/", header=self.nusa_id, user=self.ani)      # admin tidak dibatasi
        self.assertEqual(r.status_code, 200)
        await self._batasan(jam_kerja=self._jendela(-1, 1))
        r = await self._req("GET", "/envelopes/", header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.status_code, 200, r.text)

    async def test_persetujuan_tidak_tertahan_jam_kerja_pencatat(self):
        await self._batasan(batas_nominal=1000)
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "5000",
                                                      "description": "draf pagi"}, user=self.dewi)
        draf_id = r.json()["draf_id"]
        await self._batasan(batas_nominal=1000, jam_kerja=self._jendela(2, 3))
        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{draf_id}/setujui", user=self.ani)
        self.assertEqual(r.status_code, 200, r.text)

    async def test_jendela_ubah(self):
        async with self.Session() as db:
            sendiri = Transaction(envelope_id=self.u["env"], user_id=self.dewi.id, amount=D("1"), description="s",
                                  transaction_date=self.today)
            kemarin = Transaction(envelope_id=self.u["env"], user_id=self.dewi.id, amount=D("1"), description="k",
                                  transaction_date=self.today,
                                  created_at=datetime.now(timezone.utc) - timedelta(days=1, hours=1))
            db.add_all([sendiri, kemarin])
            await db.commit()
        r = await self._req("DELETE", f"/transactions/{self.u['txn']}", user=self.dewi)   # milik owner
        self.assertEqual(self._kode(r), (403, "jendela_ubah_lewat"))
        r = await self._req("DELETE", f"/transactions/{kemarin.id}", user=self.dewi)
        self.assertEqual(self._kode(r), (403, "jendela_ubah_lewat"))
        r = await self._req("DELETE", f"/transactions/{sendiri.id}", user=self.dewi)
        self.assertEqual(r.status_code, 204, r.text)
        # Review PR #175 temuan 7: hapus oleh karyawan meninggalkan jejak untuk admin.
        self.assertEqual(await self._hitung(RuangAudit, RuangAudit.aksi == "catatan_dihapus",
                                            RuangAudit.actor_id == self.dewi.id), 1)
        r = await self._req("DELETE", f"/transactions/{kemarin.id}", user=self.ani)       # admin boleh
        self.assertEqual(r.status_code, 204, r.text)

    # 5. Anggota, undangan, audit -----------------------------------------
    async def test_admin_tidak_bisa_mengubah_owner_dan_validasi_batasan(self):
        r = await self._req("PATCH", f"/ruang/{self.nusa_id}/anggota/{self.me.id}", {"peran": "member"},
                            user=self.ani)
        self.assertEqual(self._kode(r), (403, "khusus_admin"))
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/anggota/{self.me.id}", user=self.ani)
        self.assertEqual(self._kode(r), (403, "khusus_admin"))
        r = await self._req("PUT", f"/ruang/{self.nusa_id}/anggota/{self.ani.id}/batasan", {}, user=self.me)
        self.assertEqual(r.status_code, 422)
        r = await self._req("PUT", f"/ruang/{self.nusa_id}/anggota/{self.dewi.id}/batasan",
                            {"amplop_ids": [str(self.k["env"])]}, user=self.ani)   # amplop ruang keluarga
        self.assertEqual(r.status_code, 422)
        r = await self._req("GET", f"/ruang/{self.nusa_id}/anggota", user=self.dewi)
        self.assertEqual(self._kode(r), (403, "khusus_admin"))
        for path in (f"/ruang/{self.nusa_id}/anggota", f"/ruang/{self.rumah_id}/anggota"):
            r = await self._req("GET", path, user=self.orang)
            self.assertEqual(r.status_code, 404)
        r = await self._req("GET", f"/ruang/{self.rumah_id}/anggota", user=self.me)   # ruang keluarga: /household
        self.assertEqual(r.status_code, 404)
        r = await self._req("PATCH", f"/ruang/{self.nusa_id}/anggota/{self.dewi.id}", {"jabatan": "Kasir"},
                            user=self.ani)
        self.assertEqual(r.status_code, 200)
        r = await self._req("GET", f"/ruang/{self.nusa_id}/anggota", user=self.ani)
        dewi = next(a for a in r.json() if a["nama"] == "Dewi")
        self.assertEqual((dewi["peran"], dewi["jabatan"], dewi["batasan"]["lihat_saldo"]), ("member", "Kasir", False))
        self.assertIsNone(next(a for a in r.json() if a["nama"] == "Saya")["batasan"])

    async def test_undangan_sekali_pakai_dan_ruang_keluarga_tidak_tersentuh(self):
        r = await self._req("POST", f"/ruang/{self.nusa_id}/undangan", {"peran": "member"}, user=self.dewi)
        self.assertEqual(self._kode(r), (403, "khusus_admin"))
        r = await self._req("POST", f"/ruang/{self.rumah_id}/undangan", {}, user=self.me)
        self.assertEqual(r.status_code, 404)
        r = await self._req("POST", f"/ruang/{self.nusa_id}/undangan", {"peran": "member"}, user=self.ani)
        kode = r.json()["kode"]
        r = await self._req("POST", "/ruang/gabung", {"kode": kode.lower()}, user=self.rina)
        self.assertEqual((r.status_code, r.json()["peran"]), (200, "member"), r.text)
        r = await self._req("POST", "/ruang/gabung", {"kode": kode}, user=self.orang)
        self.assertEqual(r.status_code, 400)
        async with self.Session() as db:
            self.assertEqual(await ruang.ruang_keluarga_id(db, self.rina.id), self.rumah_id)
            db.add(RuangUndangan(household_id=self.nusa_id, kode="RUBASI000001", peran="admin",
                                 kedaluwarsa=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await db.commit()
        r = await self._req("POST", "/ruang/gabung", {"kode": "RUBASI000001"}, user=self.orang)
        self.assertEqual(r.status_code, 400)
        # Rina kini karyawan di Dapur Nusa: dibatasi di sana, tidak di ruang keluarga Saya.
        r = await self._req("PUT", f"/envelopes/{self.u['env']}", {"name": "x", "budget_amount": "1"}, user=self.rina)
        self.assertEqual(self._kode(r), (403, "khusus_admin"))
        aksi = {a for (a,) in (await self._all(select(RuangAudit.aksi)))}
        self.assertTrue({"undangan_dibuat", "anggota_bergabung"} <= aksi)

    async def _all(self, stmt):
        async with self.Session() as db:
            return (await db.execute(stmt)).all()

    async def test_keluar_membatalkan_draf_dan_menutup_akses(self):
        await self._batasan(batas_nominal=1000)
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "5000",
                                                      "description": "draf terakhir"}, user=self.dewi)
        self.assertEqual(r.status_code, 202)
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/anggota/{self.me.id}", user=self.me)
        self.assertEqual(self._kode(r), (403, "khusus_admin"))   # owner tidak bisa keluar
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/anggota/{self.dewi.id}", user=self.dewi)
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual(await self._hitung(RuangDraf, RuangDraf.status == "dibatalkan"), 1)
        self.assertEqual(await self._hitung(RuangBatasan, RuangBatasan.user_id == self.dewi.id), 0)
        r = await self._req("GET", "/envelopes/", header=self.nusa_id, user=self.dewi)
        self.assertEqual(self._kode(r), (403, "ruang_tidak_diizinkan"))
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "1",
                                                      "description": "x"}, user=self.dewi)
        self.assertEqual(r.status_code, 404)
        async with self.Session() as db:   # catatan lama tetap milik ruang usaha
            self.assertEqual(await ruang.ruang_keluarga_id(db, self.dewi.id), self.rumah_dewi_id)

    async def test_reset_ruang_usaha_tercatat_di_audit(self):
        await self._batasan(batas_nominal=1000)
        await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "500",
                                                  "description": "kecil"}, user=self.dewi)
        await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "5000",
                                                  "description": "besar"}, user=self.dewi)
        r = await self._req("POST", "/user/reset", {}, header=self.nusa_id, user=self.me)
        self.assertEqual(r.status_code, 200, r.text)
        rows = await self._all(select(RuangAudit.rincian).where(RuangAudit.aksi == "reset_ruang"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0]["catatan_per_pencatat"], {str(self.me.id): 1, str(self.dewi.id): 1})
        self.assertEqual(await self._hitung(RuangDraf, RuangDraf.status == "menunggu"), 0)
        r = await self._req("GET", f"/ruang/{self.nusa_id}/audit", user=self.ani)
        self.assertIn("reset_ruang", [a["aksi"] for a in r.json()])

    # 6. Tindak lanjut review keamanan PR #175 -----------------------------
    async def test_pesan_galat_tidak_membocorkan_saldo(self):
        """Temuan 1: tanpa `lihat_saldo`, pesan dana/limit tidak berisi angka (saldo tidak bisa ditebak)."""
        await self._batasan()
        body = {"envelope_id": str(self.u["env"]), "amount": "9000000", "description": "kebanyakan"}
        r = await self._req("POST", "/transactions/", body, user=self.dewi)
        self.assertEqual(r.status_code, 403, r.text)
        self.assertNotRegex(r.json()["detail"], r"\d")
        r = await self._req("POST", "/transactions/batch", {"items": [{**body, "client_ref": "bocor-1"}]},
                            user=self.dewi)
        self.assertNotRegex(r.json()[0]["error"], r"\d")
        await self._batasan(lihat_saldo=True)
        r = await self._req("POST", "/transactions/", body, user=self.dewi)
        self.assertIn("Sisa", r.json()["detail"])
        r = await self._req("POST", "/transactions/", body, user=self.ani)        # admin: pesan biasa
        self.assertIn("Sisa", r.json()["detail"])

    async def test_karyawan_tidak_bisa_menaikkan_limit_harian(self):
        """Temuan 2: `raise_daily_limit` diabaikan untuk karyawan, di jalur tunggal dan antrean offline."""
        async with self.Session() as db:
            env = await db.get(Envelope, self.u["env"])
            env.daily_limit = D("50000")
            await db.commit()
        await self._batasan()
        body = {"envelope_id": str(self.u["env"]), "amount": "60000", "description": "lewat limit",
                "raise_daily_limit": True}
        r = await self._req("POST", "/transactions/", body, user=self.dewi)
        self.assertEqual(r.status_code, 403, r.text)
        self.assertNotRegex(r.json()["detail"], r"\d")
        r = await self._req("POST", "/transactions/batch", {"items": [{**body, "client_ref": "lim-1"}]},
                            user=self.dewi)
        self.assertFalse(r.json()[0]["ok"])
        self.assertEqual(await self._hitung(Transaction, Transaction.description == "lewat limit"), 0)
        r = await self._req("POST", "/transactions/", body, user=self.ani)         # admin tetap boleh menaikkan
        self.assertEqual(r.status_code, 201, r.text)

    async def test_penjualan_karyawan_harus_dialokasikan_penuh(self):
        """Temuan 3: sisa penjualan tidak boleh jatuh ke (atau membuat) Tabungan di luar amplop yang diizinkan."""
        await self._batasan(amplop_ids=[str(self.u["env"])])
        n_amplop = await self._hitung(Envelope, Envelope.household_id == self.nusa_id)
        for body in ({"amount": "100000", "source": "jual sisa", "allocations": [
                          {"envelope_id": str(self.u["env"]), "amount": "10000"}]},
                     {"amount": "100000", "source": "jual sisa"}):
            r = await self._req("POST", "/incomes/", body, header=self.nusa_id, user=self.dewi)
            self.assertEqual(self._kode(r), (422, "alokasi_tidak_penuh"), r.text)
        self.assertEqual(await self._hitung(Income, Income.description == "jual sisa"), 0)
        self.assertEqual(await self._hitung(Envelope, Envelope.household_id == self.nusa_id), n_amplop)
        r = await self._req("POST", "/incomes/", {"amount": "100000", "source": "jual penuh", "allocations": [
            {"envelope_id": str(self.u["env"]), "amount": "100000"}]}, user=self.dewi)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self._req("POST", "/incomes/", {"amount": "100000", "source": "owner sisa", "allocations": [
            {"envelope_id": str(self.u["env"]), "amount": "10000"}]}, user=self.me)   # owner: sisa ke Tabungan
        self.assertEqual(r.status_code, 201, r.text)

    async def test_draf_penjualan_divalidasi_dan_idempoten(self):
        """Temuan 5 dan 6: alokasi tidak sah ditolak sebelum menjadi draf; kiriman ulang `client_ref` → draf sama."""
        await self._batasan(batas_nominal=500000)
        r = await self._req("POST", "/incomes/", {"amount": "900000", "source": "salah amplop", "allocations": [
            {"envelope_id": str(self.op_id), "amount": "900000"},
            {"envelope_id": str(self.k["env"]), "amount": "0"}]}, user=self.dewi)
        self.assertIn(r.status_code, (400, 404), r.text)
        self.assertEqual(await self._hitung(RuangDraf), 0)
        body = {"amount": "900000", "source": "nasi box", "client_ref": "jual-1", "allocations": [
            {"envelope_id": str(self.u["env"]), "amount": "900000"}]}
        a = await self._req("POST", "/incomes/", body, user=self.dewi)
        b = await self._req("POST", "/incomes/", body, user=self.dewi)
        self.assertEqual((a.status_code, b.status_code), (202, 202), a.text)
        self.assertEqual(a.json()["draf_id"], b.json()["draf_id"])
        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{a.json()['draf_id']}/setujui", user=self.ani)
        self.assertEqual(r.status_code, 200, r.text)
        c = await self._req("POST", "/incomes/", body, user=self.dewi)      # sesudah disetujui
        self.assertEqual((c.status_code, c.json()["status"]), (202, "disetujui"))
        self.assertEqual(await self._hitung(Income, Income.description == "nasi box"), 1)

    async def test_notifikasi_target_untuk_owner_bukan_karyawan(self):
        """Temuan 4: notifikasi target (berisi angka) dari penjualan karyawan dikirim ke owner, juga saat draf
        disetujui; pencatat biasa tetap menerimanya sendiri."""
        penerima = []

        async def tangkap(db, user, before):
            penerima.append(user.id)
            return []
        await self._batasan(batas_nominal=500000)
        with patch("app.services.goal_notify.notify_goals_reached", tangkap):
            await self._req("POST", "/incomes/", {"amount": "100000", "source": "jual 1", "allocations": [
                {"envelope_id": str(self.u["env"]), "amount": "100000"}]}, user=self.dewi)
            r = await self._req("POST", "/incomes/", {"amount": "900000", "source": "jual 2", "allocations": [
                {"envelope_id": str(self.u["env"]), "amount": "900000"}]}, user=self.dewi)
            await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{r.json()['draf_id']}/setujui", user=self.ani)
            await self._req("POST", "/incomes/", {"amount": "1000", "source": "admin"}, header=self.nusa_id,
                            user=self.ani)
        self.assertEqual(penerima, [self.me.id, self.me.id, self.ani.id])


if __name__ == "__main__":
    unittest.main()
