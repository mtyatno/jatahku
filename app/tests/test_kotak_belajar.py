"""Belajar lintas user Kotak Struk (spec 2026-11-01 §3b, §4.1-4.3, §8, §12.1; pre-flight K3, K5, K9, G3, G5, G7):
suara koreksi dari kerangka tata letak, aturan `menunggu` mulai 2 user berbeda, rumah tangga dihitung, transisi status,
dan lupakan user (hapus akun, gabung akun). SQLite in-memory.
Run: python -m unittest app.tests.test_kotak_belajar -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import contextlib
import importlib.util
import json
import re
import unittest
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

from app.core.database import Base
from app.models.models import Household, HouseholdMember, HouseholdRole, ProofRule, ProofRuleVote, User
from app.services.kotak_struk import belajar, maintenance, merchants
from app.services.kotak_struk.belajar import (
    Final, Vote, forget_user, learn_from_correction, next_status, record_votes, recount, votes_for,
)
from app.services.kotak_struk.config import RULE_MIN_USERS
from app.services.kotak_struk.extract import KIND_IMAGE, TextDoc
from app.services.kotak_struk.kerangka import LABEL_WORDS, build_layout
from app.services.kotak_struk.merchants import hmac_hex, normalize_name
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import ParseContext
from app.services.kotak_struk.readers.profiles import PROFILES, detect_issuer
from app.services.kotak_struk.registry import read_document

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
SWEEP = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "sweep_lines.json").read_text(encoding="utf-8"))
TODAY = date(2026, 11, 1)
DOC_DAY = date(2026, 10, 26)
PROFILE_KEYS = {p.key for p in PROFILES}
BELAJAR_LOG = "app.services.kotak_struk.belajar"


def h(name: str) -> str:
    return hmac_hex(normalize_name(name))


def layout(*lines, key="jago"):
    return {"v": 1, "key": key, "lines": list(lines)}


def nominal(i, label, amount):
    return {"i": i, "label": label, "kind": "nominal", "amount": amount}


def tanggal(i, label, day: date):
    return {"i": i, "label": label, "kind": "tanggal", "date": day.isoformat()}


def nama(i, label, name):
    return {"i": i, "label": label, "kind": "nama", "h": h(name)}


def doc(total=None, name=None, paid_at="2026-10-26T08:12:33+07:00"):
    return {"amounts": {"total": total}, "counterparty": {"name": name}, "paid_at": paid_at}


def final(amount=None, txn_date=None, description=None, today=TODAY):
    return Final(amount, txn_date, description, today)


@contextlib.contextmanager
def postgres_abort(engine, prefix: str):
    """Galat database sekali pada pernyataan SQL pertama berawalan `prefix`, lalu seperti Postgres (SQLite tidak):
    transaksi menjadi "aborted" sampai ROLLBACK TO SAVEPOINT; pernyataan lain dan COMMIT di antaranya gagal. Membuktikan
    bahwa galat yang ditelan benar-benar dibatalkan lewat savepoint, bukan hanya ditangkap. `state["left"] == 0`
    berarti galatnya terjadi."""
    state = {"left": 1, "aborted": False}

    def before(conn, cursor, statement, *_a):
        text = statement.lstrip()
        if text.startswith("ROLLBACK TO SAVEPOINT"):
            state["aborted"] = False
        elif state["aborted"]:
            raise OperationalError(statement, None, Exception("current transaction is aborted"))
        elif state["left"] and text.startswith(prefix):
            state["left"] -= 1
            state["aborted"] = True
            raise OperationalError(statement, None, Exception("disk I/O error"))

    def commit(conn):
        if state["aborted"]:
            state["aborted"] = False
            raise OperationalError("COMMIT", None, Exception("current transaction is aborted, commands ignored"))

    def rollback(conn):
        state["aborted"] = False

    hooks = (("before_cursor_execute", before), ("commit", commit), ("rollback", rollback))
    for name, fn in hooks:
        event.listen(engine.sync_engine, name, fn)
    try:
        yield state
    finally:
        for name, fn in hooks:
            event.remove(engine.sync_engine, name, fn)


class _Quiet(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(merchants, "_warned_no_key", True)
        patcher.start()
        self.addCleanup(patcher.stop)


# ── suara (murni) ───────────────────────────────────────────────────────────

class VotesForTests(_Quiet):
    def test_amount_correction_votes_label_of_matching_line(self):
        lay = layout(nominal(3, "nominal", 10000), nominal(5, "total bayar", 12500))
        votes = votes_for(lay, {"amounts": {"total": 10000}}, None, final(12500, None, "Transfer ke X"))
        self.assertEqual(votes, [Vote("label_total", "jago", "total bayar")])

    def test_amount_equal_to_the_read_total_gives_no_vote(self):
        lay = layout(nominal(3, "nominal", 10000), nominal(5, "total bayar", 12500))
        self.assertEqual(votes_for(lay, doc(total=12500), None, final(12500)), [])

    def test_unread_total_still_votes(self):
        lay = layout(nominal(5, "total bayar", 12500))
        self.assertEqual(votes_for(lay, None, None, final(12500)), [Vote("label_total", "jago", "total bayar")])
        self.assertEqual(votes_for(lay, doc(total=None), None, final(12500)),
                         [Vote("label_total", "jago", "total bayar")])

    def test_typed_amount_not_printed_gives_no_vote(self):
        lay = layout(nominal(3, "nominal", 10000), nominal(5, "total bayar", 12500))
        self.assertEqual(votes_for(lay, doc(total=10000), None, final(9999)), [])
        self.assertEqual(votes_for(lay, doc(total=10000), None, final(None)), [])

    def test_unlabelled_or_masked_label_never_votes(self):
        # Kerangka memuat banyak entri tanpa label (derau) dan label bertanda `#` (digit tersamar): bukan suara.
        lay = layout(nominal(3, None, 12500), nominal(4, "biaya #", 12500), nominal(5, "#", 12500))
        self.assertEqual(votes_for(lay, doc(total=10000), None, final(12500)), [])
        lay = layout(nominal(3, None, 12500), nominal(5, "jumlah", 12500))   # derau tidak membuatnya ambigu
        self.assertEqual(votes_for(lay, doc(total=10000), None, final(12500)), [Vote("label_total", "jago", "jumlah")])

    def test_two_labels_same_amount_prefers_total_else_none(self):
        both = layout(nominal(3, "nominal", 12500), nominal(5, "total bayar", 12500))
        self.assertEqual(votes_for(both, doc(total=10000), None, final(12500)),
                         [Vote("label_total", "jago", "total bayar")])
        none_total = layout(nominal(3, "nominal", 12500), nominal(5, "jumlah", 12500))
        self.assertEqual(votes_for(none_total, doc(total=10000), None, final(12500)), [])
        two_totals = layout(nominal(3, "total", 12500), nominal(5, "total bayar", 12500))
        self.assertEqual(votes_for(two_totals, doc(total=10000), None, final(12500)), [])
        # Label yang sama di dua baris tetap satu label.
        same = layout(nominal(3, "jumlah", 12500), nominal(9, "jumlah", 12500))
        self.assertEqual(votes_for(same, doc(total=10000), None, final(12500)), [Vote("label_total", "jago", "jumlah")])
        # "subtotal" bukan kata "total".
        word = layout(nominal(3, "nominal", 12500), nominal(5, "subtotal", 12500))
        self.assertEqual(votes_for(word, doc(total=10000), None, final(12500)), [])

    def test_name_vote_only_when_printed_and_changed(self):
        lay = layout(nama(3, "ditransfer ke", "BUDI SANTOSO"), nama(6, "nama penerima", "SITI RAHAYU"),
                     nama(8, None, "RINA"), key="gopay")
        read = doc(name="BUDI SANTOSO")
        self.assertEqual(votes_for(lay, read, None, final(description="Transfer ke Siti Rahayu")),
                         [Vote("label_pihak", "gopay", "nama penerima")])
        # Nama yang terbaca (tidak diganti), nama panggilan yang tidak tercetak, dan baris tanpa label: tanpa suara.
        for description in ("Transfer ke BUDI SANTOSO", "Transfer ke Pak Budi", "arisan (Mbak Siti)",
                            "Transfer ke RINA", "", None):
            with self.subTest(description=description):
                self.assertEqual(votes_for(lay, read, None, final(description=description)), [])
        # Tanpa nama di dokumen: nama merchant item yang terbaca.
        self.assertEqual(votes_for(lay, doc(name=None), "BUDI SANTOSO", final(description="Budi Santoso (QRIS)")), [])

    def test_name_inside_the_read_name_is_not_a_correction(self):
        # "RM AJO PIAMAN" terbaca; baris lain mencetak "AJO PIAMAN" saja: keterangan yang memuat nama terbaca
        # bukan koreksi, meskipun potongannya cocok dengan baris lain.
        lay = layout(nama(1, "nama", "AJO PIAMAN"), key="jago")
        self.assertEqual(votes_for(lay, doc(name="RM AJO PIAMAN"), None, final(description="RM Ajo Piaman (QRIS)")), [])
        self.assertEqual(votes_for(lay, doc(name="RM AJO PIAMAN"), None, final(description="makan (Ajo Piaman)")), [])

    def test_name_matching_two_labels_gives_no_vote(self):
        lay = layout(nama(3, "penerima", "SITI RAHAYU"), nama(6, "nama penerima", "SITI RAHAYU"), key="gopay")
        self.assertEqual(votes_for(lay, doc(name="BUDI"), None, final(description="ke Siti Rahayu")), [])

    def test_date_vote_never_for_today_or_doc_date(self):
        other = date(2026, 10, 25)
        lay = layout(tanggal(6, "waktu selesai", other), tanggal(7, "tanggal", DOC_DAY), tanggal(8, None, TODAY))
        self.assertEqual(votes_for(lay, doc(), None, final(txn_date=other)),
                         [Vote("label_tanggal", "jago", "waktu selesai")])
        for day in (DOC_DAY, TODAY, date(2026, 10, 1), None):   # tanggal bukti, hari ini, tidak tercetak, kosong
            with self.subTest(day=day):
                self.assertEqual(votes_for(lay, doc(), None, final(txn_date=day)), [])
        # Hari ini yang juga tercetak berlabel: tetap bukan suara (pilihan, bukan koreksi; K9).
        lay_today = layout(tanggal(6, "waktu selesai", TODAY))
        self.assertEqual(votes_for(lay_today, doc(), None, final(txn_date=TODAY)), [])

    def test_doc_date_is_the_wib_date_of_paid_at(self):
        # 25 Okt 18:00 UTC = 26 Okt 01:00 WIB: tanggal bukti 26 Okt, jadi 26 Okt bukan koreksi, 25 Okt koreksi.
        lay = layout(tanggal(6, "waktu selesai", date(2026, 10, 25)), tanggal(7, "tanggal", DOC_DAY))
        read = doc(paid_at="2026-10-25T18:00:00+00:00")
        self.assertEqual(votes_for(lay, read, None, final(txn_date=DOC_DAY)), [])
        self.assertEqual(votes_for(lay, read, None, final(txn_date=date(2026, 10, 25))),
                         [Vote("label_tanggal", "jago", "waktu selesai")])
        # Tanpa tanggal terbaca: tanggal tercetak berlabel yang dipilih user tetap suara.
        self.assertEqual(votes_for(lay, doc(paid_at=None), None, final(txn_date=DOC_DAY)),
                         [Vote("label_tanggal", "jago", "tanggal")])

    def test_at_most_one_vote_per_kind_and_all_kinds_together(self):
        other = date(2026, 10, 25)
        lay = layout(nominal(2, "total bayar", 12500), nominal(3, "jumlah", 12500), nama(4, "penerima", "SITI RAHAYU"),
                     tanggal(5, "waktu selesai", other), key="dana")
        votes = votes_for(lay, doc(total=10000, name="BUDI"), None, final(12500, other, "ke Siti Rahayu"))
        self.assertEqual(votes, [Vote("label_total", "dana", "total bayar"), Vote("label_pihak", "dana", "penerima"),
                                 Vote("label_tanggal", "dana", "waktu selesai")])

    def test_no_layout_no_key_or_unsafe_label_gives_no_vote(self):
        f = final(12500)
        for lay in (None, {}, {"v": 1, "lines": [nominal(1, "total", 12500)]},
                    layout(nominal(1, "total", 12500), key=""),
                    layout(nominal(1, "total", 12500), key="logo:" + "x" * 60),       # kunci > 60 karakter
                    layout(nominal(1, "transfer ke budi", 12500)),                     # kata di luar kosakata
                    layout(nominal(1, "total 12", 12500)),                             # digit
                    layout(nominal(1, "x" * 61, 12500))):
            with self.subTest(layout=lay):
                self.assertEqual(votes_for(lay, doc(total=1), None, f), [])

    def test_broken_layout_entries_are_ignored(self):
        lay = layout({"i": 1}, {"kind": "nominal", "label": "total"}, "rusak", nominal(2, "total bayar", 12500),
                     {"i": 3, "label": "tanggal", "kind": "tanggal", "date": "bukan tanggal"})
        self.assertEqual(votes_for(lay, {"amounts": None, "paid_at": "x"}, None, final(12500, date(2026, 10, 2))),
                         [Vote("label_total", "jago", "total bayar")])


class ReviewFixVotesTests(_Quiet):
    """Review L2 putaran 1: label penerima saja (I-1), kunci profil saja (M-1), nominal tanpa biaya bukan suara (M-4),
    nama panjang (M-3)."""

    PARTY = ("ke", "kirim ke", "ditransfer ke", "penerima", "nama", "nama penerima", "nama merchant", "toko", "tujuan",
             "recipient", "transfer to", "dibayar ke")
    NOT_PARTY = ("keterangan", "berita", "catatan", "sumber akun", "sumber dana", "dikirim dari", "dari", "status",
                 "status transaksi", "metode pembayaran", "nama pengirim", "lokasi merchant", "merchant location",
                 "id", "rekening sumber", "harga", "uang", "saldo")

    def test_name_vote_only_for_recipient_labels(self):
        for label in self.PARTY + self.NOT_PARTY:
            with self.subTest(label=label):
                lay = layout(nama(4, label, "SITI RAHAYU"), key="gopay")
                self.assertTrue(belajar._votable(label), label)   # label kosakata yang sah: hanya jenisnya yang menolak
                votes = votes_for(lay, doc(name="BUDI"), None, final(description="arisan Siti Rahayu"))
                self.assertEqual(votes, [Vote("label_pihak", "gopay", label)] if label in self.PARTY else [])

    def test_transfer_note_typed_as_description_is_not_a_name_correction(self):
        # Kasus review: keterangan/berita transfer diketik ulang sebagai deskripsi.
        lay = layout(nama(3, "ditransfer ke", "BUDI SANTOSO"), nama(8, "keterangan", "Arisan Bulanan"),
                     nama(9, "sumber akun", "ANDI PRATAMA"), key="gopay")
        for description in ("Arisan bulanan", "Andi Pratama", "arisan bulanan (Budi Santoso)"):
            with self.subTest(description=description):
                self.assertEqual(votes_for(lay, doc(name="BUDI SANTOSO"), None, final(description=description)), [])

    def test_logo_keys_never_vote(self):
        # Kunci logo bisa nama orang ("logo:wahyu nugroho"): tahap 1 hanya kunci profil (M-1).
        for key in ("logo:wahyu nugroho", "logo:gopay", "logo:byond", "wahyu", "GOPAY"):
            with self.subTest(key=key):
                lay = layout(nominal(2, "nominal", 50000), nama(3, "penerima", "SITI"), key=key)
                self.assertEqual(votes_for(lay, doc(total=52000), None, final(50000, description="ke Siti")), [])

    def test_amount_without_the_fee_is_not_a_vote(self):
        gopay = layout(nominal(5, "jumlah kirim uang", 10000), nominal(6, "biaya layanan", 1000),
                       nominal(7, "total bayar", 11000), key="gopay")
        # Total terbaca benar; user mencatat tanpa biaya: pilihan, bukan salah baca.
        self.assertEqual(votes_for(gopay, doc(total=11000), None, final(10000)), [])
        # Salah baca sebaliknya (total diambil dari sub-nominal), user mencatat total: suara.
        self.assertEqual(votes_for(gopay, doc(total=10000), None, final(11000)),
                         [Vote("label_total", "gopay", "total bayar")])
        # Tanpa baris biaya berlabel, label sub-nominal tetap suara.
        no_fee = layout(nominal(5, "jumlah kirim uang", 10000), nominal(7, "total bayar", 11000), key="gopay")
        self.assertEqual(votes_for(no_fee, doc(total=11000), None, final(10000)),
                         [Vote("label_total", "gopay", "jumlah kirim uang")])
        # Label sub-nominal yang juga "total" bukan nominal tanpa biaya.
        total_amount = layout(nominal(5, "total nominal", 10000), nominal(6, "biaya admin", 1000), key="gopay")
        self.assertEqual(votes_for(total_amount, doc(total=11000), None, final(10000)),
                         [Vote("label_total", "gopay", "total nominal")])

    def test_fee_discount_or_balance_label_is_never_a_total(self):
        for label in ("biaya admin", "biaya transaksi", "admin", "diskon", "potongan", "cashback", "pajak", "saldo"):
            with self.subTest(label=label):
                lay = layout(nominal(3, label, 2500), nominal(5, "total", 52500), key="bsi")
                self.assertEqual(votes_for(lay, doc(total=52500), None, final(2500)), [])

    def test_names_of_three_to_six_words_vote(self):
        for name in ("M ANDI SAPUTRA", "MUHAMMAD RIZKI ANDI SAPUTRA WIJAYA KUSUMA"):
            with self.subTest(name=name):
                lay = layout(nama(3, "penerima", name), key="dana")
                self.assertEqual(votes_for(lay, doc(name="BUDI"), None, final(description=f"arisan {name.title()}")),
                                 [Vote("label_pihak", "dana", "penerima")])
                # Potongan nama (bukan nama lengkap yang tercetak) tidak cocok.
                partial = " ".join(name.split()[1:])
                self.assertEqual(votes_for(lay, doc(name="BUDI"), None, final(description=partial)), [])


class TransitionTests(unittest.TestCase):
    def test_g5_transitions(self):
        allowed = {("setujui", "menunggu"): "disetujui", ("setujui", "ditolak"): "disetujui",
                   ("setujui", "dicabut"): "disetujui", ("tolak", "menunggu"): "ditolak",
                   ("cabut", "disetujui"): "dicabut"}
        for action in ("setujui", "tolak", "cabut", "hapus"):
            for status in ("menunggu", "disetujui", "ditolak", "dicabut", "lain"):
                with self.subTest(action=action, status=status):
                    self.assertEqual(next_status(status, action), allowed.get((action, status)))


# ── suara dan aturan (database) ─────────────────────────────────────────────

@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class DbBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        # Pembaca sungguhan (tes privasi) berjalan di loop; mode debug asyncio mengeluh bila satu langkah > 0,1 detik.
        asyncio.get_running_loop().slow_callback_duration = 2.0
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        # Resep SQLAlchemy untuk pysqlite: SAVEPOINT (begin_nested) butuh BEGIN eksplisit.
        event.listen(self.engine.sync_engine, "connect", lambda conn, _rec: setattr(conn, "isolation_level", None))
        event.listen(self.engine.sync_engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        patcher = patch.object(merchants, "_warned_no_key", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        async with self.Session() as db:
            self.users = [User(name=n) for n in ("Ani", "Budi", "Citra", "Dodi")]
            self.hh = [Household(name=f"R{i}") for i in range(3)]
            db.add_all([*self.users, *self.hh])
            await db.commit()

    async def vote(self, user, household, *votes):
        async with self.Session() as db:
            await record_votes(db, list(votes), user_id=user.id, household_id=household.id if household else None)
            await db.commit()

    async def rules(self):
        async with self.Session() as db:
            return (await db.execute(select(ProofRule).order_by(ProofRule.value))).scalars().all()

    async def vote_count(self, *where):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(ProofRuleVote).where(*where))).scalar_one()

    def item(self, lay, *, doc_type="transfer", document=None, household=None, merchant=None):
        return SimpleNamespace(id=uuid.uuid4(), layout=lay, doc_type=doc_type, document=document or doc(total=10000),
                               merchant=merchant, household_id=household.id if household else None)


V = Vote("label_total", "jago", "total bayar")


class VoteAndRuleTests(DbBase):
    async def test_threshold_two_distinct_users(self):
        self.assertEqual(RULE_MIN_USERS, 2)
        await self.vote(self.users[0], self.hh[0], V)
        self.assertEqual((await self.vote_count(), await self.rules()), (1, []))   # satu user: suara saja
        await self.vote(self.users[1], self.hh[1], V)
        [rule] = await self.rules()
        self.assertEqual((rule.kind, rule.rule_key, rule.value, rule.users, rule.households, rule.status),
                         ("label_total", "jago", "total bayar", 2, 2, "menunggu"))
        self.assertIsNone(rule.decided_at)

    async def test_same_user_votes_once(self):
        for _ in range(3):
            await self.vote(self.users[0], self.hh[0], V)
        await self.vote(self.users[0], self.hh[1], V)   # rumah tangga lain, user yang sama: tetap satu suara
        self.assertEqual((await self.vote_count(), await self.rules()), (1, []))

    async def test_households_counted(self):
        await self.vote(self.users[0], self.hh[0], V)
        await self.vote(self.users[1], self.hh[0], V)   # dua user satu rumah tangga: aturan, 1 rumah tangga
        [rule] = await self.rules()
        self.assertEqual((rule.users, rule.households, rule.status), (2, 1, "menunggu"))
        await self.vote(self.users[2], None, V)           # tanpa rumah tangga: user dihitung, rumah tangga tidak
        await self.vote(self.users[3], self.hh[2], V)
        [rule] = await self.rules()
        self.assertEqual((rule.users, rule.households), (4, 2))

    async def test_new_votes_update_counts_without_changing_status(self):
        await self.vote(self.users[0], self.hh[0], V)
        await self.vote(self.users[1], self.hh[1], V)
        for status in ("ditolak", "disetujui", "dicabut"):
            async with self.Session() as db:
                rule = (await db.execute(select(ProofRule))).scalar_one()
                rule.status = status
                await db.commit()
            user = self.users[{"ditolak": 2, "disetujui": 3, "dicabut": 0}[status]]
            await self.vote(user, self.hh[2], V)
            [rule] = await self.rules()
            self.assertEqual(rule.status, status)
        self.assertEqual(((await self.rules())[0].users, (await self.rules())[0].households), (4, 3))

    async def test_rules_are_per_kind_key_and_value(self):
        others = [Vote("label_total", "jago", "jumlah"), Vote("label_total", "dana", "total bayar"),
                  Vote("label_pihak", "jago", "total bayar")]
        await self.vote(self.users[0], self.hh[0], V, *others)
        await self.vote(self.users[1], self.hh[1], V)
        self.assertEqual([(r.kind, r.rule_key, r.value) for r in await self.rules()], [("label_total", "jago", "total bayar")])
        self.assertEqual(await self.vote_count(), 5)

    async def test_recount_returns_rule_or_none_and_never_deletes(self):
        async with self.Session() as db:
            self.assertIsNone(await recount(db, "label_total", "jago", "total bayar"))
        await self.vote(self.users[0], self.hh[0], V)
        await self.vote(self.users[1], self.hh[1], V)
        async with self.Session() as db:
            await db.execute(ProofRuleVote.__table__.delete())
            rule = await recount(db, "label_total", "jago", "total bayar")
            await db.commit()
        self.assertEqual((rule.users, rule.households, rule.status), (0, 0, "menunggu"))
        self.assertEqual(len(await self.rules()), 1)


class LearnFromCorrectionTests(DbBase):
    LAY = layout(nominal(3, "nominal", 10000), nominal(5, "total bayar", 12500))

    async def learn(self, item, f, user):
        async with self.Session() as db:
            n = await learn_from_correction(db, item, f, user_id=user.id)
            await db.commit()
            return n

    async def test_votes_with_the_items_household(self):
        n = await self.learn(self.item(self.LAY, household=self.hh[0]), final(12500), self.users[0])
        self.assertEqual(n, 1)
        async with self.Session() as db:
            row = (await db.execute(select(ProofRuleVote))).scalar_one()
        self.assertEqual((row.kind, row.rule_key, row.value, row.user_id, row.household_id),
                         ("label_total", "jago", "total bayar", self.users[0].id, self.hh[0].id))
        await self.learn(self.item(self.LAY, household=self.hh[0]), final(12500), self.users[1])
        [rule] = await self.rules()
        self.assertEqual((rule.users, rule.households), (2, 1))

    async def test_no_learning_from_store_receipts_or_items_without_layout(self):
        cases = [self.item(self.LAY, doc_type="struk_belanja"), self.item(None), self.item({}),
                 self.item(self.LAY, doc_type=None)]
        for item in cases:
            with self.subTest(doc_type=item.doc_type, layout=item.layout):
                self.assertEqual(await self.learn(item, final(12500), self.users[0]), 0)
        self.assertEqual(await self.vote_count(), 0)
        for doc_type in ("qris", "transfer", "tidak_dikenali"):
            self.assertEqual(await self.learn(self.item(self.LAY, doc_type=doc_type), final(12500), self.users[0]), 1)

    async def test_errors_are_swallowed_logged_and_leave_the_session_usable(self):
        item = self.item(self.LAY, household=self.hh[0])
        async with self.Session() as db:
            with patch.object(belajar, "record_votes", AsyncMock(side_effect=RuntimeError("x"))), \
                    self.assertLogs(BELAJAR_LOG, "WARNING") as logs:
                self.assertEqual(await learn_from_correction(db, item, final(12500), user_id=self.users[0].id), 0)
            self.assertIn(str(item.id), logs.output[0])
            with patch.object(belajar, "votes_for", side_effect=KeyError("x")), self.assertLogs(BELAJAR_LOG, "WARNING"):
                self.assertEqual(await learn_from_correction(db, item, final(12500), user_id=self.users[0].id), 0)
            db.add(User(name="Sesudah"))
            await db.commit()   # sesi pemanggil tetap bisa meng-commit

    async def test_database_failure_rolls_back_only_the_votes(self):
        item = self.item(self.LAY, household=self.hh[0])
        with postgres_abort(self.engine, "INSERT INTO proof_rule_votes") as state:
            async with self.Session() as db:
                db.add(User(name="Ditulis bersama"))
                await db.flush()
                with self.assertLogs(BELAJAR_LOG, "WARNING"):
                    self.assertEqual(await learn_from_correction(db, item, final(12500), user_id=self.users[0].id), 0)
                await db.commit()   # Postgres: hanya bisa bila savepoint suara sudah dibatalkan
        self.assertEqual(state["left"], 0)
        self.assertEqual(await self.vote_count(), 0)
        async with self.Session() as db:   # tulisan pemanggil sebelum suara tetap ter-commit
            self.assertEqual((await db.execute(select(func.count()).select_from(User).where(
                User.name == "Ditulis bersama"))).scalar_one(), 1)

    async def test_never_commits_itself(self):
        item = self.item(self.LAY, household=self.hh[0])
        async with self.Session() as db:
            self.assertEqual(await learn_from_correction(db, item, final(12500), user_id=self.users[0].id), 1)
            await db.rollback()   # pemanggil membatalkan: suaranya ikut batal
        self.assertEqual(await self.vote_count(), 0)


class DecideTests(DbBase):
    NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

    async def pending_rule(self):
        await self.vote(self.users[0], self.hh[0], V)
        await self.vote(self.users[1], self.hh[1], V)
        return (await self.rules())[0]

    async def decide(self, rule_id, action, note=None):
        async with self.Session() as db:
            rule = await belajar.decide(db, rule_id, action, by=self.users[3].id, note=note, now=self.NOW)
            await db.commit()
            return rule

    async def test_decisions_follow_g5_and_record_who_when_and_note(self):
        rule = await self.pending_rule()
        got = await self.decide(rule.id, "setujui", "cocok")
        self.assertEqual((got.status, got.decided_by, got.note), ("disetujui", self.users[3].id, "cocok"))
        self.assertEqual(got.decided_at.replace(tzinfo=timezone.utc), self.NOW)
        for action in ("setujui", "tolak"):   # dari disetujui hanya cabut
            with self.subTest(action=action), self.assertRaises(belajar.RuleConflict) as err:
                await self.decide(rule.id, action)
            self.assertEqual(str(err.exception), "Aturan ini tidak bisa diubah ke status itu")
        self.assertEqual((await self.decide(rule.id, "cabut")).status, "dicabut")
        self.assertEqual((await self.decide(rule.id, "setujui")).status, "disetujui")   # dicabut -> setujui lagi
        with self.assertRaises(belajar.RuleConflict):
            await self.decide(rule.id, "hapus")
        self.assertEqual((await self.rules())[0].users, 2)   # keputusan tidak menyentuh hitungan

    async def test_unknown_rule_is_not_found(self):
        with self.assertRaises(belajar.RuleNotFound) as err:
            await self.decide(uuid.uuid4(), "setujui")
        self.assertEqual(str(err.exception), "Aturan tidak ditemukan")

    async def test_reject_only_from_pending_and_setujui_reopens_rejected(self):
        rule = await self.pending_rule()
        self.assertEqual((await self.decide(rule.id, "tolak")).status, "ditolak")
        with self.assertRaises(belajar.RuleConflict):
            await self.decide(rule.id, "tolak")
        with self.assertRaises(belajar.RuleConflict):
            await self.decide(rule.id, "cabut")
        self.assertEqual((await self.decide(rule.id, "setujui")).status, "disetujui")


class ReconcileTests(DbBase):
    """Review L2 M-2: dua suara bersamaan bisa tidak membuat aturan atau menyimpan hitungan lama; rekonsiliasi tiap jam
    menyamakan semuanya dari tabel suara."""

    async def add_votes(self, *rows):
        async with self.Session() as db:   # suara mentah tanpa recount (seperti dua transaksi yang tumpang tindih)
            db.add_all([ProofRuleVote(kind=V.kind, rule_key=V.rule_key, value=V.value, user_id=u.id,
                                      household_id=h.id if h else None) for u, h in rows])
            await db.commit()

    async def reconcile(self):
        async with self.Session() as db:
            return await maintenance.reconcile_proof_rules(db)   # meng-commit sendiri

    async def test_two_first_votes_without_a_rule_get_their_rule(self):
        await self.add_votes((self.users[0], self.hh[0]), (self.users[1], self.hh[1]))
        self.assertEqual(await self.rules(), [])
        self.assertEqual(await self.reconcile(), 1)
        [rule] = await self.rules()
        self.assertEqual((rule.users, rule.households, rule.status), (2, 2, "menunggu"))
        self.assertEqual(await self.reconcile(), 0)   # idempoten

    async def test_stale_count_from_concurrent_creation_is_corrected_without_touching_status(self):
        await self.add_votes((self.users[0], self.hh[0]), (self.users[1], self.hh[0]), (self.users[2], self.hh[1]))
        async with self.Session() as db:
            db.add(ProofRule(kind=V.kind, rule_key=V.rule_key, value=V.value, users=2, households=1,
                             status="disetujui"))
            await db.commit()
        self.assertEqual(await self.reconcile(), 1)
        [rule] = await self.rules()
        self.assertEqual((rule.users, rule.households, rule.status), (3, 2, "disetujui"))
        self.assertEqual(await self.reconcile(), 0)

    async def test_single_votes_stay_votes_and_rules_without_votes_drop_to_zero(self):
        other = Vote("label_pihak", "dana", "penerima")
        await self.add_votes((self.users[0], self.hh[0]))
        async with self.Session() as db:
            db.add(ProofRule(kind=other.kind, rule_key=other.rule_key, value=other.value, users=2, households=2,
                             status="ditolak"))
            await db.commit()
        self.assertEqual(await self.reconcile(), 1)
        [rule] = await self.rules()   # hanya aturan lama; satu suara tidak membuat aturan
        self.assertEqual((rule.value, rule.users, rule.households, rule.status), ("penerima", 0, 0, "ditolak"))
        self.assertEqual(await self.reconcile(), 0)


class ForgetUserTests(DbBase):
    async def test_forget_user_recounts(self):
        other = Vote("label_pihak", "dana", "penerima")
        await self.vote(self.users[0], self.hh[0], V, other)
        await self.vote(self.users[1], self.hh[1], V, other)
        await self.vote(self.users[2], self.hh[1], other)
        async with self.Session() as db:
            rule = (await db.execute(select(ProofRule).where(ProofRule.value == "total bayar"))).scalar_one()
            rule.status = "disetujui"
            await db.commit()
        async with self.Session() as db:
            await forget_user(db, self.users[0].id)
            await db.commit()
        self.assertEqual(await self.vote_count(ProofRuleVote.user_id == self.users[0].id), 0)
        got = {r.value: (r.users, r.households, r.status) for r in await self.rules()}
        # Hitungan turun, status tidak berubah, baris aturan tidak dihapus (spec §8, G7).
        self.assertEqual(got, {"total bayar": (1, 1, "disetujui"), "penerima": (2, 1, "menunggu")})
        async with self.Session() as db:   # user tanpa suara: tidak ada yang berubah
            await forget_user(db, self.users[3].id)
            await db.commit()
        self.assertEqual(await self.vote_count(), 3)

    async def test_merge_users_forgets_source_votes(self):
        from app.services.merge import merge_users
        src, tgt = self.users[0], self.users[1]
        async with self.Session() as db:
            db.add_all([HouseholdMember(user_id=src.id, household_id=self.hh[0].id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=tgt.id, household_id=self.hh[1].id, role=HouseholdRole.owner)])
            await db.commit()
        await self.vote(src, self.hh[0], V)
        await self.vote(tgt, self.hh[1], V)
        await self.vote(self.users[2], self.hh[2], V)
        async with self.Session() as db:
            decided = (await db.execute(select(ProofRule))).scalar_one()
            decided.decided_by = src.id
            await db.commit()
        async with self.Session() as db:
            result = await merge_users(src.id, tgt.id, self.hh[1].id, db)
        self.assertEqual(result["status"], "merged")
        self.assertEqual(await self.vote_count(ProofRuleVote.user_id == src.id), 0)
        [rule] = await self.rules()
        self.assertEqual((rule.users, rule.households), (2, 2))
        self.assertEqual(rule.decided_by, tgt.id)   # jejak keputusan pindah ke akun tujuan


# ── tanpa data pribadi (Review Focus 3) ─────────────────────────────────────

def _name_words(case, document, clean) -> set[str]:
    names = [document.counterparty.name, pc.read_sender_name(clean, detect_issuer(clean)), case.get("user_name")]
    try:
        names.append(pc.read_name(pc.body_lines(clean), detect_issuer(clean), "merchant"))
    except Exception:
        pass
    return {w for n in names for w in normalize_name(n).split()}


def _corrections(lay, clean):
    """Setiap koreksi yang mungkin dari kerangka ini: tiap nominal dan tanggal tercetak, dan tiap baris teks sebagai
    keterangan (memuat semua nama yang tercetak, jadi setiap baris `nama` bisa cocok)."""
    out = [final(amount=e["amount"]) for e in lay["lines"] if e.get("kind") == "nominal"]
    out += [final(txn_date=date.fromisoformat(e["date"])) for e in lay["lines"] if e.get("kind") == "tanggal"]
    out += [final(description=line) for line in clean]
    out.append(final(description=" ".join(clean)))
    return out


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class PrivacyTests(DbBase):
    async def test_votes_and_rules_hold_no_pii(self):
        """Setiap daftar sapuan (kedua saklar): kerangka dari pembaca sungguhan, setiap koreksi yang mungkin, oleh dua
        user (jadi aturan terbentuk). Suara dan aturan hanya memuat jenis, kunci aplikasi, dan label kosakata: tanpa
        digit, tanpa `#`, tanpa kata nama pihak lawan/pengirim/user sampel itu."""
        built = voted = 0
        async with self.Session() as db:
            for case in SWEEP:
                for enabled in (False, True):
                    text = TextDoc(lines=list(case["lines"]), kind=KIND_IMAGE)
                    res = await read_document(text, ParseContext(today=TODAY, user_name=case.get("user_name")),
                                              proofs_enabled=enabled)
                    document = res.parsed.doc
                    lay = build_layout(case["lines"], document, res.parsed.secrets, user_name=case.get("user_name"))
                    if lay is None:
                        continue
                    built += 1
                    clean = pc.clean_lines(case["lines"])
                    forbidden = _name_words(case, document, clean)
                    item = SimpleNamespace(id=uuid.uuid4(), layout=lay, doc_type=document.doc_type,
                                           document=document.to_json(), merchant=document.counterparty.name,
                                           household_id=self.hh[0].id)
                    for f in _corrections(lay, clean):
                        votes = votes_for(lay, item.document, item.merchant, f)
                        for v in votes:
                            with self.subTest(id=case["id"], on=enabled, vote=v):
                                words = set(re.findall(r"[a-z]+", f"{v.rule_key} {v.value}".lower()))
                                self.assertFalse(words & forbidden, v)
                        for user in self.users[:2]:
                            voted += await learn_from_correction(db, item, f, user_id=user.id)
            await db.commit()
            vote_rows = (await db.execute(select(ProofRuleVote))).scalars().all()
            rule_rows = (await db.execute(select(ProofRule))).scalars().all()
        self.assertGreater(built, 20)
        self.assertGreater(voted, 20)
        self.assertGreater(len(rule_rows), 5)   # dua user: suara yang sama menjadi aturan
        self.assertEqual({r.kind for r in rule_rows} | {v.kind for v in vote_rows} <= {"label_total", "label_pihak",
                                                                                        "label_tanggal"}, True)
        for row in [*vote_rows, *rule_rows]:
            with self.subTest(row=(row.kind, row.rule_key, row.value)):
                for text in (row.kind, row.rule_key, row.value):
                    self.assertNotRegex(text, r"\d")
                    self.assertNotIn("#", text)
                self.assertIn(row.rule_key, PROFILE_KEYS)   # tahap 1: tidak pernah kunci `logo:` (review L2 M-1)
                if row.kind == "label_pihak":   # hanya label penerima (review L2 I-1)
                    self.assertTrue(belajar._party_label(row.value), row.value)
                if row.kind == "label_total":
                    self.assertFalse(set(row.value.split()) & belajar.NOT_TOTAL_WORDS, row.value)
                self.assertTrue(all(w in LABEL_WORDS for w in re.findall(r"[^\s]+", row.value)
                                    if w.strip(".,:;()'&/-")), row.value)
                self.assertLessEqual(len(row.value), 40)
        for row in rule_rows:
            self.assertIsNone(row.note)
        # Kolom tabel: tidak ada tempat untuk nominal, tanggal, nama, atau teks bebas di luar label dan catatan admin.
        self.assertEqual(set(ProofRuleVote.__table__.c.keys()),
                         {"kind", "rule_key", "value", "user_id", "household_id", "created_at"})
        self.assertEqual(set(ProofRule.__table__.c.keys()),
                         {"id", "kind", "rule_key", "value", "users", "households", "status", "created_at",
                          "decided_at", "decided_by", "note"})


if __name__ == "__main__":
    unittest.main()
