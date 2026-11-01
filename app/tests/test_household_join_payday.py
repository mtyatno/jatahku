"""Siklus household, Task 7: join (web + bot) mengikuti siklus rumah, dan `GET /household/` membawa `payday_day`.

Join web rusak sebelumnya: `code` dideklarasikan sebagai parameter query, sedangkan Settings.jsx mengirimnya di body JSON
(→ 422). Sekarang route menerima keduanya. Anggota baru mengadopsi tanggal gajian household (`adopt_household_payday`,
penulis tunggal `payday_day`) SEBELUM commit keanggotaannya, jadi keanggotaan dan cermin tanggalnya tersimpan dalam satu
transaksi.

Baris `payday_day=None` pada household tiruan disengaja: household yang belum dimigrasi menyimpan NULL, dan `adopt` /
`household_payday` yang menurunkannya. Respons yang membaca atribut mentah akan gagal di sini.

Sejak Plugin R2, join web dan bot lebih dulu memuat household tujuan undangan (`db.get`) dan menolak yang bukan ruang
keluarga sebelum mengubah apa pun; tiruan `db.get` di sini mengembalikan household ruang keluarga (penolakan ruang usaha
dikunci test_household_cycle_r1 dan test_ruang_gerbang). `GET /household/` membaca ruang dari dependency
`ruang_aktif`, yang di sini diganti household tiruan.
Run: python -m unittest app.tests.test_household_join_payday -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import configure_mappers

from app.api.routes import household
from app.bot import household_cmd
from app.core.database import get_db
from app.core.deps import get_current_user
from app.services import ruang
from app.tests.fakes import FakeResult, db_with

# Konfigurasi mapper pertama (~50ms) jangan jatuh di dalam event loop test (HouseholdMember dibuat sungguhan di rute).
configure_mappers()

HOUSEHOLD_ID = uuid.uuid4()
CODE = "ABC12DEF"


def household_row(payday_day=None):
    return SimpleNamespace(id=HOUSEHOLD_ID, name="Rumah Ani", currency="IDR", type="rumah_tangga",
                           payday_day=payday_day)


def user_row():
    return SimpleNamespace(id=uuid.uuid4(), name="Budi", payday_day=1)


def fake_redis(invite_for=HOUSEHOLD_ID):
    """Redis palsu: `get` mengembalikan id household sebagai bytes (seperti redis sungguhan), atau None bila kode tidak
    dikenal; `delete` dan `close` hanya direkam."""
    found = None if invite_for is None else str(invite_for).encode()
    return SimpleNamespace(get=AsyncMock(return_value=found), delete=AsyncMock(), close=AsyncMock())


def record_order(**mocks):
    """Lampirkan semua `mocks` ke satu MagicMock manajer; hasilnya fungsi yang mengembalikan nama panggilan berurutan."""
    manager = MagicMock()
    for name, mock in mocks.items():
        manager.attach_mock(mock, name)
    return lambda: [name for name, _args, _kwargs in manager.mock_calls]


def client_for(db, user):
    """Rute asli household di aplikasi mini; login, sesi DB, dan ruang aktif (Plugin R2) diganti tiruan."""
    app = FastAPI()
    app.include_router(household.router, prefix="/household")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[ruang.ruang_aktif] = lambda: HOUSEHOLD_ID
    return TestClient(app)


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


class JoinRouteTests(unittest.TestCase):
    def setUp(self):
        self.user = user_row()
        self.household = household_row()
        self.redis = fake_redis()
        self.adopt = AsyncMock(return_value=25)
        # Urutan route: household tujuan (`db.get`, cek ruang keluarga Plugin R2) → sudah anggota household itu?
        # (belum) → keanggotaan ruang keluarga lama (tidak ada) → muat household.
        self.db = db_with(FakeResult(None), FakeResult(None), FakeResult(self.household))
        self.db.get = AsyncMock(return_value=self.household)
        for patcher in (
            patch.object(household, "_redis", new=AsyncMock(return_value=self.redis)),
            patch.object(household, "adopt_household_payday", new=self.adopt),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = client_for(self.db, self.user)

    def assert_rejected(self, res, detail):
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"], detail)
        self.adopt.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    def test_join_accepts_code_in_json_body(self):
        # Inilah permintaan Settings.jsx; sebelumnya 422 {'loc': ['query', 'code'], 'msg': 'Field required'}.
        res = self.client.post("/household/join", json={"code": "abc12def"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"status": "joined", "household_name": "Rumah Ani", "payday_day": 25})
        self.redis.get.assert_awaited_once_with("invite:ABC12DEF")
        self.redis.delete.assert_awaited_once_with("invite:ABC12DEF")  # kode pakai-sekali tetap dihapus
        self.adopt.assert_awaited_once_with(self.db, self.user, self.household)

    def test_join_still_accepts_query_code(self):
        res = self.client.post("/household/join?code=ABC12DEF")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["payday_day"], 25)
        self.redis.get.assert_awaited_once_with("invite:ABC12DEF")

    def test_join_without_code_400(self):
        blank = (
            {},                                  # tanpa query dan body
            {"json": {"code": ""}},
            {"json": {"code": "   "}},
            {"params": {"code": "  "}},
        )
        for request in blank:
            with self.subTest(request=request):
                self.assert_rejected(self.client.post("/household/join", **request), "Kode invite wajib diisi")
        self.redis.get.assert_not_awaited()  # ditolak sebelum menyentuh redis

    def test_join_json_body_without_code_is_400_not_422(self):
        # `JoinRequest.code` opsional: body JSON tanpa kode sama dengan tanpa kode (400 dengan pesan yang dipahami
        # klien), bukan 422 validasi.
        for body in ({}, {"code": None}):
            with self.subTest(body=body):
                self.assert_rejected(self.client.post("/household/join", json=body), "Kode invite wajib diisi")
        self.redis.get.assert_not_awaited()

    def test_join_query_code_with_an_empty_json_body(self):
        # Klien yang mengirim `?code=X` dengan body `{}` (200 sebelum fase ini): query didahulukan.
        res = self.client.post("/household/join?code=ABC12DEF", json={})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["payday_day"], 25)
        self.redis.get.assert_awaited_once_with("invite:ABC12DEF")

    def test_join_code_is_stripped_and_uppercased_and_query_wins(self):
        for request, expected in (
            ({"params": {"code": " abc12def "}}, "invite:ABC12DEF"),
            ({"json": {"code": " abc12def "}}, "invite:ABC12DEF"),
            ({"params": {"code": "QUERY123"}, "json": {"code": "body4567"}}, "invite:QUERY123"),   # query didahulukan
            ({"params": {"code": "  "}, "json": {"code": "body4567"}}, "invite:BODY4567"),         # query kosong → body
        ):
            with self.subTest(request=request):
                self.redis.get.reset_mock()
                self.db.execute.side_effect = [FakeResult(None), FakeResult(None), FakeResult(self.household)]
                res = self.client.post("/household/join", **request)
                self.assertEqual(res.status_code, 200, res.text)
                self.redis.get.assert_awaited_once_with(expected)

    def test_join_adopts_before_commit(self):
        order = record_order(add=self.db.add, adopt=self.adopt, commit=self.db.commit)
        res = self.client.post("/household/join", json={"code": CODE})
        self.assertEqual(res.status_code, 200, res.text)
        names = order()
        for step in ("add", "adopt", "commit"):
            self.assertIn(step, names)
        # Keanggotaan ditambahkan dulu (household tanpa tanggal menurunkannya dari anggotanya), adopsi, lalu satu commit.
        self.assertLess(names.index("add"), names.index("adopt"))
        self.assertLess(names.index("adopt"), names.index("commit"))

    def test_invalid_or_expired_code_does_not_adopt(self):
        self.redis.get.return_value = None
        res = self.client.post("/household/join", json={"code": CODE})
        self.assert_rejected(res, "Kode invite tidak valid atau expired")

    def test_already_member_does_not_adopt(self):
        self.db.execute.side_effect = [FakeResult(SimpleNamespace(household_id=HOUSEHOLD_ID))]
        res = self.client.post("/household/join", json={"code": CODE})
        self.assert_rejected(res, "Kamu sudah bergabung di household ini")


class GetHouseholdTests(unittest.TestCase):
    def test_get_household_includes_payday_day(self):
        member = SimpleNamespace(household_id=HOUSEHOLD_ID)
        hh = household_row()  # payday_day NULL: hanya `household_payday` yang tahu tanggalnya
        db = db_with(FakeResult(member), FakeResult(hh), FakeResult(3))
        payday = AsyncMock(return_value=25)
        with patch.object(household, "household_payday", new=payday):
            res = client_for(db, user_row()).get("/household/")
        self.assertEqual(res.status_code, 200, res.text)
        # Field lama tetap dengan arti yang sama; `payday_day` hanya bertambah.
        self.assertEqual(res.json(), {
            "id": str(HOUSEHOLD_ID), "name": "Rumah Ani", "currency": "IDR", "member_count": 3,
            "type": "rumah_tangga", "payday_day": 25,
        })
        payday.assert_awaited_once_with(db, hh)


class BotJoinTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = user_row()
        self.household = household_row()
        self.redis = fake_redis()
        self.adopt = AsyncMock(return_value=25)
        # Urutan cmd_join: household tujuan (`db.get`, cek ruang keluarga Plugin R2) → sudah anggota household itu?
        # (belum) → keanggotaan ruang keluarga lama (tidak ada) → muat household → hitung anggota (setelah commit).
        self.db = db_with(FakeResult(None), FakeResult(None), FakeResult(self.household), FakeResult(2))
        self.db.get = AsyncMock(return_value=self.household)
        for patcher in (
            patch.object(household_cmd, "AsyncSessionLocal", new=lambda: FakeSession(self.db)),
            patch.object(household_cmd, "get_or_create_user", new=AsyncMock(return_value=self.user)),
            patch.object(household_cmd, "adopt_household_payday", new=self.adopt),
            patch("redis.asyncio.from_url", new=MagicMock(return_value=self.redis)),  # `import redis.asyncio` di dalam cmd_join
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def join(self, code=CODE):
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=123, first_name="Tes")
        update.message.reply_text = AsyncMock()
        await household_cmd.cmd_join(update, SimpleNamespace(args=[code]))
        return update.message.reply_text

    async def test_cmd_join_adopts_payday_and_mentions_it(self):
        order = record_order(add=self.db.add, adopt=self.adopt, commit=self.db.commit)
        reply = await self.join(CODE.lower())
        reply.assert_awaited_once()
        text = reply.await_args.args[0]
        line = "Siklus anggaranmu sekarang mengikuti rumah ini: tanggal 25."
        self.assertIn(line, text)
        self.assertLess(text.index(line), text.index("/status"))  # baris baru sebelum baris /status
        self.assertIn("Sekarang ada 2 anggota.", text)            # baris lama tetap
        self.assertEqual(reply.await_args.kwargs["parse_mode"], "Markdown")
        self.redis.get.assert_awaited_once_with(f"invite:{CODE}")
        self.adopt.assert_awaited_once_with(self.db, self.user, self.household)
        names = order()
        self.assertLess(names.index("add"), names.index("adopt"))
        self.assertLess(names.index("adopt"), names.index("commit"))

    async def test_invalid_code_does_not_adopt(self):
        self.redis.get.return_value = None
        reply = await self.join()
        reply.assert_awaited_once_with("❌ Kode invite tidak valid atau sudah expired.")
        self.adopt.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    async def test_already_member_does_not_adopt(self):
        self.db.execute.side_effect = [FakeResult(SimpleNamespace(household_id=HOUSEHOLD_ID))]
        reply = await self.join()
        reply.assert_awaited_once_with("Kamu sudah bergabung di household ini.")
        self.adopt.assert_not_awaited()
        self.db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
