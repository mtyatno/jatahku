"""Bot Telegram dan chat bot web lewat Kotak Struk (Task A11, spec 2026-10-26 bagian 5a): foto, dokumen gambar, PDF,
dan teks bukti menjadi item Kotak Struk; pesan hasil (bukti bayar dan struk belanja lama tanpa baris kuota); tombol
amplop, catatan, lewati; kabar Telegram untuk item yang lambat; dan jalur catat bot yang tidak pernah mencatat bukti
dua kali.

Dua jenis tes: alur dengan database/worker tiruan (pola `TestBotReceipt`), dan alur ujung ke ujung dengan SQLite,
intake dan worker sungguhan (`TxnBase`).
Run: python -m unittest app.tests.test_kotak_bot -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import json
import re
import unittest
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from app.bot import channel, handlers, receipt_cmd, web_adapter
from app.bot.receipt_cmd import looks_like_proof_text, proof_message
from app.models.models import (
    Allocation, Envelope, Income, MerchantEnvelopeMap, ReceiptScan, Transaction, User, UserEnvelopeKeyword,
)
from app.services.kotak_struk import intake, record as record_mod, view, waiter
from app.services.kotak_struk.document import Amounts, Counterparty, DokumenBayar
from app.services.kotak_struk.worker import process_item
from app.tests.test_kotak_api import CORPUS, HAS_AIOSQLITE, JPG, NOW, PAID, QRIS_KEY, fake_extract
from app.tests.test_kotak_transactions import STORE_LINES, TxnBase
from app.tests.test_web_chat import FakeRedis as ChatRedis

UID = uuid4()
HID = uuid4()
USER = SimpleNamespace(id=UID, name="Ani", payday_day=1)
MAKAN = SimpleNamespace(id=uuid4(), name="Makan", emoji="🍜", purpose="expense")
JAJAN = SimpleNamespace(id=uuid4(), name="Jajan", emoji="🛒", purpose="expense")
TABUNGAN = SimpleNamespace(id=uuid4(), name="Tabungan", emoji="🐷", purpose="saving")
NO_FLAGS = {"duplicate_of": None, "skip_suggestion": None, "blocked": None, "warnings": []}
NO_SUGGESTION = {"envelope_id": None, "envelope_name": None, "confident": False, "source": "none"}


def _detail(doc_type, *, name, total, paid_at, preview, city=None, status="berhasil", suggestion=None, **over):
    doc = DokumenBayar(doc_type=doc_type, status=status, counterparty=Counterparty(name=name.upper(), city=city),
                       amounts=Amounts(total=total)).to_json()
    detail = {
        "id": str(uuid4()), "status": "siap", "doc_type": doc_type, "source": "telegram",
        "created_at": "2026-10-26T03:00:00+00:00", "paid_at": paid_at, "document": doc,
        "merchant": {"id": str(uuid4()), "name": name, "display_name": None},
        "suggestion": suggestion or NO_SUGGESTION, "description_preview": preview,
        "flags": {**NO_FLAGS, "warnings": []}, "error": None,
    }
    detail.update(over)
    return detail


def with_flags(detail, **flags):
    return {**detail, "flags": {**detail["flags"], **flags}}


DETAIL_QRIS = _detail("qris", name="Siti Aminah", city="BANDUNG", total=25000, paid_at="2026-10-26T01:12:33+00:00",
                      preview="Siti Aminah (QRIS)",
                      suggestion={"envelope_id": str(MAKAN.id), "envelope_name": "Makan", "confident": True,
                                  "source": "merchant"})
DETAIL_QRIS_NOTE = {**DETAIL_QRIS, "description_preview": "bakso 2, es teh (Siti Aminah)",
                    "suggestion": {"envelope_id": str(JAJAN.id), "envelope_name": "Jajan", "confident": False,
                                   "source": "note"}}
DETAIL_TRANSFER = _detail("transfer", name="Budi Santoso", total=152500, paid_at="2026-10-26T02:30:00+00:00",
                          preview="Transfer ke Budi Santoso")
DETAIL_STRUK = _detail("struk_belanja", name="Indomaret", total=51000, paid_at=None, preview="Indomaret")
DETAIL_PENDING = {**DETAIL_QRIS, "id": str(uuid4()), "status": "diterima", "doc_type": None, "document": None}
DETAIL_GAGAL = {**DETAIL_QRIS, "id": str(uuid4()), "status": "gagal", "doc_type": None, "document": None,
                "error": "PDF terkunci kata sandi"}
RECORDED = {"kind": "ref", "item_id": str(uuid4()), "recorded": True}
SOFT = {"kind": "soft", "transaction": {"id": str(uuid4()), "description": "bakso", "amount": 25000,
                                        "created_at": "2026-10-26T01:30:00+00:00", "envelope_name": "Makan"}}
TXN = uuid4()
ENV = uuid4()
PROOF_ITEM_ID = uuid4()


def _item(detail, **over):
    """Item `ReceiptScan` tiruan untuk sebuah detail (struk belanja: kolom yang dipakai respons scan lama)."""
    store = detail["doc_type"] == "struk_belanja"
    fields = dict(
        id=UUID(detail["id"]), status=detail["status"], doc_type=detail["doc_type"], user_id=UID,
        channel_meta=None, error=detail.get("error"), document=detail["document"],
        merchant="Indomaret" if store else None, parsed_date=date(2026, 10, 14) if store else None,
        confidence="tinggi", engine="rapidocr",
    )
    fields.update(over)
    return SimpleNamespace(**fields)


class FakeDb:
    """Sesi tiruan: `get` dari kamus item, `execute` mencatat pernyataan (UPDATE `notify`) dan mengembalikan rowcount."""

    def __init__(self):
        self.items, self.executed, self.rowcount = {}, [], 1
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, cls, key):
        return USER if cls is User else self.items.get(key)

    async def execute(self, stmt):
        self.executed.append(stmt)
        return SimpleNamespace(rowcount=self.rowcount)


def keyboard_of(call):
    markup = call.kwargs.get("reply_markup")
    return markup.inline_keyboard if markup is not None else []


def datas(rows):
    return [b.callback_data for row in rows for b in row]


# ── teks bukti (murni) ─────────────────────────────────────────────────────────

class ProofTextTests(unittest.TestCase):
    def test_proof_text_detected(self):
        self.assertTrue(looks_like_proof_text("Transfer berhasil\nPenerima BUDI\nRp150.000\nNo. Ref 123"))
        self.assertTrue(looks_like_proof_text("Pembayaran Sukses\nMerchant WARUNG\nIDR 25,000\nRRN 0001"))

    def test_plain_text_is_not_proof(self):
        for t in ["kopi 35k", "kopi 20k\nroti 15k", "berhasil hemat hari ini", "bayar listrik 200rb berhasil",
                  "Transfer berhasil Rp150.000 ref 123",            # satu baris
                  "Transfer berhasil\nPenerima BUDI\nNo. Ref 123",   # tanpa nominal Rp
                  "Transfer\nPenerima BUDI\nRp150.000\nNo. Ref 123",  # tanpa kata status
                  "Bayar berhasil\nRp150.000"]:                       # tanpa label
            with self.subTest(t):
                self.assertFalse(looks_like_proof_text(t))


# ── pesan bukti (murni) ────────────────────────────────────────────────────────

class MessageTests(unittest.TestCase):
    def test_ready_qris_message(self):
        self.assertEqual(proof_message(DETAIL_QRIS),
                         "QRIS · Siti Aminah · Bandung\nRp 25.000 · 26 Okt 08.12 · Berhasil\n\nMasuk ke amplop mana?")

    def test_recorded_and_failed_messages(self):
        self.assertEqual(proof_message(with_flags(DETAIL_QRIS, blocked="transaksi_gagal")), "⚠️ Transaksi ini gagal di bank, jadi tidak dicatat.")
        self.assertIn("sudah tercatat", proof_message(with_flags(DETAIL_QRIS, blocked="sudah_tercatat", duplicate_of=RECORDED)))

    def test_recorded_message_variants(self):
        blocked = with_flags(DETAIL_QRIS, blocked="sudah_tercatat", duplicate_of=RECORDED)
        self.assertEqual(proof_message(blocked, recorded={"date": date(2026, 10, 26), "envelope_name": "Makan"}),
                         "✅ Bukti ini sudah tercatat 26 Okt di Makan.")
        self.assertEqual(proof_message(blocked, recorded={"date": date(2026, 10, 26), "envelope_name": None}),
                         "✅ Bukti ini sudah tercatat 26 Okt.")
        self.assertEqual(proof_message(blocked), "✅ Bukti ini sudah tercatat.")

    def test_transfer_without_city_and_pending_status(self):
        self.assertEqual(proof_message(DETAIL_TRANSFER),
                         "Transfer · Budi Santoso\nRp 152.500 · 26 Okt 09.30 · Berhasil\n\nMasuk ke amplop mana?")
        pending = {**DETAIL_TRANSFER, "document": {**DETAIL_TRANSFER["document"], "status": "pending"}}
        self.assertIn("· Pending\n", proof_message(pending))

    def test_skip_suggestions_and_soft_duplicate(self):
        head = "QRIS · Siti Aminah · Bandung\nRp 25.000 · 26 Okt 08.12 · Berhasil\n\n"
        for flow, tail in [("top_up", "ℹ️ Ini top-up saldo, bukan pengeluaran."),
                           ("masuk", "ℹ️ Ini uang masuk, bukan pengeluaran."),
                           ("antar_rekening_sendiri", "ℹ️ Sepertinya transfer ke rekeningmu sendiri. Bukan pengeluaran?")]:
            with self.subTest(flow):
                self.assertEqual(proof_message(with_flags(DETAIL_QRIS, skip_suggestion=flow)), head + tail)
        self.assertEqual(proof_message(with_flags(DETAIL_QRIS, duplicate_of=SOFT)),
                         head + '🤔 Mirip "bakso" yang dicatat 08.30. Sama?')

    def test_warnings_become_lines_and_note_shows_description(self):
        text = proof_message(with_flags(DETAIL_QRIS, warnings=["Bukti ini juga dibagikan Budi"]))
        self.assertEqual(text, "QRIS · Siti Aminah · Bandung\nRp 25.000 · 26 Okt 08.12 · Berhasil\n"
                               "⚠️ Bukti ini juga dibagikan Budi\n\nMasuk ke amplop mana?")
        self.assertIn("\n📝 bakso 2, es teh (Siti Aminah)\n\n", proof_message(DETAIL_QRIS_NOTE, note="bakso 2, es teh"))


# ── alur bot dengan database dan worker tiruan ────────────────────────────────

class BotFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 2.0   # mode debug asyncio: jeda GC bukan urusan tes ini
        self.redis = ChatRedis()
        self.db = FakeDb()
        self.detail = self.detail_note = None
        self.item = None
        self.create = AsyncMock(side_effect=self._create)
        self.skip = AsyncMock(return_value=True)
        envs = [{"envelope": e} for e in (JAJAN, TABUNGAN, MAKAN)]
        for p in (
            patch.object(receipt_cmd, "AsyncSessionLocal", new=lambda: self.db),
            patch.object(handlers, "AsyncSessionLocal", new=lambda: self.db),
            patch.object(handlers, "get_or_create_user", new=AsyncMock(return_value=USER)),
            patch.object(handlers, "_is_setup_complete", new=AsyncMock(return_value=(True, "ok"))),
            patch.object(handlers, "get_household_id", new=AsyncMock(return_value=HID)),
            patch.object(handlers, "get_envelopes_with_spent", new=AsyncMock(return_value=envs)),
            patch("redis.asyncio.from_url", return_value=self.redis),
            patch.object(intake, "create_item", new=self.create),
            patch.object(waiter, "wait_for_item", new=AsyncMock(side_effect=lambda item_id, timeout_s: self.item)),
            patch.object(view, "item_detail", new=AsyncMock(side_effect=self._item_detail)),
            patch.object(record_mod, "skip_item", new=self.skip),
            patch("app.services.txn_nlp.find_best_envelope", new=AsyncMock(return_value=(None, False))),
        ):
            p.start()
            self.addCleanup(p.stop)

    async def _create(self, db, req, **kw):
        self.request = req
        return self.item, True

    async def _item_detail(self, db, item, user, *, note=None):
        return self.detail_note if note else self.detail

    # --- pembantu -------------------------------------------------------

    def _update(self, message):
        return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42, first_name="Ani"),
                               effective_chat=SimpleNamespace(id=4242))

    async def _send(self, message, detail):
        self.detail = detail
        self.item = _item(detail)
        self.db.items[self.item.id] = self.item
        self.status = MagicMock(message_id=501, edit_text=AsyncMock(), delete=AsyncMock())
        message.reply_text = AsyncMock(return_value=self.status)
        await handlers.handle_non_text(self._update(message), SimpleNamespace(bot=None))

    async def send_photo(self, detail):
        tg_file = MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"\xff\xd8jpg")))
        message = MagicMock(photo=[MagicMock(get_file=AsyncMock(return_value=tg_file))], document=None)
        await self._send(message, detail)

    async def send_document(self, data, mime, detail):
        tg_file = MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(data)))
        doc = MagicMock(mime_type=mime, file_size=len(data), get_file=AsyncMock(return_value=tg_file))
        message = MagicMock(photo=None, document=doc)
        await self._send(message, detail)

    def text(self):
        return self.status.edit_text.call_args.args[0]

    def keyboard(self):
        return keyboard_of(self.status.edit_text.call_args)

    def button_texts(self):
        return [b.text for row in self.keyboard() for b in row]

    @property
    def key(self):
        return next(d for d in datas(self.keyboard()) if d.startswith("t_")).split("_")[1]

    def stored_payload(self):
        return json.loads(self.redis.store[f"txn:{self.key}"])

    def created_request(self):
        return self.request

    def saved_channel_meta(self):
        [stmt] = [s for s in self.db.executed if getattr(getattr(s, "table", None), "name", None) == "receipt_scans"]
        return stmt.compile().params["channel_meta"]

    async def press(self, data):
        self.query = MagicMock(data=data, answer=AsyncMock(), edit_message_text=AsyncMock(),
                               message=MagicMock(message_id=501, reply_text=AsyncMock()))
        upd = SimpleNamespace(callback_query=self.query, effective_user=SimpleNamespace(id=42, first_name="Ani"),
                              effective_chat=SimpleNamespace(id=4242))
        handler = next(h for pattern, h in handlers.bot_callbacks() if re.match(pattern, data))
        await handler(upd, SimpleNamespace(bot=None))
        return self.query

    async def reply_text(self, text, detail_after_note):
        self.detail_note = detail_after_note
        self.bot = MagicMock(edit_message_text=AsyncMock())
        message = MagicMock(text=text, reply_text=AsyncMock())
        return await receipt_cmd.capture_note(self._update(message), SimpleNamespace(bot=self.bot))

    # --- brief ----------------------------------------------------------

    async def test_qris_photo_offers_star_envelope_and_note_button(self):
        await self.send_photo(detail=DETAIL_QRIS)
        rows = self.keyboard()
        self.assertEqual(rows[0][0].text, "⭐ 🍜 Makan")
        self.assertIn("✏️ Tambah catatan", self.button_texts())
        stored = self.stored_payload()
        self.assertEqual((stored["kind"], stored["desc"], stored["date"], stored["scan_id"]), ("proof", "Siti Aminah (QRIS)", "2026-10-26", DETAIL_QRIS["id"]))
        self.assertNotIn("Sisa scan", self.text())

    async def test_store_receipt_photo_keeps_old_message_without_quota(self):
        await self.send_photo(detail=DETAIL_STRUK)
        self.assertIn("🧾 Struk Indomaret", self.text()); self.assertNotIn("Sisa scan", self.text())

    async def test_slow_item_promises_notification(self):
        await self.send_photo(detail=DETAIL_PENDING)
        self.assertEqual(self.text(), "⏳ Masih dibaca, nanti kukabari.")
        self.assertTrue(self.saved_channel_meta()["notify"])

    async def test_note_capture_updates_payload_and_message(self):
        await self.send_photo(detail=DETAIL_QRIS)
        await self.press(f"kn_{self.key}")
        captured = await self.reply_text("bakso 2, es teh", detail_after_note=DETAIL_QRIS_NOTE)
        self.assertTrue(captured)
        self.assertEqual(self.stored_payload()["desc"], "bakso 2, es teh (Siti Aminah)")

    async def test_pdf_document_goes_to_kotak(self):
        await self.send_document(b"%PDF-1.4 x", "application/pdf", detail=DETAIL_TRANSFER)
        self.assertEqual(self.created_request().data, b"%PDF-1.4 x")
        self.assertTrue(self.text().startswith("Transfer · Budi Santoso"))

    async def test_feedback_hook_marks_proof_recorded(self):
        self.db.items[PROOF_ITEM_ID] = SimpleNamespace(id=PROOF_ITEM_ID, user_id=UID, status="tercatat", doc_type="qris")
        with patch("app.services.kotak_struk.record.mark_recorded", new=AsyncMock()) as mark, \
             patch("app.services.receipt_scan.apply_feedback", new=AsyncMock()) as fb:
            await handlers._receipt_feedback_saved(UID, PROOF_ITEM_ID, 25000, date(2026, 10, 26), "x",
                                                   transaction_id=TXN, envelope_id=ENV)
        mark.assert_awaited_once(); fb.assert_not_awaited()

    # --- tambahan -------------------------------------------------------

    async def test_photo_goes_through_kotak_intake_not_scan_receipt(self):
        with patch("app.services.receipt_scan.scan_receipt", new=AsyncMock()) as old_scan:
            await self.send_photo(detail=DETAIL_QRIS)
        old_scan.assert_not_awaited()
        req = self.created_request()
        self.assertEqual((req.source, req.data, req.content_type, req.text), ("telegram", b"\xff\xd8jpg", "image/jpeg", None))
        self.assertEqual(req.channel_meta, {"chat_id": 4242, "status_message_id": 501})
        self.assertEqual(self.status.edit_text.call_count, 1)   # "🧾 Membaca bukti..." diedit menjadi hasil

    async def test_ready_proof_buttons(self):
        await self.send_photo(detail=DETAIL_QRIS)
        item_id = DETAIL_QRIS["id"]
        self.assertEqual(datas(self.keyboard())[-3:], [f"kn_{self.key}", f"kx_{item_id}", f"struk_no_{item_id}"])
        self.assertEqual(self.button_texts()[:2], ["⭐ 🍜 Makan", "🛒 Jajan"])   # tabungan tidak ditawarkan
        self.assertNotIn("🐷 Tabungan", self.button_texts())
        self.assertEqual(self.button_texts()[-2:], ["🚫 Bukan pengeluaran", "❌ Batal"])
        self.assertTrue(all(len(d.encode()) <= 64 for d in datas(self.keyboard())))
        self.assertEqual(self.stored_payload()["item_id"], item_id)
        self.assertIsNone(self.stored_payload()["note"])

    async def test_unconfident_suggestion_is_first_without_star(self):
        unsure = {**DETAIL_QRIS, "suggestion": {**DETAIL_QRIS["suggestion"], "confident": False}}
        await self.send_photo(detail=unsure)
        self.assertEqual(self.button_texts()[:2], ["🍜 Makan", "🛒 Jajan"])

    async def test_skip_suggestion_offers_skip_or_record_anyway(self):
        await self.send_photo(detail=with_flags(DETAIL_QRIS, skip_suggestion="top_up"))
        self.assertTrue(self.text().endswith("ℹ️ Ini top-up saldo, bukan pengeluaran."))
        key = next(d for d in datas(self.keyboard()) if d.startswith("ko_"))[3:]
        self.assertEqual([[b.text for b in row] for row in self.keyboard()], [["Oke, lewati", "Tetap catat"]])
        self.assertEqual(datas(self.keyboard()), [f"kx_{DETAIL_QRIS['id']}", f"ko_{key}"])
        # "Tetap catat" → tombol amplop dengan sesi tombol yang sama
        query = await self.press(f"ko_{key}")
        text = query.edit_message_text.call_args.args[0]
        self.assertTrue(text.endswith("Masuk ke amplop mana?"))
        rows = keyboard_of(query.edit_message_text.call_args)
        self.assertEqual(rows[0][0].callback_data, f"t_{key}_0")
        self.assertEqual(rows[0][0].text, "⭐ 🍜 Makan")

    async def test_soft_duplicate_offers_same_or_different(self):
        await self.send_photo(detail=with_flags(DETAIL_QRIS, duplicate_of=SOFT))
        self.assertTrue(self.text().endswith('🤔 Mirip "bakso" yang dicatat 08.30. Sama?'))
        key = next(d for d in datas(self.keyboard()) if d.startswith("ko_"))[3:]
        self.assertEqual([[b.text for b in row] for row in self.keyboard()], [["Sama, lewati", "Beda, catat"]])
        self.assertEqual(datas(self.keyboard()), [f"kd_{DETAIL_QRIS['id']}", f"ko_{key}"])

    async def test_blocked_proofs_have_no_record_buttons(self):
        for flags, expect in [({"blocked": "transaksi_gagal"}, "⚠️ Transaksi ini gagal di bank, jadi tidak dicatat."),
                              ({"blocked": "sudah_tercatat", "duplicate_of": RECORDED}, "✅ Bukti ini sudah tercatat.")]:
            with self.subTest(flags), patch.object(view, "recorded_summary", new=AsyncMock(return_value=None)):
                await self.send_photo(detail=with_flags(DETAIL_QRIS, **flags))
                self.assertEqual(self.text(), expect)
                self.assertEqual(self.keyboard(), [])

    async def test_failed_item_shows_its_error(self):
        await self.send_photo(detail=DETAIL_GAGAL)
        self.assertEqual(self.text(), "😕 PDF terkunci kata sandi")
        self.assertEqual(self.keyboard(), [])

    async def test_slow_item_on_web_points_to_waiting_list_without_notify(self):
        with channel.web_channel():
            await self.send_photo(detail=DETAIL_PENDING)
        self.assertEqual(self.text(), "⏳ Masih dibaca. Cek Bukti menunggu di beranda nanti.")
        self.assertEqual(self.created_request().source, "web_chat")
        self.assertEqual(self.db.executed, [])   # tanpa `notify`

    async def test_item_finished_before_notify_update_is_rendered_directly(self):
        self.db.rowcount = 0   # UPDATE bersyarat tidak mengenai baris: item sudah selesai
        pending = _item(DETAIL_PENDING)
        ready = _item(DETAIL_QRIS, id=pending.id)
        self.detail = DETAIL_QRIS
        self.item = pending
        self.db.items[pending.id] = ready   # dibaca ulang dari database: sudah `siap`
        self.status = MagicMock(message_id=501, edit_text=AsyncMock(), delete=AsyncMock())
        tg_file = MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"\xff\xd8jpg")))
        message = MagicMock(photo=[MagicMock(get_file=AsyncMock(return_value=tg_file))], document=None,
                            reply_text=AsyncMock(return_value=self.status))
        await handlers.handle_non_text(self._update(message), SimpleNamespace(bot=None))
        texts = [c.args[0] for c in self.status.edit_text.call_args_list]
        self.assertEqual(texts, [proof_message(DETAIL_QRIS)])   # tanpa "Masih dibaca"
        self.db.rollback.assert_awaited()

    async def test_rejected_uploads_edit_the_status_message(self):
        for exc in (intake.IntakeRejected(415, intake.MSG_TYPE), intake.IntakeRejected(413, intake.MSG_IMAGE_BIG),
                    intake.IntakeRejected(429, intake.MSG_RATE), intake.IntakeRejected(429, intake.MSG_PENDING)):
            with self.subTest(exc.detail):
                self.create.side_effect = exc
                await self.send_photo(detail=DETAIL_QRIS)
                self.assertEqual(self.text(), exc.detail)
                self.assertEqual(self.keyboard(), [])

    async def test_oversize_document_is_refused_without_download(self):
        for mime, size, expect in [("application/pdf", 10 * 1024 * 1024 + 1, intake.MSG_PDF_BIG),
                                   ("image/png", 8 * 1024 * 1024 + 1, intake.MSG_IMAGE_BIG)]:
            with self.subTest(mime):
                doc = MagicMock(mime_type=mime, file_size=size, get_file=AsyncMock())
                message = MagicMock(photo=None, document=doc, reply_text=AsyncMock())
                await handlers.handle_non_text(self._update(message), SimpleNamespace(bot=None))
                message.reply_text.assert_awaited_once_with(expect)
                doc.get_file.assert_not_awaited()
        self.create.assert_not_awaited()

    async def test_other_documents_keep_old_reply(self):
        message = MagicMock(photo=None, sticker=None, voice=None, audio=None,
                            document=MagicMock(mime_type="application/zip"), reply_text=AsyncMock())
        await handlers.handle_non_text(self._update(message), SimpleNamespace(bot=None))
        self.assertIn("📄 File belum didukung", message.reply_text.call_args.args[0])
        self.create.assert_not_awaited()

    async def test_image_document_goes_to_kotak(self):
        await self.send_document(b"\x89PNG x", "image/png", detail=DETAIL_QRIS)
        self.assertEqual((self.created_request().data, self.created_request().content_type), (b"\x89PNG x", "image/png"))

    async def test_skip_buttons_skip_with_reason(self):
        for data, reason in [(f"kx_{DETAIL_QRIS['id']}", "bukan_pengeluaran"), (f"kd_{DETAIL_QRIS['id']}", "duplikat")]:
            with self.subTest(data):
                self.skip.reset_mock()
                query = await self.press(data)
                self.skip.assert_awaited_once_with(self.db, UUID(DETAIL_QRIS["id"]), UID, reason)
                self.assertEqual(query.edit_message_text.call_args.args[0], "❌ Dilewati.")
        self.skip.return_value = False
        query = await self.press(f"kx_{DETAIL_QRIS['id']}")
        self.assertEqual(query.edit_message_text.call_args.args[0], "⚠️ Bukti ini tidak bisa dilewati.")

    async def test_note_button_asks_for_text_and_remembers_message(self):
        await self.send_photo(detail=DETAIL_QRIS)
        query = await self.press(f"kn_{self.key}")
        query.message.reply_text.assert_awaited_once_with("Ketik isi belanjaannya (atau /batal)")
        state = json.loads(self.redis.store["kotak:note:42"])
        self.assertEqual(state, {"key": self.key, "item_id": DETAIL_QRIS["id"], "message_id": 501})

    async def test_note_capture_edits_the_button_message(self):
        await self.send_photo(detail=DETAIL_QRIS)
        key = self.key
        await self.press(f"kn_{key}")
        self.assertTrue(await self.reply_text("bakso 2, es teh", detail_after_note=DETAIL_QRIS_NOTE))
        call = self.bot.edit_message_text.call_args
        self.assertEqual((call.kwargs["chat_id"], call.kwargs["message_id"]), (4242, 501))
        self.assertIn("📝 bakso 2, es teh (Siti Aminah)", call.args[0])
        rows = keyboard_of(call)
        self.assertEqual(rows[0][0].text, "🛒 Jajan")   # saran dihitung ulang dengan catatan, tanpa ⭐
        payload = json.loads(self.redis.store[f"txn:{key}"])
        self.assertEqual((payload["note"], payload["envs"]["0"]), ("bakso 2, es teh", str(JAJAN.id)))
        self.assertNotIn("kotak:note:42", self.redis.store)
        # pesan berikutnya bukan catatan lagi
        self.assertFalse(await self.reply_text("kopi 35k", detail_after_note=DETAIL_QRIS_NOTE))

    async def test_note_capture_falls_back_to_a_new_message_when_edit_fails(self):
        await self.send_photo(detail=DETAIL_QRIS)
        await self.press(f"kn_{self.key}")
        self.detail_note = DETAIL_QRIS_NOTE
        bot = MagicMock(edit_message_text=AsyncMock(side_effect=RuntimeError("Message to edit not found")))
        message = MagicMock(text="bakso", reply_text=AsyncMock())
        with self.assertLogs("jatahku.bot", "WARNING"):
            self.assertTrue(await receipt_cmd.capture_note(self._update(message), SimpleNamespace(bot=bot)))
        self.assertIn("📝 bakso 2, es teh (Siti Aminah)", message.reply_text.call_args.args[0])

    async def test_no_pending_note_and_redis_down_are_not_captured(self):
        message = MagicMock(text="kopi 35k", reply_text=AsyncMock())
        self.assertFalse(await receipt_cmd.capture_note(self._update(message), SimpleNamespace(bot=None)))
        with patch("redis.asyncio.from_url", side_effect=ConnectionError("redis mati")):
            self.assertFalse(await receipt_cmd.capture_note(self._update(message), SimpleNamespace(bot=None)))
        message.reply_text.assert_not_awaited()

    async def test_expired_session_buttons(self):
        for data in ("kn_dead1234", "ko_dead1234"):
            with self.subTest(data):
                query = await self.press(data)
                self.assertEqual(query.edit_message_text.call_args.args[0], "⏰ Session expired. Kirim ulang.")

    async def test_batal_cancels_pending_note_without_undoing_a_transaction(self):
        self.redis.store["kotak:note:42"] = json.dumps({"key": "k", "item_id": "i", "message_id": 1})
        message = MagicMock(text="/batal", reply_text=AsyncMock())
        with patch.object(handlers, "AsyncSessionLocal", new=MagicMock(side_effect=AssertionError("tidak boleh"))):
            await handlers.cmd_batal(self._update(message), None)
        message.reply_text.assert_awaited_once_with("❌ Tambah catatan dibatalkan.")
        self.assertNotIn("kotak:note:42", self.redis.store)

    async def test_proof_text_goes_to_kotak_and_plain_text_to_nlp(self):
        proof = "Transfer berhasil\nPenerima BUDI\nRp150.000\nNo. Ref 123"
        message = MagicMock(text=proof, reply_text=AsyncMock(return_value=MagicMock(message_id=9, edit_text=AsyncMock())))
        self.item = _item(DETAIL_TRANSFER)
        self.detail = DETAIL_TRANSFER
        self.db.items[self.item.id] = self.item
        await handlers.handle_message(self._update(message), SimpleNamespace(bot=None))
        self.assertEqual((self.created_request().text, self.created_request().data), (proof, None))
        message.reply_text.assert_awaited_once_with("🧾 Membaca bukti...")

        self.create.reset_mock()
        whatif = AsyncMock()
        for plain in ("kopi 35k", "kopi 20k\nroti 15k", "berhasil hemat hari ini", "bayar listrik 200rb berhasil"):
            with self.subTest(plain), patch("app.bot.checkin_cmd.is_whatif", return_value=True), \
                 patch("app.bot.checkin_cmd.handle_whatif", new=whatif):
                whatif.reset_mock()
                await handlers.handle_message(self._update(MagicMock(text=plain, reply_text=AsyncMock())), None)
                whatif.assert_awaited_once()   # sampai ke NLP
        self.create.assert_not_awaited()

    async def test_long_proof_text_passes_the_500_char_guard(self):
        proof = "Transfer berhasil\nPenerima BUDI\nRp150.000\nNo. Ref 123\n" + "Catatan " * 80
        self.item = _item(DETAIL_TRANSFER)
        self.detail = DETAIL_TRANSFER
        self.db.items[self.item.id] = self.item
        message = MagicMock(text=proof, reply_text=AsyncMock(return_value=MagicMock(message_id=9, edit_text=AsyncMock())))
        await handlers.handle_message(self._update(message), SimpleNamespace(bot=None))
        self.assertEqual(self.created_request().text, proof.strip())


class SendReadyMessageTests(unittest.IsolatedAsyncioTestCase):
    """Kabar Telegram untuk item yang selesai sesudah batas tunggu bot (`worker._notify_channel`)."""

    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 2.0   # mode debug asyncio: jeda GC bukan urusan tes ini
        self.db = FakeDb()
        self.bot = MagicMock(edit_message_text=AsyncMock(), send_message=AsyncMock())
        self.bot_cls = MagicMock(return_value=self.bot)
        for p in (patch.object(receipt_cmd, "AsyncSessionLocal", new=lambda: self.db),
                  patch("telegram.Bot", new=self.bot_cls),
                  patch("redis.asyncio.from_url", return_value=ChatRedis()),
                  patch.object(handlers, "get_household_id", new=AsyncMock(return_value=HID)),
                  patch.object(handlers, "get_envelopes_with_spent",
                               new=AsyncMock(return_value=[{"envelope": MAKAN}, {"envelope": JAJAN}])),
                  patch.object(view, "item_detail", new=AsyncMock(return_value=DETAIL_QRIS))):
            p.start()
            self.addCleanup(p.stop)

    def add(self, detail, meta):
        item = _item(detail, channel_meta=meta)
        self.db.items[item.id] = item
        return item

    async def test_ready_item_edits_the_status_message(self):
        item = self.add(DETAIL_QRIS, {"chat_id": 4242, "status_message_id": 501, "notify": True})
        await receipt_cmd.send_ready_message(item.id)
        call = self.bot.edit_message_text.call_args
        self.assertEqual(call.args[0], proof_message(DETAIL_QRIS))
        self.assertEqual((call.kwargs["chat_id"], call.kwargs["message_id"]), (4242, 501))
        self.assertEqual(keyboard_of(call)[0][0].text, "⭐ 🍜 Makan")
        self.bot.send_message.assert_not_awaited()

    async def test_failed_item_is_rendered_with_its_error(self):
        item = self.add(DETAIL_GAGAL, {"chat_id": 4242, "status_message_id": 501, "notify": True})
        await receipt_cmd.send_ready_message(item.id)
        self.assertEqual(self.bot.edit_message_text.call_args.args[0], "😕 PDF terkunci kata sandi")

    async def test_edit_failure_sends_a_new_message(self):
        self.bot.edit_message_text.side_effect = RuntimeError("Message to edit not found")
        item = self.add(DETAIL_QRIS, {"chat_id": 4242, "status_message_id": 501, "notify": True})
        with self.assertLogs("jatahku.bot", "WARNING"):
            await receipt_cmd.send_ready_message(item.id)
        call = self.bot.send_message.call_args
        self.assertEqual((call.args[0], call.args[1]), (4242, proof_message(DETAIL_QRIS)))

    async def test_items_without_notify_or_chat_are_a_silent_no_op(self):
        # rute HTTP menerima source=telegram tanpa channel_meta
        for meta in (None, {"chat_id": 4242}, {"notify": True}):
            with self.subTest(meta):
                item = self.add({**DETAIL_QRIS, "id": str(uuid4())}, meta)
                await receipt_cmd.send_ready_message(item.id)
        await receipt_cmd.send_ready_message(uuid4())   # item sudah tidak ada
        self.bot_cls.assert_not_called()


# ── ujung ke ujung: SQLite, intake dan worker sungguhan ───────────────────────

@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class KotakBotDbTests(TxnBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with self.Session() as db:
            await db.execute(update(User).where(User.id == self.a.id).values(telegram_id="42"))
            kecil = Envelope(household_id=self.hh.id, name="Kecil", emoji="🪙")
            harian = Envelope(household_id=self.hh.id, name="Harian", emoji="☕", daily_limit=D("10000"))
            db.add_all([kecil, harian])
            await db.flush()
            income = Income(household_id=self.hh.id, user_id=self.a.id, amount=D("110000"), description="Bonus",
                            income_date=date.today())
            db.add(income)
            await db.flush()
            db.add_all([Allocation(income_id=income.id, envelope_id=kecil.id, amount=D("10000")),
                        Allocation(income_id=income.id, envelope_id=harian.id, amount=D("100000"))])
            await db.commit()
            self.env["Kecil"], self.env["Harian"] = kecil, harian
        self.redis = ChatRedis()
        self.bot = MagicMock(edit_message_text=AsyncMock())
        self.items = []
        real_create = intake.create_item

        async def spy_create(db, req, **kw):
            item, created = await real_create(db, req, **kw)
            self.items.append(item.id)
            return item, created

        for p in (patch("redis.asyncio.from_url", return_value=self.redis),
                  patch.object(handlers, "AsyncSessionLocal", new=self.Session),
                  patch.object(receipt_cmd, "AsyncSessionLocal", new=self.Session),
                  patch.object(intake, "create_item", new=spy_create)):
            p.start()
            self.addCleanup(p.stop)

    # --- pembantu -------------------------------------------------------

    def worker_inline(self, lines, *, stale=False):
        """Penunggu: worker sungguhan membaca item (hasil OCR palsu) lalu item dikembalikan. `lines=None`: tidak
        diproses (habis waktu). `stale`: dikembalikan item sebelum diproses (worker selesai tepat sesudah batas
        tunggu). Jam bayar dibuat seperti `ready()` (SQLite menyimpan jam dinding apa adanya)."""
        async def wait(item_id, timeout_s, **kw):
            before = await self.get(item_id)
            if lines is not None and before.status in ("diterima", "diproses"):
                await process_item(item_id, session_factory=self.Session, extract=fake_extract(lines), now=NOW,
                                   proofs_enabled=True)
                if (await self.get(item_id)).paid_at is not None:
                    await self.set(item_id, paid_at=PAID)
            return before if stale else await self.get(item_id)
        return wait

    async def send(self, lines=CORPUS[0]["lines"], *, text=None, data=None, mime=None, stale=False, message_id=501):
        self.status = SimpleNamespace(message_id=message_id, edit_text=AsyncMock(), delete=AsyncMock())
        message = SimpleNamespace(photo=None, document=None, sticker=None, voice=None, audio=None, text=text,
                                  reply_text=AsyncMock(return_value=self.status))
        payload = data if data is not None else JPG + uuid4().bytes
        tg_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(payload)))
        if mime:
            message.document = SimpleNamespace(mime_type=mime, file_size=len(payload),
                                               get_file=AsyncMock(return_value=tg_file))
        elif text is None:
            message.photo = [SimpleNamespace(get_file=AsyncMock(return_value=tg_file))]
        update_ = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42, first_name="Ani"),
                                  effective_chat=SimpleNamespace(id=4242))
        with patch.object(waiter, "wait_for_item", new=self.worker_inline(lines, stale=stale)):
            if text is None:
                await handlers.handle_non_text(update_, SimpleNamespace(bot=self.bot))
            else:
                await handlers.handle_message(update_, SimpleNamespace(bot=self.bot))
        return self.status

    def texts(self):
        return [c.args[0] for c in self.status.edit_text.call_args_list]

    def rows(self):
        return keyboard_of(self.status.edit_text.call_args)

    def button(self, label):
        return next(b.callback_data for row in self.rows() for b in row if label in b.text)

    async def tap(self, data):
        query = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock(),
                                message=SimpleNamespace(message_id=501, reply_text=AsyncMock()),
                                from_user=SimpleNamespace(id=42, first_name="Ani"))
        update_ = SimpleNamespace(callback_query=query, effective_user=query.from_user,
                                  effective_chat=SimpleNamespace(id=4242))
        handler = next(h for pattern, h in handlers.bot_callbacks() if re.match(pattern, data))
        await handler(update_, SimpleNamespace(bot=self.bot))
        return query

    async def txns(self):
        async with self.Session() as db:
            return (await db.execute(select(Transaction).order_by(Transaction.created_at))).scalars().all()

    async def keywords(self):
        async with self.Session() as db:
            return {k.keyword for k in (await db.execute(select(UserEnvelopeKeyword))).scalars().all()}

    async def map_count(self, envelope="Makan"):
        mid = await self.merchant_id(QRIS_KEY)
        async with self.Session() as db:
            return (await db.execute(select(MerchantEnvelopeMap.count).where(
                MerchantEnvelopeMap.merchant_id == mid, MerchantEnvelopeMap.envelope_id == self.env[envelope].id))
            ).scalar_one_or_none()

    def other_session_claims(self, status="tercatat"):
        """`check_recordable` asli, lalu "sesi lain" (mis. web) mengklaim dan meng-commit bukti itu sebelum bot
        sempat meng-klaim. SQLite tidak bisa mengaburkan dua sesi sungguhan di satu koneksi, jadi klaim sesi lain
        ditulis lewat sesi bot lalu di-commit (pola test_kotak_transactions). `status`: hasil sesi lain."""
        real = record_mod.check_recordable

        async def racing(db, item_id, user):
            item = await real(db, item_id, user)
            await db.execute(update(ReceiptScan).where(ReceiptScan.id == item_id).values(status=status))
            await db.commit()
            return item
        return patch.object(record_mod, "check_recordable", racing)

    # --- ujung ke ujung --------------------------------------------------

    async def test_qris_photo_recorded_once_with_merchant_learning(self):
        await self.ready_qris()   # peta merchant rumah tangga: Makan x1
        await self.send()
        [text] = self.texts()
        self.assertEqual(text, "QRIS · Siti Aminah · Bandung\nRp 25.000 · 26 Okt 08.12 · Berhasil\n\nMasuk ke amplop mana?")
        self.assertEqual(self.rows()[0][0].text, "⭐ 📁 Makan")
        item_id = self.items[-1]
        self.assertEqual((await self.get(item_id)).source, "telegram")

        query = await self.tap(self.rows()[0][0].callback_data)
        self.assertIn("✅ Rp25rb — Siti Aminah (QRIS)", query.edit_message_text.call_args.args[0])
        [txn] = await self.txns()
        self.assertEqual((txn.amount, txn.description, txn.transaction_date, txn.envelope_id, txn.user_id),
                         (D("25000"), "Siti Aminah (QRIS)", date(2026, 10, 26), self.env["Makan"].id, self.a.id))
        item = await self.get(item_id)
        self.assertEqual((item.status, item.transaction_ids), ("tercatat", [str(txn.id)]))
        self.assertEqual(await self.map_count(), 2)   # peta merchant belajar sekali
        self.assertFalse({"siti", "aminah", "qris"} & await self.keywords())   # nama merchant bukan kata kunci

    async def test_note_becomes_description_and_only_note_is_learned(self):
        await self.send()
        key = self.button("Makan").split("_")[1]
        query = await self.tap(f"kn_{key}")
        query.message.reply_text.assert_awaited_once_with("Ketik isi belanjaannya (atau /batal)")
        note = SimpleNamespace(photo=None, document=None, text="bakso 2, es teh", reply_text=AsyncMock())
        update_ = SimpleNamespace(message=note, effective_user=SimpleNamespace(id=42, first_name="Ani"),
                                  effective_chat=SimpleNamespace(id=4242))
        await handlers.handle_message(update_, SimpleNamespace(bot=self.bot))
        note.reply_text.assert_not_awaited()   # tidak dibaca NLP sebagai pengeluaran
        edit = self.bot.edit_message_text.call_args
        self.assertEqual(edit.kwargs["message_id"], 501)
        self.assertIn("📝 bakso 2, es teh (Siti Aminah)", edit.args[0])
        jajan = next(b.callback_data for row in keyboard_of(edit) for b in row if "Jajan" in b.text)
        await self.tap(jajan)
        [txn] = await self.txns()
        self.assertEqual((txn.description, txn.envelope_id), ("bakso 2, es teh (Siti Aminah)", self.env["Jajan"].id))
        learned = await self.keywords()
        self.assertIn("bakso", learned)
        self.assertFalse({"siti", "aminah"} & learned)

    async def test_pdf_and_proof_text_become_kotak_items(self):
        await self.send(CORPUS[2]["lines"], data=b"%PDF-1.4\n%x\n", mime="application/pdf")
        self.assertTrue(self.texts()[-1].startswith("Transfer · Budi Santoso\nRp 152.500 · "))
        pdf = await self.get(self.items[-1])
        self.assertEqual((pdf.content_type, pdf.source, pdf.doc_type), ("application/pdf", "telegram", "transfer"))
        await self.send(CORPUS[0]["lines"], text="\n".join(CORPUS[0]["lines"]))
        self.assertTrue(self.texts()[-1].startswith("QRIS · Siti Aminah"))
        self.assertEqual((await self.get(self.items[-1])).content_type, "text/plain")

    async def test_unsupported_image_document_is_rejected_by_intake(self):
        await self.send(data=b"GIF89a....", mime="image/gif")
        self.assertEqual(self.texts(), [intake.MSG_TYPE])
        self.assertEqual(self.items, [])

    async def test_store_receipt_keeps_old_message_and_leaves_the_inbox_when_recorded(self):
        await self.send(STORE_LINES)
        [text] = self.texts()
        self.assertTrue(text.startswith("🧾 Struk Alfamart · 14 Okt 2026\nTotal: Rp 45.400"), text)
        self.assertTrue(text.endswith("Masuk ke amplop mana?"))
        self.assertNotIn("Sisa scan", text)
        item_id = self.items[-1]
        self.assertIn(f"struk_fix_{item_id}", datas(self.rows()))
        await self.tap(self.button("Jajan"))
        [txn] = await self.txns()
        self.assertEqual((txn.amount, txn.transaction_date), (D("45400"), date(2026, 10, 14)))
        item = await self.get(item_id)
        self.assertEqual((item.status, item.transaction_ids), ("tercatat", [str(txn.id)]))
        self.assertEqual(item.outcome, "accepted")   # umpan balik belajar struk tetap jalan
        async with self.Session() as db:   # struk belanja tidak mengajari peta merchant
            self.assertEqual((await db.execute(select(func.count()).select_from(MerchantEnvelopeMap))).scalar(), 0)

    async def test_cancel_and_skip_buttons_move_items_out_of_the_inbox(self):
        for data_of, reason in [(lambda i: f"struk_no_{i}", "batal"), (lambda i: f"kx_{i}", "bukan_pengeluaran"),
                                (lambda i: f"kd_{i}", "duplikat")]:
            item = await self.ready_qris()
            with self.subTest(reason):
                query = await self.tap(data_of(item.id))
                got = await self.get(item.id)
                self.assertEqual((got.status, got.channel_meta["skip_reason"]), ("dilewati", reason))
                self.assertIn(query.edit_message_text.call_args.args[0], ("❌ Dilewati.", "❌ Struk dibatalkan."))
        recorded = await self.ready_qris()
        await self.set(recorded.id, status="tercatat")
        query = await self.tap(f"kx_{recorded.id}")
        self.assertEqual(query.edit_message_text.call_args.args[0], "⚠️ Bukti ini tidak bisa dilewati.")
        self.assertEqual((await self.get(recorded.id)).status, "tercatat")

    async def test_store_receipt_cancel_keeps_discard_feedback(self):
        await self.send(STORE_LINES)
        item_id = self.items[-1]
        query = await self.tap(f"struk_no_{item_id}")
        self.assertEqual(query.edit_message_text.call_args.args[0], "❌ Struk dibatalkan.")
        item = await self.get(item_id)
        self.assertEqual((item.status, item.outcome, item.ocr_lines), ("dilewati", "discarded", None))

    # --- C1: tidak pernah tercatat dua kali, di semua jalur catat bot --------

    async def test_proof_claimed_elsewhere_before_commit_is_not_recorded(self):
        await self.send()
        with self.other_session_claims():
            query = await self.tap(self.button("Makan"))
        self.assertEqual(query.edit_message_text.call_args.args[0], "✅ Bukti ini sudah tercatat.")
        self.assertEqual(await self.txns(), [])

    async def test_expired_proof_message_has_a_single_period(self):
        await self.send()
        await self.set(self.items[-1], status="kedaluwarsa")
        query = await self.tap(self.button("Makan"))
        self.assertEqual(query.edit_message_text.call_args.args[0], "⚠️ Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya.")
        self.assertEqual(await self.txns(), [])

    async def test_proof_expired_before_commit_says_so(self):
        await self.send()
        with self.other_session_claims("kedaluwarsa"):
            query = await self.tap(self.button("Makan"))
        self.assertEqual(query.edit_message_text.call_args.args[0], "⚠️ Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya.")
        self.assertEqual(await self.txns(), [])
        self.assertEqual((await self.get(self.items[-1])).status, "kedaluwarsa")

    async def test_fund_shift_path_claims_too(self):
        await self.send()
        query = await self.tap(self.button("Kecil"))   # sisa 10rb, bukti 25rb → tawaran geser dana
        offer = query.edit_message_text.call_args
        self.assertIn("Dana amplop kurang", offer.args[0])
        shift = next(b.callback_data for row in keyboard_of(offer) for b in row if "Makan" in b.text)
        with self.other_session_claims():
            query = await self.tap(shift)
        self.assertEqual(query.edit_message_text.call_args.args[0], "✅ Bukti ini sudah tercatat.")
        self.assertEqual(await self.txns(), [])
        self.assertEqual(await self.remaining("Kecil"), D("10000"))   # dana tidak digeser

    async def test_daily_limit_path_claims_too(self):
        await self.send()
        query = await self.tap(self.button("Harian"))   # limit harian 10rb
        offer = query.edit_message_text.call_args
        self.assertIn("Limit harian terlampaui", offer.args[0])
        with self.other_session_claims():
            query = await self.tap(keyboard_of(offer)[0][0].callback_data)
        self.assertEqual(query.edit_message_text.call_args.args[0], "✅ Bukti ini sudah tercatat.")
        self.assertEqual(await self.txns(), [])

    async def test_fund_shift_and_daily_limit_paths_mark_the_proof_recorded(self):
        await self.send()
        offer = (await self.tap(self.button("Harian"))).edit_message_text.call_args
        await self.tap(keyboard_of(offer)[0][0].callback_data)
        [txn] = await self.txns()
        item = await self.get(self.items[-1])
        self.assertEqual((item.status, item.transaction_ids, txn.envelope_id),
                         ("tercatat", [str(txn.id)], self.env["Harian"].id))

        await self.send(CORPUS[1]["lines"])
        offer = (await self.tap(self.button("Kecil"))).edit_message_text.call_args
        await self.tap(next(b.callback_data for row in keyboard_of(offer) for b in row if "Makan" in b.text))
        txn = (await self.txns())[-1]
        item = await self.get(self.items[-1])
        self.assertEqual((item.status, item.transaction_ids, txn.envelope_id),
                         ("tercatat", [str(txn.id)], self.env["Kecil"].id))

    async def test_already_recorded_proof_is_refused_at_press(self):
        await self.send()
        await self.set(self.items[-1], status="tercatat")
        query = await self.tap(self.button("Makan"))
        self.assertEqual(query.edit_message_text.call_args.args[0], "✅ Bukti ini sudah tercatat.")
        self.assertEqual(await self.txns(), [])

    async def test_failed_transfer_cannot_be_recorded_by_an_old_button(self):
        await self.send()
        item_id = self.items[-1]
        item = await self.get(item_id)
        await self.set(item_id, document={**item.document, "checks": [{"level": "block", "message": "gagal"}]})
        query = await self.tap(self.button("Makan"))
        self.assertEqual(query.edit_message_text.call_args.args[0], "⚠️ Transaksi gagal, tidak bisa dicatat.")
        self.assertEqual(await self.txns(), [])

    # --- C3: kabar Telegram tanpa balapan -----------------------------------

    async def test_slow_item_is_announced_by_the_worker(self):
        await self.send(lines=None)
        self.assertEqual(self.texts(), ["⏳ Masih dibaca, nanti kukabari."])
        item_id = self.items[-1]
        self.assertEqual((await self.get(item_id)).channel_meta,
                         {"chat_id": 4242, "status_message_id": 501, "notify": True})
        bot = MagicMock(edit_message_text=AsyncMock(), send_message=AsyncMock())
        with patch("telegram.Bot", return_value=bot):
            self.assertEqual(await process_item(item_id, session_factory=self.Session,
                                                extract=fake_extract(CORPUS[0]["lines"]), now=NOW,
                                                proofs_enabled=True), "siap")
        call = bot.edit_message_text.call_args
        self.assertTrue(call.args[0].startswith("QRIS · Siti Aminah"))
        self.assertEqual((call.kwargs["chat_id"], call.kwargs["message_id"]), (4242, 501))
        self.assertTrue(datas(keyboard_of(call))[0].startswith("t_"))

    async def test_item_finished_before_the_bots_update_is_rendered_directly(self):
        hook = AsyncMock()
        with patch.object(receipt_cmd, "send_ready_message", new=hook):
            await self.send(stale=True)   # worker selesai tepat sesudah batas tunggu
        self.assertEqual(len(self.texts()), 1)
        self.assertTrue(self.texts()[0].startswith("QRIS · Siti Aminah"))
        hook.assert_not_awaited()
        self.assertNotIn("notify", (await self.get(self.items[-1])).channel_meta)

    async def test_web_chat_slow_item_has_no_notify(self):
        user = SimpleNamespace(id=self.a.id, name="Ani")
        with patch.object(waiter, "wait_for_item", new=self.worker_inline(None)):
            ops = await web_adapter.run_photo(user, JPG + uuid4().bytes, "image/jpeg")
        self.assertEqual(ops[-1]["text"], "⏳ Masih dibaca. Cek Bukti menunggu di beranda nanti.")
        item = await self.get(self.items[-1])
        self.assertEqual(item.source, "web_chat")
        self.assertNotIn("notify", item.channel_meta)

    # --- C5: "sudah tercatat {tgl} di {amplop}" -------------------------------

    async def test_resent_recorded_proof_names_date_and_envelope(self):
        await self.send()
        await self.tap(self.button("Makan"))
        await self.send()   # file lain, nomor referensi sama
        self.assertEqual(self.texts(), ["✅ Bukti ini sudah tercatat 26 Okt di Makan."])
        self.assertEqual(self.rows(), [])

    async def test_recorded_in_another_members_personal_envelope_hides_its_name(self):
        theirs = await self.ready(CORPUS[0]["lines"], owner=self.b)
        txn = await self.add_txn(amount=25000, description="Siti Aminah (QRIS)", created_at=NOW, on=date(2026, 10, 26),
                                 user=self.b, envelope="Pribadi B")
        await self.set(theirs.id, status="tercatat", transaction_ids=[str(txn.id)])
        await self.send()
        self.assertEqual(self.texts(), ["✅ Bukti ini sudah tercatat 26 Okt."])

    # --- catatan yang ditunggu tidak membajak ketikan sesudah bukti diurus (fix 1) ----

    async def type_text(self, text):
        """Ketikan biasa lewat `handle_message` (NLP sungguhan); pesan tombol bukti yang diedit dicatat `self.bot`."""
        message = SimpleNamespace(photo=None, document=None, text=text, reply_text=AsyncMock())
        update_ = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42, first_name="Ani"),
                                  effective_chat=SimpleNamespace(id=4242))
        self.bot.edit_message_text.reset_mock()
        await handlers.handle_message(update_, SimpleNamespace(bot=self.bot))
        return message

    async def ask_note(self):
        await self.send()
        await self.tap(f"kn_{self.button('Makan').split('_')[1]}")
        self.assertIn("kotak:note:42", self.redis.store)

    async def assert_typing_reaches_nlp(self):
        before = len(await self.txns())
        message = await self.type_text("kopi 35k")
        self.bot.edit_message_text.assert_not_awaited()   # pesan bukti lama tidak diedit lagi
        self.assertEqual(message.reply_text.await_count, 1)
        self.assertIn("Rp35rb — kopi", message.reply_text.call_args.args[0])   # dijawab NLP
        self.assertEqual(len(await self.txns()), before + 1)
        self.assertEqual((await self.txns())[-1].description, "kopi")
        self.assertNotIn("kotak:note:42", self.redis.store)

    async def test_note_pending_then_skipped_typing_goes_to_nlp(self):
        await self.ask_note()
        await self.tap(f"kx_{self.items[-1]}")
        self.assertEqual((await self.get(self.items[-1])).status, "dilewati")
        await self.assert_typing_reaches_nlp()

    async def test_note_pending_then_recorded_typing_goes_to_nlp(self):
        await self.ask_note()
        await self.tap(self.button("Makan"))
        await self.assert_typing_reaches_nlp()

    async def test_note_pending_then_recorded_through_daily_limit_typing_goes_to_nlp(self):
        await self.ask_note()
        offer = (await self.tap(self.button("Harian"))).edit_message_text.call_args
        confirm = await self.tap(keyboard_of(offer)[0][0].callback_data)
        done = confirm.edit_message_text.call_args.args[0]
        await self.assert_typing_reaches_nlp()
        self.assertEqual(confirm.edit_message_text.call_args.args[0], done)   # pesan sukses tidak ditimpa

    async def test_note_pending_then_cancelled_typing_goes_to_nlp(self):
        await self.ask_note()
        await self.tap(f"struk_no_{self.items[-1]}")
        await self.assert_typing_reaches_nlp()

    async def test_stale_note_is_ignored_when_the_item_left_siap_elsewhere(self):
        await self.ask_note()
        await self.set(self.items[-1], status="tercatat")   # dicatat lewat web; tidak ada tombol bot yang ditekan
        self.assertIn("kotak:note:42", self.redis.store)
        await self.assert_typing_reaches_nlp()

    async def test_stale_note_is_ignored_when_its_button_session_is_gone(self):
        await self.ask_note()
        key = json.loads(self.redis.store["kotak:note:42"])["key"]
        self.redis.store.pop(f"txn:{key}")
        await self.assert_typing_reaches_nlp()

    # --- bukti yang sama dikirim lagi selagi dibaca (fix 2) ------------------

    async def test_same_proof_sent_again_while_waiting_keeps_the_first_promise(self):
        photo = JPG + uuid4().bytes
        await self.send(lines=None, data=photo, message_id=501)
        self.assertEqual(self.texts(), ["⏳ Masih dibaca, nanti kukabari."])
        await self.send(lines=None, data=photo, message_id=502)
        self.assertEqual(self.texts(),
                         ["⏳ Bukti ini sudah dikirim tadi dan masih dibaca. Hasilnya nanti di pesan sebelumnya."])
        self.assertEqual(len(set(self.items)), 1)   # satu item
        item_id = self.items[0]
        self.assertEqual((await self.get(item_id)).channel_meta,
                         {"chat_id": 4242, "status_message_id": 501, "notify": True})
        bot = MagicMock(edit_message_text=AsyncMock(), send_message=AsyncMock())
        with patch("telegram.Bot", return_value=bot):
            await process_item(item_id, session_factory=self.Session, extract=fake_extract(CORPUS[0]["lines"]),
                               now=NOW, proofs_enabled=True)
        bot.edit_message_text.assert_awaited_once()
        self.assertEqual(bot.edit_message_text.call_args.kwargs["message_id"], 501)   # pesan pertama yang diedit
        self.assertTrue(bot.edit_message_text.call_args.args[0].startswith("QRIS · Siti Aminah"))

    async def test_same_proof_sent_again_after_reading_is_rendered_on_the_new_message(self):
        photo = JPG + uuid4().bytes
        await self.send(data=photo, message_id=501)
        await self.send(data=photo, message_id=502)
        self.assertEqual(len(set(self.items)), 1)
        self.assertTrue(self.texts()[-1].startswith("QRIS · Siti Aminah"))
        self.assertTrue(datas(self.rows())[0].startswith("t_"))

    async def test_same_proof_from_another_channel_still_gets_a_telegram_promise(self):
        async with self.Session() as db:   # dibagikan lewat PWA dulu, belum dibaca
            req = intake.IntakeRequest(await db.get(User, self.a.id), "pwa_share", data=JPG + b"pwa",
                                       content_type="image/jpeg")
            item, _ = await intake.create_item(db, req)
        await self.send(lines=None, data=JPG + b"pwa", message_id=503)
        self.assertEqual(self.texts(), ["⏳ Masih dibaca, nanti kukabari."])
        self.assertEqual((await self.get(item.id)).channel_meta,
                         {"chat_id": 4242, "status_message_id": 503, "notify": True})

    async def test_web_chat_same_proof_while_waiting_points_to_the_waiting_list(self):
        photo = JPG + uuid4().bytes
        await self.send(lines=None, data=photo, message_id=501)
        user = SimpleNamespace(id=self.a.id, name="Ani")
        with patch.object(waiter, "wait_for_item", new=self.worker_inline(None)):
            ops = await web_adapter.run_photo(user, photo, "image/jpeg")
        self.assertEqual(ops[-1]["text"],
                         "⏳ Bukti ini sudah dikirim tadi dan masih dibaca. Cek Bukti menunggu di beranda nanti.")
        self.assertEqual((await self.get(self.items[0])).channel_meta,
                         {"chat_id": 4242, "status_message_id": 501, "notify": True})

    # --- chat web ---------------------------------------------------------

    async def test_web_chat_note_edits_the_original_message_and_records_as_webapp(self):
        user = SimpleNamespace(id=self.a.id, name="Ani")
        with patch.object(waiter, "wait_for_item", new=self.worker_inline(CORPUS[0]["lines"])):
            ops = await web_adapter.run_photo(user, JPG + uuid4().bytes, "image/jpeg")
        self.assertEqual([o["type"] for o in ops], ["message", "edit"])
        msg_id = ops[0]["id"]
        self.assertEqual(ops[1]["id"], msg_id)
        self.assertTrue(ops[1]["text"].startswith("QRIS · Siti Aminah"))
        note_btn = next(b["data"] for row in ops[1]["buttons"] for b in row if b["data"].startswith("kn_"))
        ops = await web_adapter.run_action(user, msg_id, note_btn)
        self.assertEqual(ops[-1]["text"], "Ketik isi belanjaannya (atau /batal)")
        ops = await web_adapter.run_message(user, "bakso 2, es teh")
        [edit] = ops
        self.assertEqual((edit["type"], edit["id"]), ("edit", msg_id))
        self.assertIn("📝 bakso 2, es teh (Siti Aminah)", edit["text"])
        makan = next(b["data"] for row in edit["buttons"] for b in row if "Makan" in b["text"])
        await web_adapter.run_action(user, msg_id, makan)
        [txn] = await self.txns()
        self.assertEqual((txn.description, txn.source.value), ("bakso 2, es teh (Siti Aminah)", "webapp"))

    async def remaining(self, name):
        async with self.Session() as db:
            rows = await handlers.get_envelopes_with_spent(self.hh.id, db, self.a.id)
        return next(r["remaining"] for r in rows if r["envelope"].name == name)


if __name__ == "__main__":
    unittest.main()
