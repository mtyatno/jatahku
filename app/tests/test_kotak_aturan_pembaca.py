"""Pembaca memakai aturan belajar yang disetujui (spec 2026-11-01 §1.3, §5; plan Task L3; pre-flight §5, K6).

Review Focus 2 (`test_rules_never_bypass_status_blocks`): aturan apa pun, juga aturan jahat berlabel "status" atau teks
baris gagal, tidak pernah mengubah status gagal/pending, ceknya, atau `check_recordable`. Review Focus 6
(`test_empty_rules_change_nothing`, `test_corpus_eval_uses_no_rules`): tanpa aturan = perilaku hari ini, dan alat
korpus tidak pernah memakai aturan. Baris di sini sintetis (nama dan nomor fiktif).
Run: python -m unittest app.tests.test_kotak_aturan_pembaca -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import json
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select

from app.models.models import ProofRule
from app.scripts import kotak_corpus, kotak_sapuan
from app.services.kotak_struk import belajar, checks as cross_checks, kerangka, record, registry
from app.services.kotak_struk.belajar import Final, votes_for
from app.services.kotak_struk.config import RULE_CACHE_S
from app.services.kotak_struk.extract import KIND_IMAGE, TextDoc
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers import profiles
from app.services.kotak_struk.readers.base import ParseContext
from app.services.kotak_struk.readers.labels import WIB, learned_amount, learned_datetime
from app.services.kotak_struk.readers.profiles import PROFILES, Learned, detect_issuer, learned_for, with_learned
from app.services.kotak_struk.readers.struk_belanja import StrukBelanjaReader
from app.services.kotak_struk.registry import read_document

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
FIXTURES = Path(__file__).parent / "fixtures" / "kotak"
SWEEP = json.loads((FIXTURES / "sweep_lines.json").read_text(encoding="utf-8"))
SNAPSHOT = json.loads((FIXTURES / "sweep_snapshot.json").read_text(encoding="utf-8"))
CORPUS = json.loads((FIXTURES / "corpus.json").read_text(encoding="utf-8"))["samples"]
TODAY = date(2026, 11, 1)
USER = "RINA WULANDARI"
PROFILE_KEYS = sorted(p.key for p in PROFILES)
BELAJAR_LOG = "app.services.kotak_struk.belajar"
SWITCHES = (("off", False), ("on", True))

# GoPay, salah baca hari ini: saldo "Rp50.000" (nominal Rp tanpa label pertama sesudah judul) terbaca sebagai total
# `sedang`; total sebenarnya di bawah label "Jumlah Kirim Uang" yang bukan label total.
GOPAY_MISREAD = ["GoPay", "Transfer Berhasil", "Ditransfer ke", "BUDI SANTOSO", "Saldo GoPay", "Rp50.000",
                 "Jumlah Kirim Uang", "Rp12.500", "Tanggal 26 Okt 2026 08:12"]
# GoPay QRIS: total, nama toko, dan waktu selesai salah baca hari ini (cashback, pengakuisisi, waktu dibuat).
GOPAY_QRIS = ["GoPay", "Pembayaran Berhasil", "QRIS", "Merchant PT DOMPET CONTOH", "Nama Toko WARUNG BAKSO PAK DI",
              "NMID ID1234567890", "Cashback", "Rp2.000", "Dibayar", "Rp15.000", "Waktu Dibuat 25 Okt 2026 23:58",
              "Waktu Selesai 26 Okt 2026 00:01"]
# Resi tagihan Jago (dibaca pembaca tidak dikenali, kunci profil `jago`): nominal utama sebelum biaya.
JAGO_BILL = ["Jago Syariah", "PT CONTOH DAYA", "PLN Prepaid· …3150", "Rp50.000", "ID Transaksi", "…6208", "Sumber akun",
             "RINA WULANDARI", "Jago …4821", "Tanggal & waktu transaksi", "29 Okt 2026, 23:24 WIB",
             "Rp Bayar:  Rp50.000", "Admin Bank:  Rp2.500", "Dibayar:  Rp 52.500",
             "Resi ini merupakan bukti transaksi yang sah"]
GOPAY_FEE = ["GoPay", "Transfer Berhasil", "Penerima", "BUDI SANTOSO", "Nominal Rp10.000", "Biaya Layanan Rp1.000",
             "Dibayar Rp12.000", "Tanggal 26 Okt 2026 08:12"]
GOPAY_TRANSFER = ["GoPay", "Transfer Berhasil", "Ditransfer ke", "BUDI SANTOSO", "Jumlah Kirim Uang", "Rp10.000",
                  "Biaya Layanan Rp1.000", "Total Bayar Rp11.000", "Tanggal 26 Okt 2026 08:12"]
# BSI ke rekening sendiri (review L3 I-1): tanpa aturan `antar_rekening_sendiri` untuk user RINA WULANDARI.
BSI_SELF = ["BYOND", "by BSI", "Transaksi Berhasil", "29 Okt 2026 23:30", "Nama Penerima RINA WULANDARI", "Bank Jago",
            "Tujuan Transfer Lainnya", "Nominal Transaksi Rp 50.000", "Total Rp 50.000"]
# Label jahat (Review Focus 2): kata status, label status, label total/nama/tanggal umum.
HOSTILE_BASE = ["status", "status transaksi", "status pembayaran", "transaksi", "gagal", "pending", "berhasil",
                "total", "total bayar", "jumlah", "nominal", "dibayar", "keterangan", "ke", "penerima", "tanggal",
                "waktu", "transfer gagal", "pembayaran gagal", "transaksi gagal"]


def rule(total=(), party=(), dates=()):
    return {"label_total": list(total), "label_pihak": list(party), "label_tanggal": list(dates)}


def ctx(rules=None, *, user_name=USER, **kw):
    if rules is not None:
        kw["rules"] = rules
    return ParseContext(today=TODAY, user_name=user_name, **kw)


async def read(lines, rules=None, *, enabled=True, user_name=USER, **kw):
    return await read_document(TextDoc(lines=list(lines), kind=KIND_IMAGE), ctx(rules, user_name=user_name, **kw),
                               proofs_enabled=enabled)


def full(res) -> str:
    """Seluruh hasil baca (dokumen, cek, rahasia, data tambahan, pembaca) sebagai teks: pembanding byte demi byte."""
    p = res.parsed
    return json.dumps({"doc": p.doc.to_json(), "secrets": vars(p.secrets), "extra": p.extra, "reader": res.reader,
                       "checks": [c.as_dict() for c in res.checks]}, sort_keys=True, ensure_ascii=False, default=str)


def own_key(lines) -> str | None:
    clean = pc.clean_lines(lines)
    return kerangka.rule_key(clean, detect_issuer(clean), forbidden_words=set())


def hostile_labels(lines) -> list[str]:
    """HOSTILE_BASE dan teks setiap baris daftar itu (1-5 kata pertama dan baris utuh): termasuk label = baris gagal."""
    labels = list(HOSTILE_BASE)
    for line in pc.clean_lines(lines):
        words = line.lower().split()
        labels += [" ".join(words[:n]) for n in range(1, min(len(words), 5) + 1)] + [" ".join(words)]
    return list(dict.fromkeys(labels))


def hostile_rules(lines, keys=PROFILE_KEYS) -> dict:
    labels = hostile_labels(lines)
    return {key: rule(labels, labels, labels) for key in keys}


def status_view(res) -> tuple:
    """Yang tidak boleh diubah aturan: status, cek status, semua cek blokir, arah uang selain keluar, dan nomor
    referensi (bahan cek duplikat)."""
    doc = res.parsed.doc
    levels = {c.code: c.level for c in res.checks}
    return (doc.doc_type, doc.status, {k: v for k, v in levels.items() if k.startswith("status_")},
            sorted(k for k, v in levels.items() if v == "block"), doc.flow if doc.flow != "keluar" else None,
            list(res.parsed.secrets.ref_values))


# Label realistis untuk sapuan arah uang: lolos `kerangka.safe_label` (bentuk nilai aturan), tanpa `#`.
DIRECTION_EXTRA = ["tujuan", "tujuan transfer", "bank tujuan", "rekening tujuan", "nama penerima", "penerima", "ke",
                   "kepada", "ditransfer ke", "dikirim ke", "nama", "nama merchant", "merchant", "toko", "nama toko",
                   "recipient", "to", "name", "transfer ke", "transfer ke penerima", "dari", "pengirim", "sumber dana",
                   "keterangan", "berita", "status", "tanggal", "waktu", "total", "jumlah", "nominal"]


def realistic_labels(lines) -> list[str]:
    out = list(DIRECTION_EXTRA)
    for line in pc.clean_lines(lines):
        words = line.split()
        out += [" ".join(words[:n]) for n in range(1, min(len(words), 5) + 1)]
    safe = (kerangka.safe_label(label, forbidden_words=set()) for label in out)
    return list(dict.fromkeys(label for label in safe if label and "#" not in label))


async def recordable(document: dict) -> str:
    """Hasil `record.check_recordable` untuk item `siap` berisi dokumen ini (tanpa duplikat): "ok" atau pesannya."""
    uid = uuid.uuid4()
    item = SimpleNamespace(id=uuid.uuid4(), user_id=uid, status="siap", doc_type=document["doc_type"],
                           document=document, household_id=None, file_sha256=None, ref_hash=None)
    db = SimpleNamespace(get=AsyncMock(return_value=item))
    with patch.object(record.dedup, "recorded_duplicate", AsyncMock(return_value=False)):
        try:
            await record.check_recordable(db, item.id, SimpleNamespace(id=uid))
        except record.NotRecordable as exc:
            return str(exc)
    return "ok"


def tagged(*tags):
    return [e for e in SWEEP if set(e["tags"]) & set(tags)]


class _Loop(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Sapuan pembaca sungguhan di loop: mode debug asyncio mengeluh bila satu langkah > 0,1 detik.
        asyncio.get_running_loop().slow_callback_duration = 5.0
        belajar.invalidate_rules_cache()
        self.addCleanup(belajar.invalidate_rules_cache)


# ── Review Focus 6: tanpa aturan = perilaku hari ini ────────────────────────

class NoRulesTests(_Loop):
    async def test_empty_rules_change_nothing(self):
        """Setiap daftar sapuan, kedua saklar: konteks tanpa `rules`, `rules={}`, aturan kosong untuk setiap kunci
        profil, dan aturan untuk kunci yang tidak dipakai daftar itu memberi hasil baca yang SAMA byte demi byte, dan
        sama dengan snapshot sapuan (yang dibuat sebelum L3)."""
        empty_lists = {key: rule() for key in PROFILE_KEYS}
        for entry in SWEEP:
            other = {key: rule(*[hostile_labels(entry["lines"])] * 3) for key in PROFILE_KEYS
                     if key != own_key(entry["lines"])}
            for switch, enabled in SWITCHES:
                with self.subTest(entry["id"], switch=switch):
                    base = full(await read(entry["lines"], enabled=enabled, user_name=entry.get("user_name")))
                    for rules in ({}, empty_lists, other, {"logo:contoh": rule(["total"], ["ke"], ["tanggal"])}):
                        got = await read(entry["lines"], rules, enabled=enabled, user_name=entry.get("user_name"))
                        self.assertEqual(full(got), base)
        # Kolom yang disimpan worker (snapshot sapuan) dengan `rules={}` dan aturan kosong: tanpa beda.
        for rules in ({}, empty_lists):
            real = ParseContext
            with self.subTest(rules=bool(rules)), \
                    patch.object(kotak_sapuan, "ParseContext", lambda **kw: real(**kw, rules=rules)):
                built = await kotak_sapuan.build()
                self.assertEqual(kotak_sapuan.diff(SNAPSHOT, built), [])

    async def test_corpus_eval_uses_no_rules(self):
        """`kotak_corpus` membangun ParseContext tanpa aturan (`rules == {}`), juga saat cache aturan yang disetujui
        terisi di proses yang sama; hasil evaluasinya sama dengan tanpa cache."""
        for sample in CORPUS:
            self.assertEqual(kotak_corpus.sample_context(sample).rules, {})
        hostile = {key: rule(HOSTILE_BASE, HOSTILE_BASE, HOSTILE_BASE) for key in PROFILE_KEYS}
        db = _RowsDb([(key, kind, label) for key, kinds in hostile.items() for kind, labels in kinds.items()
                      for label in labels])
        self.assertEqual(await belajar.approved_rules(db), hostile)   # cache terisi aturan untuk semua aplikasi
        seen = []
        real = kotak_corpus.read_document

        async def spy(doc, context, *, proofs_enabled):
            seen.append(context.rules)
            return await real(doc, context, proofs_enabled=proofs_enabled)

        with patch.object(kotak_corpus, "read_document", spy):
            cached = await asyncio.to_thread(kotak_corpus.evaluate, CORPUS)
        self.assertEqual(len(seen), len(CORPUS))
        self.assertTrue(all(rules == {} for rules in seen))
        belajar.invalidate_rules_cache()
        self.assertEqual(await asyncio.to_thread(kotak_corpus.evaluate, CORPUS), cached)


class _RowsDb:
    """Sesi tiruan untuk `approved_rules`: SAVEPOINT tanpa efek, SELECT mengembalikan `rows` (atau melempar `error`)."""

    def __init__(self, rows=(), error=None):
        self.rows, self.error, self.calls = list(rows), error, 0

    def begin_nested(self):
        return _AsyncNull()

    async def execute(self, _stmt):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(all=lambda: list(self.rows))


class _AsyncNull:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


# ── aturan dipakai pembaca ──────────────────────────────────────────────────

class LearnedReadingTests(_Loop):
    async def test_learned_total_label_reads_total_tinggi(self):
        """GoPay salah baca (saldo jadi total, `sedang`): aturan `label_total` "jumlah kirim uang" yang disetujui
        membaca total yang benar dengan keyakinan `tinggi`. Lingkaran belajar tertutup: koreksi user atas salah baca
        ini memberi suara persis aturan itu, dan sesudah aturan dipakai, mencatat nominal yang sama tidak memberi
        suara lagi."""
        plain = await read(GOPAY_MISREAD)
        d = plain.parsed.doc
        self.assertEqual((d.doc_type, d.issuer, d.amounts.total, d.confidence["total"]), ("transfer", "gopay", 50000, "sedang"))
        layout = kerangka.build_layout(GOPAY_MISREAD, d, plain.parsed.secrets, user_name=USER)
        final = Final(amount=12500, txn_date=date(2026, 10, 26), description="Transfer ke BUDI SANTOSO", today=TODAY)
        votes = votes_for(layout, d.to_json(), None, final)
        self.assertEqual([(v.kind, v.rule_key, v.value) for v in votes], [("label_total", "gopay", "jumlah kirim uang")])

        rules = {"gopay": rule(["jumlah kirim uang"])}
        learned = (await read(GOPAY_MISREAD, rules)).parsed.doc
        self.assertEqual((learned.amounts.total, learned.confidence["total"]), (12500, "tinggi"))
        self.assertEqual((learned.issuer, learned.status, learned.counterparty.name), ("gopay", "berhasil", "BUDI SANTOSO"))
        self.assertEqual(votes_for(layout, learned.to_json(), None, final), [])
        # Kedua saklar mati: perilaku lama (aturan hanya untuk saklar bukti bayar yang menyala).
        off = (await read(GOPAY_MISREAD, rules, enabled=False)).parsed.doc
        self.assertEqual(full(await read(GOPAY_MISREAD, rules, enabled=False)),
                         full(await read(GOPAY_MISREAD, enabled=False)))
        self.assertNotEqual(off.confidence.get("total"), "tinggi")

    async def test_learned_labels_on_qris_and_unknown_documents(self):
        rules = {"gopay": rule(["dibayar"], ["nama toko"], ["waktu selesai"])}
        plain = (await read(GOPAY_QRIS)).parsed.doc
        self.assertEqual((plain.doc_type, plain.amounts.total, plain.counterparty.name), ("qris", 2000, "PT DOMPET CONTOH"))
        got = (await read(GOPAY_QRIS, rules)).parsed.doc
        self.assertEqual((got.doc_type, got.issuer, got.amounts.total, got.confidence["total"]), ("qris", "gopay", 15000, "tinggi"))
        # Tidak dikenali (kunci profil jago): total aturan sebelum `_app_receipt_total`, tanggal dari label aturan.
        plain = (await read(JAGO_BILL)).parsed.doc
        self.assertEqual((plain.doc_type, plain.amounts.total, plain.confidence["total"]), ("tidak_dikenali", 50000, "sedang"))
        rules = {"jago": rule(["dibayar"], [], ["tanggal & waktu transaksi"])}
        got = await read(JAGO_BILL, rules)
        d = got.parsed.doc
        self.assertEqual((got.reader, d.doc_type, d.issuer, d.status), ("tidak_dikenali", "tidak_dikenali", None, "tidak_diketahui"))
        self.assertEqual((d.amounts.total, d.confidence), (52500, {"total": "tinggi", "paid_at": "tinggi"}))
        self.assertEqual(d.paid_at, datetime(2026, 10, 29, 23, 24, tzinfo=WIB))
        self.assertIn("Total dari label aturan belajar", d.evidence)
        # Hanya aturan total: tanggal tetap tebakan biasa (tepat satu tanggal tercetak).
        d = (await read(JAGO_BILL, {"jago": rule(["dibayar"])})).parsed.doc
        self.assertEqual((d.amounts.total, d.confidence, d.paid_at), (52500, {"total": "tinggi"}, plain.paid_at))
        # Label aturan yang tidak menemukan nominal: pembacaan tidak dikenali biasa.
        self.assertEqual(full(await read(JAGO_BILL, {"jago": rule(["total tagihan"], [], ["waktu"])})),
                         full(await read(JAGO_BILL)))

    async def test_unknown_reader_learned_total_comes_before_the_llm_fallback(self):
        llm = AsyncMock(return_value={"merchant": "TOKO", "date": None, "total": 99000})
        rules = {"jago": rule(["dibayar"])}
        d = (await read(JAGO_BILL, rules, image=b"img", content_type="image/jpeg", llm=llm)).parsed.doc
        self.assertEqual((d.amounts.total, d.confidence["total"]), (52500, "tinggi"))
        llm.assert_not_awaited()
        # Tanpa aturan (atau label aturan tanpa nominal): LLM cadangan seperti hari ini.
        for no_rules in (None, {"jago": rule(["total tagihan"])}):
            llm.reset_mock()
            d = (await read(JAGO_BILL, no_rules, image=b"img", content_type="image/jpeg", llm=llm)).parsed.doc
            self.assertEqual(d.amounts.total, 99000)
            llm.assert_awaited_once()

    async def test_rule_label_first_profile_label_fallback(self):
        # Label aturan didahulukan dari label total biasa ("Total Bayar")...
        d = (await read(GOPAY_TRANSFER, {"gopay": rule(["jumlah kirim uang"])})).parsed.doc
        self.assertEqual((d.amounts.total, d.confidence["total"]), (10000, "tinggi"))
        # ...tetapi label profil/generik tetap dipakai bila label aturan tidak menemukan nilai.
        base = full(await read(GOPAY_TRANSFER))
        for labels in (["jumlah tagihan"], ["total"], ["jumlah"], ["biaya"], []):
            with self.subTest(labels=labels):
                got = await read(GOPAY_TRANSFER, {"gopay": rule(labels)})
                self.assertEqual(full(got), base)
                self.assertEqual((got.parsed.doc.amounts.total, got.parsed.doc.confidence["total"]), (11000, "tinggi"))
        # Label aturan harus persis: "total" bukan "Total Bayar", "jumlah" bukan "Jumlah Kirim Uang".
        for labels in (["total"], ["jumlah"], ["saldo gopay rp"]):
            with self.subTest(labels=labels):
                self.assertEqual(full(await read(GOPAY_MISREAD, {"gopay": rule(labels)})), full(await read(GOPAY_MISREAD)))
        # Urutan label aturan = prioritas.
        d = (await read(GOPAY_TRANSFER, {"gopay": rule(["total bayar", "jumlah kirim uang"])})).parsed.doc
        self.assertEqual(d.amounts.total, 11000)

    async def test_cross_check_still_warns_on_a_learned_total(self):
        # Nominal + biaya != total aturan: peringatan `selisih_nominal` tetap ada dan keyakinan turun ke `sedang`.
        plain = await read(GOPAY_FEE)
        self.assertEqual((plain.parsed.doc.amounts.total, [c.code for c in plain.checks]), (11000, []))
        got = await read(GOPAY_FEE, {"gopay": rule(["dibayar"])})
        d = got.parsed.doc
        self.assertEqual((d.amounts.subtotal, d.amounts.fee, d.amounts.total), (10000, 1000, 12000))
        self.assertEqual({c.code: c.level for c in got.checks}, {"selisih_nominal": "warn"})
        self.assertEqual(d.confidence["total"], "sedang")

    async def test_learned_date_and_party_labels(self):
        plain = (await read(GOPAY_QRIS)).parsed.doc
        self.assertEqual((plain.counterparty.name, plain.paid_at), ("PT DOMPET CONTOH", datetime(2026, 10, 25, 23, 58, tzinfo=WIB)))
        d = (await read(GOPAY_QRIS, {"gopay": rule([], ["nama toko"], ["waktu selesai"])})).parsed.doc
        self.assertEqual((d.counterparty.name, d.confidence["counterparty"]), ("WARUNG BAKSO PAK DI", "tinggi"))
        self.assertEqual((d.paid_at, d.confidence["paid_at"]), (datetime(2026, 10, 26, 0, 1, tzinfo=WIB), "tinggi"))
        self.assertEqual(d.amounts.total, plain.amounts.total)   # tanpa aturan total: total tidak berubah
        # Tanggal di baris sendiri di bawah label aturan; label aturan yang hanya awalan ("waktu") tidak dibaca.
        lines = ["GoPay", "Pembayaran Berhasil", "QRIS", "Nama Merchant WARUNG BAKSO", "Total Bayar Rp15.000",
                 "Waktu Dibuat 25 Okt 2026 23:58", "Waktu Selesai", "26 Okt 2026 00:01"]
        self.assertEqual((await read(lines, {"gopay": rule([], [], ["waktu selesai"])})).parsed.doc.paid_at,
                         datetime(2026, 10, 26, 0, 1, tzinfo=WIB))
        self.assertEqual(full(await read(lines, {"gopay": rule([], [], ["waktu"])})), full(await read(lines)))
        # Transfer: label penerima aturan didahulukan, pengirim tidak pernah dibaca dari label penerima.
        lines = ["GoPay", "Transfer Berhasil", "Ditransfer ke", "BUDI SANTOSO", "Kepada Penerima", "SITI AMINAH",
                 "Jumlah Kirim Uang", "Rp10.000", "Total Bayar Rp10.000", "Tanggal 26 Okt 2026 08:12"]
        self.assertEqual((await read(lines)).parsed.doc.counterparty.name, "BUDI SANTOSO")
        d = (await read(lines, {"gopay": rule([], ["kepada penerima"])})).parsed.doc
        self.assertEqual((d.flow, d.counterparty.name), ("keluar", "SITI AMINAH"))

    async def test_refs_and_other_values_never_read_with_rule_labels(self):
        """Aturan hanya mengubah total, tanggal, dan nama penerima: nomor referensi (bahan cek duplikat), NMID, kota,
        bank, dan rekening dibaca dengan profil asli dan baris utuh, walau label penerima aturan mengosongkan baris
        "No Referensi …" (awalan "no") untuk bacaan nama."""
        qris = [*GOPAY_QRIS, "Lokasi BANDUNG", "No Referensi 612345678812"]
        transfer = ["GoPay", "Transfer Berhasil", "Ditransfer ke", "BUDI SANTOSO", "Kepada Penerima SITI AMINAH",
                    "Bank Tujuan BRI", "No Rekening 012301001234567", "Jumlah Kirim Uang", "Rp10.000",
                    "Total Bayar Rp10.000", "No Referensi 612345678812", "Tanggal 26 Okt 2026 08:12"]
        for lines, party in ((qris, "nama toko"), (transfer, "kepada penerima")):
            plain = await read(lines)
            got = await read(lines, {"gopay": rule([], [party, "no"], [])})
            p, g = plain.parsed, got.parsed
            self.assertNotEqual(g.doc.counterparty.name, p.doc.counterparty.name)   # aturan penerima dipakai
            self.assertTrue(p.secrets.ref_values)
            self.assertEqual((g.secrets.ref_values, g.secrets.nmid, g.secrets.account_number, g.doc.refs),
                             (p.secrets.ref_values, p.secrets.nmid, p.secrets.account_number, p.doc.refs))
            self.assertEqual((g.doc.counterparty.city, g.doc.amounts, g.doc.paid_at),
                             (p.doc.counterparty.city, p.doc.amounts, p.doc.paid_at))

    async def test_rule_for_one_profile_never_affects_another(self):
        self.assertEqual(full(await read(GOPAY_MISREAD, {"dana": rule(["jumlah kirim uang"])})), full(await read(GOPAY_MISREAD)))
        self.assertEqual(full(await read(GOPAY_QRIS, {k: rule(["dibayar"], ["nama toko"], ["waktu selesai"])
                                                      for k in PROFILE_KEYS if k != "gopay"})),
                         full(await read(GOPAY_QRIS)))
        both = {"dana": rule(["jumlah kirim uang"]), "gopay": rule(["saldo gopay"])}
        self.assertEqual((await read(GOPAY_MISREAD, both)).parsed.doc.amounts.total, 50000)
        # Bukti tanpa aplikasi yang dikenal (tanpa kunci, tahap 1): tidak ada aturan yang berlaku.
        lines = ["Transfer Berhasil", "Penerima", "BUDI SANTOSO", "Bank Tujuan BRI", "Saldo", "Rp50.000",
                 "Jumlah Kirim Uang", "Rp12.500", "26 Okt 2026 08:12"]
        self.assertIsNone(own_key(lines))
        self.assertEqual(full(await read(lines, hostile_rules(lines))), full(await read(lines)))

    async def test_store_reader_ignores_rules(self):
        """Struk belanja tidak pernah memakai aturan (Review Focus 4): setiap daftar bertanda struk yang dibaca pembaca
        struk belanja, kedua saklar, dengan aturan jahat untuk setiap aplikasi, sama byte demi byte; pembaca struk
        belanja langsung juga."""
        reader, checked = StrukBelanjaReader(), 0
        for entry in tagged("store", "store_void", "store_pending"):
            rules = hostile_rules(entry["lines"])
            for switch, enabled in SWITCHES:
                with self.subTest(entry["id"], switch=switch):
                    plain = await read(entry["lines"], enabled=enabled, user_name=entry.get("user_name"))
                    if plain.reader != "struk_belanja":
                        continue   # known_c3: struk yang dibaca pembaca QRIS (dicatat di sapuan)
                    got = await read(entry["lines"], rules, enabled=enabled, user_name=entry.get("user_name"))
                    self.assertEqual(full(got), full(plain))
                    checked += 1
            text = TextDoc(lines=list(entry["lines"]), kind=KIND_IMAGE)
            a = await reader.parse(text, ctx(rules))
            b = await reader.parse(text, ctx())
            self.assertEqual(json.dumps(a.doc.to_json(), sort_keys=True, default=str),
                             json.dumps(b.doc.to_json(), sort_keys=True, default=str))
        self.assertGreater(checked, 200)


# ── Review Focus 2: aturan tidak pernah melewati blokir ─────────────────────

class StatusBlockTests(_Loop):
    async def test_direction_never_loosened_by_rules(self):
        """Review L3 I-1 (spec §1.3): arah uang diputuskan dari bacaan tanpa aturan. Setiap bukti transfer di sapuan
        yang punya kunci aturan, saklar menyala, dengan user = penerima yang terbaca tanpa aturan (supaya cek "antar
        rekening sendiri" menyala) dan dengan user daftar itu sendiri; setiap label realistis (lolos `safe_label`) sebagai
        aturan semua jenis: arah selain `keluar` (antar rekening sendiri, uang masuk, top-up) tidak pernah berubah."""
        rules = {"bsi": rule([], ["tujuan"])}
        for labels in (["tujuan"], ["tujuan transfer"], ["bank tujuan"]):
            got = (await read(BSI_SELF, {"bsi": rule([], labels)})).parsed.doc
            self.assertEqual((got.doc_type, got.status, got.flow, got.counterparty.name),
                             ("transfer", "berhasil", "antar_rekening_sendiri", "RINA WULANDARI"), labels)
        plain = (await read(BSI_SELF, rules, user_name="BUDI SANTOSO")).parsed.doc   # bukan user: aturan boleh
        self.assertEqual(plain.flow, "keluar")
        reads, guarded = 0, 0
        for entry in SWEEP:
            key = own_key(entry["lines"])
            if key is None:
                continue
            first = (await read(entry["lines"], user_name=entry.get("user_name"))).parsed.doc
            if first.doc_type != "transfer":
                continue
            labels = realistic_labels(entry["lines"])
            for user in dict.fromkeys((entry.get("user_name"), first.counterparty.name)):
                base = (await read(entry["lines"], user_name=user)).parsed.doc
                if base.flow == "keluar":
                    continue
                guarded += 1
                for label in labels:
                    got = (await read(entry["lines"], {key: rule([label], [label], [label])}, user_name=user)).parsed.doc
                    reads += 1
                    with self.subTest(entry["id"], user=user, label=label):
                        self.assertEqual(got.flow, base.flow)
        self.assertGreater(guarded, 40)
        self.assertGreater(reads, 1500)

    async def test_rules_never_bypass_status_blocks(self):
        """Setiap daftar gagal/pending di sapuan (termasuk bentuk §9.1 pre-flight), kedua saklar, dengan aturan SEMUA
        jenis untuk SEMUA aplikasi, termasuk aturan jahat (label "status", label = teks baris gagal, kata status): status,
        cek status, semua cek blokir, arah uang selain keluar, dan `check_recordable` sama dengan tanpa aturan."""
        lists, changed, blocked = tagged("failed", "pending", "store_void", "store_pending"), 0, 0
        self.assertGreaterEqual(len(lists), 150)
        for entry in lists:
            rules = hostile_rules(entry["lines"])
            for switch, enabled in SWITCHES:
                with self.subTest(entry["id"], switch=switch):
                    plain = await read(entry["lines"], enabled=enabled, user_name=entry.get("user_name"))
                    got = await read(entry["lines"], rules, enabled=enabled, user_name=entry.get("user_name"))
                    self.assertEqual(status_view(got), status_view(plain))
                    outcome = await recordable(got.parsed.doc.to_json())
                    self.assertEqual(outcome, await recordable(plain.parsed.doc.to_json()))
                    blocked += outcome == record.MSG_BLOCKED
                    changed += full(got) != full(plain)
        self.assertGreater(blocked, 250)  # bukti gagal (kedua saklar) tetap MSG_BLOCKED
        self.assertGreater(changed, 20)   # aturan jahat benar-benar dipakai (nominal/nama/tanggal berubah)

    async def test_status_flow_and_checks_get_a_context_without_rules(self):
        seen = {}

        def spy(name, fn):
            def wrapped(parsed, context):
                seen.setdefault(name, []).append(context.rules)
                return fn(parsed, context)
            return wrapped

        with patch.object(cross_checks, "common_checks", spy("checks", cross_checks.common_checks)), \
                patch.object(cross_checks, "apply_flow", spy("flow", cross_checks.apply_flow)):
            for lines in (GOPAY_MISREAD, JAGO_BILL, kotak_sapuan.load_lines()[0]["lines"]):
                for enabled in (True, False):
                    await read(lines, hostile_rules(lines), enabled=enabled)
        self.assertEqual(set(seen), {"checks", "flow"})
        self.assertTrue(all(rules == {} for calls in seen.values() for rules in calls))

    async def test_status_reads_the_original_profile(self):
        """Status bukti dibaca dengan profil aplikasi ASLI (`PROFILES`), bukan profil berlabel aturan: aturan tidak bisa
        sampai ke pembaca status walau pembaca status kelak memakai label profil."""
        seen = []
        real = pc.read_proof_status

        def spy(lines, profile=None):
            seen.append(profile)
            return real(lines, profile)

        with patch.object(pc, "read_proof_status", spy):
            for lines in (GOPAY_MISREAD, GOPAY_QRIS, GOPAY_FEE):
                await read(lines, {"gopay": rule(HOSTILE_BASE, HOSTILE_BASE, HOSTILE_BASE)})
        gopay = next(p for p in PROFILES if p.key == "gopay")
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(profile is gopay for profile in seen), seen)

    async def test_store_reader_and_switch_off_get_no_rules(self):
        calls = []
        for reader in (registry._STRUK_BELANJA, registry._UNKNOWN, *registry._PROOF_READERS):
            async def spy(doc, context, *, _real=reader.parse, _name=reader.name):
                calls.append((_name, context.rules))
                return await _real(doc, context)

            self.enterContext(patch.object(reader, "parse", spy))
        rules = {"gopay": rule(["jumlah kirim uang"]), "jago": rule(["dibayar"])}
        store, seen = tagged("store")[0]["lines"], set()
        for lines in (store, GOPAY_MISREAD, GOPAY_QRIS, JAGO_BILL):
            for enabled in (True, False):
                calls.clear()
                await read(lines, rules, enabled=enabled)
                [(name, got)] = calls
                seen.add((name, enabled))
                with self.subTest(name=name, enabled=enabled):
                    self.assertEqual(got, rules if enabled and name != "struk_belanja" else {})
        self.assertLessEqual({("struk_belanja", True), ("struk_belanja", False), ("tidak_dikenali", True),
                              ("tidak_dikenali", False), ("transfer.umum", True), ("qris.umum", True)}, seen)


# ── bentuk aturan (murni) ───────────────────────────────────────────────────

class LearnedShapeTests(unittest.TestCase):
    def test_learned_for_reads_only_its_key_and_sanitises(self):
        rules = {"gopay": {"label_total": ["Jumlah  Kirim Uang", "jumlah kirim uang", "", 5, None, "x" * 41],
                           "label_pihak": "nama toko", "label_tanggal": ["waktu selesai"], "arah": ["top_up"]},
                 "dana": rule(["total"])}
        self.assertEqual(learned_for(rules, "gopay"), Learned(["jumlah kirim uang"], [], ["waktu selesai"]))
        self.assertEqual(learned_for(rules, "ovo"), Learned())
        for broken in (None, {}, [], "gopay", {"gopay": ["total"]}, {"gopay": None}):
            self.assertEqual(learned_for(broken, "gopay"), Learned())
        self.assertEqual(learned_for(rules, None), Learned())
        self.assertFalse(Learned())
        self.assertIs(belajar.learned_for, learned_for)
        self.assertEqual((profiles.RULE_TOTAL, profiles.RULE_PARTY, profiles.RULE_DATE), belajar.KINDS)

    def test_with_learned_prepends_party_and_dates_and_keeps_the_profile(self):
        gopay = next(p for p in PROFILES if p.key == "gopay")
        self.assertIs(with_learned(gopay, Learned()), gopay)
        self.assertIsNone(with_learned(None, Learned()))
        lp = with_learned(gopay, Learned(["dibayar"], ["nama toko"], ["waktu selesai"]))
        self.assertIsNot(lp, gopay)
        self.assertEqual((lp.key, lp.label, lp.markers, lp.party_on_top), (gopay.key, gopay.label, gopay.markers, False))
        self.assertEqual(profiles.labels_for(lp, "merchant")[:2], ["nama toko", "merchant name"])
        self.assertEqual(profiles.labels_for(lp, "paid_at"), ["waktu selesai"])
        self.assertEqual(profiles.labels_for(lp, "sender"), profiles.labels_for(gopay, "sender"))
        self.assertEqual(profiles.labels_for(lp, "amount"), profiles.labels_for(gopay, "amount"))   # K6
        self.assertEqual(gopay.labels, {})   # profil asli tidak berubah
        shopee = next(p for p in PROFILES if p.key == "shopeepay")
        self.assertEqual(with_learned(shopee, Learned([], ["nama toko"], [])).labels["merchant"], ["nama toko", "kirim ke"])
        empty = with_learned(None, Learned([], ["nama toko"], []))
        self.assertEqual((empty.key, empty.markers, empty.labels), ("", [], {"merchant": ["nama toko"]}))
        self.assertEqual(profiles.labels_for(None, "paid_at"), [])

    def test_learned_values_must_follow_the_whole_label(self):
        lines = ["• Total Bayar: Rp11.000", "Jumlah Kirim Uang", "Rp10.000", "Waktu Selesai", "Status", "26 Okt 2026",
                 "Tanggal Bayar 25 Okt 2026 10:00", "Jumlah", "Biaya Rp1.000"]
        self.assertEqual(learned_amount(lines, ["total bayar"]), 11000)
        self.assertEqual(learned_amount(lines, ["jumlah kirim uang"]), 10000)
        self.assertIsNone(learned_amount(lines, ["total"]))
        self.assertIsNone(learned_amount(lines, ["jumlah"]))      # baris di bawahnya bukan nominal
        self.assertIsNone(learned_amount(lines, []))
        self.assertEqual(learned_amount(lines, ["jumlah", "jumlah kirim uang"]), 10000)
        self.assertEqual(learned_datetime(lines, ["tanggal bayar"]), datetime(2026, 10, 25, 10, 0, tzinfo=WIB))
        self.assertIsNone(learned_datetime(lines, ["tanggal"]))
        self.assertIsNone(learned_datetime(lines, ["waktu selesai"]))   # baris di bawahnya bukan tanggal
        self.assertEqual(learned_datetime(lines, ["status"]), datetime(2026, 10, 26, tzinfo=WIB))
        self.assertIsNone(learned_datetime(lines, []))
        # Nominal PERTAMA di nilai (seperti suara kerangka), bukan yang terbesar.
        self.assertEqual(learned_amount(["Dibayar Rp15.000 Rp20.000"], ["dibayar"]), 15000)
        # Jam di baris sesudah tanggal (sama dengan read_paid_at); baris lain sesudahnya bukan jam.
        self.assertEqual(learned_datetime(["Waktu Selesai 26 Okt 2026", "00:01 WIB"], ["waktu selesai"]),
                         datetime(2026, 10, 26, 0, 1, tzinfo=WIB))
        self.assertEqual(learned_datetime(["Waktu Selesai", "26 Okt 2026", "09.31"], ["waktu selesai"]),
                         datetime(2026, 10, 26, 9, 31, tzinfo=WIB))
        self.assertEqual(learned_datetime(["Waktu Selesai 26 Okt 2026 08:00", "09:31"], ["waktu selesai"]),
                         datetime(2026, 10, 26, 8, 0, tzinfo=WIB))
        self.assertEqual(learned_datetime(["Waktu Selesai 26 Okt 2026", "Rp10.000", "25:00"], ["waktu selesai"]),
                         datetime(2026, 10, 26, tzinfo=WIB))
        self.assertEqual(learned_datetime(["Waktu Selesai 26 Okt 2026", "25:00"], ["waktu selesai"]),
                         datetime(2026, 10, 26, tzinfo=WIB))

    def test_learned_party_label_must_be_the_whole_label(self):
        """Review L3 m-2: label penerima aturan hanya membaca baris yang labelnya persis label itu."""
        gopay = next(p for p in PROFILES if p.key == "gopay")
        lines = ["Tujuan Transfer Lainnya", "Tujuan BUDI SANTOSO", "Tujuan: Transfer Ke Teman", "Tujuan:Toko Maju",
                 "Ke TOKO MAJU", "Ke Rekening BCA", "Tujuan", "SITI AMINAH"]
        masked, whole = profiles.mask_partial_labels(lines, ["tujuan", "ke"], kerangka.LABEL_WORDS)
        self.assertTrue(whole)
        self.assertEqual(masked, ["", "Tujuan BUDI SANTOSO", "Tujuan: Transfer Ke Teman", "Tujuan:Toko Maju",
                                  "Ke TOKO MAJU", "", "Tujuan", "SITI AMINAH"])
        self.assertIsNone(profiles.learned_party(["Tujuan Transfer Lainnya", "Ke Rekening BCA"], gopay, ["tujuan", "ke"]))
        self.assertIsNone(profiles.learned_party(lines, gopay, []))
        got = profiles.learned_party(["Tujuan Transfer Lainnya", "Tujuan BUDI SANTOSO"], gopay, ["tujuan"])
        self.assertEqual(got[0], ["", "Tujuan BUDI SANTOSO"])
        self.assertEqual((got[1].key, profiles.labels_for(got[1], "merchant")[0], "paid_at" in got[1].labels),
                         ("gopay", "tujuan", False))


# ── cache aturan yang disetujui ─────────────────────────────────────────────

if HAS_AIOSQLITE:
    from app.tests.test_kotak_belajar import DbBase, postgres_abort
else:   # pragma: no cover
    DbBase = unittest.IsolatedAsyncioTestCase


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class ApprovedRulesCacheTests(DbBase):
    T0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        belajar.invalidate_rules_cache()
        self.addCleanup(belajar.invalidate_rules_cache)
        self.now = 1000.0
        patcher = patch.object(belajar, "_clock", lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def add(self, kind, key, value, users=2, status="disetujui", minutes=0):
        async with self.Session() as db:
            db.add(ProofRule(kind=kind, rule_key=key, value=value, users=users, households=1, status=status,
                             decided_at=self.T0 + timedelta(minutes=minutes) if status != "menunggu" else None))
            await db.commit()

    async def approved(self):
        async with self.Session() as db:
            return await belajar.approved_rules(db)

    async def test_only_approved_rules_ordered_by_users_then_decision(self):
        await self.add("label_total", "gopay", "dibayar", users=2, minutes=0)
        await self.add("label_total", "gopay", "jumlah kirim uang", users=3, minutes=5)
        await self.add("label_total", "gopay", "total kirim", users=3, minutes=1)
        await self.add("label_pihak", "jago", "nama toko", users=2)
        await self.add("label_tanggal", "jago", "waktu selesai", users=4)
        await self.add("label_pihak", "jago", "penerima", users=2)      # sama users dan waktu: urut teks
        await self.add("label_pihak", "jago", "kepada", users=2)
        for status in ("menunggu", "ditolak", "dicabut"):
            await self.add("label_total", "dana", f"total {status}", status=status)
        await self.add("arah", "gopay", "top up")   # jenis tahap 2: tidak dimuat
        self.assertEqual(await self.approved(), {
            "gopay": rule(["total kirim", "jumlah kirim uang", "dibayar"]),
            "jago": rule([], ["kepada", "nama toko", "penerima"], ["waktu selesai"]),
        })

    async def test_rule_cache_expires_and_invalidates(self):
        await self.add("label_total", "gopay", "dibayar")
        first = await self.approved()
        self.assertEqual(first, {"gopay": rule(["dibayar"])})
        first["gopay"]["label_total"].append("dirusak pemanggil")   # salinan: cache tidak ikut berubah
        await self.add("label_total", "gopay", "jumlah kirim uang", users=3)
        self.now += RULE_CACHE_S - 1
        cached = await self.approved()
        self.assertEqual(cached, {"gopay": rule(["dibayar"])})                    # masih dari cache
        cached["gopay"]["label_total"].clear()                                      # salinan juga dari cache
        self.assertEqual(await self.approved(), {"gopay": rule(["dibayar"])})
        self.now += 1                                                              # tepat 5 menit: dimuat ulang
        self.assertEqual(await self.approved(), {"gopay": rule(["jumlah kirim uang", "dibayar"])})
        await self.add("label_pihak", "gopay", "nama toko")
        self.assertEqual((await self.approved())["gopay"]["label_pihak"], [])
        belajar.invalidate_rules_cache()                                           # keputusan admin: segera
        self.assertEqual((await self.approved())["gopay"]["label_pihak"], ["nama toko"])
        # Tanpa aturan disetujui pun di-cache (satu kueri per 5 menit).
        belajar.invalidate_rules_cache()
        db = _RowsDb([])
        self.assertEqual(await belajar.approved_rules(db), {})
        self.assertEqual(await belajar.approved_rules(db), {})
        self.assertEqual(db.calls, 1)

    async def test_invalidate_during_a_load_is_not_overwritten(self):
        await self.add("label_total", "gopay", "dibayar")

        class Racing(_RowsDb):
            async def execute(self, stmt):
                belajar.invalidate_rules_cache()   # keputusan admin selagi kueri berjalan
                return await super().execute(stmt)

        self.assertEqual(await belajar.approved_rules(Racing([("gopay", "label_total", "lama")])),
                         {"gopay": rule(["lama"])})
        self.assertEqual(await self.approved(), {"gopay": rule(["dibayar"])})   # hasil lama tidak disimpan

    async def test_database_failure_gives_no_rules_and_a_warning(self):
        await self.add("label_total", "gopay", "dibayar")
        with self.assertLogs(BELAJAR_LOG, "WARNING") as logs:
            self.assertEqual(await belajar.approved_rules(_RowsDb(error=ConnectionError("db putus"))), {})
        self.assertIn("tanpa aturan", logs.output[0])
        self.assertEqual(await self.approved(), {"gopay": rule(["dibayar"])})   # galat tidak disimpan di cache
        # Seperti Postgres: galat di SAVEPOINT sendiri, sesi pemanggil tetap bisa dipakai.
        belajar.invalidate_rules_cache()
        with postgres_abort(self.engine, "SELECT proof_rules") as state:
            async with self.Session() as db:
                with self.assertLogs(BELAJAR_LOG, "WARNING"):
                    self.assertEqual(await belajar.approved_rules(db), {})
                self.assertEqual((await db.execute(select(func.count()).select_from(ProofRule))).scalar_one(), 1)
        self.assertEqual(state["left"], 0)


# ── worker ──────────────────────────────────────────────────────────────────

if HAS_AIOSQLITE:
    from app.tests import test_kotak_worker as tw

    def setUpModule():
        tw.setUpModule()

    def tearDownModule():
        tw.tearDownModule()

    WorkerBase = tw.WorkerBase
else:   # pragma: no cover
    WorkerBase = unittest.IsolatedAsyncioTestCase


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class WorkerRulesTests(WorkerBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        belajar.invalidate_rules_cache()
        self.addCleanup(belajar.invalidate_rules_cache)

    async def approve(self, key, kind, value):
        async with self.Session() as db:
            db.add(ProofRule(kind=kind, rule_key=key, value=value, users=2, households=2, status="disetujui",
                             decided_at=tw.NOW))
            await db.commit()

    async def test_worker_reads_with_approved_rules(self):
        await self.approve("gopay", "label_total", "jumlah kirim uang")
        item = await self.item(text="x")
        self.assertEqual(await self.process(item, GOPAY_MISREAD), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.document["amounts"]["total"], got.document["confidence"]["total"]),
                         ("transfer", 12500, "tinggi"))
        self.assertEqual(got.layout["key"], "gopay")

    async def test_switch_off_loads_no_rules(self):
        await self.approve("gopay", "label_total", "jumlah kirim uang")
        spy = AsyncMock(wraps=belajar.approved_rules)
        with patch.object(belajar, "approved_rules", spy):
            item = await self.item(text="x")
            self.assertEqual(await self.process(item, GOPAY_MISREAD, proofs_enabled=False), "siap")
        spy.assert_not_awaited()
        got = await self.get(item.id)
        self.assertNotEqual(got.document["amounts"]["total"], 12500)

    async def test_rule_loading_failure_reads_without_rules(self):
        await self.approve("gopay", "label_total", "jumlah kirim uang")
        with postgres_abort(self.engine, "SELECT proof_rules") as state, \
                self.assertLogs(BELAJAR_LOG, "WARNING"):
            item = await self.item(text="x")
            self.assertEqual(await self.process(item, GOPAY_MISREAD), "siap")
        self.assertEqual(state["left"], 0)
        got = await self.get(item.id)
        self.assertEqual((got.document["amounts"]["total"], got.document["confidence"]["total"]), (50000, "sedang"))


if __name__ == "__main__":
    unittest.main()
