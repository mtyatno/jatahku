"""Siklus household, Task 8b: kompatibilitas dengan Plugin R1 (ruang keluarga vs ruang usaha).

R1 menambah `households.type` (`rumah_tangga` | `usaha`) dan membolehkan satu user menjadi anggota beberapa household.
`users.payday_day` adalah cermin siklus RUANG KELUARGA user (spec siklus-household, bagian 10), jadi:
- `membership` (sejak Plugin R2 = `ruang.keanggotaan_keluarga`) hanya mengembalikan keanggotaan ruang keluarga
  (keanggotaan ruang usaha tidak membuatnya melempar atau terpilih), dan `payday_context` untuk profil ikut bekerja pada
  ruang keluarga; dengan `household_id` (recompute, ruang tulis R2) ia bekerja pada household itu;
- `set_household_payday` mengubah `households.payday_day` untuk kedua jenis ruang, tetapi hanya meng-assign cermin
  `users.payday_day` untuk ruang keluarga; `heal` tidak menyentuh anggota ruang usaha (tanpa kueri);
- join web dan bot hanya menerima undangan ruang keluarga (Plugin R2 menolak yang lain sebelum mengubah apa pun), jadi
  `adopt_household_payday` hanya pernah dipanggil untuk ruang keluarga.

Semua household yang ada sekarang `rumah_tangga` (membuat ruang usaha menyusul), jadi tes di sini juga mengunci bahwa
perilaku ruang keluarga tidak berubah. Stub tes lama tanpa atribut `type` dihitung ruang keluarga.

Tanpa Postgres: `db_with(...)` / `FakeResult` dari app/tests/fakes.py. Satu kelompok tes integrasi memakai SQLite
in-memory (butuh `aiosqlite`, dilewati bila tidak ada; pola test_ruang_model).
Run: python -m unittest app.tests.test_household_cycle_r1 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import re
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers

from app.api.routes import household
from app.bot import household_cmd
from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.models.models import Household, HouseholdMember, HouseholdRole, HouseholdType, NotificationType, User
from app.services import household_cycle as hc
from app.services import ruang
from app.tests.fakes import FakeResult, db_with

# Konfigurasi mapper pertama (~50ms) jangan jatuh di dalam event loop test (HouseholdMember dibuat sungguhan di rute).
configure_mappers()

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
HOUSEHOLD_ID = uuid.uuid4()
CODE = "ABC12DEF"
TITLE = "Siklus anggaran rumah berubah"


def norm(statement: str) -> str:
    """SQL hasil compile berisi newline antar klausa; rapatkan supaya assert tidak bergantung pada tata letak."""
    return " ".join(statement.split())


def person(name, payday=1):
    return SimpleNamespace(id=uuid.uuid4(), name=name, payday_day=payday)


# ── membership ──────────────────────────────────────────────────────────────

class MembershipQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_membership_selects_family_household_only(self):
        user = SimpleNamespace(id=uuid.uuid4())
        row = SimpleNamespace(household_id=uuid.uuid4(), role=HouseholdRole.owner)
        db = db_with(FakeResult(row))
        self.assertIs(await hc.membership(db, user), row)  # hasilnya `scalar_one_or_none()` apa adanya
        (call,) = db.execute.call_args_list  # tepat satu kueri
        compiled = call.args[0].compile(dialect=postgresql.dialect())
        statement = norm(str(compiled))
        # Digabung ke households, dan hanya baris ruang keluarga yang terpilih (parameter terikat 'rumah_tangga').
        self.assertIn(
            "FROM household_members JOIN households ON households.id = household_members.household_id", statement
        )
        self.assertIn("household_members.user_id = %(user_id_1)s::UUID", statement)
        bound = re.search(r"households\.type = %\((\w+)\)s", statement)
        self.assertIsNotNone(bound, statement)
        self.assertEqual(compiled.params[bound.group(1)], "rumah_tangga")
        self.assertEqual(compiled.params["user_id_1"], user.id)

    async def test_membership_is_ruang_keanggotaan_keluarga(self):
        # Satu definisi "keanggotaan ruang keluarga" (Plugin R2): `membership` meneruskan ke
        # `ruang.keanggotaan_keluarga` dan tidak punya kueri sendiri.
        user = SimpleNamespace(id=uuid.uuid4())
        row = SimpleNamespace(household_id=uuid.uuid4(), role=HouseholdRole.member)
        db = db_with()
        family = AsyncMock(return_value=row)
        with patch.object(ruang, "keanggotaan_keluarga", family):
            self.assertIs(await hc.membership(db, user), row)
        family.assert_awaited_once_with(db, user.id)
        db.execute.assert_not_awaited()


class PaydayContextForHouseholdTests(unittest.IsolatedAsyncioTestCase):
    """`payday_context(db, user, household_id=…)`: konteks dan izin dihitung untuk household yang diminta (ruang tulis R2
    di `POST /snapshots/recompute`) lewat `ruang.keanggotaan`, bukan lewat keanggotaan ruang keluarga. Tiruan keduanya
    sengaja berbeda: di ruang keluarga Budi member di rumah berdua (tidak boleh mengubah), di household yang diminta ia
    owner (boleh)."""

    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.family_member = SimpleNamespace(household_id=uuid.uuid4(), role=HouseholdRole.member)
        self.target_id = uuid.uuid4()
        self.target_member = SimpleNamespace(household_id=self.target_id, role=HouseholdRole.owner)
        self.family = AsyncMock(return_value=self.family_member)
        self.one = AsyncMock(return_value=self.target_member)
        self.enterContext(patch.object(ruang, "keanggotaan_keluarga", self.family))
        self.enterContext(patch.object(ruang, "keanggotaan", self.one))

    @staticmethod
    def rows(*members):
        """Baris `member_rows` (role, created_at, user_id, name, payday_day), urut bergabung."""
        return [(role, datetime(2026, 1, i + 1, tzinfo=timezone.utc), uid, name, 1)
                for i, (role, uid, name) in enumerate(members)]

    async def test_household_id_uses_the_membership_in_that_household(self):
        target = SimpleNamespace(id=self.target_id, name="Dapur Nusa", type="usaha", payday_day=10)
        db = db_with(FakeResult(target), FakeResult(rows=self.rows(
            (HouseholdRole.owner, self.user.id, "Budi"), (HouseholdRole.member, uuid.uuid4(), "Cici"),
        )))
        ctx = await hc.payday_context(db, self.user, household_id=self.target_id)
        self.one.assert_awaited_once_with(db, self.user.id, self.target_id)
        self.family.assert_not_awaited()
        self.assertIs(ctx.household, target)
        self.assertEqual(ctx.role, HouseholdRole.owner)
        self.assertEqual(ctx.payday_day, 10)
        self.assertEqual(ctx.member_count, 2)
        self.assertIs(ctx.can_change, True)
        self.assertIsNone(ctx.owner_name)

    async def test_without_household_id_it_is_the_family_space(self):
        home = SimpleNamespace(id=self.family_member.household_id, name="Rumah Ani", payday_day=25)
        db = db_with(FakeResult(home), FakeResult(rows=self.rows(
            (HouseholdRole.owner, uuid.uuid4(), "Ani"), (HouseholdRole.member, self.user.id, "Budi"),
        )))
        ctx = await hc.payday_context(db, self.user)
        self.family.assert_awaited_once_with(db, self.user.id)
        self.one.assert_not_awaited()
        self.assertIs(ctx.household, home)
        self.assertIs(ctx.can_change, False)
        self.assertEqual(ctx.owner_name, "Ani")

    async def test_not_a_member_of_that_household_is_none(self):
        self.one.return_value = None
        db = db_with()
        self.assertIsNone(await hc.payday_context(db, self.user, household_id=self.target_id))
        self.family.assert_not_awaited()  # tidak jatuh ke ruang keluarga
        db.execute.assert_not_awaited()


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class MembershipIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Keanggotaan sungguhan di SQLite in-memory: yang diuji perilaku kueri (tidak melempar, tidak memilih ruang usaha),
    bukan teks SQL-nya. Budi anggota ruang keluarga (Rumah Budi) sekaligus pemilik ruang usaha (Dapur Nusa); Cici hanya
    pemilik ruang usaha."""

    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.Session() as db:
            self.budi, self.cici = User(name="Budi"), User(name="Cici")
            self.family = Household(name="Rumah Budi")  # type bawaan: rumah_tangga
            self.business = Household(name="Dapur Nusa", type=HouseholdType.USAHA)
            db.add_all([self.budi, self.cici, self.family, self.business])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=self.budi.id, household_id=self.family.id, role=HouseholdRole.member),
                HouseholdMember(user_id=self.budi.id, household_id=self.business.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.cici.id, household_id=self.business.id, role=HouseholdRole.owner),
            ])
            await db.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_user_in_family_and_business_space_gets_the_family_membership(self):
        # Tanpa filter, dua baris keanggotaan membuat `scalar_one_or_none()` melempar MultipleResultsFound.
        async with self.Session() as db:
            member = await hc.membership(db, self.budi)
        self.assertEqual(member.household_id, self.family.id)
        self.assertEqual(member.role, HouseholdRole.member)

    async def test_user_only_in_a_business_space_has_no_family_membership(self):
        async with self.Session() as db:
            self.assertIsNone(await hc.membership(db, self.cici))
            self.assertIsNone(await hc.payday_context(db, self.cici))

    async def test_payday_context_acts_on_the_family_space(self):
        # Profil dan recompute memakai `payday_context`: keduanya harus melihat ruang keluarga, bukan ruang usaha.
        async with self.Session() as db:
            ctx = await hc.payday_context(db, self.budi)
        self.assertEqual(ctx.household.id, self.family.id)
        self.assertEqual(ctx.household.type, HouseholdType.RUMAH_TANGGA)
        self.assertEqual(ctx.role, HouseholdRole.member)
        self.assertEqual(ctx.member_count, 1)

    async def test_payday_context_for_a_given_household_uses_that_membership(self):
        # `household_id` (ruang tulis R2 di `POST /snapshots/recompute`): konteks household itu dengan peran user di
        # sana, lewat kueri R2 sungguhan.
        async with self.Session() as db:
            ctx = await hc.payday_context(db, self.budi, household_id=self.business.id)
            self.assertEqual(ctx.household.id, self.business.id)
            self.assertEqual(ctx.role, HouseholdRole.owner)
            self.assertEqual(ctx.member_count, 2)
            self.assertIs(ctx.can_change, True)
            # Bukan anggota household itu → None (tidak jatuh ke ruang lain).
            self.assertIsNone(await hc.payday_context(db, self.cici, household_id=self.family.id))

    async def test_profile_stays_on_the_family_space_whichever_space_is_open(self):
        # `GET`/`PUT /user/profile` tidak membaca header ruang (Plugin R2): cermin `users.payday_day` milik ruang
        # keluarga, jadi siklus yang ditampilkan dan diubah lewat profil selalu milik ruang keluarga, juga saat ruang
        # usaha sedang dibuka. Ruang usaha di sini sengaja berbeda (nama, dua anggota).
        import httpx
        from fastapi import Depends
        from app.api.routes import user_settings

        app = FastAPI()
        ruang.install(app)
        app.include_router(user_settings.router, prefix="/user")

        async def _db():
            async with self.Session() as db:
                yield db

        async def _user(db=Depends(get_db)):  # dimuat di sesi request (created_at dari server)
            return await db.get(User, self.budi.id)

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = _user
        business_open = {ruang.RUANG_HEADER: str(self.business.id)}
        set_payday = AsyncMock(return_value={"changed": True, "members": 1, "recomputed": 0})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            res = await client.get("/user/profile", headers=business_open)
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual((res.json()["household_name"], res.json()["household_member_count"]), ("Rumah Budi", 1))
            self.assertIs(res.json()["payday_locked"], False)
            with patch.object(user_settings, "set_household_payday", set_payday):
                res = await client.put("/user/profile", json={"payday_day": 7}, headers=business_open)
        self.assertEqual(res.status_code, 200, res.text)
        set_payday.assert_awaited_once()
        _db_arg, changed, day = set_payday.await_args.args
        self.assertEqual((changed.id, day), (self.family.id, 7))


# ── mirrors_users ───────────────────────────────────────────────────────────

class MirrorsUsersTests(unittest.TestCase):
    def test_mirrors_users(self):
        cases = (
            (SimpleNamespace(type="rumah_tangga"), True),
            (SimpleNamespace(type="usaha"), False),
            (SimpleNamespace(), True),  # tanpa atribut `type`: stub tes lama, dihitung ruang keluarga
            (SimpleNamespace(type=None), True),
            (SimpleNamespace(type=""), True),
            # Objek ORM yang belum di-flush: `type` masih None (bawaan kolom baru terisi saat INSERT).
            (Household(name="Baru"), True),
            (Household(name="Baru", type=HouseholdType.USAHA), False),
        )
        for candidate, expected in cases:
            with self.subTest(type=getattr(candidate, "type", "<tanpa type>")):
                self.assertIs(hc.mirrors_users(candidate), expected)


# ── set_household_payday dan heal ───────────────────────────────────────────

class SetPaydayByTypeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Semua IO di sekitar langkah `set_household_payday` diganti (pola test_household_cycle_change).
        self.recompute = AsyncMock(return_value=[{}] * 12)
        self.invalidate = AsyncMock()
        self.kirim = AsyncMock(return_value={"web"})
        self.enterContext(patch.object(hc, "recompute_history", self.recompute))
        self.enterContext(patch.object(hc.advisor_cache, "invalidate", self.invalidate))
        self.enterContext(patch.object(hc.notification_service, "kirim", self.kirim))

    @staticmethod
    def space(type_, payday=1):
        """Household dengan dua anggota: Budi (pelaku) dan Ani; `db` mengembalikan keduanya untuk kueri anggota."""
        space = SimpleNamespace(id=uuid.uuid4(), name="Dapur Nusa", type=type_, payday_day=payday)
        budi, ani = person("Budi", payday), person("Ani", payday)
        return space, budi, ani, db_with(FakeResult(rows=[budi, ani]))

    async def test_set_payday_on_business_space_does_not_touch_users(self):
        space, budi, ani, db = self.space("usaha", payday=1)
        result = await hc.set_household_payday(db, space, 25, actor=budi)
        self.assertEqual(space.payday_day, 25)
        self.assertEqual((budi.payday_day, ani.payday_day), (1, 1))  # cermin ruang keluarga mereka tidak ikut
        db.commit.assert_awaited_once()
        self.recompute.assert_awaited_once_with(space.id, 12)
        # Selebihnya sama dengan ruang keluarga: cache advisor, hitungan anggota, notifikasi ke anggota selain pelaku.
        self.invalidate.assert_awaited_once_with(space.id)
        self.assertEqual(result, {"changed": True, "members": 2, "recomputed": 12})
        self.kirim.assert_awaited_once()
        call = self.kirim.await_args
        self.assertIs(call.args[0], ani)
        self.assertEqual(call.args[1:], (
            NotificationType.system, TITLE,
            "Tanggal gajian Dapur Nusa kini tanggal 25 (diubah Budi). Riwayat 12 periode terakhir dihitung ulang.",
        ))

    async def test_set_payday_on_family_space_still_mirrors_users(self):
        space, budi, ani, db = self.space("rumah_tangga", payday=1)
        result = await hc.set_household_payday(db, space, 25, actor=budi)
        self.assertEqual((space.payday_day, budi.payday_day, ani.payday_day), (25, 25, 25))
        db.commit.assert_awaited_once()
        self.recompute.assert_awaited_once_with(space.id, 12)
        self.assertEqual(result, {"changed": True, "members": 2, "recomputed": 12})

    async def test_business_space_same_day_is_still_noop(self):
        space, budi, _, _ = self.space("usaha", payday=25)
        db = db_with()
        self.assertEqual(await hc.set_household_payday(db, space, 25, actor=budi), {"changed": False})
        db.commit.assert_not_awaited()
        self.recompute.assert_not_awaited()
        self.kirim.assert_not_awaited()


class HealByTypeTests(unittest.IsolatedAsyncioTestCase):
    async def test_heal_skips_business_space(self):
        space = SimpleNamespace(id=uuid.uuid4(), name="Dapur Nusa", type="usaha", payday_day=25)
        # Cermin anggota (siklus ruang keluarga mereka) berbeda dari tanggal ruang usaha, dan itu memang benar.
        member = person("Ani", payday=1)
        db = db_with(FakeResult(rows=[member]))
        with self.assertNoLogs("jatahku.household_cycle", "WARNING"):
            fixed = await hc.heal(db, space)
        self.assertEqual(fixed, [])
        self.assertEqual(member.payday_day, 1)
        db.execute.assert_not_called()  # tanpa kueri apa pun
        db.commit.assert_not_awaited()

    async def test_heal_still_heals_family_space(self):
        space = SimpleNamespace(id=uuid.uuid4(), name="Rumah Ani", type="rumah_tangga", payday_day=25)
        member = person("Ani", payday=1)
        db = db_with(FakeResult(rows=[member]))
        with self.assertLogs("jatahku.household_cycle", "WARNING"):
            fixed = await hc.heal(db, space)
        self.assertEqual(fixed, [member])
        self.assertEqual(member.payday_day, 25)
        db.commit.assert_awaited_once()


# ── join ────────────────────────────────────────────────────────────────────

def user_row():
    return SimpleNamespace(id=uuid.uuid4(), name="Budi", payday_day=1)


def business_row(payday_day=10):
    return SimpleNamespace(id=HOUSEHOLD_ID, name="Dapur Nusa", currency="IDR", type="usaha", payday_day=payday_day)


def family_row(payday_day=25):
    return SimpleNamespace(id=HOUSEHOLD_ID, name="Rumah Ani", currency="IDR", type="rumah_tangga",
                           payday_day=payday_day)


def fake_redis():
    """Redis palsu: `get` mengembalikan id household sebagai bytes (seperti redis asli); `delete`/`close` dicatat."""
    found = str(HOUSEHOLD_ID).encode()
    return SimpleNamespace(get=AsyncMock(return_value=found), delete=AsyncMock(), close=AsyncMock())


def record_order(**mocks):
    """Lampirkan semua `mocks` ke satu MagicMock manajer; hasilnya fungsi yang mengembalikan nama panggilan urut."""
    manager = MagicMock()
    for name, mock in mocks.items():
        manager.attach_mock(mock, name)
    return lambda: [name for name, _args, _kwargs in manager.mock_calls]


def real_adopt():
    """`adopt_household_payday` asli yang terekam: bila join salah memanggilnya untuk ruang usaha, cermin user
    benar-benar tertimpa dan tes "cermin tetap" gagal, bukan lolos karena tiruan yang tidak berbuat apa-apa."""
    return AsyncMock(wraps=hc.adopt_household_payday)


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


class WebJoinByTypeTests(unittest.TestCase):
    """Join web per jenis ruang. Sejak Plugin R2 route menolak undangan ke household selain ruang keluarga (400 "Kode
    invite tidak valid atau expired") SEBELUM mengubah apa pun, jadi `adopt_household_payday` hanya pernah sampai ke ruang
    keluarga. Tes ruang usaha di sini dulu (Task 8b) mengharapkan 200 tanpa adopsi; premis itu gugur oleh aturan keamanan
    R2, dan kini tes itu mengunci penolakannya dari sisi siklus: tanpa adopsi, cermin user utuh, tanpa commit."""

    def setUp(self):
        self.user = user_row()
        self.redis = fake_redis()
        self.adopt = real_adopt()
        self.payday = AsyncMock(return_value=10)  # `household_payday`: undangan yang ditolak tidak membaca tanggal
        for patcher in (
            patch.object(household, "_redis", new=AsyncMock(return_value=self.redis)),
            patch.object(household, "adopt_household_payday", new=self.adopt),
            patch.object(household, "household_payday", new=self.payday),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def client_for(self, joined):
        """Rute asli di aplikasi mini; login dan sesi DB diganti tiruan. Urutan route: household tujuan (`db.get`, cek
        ruang keluarga Plugin R2) → sudah anggota household itu? (belum) → keanggotaan ruang keluarga lama (tidak ada) →
        muat household yang dimasuki."""
        self.db = db_with(FakeResult(None), FakeResult(None), FakeResult(joined))
        self.db.get = AsyncMock(return_value=joined)
        self.db.delete = AsyncMock()
        app = FastAPI()
        app.include_router(household.router, prefix="/household")
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: self.db
        return TestClient(app)

    def test_web_join_business_space_is_rejected_before_any_change(self):
        client = self.client_for(business_row(payday_day=10))
        res = client.post("/household/join", json={"code": CODE})
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"], "Kode invite tidak valid atau expired")
        self.adopt.assert_not_awaited()
        self.payday.assert_not_awaited()
        self.assertEqual(self.user.payday_day, 1)  # cermin ruang keluarga user tidak berubah
        # Tidak ada keanggotaan yang ditambah atau dihapus, dan tidak ada yang disimpan.
        self.db.add.assert_not_called()
        self.db.delete.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    def test_web_join_family_space_still_adopts(self):
        family = family_row(payday_day=25)
        client = self.client_for(family)
        res = client.post("/household/join", json={"code": CODE})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"status": "joined", "household_name": "Rumah Ani", "payday_day": 25})
        self.adopt.assert_awaited_once_with(self.db, self.user, family)
        self.assertEqual(self.user.payday_day, 25)  # adopsi sungguhan mencerminkannya
        self.db.commit.assert_awaited_once()


class BotJoinByTypeTests(unittest.IsolatedAsyncioTestCase):
    """`/join` di bot (dan chat web) per jenis ruang; penolakan undangan ruang usaha dari Plugin R2, seperti join web."""

    def setUp(self):
        self.user = user_row()
        self.redis = fake_redis()
        self.adopt = real_adopt()
        for patcher in (
            patch.object(household_cmd, "AsyncSessionLocal", new=lambda: FakeSession(self.db)),
            patch.object(household_cmd, "get_or_create_user", new=AsyncMock(return_value=self.user)),
            patch.object(household_cmd, "adopt_household_payday", new=self.adopt),
            # `import redis.asyncio` terjadi di dalam cmd_join, jadi yang ditiru `from_url` di modul redis.
            patch("redis.asyncio.from_url", new=MagicMock(return_value=self.redis)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def join(self, joined):
        """Jalankan `cmd_join`; mengembalikan `reply_text`. Urutan: household tujuan (`db.get`, cek ruang keluarga
        Plugin R2) → sudah anggota household itu? (belum) → keanggotaan ruang keluarga lama (tidak ada) → muat household
        → hitung anggota (setelah commit)."""
        self.db = db_with(FakeResult(None), FakeResult(None), FakeResult(joined), FakeResult(2))
        self.db.get = AsyncMock(return_value=joined)
        self.db.delete = AsyncMock()
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=123, first_name="Tes")
        update.message.reply_text = AsyncMock()
        await household_cmd.cmd_join(update, SimpleNamespace(args=[CODE]))
        return update.message.reply_text

    async def test_bot_join_business_space_is_rejected_before_any_change(self):
        reply = await self.join(business_row(payday_day=10))
        reply.assert_awaited_once_with("❌ Kode invite tidak valid atau sudah expired.")
        self.adopt.assert_not_awaited()
        self.assertEqual(self.user.payday_day, 1)  # cermin ruang keluarga user tidak berubah
        self.db.add.assert_not_called()
        self.db.delete.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    async def test_bot_join_family_space_reply_is_unchanged(self):
        family = family_row(payday_day=25)
        reply = await self.join(family)
        reply.assert_awaited_once()
        self.assertEqual(
            reply.await_args.args[0],
            "✅ Bergabung ke *Rumah Ani*!\n\n"
            "Sekarang ada 2 anggota.\n"
            "Semua amplop dan transaksi sekarang shared.\n"
            "Siklus anggaranmu sekarang mengikuti rumah ini: tanggal 25.\n\n"
            "Ketik /status untuk lihat budget bersama.",
        )
        self.adopt.assert_awaited_once_with(self.db, self.user, family)
        self.assertEqual(self.user.payday_day, 25)  # adopsi sungguhan mencerminkannya
        self.db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
