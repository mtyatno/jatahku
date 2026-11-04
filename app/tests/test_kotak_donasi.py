"""Kotak Struk tahap 2 — donasi contoh (spec 2026-11-01 §10 Tahap 2 butir 1; pre-flight A16 §2, K1, G1, G4).

M1a: saklar `features.kotak_donasi`, persetujuan opt-in (`GET/PUT /user/kotak-donasi`), dan lupa (tarik persetujuan,
hapus akun, gabung akun). Route asli lewat httpx ASGITransport di atas SQLite in-memory; butuh `aiosqlite`.
Semua nama, nomor, dan baris di sini karangan.
Run: python -m unittest app.tests.test_kotak_donasi -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import json
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import FastAPI
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import configure_mappers

from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.models.models import (
    AppSetting, Household, HouseholdMember, HouseholdRole, ProofSample, ProofSampleConsent, ReceiptScan, User,
)
from app.services.kotak_struk import config as K

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
T0 = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
LINES = ["gopay", "Pembayaran Berhasil", "Ke TOKO CONTOH", "Total Rp12.500"]   # karangan, sudah tersamar


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class DonasiBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from app.api.routes import user_settings
        asyncio.get_running_loop().slow_callback_duration = 2.0
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        # Resep SQLAlchemy untuk pysqlite: SAVEPOINT butuh BEGIN eksplisit.
        event.listen(self.engine.sync_engine, "connect", lambda conn, _rec: setattr(conn, "isolation_level", None))
        event.listen(self.engine.sync_engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.Session() as db:
            self.user = User(name="Rina Wulandari")
            self.other = User(name="Dodi Prakoso")
            self.admin = User(name="Pemilik Tes", is_admin=True)
            db.add_all([self.user, self.other, self.admin])
            await db.commit()
        self.current = self.user

        app = FastAPI()
        app.include_router(user_settings.router, prefix="/user")
        app.dependency_overrides[get_current_user] = lambda: self.current

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        self.app = app
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    # ── pembantu ──────────────────────────────────────────────────────────
    async def flag(self, **features):
        async with self.Session() as db:
            row = await db.get(AppSetting, "app_config")
            value = json.dumps({"features": {name: {"web": on} for name, on in features.items()}})
            if row is None:
                db.add(AppSetting(key="app_config", value=value))
            else:
                row.value = value
            await db.commit()

    async def add_samples(self, user, *, statuses=("menunggu", "disetujui")):
        """Item dengan `sample_lines` dan sampel per status untuk `user` (karangan)."""
        async with self.Session() as db:
            item = ReceiptScan(user_id=user.id, status=K.ST_SIAP, doc_type="qris", sample_lines=list(LINES))
            done = ReceiptScan(user_id=user.id, status=K.ST_TERCATAT, doc_type="transfer")
            db.add_all([item, done])
            await db.flush()
            for st in statuses:
                db.add(ProofSample(user_id=user.id, item_id=uuid.uuid4(), rule_key="gopay", doc_type="qris",
                                   trigger="nominal", lines=list(LINES), user_name="ANDI PRATAMA",
                                   truth={"total": 12500, "date": "2026-11-01", "flow": None, "app": None},
                                   today=date(2026, 11, 2), status=st, created_at=T0,
                                   decided_at=T0 if st != "menunggu" else None,
                                   decided_by=self.admin.id if st != "menunggu" else None))
            db.add(ProofSampleConsent(user_id=user.id, consented_at=T0))
            await db.commit()
            return item.id, done.id

    async def count(self, model, *where):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar()

    async def sql_null_sample_lines(self, item_id):
        async with self.Session() as db:
            return (await db.execute(text("SELECT sample_lines IS NULL FROM receipt_scans WHERE id = :i"),
                                     {"i": item_id.hex})).scalar()


class ConsentApiTests(DonasiBase):
    async def test_consent_roundtrip_and_flag(self):
        await self.flag(kotak_donasi=False)
        r = await self.client.get("/user/kotak-donasi")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"available": False, "consented": False, "consented_at": None})
        res = await self.client.put("/user/kotak-donasi", json={"consented": True})
        self.assertEqual((res.status_code, res.json()["detail"]), (409, "Donasi contoh belum dibuka"))
        self.assertEqual(await self.count(ProofSampleConsent), 0)
        await self.flag(kotak_donasi=True)
        r = await self.client.put("/user/kotak-donasi", json={"consented": True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["available"], r.json()["consented"]), (True, True))
        self.assertIsNotNone(r.json()["consented_at"])
        got = (await self.client.get("/user/kotak-donasi")).json()
        self.assertEqual(got, r.json())
        # Persetujuan milik user ini saja.
        self.current = self.other
        self.assertEqual((await self.client.get("/user/kotak-donasi")).json(),
                         {"available": True, "consented": False, "consented_at": None})

    async def test_flag_is_off_by_default(self):
        self.assertEqual((await self.client.get("/user/kotak-donasi")).json()["available"], False)
        self.assertEqual((await self.client.put("/user/kotak-donasi", json={"consented": True})).status_code, 409)

    async def test_consent_twice_keeps_first_time(self):
        from app.services.kotak_struk import donasi
        await self.flag(kotak_donasi=True)
        async with self.Session() as db:
            first = await donasi.set_consent(db, self.user.id, True, now=T0)
            await db.commit()
        async with self.Session() as db:
            again = await donasi.set_consent(db, self.user.id, True, now=T0 + timedelta(days=3))
            await db.commit()
        self.assertEqual(first.replace(tzinfo=None), T0.replace(tzinfo=None))
        self.assertEqual(again.replace(tzinfo=None), T0.replace(tzinfo=None))
        r = await self.client.put("/user/kotak-donasi", json={"consented": True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["consented_at"].startswith("2026-11-02T03:00"))
        self.assertEqual(await self.count(ProofSampleConsent), 1)

    async def test_withdraw_deletes_samples(self):          # Review Focus 1, G4
        await self.flag(kotak_donasi=True)
        item, done = await self.add_samples(self.user)
        other_item, _ = await self.add_samples(self.other)
        r = await self.client.put("/user/kotak-donasi", json={"consented": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"available": True, "consented": False, "consented_at": None})
        # Semua sampel user (menunggu DAN disetujui), persetujuannya, dan baris di itemnya hilang (SQL NULL).
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.user.id), 0)
        self.assertEqual(await self.count(ProofSampleConsent, ProofSampleConsent.user_id == self.user.id), 0)
        self.assertTrue(await self.sql_null_sample_lines(item))
        self.assertTrue(await self.sql_null_sample_lines(done))
        # Item tetap ada, statusnya tidak berubah.
        async with self.Session() as db:
            self.assertEqual((await db.get(ReceiptScan, item)).status, K.ST_SIAP)
        # User lain utuh.
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.other.id), 2)
        self.assertEqual(await self.count(ProofSampleConsent, ProofSampleConsent.user_id == self.other.id), 1)
        self.assertFalse(await self.sql_null_sample_lines(other_item))

    async def test_withdraw_allowed_with_flag_off(self):
        await self.flag(kotak_donasi=False)
        item, _ = await self.add_samples(self.user)
        self.assertEqual((await self.client.get("/user/kotak-donasi")).json()["consented"], True)
        r = await self.client.put("/user/kotak-donasi", json={"consented": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"available": False, "consented": False, "consented_at": None})
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.user.id), 0)
        self.assertTrue(await self.sql_null_sample_lines(item))
        # Menarik tanpa persetujuan sebelumnya juga boleh (idempoten).
        self.assertEqual((await self.client.put("/user/kotak-donasi", json={"consented": False})).status_code, 200)

    async def test_put_rejects_extra_fields(self):
        await self.flag(kotak_donasi=True)
        for body in ({"consented": True, "user_id": str(self.other.id)}, {"consented": True, "consented_at": "x"},
                     {}, {"consented": "ya"}, {"consented": None}):
            with self.subTest(body=body):
                self.assertEqual((await self.client.put("/user/kotak-donasi", json=body)).status_code, 422)
        self.assertEqual(await self.count(ProofSampleConsent), 0)

    async def test_requires_login(self):
        del self.app.dependency_overrides[get_current_user]
        self.assertIn((await self.client.get("/user/kotak-donasi")).status_code, (401, 403))
        self.assertIn((await self.client.put("/user/kotak-donasi", json={"consented": False})).status_code, (401, 403))

    async def test_routes_have_response_model(self):
        from fastapi.routing import APIRoute
        routes = {(m, r.path): r for r in self.app.routes if isinstance(r, APIRoute) for m in r.methods}
        for key in (("GET", "/user/kotak-donasi"), ("PUT", "/user/kotak-donasi")):
            with self.subTest(key):
                self.assertEqual(routes[key].response_model.__name__, "KotakDonasiOut")


class DonasiServiceTests(DonasiBase):
    async def test_available_follows_flag(self):
        from app.services.kotak_struk import donasi
        async with self.Session() as db:
            self.assertFalse(await donasi.donation_available(db))
        await self.flag(kotak_donasi=True)
        async with self.Session() as db:
            self.assertTrue(await donasi.donation_available(db))
        await self.flag(receipt_inbox=True)   # saklar lain tidak membuka donasi
        async with self.Session() as db:
            self.assertFalse(await donasi.donation_available(db))

    async def test_set_consent_and_forget_never_commit(self):
        from app.services.kotak_struk import donasi
        async with self.Session() as db:
            await donasi.set_consent(db, self.user.id, True, now=T0)
            self.assertTrue(await donasi.consented(db, self.user.id))
            await db.rollback()
        self.assertEqual(await self.count(ProofSampleConsent), 0)
        item, _ = await self.add_samples(self.user)
        async with self.Session() as db:
            self.assertIsNone(await donasi.set_consent(db, self.user.id, False, now=T0))
            await db.rollback()
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.user.id), 2)
        self.assertFalse(await self.sql_null_sample_lines(item))
        async with self.Session() as db:
            await donasi.forget_user(db, self.user.id)
            await db.rollback()
        self.assertEqual(await self.count(ProofSampleConsent), 1)

    async def test_set_consent_off_forgets_everything(self):
        from app.services.kotak_struk import donasi
        item, _ = await self.add_samples(self.user, statuses=("menunggu", "disetujui", "ditolak"))
        async with self.Session() as db:
            self.assertIsNone(await donasi.set_consent(db, self.user.id, False, now=T0))
            self.assertFalse(await donasi.consented(db, self.user.id))
            await db.commit()
        self.assertEqual(await self.count(ProofSample), 0)
        self.assertTrue(await self.sql_null_sample_lines(item))

    async def test_forget_user_only_touches_that_user(self):
        from app.services.kotak_struk import donasi
        item, _ = await self.add_samples(self.user)
        other_item, _ = await self.add_samples(self.other)
        async with self.Session() as db:
            await donasi.forget_user(db, self.user.id)
            await db.commit()
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.user.id), 0)
        self.assertEqual(await self.count(ProofSampleConsent, ProofSampleConsent.user_id == self.user.id), 0)
        self.assertTrue(await self.sql_null_sample_lines(item))
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.other.id), 2)
        self.assertFalse(await self.sql_null_sample_lines(other_item))

    async def test_one_sample_per_item(self):
        from sqlalchemy.exc import IntegrityError
        item_id = uuid.uuid4()
        async with self.Session() as db:
            for _ in range(2):
                db.add(ProofSample(user_id=self.user.id, item_id=item_id, doc_type="qris", trigger="nominal",
                                   lines=list(LINES), today=date(2026, 11, 2), status="menunggu"))
            with self.assertRaises(IntegrityError):
                await db.commit()
        async with self.Session() as db:   # item_id NULL boleh berulang
            for _ in range(2):
                db.add(ProofSample(user_id=self.user.id, item_id=None, doc_type="qris", trigger="nominal",
                                   lines=list(LINES), today=date(2026, 11, 2), status="menunggu"))
            await db.commit()
        self.assertEqual(await self.count(ProofSample), 2)


class MergeDonationTests(DonasiBase):
    async def test_merge_users_drops_source_donation(self):          # G4: persetujuan tidak diwariskan
        from app.services.merge import merge_users
        async with self.Session() as db:
            hh_src, hh_tgt = Household(name="Rumah A"), Household(name="Rumah B")
            db.add_all([hh_src, hh_tgt])
            await db.flush()
            db.add_all([HouseholdMember(user_id=self.user.id, household_id=hh_src.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=self.other.id, household_id=hh_tgt.id, role=HouseholdRole.owner)])
            await db.commit()
        await self.add_samples(self.user)
        async with self.Session() as db:
            result = await merge_users(self.user.id, self.other.id, hh_tgt.id, db)
        self.assertEqual(result["status"], "merged")
        self.assertEqual(await self.count(ProofSample), 0)
        self.assertEqual(await self.count(ProofSampleConsent), 0)   # target tidak mewarisi persetujuan source

    async def test_merge_keeps_target_choice(self):
        from app.services.merge import merge_users
        async with self.Session() as db:
            hh_src, hh_tgt = Household(name="Rumah A"), Household(name="Rumah B")
            db.add_all([hh_src, hh_tgt])
            await db.flush()
            db.add_all([HouseholdMember(user_id=self.user.id, household_id=hh_src.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=self.other.id, household_id=hh_tgt.id, role=HouseholdRole.owner)])
            await db.commit()
        await self.add_samples(self.user)
        target_item, _ = await self.add_samples(self.other, statuses=("menunggu",))
        async with self.Session() as db:
            await merge_users(self.user.id, self.other.id, hh_tgt.id, db)
        self.assertEqual(await self.count(ProofSample, ProofSample.user_id == self.other.id), 1)
        self.assertEqual(await self.count(ProofSampleConsent, ProofSampleConsent.user_id == self.other.id), 1)
        self.assertFalse(await self.sql_null_sample_lines(target_item))


if __name__ == "__main__":
    unittest.main()
