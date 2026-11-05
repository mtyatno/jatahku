"""Kotak Struk tahap 2 M1d — API Admin tinjauan sampel donasi dan entri korpus (pre-flight A16 §2 "Admin review ->
corpus", K4, K5, K17; Review Focus 2).

`GET /admin/kotak/samples`, `POST .../{id}/setujui|tolak`, `DELETE .../{id}`, `GET .../{id}/korpus`. Ruling M1d: `tolak`
menghapus baris (G2), jadi sampel `ditolak` tidak pernah ada. Persetujuan menyamarkan ulang baris editan (`mask_line`)
dan menolak baris yang masih memuat nomor panjang, alamat email, atau nomor rekening berkelompok (aturan yang sama
dengan penangkapan, `donasi._holds_secret`). Respons tidak pernah memuat `user_id`/`item_id`.
Route asli lewat httpx ASGITransport di atas SQLite in-memory; butuh `aiosqlite`. Semua nama, nomor, dan baris karangan.
Run: python -m unittest app.tests.test_kotak_donasi_admin -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import json
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.orm import configure_mappers

from app.core import deps
from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.models.models import ProofSample, User
from app.scripts import kotak_corpus
from app.services.kotak_struk import config as K

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
T0 = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
# Bukti transfer karangan, sudah tersamar (seperti hasil `donasi.sample_lines`).
LINES = ["Transfer Berhasil", "26 Okt 2026, 09:30 WIB", "Penerima", "BUDI SANTOSO", "Bank Tujuan BRI",
         "Rekening Tujuan …4567", "Nominal Rp150.000", "No. Ref …5678"]
READ = {"doc_type": "transfer", "issuer": None, "total": 150000, "paid_at": "2026-10-26T09:30:00+07:00",
        "counterparty": "BUDI SANTOSO", "status": "berhasil", "flow": "keluar"}
TRUTH = {"total": 150000, "date": "2026-10-26", "flow": None, "app": None}
PATHS = {
    ("GET", "/admin/kotak/samples"),
    ("POST", "/admin/kotak/samples/{sample_id}/setujui"),
    ("POST", "/admin/kotak/samples/{sample_id}/tolak"),
    ("DELETE", "/admin/kotak/samples/{sample_id}"),
    ("GET", "/admin/kotak/samples/{sample_id}/korpus"),
}


class RoutesRegisteredTests(unittest.TestCase):
    """Rute terpasang di aplikasi sungguhan, admin saja; selain DELETE 204 dengan response_model."""

    def test_routes_are_admin_only_with_response_models(self):
        from app.main import app
        found = {}
        for route in app.routes:
            for method in getattr(route, "methods", None) or ():
                if (method, getattr(route, "path", None)) in PATHS:
                    found[(method, route.path)] = route
        self.assertEqual(set(found), PATHS)
        for key, route in found.items():
            self.assertIn(deps.require_admin, {d.call for d in route.dependant.dependencies}, key)
            self.assertIn("admin", route.tags, key)
            if key[0] == "DELETE":
                self.assertEqual(route.status_code, 204)
            else:
                self.assertIsNotNone(route.response_model, key)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class SamplesBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from app.api.routes import admin_kotak
        asyncio.get_running_loop().slow_callback_duration = 2.0
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        event.listen(self.engine.sync_engine, "connect", lambda conn, _rec: setattr(conn, "isolation_level", None))
        event.listen(self.engine.sync_engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.Session() as db:
            self.admin = User(name="Pemilik Tes", is_admin=True)
            self.user = User(name="Rina Wulandari")
            db.add_all([self.admin, self.user])
            await db.commit()
        self.current = self.admin
        app = FastAPI()
        app.include_router(admin_kotak.router, prefix="/admin/kotak", tags=["admin"])
        app.dependency_overrides[get_current_user] = lambda: self.current

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.c.aclose)

    async def sample(self, *, status="menunggu", lines=LINES, truth=TRUTH, rule_key=None, doc_type="transfer",
                     user_name="ANDI PRATAMA", created_at=T0, **cols):
        async with self.Session() as db:
            s = ProofSample(user_id=self.user.id, item_id=uuid.uuid4(), rule_key=rule_key, doc_type=doc_type,
                            trigger="nominal", lines=list(lines), user_name=user_name, truth=truth,
                            today=date(2026, 10, 27), status=status, created_at=created_at,
                            decided_at=T0 if status != "menunggu" else None,
                            decided_by=self.admin.id if status != "menunggu" else None, **cols)
            db.add(s)
            await db.commit()
            return s

    async def get(self, sample_id):
        async with self.Session() as db:
            return (await db.execute(select(ProofSample).where(ProofSample.id == sample_id))).scalar_one_or_none()

    async def approve(self, sample_id, **body):
        body.setdefault("lines", list(LINES))
        return await self.c.post(f"/admin/kotak/samples/{sample_id}/setujui", json=body)

    def assert_no_owner_ids(self, r, *samples):
        self.assertNotIn("user_id", r.text)
        self.assertNotIn("item_id", r.text)
        self.assertNotIn(str(self.user.id), r.text)
        self.assertNotIn(self.user.id.hex, r.text)
        for s in samples:
            self.assertNotIn(str(s.item_id), r.text)
            self.assertNotIn(s.item_id.hex, r.text)


class ListSamplesTests(SamplesBase):
    async def test_lists_per_status_with_counts(self):
        a = await self.sample(created_at=T0 + timedelta(hours=1))
        b = await self.sample(created_at=T0)
        c = await self.sample(status="disetujui", note="oke")
        r = await self.c.get("/admin/kotak/samples")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["counts"], {"menunggu": 2, "disetujui": 1, "ditolak": 0})
        self.assertEqual([x["id"] for x in body["samples"]], [str(b.id), str(a.id)])   # yang lebih dulu dibuat
        r = await self.c.get("/admin/kotak/samples", params={"status": "disetujui"})
        self.assertEqual([x["id"] for x in r.json()["samples"]], [str(c.id)])
        self.assertEqual(r.json()["samples"][0]["decided_by_name"], "Pemilik Tes")
        self.assertEqual(r.json()["samples"][0]["note"], "oke")
        r = await self.c.get("/admin/kotak/samples", params={"status": "semua"})
        self.assertEqual(len(r.json()["samples"]), 3)
        # Ruling M1d: `tolak` menghapus baris, jadi tab Ditolak selalu kosong (kunci counts tetap untuk bentuknya).
        r = await self.c.get("/admin/kotak/samples", params={"status": "ditolak"})
        self.assertEqual((r.status_code, r.json()["samples"]), (200, []))
        self.assertEqual((await self.c.get("/admin/kotak/samples", params={"status": "dicabut"})).status_code, 422)

    async def test_never_exposes_user_or_item_ids(self):
        a = await self.sample()
        b = await self.sample(status="disetujui")
        r = await self.c.get("/admin/kotak/samples", params={"status": "semua"})
        self.assert_no_owner_ids(r, a, b)
        for row in r.json()["samples"]:
            self.assertEqual(set(row), {
                "id", "doc_type", "rule_key", "app_label", "trigger", "lines", "user_name", "truth", "reading", "today",
                "status", "created_at", "decided_at", "decided_by_name", "note"})

    async def test_lines_flag_periksa_and_reading_is_the_current_reader(self):
        lines = [*LINES, "Ref …5678 …1234"]
        s = await self.sample(lines=lines, rule_key="gopay", truth={**TRUTH, "total": 125000})
        row = (await self.c.get("/admin/kotak/samples")).json()["samples"][0]
        self.assertEqual([x["text"] for x in row["lines"]], lines)
        self.assertEqual([x["periksa"] for x in row["lines"]], [False] * len(LINES) + [True])
        # Pembaca sekarang pada baris sampel, tanpa aturan (pola `kotak_corpus.sample_context`): sama dengan `eval`.
        entry = {"lines": lines, "today": "2026-10-27", "user_name": "ANDI PRATAMA"}
        self.assertEqual(row["reading"], kotak_corpus.expect_from(await kotak_corpus._read(entry)))
        self.assertEqual(row["reading"], READ)
        self.assertEqual(row["truth"]["total"], 125000)
        self.assertEqual((row["app_label"], row["rule_key"], row["trigger"], row["today"], row["user_name"]),
                         ("GoPay", "gopay", "nominal", "2026-10-27", "ANDI PRATAMA"))
        self.assertEqual(str(s.id), row["id"])

    async def test_app_label_from_key_or_answer(self):
        await self.sample(rule_key=None, truth={**TRUTH, "app": "dana"}, created_at=T0)
        await self.sample(rule_key="logo:newpay", truth=TRUTH, created_at=T0 + timedelta(minutes=1))
        await self.sample(rule_key=None, truth=None, created_at=T0 + timedelta(minutes=2))
        rows = (await self.c.get("/admin/kotak/samples")).json()["samples"]
        self.assertEqual([r["app_label"] for r in rows], ["DANA", 'Logo "NEWPAY"', None])


class ApproveTests(SamplesBase):
    async def test_approve_remasks_and_refuses_numbers(self):        # Review Focus 2
        s = await self.sample()
        edited = [*LINES, "Ke 1234567890", "1234 5678 9012", "Total Rp 1.234.567", "Rp 1.234.567.890",
                  "26/10/2026 10:11:12 123.456", "NMID ID1024358806544"]
        r = await self.approve(s.id, lines=edited)
        self.assertEqual(r.status_code, 200, r.text)
        stored = (await self.get(s.id)).lines
        # NMID publik di baris berlabel NMID dibiarkan `mask_line` dan tidak dihitung `\d{6,}` (sama dengan penangkapan).
        self.assertEqual(stored[-6:], ["Ke …7890", "…9012", "Total Rp 1.234.567", "Rp 1.234.567.890",
                                       "26/10/2026 10:11:12 123.456", "NMID ID1024358806544"])
        self.assertEqual([x["text"] for x in r.json()["lines"]][-6:], stored[-6:])
        self.assertNotIn("1234567890", json.dumps(stored))
        refused = {
            "NMID ID1024358806544 123.456.789.012": "Masih ada nomor rekening di baris 2",   # di samping NMID tetap dihitung
            "NMID ID1024358806544 Total Rp 1500000": "Masih ada nomor panjang di baris 2",   # hanya rentang NMID yang bebas
            "Total Rp 1500000": "Masih ada nomor panjang di baris 2",
            "Email andi.contoh@contoh.id": "Masih ada alamat email di baris 2",
            "Rek 1.234.567.890": "Masih ada nomor rekening di baris 2",
            "Ref 1234/5678/9012": "Masih ada nomor panjang di baris 2",     # review akhir A16 temuan 1: >= 10 digit
        }
        for line, message in refused.items():
            with self.subTest(line):
                other = await self.sample()
                r = await self.approve(other.id, lines=["Transfer Berhasil", line])
                self.assertEqual((r.status_code, r.json()["detail"]), (422, message))
                after = await self.get(other.id)
                self.assertEqual((after.status, after.lines), ("menunggu", LINES))   # tidak ada yang berubah

    async def test_approve_sets_decision_and_commits(self):
        s = await self.sample()
        r = await self.approve(s.id, user_name="  siti aminah ", note="  nama penerima diganti  ",
                               from_status="menunggu")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["status"], body["user_name"], body["note"], body["decided_by_name"]),
                         ("disetujui", "siti aminah", "nama penerima diganti", "Pemilik Tes"))
        self.assert_no_owner_ids(r, s)
        row = await self.get(s.id)   # sesi baru: route meng-commit
        self.assertEqual((row.status, row.decided_by, row.user_name), ("disetujui", self.admin.id, "siti aminah"))
        self.assertIsNotNone(row.decided_at)

    async def test_user_name_must_be_a_pseudonym(self):              # review M1d temuan 3: masuk entri korpus publik
        s = await self.sample()
        for name in ("Rina Wulandari", "ANDI WIJAYA", "Dewi"):
            with self.subTest(name):
                r = await self.approve(s.id, user_name=name)
                self.assertEqual((r.status_code, r.json()["detail"]), (422, "Nama user harus nama samaran"))
        self.assertEqual((await self.get(s.id)).status, "menunggu")
        r = await self.approve(s.id, user_name="Budi Pratama")          # kata-kata daftar samaran, huruf bebas
        self.assertEqual((r.status_code, r.json()["user_name"]), (200, "Budi Pratama"))

    async def test_user_name_kept_when_omitted_and_cleared_when_null(self):
        a = await self.sample()
        self.assertEqual((await self.approve(a.id)).json()["user_name"], "ANDI PRATAMA")
        b = await self.sample()
        self.assertIsNone((await self.approve(b.id, user_name=None)).json()["user_name"])
        c = await self.sample()
        self.assertIsNone((await self.approve(c.id, user_name="   ")).json()["user_name"])

    async def test_transitions_and_missing(self):
        s = await self.sample()
        self.assertEqual((await self.approve(s.id)).status_code, 200)
        r = await self.approve(s.id)
        self.assertEqual(r.status_code, 409)
        r = await self.approve(uuid.uuid4())
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "Sampel tidak ditemukan"))
        # Ruling M1d: sampel `ditolak` tidak pernah ada, jadi `from_status` hanya `menunggu`.
        other = await self.sample()
        self.assertEqual((await self.approve(other.id, from_status="ditolak")).status_code, 422)
        self.assertEqual((await self.get(other.id)).status, "menunggu")

    async def test_body_limits(self):
        s = await self.sample()
        bad = [
            {"lines": []},
            {"lines": ["x"] * (K.SAMPLE_MAX_LINES + 1)},
            {"lines": ["x" * (K.SAMPLE_LINE_MAX + 1)]},
            {"lines": ["Transfer\x00Berhasil"]},
            {"lines": ["Transfer\nBerhasil"]},
            {"lines": LINES, "user_name": "A" * 61},
            {"lines": LINES, "user_name": "ANDI​PRATAMA"},
            {"lines": LINES, "note": "n" * 201},
            {"lines": LINES, "note": "catatan‮"},
            {"lines": LINES, "status": "disetujui"},
            {"lines": LINES, "user_id": str(self.user.id)},
        ]
        for body in bad:
            with self.subTest(body=str(body)[:60]):
                r = await self.c.post(f"/admin/kotak/samples/{s.id}/setujui", json=body)
                self.assertEqual(r.status_code, 422)
        self.assertEqual((await self.get(s.id)).status, "menunggu")
        ok = await self.approve(s.id, lines=["x"] * K.SAMPLE_MAX_LINES)
        self.assertEqual(ok.status_code, 200, ok.text)


class RejectDeleteTests(SamplesBase):
    async def test_tolak_deletes_the_row(self):
        s = await self.sample()
        r = await self.c.post(f"/admin/kotak/samples/{s.id}/tolak", json={"note": "bukan bukti", "from_status": "menunggu"})
        self.assertEqual((r.status_code, r.json()), (200, {"deleted": True}))
        self.assertIsNone(await self.get(s.id))
        r = await self.c.post(f"/admin/kotak/samples/{s.id}/tolak")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "Sampel tidak ditemukan"))

    async def test_tolak_only_from_menunggu(self):
        s = await self.sample(status="disetujui")
        self.assertEqual((await self.c.post(f"/admin/kotak/samples/{s.id}/tolak")).status_code, 409)
        other = await self.sample()
        r = await self.c.post(f"/admin/kotak/samples/{other.id}/tolak", json={"from_status": "ditolak"})
        self.assertEqual(r.status_code, 422)
        r = await self.c.post(f"/admin/kotak/samples/{other.id}/tolak", json={"lines": ["x"]})
        self.assertEqual(r.status_code, 422)
        self.assertIsNotNone(await self.get(s.id))
        self.assertIsNotNone(await self.get(other.id))

    async def test_delete_after_copy(self):
        s = await self.sample(status="disetujui")
        r = await self.c.delete(f"/admin/kotak/samples/{s.id}")
        self.assertEqual((r.status_code, r.content), (204, b""))
        self.assertIsNone(await self.get(s.id))
        r = await self.c.delete(f"/admin/kotak/samples/{s.id}")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "Sampel tidak ditemukan"))


class CorpusEntryTests(SamplesBase):
    async def test_korpus_only_for_approved(self):
        s = await self.sample()
        self.assertEqual((await self.c.get(f"/admin/kotak/samples/{s.id}/korpus")).status_code, 409)
        r = await self.c.get(f"/admin/kotak/samples/{uuid.uuid4()}/korpus")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "Sampel tidak ditemukan"))

    async def test_entry_passes_load_corpus_and_reads_the_approved_lines(self):
        s = await self.sample()
        edited = [*LINES[:-1], "No. Ref 2026102612345678"]          # disamarkan lagi saat disetujui
        self.assertEqual((await self.approve(s.id, lines=edited, user_name="siti aminah")).status_code, 200)
        r = await self.c.get(f"/admin/kotak/samples/{s.id}/korpus")
        self.assertEqual(r.status_code, 200, r.text)
        self.assert_no_owner_ids(r, s)
        body = r.json()
        entry = body["entry"]
        self.assertEqual(list(entry), ["id", "real", "reviewed", "today", "user_name", "lines", "expect"])
        self.assertEqual(entry["id"], f"donasi-transfer-{s.id.hex[:8]}")
        self.assertEqual((entry["real"], entry["reviewed"], entry["today"], entry["user_name"]),
                         (True, True, "2026-10-27", "siti aminah"))
        self.assertEqual(entry["lines"][-1], "No. Ref …5678")
        self.assertEqual(entry["expect"], kotak_corpus.expect_from(await kotak_corpus._read(entry)))
        self.assertEqual((body["truth"], body["gated_diff"]), (TRUTH, []))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corpus.json"
            kotak_corpus.write_corpus(path, [entry])
            self.assertEqual(kotak_corpus.load_corpus(path), [entry])
            result = await asyncio.to_thread(kotak_corpus.evaluate, [entry])   # evaluate memakai asyncio.run
            self.assertEqual(result["failures"], [])

    async def test_entry_without_user_name_omits_the_key(self):
        s = await self.sample(user_name=None)
        await self.approve(s.id)
        entry = (await self.c.get(f"/admin/kotak/samples/{s.id}/korpus")).json()["entry"]
        self.assertNotIn("user_name", entry)
        self.assertIsNone(kotak_corpus._sample_problem(entry))

    async def test_expect_uses_the_user_correction_and_lists_differences(self):   # review M1d temuan 2
        s = await self.sample(truth={"total": 125000, "date": "2026-10-25", "flow": "top_up", "app": "dana"})
        await self.approve(s.id)
        body = (await self.c.get(f"/admin/kotak/samples/{s.id}/korpus")).json()
        self.assertEqual(body["gated_diff"], ["total", "date", "flow", "app"])
        self.assertEqual(body["entry"]["expect"], {**READ, "issuer": "dana", "total": 125000,
                                                   "paid_at": "2026-10-25T09:30:00+07:00", "flow": "top_up"})
        self.assertEqual(body["entry"]["reviewed"], True)        # pemilik menyetujui; CLI yang menahan (K17)
        # Aplikasi `baru` dan nilai null bukan koreksi.
        other = await self.sample(truth={"total": None, "date": None, "flow": None, "app": "baru"})
        await self.approve(other.id)
        body = (await self.c.get(f"/admin/kotak/samples/{other.id}/korpus")).json()
        self.assertEqual((body["gated_diff"], body["entry"]["expect"]), ([], READ))

    async def test_corpus_entry_has_only_corpus_keys(self):        # review M1d temuan 5
        from app.services.kotak_struk import donasi
        s = await self.get((await self.sample()).id)
        self.assertEqual(list(donasi.corpus_entry(s, dict(READ))),
                         ["id", "real", "reviewed", "today", "user_name", "lines", "expect"])
        s.user_name = None
        self.assertEqual(set(donasi.corpus_entry(s, dict(READ))), {"id", "real", "reviewed", "today", "lines", "expect"})


class NonAdminTests(SamplesBase):
    async def test_every_route_refuses_non_admin(self):
        s = await self.sample()
        self.current = self.user
        calls = [
            self.c.get("/admin/kotak/samples"),
            self.c.post(f"/admin/kotak/samples/{s.id}/setujui", json={"lines": LINES}),
            self.c.post(f"/admin/kotak/samples/{s.id}/tolak"),
            self.c.delete(f"/admin/kotak/samples/{s.id}"),
            self.c.get(f"/admin/kotak/samples/{s.id}/korpus"),
        ]
        for call in calls:
            self.assertEqual((await call).status_code, 403)
        row = await self.get(s.id)
        self.assertEqual((row.status, row.lines), ("menunggu", LINES))


if __name__ == "__main__":
    unittest.main()
