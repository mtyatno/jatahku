"""Kunci logo, suara `logo`, dan "Aplikasi apa ini?" (belajar lintas user tahap 2, Task M2a; spec 2026-11-01 §2 baris
`logo`; pre-flight A16 §3, K6, K8, K13, G9, G10). Kandidat kunci logo ketat (bukan nama orang/merchant), suara `logo`
sekali per item dengan nilai kunci profil atau "baru", suara ditolak bila kata logonya nama yang dikenal, suara label
untuk kunci logo hanya sesudah aturan `logo`-nya disetujui, tanda `ask_app`/`app_logo`, dan rute
`POST /kotak-struk/{item_id}/aplikasi`. Hanya nama dan angka karangan. SQLite in-memory.
Run: python -m unittest app.tests.test_kotak_logo -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import json
import unittest
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import func, select, text

from app.models.models import Envelope, ProofRule, ProofRuleVote, ReceiptScan, Transaction
from app.services.kotak_struk import belajar, kerangka, merchants, record
from app.services.kotak_struk.belajar import Vote, votes_for
from app.services.kotak_struk.config import APP_NEW, KEY_MAX
from app.services.kotak_struk.document import Counterparty, DokumenBayar
from app.services.kotak_struk.extract import KIND_IMAGE, TextDoc
from app.services.kotak_struk.kerangka import build_layout, logo_word, rule_key
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import ParseContext, Secrets
from app.services.kotak_struk.readers.profiles import PROFILES, Learned, learned_profile
from app.services.kotak_struk.registry import read_document
from app.tests.test_kotak_admin_aturan import AdminRulesBase
from app.tests.test_kotak_api import CORPUS, HAS_AIOSQLITE, ApiBase
from app.tests.test_kotak_belajar import DbBase, doc, final, layout, nominal

SWEEP = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "sweep_lines.json").read_text(encoding="utf-8"))
TODAY = date(2026, 11, 1)
PROFILE_KEYS = [p.key for p in PROFILES]
# Bukti aplikasi tak berprofil rekaan ("NEWPAY"): terbaca `tidak_dikenali` dengan kunci kerangka `logo:newpay`.
NEWPAY = ["NEWPAY", "Pembayaran Berhasil", "Nominal Rp50.000", "31/10/2026 10:00"]
LOGO_LAY = layout(nominal(2, "nominal", 50000), key="logo:newpay")
HOSTILE = {"label_total": ["nominal", "total", "jumlah", "total bayar", "dibayar"],
           "label_pihak": ["penerima", "ke", "merchant", "nama merchant", "kepada"],
           "label_tanggal": ["tanggal", "waktu", "waktu transaksi"]}


def key_of(lines, forbidden=frozenset()):
    return rule_key(pc.clean_lines(lines), None, forbidden_words=set(forbidden))


def unknown_doc(name=None):
    return DokumenBayar(doc_type="tidak_dikenali", counterparty=Counterparty(name=name))


class LogoKeyTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(merchants, "_warned_no_key", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_logo_keys_are_on(self):
        self.assertIs(kerangka.LOGO_KEYS, True)

    def test_logo_key_never_from_person_or_merchant_name(self):   # Review Focus 6
        with_names = [["09:41", "Siti Aminah", "Kirim Uang Berhasil", "Nominal Rp50.000"],
                      ["10:57 LTE", "Wahyu Nugroho", "Rp50.000", "Berhasil"],
                      ["Warung Sederhana", "Pembayaran Berhasil", "Nominal Rp15.000"],
                      ["Toko Sinar", "Pembayaran Berhasil", "Nominal Rp15.000"]]
        for lines in with_names:
            with self.subTest(lines=lines):
                self.assertIsNone(key_of(lines))
                self.assertIsNone(build_layout(lines, unknown_doc(), Secrets(), user_name=None))
        self.assertEqual(key_of(["NEWPAY", "Pembayaran Berhasil", "Total Rp50.000"]), "logo:newpay")
        # Dua kata hanya bersama kata logo/penyedia ("Bank Raya"); kata pendamping saja bukan nama aplikasi.
        self.assertEqual(key_of(["Bank Raya", "Transfer Berhasil", "Nominal Rp50.000"]), "logo:bank raya")
        self.assertEqual(key_of(["Kilat Syariah", "Rp50.000"]), "logo:kilat syariah")
        for first in ("Bank Digital", "Mobile Banking", "Mobile", "Bank", "Bank Tujuan", "Siti Bank Raya"):
            with self.subTest(first=first):
                self.assertIsNone(key_of([first, "Pembayaran Berhasil", "Nominal Rp50.000"]))
        # Nama satu kata lolos bentuk kandidat, tetapi tidak pernah bila itu nama yang dikenal di bukti itu (kerangka),
        # dan suaranya ditolak (`learn_app_choice`, AppChoiceTests).
        self.assertEqual(key_of(["Bambang", "Pembayaran Berhasil"]), "logo:bambang")   # sisa, lihat tes residual
        self.assertIsNone(key_of(["Bambang", "Pembayaran Berhasil"], {"bambang"}))
        lay = build_layout(["Bambang", "Pembayaran Berhasil", "Nominal Rp10.000"], unknown_doc(name="Bambang"),
                           Secrets(), user_name=None)
        self.assertIsNone(lay)
        lay = build_layout(["Bambang", "Pembayaran Berhasil", "Nominal Rp10.000"], unknown_doc(), Secrets(),
                           user_name="Bambang Wijaya")
        self.assertIsNone(lay)

    def test_one_word_candidate_followed_by_amount_or_date_is_a_name(self):
        # Review M2a temuan 1, putusan pengendali (b): logo aplikasi diikuti judul; nama penerima besar diikuti
        # nominalnya atau tanggal. Bilah status di antaranya dilewati.
        self.assertIsNone(key_of(["Andi", "Rp50.000", "Transfer Berhasil"]))
        self.assertIsNone(key_of(["Siti", "12 Okt 2026", "Rp50.000"]))
        # Cabang tanggal sendiri (tanpa nominal di baris berikutnya; fix round 2 R1-1).
        self.assertIsNone(key_of(["Siti", "12 Oktober 2026 10:00", "Transfer Berhasil"]))
        self.assertIsNone(key_of(["Siti", "Selasa, 12 Okt 2026", "Transfer Berhasil"]))
        self.assertIsNone(key_of(["Siti", "09:41", "LTE", "Rp50.000", "Transfer Berhasil"]))
        self.assertIsNone(key_of(["09:41", "Andi", "Nominal Rp50.000"]))
        self.assertEqual(key_of(["NEWPAY", "Pembayaran Berhasil", "Total Rp50.000"]), "logo:newpay")
        self.assertEqual(key_of(["NEWPAY", "Detail Transaksi", "Rp50.000"]), "logo:newpay")
        self.assertEqual(key_of(["NEWPAY"]), "logo:newpay")   # tanpa baris berikutnya: tidak ada tanda nama
        # Harga yang diterima: logo aplikasi satu kata yang langsung diikuti nominal tidak berkunci (tanpa kerangka,
        # tanpa pertanyaan "Aplikasi apa ini?").
        self.assertIsNone(key_of(["NEWPAY", "Rp50.000", "Pembayaran Berhasil"]))
        # Kandidat dua kata (dengan kata logo/penyedia) tetap aturan lama.
        self.assertEqual(key_of(["Bank Raya", "Rp50.000", "Transfer Berhasil"]), "logo:bank raya")

    def test_residual_first_name_before_title_is_a_key_masked_in_admin(self):
        # Sisa yang diterima (review M2a temuan 1): nama depan satu kata yang diikuti baris judul tetap menjadi kunci
        # logo bila pembaca tidak mengenalinya sebagai nama (pihak lawan/pengirim/merchant/user). Pertahanannya: suara
        # ditolak bila kata itu nama yang dikenal (`learn_app_choice`), ambang 2 user, persetujuan pemilik, dan
        # penyamaran kunci logo di tab Suara Admin (M3d, K15) yang menjadi GERBANG RILIS tahap 2. Juga nama dua baris:
        # nama depan, lalu nama belakang di baris sendiri, lalu nominal ("Andi" / "Saputra" / "Rp50.000"): baris
        # berikutnya teks, bukan nominal, jadi "Andi" tetap menjadi kunci.
        self.assertEqual(key_of(["Andi", "Transfer Berhasil", "Rp50.000"]), "logo:andi")
        self.assertEqual(key_of(["Andi", "Saputra", "Rp50.000"]), "logo:andi")
        self.assertIsNone(key_of(["Andi", "Transfer Berhasil", "Rp50.000"], {"andi"}))

    def test_logo_word(self):
        self.assertEqual(logo_word("logo:newpay"), "newpay")
        self.assertEqual(logo_word("logo:bank raya"), "bank raya")
        for key in (None, 5, "gopay", "logo:", "logo:ab", "logo:NEWPAY", "logo:new pay", "logo:siti aminah",
                    "logo:bank  raya", "logo: newpay", "logo:newpay ", "logo:new1pay", "logo:mobile", "logo:berhasil",
                    "logo:penerima", "logo:a b c", "logo:" + "x" * (KEY_MAX - 4), ["logo:newpay"]):
            with self.subTest(key=key):
                self.assertIsNone(logo_word(key))

    def test_qris_without_profile_never_gets_a_logo_read_key(self):
        lines = pc.clean_lines(NEWPAY)
        rules = {"logo:newpay": dict(HOSTILE)}
        self.assertEqual(learned_profile(lines, None, rules), (Learned(), None))
        learned, _ = learned_profile(lines, None, rules, allow_logo=True)
        self.assertEqual(learned.total, HOSTILE["label_total"])

    def test_logo_key_only_for_unknown_documents(self):
        for doc_type in ("qris", "transfer"):
            with self.subTest(doc_type=doc_type):
                self.assertIsNone(build_layout(NEWPAY, DokumenBayar(doc_type=doc_type), Secrets(), user_name=None))
        lay = build_layout(NEWPAY, unknown_doc(), Secrets(), user_name=None)
        self.assertEqual(lay["key"], "logo:newpay")
        self.assertNotIn(0, [e["i"] for e in lay["lines"]])   # baris logo sendiri bukan entri


class LogoReadKeyTests(unittest.IsolatedAsyncioTestCase):
    """Saat membaca, hanya `UnknownReader` berkunci logo: aturan label dengan kunci logo (bahkan jahat) tidak pernah
    mengubah hasil pembaca QRIS/transfer pada daftar sapuan (pre-flight A16 §3: QRIS/transfer tanpa profil sering
    diawali nama merchant)."""

    async def asyncSetUp(self):
        # Pembaca sungguhan di loop; mode debug asyncio mengeluh bila satu langkah > 0,1 detik.
        asyncio.get_running_loop().slow_callback_duration = 5.0
        patcher = patch.object(merchants, "_warned_no_key", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_qris_and_transfer_readers_ignore_logo_keyed_rules(self):
        compared = 0
        # Rekaan: QRIS/transfer tanpa profil aplikasi dengan baris teratas yang lolos kandidat logo; hari ini cashback
        # "Rp2.000" terbaca total QRIS. Aturan `label_total` "dibayar" berkunci logo akan mengubahnya bila dipakai.
        invented = [
            {"id": "rekaan-qris", "lines": ["KILATPAY", "Pembayaran Berhasil", "QRIS", "Nama Merchant WARUNG MAJU",
                                            "NMID ID1234567890", "Cashback", "Rp2.000", "Dibayar", "Rp15.000",
                                            "Waktu Transaksi 26 Okt 2026 08:12"]},
            {"id": "rekaan-transfer", "lines": ["KILATPAY", "Transfer Berhasil", "Penerima", "RINA HARTONO",
                                                "Rekening 1234567890", "Biaya Rp2.500", "Jumlah", "Rp50.000",
                                                "Dibayar", "Rp52.000", "Tanggal 26 Okt 2026 08:12"]},
        ]
        for case in [*invented, *SWEEP]:
            key = key_of(case["lines"])
            if key is None or not key.startswith("logo:"):
                continue
            for enabled in (False, True):
                plain = await read_document(TextDoc(lines=list(case["lines"]), kind=KIND_IMAGE),
                                            ParseContext(today=TODAY, user_name=case.get("user_name")),
                                            proofs_enabled=enabled)
                if plain.parsed.doc.doc_type not in ("qris", "transfer"):
                    continue
                # Juga dengan aturan `logo` yang disetujui untuk kunci itu (M2b): hanya `UnknownReader` memakainya.
                for extra in ({}, {"logo": ["baru"]}, {"logo": ["bsi"]}):
                    ruled = await read_document(TextDoc(lines=list(case["lines"]), kind=KIND_IMAGE),
                                                ParseContext(today=TODAY, user_name=case.get("user_name"),
                                                             rules={key: {**HOSTILE, **extra}}),
                                                proofs_enabled=enabled)
                    compared += 1
                    with self.subTest(id=case["id"], on=enabled, extra=extra):
                        self.assertEqual(ruled.reader, plain.reader)
                        self.assertEqual(ruled.parsed.doc.to_json(), plain.parsed.doc.to_json())
        self.assertGreater(compared, 5)


async def read_doc(lines, rules=None, *, enabled=True, user_name=None):
    ctx = ParseContext(today=TODAY, user_name=user_name, **({"rules": rules} if rules is not None else {}))
    return await read_document(TextDoc(lines=list(lines), kind=KIND_IMAGE), ctx, proofs_enabled=enabled)


def logo_rule(value, **labels):
    return {"logo": [value] if isinstance(value, str) else list(value), **labels}


# NEWPAY dengan dua tanggal: tanpa aturan total Rp50.000 berkeyakinan `rendah` (nominal Rp terbesar) dan tanpa tanggal
# (dua tanggal tercetak); aturan "nominal"/"tanggal" membacanya `tinggi` dan tanggal 30. Baris Rp kedua (mis. biaya)
# membuat teks ini dibaca pembaca struk belanja, jadi tidak dipakai di sini.
NEWPAY_DATES = ["NEWPAY", "Pembayaran Berhasil", "Nominal Rp50.000", "Tanggal 30/10/2026 09:00", "31/10/2026 10:00"]
RULE_LABELS = {"label_total": ["nominal"], "label_pihak": [], "label_tanggal": ["tanggal"]}


class UnknownReaderLogoRulesTests(unittest.IsolatedAsyncioTestCase):
    """Aturan `logo` yang disetujui (Task M2b; pre-flight A16 K7, G11) hanya memberi `UnknownReader` penerbit
    (`doc.issuer`) dan kunci label belajarnya. Status, pihak, referensi, perutean, dan keyakinan tanpa label aturan sama
    persis dengan tanpa aturan."""

    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 5.0
        patcher = patch.object(merchants, "_warned_no_key", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def same_but_issuer(self, got, plain, issuer):
        self.assertEqual(got.reader, plain.reader)
        self.assertEqual(got.parsed.doc.issuer, issuer)
        self.assertEqual({**got.parsed.doc.to_json(), "issuer": None}, plain.parsed.doc.to_json())
        self.assertEqual(vars(got.parsed.secrets), vars(plain.parsed.secrets))
        self.assertEqual([c.as_dict() for c in got.checks], [c.as_dict() for c in plain.checks])

    async def test_approved_logo_maps_unknown_app_to_profile_issuer(self):
        # Rencana memakai "Total Rp50.000"; label "Total" membuat teks ini dibaca pembaca struk belanja (tanpa aturan
        # pun), jadi di sini "Nominal Rp50.000" (NEWPAY), yang memang jatuh ke pembaca tidak dikenali.
        rules = {"logo:newpay": {"logo": ["bsi"]}}
        d = (await read_doc(NEWPAY, rules)).parsed.doc
        self.assertEqual((d.doc_type, d.issuer), ("tidak_dikenali", "bsi"))
        plain = await read_doc(NEWPAY)
        self.assertIsNone(plain.parsed.doc.issuer)
        self.same_but_issuer(await read_doc(NEWPAY, rules), plain, "bsi")
        # Nilai pertama yang sah (urut pendukung); nilai rusak dilewati; bentuk rusak = tanpa aturan.
        for values, want in ((["jago", "bsi"], "jago"), (["siti", "BSI", "seabank"], "seabank"), (["siti"], None),
                             ([], None), (["baru", "bsi"], None)):
            with self.subTest(values=values):
                self.same_but_issuer(await read_doc(NEWPAY, {"logo:newpay": logo_rule(values)}), plain, want)
        for broken in ({"logo:newpay": {"logo": "bsi"}}, {"logo:newpay": ["bsi"]}, {"logo:newpay": {"logo": [7]}},
                       {"logo:kilatpay": {"logo": ["bsi"]}}, {"newpay": {"logo": ["bsi"]}}, {"bsi": {"logo": ["jago"]}}):
            with self.subTest(broken=broken):
                self.same_but_issuer(await read_doc(NEWPAY, broken), plain, None)
        # Saklar bukti mati: aturan tidak sampai ke pembaca.
        off = await read_doc(NEWPAY, enabled=False)
        self.same_but_issuer(await read_doc(NEWPAY, rules, enabled=False), off, None)

    async def test_mapped_profile_gives_labels_but_never_status_party_or_refs(self):
        plain = await read_doc(NEWPAY_DATES)
        self.assertEqual((plain.parsed.doc.doc_type, plain.parsed.doc.amounts.total, plain.parsed.doc.confidence,
                          plain.parsed.doc.paid_at), ("tidak_dikenali", 50000, {"total": "rendah"}, None))
        # Label dibaca dengan kunci profil P, bukan kunci logo.
        got = await read_doc(NEWPAY_DATES, {"logo:newpay": logo_rule("jago"), "jago": dict(RULE_LABELS)})
        d = got.parsed.doc
        self.assertEqual((d.issuer, d.amounts.total, d.confidence["total"]), ("jago", 50000, "tinggi"))
        self.assertEqual((d.paid_at.day, d.confidence["paid_at"]), (30, "tinggi"))
        self.assertEqual((d.doc_type, d.status, got.reader), (plain.parsed.doc.doc_type, plain.parsed.doc.status,
                                                               plain.reader))
        # Label berkunci logo tidak dipakai bila logonya dipetakan ke profil; label profil lain juga tidak.
        for rules in ({"logo:newpay": logo_rule("jago", **RULE_LABELS)},
                      {"logo:newpay": logo_rule("jago"), "bsi": dict(RULE_LABELS)}):
            with self.subTest(rules=rules):
                self.same_but_issuer(await read_doc(NEWPAY_DATES, rules), plain, "jago")
        # Profil Jago punya kalimat selesai (status), pihak di atas nominal, dan label referensi "id transaksi": tidak
        # satu pun dipakai untuk bukti tak dikenal yang dipetakan ke Jago (K7).
        jago_like = ["NEWPAY", "Pembayaran", "WARUNG CONTOH", "Rp50.000", "ID Transaksi", "87654321",
                     "Nomor Referensi 12345678", "Resi ini merupakan bukti transaksi yang sah"]
        plain = await read_doc(jago_like)
        self.assertEqual((plain.parsed.doc.doc_type, plain.parsed.doc.status), ("tidak_dikenali", "tidak_diketahui"))
        for labels in ({}, {"label_pihak": ["id transaksi", "nomor referensi"], "label_tanggal": ["status"]}):
            with self.subTest(labels=labels):
                self.same_but_issuer(await read_doc(jago_like, {"logo:newpay": logo_rule("jago"), "jago": labels}),
                                     plain, "jago")
        # Penyelamatan LLM (dibaca sebagai struk belanja): tanpa penerbit dari aturan logo, sama dengan tanpa aturan.
        llm = AsyncMock(return_value={"merchant": "TOKO", "date": None, "total": 99000})
        extra = {"image": b"img", "content_type": "image/jpeg", "llm": llm}
        saved = await read_document(TextDoc(lines=list(NEWPAY), kind=KIND_IMAGE),
                                    ParseContext(today=TODAY, **extra), proofs_enabled=True)
        self.assertEqual(saved.parsed.doc.doc_type, "struk_belanja")
        ruled = await read_document(TextDoc(lines=list(NEWPAY), kind=KIND_IMAGE),
                                    ParseContext(today=TODAY, rules={"logo:newpay": logo_rule("bsi")}, **extra),
                                    proofs_enabled=True)
        self.same_but_issuer(ruled, saved, None)
        # Bukti tak dikenal yang profilnya terdeteksi tidak pernah memakai aturan logo (kunci aturannya kunci profil).
        jago = ["Jago Syariah", "Pembayaran Berhasil", "Nominal Rp50.000", "Tanggal 30/10/2026 09:00", "31/10/2026 10:00"]
        self.assertEqual(key_of(jago), "logo:jago syariah")
        plain = await read_doc(jago)
        self.assertEqual(plain.reader, "tidak_dikenali")
        self.same_but_issuer(await read_doc(jago, {"logo:jago syariah": logo_rule("bsi", **RULE_LABELS)}), plain, None)
        # Pembanding: label kunci profil `jago` sungguh dipakai (tahap 1), tetap tanpa penerbit.
        got = (await read_doc(jago, {"jago": dict(RULE_LABELS), "logo:jago syariah": logo_rule("bsi")})).parsed.doc
        self.assertEqual((got.issuer, got.confidence["total"]), (None, "tinggi"))

    async def test_logo_baru_unlocks_learned_labels_for_logo_key(self):
        plain = await read_doc(NEWPAY_DATES)
        labels = {"logo:newpay": dict(RULE_LABELS)}
        # Tanpa aturan `logo` yang disetujui untuk kunci itu: label berkunci logo diabaikan (review M2a temuan 3).
        for rules in (labels, {**labels, "logo:kilatpay": logo_rule("baru")},
                      {"logo:newpay": {**RULE_LABELS, "logo": ["siti"]}}, {"logo:newpay": {**RULE_LABELS, "logo": []}}):
            with self.subTest(rules=rules):
                self.same_but_issuer(await read_doc(NEWPAY_DATES, rules), plain, None)
        # `baru`: penerbit tetap None, label dibaca dengan kunci `logo:newpay`.
        got = await read_doc(NEWPAY_DATES, {"logo:newpay": logo_rule("baru", **RULE_LABELS)})
        d = got.parsed.doc
        self.assertEqual((d.issuer, d.amounts.total, d.confidence["total"]), (None, 50000, "tinggi"))
        self.assertEqual((d.paid_at.day, d.confidence["paid_at"]), (30, "tinggi"))
        self.assertEqual((d.doc_type, d.status, got.reader), ("tidak_dikenali", "tidak_diketahui", "tidak_dikenali"))
        # Label profil tidak dipakai untuk `baru`.
        self.same_but_issuer(await read_doc(NEWPAY_DATES, {"logo:newpay": logo_rule("baru"), "jago": dict(RULE_LABELS)}),
                             plain, None)
        # Status tetap hanya dari judul: label jahat ("status", baris gagal) tidak membuka blokir.
        failed = ["NEWPAY", "Pembayaran Gagal", "Nominal Rp50.000", "31/10/2026 10:00"]
        hostile = {"label_total": ["status", "pembayaran gagal", "nominal"], "label_pihak": ["status"],
                   "label_tanggal": ["status", "pembayaran gagal"]}
        before = await read_doc(failed)
        after = await read_doc(failed, {"logo:newpay": logo_rule("baru", **hostile)})
        self.assertEqual((before.parsed.doc.doc_type, before.parsed.doc.status), ("tidak_dikenali", "gagal"))
        self.assertEqual(after.parsed.doc.status, "gagal")
        self.assertEqual([c.as_dict() for c in after.checks], [c.as_dict() for c in before.checks])
        self.assertEqual(after.parsed.doc.confidence["total"], "tinggi")   # aturannya sungguh dipakai


class VotesForLogoTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(merchants, "_warned_no_key", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_label_votes_for_logo_key_only_after_logo_approved(self):
        f = final(50000)
        self.assertEqual(votes_for(LOGO_LAY, doc(total=1), None, f), [])
        self.assertEqual(votes_for(LOGO_LAY, doc(total=1), None, f, approved_logo=frozenset({"logo:kilatpay"})), [])
        self.assertEqual(votes_for(LOGO_LAY, doc(total=1), None, f, approved_logo=frozenset({"logo:newpay"})),
                         [Vote("label_total", "logo:newpay", "nominal")])
        # Kunci logo yang bentuknya bukan kandidat sah tidak pernah memberi suara, juga bila "disetujui".
        for key in ("logo:siti aminah", "logo:NEWPAY", "logo:" + "x" * 60):
            with self.subTest(key=key):
                lay = layout(nominal(2, "nominal", 50000), key=key)
                self.assertEqual(votes_for(lay, doc(total=1), None, f, approved_logo=frozenset({key})), [])
        # Kunci profil tetap tanpa syarat.
        lay = layout(nominal(2, "nominal", 50000), key="jago")
        self.assertEqual(votes_for(lay, doc(total=1), None, f), [Vote("label_total", "jago", "nominal")])

    def test_valid_key(self):
        self.assertTrue(belajar._valid_key("gopay", logo_ok=False))
        self.assertFalse(belajar._valid_key("logo:newpay", logo_ok=False))
        self.assertTrue(belajar._valid_key("logo:newpay", logo_ok=True))
        for key in ("logo:siti aminah", "GOPAY", "", None, "logo:" + "a" * 60):
            with self.subTest(key=key):
                self.assertFalse(belajar._valid_key(key, logo_ok=True))

    def test_kinds_and_choices(self):
        self.assertEqual(belajar.KINDS, ("label_total", "label_pihak", "label_tanggal"))
        self.assertEqual(belajar.KIND_LOGO, "logo")
        self.assertEqual(belajar.ALL_KINDS, (*belajar.KINDS, "logo"))
        self.assertEqual(APP_NEW, "baru")
        self.assertEqual(belajar.APP_CHOICES, frozenset(PROFILE_KEYS) | {"baru"})
        self.assertEqual(len(belajar.APP_CHOICES), 13)
        self.assertEqual(KEY_MAX, 60)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class AppChoiceTests(DbBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        belajar.invalidate_rules_cache()
        self.addCleanup(belajar.invalidate_rules_cache)
        async with self.Session() as db:
            self.env = Envelope(household_id=self.hh[0].id, name="Makan")
            db.add(self.env)
            await db.commit()

    async def scan(self, user, *, lay=LOGO_LAY, doc_type="tidak_dikenali", status="siap", document=None,
                   merchant=None, household=None, transaction_ids=None, channel_meta=None):
        async with self.Session() as db:
            row = ReceiptScan(user_id=user.id, status=status, doc_type=doc_type, layout=lay,
                              document=document if document is not None else doc(total=50000), merchant=merchant,
                              household_id=(household or self.hh[0]).id, transaction_ids=transaction_ids,
                              channel_meta=channel_meta, source="pwa_share")
            db.add(row)
            await db.commit()
            return row

    async def answer(self, item, choice, user, user_name=None):
        async with self.Session() as db:
            ok = await belajar.learn_app_choice(db, item, choice, user_id=user.id, user_name=user_name)
            await db.commit()
            return ok

    async def votes(self):
        async with self.Session() as db:
            return [(v.kind, v.rule_key, v.value, v.user_id) for v in
                    (await db.execute(select(ProofRuleVote).order_by(ProofRuleVote.created_at))).scalars().all()]

    async def meta(self, item):
        async with self.Session() as db:
            return (await db.get(ReceiptScan, item.id)).channel_meta

    async def txn(self, description):
        async with self.Session() as db:
            row = Transaction(envelope_id=self.env.id, user_id=self.users[0].id, amount=Decimal(50000),
                              description=description, transaction_date=date(2026, 10, 31))
            db.add(row)
            await db.commit()
            return str(row.id)

    async def test_app_choice_votes_once_and_threshold(self):
        a, b = self.users[:2]
        item = await self.scan(a, channel_meta={"chat_id": 7})
        self.assertTrue(await self.answer(item, "bsi", a))
        self.assertEqual(await self.votes(), [("logo", "logo:newpay", "bsi", a.id)])
        self.assertEqual(await self.meta(item), {"chat_id": 7, "app_choice": "bsi"})
        # Sekali per item: jawaban kedua (nilai apa pun) ditolak, suara tetap satu.
        for choice in ("bsi", "baru"):
            self.assertFalse(await self.answer(item, choice, a))
        stale = await self.scan(a)   # objek lama tanpa app_choice: baris di database yang menentukan
        self.assertTrue(await self.answer(stale, "bsi", a))   # item lain user yang sama: suara yang sama tetap satu
        stale.channel_meta = None
        self.assertFalse(await self.answer(stale, "baru", a))
        self.assertEqual(len(await self.votes()), 1)
        async with self.Session() as db:
            self.assertEqual((await db.execute(select(func.count()).select_from(ProofRule))).scalar_one(), 0)
        # User kedua (rumah tangga lain): aturan `logo` menunggu dengan 2 user.
        self.assertTrue(await self.answer(await self.scan(b, household=self.hh[1]), "bsi", b))
        [rule] = await self.rules()
        self.assertEqual((rule.kind, rule.rule_key, rule.value, rule.users, rule.households, rule.status),
                         ("logo", "logo:newpay", "bsi", 2, 2, "menunggu"))
        # "baru" juga nilai sah; status item tidak berubah.
        self.assertTrue(await self.answer(await self.scan(self.users[2]), APP_NEW, self.users[2]))
        self.assertIn(("logo", "logo:newpay", "baru", self.users[2].id), await self.votes())
        async with self.Session() as db:
            self.assertEqual((await db.get(ReceiptScan, item.id)).status, "siap")
            self.assertEqual((await db.execute(select(func.count()).select_from(Transaction))).scalar_one(), 0)

    async def test_logo_vote_refused_for_known_names(self):   # Review Focus 6, K8
        a = self.users[0]
        wahyu = layout(nominal(2, "nominal", 50000), key="logo:wahyu")
        raya = layout(nominal(2, "nominal", 50000), key="logo:bank raya")
        cases = [
            ("nama user", dict(lay=wahyu), "Wahyu Pratama", None),
            ("pihak lawan", dict(lay=wahyu, document=doc(total=50000, name="WAHYU")), None, None),
            ("merchant", dict(lay=wahyu, merchant="Toko Wahyu Jaya"), None, None),
            ("keterangan tercatat", dict(lay=wahyu, status="tercatat"), None, "bayar arisan ke Pak Wahyu"),
            ("dua kata, kata bukan pendamping", dict(lay=raya, status="tercatat"), None, "titip ke bu raya"),
        ]
        for name, cols, user_name, description in cases:
            with self.subTest(name):
                if description:
                    cols["transaction_ids"] = [await self.txn(description)]
                item = await self.scan(a, **cols)
                self.assertTrue(await self.answer(item, "bsi", a, user_name=user_name))
                self.assertEqual(await self.votes(), [])
                self.assertEqual((await self.meta(item))["app_choice"], "bsi")   # dijawab: tidak ditanya lagi
        # Nama bersambung tanda baca (review M2a temuan 2).
        for name, cols, user_name, description in (
                ("titik", dict(lay=wahyu, merchant="WAHYU.N"), None, None),
                ("tanda hubung", dict(lay=wahyu), "Wahyu-Nugroho", None),
                ("koma di keterangan", dict(lay=wahyu, status="tercatat"), None, "kirim ke wahyu,arisan"),
                ("garis miring", dict(lay=wahyu, document=doc(total=50000, name="Wahyu/arisan")), None, None)):
            with self.subTest(name):
                if description:
                    cols["transaction_ids"] = [await self.txn(description)]
                item = await self.scan(a, **cols)
                self.assertTrue(await self.answer(item, "bsi", a, user_name=user_name))
                self.assertEqual(await self.votes(), [])
        # Pembanding: nama lain, dan kata pendamping ("bank") di keterangan bukan nama logo.
        item = await self.scan(a, lay=wahyu, document=doc(total=50000, name="SITI"), merchant="Toko Sinar",
                               status="tercatat", transaction_ids=[await self.txn("transfer bank ke Siti")])
        self.assertTrue(await self.answer(item, "bsi", a, user_name="Ani Lestari"))
        item = await self.scan(a, lay=raya, status="tercatat", transaction_ids=[await self.txn("transfer bank")])
        self.assertTrue(await self.answer(item, "baru", a, user_name="Ani Lestari"))
        self.assertEqual(await self.votes(), [("logo", "logo:wahyu", "bsi", a.id),
                                              ("logo", "logo:bank raya", "baru", a.id)])

    async def test_items_that_cannot_be_asked_give_no_vote(self):
        a = self.users[0]
        cases = [
            ("qris", dict(doc_type="qris")),
            ("transfer", dict(doc_type="transfer")),
            ("kunci profil", dict(lay=layout(nominal(2, "nominal", 50000), key="jago"))),
            ("kunci logo bukan kandidat", dict(lay=layout(nominal(2, "nominal", 50000), key="logo:siti aminah"))),
            ("tanpa kerangka", dict(lay=None)),
            ("dilewati", dict(status="dilewati")),
            ("gagal", dict(status="gagal")),
            ("kedaluwarsa", dict(status="kedaluwarsa")),
            ("sudah dijawab", dict(channel_meta={"app_choice": "ovo"})),
        ]
        for name, cols in cases:
            with self.subTest(name):
                item = await self.scan(a, **cols)
                self.assertIsNone(belajar.app_logo(item))
                self.assertFalse(await self.answer(item, "bsi", a))
                self.assertEqual(await self.meta(item), cols.get("channel_meta"))
        item = await self.scan(a)
        self.assertEqual(belajar.app_logo(item), "newpay")
        for choice in ("xyz", "BSI", "", "logo:newpay", "Lainnya", None):
            with self.subTest(choice=choice):
                self.assertFalse(await self.answer(item, choice, a))
        self.assertIsNone(await self.meta(item))
        # Item milik user lain: tidak ada yang berubah.
        self.assertFalse(await self.answer(item, "bsi", self.users[1]))
        self.assertEqual(await self.votes(), [])

    async def test_errors_are_swallowed_and_never_commit(self):
        a = self.users[0]
        item = await self.scan(a)
        with patch.object(belajar, "record_votes", AsyncMock(side_effect=RuntimeError("db putus"))), \
                self.assertLogs("app.services.kotak_struk.belajar", "WARNING") as logs:
            async with self.Session() as db:
                self.assertFalse(await belajar.learn_app_choice(db, item, "bsi", user_id=a.id, user_name=None))
                self.assertEqual((await db.execute(text("SELECT 1"))).scalar(), 1)   # sesi tetap bisa dipakai
                await db.commit()
        self.assertNotIn("newpay", "".join(logs.output).lower())   # log tanpa isi bukti
        self.assertIsNone(await self.meta(item))   # savepoint dibatalkan: jawaban juga tidak tersimpan
        async with self.Session() as db:
            self.assertTrue(await belajar.learn_app_choice(db, item, "bsi", user_id=a.id, user_name=None))
            await db.rollback()   # tidak meng-commit sendiri
        self.assertEqual((await self.votes(), await self.meta(item)), ([], None))

    async def test_approved_logo_keys_and_reader_rules_with_logo(self):
        async def add(kind, key, value, status="disetujui", users=2):
            async with self.Session() as db:
                db.add(ProofRule(kind=kind, rule_key=key, value=value, users=users, households=1, status=status,
                                 decided_at=datetime(2026, 10, 30, tzinfo=timezone.utc)))
                await db.commit()
            belajar.invalidate_rules_cache()

        async def keys():
            async with self.Session() as db:
                return await belajar.approved_logo_keys(db), await belajar.approved_rules(db)

        await add("logo", "logo:newpay", "bsi", status="menunggu")
        await add("logo", "logo:kilatpay", "baru", status="ditolak")
        await add("label_total", "logo:sinarpay", "nominal")   # aturan label, bukan aturan logo
        await add("label_total", "gopay", "dibayar")
        logo_keys, rules = await keys()
        self.assertEqual(logo_keys, frozenset())
        self.assertEqual(set(rules), {"logo:sinarpay", "gopay"})
        await add("logo", "logo:newpay", "baru")
        await add("logo", "logo:siti aminah", "bsi")   # bentuk rusak (data lama/tangan): tidak pernah kunci logo
        await add("logo", "logo:kilatpay", "siti")   # nilai bukan pilihan (data lama/tangan): tidak dimuat
        await add("logo", "gopay", "bsi")             # aturan `logo` untuk kunci profil: tidak dimuat
        logo_keys, rules = await keys()
        self.assertEqual(logo_keys, frozenset({"logo:newpay"}))
        # M2b: `approved_rules` memuat jenis `logo` (`{"logo": [nilai]}`) untuk kunci logo yang sah; kunci yang tidak
        # punya aturan `logo` tetap berbentuk tahap 1 (tanpa `"logo"`).
        self.assertEqual(rules, {"logo:sinarpay": {"label_total": ["nominal"], "label_pihak": [], "label_tanggal": []},
                                 "gopay": {"label_total": ["dibayar"], "label_pihak": [], "label_tanggal": []},
                                 "logo:newpay": {"label_total": [], "label_pihak": [], "label_tanggal": [],
                                                 "logo": ["baru"]}})
        # Nilai `logo` urut pendukung terbanyak (lalu yang lebih dulu disetujui, lalu teksnya).
        await add("logo", "logo:newpay", "jago", users=3)
        await add("label_total", "logo:newpay", "biaya")
        _, rules = await keys()
        self.assertEqual(rules["logo:newpay"], {"label_total": ["biaya"], "label_pihak": [], "label_tanggal": [],
                                                "logo": ["jago", "baru"]})
        # Galat database: kosong, bukan melempar.
        belajar.invalidate_rules_cache()
        broken = AsyncMock()
        broken.begin_nested = lambda: (_ for _ in ()).throw(RuntimeError("db putus"))
        with self.assertLogs("app.services.kotak_struk.belajar", "WARNING"):
            self.assertEqual(await belajar.approved_logo_keys(broken), frozenset())

    async def test_recording_votes_labels_for_logo_key_only_after_approval(self):
        a = self.users[0]

        async def record_once():
            tid = await self.txn("bayar NEWPAY")
            item = await self.scan(a, document=doc(total=10000))
            async with self.Session() as db:
                await record._learn_correction(db, await db.get(ReceiptScan, item.id), a.id, uuid.UUID(tid))
                await db.commit()
            return [v for v in await self.votes() if v[0] == "label_total"]

        self.assertEqual(await record_once(), [])
        async with self.Session() as db:
            db.add(ProofRule(kind="logo", rule_key="logo:newpay", value="baru", users=2, households=2,
                             status="disetujui", decided_at=datetime(2026, 10, 30, tzinfo=timezone.utc)))
            await db.commit()
        belajar.invalidate_rules_cache()
        self.assertEqual(await record_once(), [("label_total", "logo:newpay", "nominal", a.id)])


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class AdminLogoKindTests(AdminRulesBase):
    async def test_admin_lists_reconciles_and_decides_logo_rules(self):
        for user in (self.user, self.user2):
            await self.vote("bsi", user, kind="logo", key="logo:newpay")
        async with self.Session() as db:
            self.assertGreater(await belajar.reconcile_rules(db), 0)   # rekonsiliasi membuat aturan `logo`
            await db.commit()
        votes = (await self.c.get("/admin/kotak/votes")).json()["rows"]
        self.assertEqual(votes, [{"rule_key": "logo:newpay", "kind": "logo", "users": 2, "values": 1}])
        [rule] = (await self.c.get("/admin/kotak/rules")).json()["rules"]
        self.assertEqual((rule["kind"], rule["rule_key"], rule["value"], rule["users"]),
                         ("logo", "logo:newpay", "bsi", 2))
        self.assertEqual((await self.act(rule["id"], "setujui")).status_code, 200)
        async with self.Session() as db:
            self.assertEqual(await belajar.approved_logo_keys(db), frozenset({"logo:newpay"}))
            self.assertEqual(await belajar.approved_rules(db), {"logo:newpay": {
                "label_total": [], "label_pihak": [], "label_tanggal": [], "logo": ["bsi"]}})


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class AppQuestionApiTests(ApiBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        belajar.invalidate_rules_cache()
        self.addCleanup(belajar.invalidate_rules_cache)

    async def test_ask_app_flags(self):
        item = await self.ready(NEWPAY)
        self.assertEqual((await self.get(item.id)).layout["key"], "logo:newpay")
        flags = (await self.detail(item))["flags"]
        self.assertEqual((flags["ask_app"], flags["app_logo"]), (True, "NEWPAY"))
        self.assertEqual(set(flags), {"duplicate_of", "skip_suggestion", "blocked", "warnings", "ask_app", "app_logo"})
        # Tercatat masih boleh ditanya; dilewati/gagal tidak.
        await self.set(item.id, status="tercatat")
        self.assertTrue((await self.detail(item))["flags"]["ask_app"])
        await self.set(item.id, status="dilewati")
        self.assertEqual(((await self.detail(item))["flags"]["ask_app"], (await self.detail(item))["flags"]["app_logo"]),
                         (False, None))
        # QRIS berprofil dan bukti tak dikenal tanpa kandidat logo (G9): tidak ditanya.
        for other in (await self.ready_qris(),
                      await self.ready(["09:41", "Siti Aminah", "Kirim Uang Berhasil", "Nominal Rp50.000"])):
            flags = (await self.detail(other))["flags"]
            self.assertEqual((flags["ask_app"], flags["app_logo"]), (False, None))
        # Sesudah dijawab: tidak ditanya lagi; kerangka tidak pernah dikirim.
        fresh = await self.ready(NEWPAY)
        r = await self.c.post(f"/kotak-struk/{fresh.id}/aplikasi", json={"app": "bsi"})
        self.assertEqual((r.status_code, r.json()), (200, {"app": "bsi", "ask_app": False}))
        d = await self.detail(fresh)
        self.assertEqual((d["flags"]["ask_app"], d["flags"]["app_logo"], d["status"]), (False, None, "siap"))
        self.assertNotIn("layout", d)
        self.assertNotIn("logo:", json.dumps(d))

    async def test_aplikasi_route_errors(self):
        item = await self.ready(NEWPAY)
        others = await self.ready(NEWPAY, owner=self.b)
        url = f"/kotak-struk/{item.id}/aplikasi"
        for target in (others.id, uuid4()):
            r = await self.c.post(f"/kotak-struk/{target}/aplikasi", json={"app": "bsi"})
            self.assertEqual((r.status_code, r.json()["detail"]), (404, "Bukti tidak ditemukan"))
        for body in ({"app": "xyz"}, {"app": "BSI"}, {"app": "Lainnya"}, {"app": ""}, {"app": "b" * 21}, {}):
            with self.subTest(body=body):
                self.assertEqual((await self.c.post(url, json=body)).status_code, 422)
        qris = await self.ready_qris()
        r = await self.c.post(f"/kotak-struk/{qris.id}/aplikasi", json={"app": "bsi"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Aplikasi bukti ini tidak bisa dipilih"))
        self.assertEqual((await self.c.post(url, json={"app": "baru"})).status_code, 200)
        r = await self.c.post(url, json={"app": "bsi"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Aplikasi bukti ini tidak bisa dipilih"))
        async with self.Session() as db:
            votes = [(v.kind, v.rule_key, v.value, v.user_id) for v in
                     (await db.execute(select(ProofRuleVote))).scalars().all()]
            self.assertEqual((await db.execute(select(func.count()).select_from(Transaction))).scalar_one(), 0)
        self.assertEqual(votes, [("logo", "logo:newpay", "baru", self.a.id)])
        got = await self.get(item.id)
        self.assertEqual((got.status, got.channel_meta.get("app_choice")), ("siap", "baru"))
        self.assertIsNone((await self.get(others.id)).channel_meta)

    async def test_route_is_registered_with_a_response_model(self):
        from app.main import app
        [route] = [r for r in app.routes if getattr(r, "path", None) == "/kotak-struk/{item_id}/aplikasi"]
        self.assertEqual(route.methods, {"POST"})
        self.assertIsNotNone(route.response_model)


if __name__ == "__main__":
    unittest.main()
