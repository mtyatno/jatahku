"""API Admin "Aturan belajar" Kotak Struk (task L4a; spec 2026-11-01 §6, pre-flight G5, G6, G10, K10): daftar aturan
per status, setujui/tolak/cabut, angka suara tanpa teks label, dan `rules_pending` di statistik Scan Struk.
SQLite in-memory; klien httpx langsung ke ASGI.
Run: python -m unittest app.tests.test_kotak_admin_aturan -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.orm import configure_mappers

from app.core import deps
from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.models.models import Household, ProofRule, ProofRuleVote, User
from app.services.kotak_struk import belajar

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
T0 = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
STATUSES = ("menunggu", "disetujui", "ditolak", "dicabut")
ADMIN_PATHS = {
    ("GET", "/admin/kotak/rules"),
    ("POST", "/admin/kotak/rules/{rule_id}/setujui"),
    ("POST", "/admin/kotak/rules/{rule_id}/tolak"),
    ("POST", "/admin/kotak/rules/{rule_id}/cabut"),
    ("GET", "/admin/kotak/votes"),
}


class RoutesRegisteredTests(unittest.TestCase):
    """Rute terpasang di aplikasi sungguhan, admin saja, dengan response_model (openapi_cek melihat bentuknya)."""

    def test_routes_are_admin_only_with_response_models(self):
        from app.main import app
        found = {}
        for route in app.routes:
            for method in getattr(route, "methods", None) or ():
                if (method, getattr(route, "path", None)) in ADMIN_PATHS:
                    found[(method, route.path)] = route
        self.assertEqual(set(found), ADMIN_PATHS)
        for key, route in found.items():
            calls = {d.call for d in route.dependant.dependencies}
            self.assertIn(deps.require_admin, calls, key)
            self.assertIsNotNone(route.response_model, key)
            self.assertIn("admin", route.tags, key)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class AdminRulesBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from app.api.routes import admin as admin_routes
        from app.api.routes import admin_kotak
        asyncio.get_running_loop().slow_callback_duration = 2.0
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        # Resep SQLAlchemy untuk pysqlite: SAVEPOINT (approved_rules) butuh BEGIN eksplisit.
        event.listen(self.engine.sync_engine, "connect", lambda conn, _rec: setattr(conn, "isolation_level", None))
        event.listen(self.engine.sync_engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.Session() as db:
            self.admin = User(name="Pemilik Tes", is_admin=True)
            self.user = User(name="Ani", is_admin=False)
            self.user2 = User(name="Budi", is_admin=False)
            self.hh = Household(name="Rumah")
            db.add_all([self.admin, self.user, self.user2, self.hh])
            await db.commit()
        self.current = self.admin

        app = FastAPI()
        app.include_router(admin_routes.router, prefix="/admin", tags=["admin"])
        app.include_router(admin_kotak.router, prefix="/admin/kotak", tags=["admin"])
        app.dependency_overrides[get_current_user] = lambda: self.current

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.c.aclose)
        belajar.invalidate_rules_cache()
        self.addCleanup(belajar.invalidate_rules_cache)

    async def rule(self, value, *, kind="label_total", key="gopay", status="menunggu", users=2, households=1,
                   created_at=T0, **cols):
        async with self.Session() as db:
            r = ProofRule(kind=kind, rule_key=key, value=value, users=users, households=households, status=status,
                          created_at=created_at, **cols)
            db.add(r)
            await db.commit()
            return r

    async def get_rule(self, rule_id):
        async with self.Session() as db:
            return (await db.execute(select(ProofRule).where(ProofRule.id == rule_id))).scalar_one()

    async def vote(self, value, user, *, kind="label_total", key="gopay", household=None):
        async with self.Session() as db:
            db.add(ProofRuleVote(kind=kind, rule_key=key, value=value, user_id=user.id, household_id=household))
            await db.commit()

    async def act(self, rule_id, action, body=None):
        if body is None:
            return await self.c.post(f"/admin/kotak/rules/{rule_id}/{action}")
        return await self.c.post(f"/admin/kotak/rules/{rule_id}/{action}", json=body)


class ListRulesTests(AdminRulesBase):
    async def test_default_lists_pending_with_counts_over_all_statuses(self):
        a = await self.rule("total bayar", users=2, created_at=T0)
        b = await self.rule("jumlah", users=3, created_at=T0 + timedelta(hours=2))
        c = await self.rule("total", users=2, created_at=T0 - timedelta(hours=1))
        await self.rule("ke", kind="label_pihak", status="disetujui", decided_at=T0, decided_by=self.admin.id)
        await self.rule("tanggal", kind="label_tanggal", status="ditolak")
        await self.rule("penerima", kind="label_pihak", status="ditolak")
        r = await self.c.get("/admin/kotak/rules")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["counts"], {"menunggu": 3, "disetujui": 1, "ditolak": 2, "dicabut": 0})
        # users turun, lalu created_at naik
        self.assertEqual([x["id"] for x in body["rules"]], [str(b.id), str(c.id), str(a.id)])
        self.assertTrue(all(x["status"] == "menunggu" for x in body["rules"]))

    async def test_each_status_filter_and_semua(self):
        ids = {}
        for st in STATUSES:
            ids[st] = (await self.rule(f"total {st}", status=st)).id
        for st in STATUSES:
            body = (await self.c.get(f"/admin/kotak/rules?status={st}")).json()
            self.assertEqual([x["id"] for x in body["rules"]], [str(ids[st])], st)
        body = (await self.c.get("/admin/kotak/rules?status=semua")).json()
        self.assertEqual({x["id"] for x in body["rules"]}, {str(i) for i in ids.values()})
        self.assertEqual(body["counts"], {st: 1 for st in STATUSES})

    async def test_unknown_status_is_422(self):
        self.assertEqual((await self.c.get("/admin/kotak/rules?status=apa")).status_code, 422)

    async def test_row_shape_decider_name_and_synthetic_example(self):
        decided = T0 + timedelta(days=1)
        r = await self.rule("total bayar", users=4, households=2, status="disetujui", decided_at=decided,
                            decided_by=self.admin.id, note="cocok dengan GoPay")
        row = (await self.c.get("/admin/kotak/rules?status=disetujui")).json()["rules"][0]
        self.assertEqual(set(row), {"id", "kind", "rule_key", "value", "users", "households", "status", "created_at",
                                    "decided_at", "decided_by", "decided_by_name", "note", "example", "warning"})
        self.assertEqual((row["id"], row["kind"], row["rule_key"], row["value"], row["users"], row["households"]),
                         (str(r.id), "label_total", "gopay", "total bayar", 4, 2))
        self.assertEqual((row["decided_by"], row["decided_by_name"], row["note"]),
                         (str(self.admin.id), "Pemilik Tes", "cocok dengan GoPay"))
        self.assertEqual(datetime.fromisoformat(row["decided_at"]).replace(tzinfo=None), decided.replace(tzinfo=None))
        self.assertEqual(row["example"], "Total bayar Rp##.###")
        self.assertFalse(row["warning"])

    async def test_pending_row_has_no_decision(self):
        await self.rule("total bayar")
        row = (await self.c.get("/admin/kotak/rules")).json()["rules"][0]
        self.assertEqual((row["decided_at"], row["decided_by"], row["decided_by_name"], row["note"]),
                         (None, None, None, None))

    async def test_synthetic_examples_never_carry_digits(self):
        await self.rule("ke", kind="label_pihak")
        await self.rule("tanggal transaksi", kind="label_tanggal")
        await self.rule("total bayar", kind="label_total")
        rows = {x["kind"]: x["example"] for x in (await self.c.get("/admin/kotak/rules")).json()["rules"]}
        self.assertEqual(rows, {"label_pihak": "Ke NAMA PENERIMA", "label_tanggal": "Tanggal transaksi ## Okt ####",
                                "label_total": "Total bayar Rp##.###"})
        self.assertFalse(any(ch.isdigit() for ex in rows.values() for ch in ex))

    async def test_warning_for_status_or_method_words(self):
        for value, kind in [("status", "label_pihak"), ("metode pembayaran", "label_total"),
                            ("sumber dana", "label_pihak"), ("transaksi berhasil", "label_total"),
                            ("total bayar", "label_total"), ("penerima", "label_pihak"),
                            ("tanggal", "label_tanggal"), ("total pembayaran", "label_total"),
                            ("total spending", "label_total")]:   # kata utuh: "spending" bukan "pending"
            await self.rule(value, kind=kind)
        rows = {x["value"]: x["warning"] for x in (await self.c.get("/admin/kotak/rules")).json()["rules"]}
        self.assertEqual(rows, {"status": True, "metode pembayaran": True, "sumber dana": True,
                                "transaksi berhasil": True, "total bayar": False, "penerima": False,
                                "tanggal": False, "total pembayaran": False, "total spending": False})

    async def test_list_never_writes(self):
        await self.rule("total bayar")
        statements = []
        event.listen(self.engine.sync_engine, "before_cursor_execute",
                     lambda conn, cur, statement, *_a: statements.append(statement))
        self.assertEqual((await self.c.get("/admin/kotak/rules?status=semua")).status_code, 200)
        self.assertEqual((await self.c.get("/admin/kotak/votes")).status_code, 200)
        writes = [s for s in statements if s.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}]
        self.assertEqual(writes, [])


class DecisionTests(AdminRulesBase):
    async def test_setujui_from_pending_fills_decision(self):
        r = await self.rule("total bayar")
        res = await self.act(r.id, "setujui", {"note": "  dicek di tiga bukti  "})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual((body["id"], body["status"], body["decided_by"], body["decided_by_name"], body["note"]),
                         (str(r.id), "disetujui", str(self.admin.id), "Pemilik Tes", "dicek di tiga bukti"))
        self.assertIsNotNone(body["decided_at"])
        self.assertEqual(body["example"], "Total bayar Rp##.###")
        stored = await self.get_rule(r.id)
        self.assertEqual((stored.status, stored.decided_by, stored.note),
                         ("disetujui", self.admin.id, "dicek di tiga bukti"))
        self.assertIsNotNone(stored.decided_at)
        self.assertEqual((stored.users, stored.households, stored.value), (2, 1, "total bayar"))

    async def test_all_legal_transitions(self):
        cases = [("menunggu", "setujui", "disetujui"), ("ditolak", "setujui", "disetujui"),
                 ("dicabut", "setujui", "disetujui"), ("menunggu", "tolak", "ditolak"),
                 ("disetujui", "cabut", "dicabut")]
        for i, (start, action, end) in enumerate(cases):
            r = await self.rule(f"total {i}", status=start)
            res = await self.act(r.id, action)
            self.assertEqual(res.status_code, 200, (start, action, res.text))
            self.assertEqual(res.json()["status"], end)
            self.assertEqual((await self.get_rule(r.id)).status, end)

    async def test_illegal_transitions_are_409_and_change_nothing(self):
        cases = [("disetujui", "setujui"), ("ditolak", "tolak"), ("dicabut", "tolak"), ("disetujui", "tolak"),
                 ("menunggu", "cabut"), ("ditolak", "cabut"), ("dicabut", "cabut")]
        for i, (start, action) in enumerate(cases):
            r = await self.rule(f"total {i}", status=start, note="lama")
            res = await self.act(r.id, action, {"note": "baru"})
            self.assertEqual(res.status_code, 409, (start, action))
            self.assertEqual(res.json()["detail"], "Aturan ini tidak bisa diubah ke status itu")
            stored = await self.get_rule(r.id)
            self.assertEqual((stored.status, stored.note, stored.decided_by), (start, "lama", None))

    async def test_unknown_id_is_404(self):
        for action in ("setujui", "tolak", "cabut"):
            res = await self.act(uuid.uuid4(), action)
            self.assertEqual(res.status_code, 404, action)
            self.assertEqual(res.json()["detail"], "Aturan tidak ditemukan")

    async def test_unknown_action_has_no_route(self):
        r = await self.rule("total bayar")
        self.assertIn((await self.act(r.id, "hapus")).status_code, (404, 405))
        self.assertEqual((await self.get_rule(r.id)).status, "menunggu")

    async def test_note_capped_at_200(self):
        r = await self.rule("total bayar")
        res = await self.act(r.id, "setujui", {"note": "x" * 201})
        self.assertEqual(res.status_code, 422)
        self.assertEqual((await self.get_rule(r.id)).status, "menunggu")
        res = await self.act(r.id, "setujui", {"note": "x" * 200})
        self.assertEqual(res.status_code, 200)
        self.assertEqual((await self.get_rule(r.id)).note, "x" * 200)

    async def test_blank_or_missing_note_is_null(self):
        a = await self.rule("total a")
        b = await self.rule("total b")
        c = await self.rule("total c")
        self.assertIsNone((await self.act(a.id, "setujui")).json()["note"])
        self.assertIsNone((await self.act(b.id, "setujui", {})).json()["note"])
        self.assertIsNone((await self.act(c.id, "setujui", {"note": "   "})).json()["note"])
        self.assertIsNone((await self.get_rule(c.id)).note)

    async def test_rule_text_is_never_taken_from_the_client(self):
        r = await self.rule("total bayar")
        for extra in ({"value": "nama pengirim"}, {"kind": "label_pihak"}, {"status": "disetujui"},
                      {"rule_key": "dana"}, {"users": 99}):
            res = await self.act(r.id, "tolak", {"note": "x", **extra})
            self.assertEqual(res.status_code, 422, extra)
        stored = await self.get_rule(r.id)
        self.assertEqual((stored.kind, stored.rule_key, stored.value, stored.status, stored.users),
                         ("label_total", "gopay", "total bayar", "menunggu", 2))

    async def test_bad_id_is_422(self):
        self.assertEqual((await self.c.post("/admin/kotak/rules/bukan-uuid/setujui")).status_code, 422)


class CacheTests(AdminRulesBase):
    async def test_invalidate_runs_after_commit(self):
        """Commit LALU invalidate (L3): pembacaan yang dimulai sebelum commit tidak boleh menyimpan status lama."""
        from sqlalchemy.ext.asyncio import AsyncSession
        r = await self.rule("total bayar")
        seen = []
        original_commit = AsyncSession.commit

        async def commit(session):
            seen.append("commit")
            return await original_commit(session)

        with patch.object(belajar, "invalidate_rules_cache", side_effect=lambda: seen.append("invalidate")) as inv, \
                patch.object(AsyncSession, "commit", commit):
            res = await self.act(r.id, "setujui")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(inv.call_count, 1)
        self.assertEqual(seen, ["commit", "invalidate"])
        self.assertEqual((await self.get_rule(r.id)).status, "disetujui")

    async def test_no_invalidate_on_404_or_409(self):
        r = await self.rule("total bayar", status="ditolak")
        with patch.object(belajar, "invalidate_rules_cache") as inv:
            self.assertEqual((await self.act(r.id, "cabut")).status_code, 409)
            self.assertEqual((await self.act(uuid.uuid4(), "setujui")).status_code, 404)
        inv.assert_not_called()

    async def test_reader_sees_decision_without_waiting_for_cache(self):
        r = await self.rule("total bayar")
        async with self.Session() as db:
            self.assertEqual(await belajar.approved_rules(db), {})        # cache terisi: kosong
        self.assertEqual((await self.act(r.id, "setujui")).status_code, 200)
        async with self.Session() as db:
            rules = await belajar.approved_rules(db)
        self.assertEqual(rules["gopay"]["label_total"], ["total bayar"])
        self.assertEqual((await self.act(r.id, "cabut")).status_code, 200)
        async with self.Session() as db:
            self.assertEqual(await belajar.approved_rules(db), {})

    async def test_tolak_also_invalidates(self):
        r = await self.rule("total bayar")
        with patch.object(belajar, "invalidate_rules_cache") as inv:
            self.assertEqual((await self.act(r.id, "tolak")).status_code, 200)
        inv.assert_called_once_with()


class VotesTests(AdminRulesBase):
    async def test_counts_per_key_and_kind_without_label_text(self):
        labels = ["jumlah kirim uang", "total bayar", "nama penerima", "tanggal transaksi"]
        await self.vote("jumlah kirim uang", self.user, household=self.hh.id)
        await self.vote("total bayar", self.user)
        await self.vote("total bayar", self.user2)
        await self.vote("nama penerima", self.user, kind="label_pihak")
        await self.vote("tanggal transaksi", self.user2, kind="label_tanggal", key="dana")
        res = await self.c.get("/admin/kotak/votes")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(set(body), {"rows"})
        self.assertEqual(body["rows"], [
            {"rule_key": "gopay", "kind": "label_total", "users": 2, "values": 2},
            {"rule_key": "dana", "kind": "label_tanggal", "users": 1, "values": 1},
            {"rule_key": "gopay", "kind": "label_pihak", "users": 1, "values": 1},
        ])
        for label in labels:
            self.assertNotIn(label, res.text)
        for word in ("jumlah", "bayar", "penerima", "transaksi"):
            self.assertNotIn(word, res.text)
        self.assertNotIn(str(self.user.id), res.text)
        self.assertNotIn(str(self.hh.id), res.text)

    async def test_empty(self):
        self.assertEqual((await self.c.get("/admin/kotak/votes")).json(), {"rows": []})


class AdminOnlyTests(AdminRulesBase):
    async def test_normal_user_gets_403_everywhere_and_nothing_changes(self):
        r = await self.rule("total bayar")
        await self.vote("total bayar", self.user)
        self.current = self.user
        with patch.object(belajar, "invalidate_rules_cache") as inv:
            for res in (await self.c.get("/admin/kotak/rules"), await self.c.get("/admin/kotak/rules?status=semua"),
                        await self.c.get("/admin/kotak/votes"), await self.act(r.id, "setujui"),
                        await self.act(r.id, "tolak", {"note": "x"}), await self.act(r.id, "cabut"),
                        await self.c.get("/admin/receipt-scans/stats")):
                self.assertEqual(res.status_code, 403, res.request.url)
                self.assertNotIn("total bayar", res.text)
        inv.assert_not_called()
        stored = await self.get_rule(r.id)
        self.assertEqual((stored.status, stored.decided_by, stored.note), ("menunggu", None, None))


class StatsTests(AdminRulesBase):
    async def test_rules_pending_in_accuracy_stats(self):
        from app.services.receipt_scan import accuracy_stats
        async with self.Session() as db:
            self.assertEqual((await accuracy_stats(db))["rules_pending"], 0)
        await self.rule("total a")
        await self.rule("total b", created_at=T0 - timedelta(days=90))   # lama tetap dihitung: bukan per bulan
        await self.rule("total c", status="disetujui")
        await self.rule("total d", status="ditolak")
        await self.rule("total e", status="dicabut")
        async with self.Session() as db:
            self.assertEqual((await accuracy_stats(db))["rules_pending"], 2)

    async def test_rules_pending_in_stats_endpoint(self):
        await self.rule("total a")
        with patch("app.services.receipt_llm.budget_status", new=AsyncMock(return_value=None)):
            res = await self.c.get("/admin/receipt-scans/stats")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["rules_pending"], 1)


if __name__ == "__main__":
    unittest.main()
