"""Tahap 2 M3a (plan 2026-11-04): token arah uang di kerangka, alasan "Bukan pengeluaran", suara `arah`.

Spec 2026-11-01 §2 baris `arah`, §4.2 butir 4; pre-flight A16 §4, K9, K11 (server), K14. Token hanya kata kosakata
(judul tanpa kata status, atau kata terdepan penerima: penyedia + kata top-up), tidak pernah nama, nomor, atau nominal.
Semua nama dan nomor di sini rekaan atau sampel korpus yang sudah disamarkan."""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import json
import unittest
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.core.deps import get_current_user
from app.models.models import ProofRule, ProofRuleVote, ReceiptScan
from app.services.kotak_struk import belajar, kerangka, merchants, record
from app.services.kotak_struk.belajar import KIND_ARAH, Vote, learn_from_skip, votes_for_skip
from app.services.kotak_struk.config import ARAH_FLOWS, KEY_MAX, ST_DILEWATI
from app.services.kotak_struk.document import Counterparty, DokumenBayar
from app.services.kotak_struk.extract import TextDoc
from app.services.kotak_struk.kerangka import (
    ARAH_GENERIC, ARAH_PARTY_WORDS, TOP_UP_WORDS, arah_tokens, build_layout,
)
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import ParseContext, Secrets
from app.services.kotak_struk.registry import read_document

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
CORPUS = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "corpus.json").read_text())["samples"]
BY_ID = {s["id"]: s for s in CORPUS}
TODAY = date(2026, 11, 1)


def corpus_sample(sample_id: str) -> dict:
    return BY_ID[sample_id]


def read_flag_on(sample: dict):
    """Hasil baca sampel korpus dengan saklar bukti menyala, tanpa aturan (`parsed`: doc + secrets)."""
    text = TextDoc(lines=list(sample["lines"]), kind="image")
    return asyncio.run(read_document(text, ParseContext(today=TODAY), proofs_enabled=True)).parsed


def transfer_doc(*, flow="keluar", name=None, issuer="gopay", doc_type="transfer"):
    return DokumenBayar(doc_type=doc_type, issuer=issuer, flow=flow, counterparty=Counterparty(name=name))


def layout(key="shopeepay", arah=("ke:gopay topu",)):
    lay = {"v": 1, "key": key, "lines": []}
    if arah is not None:
        lay["arah"] = list(arah)
    return lay


def document(flow="keluar", doc_type="transfer"):
    return {"doc_type": doc_type, "flow": flow, "counterparty": {"name": "GOPAY TOPU-SXXXX AXXXXXXX"}}


# ── token (murni) ───────────────────────────────────────────────────────────

class ArahTokenTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(merchants, "_warned_no_key", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_shopeepay_gopay_topu_gives_ke_token(self):
        sample = corpus_sample("real-shopeepay-topup-01")
        doc = read_flag_on(sample).doc
        self.assertEqual(doc.flow, "keluar")   # tanpa aturan: dibaca keluar (gagal korpus yang dikenal)
        tokens = arah_tokens(pc.clean_lines(sample["lines"]), doc)
        self.assertIn("ke:gopay topu", tokens)
        self.assertEqual(tokens, ["ke:gopay topu"])   # tanpa entri judul ("Berhasil" saja bukan judul status)

    def test_person_with_provider_prefix_gives_no_token(self):
        sample = corpus_sample("real-gopay-topup-01")
        doc = read_flag_on(sample).doc
        self.assertEqual((doc.flow, doc.counterparty.name), ("keluar", "Shopeepaysitxx Amixxxxx"))
        self.assertEqual(arah_tokens(pc.clean_lines(sample["lines"]), doc), [])
        lines = ["GoPay", "Transfer Berhasil", "Rp20.000"]
        for name in ("Shopeepaysitxx Amixxxxx", "GOPAY SITI AMINAH", "Gopay Topup",       # satu kata top-up saja: ya
                     "DANA BUDI SANTOSO", "TOPUP", "GOPAY", "Budi Topup Gopay", "OVO 0812 TOPUP", "Top Up Andi"):
            with self.subTest(name):
                tokens = [t for t in arah_tokens(lines, transfer_doc(name=name)) if t.startswith("ke:")]
                self.assertEqual(tokens, ["ke:gopay topup"] if name == "Gopay Topup" else [])

    def test_ke_token_vocabulary_only_leading_words(self):
        lines = ["GoPay", "Transfer Berhasil", "Rp20.000"]
        cases = {
            "GOPAY TOPU-SXXXX Axxxxxxx": ["ke:gopay topu"],
            "OVO Top Up 0812xxxx": ["ke:ovo top up"],
            "Topup DANA Budi": ["ke:topup dana"],
            "ISI SALDO GOPAY RINA": ["ke:isi saldo gopay"],           # paling banyak 3 kata
            "Bank Topup Ewallet": ["ke:bank topup"],
            "Saldo Topup": [],                                         # tanpa kata penyedia
            None: [],
        }
        for name, want in cases.items():
            with self.subTest(name):
                tokens = [t for t in arah_tokens(lines, transfer_doc(name=name)) if t.startswith("ke:")]
                self.assertEqual(tokens, want)
                for t in tokens:
                    words = t[3:].split()
                    self.assertTrue(2 <= len(words) <= 3 and set(words) <= ARAH_PARTY_WORDS, t)
                    self.assertTrue(set(words) & TOP_UP_WORDS and set(words) - TOP_UP_WORDS, t)

    def test_status_only_title_gives_no_judul_token(self):
        for title in ("Transfer Berhasil", "Pembayaran Berhasil", "Transaksi Sukses", "Kirim Uang Berhasil",
                      "Payment Successful", "Transfer Gagal", "Pembayaran QRIS Berhasil"):
            with self.subTest(title):
                self.assertEqual(arah_tokens(["GoPay", title, "Rp20.000"], transfer_doc()), [])

    def test_judul_token_from_title_words_without_status(self):
        cases = {
            "Top Up Berhasil": "judul:top up",
            "Top Up GoPay Berhasil": "judul:top up gopay",
            "Isi Saldo Sukses": "judul:isi saldo",
            "Dana Masuk": "judul:dana masuk",
            "Transfer ke Rekening Anda Berhasil": "judul:transfer ke rekening anda",
        }
        for title, want in cases.items():
            with self.subTest(title):
                self.assertEqual(arah_tokens(["BCA", title, "Rp20.000"], transfer_doc(issuer="bca_mobile")), [want])

    def test_judul_token_keeps_order_drops_names_and_digits(self):
        # Kata nama pihak lawan tidak pernah masuk judul, juga bila kata itu kosakata ("Dana").
        tokens = arah_tokens(["GoPay", "Top Up Dana Berhasil", "Rp20.000"], transfer_doc(name="DANA PRATAMA"))
        self.assertEqual(tokens, ["judul:top up"])
        # Kata di luar kosakata (nama, kode) dibuang; digit tidak pernah.
        tokens = arah_tokens(["GoPay", "Top Up Wahyu 0812 Berhasil", "Rp20.000"], transfer_doc())
        self.assertEqual(tokens, ["judul:top up"])
        # Paling banyak 6 kata, urutan asli.
        tokens = arah_tokens(["GoPay", "Top Up Saldo GoPay Dana Masuk Ke Rekening Anda Berhasil", "Rp20.000"],
                             transfer_doc())
        self.assertEqual(len(tokens), 1)
        self.assertTrue(tokens[0].startswith("judul:top up saldo"))
        self.assertLessEqual(len(tokens[0][len("judul:"):].split()), 6)

    def test_sint_topup_gives_judul_token(self):
        sample = corpus_sample("sint-topup")
        doc = read_flag_on(sample).doc
        self.assertEqual(doc.flow, "top_up")
        self.assertEqual(arah_tokens(pc.clean_lines(sample["lines"]), doc), ["judul:top up"])

    def test_vocab_constants(self):
        self.assertEqual(TOP_UP_WORDS, frozenset({"top", "up", "topup", "topu", "isi", "saldo", "deposit", "reload"}))
        self.assertLessEqual(TOP_UP_WORDS, ARAH_PARTY_WORDS)
        self.assertLessEqual({"gopay", "ovo", "dana", "shopeepay", "bca", "mandiri", "bank"}, ARAH_PARTY_WORDS)
        self.assertLessEqual({"transfer", "pembayaran", "kirim", "uang", "ke", "qris", "rekening"}, ARAH_GENERIC)
        self.assertEqual(ARAH_FLOWS, ("top_up", "masuk", "antar_rekening_sendiri"))

    def test_layout_carries_arah_tokens(self):
        sample = corpus_sample("real-shopeepay-topup-01")
        parsed = read_flag_on(sample)
        lay = build_layout(sample["lines"], parsed.doc, parsed.secrets, user_name=None)
        self.assertEqual((lay["key"], lay["arah"]), ("shopeepay", ["ke:gopay topu"]))
        # Tanpa token: daftar kosong (kunci tetap ada, versi 1).
        lay = build_layout(["GoPay", "Transfer Berhasil", "Rp20.000"], transfer_doc(name="BUDI SANTOSO"), Secrets(),
                           user_name=None)
        self.assertEqual((lay["v"], lay["arah"]), (1, []))


# ── suara (murni) ───────────────────────────────────────────────────────────

class VotesForSkipTests(unittest.TestCase):
    def test_one_vote_per_token(self):
        lay = layout(arah=["judul:top up", "ke:gopay topu"])
        self.assertEqual(votes_for_skip(lay, document(), "top_up"),
                         [Vote(KIND_ARAH, "shopeepay|judul:top up", "top_up"),
                          Vote(KIND_ARAH, "shopeepay|ke:gopay topu", "top_up")])

    def test_agreeing_or_unknown_alasan_gives_no_vote(self):   # K14
        lay = layout()
        self.assertEqual(votes_for_skip(lay, document(flow="top_up"), "top_up"), [])
        self.assertEqual(votes_for_skip(lay, document(flow="masuk"), "masuk"), [])
        for alasan in (None, "", "keluar", "tidak_diketahui", "lainnya", "TOP_UP"):
            with self.subTest(alasan):
                self.assertEqual(votes_for_skip(lay, document(), alasan), [])
        self.assertEqual(len(votes_for_skip(lay, document(flow="top_up"), "masuk")), 1)   # beda dari baca: suara

    def test_needs_profile_key_proof_type_and_tokens(self):
        self.assertEqual(votes_for_skip(layout(key="logo:newpay"), document(), "top_up"), [])
        self.assertEqual(votes_for_skip(layout(key="tokoku"), document(), "top_up"), [])
        self.assertEqual(votes_for_skip(layout(arah=None), document(), "top_up"), [])   # kerangka lama
        self.assertEqual(votes_for_skip(layout(arah=[]), document(), "top_up"), [])
        for doc_type in ("tidak_dikenali", "struk_belanja", None):
            with self.subTest(doc_type):
                self.assertEqual(votes_for_skip(layout(), document(doc_type=doc_type), "top_up"), [])
        for bad in (None, "x", [], {"key": None}, {"key": "shopeepay", "arah": "ke:gopay topu"}):
            with self.subTest(bad=bad):
                self.assertEqual(votes_for_skip(bad, document(), "top_up"), [])
        self.assertEqual(votes_for_skip(layout(), None, "top_up"), [])

    def test_logo_key_only_when_approved(self):   # K8 (dalam praktik kunci logo hanya untuk tidak_dikenali)
        lay = layout(key="logo:newpay")
        self.assertEqual(votes_for_skip(lay, document(), "top_up"), [])
        self.assertEqual(votes_for_skip(lay, document(), "top_up", approved_logo=frozenset({"logo:newpay"})),
                         [Vote(KIND_ARAH, "logo:newpay|ke:gopay topu", "top_up")])

    def test_only_vocabulary_tokens_vote(self):
        bad = ["ke:budi santoso", "ke:gopay budi", "ke:gopay", "ke:gopay topu topup ovo", "ke:gopay topup budi",
               "ke:budi gopay topup", "ke:gopay topu sxxxx", "judul:wahyu", "judul:top up wahyu",
               "judul:transfer", "judul:top up 1234", "judul:top up berhasil", "kirim:gopay topu", 7, None,
               "judul:", "ke:", "judul:top  up", "judul:Top Up"]
        self.assertEqual(votes_for_skip(layout(arah=bad), document(), "top_up"), [])
        for token in bad:
            with self.subTest(token):
                self.assertFalse(kerangka.arah_token_ok(token))
        for token in ("ke:gopay topu", "ke:ovo top up", "judul:top up", "judul:dana masuk"):
            self.assertTrue(kerangka.arah_token_ok(token), token)

    def test_at_most_one_judul_and_one_ke(self):
        lay = layout(arah=["judul:top up", "judul:isi saldo", "ke:gopay topu", "ke:ovo topup"])
        self.assertEqual([v.rule_key for v in votes_for_skip(lay, document(), "top_up")],
                         ["shopeepay|judul:top up", "shopeepay|ke:gopay topu"])

    def test_key_longer_than_key_max_gives_no_vote(self):
        token = "judul:pengiriman saldo deposit withdrawal transaction"
        self.assertTrue(kerangka.arah_token_ok(token))
        self.assertGreater(len(f"bca_mobile|{token}"), KEY_MAX)
        self.assertEqual(votes_for_skip(layout(key="bca_mobile", arah=[token]), document(), "masuk"), [])
        self.assertEqual(len(votes_for_skip(layout(key="ovo", arah=[token]), document(), "masuk")), 1)


# ── database dan API ────────────────────────────────────────────────────────

if HAS_AIOSQLITE:
    from app.tests.test_kotak_api import ApiBase
    from app.tests.test_kotak_belajar import postgres_abort
else:   # pragma: no cover
    ApiBase = unittest.IsolatedAsyncioTestCase


TOPUP = corpus_sample("real-shopeepay-topup-01")["lines"]
SINT_TOPUP = corpus_sample("sint-topup")["lines"]


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class SkipAlasanTests(ApiBase):
    async def skip(self, item_id, **body):
        return await self.c.post(f"/kotak-struk/{item_id}/lewati", json=body)

    async def votes(self):
        async with self.Session() as db:
            return [(v.kind, v.rule_key, v.value, v.user_id) for v in
                    (await db.execute(select(ProofRuleVote).order_by(ProofRuleVote.created_at))).scalars().all()]

    async def rules(self):
        async with self.Session() as db:
            return (await db.execute(select(ProofRule))).scalars().all()

    async def test_skip_with_alasan_votes_arah_once(self):
        item = await self.ready(TOPUP)
        self.assertEqual((await self.get(item.id)).layout["arah"], ["ke:gopay topu"])
        r = await self.skip(item.id, reason="bukan_pengeluaran", alasan="top_up")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "dilewati"))
        row = await self.get(item.id)
        self.assertEqual((row.channel_meta["skip_reason"], row.channel_meta["skip_alasan"]),
                         ("bukan_pengeluaran", "top_up"))
        self.assertEqual(await self.votes(), [("arah", "shopeepay|ke:gopay topu", "top_up", self.a.id)])
        self.assertEqual(await self.rules(), [])   # satu user: suara saja
        # User yang sama, bukti kedua: tetap satu suara per user per aturan.
        again = await self.ready(TOPUP)
        self.assertEqual((await self.skip(again.id, reason="bukan_pengeluaran", alasan="top_up")).status_code, 200)
        self.assertEqual(len(await self.votes()), 1)
        # User kedua -> aturan menunggu.
        self.app.dependency_overrides[get_current_user] = lambda: self.b
        theirs = await self.ready(TOPUP, owner=self.b)
        self.assertEqual((await self.skip(theirs.id, reason="bukan_pengeluaran", alasan="top_up")).status_code, 200)
        [rule] = await self.rules()
        self.assertEqual((rule.kind, rule.rule_key, rule.value, rule.users, rule.status),
                         ("arah", "shopeepay|ke:gopay topu", "top_up", 2, "menunggu"))

    async def test_skip_without_alasan_or_other_reason_gives_no_vote(self):
        for body in ({"reason": "bukan_pengeluaran"}, {"reason": "bukan_pengeluaran", "alasan": None},
                     {"reason": "duplikat"}, {"reason": "batal"}):
            with self.subTest(body):
                item = await self.ready(TOPUP)
                r = await self.skip(item.id, **body)
                self.assertEqual(r.status_code, 200)
                self.assertNotIn("skip_alasan", (await self.get(item.id)).channel_meta)
        self.assertEqual(await self.votes(), [])

    async def test_agreeing_alasan_gives_no_vote(self):   # K14
        item = await self.ready(SINT_TOPUP)
        stored = await self.get(item.id)
        self.assertEqual((stored.document["flow"], stored.layout["arah"]), ("top_up", ["judul:top up"]))
        r = await self.skip(item.id, reason="bukan_pengeluaran", alasan="top_up")
        self.assertEqual((r.status_code, (await self.get(item.id)).channel_meta["skip_alasan"]), (200, "top_up"))
        self.assertEqual(await self.votes(), [])
        # Alasan lain dari bacaan: suara.
        other = await self.ready(SINT_TOPUP)
        self.assertEqual((await self.skip(other.id, reason="bukan_pengeluaran", alasan="masuk")).status_code, 200)
        self.assertEqual(await self.votes(), [("arah", "gopay|judul:top up", "masuk", self.a.id)])

    async def test_skip_votes_never_fail_the_skip(self):   # Review Focus 3
        item = await self.ready(TOPUP)
        with patch.object(belajar, "learn_from_skip", AsyncMock(side_effect=RuntimeError("rusak"))), \
                self.assertLogs("app.services.kotak_struk.record", "WARNING"):
            r = await self.skip(item.id, reason="bukan_pengeluaran", alasan="top_up")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "dilewati"))
        row = await self.get(item.id)
        self.assertEqual((row.status, row.channel_meta["skip_alasan"]), (ST_DILEWATI, "top_up"))
        # Galat database di dalam suara: savepoint dibatalkan, lewati tetap ter-commit.
        other = await self.ready(TOPUP)
        with self.assertLogs("app.services.kotak_struk.belajar", "WARNING"), \
                postgres_abort(self.engine, "INSERT INTO proof_rule_votes") as state:
            r = await self.skip(other.id, reason="bukan_pengeluaran", alasan="top_up")
        self.assertEqual(state["left"], 0)   # galatnya benar-benar terjadi
        self.assertEqual((r.status_code, r.json()["status"]), (200, "dilewati"))
        self.assertEqual((await self.get(other.id)).status, ST_DILEWATI)
        self.assertEqual(await self.votes(), [])
        # Satu-satunya efek suara: tidak ada transaksi, item tetap dilewati.
        async with self.Session() as db:
            self.assertEqual((await db.execute(select(ReceiptScan.transaction_ids)
                                               .where(ReceiptScan.id == other.id))).scalar_one(), None)

    async def test_skipin_alasan_validation(self):
        item = await self.ready(TOPUP)
        for body in ({"reason": "duplikat", "alasan": "top_up"}, {"reason": "batal", "alasan": "masuk"}):
            with self.subTest(body), patch.object(record, "skip_item", AsyncMock(return_value=True)) as skip:
                r = await self.skip(item.id, **body)
                self.assertEqual(r.status_code, 422)
                self.assertIn("Alasan hanya untuk Bukan pengeluaran", json.dumps(r.json()))
                skip.assert_not_called()   # ditolak `SkipIn`, sebelum layanan
        for body in ({"alasan": "top_up"}, {"reason": "bukan_pengeluaran", "alasan": "iseng"},
                     {"reason": "bukan_pengeluaran", "alasan": "keluar"}):
            with self.subTest(body):
                self.assertEqual((await self.skip(item.id, **body)).status_code, 422)
        self.assertEqual((await self.get(item.id)).status, "siap")
        self.assertEqual(await self.votes(), [])
        # Service: alasan dengan reason lain -> ValueError, tidak ada yang berubah.
        async with self.Session() as db:
            with self.assertRaises(ValueError):
                await record.skip_item(db, item.id, self.a.id, "duplikat", alasan="top_up")
            with self.assertRaises(ValueError):
                await record.skip_item(db, item.id, self.a.id, "bukan_pengeluaran", alasan="iseng")
        self.assertEqual((await self.get(item.id)).status, "siap")
        # Tanpa alasan = perilaku lama.
        r = await self.skip(item.id, reason="bukan_pengeluaran")
        self.assertEqual((r.status_code, (await self.get(item.id)).channel_meta), (200, {"skip_reason": "bukan_pengeluaran"}))

    async def test_skip_alasan_on_failed_item_is_stored_without_vote(self):
        item = await self.ready(TOPUP)
        await self.set(item.id, status="gagal", error="x")
        self.assertEqual((await self.skip(item.id, reason="bukan_pengeluaran", alasan="top_up")).status_code, 200)
        self.assertEqual((await self.get(item.id)).channel_meta["skip_alasan"], "top_up")


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class LearnFromSkipTests(ApiBase):
    async def test_learn_from_skip_counts_and_never_commits(self):
        item = SimpleNamespace(id=uuid.uuid4(), layout=layout(arah=["judul:top up", "ke:gopay topu"]),
                               doc_type="transfer", document=document(), household_id=self.hh.id)
        async with self.Session() as db:
            self.assertEqual(await learn_from_skip(db, item, "top_up", user_id=self.a.id), 2)
            await db.rollback()   # tidak meng-commit sendiri
        async with self.Session() as db:
            self.assertEqual((await db.execute(select(ProofRuleVote))).scalars().all(), [])
        async with self.Session() as db:
            self.assertEqual(await learn_from_skip(db, item, "top_up", user_id=self.a.id), 2)
            await db.commit()
            self.assertEqual(len((await db.execute(select(ProofRuleVote))).scalars().all()), 2)

    async def test_learn_from_skip_never_raises(self):
        with self.assertLogs("app.services.kotak_struk.belajar", "WARNING"):
            for item in (None, SimpleNamespace(), SimpleNamespace(id=1, layout="x", doc_type="transfer", document=None,
                                                                    household_id=None)):
                async with self.Session() as db:
                    self.assertEqual(await learn_from_skip(db, item, "top_up", user_id=self.a.id), 0)
        item = SimpleNamespace(id=uuid.uuid4(), layout=layout(), doc_type="transfer", document=document(),
                               household_id=None)
        async with self.Session() as db:
            with patch.object(belajar, "record_votes", AsyncMock(side_effect=RuntimeError("x"))), \
                    self.assertLogs("app.services.kotak_struk.belajar", "WARNING"):
                self.assertEqual(await learn_from_skip(db, item, "top_up", user_id=self.a.id), 0)

    async def test_admin_lists_arah_kind(self):
        """Admin `/admin/kotak/rules` dan `/votes` tidak menyaring jenis: `arah` ikut tampil (penyamaran K15 di M3d)."""
        import httpx
        from fastapi import FastAPI
        from app.api.routes import admin_kotak
        from app.core.database import get_db
        from app.models.models import User
        for user in (self.a, self.b):
            item = SimpleNamespace(id=uuid.uuid4(), layout=layout(), doc_type="transfer", document=document(),
                                   household_id=self.hh.id)
            async with self.Session() as db:
                await learn_from_skip(db, item, "top_up", user_id=user.id)
                await db.commit()
        async with self.Session() as db:
            admin = User(name="Pemilik", is_admin=True)
            db.add(admin)
            await db.commit()
        app = FastAPI()
        app.include_router(admin_kotak.router, prefix="/admin/kotak")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: admin
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            rules = await c.get("/admin/kotak/rules")
            votes = await c.get("/admin/kotak/votes")
        self.assertEqual((rules.status_code, votes.status_code), (200, 200))
        self.assertIn("arah", json.dumps(rules.json()))
        self.assertIn("arah", json.dumps(votes.json()))
        self.assertIn(KIND_ARAH, belajar.ALL_KINDS)


if __name__ == "__main__":
    unittest.main()
