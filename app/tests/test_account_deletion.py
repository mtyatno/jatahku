"""Mobile 1.2 — hapus akun sungguhan: data terhapus (atau teranonim penuh di amplop
bersama), semua sesi tercabut, dan permintaan hapus lewat halaman web tanpa login
dengan konfirmasi email.

Route asli lewat HTTP (httpx ASGITransport) di atas SQLite in-memory.
Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_account_deletion -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy import event, func, select
from sqlalchemy.orm import configure_mappers

from app.api.routes import auth as auth_route, envelopes as envelopes_route, user_settings
from app.core.database import Base, get_db
from app.models.models import (
    Allocation, AuthSession, BalanceCheck, Envelope, Household, HouseholdMember, HouseholdMerchant,
    HouseholdRole, Income, IncomeKind, MerchantEnvelopeMap, Notification, NotificationPreference, PaymentOrder,
    PendingTransaction, RecurringTransaction, Transaction, User, UserStreak,
)
from app.services import account_deletion
from app.services.account_deletion import FORMER_MEMBER_ID
from app.services.envelope_balance import compute_envelope_summaries
from app.services.fund_shift import record_transfer

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
PASSWORD = "rahasia123"
PW_HASH = "fake$" + PASSWORD  # lihat test_auth_sessions: bcrypt dipalsukan


def _fake_verify(plain, hashed):
    return hashed == "fake$" + plain


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)

    async def close(self):
        pass


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class AccountDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        self.addAsyncCleanup(self.engine.dispose)  # juga bila setUp gagal (aiosqlite menggantung)

        # Postgres menegakkan FK; tanpa ini SQLite meloloskan urutan hapus yang salah.
        @event.listens_for(self.engine.sync_engine, "connect")
        def _fk_on(conn, _record):
            conn.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        app = FastAPI()
        app.state.limiter = auth_route.limiter
        app.include_router(auth_route.router, prefix="/auth")
        app.include_router(user_settings.router, prefix="/user")
        app.include_router(envelopes_route.router, prefix="/envelopes")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        auth_route.limiter.enabled = False

        self.redis = FakeRedis()
        self.sent = []  # (jenis, argumen) email yang dikirim
        patches = [
            patch.object(auth_route, "verify_password", _fake_verify),
            patch.object(user_settings.aioredis, "from_url", lambda *_a, **_k: self.redis),
            patch.object(user_settings, "send_account_deletion_email",
                         lambda *a: self.sent.append(("konfirmasi", a))),
            patch.object(user_settings, "send_account_deleted_email",
                         lambda *a: self.sent.append(("terhapus", a))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def asyncTearDown(self):
        auth_route.limiter.enabled = True
        await self.client.aclose()

    # ── helper ────────────────────────────────────────────────────────────
    async def add_user(self, name, email, household=None, role=HouseholdRole.owner, joined=None):
        """User + household sendiri (atau gabung `household`) + satu amplop pribadi."""
        async with self.Session() as db:
            u = User(name=name, email=email, password_hash=PW_HASH)
            db.add(u)
            await db.flush()
            if household is None:
                hh = Household(name=f"HH {name}")
                db.add(hh)
                await db.flush()
                household = hh.id
            db.add(HouseholdMember(user_id=u.id, household_id=household, role=role,
                                   created_at=joined or datetime.now(timezone.utc)))
            env = Envelope(household_id=household, name=f"Pribadi {name}", owner_id=u.id)
            db.add(env)
            await db.flush()
            db.add_all([
                Transaction(envelope_id=env.id, user_id=u.id, amount=Decimal("10000"), description="kopi rahasia"),
                Notification(user_id=u.id, title="hai", message="pesan"),
                NotificationPreference(user_id=u.id),
                UserStreak(user_id=u.id, current_streak=3),
                PendingTransaction(envelope_id=env.id, user_id=u.id, amount=Decimal("500000"),
                                   description="tas", expires_at=datetime.now(timezone.utc),
                                   confirm_after=datetime.now(timezone.utc)),
                PaymentOrder(user_id=u.id, amount=Decimal("79000"), original_amount=Decimal("79000"),
                             proof_url=f"/uploads/proof_{name}.jpg"),
                RecurringTransaction(envelope_id=env.id, amount=Decimal("50000"), description="netflix",
                                     next_run=date.today()),
            ])
            await db.commit()
            return u.id, household, env.id

    async def login(self, email):
        r = await self.client.post("/auth/login", json={"email": email, "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def auth(self, tokens):
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    async def count(self, model, *where):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar()

    async def get(self, model, pk):
        async with self.Session() as db:
            return await db.get(model, pk)

    # ── akun sendiri ──────────────────────────────────────────────────────
    async def test_solo_account_is_fully_deleted(self):
        uid, hid, env = await self.add_user("Sari", "sari@example.com")
        other, other_hid, _ = await self.add_user("Budi", "budi@example.com")
        async with self.Session() as db:
            inc = Income(household_id=hid, user_id=uid, amount=Decimal("1000000"), description="gaji")
            db.add(inc)
            await db.flush()
            db.add(Allocation(income_id=inc.id, envelope_id=env, amount=Decimal("1000000")))
            db.add(BalanceCheck(household_id=hid, user_id=uid, actual_amount=1, app_amount=1, gap=0))
            await db.commit()
        t = await self.login("sari@example.com")

        r = await self.client.delete("/user/account", headers=self.auth(t))
        self.assertEqual(r.json(), {"status": "deleted"})

        self.assertIsNone(await self.get(User, uid))
        self.assertIsNone(await self.get(Household, hid))
        for model in (Envelope, Income, BalanceCheck):
            self.assertEqual(await self.count(model, model.household_id == hid), 0, model.__name__)
        for model in (Transaction, Income, Notification, NotificationPreference, UserStreak,
                      PendingTransaction, PaymentOrder, AuthSession, HouseholdMember, BalanceCheck):
            self.assertEqual(await self.count(model, model.user_id == uid), 0, model.__name__)
        self.assertEqual(await self.count(RecurringTransaction, RecurringTransaction.envelope_id == env), 0)
        self.assertEqual(await self.count(Allocation), 0)
        # Akun sendiri tidak membuat "Mantan anggota".
        self.assertIsNone(await self.get(User, FORMER_MEMBER_ID))
        # User lain tidak tersentuh.
        self.assertIsNotNone(await self.get(Household, other_hid))
        self.assertEqual(await self.count(Transaction, Transaction.user_id == other), 1)
        self.assertEqual(await self.count(PaymentOrder, PaymentOrder.user_id == other), 1)
        self.assertEqual(self.sent, [("terhapus", ("sari@example.com", "Sari"))])

    async def test_old_tokens_rejected_after_deletion(self):
        await self.add_user("Sari", "sari@example.com")
        laptop = await self.login("sari@example.com")
        hp = await self.login("sari@example.com")

        await self.client.delete("/user/account", headers=self.auth(laptop))

        for t in (laptop, hp):
            self.assertEqual((await self.client.get("/auth/me", headers=self.auth(t))).status_code, 401)
            r = await self.client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})
            self.assertEqual(r.status_code, 401)
        r = await self.client.post("/auth/login", json={"email": "sari@example.com", "password": PASSWORD})
        self.assertEqual(r.status_code, 401)

    async def test_uploaded_files_removed(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(f"{root}/uploads")
            for name in ("pp.jpg", "proof_x.jpg", "punya_lain.jpg"):
                open(f"{root}/uploads/{name}", "w").close()
            account_deletion.remove_files(
                ["/uploads/pp.jpg", "/uploads/proof_x.jpg", "/uploads/hilang.jpg", "/uploads/../x", None],
                root=root,
            )
            self.assertEqual(os.listdir(f"{root}/uploads"), ["punya_lain.jpg"])

    async def test_delete_collects_profile_pic_and_payment_proofs(self):
        uid, _, _ = await self.add_user("Sari", "sari@example.com")
        async with self.Session() as db:
            u = await db.get(User, uid)
            u.profile_pic = "/uploads/x.jpg"
            await db.commit()
            files = await account_deletion.delete_account(db, u)
        self.assertEqual(sorted(files), ["/uploads/proof_Sari.jpg", "/uploads/x.jpg"])

    # ── household bersama ─────────────────────────────────────────────────
    async def shared_household(self):
        """Owner Andi + anggota Sari; amplop bersama 'Dapur' berisi catatan keduanya."""
        now = datetime.now(timezone.utc)
        andi, hid, andi_env = await self.add_user("Andi", "andi@example.com", joined=now - timedelta(days=30))
        sari, _, sari_env = await self.add_user("Sari", "sari@example.com", household=hid,
                                                role=HouseholdRole.member, joined=now - timedelta(days=5))
        async with self.Session() as db:
            dapur = Envelope(household_id=hid, name="Dapur")
            db.add(dapur)
            await db.flush()
            # Gaji Sari 1jt: 300rb ke Dapur (bersama), 200rb ke amplop pribadinya, 500rb belum dialokasikan.
            inc = Income(household_id=hid, user_id=sari, amount=Decimal("1000000"), description="gaji Sari")
            db.add(inc)
            await db.flush()
            db.add_all([
                Allocation(income_id=inc.id, envelope_id=dapur.id, amount=Decimal("300000")),
                Allocation(income_id=inc.id, envelope_id=sari_env, amount=Decimal("200000")),
                Transaction(envelope_id=dapur.id, user_id=sari, amount=Decimal("75000"), description="sayur pasar"),
                Transaction(envelope_id=dapur.id, user_id=sari, amount=Decimal("5000"), description="dihapus",
                            is_deleted=True),
                Transaction(envelope_id=dapur.id, user_id=andi, amount=Decimal("40000"), description="beras"),
            ])
            await db.commit()
            return andi, sari, hid, dapur.id, sari_env, inc.id

    async def test_member_deletion_anonymizes_shared_records(self):
        andi, sari, hid, dapur, sari_env, inc = await self.shared_household()
        t = await self.login("sari@example.com")

        await self.client.delete("/user/account", headers=self.auth(t))

        self.assertIsNone(await self.get(User, sari))
        self.assertIsNone(await self.get(Envelope, sari_env))
        async with self.Session() as db:
            txns = (await db.execute(select(Transaction).where(Transaction.envelope_id == dapur)
                                     .order_by(Transaction.amount))).scalars().all()
            members = (await db.execute(select(HouseholdMember).where(HouseholdMember.household_id == hid))).scalars().all()
        # Saldo Dapur tetap: 75rb (kini Mantan anggota, tanpa keterangan) + 40rb Andi; yang sudah dihapus dibuang.
        self.assertEqual([(t.amount, t.user_id, t.description) for t in txns], [
            (Decimal("40000"), andi, "beras"),
            (Decimal("75000"), FORMER_MEMBER_ID, account_deletion.ANON_TXN_DESC),
        ])
        # Pemasukan dipangkas ke yang masih teralokasi ke amplop bersama.
        income = await self.get(Income, inc)
        self.assertEqual((income.amount, income.user_id, income.description),
                         (Decimal("300000"), FORMER_MEMBER_ID, account_deletion.ANON_INCOME_DESC))
        self.assertEqual(await self.count(Allocation, Allocation.income_id == inc), 1)
        self.assertEqual([(m.user_id, m.role) for m in members], [(andi, HouseholdRole.owner)])
        former = await self.get(User, FORMER_MEMBER_ID)
        self.assertEqual(former.name, "Mantan anggota")
        self.assertTrue(former.email.startswith("deleted_"))
        self.assertIsNone(former.password_hash)
        # Data Andi utuh.
        self.assertEqual(await self.count(Transaction, Transaction.user_id == andi), 2)

    async def test_owner_deletion_hands_household_to_oldest_member(self):
        andi, sari, hid, dapur, _, _ = await self.shared_household()
        async with self.Session() as db:
            later = User(name="Cici", email="cici@example.com", password_hash=PW_HASH)
            db.add(later)
            await db.flush()
            db.add(HouseholdMember(user_id=later.id, household_id=hid, role=HouseholdRole.member,
                                   created_at=datetime.now(timezone.utc)))
            await db.commit()
        t = await self.login("andi@example.com")

        await self.client.delete("/user/account", headers=self.auth(t))

        self.assertIsNotNone(await self.get(Household, hid))
        self.assertEqual(await self.count(Envelope, Envelope.id == dapur), 1)
        async with self.Session() as db:
            roles = dict((await db.execute(
                select(HouseholdMember.user_id, HouseholdMember.role).where(HouseholdMember.household_id == hid)
            )).all())
        self.assertEqual(roles, {sari: HouseholdRole.owner, later.id: HouseholdRole.member})
        self.assertEqual(await self.count(Transaction, Transaction.user_id == FORMER_MEMBER_ID), 1)

    async def test_former_member_row_is_shared_between_deletions(self):
        andi, sari, hid, dapur, _, _ = await self.shared_household()
        async with self.Session() as db:
            cici = User(name="Cici", email="cici@example.com", password_hash=PW_HASH)
            db.add(cici)
            await db.flush()
            db.add(HouseholdMember(user_id=cici.id, household_id=hid, role=HouseholdRole.member))
            db.add(Transaction(envelope_id=dapur, user_id=cici.id, amount=Decimal("1000"), description="garam"))
            await db.commit()
        for email in ("sari@example.com", "cici@example.com"):
            await self.client.delete("/user/account", headers=self.auth(await self.login(email)))
        self.assertEqual(await self.count(User, User.name == "Mantan anggota"), 1)
        self.assertEqual(await self.count(Transaction, Transaction.user_id == FORMER_MEMBER_ID), 2)

    # ── pemasukan & geser dana yang masih beralokasi di amplop bersama ─────
    # Income hanya boleh dibuang bila TIDAK punya alokasi lagi. Geser dana = Income bernilai 0 dengan alokasi
    # −x/+x; `allocations.income_id` NOT NULL, jadi menghapus Income yang alokasinya tersisa membuat flush gagal
    # dan seluruh hapus akun dibatalkan (data user tetap tersimpan, padahal ia minta dihapus).
    async def transfer_household(self):
        """Owner Andi + anggota Sari; dua amplop bersama (Dapur 500rb, Listrik 100rb, dari gaji Andi) dan amplop
        pribadi Sari. Mengembalikan (andi, sari, hid, dapur, listrik, amplop pribadi Sari)."""
        now = datetime.now(timezone.utc)
        andi, hid, _ = await self.add_user("Andi", "andi@example.com", joined=now - timedelta(days=30))
        sari, _, sari_env = await self.add_user("Sari", "sari@example.com", household=hid,
                                                role=HouseholdRole.member, joined=now - timedelta(days=5))
        async with self.Session() as db:
            dapur, listrik = Envelope(household_id=hid, name="Dapur"), Envelope(household_id=hid, name="Listrik")
            db.add_all([dapur, listrik])
            await db.flush()
            gaji = Income(household_id=hid, user_id=andi, amount=Decimal("600000"), description="gaji Andi")
            db.add(gaji)
            await db.flush()
            db.add_all([
                Allocation(income_id=gaji.id, envelope_id=dapur.id, amount=Decimal("500000")),
                Allocation(income_id=gaji.id, envelope_id=listrik.id, amount=Decimal("100000")),
            ])
            await db.commit()
            return andi, sari, hid, dapur.id, listrik.id, sari_env

    async def shift(self, user_id, hid, from_env, to_env, amount):
        """Geser dana lewat `fund_shift.record_transfer`, bentuk yang sama dengan POST /envelopes/transfer
        (Income bernilai 0, alokasi −x di sumber dan +x di tujuan). Mengembalikan id Income-nya."""
        async with self.Session() as db:
            income = record_transfer(db, hid, user_id, await db.get(Envelope, from_env),
                                     await db.get(Envelope, to_env), Decimal(amount))
            await db.commit()
            return income.id

    async def close_envelope(self, email, env_id):
        """Tutup amplop lewat DELETE /envelopes/{id} sungguhan: sisanya (alokasi + rollover − terpakai) dipindah ke
        Tabungan sebagai Income bernilai 0, "Refund" bila positif dan "Tutup minus" bila minus. Mengembalikan id
        Income-nya."""
        r = await self.client.delete(f"/envelopes/{env_id}", headers=self.auth(await self.login(email)))
        self.assertEqual(r.status_code, 204, r.text)
        async with self.Session() as db:
            return (await db.execute(
                select(Income.id).join(Allocation, Allocation.income_id == Income.id)
                .where(Income.kind == IncomeKind.TRANSFER, Allocation.envelope_id == env_id)
            )).scalar_one()

    async def shared_balances(self, hid, viewer):
        """{id amplop bersama: (dialokasikan, sisa)} yang dilihat `viewer` (rumus saldo dashboard sungguhan)."""
        async with self.Session() as db:
            rows = await compute_envelope_summaries(await db.get(User, viewer), db, household_id=hid)
        return {r["id"]: (r["allocated"], r["remaining"]) for r in rows if not r["is_personal"]}

    async def allocations_of(self, income_id):
        async with self.Session() as db:
            rows = (await db.execute(select(Allocation).where(Allocation.income_id == income_id))).scalars().all()
        return [(a.envelope_id, a.amount) for a in rows]

    async def delete_via_api(self, email):
        r = await self.client.delete("/user/account", headers=self.auth(await self.login(email)))
        self.assertEqual((r.status_code, r.json()), (200, {"status": "deleted"}))

    def assertAnonymizedTransfer(self, income):
        self.assertEqual(
            (income.user_id, income.description, income.amount, income.kind),
            (FORMER_MEMBER_ID, account_deletion.ANON_INCOME_DESC, Decimal("0"), IncomeKind.TRANSFER),
        )

    async def test_member_deletion_keeps_transfer_between_shared_envelopes(self):
        # Dapur → Listrik, keduanya bersama: jumlah alokasi 0, tapi alokasinya milik amplop yang tetap ada.
        # Income-nya dianonimkan (bukan dihapus), alokasinya tidak disentuh, saldo Dapur & Listrik tetap.
        andi, sari, hid, dapur, listrik, _ = await self.transfer_household()
        transfer = await self.shift(sari, hid, dapur, listrik, "150000")
        before = await self.shared_balances(hid, andi)
        self.assertEqual(before, {dapur: (Decimal("350000"), Decimal("350000")),
                                  listrik: (Decimal("250000"), Decimal("250000"))})

        await self.delete_via_api("sari@example.com")

        self.assertIsNone(await self.get(User, sari))
        self.assertAnonymizedTransfer(await self.get(Income, transfer))
        self.assertCountEqual(await self.allocations_of(transfer),
                              [(dapur, Decimal("-150000")), (listrik, Decimal("150000"))])
        self.assertEqual(await self.shared_balances(hid, andi), before)
        # Data Andi dan household-nya tidak tersentuh.
        self.assertIsNotNone(await self.get(Household, hid))
        self.assertEqual(await self.count(Income, Income.user_id == andi), 1)

    async def test_member_deletion_keeps_transfer_whose_personal_side_is_deleted(self):
        # Dapur → amplop pribadi Sari: amplop pribadi ikut terhapus beserta alokasi +x-nya, tersisa hanya sisi −x di
        # Dapur (jumlah negatif). Income-nya tetap dianonimkan dan tetap bernilai 0 (bukan −x, supaya tidak dihitung
        # sebagai pemasukan negatif), alokasi −x tidak disentuh, saldo Dapur tetap.
        andi, sari, hid, dapur, _, sari_env = await self.transfer_household()
        transfer = await self.shift(sari, hid, dapur, sari_env, "120000")
        before = await self.shared_balances(hid, andi)
        self.assertEqual(before[dapur], (Decimal("380000"), Decimal("380000")))

        await self.delete_via_api("sari@example.com")

        self.assertIsNone(await self.get(User, sari))
        self.assertIsNone(await self.get(Envelope, sari_env))
        self.assertAnonymizedTransfer(await self.get(Income, transfer))
        self.assertEqual(await self.allocations_of(transfer), [(dapur, Decimal("-120000"))])
        self.assertEqual(await self.shared_balances(hid, andi), before)

    async def test_member_deletion_keeps_transfer_whose_source_is_deleted_personal_envelope(self):
        # Kebalikannya: amplop pribadi Sari → Dapur. Tersisa hanya sisi +x (jumlah positif); perilaku lama tidak berubah,
        # nominal Income tetap 0 (min(0, x)) dan saldo Dapur tetap.
        andi, sari, hid, dapur, _, sari_env = await self.transfer_household()
        transfer = await self.shift(sari, hid, sari_env, dapur, "70000")
        before = await self.shared_balances(hid, andi)
        self.assertEqual(before[dapur], (Decimal("570000"), Decimal("570000")))

        await self.delete_via_api("sari@example.com")

        self.assertIsNone(await self.get(Envelope, sari_env))
        self.assertAnonymizedTransfer(await self.get(Income, transfer))
        self.assertEqual(await self.allocations_of(transfer), [(dapur, Decimal("70000"))])
        self.assertEqual(await self.shared_balances(hid, andi), before)

    async def test_member_deletion_keeps_refund_and_tutup_minus_of_closed_shared_envelopes(self):
        # Sari menutup dua amplop bersama lewat DELETE /envelopes/{id}; sisanya pindah ke Tabungan sebagai Income
        # bernilai 0 miliknya: "Refund" (Dapur sisa 500rb: −x di Dapur, +x di Tabungan) dan "Tutup minus" (Listrik
        # minus 30rb: +x di Listrik, −x di Tabungan). Amplop yang ditutup hanya dinonaktifkan, jadi alokasinya tetap
        # sah: Income-nya dianonimkan (bukan dihapus), kedua alokasi tidak disentuh, saldo Tabungan tetap.
        andi, sari, hid, dapur, listrik, _ = await self.transfer_household()
        async with self.Session() as db:
            tabungan = Envelope(household_id=hid, name="Tabungan")
            db.add_all([
                tabungan,
                Transaction(envelope_id=listrik, user_id=andi, amount=Decimal("130000"), description="token listrik"),
            ])
            await db.commit()
        refund = await self.close_envelope("sari@example.com", dapur)
        tutup_minus = await self.close_envelope("sari@example.com", listrik)
        before = await self.shared_balances(hid, andi)
        self.assertEqual(before, {tabungan.id: (Decimal("470000"), Decimal("470000"))})  # +500rb Refund, −30rb minus

        await self.delete_via_api("sari@example.com")

        self.assertIsNone(await self.get(User, sari))
        for income in (refund, tutup_minus):
            self.assertAnonymizedTransfer(await self.get(Income, income))
        self.assertCountEqual(await self.allocations_of(refund),
                              [(dapur, Decimal("-500000")), (tabungan.id, Decimal("500000"))])
        self.assertCountEqual(await self.allocations_of(tutup_minus),
                              [(listrik, Decimal("30000")), (tabungan.id, Decimal("-30000"))])
        for env in (dapur, listrik):
            self.assertFalse((await self.get(Envelope, env)).is_active)
        self.assertEqual(await self.shared_balances(hid, andi), before)

    async def test_owner_deletion_keeps_transfer_and_hands_household_to_heir(self):
        # Varian yang sama, tapi OWNER yang menggeser dana lalu menghapus akunnya: peran owner pindah ke anggota
        # tertua (Sari), transfernya dianonimkan seperti kasus anggota biasa, alokasinya tidak disentuh, saldo tetap.
        andi, sari, hid, dapur, listrik, _ = await self.transfer_household()
        transfer = await self.shift(andi, hid, dapur, listrik, "150000")
        before = await self.shared_balances(hid, sari)
        self.assertEqual(before, {dapur: (Decimal("350000"), Decimal("350000")),
                                  listrik: (Decimal("250000"), Decimal("250000"))})

        await self.delete_via_api("andi@example.com")

        self.assertIsNone(await self.get(User, andi))
        self.assertAnonymizedTransfer(await self.get(Income, transfer))
        self.assertCountEqual(await self.allocations_of(transfer),
                              [(dapur, Decimal("-150000")), (listrik, Decimal("150000"))])
        self.assertEqual(await self.shared_balances(hid, sari), before)
        async with self.Session() as db:
            roles = dict((await db.execute(
                select(HouseholdMember.user_id, HouseholdMember.role).where(HouseholdMember.household_id == hid)
            )).all())
        self.assertEqual(roles, {sari: HouseholdRole.owner})

    async def test_member_deletion_drops_income_without_remaining_allocations(self):
        # Pemasukan yang seluruhnya masuk amplop pribadi (ikut terhapus) dan yang tidak pernah dialokasikan:
        # tidak ada lagi yang bergantung padanya, jadi dibuang (bukan dianonimkan jadi baris kosong).
        _, sari, hid, _, _, sari_env = await self.transfer_household()
        async with self.Session() as db:
            all_personal = Income(household_id=hid, user_id=sari, amount=Decimal("800000"), description="gaji Sari")
            unallocated = Income(household_id=hid, user_id=sari, amount=Decimal("50000"), description="belum dialokasikan")
            db.add_all([all_personal, unallocated])
            await db.flush()
            db.add(Allocation(income_id=all_personal.id, envelope_id=sari_env, amount=Decimal("800000")))
            await db.commit()
            ids = [all_personal.id, unallocated.id]

        await self.delete_via_api("sari@example.com")

        self.assertIsNone(await self.get(User, sari))
        for income_id in ids:
            self.assertIsNone(await self.get(Income, income_id))
        self.assertEqual(await self.count(Income, Income.user_id.in_([sari, FORMER_MEMBER_ID])), 0)
        self.assertEqual(await self.count(Allocation, Allocation.income_id.in_(ids)), 0)

    async def test_member_deletion_caps_income_to_amount_still_allocated_to_shared_envelopes(self):
        # Gaji Sari 1jt: 400rb Dapur + 250rb Listrik (bersama), 100rb amplop pribadi (ikut terhapus), 250rb belum
        # dialokasikan. Nominalnya dipangkas ke 650rb yang masih teralokasi, kedua alokasi bersama tetap.
        andi, sari, hid, dapur, listrik, sari_env = await self.transfer_household()
        async with self.Session() as db:
            gaji = Income(household_id=hid, user_id=sari, amount=Decimal("1000000"), description="gaji Sari")
            db.add(gaji)
            await db.flush()
            db.add_all([
                Allocation(income_id=gaji.id, envelope_id=dapur, amount=Decimal("400000")),
                Allocation(income_id=gaji.id, envelope_id=listrik, amount=Decimal("250000")),
                Allocation(income_id=gaji.id, envelope_id=sari_env, amount=Decimal("100000")),
            ])
            await db.commit()
            gaji_id = gaji.id
        before = await self.shared_balances(hid, andi)

        await self.delete_via_api("sari@example.com")

        income = await self.get(Income, gaji_id)
        self.assertEqual((income.user_id, income.description, income.amount, income.kind),
                         (FORMER_MEMBER_ID, account_deletion.ANON_INCOME_DESC, Decimal("650000"), IncomeKind.PEMASUKAN))
        self.assertCountEqual(await self.allocations_of(gaji_id),
                              [(dapur, Decimal("400000")), (listrik, Decimal("250000"))])
        self.assertEqual(await self.shared_balances(hid, andi), before)

    # ── peta merchant Kotak Struk ─────────────────────────────────────────
    async def add_merchant(self, hid, key, maps):
        """Merchant rumah tangga `hid` + baris peta {envelope_id: last_user_id}."""
        async with self.Session() as db:
            m = HouseholdMerchant(household_id=hid, counterparty_key=key, raw_name=key)
            db.add(m)
            await db.flush()
            rows = [MerchantEnvelopeMap(merchant_id=m.id, envelope_id=env, count=3, last_user_id=who)
                    for env, who in maps.items()]
            db.add_all(rows)
            await db.commit()
            return m.id, [r.id for r in rows]

    async def foreign_keys(self, on: bool):
        """FK di koneksi StaticPool (satu-satunya koneksi) dinyalakan/dimatikan. Dengan FK menyala, aksi CASCADE /
        SET NULL ikut membersihkan tabel peta, jadi hanya varian tanpa FK yang membuktikan penghapusan eksplisit."""
        async with self.engine.connect() as conn:
            await conn.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if on else 'OFF'}")
            self.assertEqual((await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar(), int(on))

    async def sole_member_scenario(self, *, fk: bool):
        uid, hid, env = await self.add_user("Sari", "sari@example.com")
        other, other_hid, other_env = await self.add_user("Budi", "budi@example.com")
        async with self.Session() as db:
            dapur = Envelope(household_id=hid, name="Dapur")
            db.add(dapur)
            await db.commit()
        # Baris buatan tangan: merchant milik household yang dihapus, amplopnya milik household lain. Hanya
        # penghapusan peta lewat merchant_id (bukan lewat amplop) yang membuangnya.
        await self.add_merchant(hid, "nmid:ID1020", {dapur.id: uid, env: None, other_env: None})
        await self.add_merchant(hid, "nama:warung|", {dapur.id: uid})
        other_mid, other_maps = await self.add_merchant(other_hid, "nmid:ID1020", {other_env: other})
        await self.foreign_keys(fk)

        async with self.Session() as db:
            await account_deletion.delete_account(db, await db.get(User, uid))

        self.assertEqual(await self.count(HouseholdMerchant, HouseholdMerchant.household_id == hid), 0)
        self.assertEqual(await self.count(MerchantEnvelopeMap, MerchantEnvelopeMap.merchant_id != other_mid), 0)
        self.assertIsNone(await self.get(Household, hid))
        # Rumah tangga lain tidak tersentuh.
        self.assertIsNotNone(await self.get(HouseholdMerchant, other_mid))
        self.assertEqual((await self.get(MerchantEnvelopeMap, other_maps[0])).last_user_id, other)
        self.assertIsNotNone(await self.get(Envelope, other_env))

    async def test_sole_member_deletion_removes_household_merchants_and_map(self):
        await self.sole_member_scenario(fk=True)

    async def test_sole_member_deletion_removes_household_merchants_and_map_without_fk_actions(self):
        await self.sole_member_scenario(fk=False)

    async def shared_map_scenario(self, *, fk: bool):
        andi, sari, hid, dapur, sari_env, _ = await self.shared_household()
        mid, [shared_map] = await self.add_merchant(hid, "nmid:ID1020", {dapur: sari})
        andi_mid, [andi_map] = await self.add_merchant(hid, "nama:pasar|", {dapur: andi})
        await self.foreign_keys(fk)

        await self.client.delete("/user/account", headers=self.auth(await self.login("sari@example.com")))

        self.assertIsNone(await self.get(User, sari))
        row = await self.get(MerchantEnvelopeMap, shared_map)
        self.assertEqual((row.merchant_id, row.envelope_id, row.count, row.last_user_id), (mid, dapur, 3, None))
        self.assertIsNotNone(await self.get(HouseholdMerchant, mid))
        self.assertEqual((await self.get(MerchantEnvelopeMap, andi_map)).last_user_id, andi)

    async def test_member_deletion_keeps_shared_map_and_clears_last_user(self):
        await self.shared_map_scenario(fk=True)

    async def test_member_deletion_keeps_shared_map_and_clears_last_user_without_fk_actions(self):
        await self.shared_map_scenario(fk=False)

    async def personal_map_scenario(self, *, fk: bool):
        andi, sari, hid, dapur, sari_env, _ = await self.shared_household()
        mid, [personal_map, shared_map] = await self.add_merchant(hid, "nmid:ID1020", {sari_env: sari, dapur: andi})
        await self.foreign_keys(fk)

        await self.client.delete("/user/account", headers=self.auth(await self.login("sari@example.com")))

        self.assertIsNone(await self.get(Envelope, sari_env))
        self.assertIsNone(await self.get(MerchantEnvelopeMap, personal_map))
        self.assertEqual((await self.get(MerchantEnvelopeMap, shared_map)).last_user_id, andi)
        self.assertIsNotNone(await self.get(HouseholdMerchant, mid))

    async def test_member_deletion_drops_map_rows_of_personal_envelopes(self):
        await self.personal_map_scenario(fk=True)

    async def test_member_deletion_drops_map_rows_of_personal_envelopes_without_fk_actions(self):
        await self.personal_map_scenario(fk=False)

    async def test_former_member_cannot_be_deleted(self):
        await self.shared_household()
        await self.client.delete("/user/account", headers=self.auth(await self.login("sari@example.com")))
        async with self.Session() as db:
            with self.assertRaises(ValueError):
                await account_deletion.delete_account(db, await db.get(User, FORMER_MEMBER_ID))

    # ── halaman web tanpa login ───────────────────────────────────────────
    async def test_web_request_sends_link_and_confirm_deletes(self):
        uid, _, _ = await self.add_user("Sari", "sari@example.com")
        t = await self.login("sari@example.com")

        r = await self.client.post("/user/account/deletion-request", json={"email": " Sari@Example.com "})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["message"], user_settings.GENERIC_DELETION_MESSAGE)
        [(kind, (to, name, url))] = self.sent
        self.assertEqual((kind, to, name), ("konfirmasi", "sari@example.com", "Sari"))
        self.assertTrue(url.startswith("https://jatahku.com/hapus-akun?token="))
        token = url.split("token=", 1)[1]
        self.assertIsNotNone(await self.get(User, uid))  # belum dihapus sebelum konfirmasi

        r = await self.client.post("/user/account/deletion-confirm", json={"token": token})
        self.assertEqual(r.json(), {"status": "deleted"})
        self.assertIsNone(await self.get(User, uid))
        self.assertEqual((await self.client.get("/auth/me", headers=self.auth(t))).status_code, 401)

        # Token sekali pakai.
        r = await self.client.post("/user/account/deletion-confirm", json={"token": token})
        self.assertEqual(r.status_code, 400)

    async def test_web_request_unknown_email_same_answer_no_mail(self):
        await self.add_user("Sari", "sari@example.com")
        for email in ("tidakada@example.com", "", account_deletion.FORMER_MEMBER_EMAIL):
            r = await self.client.post("/user/account/deletion-request", json={"email": email})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["message"], user_settings.GENERIC_DELETION_MESSAGE)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.redis.store, {})

    async def test_web_confirm_rejects_bad_token(self):
        await self.add_user("Sari", "sari@example.com")
        self.redis.store["acctdel:bukan-uuid"] = "xyz"
        for token in ("", "asal", "bukan-uuid"):
            r = await self.client.post("/user/account/deletion-confirm", json={"token": token})
            self.assertEqual(r.status_code, 400, token)
        self.assertEqual(await self.count(User), 1)

    async def test_token_expires_after_one_hour(self):
        redis = MagicMock()
        redis.set = MagicMock(side_effect=lambda *a, **k: _done())
        await account_deletion.create_deletion_token(redis, "u")
        self.assertEqual(redis.set.call_args.kwargs["ex"], 3600)


async def _done():
    return None


if __name__ == "__main__":
    unittest.main()
