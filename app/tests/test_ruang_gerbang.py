"""Plugin R2 — gerbang refactor `ruang_aktif` (03-workflow.md, Gerbang R; 04-kontrak-api.md §1).

Setiap endpoint GET tanpa parameter path dipanggil lewat HTTP untuk user dengan satu ruang
keluarga, lalu user itu diberi ruang usaha kedua yang berisi datanya sendiri. Dikunci:

1. Tanpa header, setiap jawaban identik dengan sebelum ruang kedua ada: tidak ada galat
   "lebih dari satu keanggotaan" dan tidak ada data ruang usaha yang bocor ke ruang keluarga.
2. Dengan header ruang usaha, endpoint baca yang memakai ruang tidak lagi menampilkan data
   ruang keluarga (bukti header benar-benar dipakai, bukan diabaikan).
3. Dengan header ruang orang lain, setiap endpoint ber-ruang menjawab 403 `ruang_tidak_diizinkan`.
4. Anggota lain household yang sama (tanpa ruang kedua) juga tidak berubah.

Endpoint yang jawabannya berubah antara dua panggilan berturut-turut (waktu, acak) dibuang
dari perbandingan; endpoint yang galat sebelum ruang kedua ada juga dibuang (dicetak).

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_ruang_gerbang -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
JKT = ZoneInfo("Asia/Jakarta")

if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI
    from fastapi.routing import APIRoute

    from app.api.routes import (
        advisor, analytics, balance_check, dashboard, envelopes, export, goals, household, incomes,
        kotak_struk, link, notifications, recurring, snapshots, transactions, user_settings,
    )
    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        Allocation, AppSetting, Envelope, EnvelopeGroup, Goal, Household, HouseholdMember, HouseholdRole, HouseholdType,
        Income, PurposeType, RecurringTransaction, Transaction, User,
    )
    from app.services import ruang
    from app.tests.test_advisor_dashboard_integration import FakeRedis

    ROUTERS = (
        (advisor, "/advisor"), (analytics, "/analytics"), (balance_check, "/balance-check"),
        (dashboard, "/dashboard"), (envelopes, "/envelopes"), (export, "/export"), (goals, "/goals"),
        (household, "/household"), (incomes, "/incomes"), (kotak_struk, "/kotak-struk"),
        (notifications, "/notifications"), (recurring, "/recurring"), (snapshots, "/snapshots"),
        (transactions, "/transactions"), (user_settings, "/user"),
    )

if HAS_AIOSQLITE:
    class _Redis(FakeRedis):
        """FakeRedis + close/aclose untuk route lama (link, household) yang menutup klien sendiri."""
        async def close(self):
            pass

        async def aclose(self):
            pass


# Waktu pembuatan jawaban (generated_at, exported_at, …) berbeda per detik; disamakan sebelum dibandingkan.
_WAKTU = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")


def _normal(body):
    return json.loads(_WAKTU.sub("<waktu>", json.dumps(body, ensure_ascii=False, sort_keys=True)))


# Penanda data ruang usaha: tidak boleh muncul di jawaban mana pun tanpa header.
PENANDA_USAHA = ("Bahan Baku Nusa", "terigu nusa", "Omzet Nusa", "Sewa Kios Nusa", "Mixer Nusa")
PENANDA_KELUARGA = ("Makan Rumah", "kopi rumah")


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RuangGerbangTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.redis = _Redis()
        p = patch("redis.asyncio.from_url", return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)

        today = datetime.now(JKT).date()
        async with self.Session() as db:
            me = User(name="Saya", payday_day=1, timezone="Asia/Jakarta", plan="pro")
            rina = User(name="Rina", payday_day=1, timezone="Asia/Jakarta")
            orang = User(name="Orang", payday_day=1, timezone="Asia/Jakarta")
            rumah, asing = Household(name="Rumah"), Household(name="Rumah orang")
            db.add_all([me, rina, orang, rumah, asing])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=me.id, household_id=rumah.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=rina.id, household_id=rumah.id, role=HouseholdRole.member),
                HouseholdMember(user_id=orang.id, household_id=asing.id, role=HouseholdRole.owner),
            ])
            self.id_rumah = await self._isi_ruang(db, rumah.id, me.id, today, "Makan Rumah", "kopi rumah", "Gaji Rumah",
                                  "Internet Rumah", "Liburan Rumah")
            self.id_asing = await self._isi_ruang(db, asing.id, orang.id, today, "Makan Orang", "kopi orang", "Gaji Orang",
                                  "Internet Orang", "Liburan Orang")
            db.add(AppSetting(key="advisor_v2_users", value="*"))
            await db.commit()
        self.me, self.rina, self.orang = me, rina, orang
        self.rumah_id, self.asing_id = rumah.id, asing.id
        self.today = today

        self.current = me
        app = FastAPI()
        ruang.install(app)
        for mod, prefix in ROUTERS:
            app.include_router(mod.router, prefix=prefix)
        app.include_router(link.router, prefix="/auth")  # gabung akun (POST saja, tidak ikut potret GET)
        self.paths = sorted({
            r.path for r in app.routes
            if isinstance(r, APIRoute) and "GET" in r.methods and "{" not in r.path
        })

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    @staticmethod
    async def _isi_ruang(db, hid, uid, today, amplop, belanja, gaji_desc, langganan, target):
        env = Envelope(household_id=hid, name=amplop, emoji="🍜", budget_amount=D("0"), classification="needs")
        tab = Envelope(household_id=hid, name=target, emoji="💰", budget_amount=D("0"),
                       purpose=PurposeType.saving)
        db.add_all([env, tab])
        await db.flush()
        inc = Income(household_id=hid, user_id=uid, amount=D("5000000"), description=gaji_desc,
                     income_date=today)
        db.add(inc)
        await db.flush()
        grp = EnvelopeGroup(household_id=hid, name=f"Grup {amplop}")
        txn = Transaction(envelope_id=env.id, user_id=uid, amount=D("35000"), description=belanja,
                          transaction_date=today)
        goal = Goal(envelope_id=tab.id, name=target, target_amount=D("6000000"))
        rec = RecurringTransaction(envelope_id=env.id, amount=D("150000"), description=langganan,
                                   next_run=today + timedelta(days=3))
        db.add_all([
            Allocation(income_id=inc.id, envelope_id=env.id, amount=D("4000000")),
            Allocation(income_id=inc.id, envelope_id=tab.id, amount=D("1000000")),
            grp, txn, goal, rec,
        ])
        await db.flush()
        return {"env": env.id, "tab": tab.id, "grp": grp.id, "txn": txn.id, "goal": goal.id, "rec": rec.id}

    async def _beri_ruang_usaha(self, bukakan=True):
        async with self.Session() as db:
            usaha = Household(name="Dapur Nusa", type=HouseholdType.USAHA)
            db.add(usaha)
            if bukakan:   # R4: ruang usaha hanya terbuka untuk user di flag `ruang_usaha_users`
                db.add(AppSetting(key=ruang.FLAG_RUANG_USAHA, value=str(self.me.id)))
            await db.flush()
            # Lebih tua dari keanggotaan keluarga: urutan tidak boleh menentukan ruang keluarga.
            db.add(HouseholdMember(user_id=self.me.id, household_id=usaha.id, role=HouseholdRole.owner,
                                   created_at=datetime.now(timezone.utc) - timedelta(days=400)))
            self.id_usaha = await self._isi_ruang(db, usaha.id, self.me.id, self.today, "Bahan Baku Nusa",
                                                  "terigu nusa", "Omzet Nusa", "Sewa Kios Nusa", "Mixer Nusa")
            await db.commit()
        self.usaha_id = usaha.id

    async def _jawab(self, path, user, header=None):
        self.current = user
        headers = {ruang.RUANG_HEADER: header} if header else {}
        r = await self.client.get(path, headers=headers)
        try:
            body = _normal(r.json())
        except ValueError:
            body = r.text
        return r.status_code, body

    async def _potret(self, user, header=None):
        return {p: await self._jawab(p, user, header) for p in self.paths}

    async def _stabil(self, user):
        """Potret sebelum ruang kedua: hanya endpoint 200 yang jawabannya sama dua kali berturut-turut."""
        a, b = await self._potret(user), await self._potret(user)
        stabil = {p: a[p] for p in self.paths if a[p][0] == 200 and a[p] == b[p]}
        dibuang = sorted(set(self.paths) - set(stabil))
        return stabil, dibuang

    async def test_ruang_kedua_tidak_mengubah_apa_pun_tanpa_header(self):
        sebelum_me, dibuang = await self._stabil(self.me)
        sebelum_rina, _ = await self._stabil(self.rina)
        self.assertGreaterEqual(len(sebelum_me), 25, f"terlalu sedikit endpoint teruji; dibuang: {dibuang}")
        await self._beri_ruang_usaha()

        for user, sebelum in ((self.me, sebelum_me), (self.rina, sebelum_rina)):
            sesudah = await self._potret(user)
            for p, jawaban in sebelum.items():
                self.assertEqual(sesudah[p], jawaban, f"{p} berubah untuk {user.name} setelah ruang kedua ada")
                teks = json.dumps(sesudah[p][1], ensure_ascii=False)
                for penanda in PENANDA_USAHA:
                    self.assertNotIn(penanda, teks, f"data ruang usaha bocor di {p}")

    async def test_header_ruang_usaha_membaca_ruang_usaha(self):
        await self._beri_ruang_usaha()
        keluarga = await self._potret(self.me)
        usaha = await self._potret(self.me, header=str(self.usaha_id))
        berpindah = []
        for p in self.paths:
            teks_kel = json.dumps(keluarga[p][1], ensure_ascii=False)
            if keluarga[p][0] != 200 or not any(x in teks_kel for x in PENANDA_KELUARGA):
                continue  # endpoint tidak menampilkan data ber-ruang
            self.assertEqual(usaha[p][0], 200, f"{p} dengan header ruang usaha: {usaha[p]}")
            teks_usaha = json.dumps(usaha[p][1], ensure_ascii=False)
            for penanda in PENANDA_KELUARGA:
                self.assertNotIn(penanda, teks_usaha, f"{p} mengabaikan header ruang")
            berpindah.append(p)
        self.assertGreaterEqual(len(berpindah), 8, f"terlalu sedikit endpoint ber-ruang: {berpindah}")

    async def test_reset_hanya_menghapus_ruang_yang_direset(self):
        from sqlalchemy import func, select
        await self._beri_ruang_usaha()
        self.current = self.me
        r = await self.client.post("/user/reset", json={})
        self.assertEqual(r.status_code, 200, r.text)
        async with self.Session() as db:
            sisa_inc = (await db.execute(select(Income.description).where(Income.user_id == self.me.id))).scalars().all()
            sisa_env = (await db.execute(select(Envelope.name).where(Envelope.household_id == self.usaha_id))).scalars().all()
            n_txn = (await db.execute(select(func.count(Transaction.id)).where(Transaction.description == "terigu nusa"))).scalar()
        self.assertEqual(sisa_inc, ["Omzet Nusa"], "reset ruang keluarga menghapus pemasukan ruang lain")
        self.assertEqual(sorted(sisa_env), ["Bahan Baku Nusa", "Mixer Nusa"])
        self.assertEqual(n_txn, 1)

    async def test_reset_dengan_header_ruang_orang_lain_ditolak(self):
        await self._beri_ruang_usaha()
        self.current = self.me
        r = await self.client.post("/user/reset", json={}, headers={ruang.RUANG_HEADER: str(self.asing_id)})
        self.assertEqual((r.status_code, r.json().get("kode")), (403, "ruang_tidak_diizinkan"))

    async def test_reset_dengan_header_ruang_usaha_hanya_menghapus_ruang_usaha(self):
        # R3 (keputusan A): objek tanpa induk, termasuk reset, memakai ruang dari header yang sah.
        from sqlalchemy import select
        await self._beri_ruang_usaha()
        self.current = self.me
        r = await self.client.post("/user/reset", json={}, headers={ruang.RUANG_HEADER: str(self.usaha_id)})
        self.assertEqual(r.status_code, 200, r.text)
        async with self.Session() as db:
            sisa_inc = (await db.execute(select(Income.description).where(Income.user_id == self.me.id))).scalars().all()
            sisa_usaha = (await db.execute(select(Envelope.id).where(Envelope.household_id == self.usaha_id))).all()
        self.assertEqual(sisa_inc, ["Gaji Rumah"])
        self.assertEqual(sisa_usaha, [])

    async def _idor(self, ids, headers=None):
        """Setiap endpoint ber-ID dicoba terhadap objek `ids`; jawabannya tidak boleh 2xx."""
        self.current = self.me
        headers = headers or {}
        body_env = {"name": "Dibajak", "budget_amount": "1"}
        coba = [
            ("put", f"/envelopes/{ids['env']}", body_env), ("delete", f"/envelopes/{ids['env']}", None),
            ("patch", f"/envelopes/groups/{ids['grp']}", {"name": "Dibajak"}),
            ("delete", f"/envelopes/groups/{ids['grp']}", None),
            ("delete", f"/transactions/{ids['txn']}", None),
            ("put", f"/recurring/{ids['rec']}", {"envelope_id": str(ids["env"]), "amount": "1", "description": "Dibajak",
                                                "next_run": str(self.today)}),
            ("delete", f"/recurring/{ids['rec']}", None),
            ("post", f"/recurring/{ids['rec']}/pay", {}), ("post", f"/recurring/{ids['rec']}/skip", None),
            ("post", f"/recurring/{ids['rec']}/mark-paid", None),
            ("get", f"/goals/{ids['goal']}", None), ("put", f"/goals/{ids['goal']}", {"name": "Dibajak"}),
            ("delete", f"/goals/{ids['goal']}", None),
            ("post", "/envelopes/transfer", None),
            # R3: objek baru yang induknya amplop household lain
            ("post", "/transactions/", {"envelope_id": str(ids["env"]), "amount": "1000", "description": "Dibajak"}),
            ("post", "/goals/", {"envelope_id": str(ids["tab"]), "name": "Dibajak", "target_amount": "1000"}),
            ("post", "/recurring/", {"envelope_id": str(ids["env"]), "amount": "1000", "description": "Dibajak",
                                     "next_run": str(self.today)}),
            ("post", "/incomes/", {"amount": "1000", "source": "Dibajak",
                                   "allocations": [{"envelope_id": str(ids["env"]), "amount": "1000"}]}),
        ]
        for method, path, body in coba:
            kw = {"headers": headers}
            if method == "post" and path == "/envelopes/transfer":
                kw["params"] = {"from_id": str(ids["env"]), "to_id": str(ids["tab"]), "amount": "1000"}
            elif body is not None:
                kw["json"] = body
            r = await self.client.request(method.upper(), path, **kw)
            # Kontrak §1: objek di ruang orang lain = 404 biasa, tanpa membocorkan keberadaannya (review PR #171).
            # 422 berarti permintaan tidak sampai ke pemeriksaan ruang: tesnya yang salah, bukan bukti aman.
            self.assertEqual(r.status_code, 404, f"{method} {path} {headers}: {r.status_code} {r.text[:200]}")

    async def _utuh(self, ids, amplop):
        from sqlalchemy import select
        async with self.Session() as db:
            env = await db.get(Envelope, ids["env"])
            txn = await db.get(Transaction, ids["txn"])
            goal = await db.get(Goal, ids["goal"])
            rec = await db.get(RecurringTransaction, ids["rec"])
            grp = await db.get(EnvelopeGroup, ids["grp"])
            n_alloc = len((await db.execute(select(Allocation).where(Allocation.envelope_id == ids["env"]))).all())
        self.assertEqual((env.name, env.is_active), (amplop, True))
        self.assertFalse(txn.is_deleted)
        self.assertNotEqual(goal.name, "Dibajak")
        self.assertTrue(rec.is_active)
        self.assertEqual(rec.amount, D("150000"))
        self.assertTrue(grp.name.startswith("Grup "))
        self.assertEqual(n_alloc, 1, "transfer/pemasukan menyentuh amplop ruang lain")
        async with self.Session() as db:
            for model, kolom in ((Transaction, Transaction.description), (Goal, Goal.name),
                                 (RecurringTransaction, RecurringTransaction.description), (Income, Income.description)):
                n = len((await db.execute(select(model).where(kolom == "Dibajak"))).all())
                self.assertEqual(n, 0, f"{model.__name__} dibuat di household orang lain")

    async def test_idor_objek_household_orang_lain(self):
        await self._beri_ruang_usaha()
        await self._idor(self.id_asing)
        await self._idor(self.id_asing, {ruang.RUANG_HEADER: str(self.usaha_id)})
        await self._utuh(self.id_asing, "Makan Orang")

    # ── R3: ruang dari objek saat menulis ──────────────────────────────
    async def _req(self, method, path, json=None, params=None, header=None, user=None):
        self.current = user or self.me
        headers = {ruang.RUANG_HEADER: str(header)} if header else {}
        return await self.client.request(method, path, json=json, params=params, headers=headers)

    async def test_tulis_objek_ruang_usaha_sendiri_dari_objek(self):
        """Tanpa header (atau dengan header ruang keluarga), objek ruang usaha milik user bisa diubah: ruang
        ditentukan objeknya, bukan header."""
        from sqlalchemy import select
        await self._beri_ruang_usaha()
        u = self.id_usaha
        for header in (None, self.rumah_id):
            r = await self._req("PUT", f"/goals/{u['goal']}", {"name": "Mixer Baru"}, header=header)
            self.assertEqual(r.status_code, 200, r.text)
        cek = [
            ("PATCH", f"/envelopes/groups/{u['grp']}", {"name": "Grup Usaha"}, None, 200),
            ("PUT", f"/envelopes/{u['env']}", {"name": "Bahan Baku Nusa", "budget_amount": "5"}, None, 200),
            ("PUT", f"/recurring/{u['rec']}", {"envelope_id": str(u["env"]), "amount": "175000",
                                               "description": "Sewa Kios Nusa", "next_run": str(self.today)}, None, 200),
            ("POST", f"/recurring/{u['rec']}/skip", None, None, 200),
            ("POST", "/envelopes/transfer", None, {"from_id": str(u["env"]), "to_id": str(u["tab"]), "amount": "1000"}, 200),
            ("DELETE", f"/transactions/{u['txn']}", None, None, 204),
        ]
        for method, path, body, params, status in cek:
            r = await self._req(method, path, body, params)
            self.assertEqual(r.status_code, status, f"{method} {path}: {r.text[:200]}")
        r = await self._req("POST", "/transactions/", {"envelope_id": str(u["env"]), "amount": "1000",
                                                      "description": "gula nusa"})
        self.assertEqual(r.status_code, 201, r.text)
        async with self.Session() as db:
            txn = (await db.execute(select(Transaction).where(Transaction.description == "gula nusa"))).scalar_one()
            env = await db.get(Envelope, txn.envelope_id)
        self.assertEqual(env.household_id, self.usaha_id)

    async def test_objek_baru_tanpa_induk_ke_ruang_header(self):
        from sqlalchemy import select
        await self._beri_ruang_usaha()
        r = await self._req("POST", "/envelopes/", {"name": "Kemasan", "budget_amount": "100000"}, header=self.usaha_id)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self._req("POST", "/envelopes/", {"name": "Jajan Anak", "budget_amount": "100000"})
        self.assertEqual(r.status_code, 201, r.text)
        r = await self._req("POST", "/envelopes/groups", {"name": "Operasional"}, header=self.usaha_id)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self._req("POST", "/incomes/", {"amount": "250000", "source": "Penjualan pagi"}, header=self.usaha_id)
        self.assertEqual(r.status_code, 201, r.text)
        async with self.Session() as db:
            def hh(model, kolom, nilai):
                return select(model.household_id).where(kolom == nilai)
            self.assertEqual((await db.execute(hh(Envelope, Envelope.name, "Kemasan"))).scalar_one(), self.usaha_id)
            self.assertEqual((await db.execute(hh(Envelope, Envelope.name, "Jajan Anak"))).scalar_one(), self.rumah_id)
            self.assertEqual((await db.execute(hh(EnvelopeGroup, EnvelopeGroup.name, "Operasional"))).scalar_one(),
                             self.usaha_id)
            self.assertEqual((await db.execute(hh(Income, Income.description, "Penjualan pagi"))).scalar_one(),
                             self.usaha_id)
        r = await self._req("POST", "/envelopes/", {"name": "Bajakan", "budget_amount": "100000"}, header=self.asing_id)
        self.assertEqual((r.status_code, r.json().get("kode")), (403, "ruang_tidak_diizinkan"))

    async def test_permintaan_lintas_ruang_ditolak(self):
        from sqlalchemy import func, select
        await self._beri_ruang_usaha()
        k, u = self.id_rumah, self.id_usaha
        r = await self._req("POST", "/envelopes/transfer", params={"from_id": str(k["env"]), "to_id": str(u["env"]),
                                                                    "amount": "1000"})
        self.assertEqual((r.status_code, r.json().get("kode")), (400, "lintas_ruang"), r.text)
        r = await self._req("POST", "/incomes/", {"amount": "2000", "source": "Campur", "allocations": [
            {"envelope_id": str(k["env"]), "amount": "1000"}, {"envelope_id": str(u["env"]), "amount": "1000"}]})
        self.assertEqual((r.status_code, r.json().get("kode")), (400, "lintas_ruang"), r.text)
        # Langganan ruang keluarga tidak bisa dipindah ke amplop ruang usaha.
        r = await self._req("PUT", f"/recurring/{k['rec']}", {"envelope_id": str(u["env"]), "amount": "150000",
                                                             "description": "Internet Rumah", "next_run": str(self.today)})
        self.assertIn(r.status_code, (400, 404), r.text)
        async with self.Session() as db:
            n_inc = (await db.execute(select(func.count(Income.id)).where(Income.description == "Campur"))).scalar()
            rec = await db.get(RecurringTransaction, k["rec"])
        self.assertEqual(n_inc, 0)
        self.assertEqual(rec.envelope_id, k["env"])

    async def test_antrean_offline_per_item_ke_ruang_amplopnya(self):
        from sqlalchemy import select
        await self._beri_ruang_usaha()
        k, u, a = self.id_rumah, self.id_usaha, self.id_asing
        r = await self._req("POST", "/transactions/batch", {"items": [
            {"envelope_id": str(k["env"]), "amount": "1000", "description": "offline rumah", "client_ref": "off-1"},
            {"envelope_id": str(u["env"]), "amount": "1000", "description": "offline nusa", "client_ref": "off-2"},
            {"envelope_id": str(a["env"]), "amount": "1000", "description": "offline orang", "client_ref": "off-3"},
        ]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([x["ok"] for x in sorted(r.json(), key=lambda x: x["index"])], [True, True, False])
        async with self.Session() as db:
            rows = (await db.execute(select(Transaction.description, Envelope.household_id)
                                     .join(Envelope, Envelope.id == Transaction.envelope_id)
                                     .where(Transaction.description.like("offline %")))).all()
        self.assertEqual(dict(rows), {"offline rumah": self.rumah_id, "offline nusa": self.usaha_id})

    async def test_kuota_basic_hanya_ruang_keluarga(self):
        from datetime import date as _date
        from sqlalchemy import update
        await self._beri_ruang_usaha()
        async with self.Session() as db:
            await db.execute(update(User).where(User.id == self.me.id).values(plan="basic"))
            for i in range(48):              # + 1 kopi rumah dari fixture = 49
                db.add(Transaction(envelope_id=self.id_rumah["env"], user_id=self.me.id, amount=D("1"),
                                   description=f"isi {i}", transaction_date=_date.today()))
            await db.commit()
            self.me = await db.get(User, self.me.id)
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.id_rumah["env"]), "amount": "1",
                                                      "description": "isi terakhir"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(r.json().get("quota_notice"), r.text)      # input ke-50 ruang keluarga: kuota kini habis
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.id_rumah["env"]), "amount": "1",
                                                      "description": "lewat kuota"})
        self.assertEqual(r.status_code, 403, r.text)               # kuota Basic ruang keluarga habis
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.id_usaha["env"]), "amount": "1",
                                                      "description": "jualan"})
        self.assertEqual(r.status_code, 201, r.text)               # ruang usaha tidak memakai kuota Basic
        self.assertIsNone(r.json().get("quota_notice"), r.text)    # ...dan tidak diberi peringatan kuota (review #171)
        for i in range(6):                                         # batas 6 amplop Basic tidak berlaku di ruang usaha
            r = await self._req("POST", "/envelopes/", {"name": f"Usaha {i}", "budget_amount": "100000"},
                                header=self.usaha_id)
            self.assertEqual(r.status_code, 201, r.text)
        prof = (await self._req("GET", "/user/profile")).json()
        self.assertEqual(prof["usage"]["txn_this_month"], 50)      # 48 isi + kopi rumah + isi terakhir; usaha tidak dihitung

    # ── gabung akun: ruang yang dipertahankan tidak boleh dari body sembarang (review PR #166) ──
    async def _akun_bot(self):
        """Akun bot (sumber gabung) dengan ruang keluarga sendiri berisi satu amplop."""
        async with self.Session() as db:
            bot = User(name="Bot", telegram_id="5151", payday_day=1, timezone="Asia/Jakarta")
            hh = Household(name="Rumah bot")
            db.add_all([bot, hh])
            await db.flush()
            db.add(HouseholdMember(user_id=bot.id, household_id=hh.id, role=HouseholdRole.owner))
            db.add(Envelope(household_id=hh.id, name="Amplop Bot", budget_amount=D("0")))
            await db.commit()
        return bot, hh.id

    async def _gabung(self, bot_id, keep):
        import json as _json
        kode = "GABUNG01"
        await self.redis.set(f"merge:{kode}", _json.dumps(
            {"source_id": str(bot_id), "target_id": str(self.me.id), "telegram_id": "5151"}))
        return await self.client.post("/auth/link/merge", json={"code": kode, "keep_household_id": keep})

    async def _anggota(self, user_id):
        from sqlalchemy import select
        async with self.Session() as db:
            return set((await db.execute(select(HouseholdMember.household_id)
                                         .where(HouseholdMember.user_id == user_id))).scalars())

    async def test_gabung_akun_menolak_household_orang_lain_dan_ruang_usaha(self):
        from sqlalchemy import func, select
        await self._beri_ruang_usaha()
        bot, hh_bot = await self._akun_bot()
        for keep in (str(self.asing_id), str(self.usaha_id), "bukan-uuid"):
            r = await self._gabung(bot.id, keep)
            self.assertEqual(r.status_code, 400, f"{keep}: {r.text}")
        self.assertEqual(await self._anggota(self.me.id), {self.rumah_id, self.usaha_id})
        async with self.Session() as db:
            n_asing = (await db.execute(select(func.count(Envelope.id))
                                        .where(Envelope.household_id == self.asing_id))).scalar()
            bot_masih = await db.get(User, bot.id)
        self.assertEqual(n_asing, 2, "amplop dipindah ke household orang lain")
        self.assertIsNotNone(bot_masih, "akun sumber terhapus walau gabung ditolak")

    async def test_gabung_akun_dengan_ruang_keluarga_sah_tetap_jalan(self):
        await self._beri_ruang_usaha()
        bot, hh_bot = await self._akun_bot()
        r = await self._gabung(bot.id, str(self.rumah_id))
        self.assertEqual(r.status_code, 200, r.text)
        # Ruang keluarga target dipertahankan, ruang usaha target tidak tersentuh.
        self.assertEqual(await self._anggota(self.me.id), {self.rumah_id, self.usaha_id})

    async def test_gabung_ke_ruang_usaha_lewat_undangan_ditolak(self):
        # Sampai R5 undangan hanya ruang keluarga; kode yang menunjuk ruang usaha tidak boleh
        # menghapus keanggotaan ruang keluarga user.
        await self._beri_ruang_usaha()
        await self.redis.set("invite:USAHA01", str(self.usaha_id))
        self.current = self.rina
        r = await self.client.post("/household/join", params={"code": "USAHA01"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(await self._anggota(self.rina.id), {self.rumah_id})

    async def test_join_bot_ke_ruang_usaha_ditolak(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.bot import household_cmd
        await self._beri_ruang_usaha()
        async with self.Session() as db:
            self.rina.telegram_id = "7272"
            await db.merge(self.rina)
            await db.commit()
        await self.redis.set("invite:USAHA02", str(self.usaha_id))
        update = SimpleNamespace(effective_user=SimpleNamespace(id=7272, first_name="Rina"),
                                 message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(household_cmd, "AsyncSessionLocal", self.Session):
            await household_cmd.cmd_join(update, SimpleNamespace(args=["usaha02"]))
        self.assertIn("tidak valid", update.message.reply_text.await_args.args[0])
        self.assertEqual(await self._anggota(self.rina.id), {self.rumah_id})

    async def test_header_ruang_orang_lain_403(self):
        await self._beri_ruang_usaha()
        keluarga = await self._potret(self.me)
        asing = await self._potret(self.me, header=str(self.asing_id))
        for p in self.paths:
            teks_kel = json.dumps(keluarga[p][1], ensure_ascii=False)
            teks_asing = json.dumps(asing[p][1], ensure_ascii=False)
            self.assertNotIn("Makan Orang", teks_asing, f"{p} membocorkan ruang orang lain")
            self.assertNotIn("kopi orang", teks_asing, f"{p} membocorkan ruang orang lain")
            if keluarga[p][0] == 200 and any(x in teks_kel for x in PENANDA_KELUARGA):
                self.assertEqual(asing[p][0], 403, p)
                self.assertEqual(asing[p][1].get("kode"), "ruang_tidak_diizinkan", p)


if __name__ == "__main__":
    unittest.main()
