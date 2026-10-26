"""Bot (Telegram dan chat web): bukti bayar dan struk masuk Kotak Struk, lalu dicatat lewat tombol (spec 2026-10-26
bagian 5a).

Foto, dokumen gambar, PDF, dan teks bukti → `intake.create_item` (source `telegram` atau `web_chat`) → tunggu worker
paling lama `WAIT_BOT_S` → pesan hasil yang menggantikan "🧾 Membaca bukti...":
- QRIS/transfer: `proof_message` dengan tombol amplop (saran teratas, ⭐ bila yakin), "✏️ Tambah catatan",
  "🚫 Bukan pengeluaran", dan "❌ Batal"; atau tawaran lewati (top-up, uang masuk, rekening sendiri, duplikat lunak);
  atau pemberitahuan saja (transaksi gagal, sudah tercatat).
- Struk belanja dan tidak dikenali: pesan struk yang lama (rincian, cocok/selisih), tanpa baris kuota scan.
- Lewat batas tunggu: Telegram dikabari worker lewat `send_ready_message`; chat web melihatnya di "Bukti menunggu".

Pencatatan memakai callback `t_{key}_{idx}` yang sudah ada (handle_txn_callback) dengan payload Redis `txn:{key}`:
"date" (tanggal struk/bayar) dan "scan_id" (id item), ditambah untuk bukti bayar "kind": "proof", "item_id", "note".
"""
import json
import logging
import re
import secrets
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.channel import is_web
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.models import ReceiptScan, User
from app.services.kotak_struk import intake, record, view, waiter
from app.services.kotak_struk.config import (
    IMAGE_MAX_BYTES, NOTE_TTL_S, PDF_MAX_BYTES, PROOF_TYPES, ST_DIPROSES, ST_DITERIMA, ST_GAGAL, WAIT_BOT_S,
)
from app.services.kotak_struk.merchants import display_name
from app.services.kotak_struk.readers.labels import WIB

logger = logging.getLogger("jatahku.bot")

TXN_TTL = 600                       # detik; sesi tombol `txn:{key}` sama dengan alur bot lain
NOTE_KEY = "kotak:note:{}"          # catatan yang ditunggu dari user (tombol "✏️ Tambah catatan")
WAITING = (ST_DITERIMA, ST_DIPROSES)

MSG_READING = "🧾 Membaca bukti..."
MSG_WAIT_TELEGRAM = "⏳ Masih dibaca, nanti kukabari."
MSG_WAIT_WEB = "⏳ Masih dibaca. Cek Bukti menunggu di beranda nanti."
MSG_UNREADABLE = "😕 Bukti tidak bisa dibaca. Coba kirim ulang."
MSG_SEND_FILE = "📄 Kirim bukti sebagai foto (JPG/PNG) atau PDF."
MSG_FAILED_TXN = "⚠️ Transaksi ini gagal di bank, jadi tidak dicatat."
MSG_ALREADY_RECORDED = "✅ Bukti ini sudah tercatat."
MSG_SKIPPED = "❌ Dilewati."
MSG_ASK_NOTE = "Ketik isi belanjaannya (atau /batal)"
MSG_NOTE_CANCELLED = "❌ Tambah catatan dibatalkan."
MSG_EXPIRED = "⏰ Session expired. Kirim ulang."
MSG_NO_ENVELOPE = "Belum ada amplop. Ketik /template untuk buat."
ASK_ENVELOPE = "Masuk ke amplop mana?"

PROOF_LABEL = {"qris": "QRIS", "transfer": "Transfer"}
PAY_STATUS = {"berhasil": "Berhasil", "pending": "Pending"}
SKIP_TEXT = {
    "top_up": "ℹ️ Ini top-up saldo, bukan pengeluaran.",
    "masuk": "ℹ️ Ini uang masuk, bukan pengeluaran.",
    "antar_rekening_sendiri": "ℹ️ Sepertinya transfer ke rekeningmu sendiri. Bukan pengeluaran?",
}

CONF_TEXT = {
    "tinggi": "✅ cocok dengan pembayaran",
    "sedang": "⚠️ cek lagi nominalnya",
    "rendah": "⚠️ kurang yakin, mohon dicek",
}

BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

# Teks bukti yang ditempel (bukan ketikan): semua syarat ini harus terpenuhi (spec 5a).
_PROOF_AMOUNT = re.compile(r"\b(?:rp|idr)\.?\s*\d", re.IGNORECASE)
_PROOF_STATUS = re.compile(r"\b(?:berhasil|sukses|successful)\b", re.IGNORECASE)
_PROOF_LABEL = re.compile(r"\b(?:referensi|ref|rrn|merchant|penerima|tujuan|nmid)\b", re.IGNORECASE)


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "hari ini"
    y, m, d = iso.split("-")
    return f"{int(d)} {BULAN[int(m) - 1]} {y}"


def _rp(n) -> str:
    return "Rp " + f"{int(n):,}".replace(",", ".")


MAX_ITEM_LINES = 12
MAX_ADJ_LINES = 5
MAX_SUMMARY_CHARS = 2500  # pesan Telegram maks 4096 karakter


def _items_summary(result: dict) -> str:
    """Rincian ringkas untuk pesan bot (teks biasa, tanpa Markdown)."""
    items = result.get("items") or []
    rec = result.get("reconciliation") or {}
    if not items:
        return ""
    n = len(items)
    if rec.get("status") == "cocok":
        head = f"Rincian {n} barang ✅ cocok dengan total"
    else:
        diff = rec.get("diff") or 0
        word = "kurang" if diff > 0 else "lebih"
        head = f"Rincian {n} barang ⚠️ {word} {_rp(abs(diff))} dari total"
    lines = [head]
    for it in items[:MAX_ITEM_LINES]:
        name = (it.get("name") or "Barang")[:28]
        row = f"• {name}  {_rp(it.get('amount') or 0)}"
        if it.get("discount"):
            row += f" (voucher −{_rp(it['discount'])})"
        if it.get("flag") == "cek":
            sug = it.get("suggestion")
            row += " ⚠️ " + ("terbaca dobel?" if sug == 0 else f"mungkin {_rp(sug)}?" if sug else "cek")
        lines.append(row)
    if n > MAX_ITEM_LINES:
        lines.append(f"… +{n - MAX_ITEM_LINES} barang lagi")
    adjustments = result.get("adjustments") or []
    for adj in adjustments[:MAX_ADJ_LINES]:
        sign = "−" if adj.get("kind") == "discount" else "+"
        lines.append(f"{(adj.get('label') or 'Penyesuaian')[:28]}  {sign}{_rp(adj.get('amount') or 0)}")
    if len(adjustments) > MAX_ADJ_LINES:
        lines.append(f"… +{len(adjustments) - MAX_ADJ_LINES} penyesuaian lagi")
    if rec.get("status") != "cocok":
        lines.append("💡 Koreksi rincian & pecah per amplop: tombol + → Pengeluaran → Struk."
                     if is_web() else
                     "💡 Koreksi rincian & pecah per amplop bisa di webapp (tombol Struk).")
    text = "\n".join(lines)
    return text if len(text) <= MAX_SUMMARY_CHARS else text[:MAX_SUMMARY_CHARS - 1] + "…"


# ── pembantu murni ──────────────────────────────────────────────────────────

def looks_like_proof_text(text: str) -> bool:
    """Teks bukti bayar yang ditempel (bukan ketikan biasa): minimal 2 baris, nominal Rp/IDR, kata status
    (berhasil/sukses/successful), dan minimal satu label (referensi, ref, rrn, merchant, penerima, tujuan, nmid)."""
    text = text or ""
    if sum(1 for line in text.splitlines() if line.strip()) < 2:
        return False
    return bool(_PROOF_AMOUNT.search(text) and _PROOF_STATUS.search(text) and _PROOF_LABEL.search(text))


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _wib(iso: str | None) -> datetime | None:
    """Waktu ISO dari `item_detail` dalam WIB. Tanpa zona dianggap UTC (seperti `dedup.soft_duplicate`)."""
    if not iso:
        return None
    try:
        value = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(WIB)


def _day(value) -> str:
    """"26 Okt" dari tanggal (atau teks ISO)."""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.day} {BULAN[value.month - 1]}"


def _clock(value: datetime) -> str:
    return f"{value.hour:02d}.{value.minute:02d}"


def _total(detail: dict) -> int | None:
    return ((detail.get("document") or {}).get("amounts") or {}).get("total")


def _prompt(detail: dict) -> str:
    """Apa yang ditanyakan pesan bukti: blocked (hanya pemberitahuan), skip (bukan pengeluaran?), soft (duplikat
    lunak?), atau ready (pilih amplop)."""
    flags = detail.get("flags") or {}
    if flags.get("blocked"):
        return "blocked"
    if flags.get("skip_suggestion") in SKIP_TEXT:
        return "skip"
    if (flags.get("duplicate_of") or {}).get("kind") == "soft":
        return "soft"
    return "ready"


def _ready_only(detail: dict) -> dict:
    """Detail tanpa tawaran lewati (user sudah memilih "Tetap catat"/"Beda, catat" atau menulis catatan)."""
    flags = dict(detail.get("flags") or {})
    flags["skip_suggestion"] = None
    if (flags.get("duplicate_of") or {}).get("kind") == "soft":
        flags["duplicate_of"] = None
    return {**detail, "flags": flags}


def _recorded_text(recorded: dict | None) -> str:
    if not recorded or not recorded.get("date"):
        return MSG_ALREADY_RECORDED
    day = _day(recorded["date"])
    if recorded.get("envelope_name"):
        return f"✅ Bukti ini sudah tercatat {day} di {recorded['envelope_name']}."
    return f"✅ Bukti ini sudah tercatat {day}."


def proof_message(detail: dict, *, recorded: dict | None = None, note: str | None = None) -> str:
    """Pesan bot untuk bukti bayar (QRIS/transfer) dari `view.item_detail`. `recorded` = `{date, envelope_name}`
    transaksi yang sudah mencatat bukti ini (`view.recorded_summary`); `note` = catatan user (keterangannya
    ditampilkan)."""
    flags = detail.get("flags") or {}
    if flags.get("blocked") == view.BLOCKED_FAILED:
        return MSG_FAILED_TXN
    if flags.get("blocked"):
        return _recorded_text(recorded)

    doc = detail.get("document") or {}
    city = (doc.get("counterparty") or {}).get("city")
    who = [PROOF_LABEL.get(detail.get("doc_type"), "Bukti"), (detail.get("merchant") or {}).get("name"),
           display_name(city) if city else None]
    paid = _wib(detail.get("paid_at"))
    total = _total(detail)
    what = [_rp(total) if total else None, f"{_day(paid)} {_clock(paid)}" if paid else None,
            PAY_STATUS.get(doc.get("status"))]
    lines = [" · ".join(p for p in who if p), " · ".join(p for p in what if p)]
    lines += [f"⚠️ {w}" for w in flags.get("warnings") or []]
    if note:
        lines.append(f"📝 {detail.get('description_preview') or note}")

    prompt = _prompt(detail)
    if prompt == "skip":
        ask = SKIP_TEXT[flags["skip_suggestion"]]
    elif prompt == "soft":
        txn = flags["duplicate_of"].get("transaction") or {}
        at = _wib(txn.get("created_at"))
        ask = f'🤔 Mirip "{txn.get("description")}" yang dicatat {_clock(at) if at else "tadi"}. Sama?'
    else:
        ask = ASK_ENVELOPE
    return "\n".join(lines) + "\n\n" + ask


# ── Redis ────────────────────────────────────────────────────────────────────

def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(get_settings().REDIS_URL)


async def _save_payload(key: str, payload: dict) -> None:
    r = _redis()
    try:
        await r.set(f"txn:{key}", json.dumps(payload), ex=TXN_TTL)
    finally:
        await r.aclose()


async def _load_payload(key: str | None) -> dict | None:
    if not key:
        return None
    r = _redis()
    try:
        raw = await r.get(f"txn:{key}")
    finally:
        await r.aclose()
    return json.loads(raw) if raw else None


async def cancel_note(tg_user_id) -> bool:
    """/batal saat bot menunggu catatan: hapus `kotak:note:{tg}`. True bila memang ada yang ditunggu."""
    try:
        r = _redis()
        try:
            return bool(await r.getdel(NOTE_KEY.format(tg_user_id)))
        finally:
            await r.aclose()
    except Exception:
        return False   # Redis mati: /batal berjalan seperti biasa


# ── pesan hasil ─────────────────────────────────────────────────────────────

async def _store_reply(db, user, item, detail) -> tuple[str, InlineKeyboardMarkup | None]:
    """Pesan struk yang lama (struk belanja dan tidak dikenali), tanpa baris kuota scan."""
    from app.bot.handlers import get_envelopes_with_spent, get_household_id
    from app.services.kotak_struk.document import scan_receipt_response
    from app.services.txn_nlp import find_best_envelope

    result = scan_receipt_response(item, detail)
    total = result.get("total")
    merchant = result.get("merchant") or "Belanja"
    if not total:
        # Tanpa parse_mode: nama toko dari OCR bisa mengandung karakter Markdown.
        return ("😕 Total struk tidak terbaca.\n\n"
                "Tips: foto tegak lurus, terang, tanpa bayangan. Atau ketik manual, misalnya:\n"
                f"{merchant.lower()} 45rb"), None

    hid = await get_household_id(user, db)
    payday_day = getattr(user, "payday_day", 1) or 1
    envs = [e for e in await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
            if str(getattr(e["envelope"], "purpose", "expense")) not in ("saving", "sinking_fund")]
    if not envs:
        return MSG_NO_ENVELOPE, None
    suggested, confident = await find_best_envelope(merchant, hid, db, user_id=user.id)
    if suggested and confident:   # amplop yang disarankan di urutan teratas
        envs.sort(key=lambda e: e["envelope"].id != suggested.id)

    txn_key = secrets.token_hex(4)
    await _save_payload(txn_key, {
        "amount": int(total), "desc": merchant,
        "envs": {str(i): str(e["envelope"].id) for i, e in enumerate(envs)},
        "date": result.get("date"), "scan_id": result.get("scan_id"),
    })
    keyboard = []
    for i, e in enumerate(envs):
        env = e["envelope"]
        star = "⭐ " if (suggested and confident and env.id == suggested.id) else ""
        keyboard.append([InlineKeyboardButton(f"{star}{env.emoji or '📁'} {env.name}", callback_data=f"t_{txn_key}_{i}")])
    keyboard.append([InlineKeyboardButton("✏️ Nominal salah", callback_data=f"struk_fix_{result['scan_id']}"),
                     InlineKeyboardButton("❌ Batal", callback_data=f"struk_no_{result['scan_id']}")])

    conf = CONF_TEXT.get(result.get("confidence"), "")
    if result.get("confidence") == "tinggi" and result.get("confidence_source") == "items":
        conf = "✅ cocok dengan rincian barang"
    elif result.get("confidence_source") == "items_sum":
        conf = "⚠️ dihitung dari rincian, cek dengan struk"
    summary = _items_summary(result)
    text = (f"🧾 Struk {merchant} · {_fmt_date(result.get('date'))}\n"
            f"Total: {_rp(total)}  {conf}\n\n"
            + (f"{summary}\n\n" if summary else "")
            + ASK_ENVELOPE)
    return text, InlineKeyboardMarkup(keyboard)


async def _proof_reply(db, user, detail, *, recorded=None, key=None, note=None) -> tuple[str, InlineKeyboardMarkup | None]:
    """Pesan bukti bayar + tombolnya; payload `txn:{key}` (baru, atau yang sudah ada bila `key`) diperbarui."""
    from app.bot.handlers import _spendable_rows, get_envelopes_with_spent, get_household_id

    text = proof_message(detail, recorded=recorded, note=note)
    prompt = _prompt(detail)
    if prompt == "blocked":
        return text, None
    hid = await get_household_id(user, db)
    payday_day = getattr(user, "payday_day", 1) or 1
    envs = _spendable_rows(await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day))
    if not envs:
        return MSG_NO_ENVELOPE, None
    suggestion = detail.get("suggestion") or {}
    suggested = suggestion.get("envelope_id")
    if suggested:   # yang disarankan teratas; ⭐ hanya bila yakin
        envs.sort(key=lambda e: str(e["envelope"].id) != suggested)

    key = key or secrets.token_hex(4)
    item_id = detail["id"]
    paid = _wib(detail.get("paid_at"))
    await _save_payload(key, {
        "amount": int(_total(detail)), "desc": detail.get("description_preview"),
        "envs": {str(i): str(e["envelope"].id) for i, e in enumerate(envs)},
        "date": paid.date().isoformat() if paid else None, "scan_id": item_id,
        "kind": "proof", "item_id": item_id, "note": note,
    })
    if prompt == "skip":
        rows = [[InlineKeyboardButton("Oke, lewati", callback_data=f"kx_{item_id}"),
                 InlineKeyboardButton("Tetap catat", callback_data=f"ko_{key}")]]
    elif prompt == "soft":
        rows = [[InlineKeyboardButton("Sama, lewati", callback_data=f"kd_{item_id}"),
                 InlineKeyboardButton("Beda, catat", callback_data=f"ko_{key}")]]
    else:
        rows = []
        for i, e in enumerate(envs):
            env = e["envelope"]
            star = "⭐ " if suggestion.get("confident") and str(env.id) == suggested else ""
            rows.append([InlineKeyboardButton(f"{star}{env.emoji or '📁'} {env.name}", callback_data=f"t_{key}_{i}")])
        rows.append([InlineKeyboardButton("✏️ Tambah catatan", callback_data=f"kn_{key}")])
        rows.append([InlineKeyboardButton("🚫 Bukan pengeluaran", callback_data=f"kx_{item_id}"),
                     InlineKeyboardButton("❌ Batal", callback_data=f"struk_no_{item_id}")])
    return text, InlineKeyboardMarkup(rows)


async def _result_reply(db, user, item, *, key=None, note=None, ready=False) -> tuple[str, InlineKeyboardMarkup | None]:
    """Pesan hasil untuk item yang sudah selesai dibaca. `ready`: langsung tombol amplop (tanpa tawaran lewati);
    `key`/`note`: sesi tombol yang sudah ada dan catatan user."""
    if item is None:
        return MSG_UNREADABLE, None
    if item.status in WAITING:
        return (MSG_WAIT_WEB if is_web() else MSG_WAIT_TELEGRAM), None
    if item.status == ST_GAGAL:
        return f"😕 {item.error or 'Bukti tidak bisa dibaca. Coba kirim ulang.'}", None
    detail = await view.item_detail(db, item, user, note=note)
    if ready:
        detail = _ready_only(detail)
    flags = detail.get("flags") or {}
    recorded = (await view.recorded_summary(db, item, user, flags)
                if flags.get("blocked") == view.BLOCKED_RECORDED else None)
    if detail.get("doc_type") in PROOF_TYPES and _total(detail):
        return await _proof_reply(db, user, detail, recorded=recorded, key=key, note=note)
    if flags.get("blocked"):   # struk/tidak dikenali yang sudah tercatat (file sama) atau gagal: tanpa tombol catat
        return proof_message(detail, recorded=recorded), None
    return await _store_reply(db, user, item, detail)


async def _own_item(db, item_id, user) -> ReceiptScan | None:
    item = await db.get(ReceiptScan, item_id) if item_id is not None else None
    return item if item is not None and item.user_id == user.id else None


# ── masuk Kotak Struk ───────────────────────────────────────────────────────

async def _download(message) -> tuple[bytes, str] | None:
    """Foto terbesar, dokumen gambar, atau dokumen PDF. Dokumen di atas batasnya → IntakeRejected 413 tanpa
    diunduh. Selain itu None."""
    if message.photo:
        tg_file = await message.photo[-1].get_file()
        mime = "image/jpeg"
    else:
        doc = message.document
        mime = (getattr(doc, "mime_type", None) or "") if doc else ""
        if mime == "application/pdf":
            limit, too_big = PDF_MAX_BYTES, intake.MSG_PDF_BIG
        elif mime.startswith("image/"):
            limit, too_big = IMAGE_MAX_BYTES, intake.MSG_IMAGE_BIG
        else:
            return None
        if (doc.file_size or 0) > limit:
            raise intake.IntakeRejected(413, too_big)
        tg_file = await doc.get_file()
    return bytes(await tg_file.download_as_bytearray()), mime


async def _promise_notification(status, item, meta: dict) -> bool:
    """Item belum selesai saat batas tunggu habis (Telegram): nyalakan `notify` dengan satu UPDATE bersyarat
    (`diterima`/`diproses`). Pesan "Masih dibaca" dikirim SEBELUM commit, jadi worker yang selesai sesudahnya (dan
    mengedit pesan yang sama) tidak tertimpa. False: item sudah selesai (UPDATE tidak mengenai baris), pemanggil
    merender hasilnya sendiri dan worker tidak mengabari."""
    async with AsyncSessionLocal() as db:
        done = await db.execute(
            update(ReceiptScan).where(ReceiptScan.id == item.id, ReceiptScan.status.in_(WAITING))
            .values(channel_meta={**(item.channel_meta or {}), **meta, "notify": True})
            .execution_options(synchronize_session=False)
        )
        if done.rowcount != 1:
            await db.rollback()
            return False
        try:
            await status.edit_text(MSG_WAIT_TELEGRAM)
        finally:
            await db.commit()
    return True


async def _take_in(update, **upload) -> None:
    """Satu unggahan (file atau teks) → item Kotak Struk → pesan hasil di pesan status "🧾 Membaca bukti..."."""
    from app.bot.handlers import _is_setup_complete, get_or_create_user
    from app.bot.tglogin_cmd import reply_setup_needed

    tg_user = update.effective_user
    status = await update.message.reply_text(MSG_READING)
    meta = {"chat_id": getattr(getattr(update, "effective_chat", None), "id", None),
            "status_message_id": status.message_id}
    try:
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
            setup_ok, _ = await _is_setup_complete(user, db)
            if not setup_ok:
                await status.delete()
                await reply_setup_needed(update, user)
                return
            user_id = user.id
            req = intake.IntakeRequest(user, "web_chat" if is_web() else "telegram", channel_meta=meta, **upload)
            try:
                item, _created = await intake.create_item(db, req)
            except intake.IntakeRejected as exc:
                await status.edit_text(exc.detail)
                return
            item_id = item.id
            await db.commit()   # item lama dikembalikan dengan transaksi baca terbuka: jangan ditahan selama menunggu

        item = await waiter.wait_for_item(item_id, WAIT_BOT_S)
        if item is not None and item.status in WAITING:
            if is_web():
                await status.edit_text(MSG_WAIT_WEB)
                return
            if await _promise_notification(status, item, meta):
                return
        async with AsyncSessionLocal() as db:
            text, markup = await _result_reply(db, await db.get(User, user_id), await db.get(ReceiptScan, item_id))
        await status.edit_text(text, reply_markup=markup)
    except Exception:
        logger.exception("bukti dari bot gagal diproses")
        try:   # pesan "Membaca bukti..." tidak boleh menggantung
            await status.edit_text(MSG_UNREADABLE)
        except Exception:
            pass


async def handle_receipt_document(update, context):
    """Foto, dokumen gambar, atau dokumen PDF → Kotak Struk → pesan hasil."""
    message = update.message
    try:
        downloaded = await _download(message)
    except intake.IntakeRejected as exc:
        await message.reply_text(exc.detail)
        return
    if not downloaded:
        await message.reply_text(MSG_SEND_FILE)
        return
    data, mime = downloaded
    await _take_in(update, data=data, content_type=mime)


handle_receipt_photo = handle_receipt_document   # nama lama


async def handle_proof_text(update, context, text: str) -> None:
    """Teks bukti bayar yang ditempel (`looks_like_proof_text`) → Kotak Struk → pesan hasil."""
    await _take_in(update, text=text)


# ── kabar Telegram untuk item yang selesai lewat batas tunggu ────────────────

async def send_ready_message(item_id) -> None:
    """Dipanggil worker untuk item ber-`notify` (siap atau gagal): edit pesan status Telegram menjadi pesan hasil;
    gagal edit (pesan terhapus) → kirim pesan baru. Berdasarkan `channel_meta` (`notify` dan `chat_id`), bukan
    `source`: item tanpa keduanya (mis. dari rute HTTP dengan source=telegram) diabaikan tanpa galat."""
    async with AsyncSessionLocal() as db:
        item = await db.get(ReceiptScan, item_id)
        meta = (item.channel_meta or {}) if item is not None else {}
        if not meta.get("notify") or meta.get("chat_id") is None:
            return
        user = await db.get(User, item.user_id)
        if user is None:
            return
        text, markup = await _result_reply(db, user, item)

    from telegram import Bot
    bot = Bot(token=get_settings().TELEGRAM_BOT_TOKEN)
    chat_id = meta["chat_id"]
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=meta.get("status_message_id"),
                                    reply_markup=markup)
    except Exception as exc:
        logger.warning("pesan status bukti %s tidak bisa diedit (%s); dikirim pesan baru", item_id, exc)
        await bot.send_message(chat_id, text, reply_markup=markup)


# ── tombol ──────────────────────────────────────────────────────────────────

async def handle_kotak_callback(update, context):
    """kn_{key} tambah catatan · kx_{item_id} bukan pengeluaran · kd_{item_id} duplikat (lewati) ·
    ko_{key} tetap catat (tampilkan tombol amplop)."""
    from app.bot.handlers import get_or_create_user

    query = update.callback_query
    await query.answer()
    action, _, arg = (query.data or "").partition("_")
    tg_user = update.effective_user

    if action in ("kx", "kd"):
        item_id = _uuid(arg)
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
            reason = "bukan_pengeluaran" if action == "kx" else "duplikat"
            done = item_id is not None and await record.skip_item(db, item_id, user.id, reason)
        await query.edit_message_text(MSG_SKIPPED if done else f"⚠️ {record.MSG_CANNOT_SKIP}.")
        return

    payload = await _load_payload(arg)
    if payload is None:
        await query.edit_message_text(MSG_EXPIRED)
        return
    if action == "kn":
        r = _redis()
        try:
            await r.set(NOTE_KEY.format(tg_user.id), json.dumps({
                "key": arg, "item_id": payload.get("item_id"), "message_id": query.message.message_id,
            }), ex=NOTE_TTL_S)
        finally:
            await r.aclose()
        await query.message.reply_text(MSG_ASK_NOTE)
    elif action == "ko":
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
            item = await _own_item(db, _uuid(payload.get("item_id")), user)
            if item is None:
                text, markup = MSG_EXPIRED, None
            else:
                text, markup = await _result_reply(db, user, item, key=arg, note=payload.get("note"), ready=True)
        await query.edit_message_text(text, reply_markup=markup)


async def _edit_message(update, context, message_id, text, markup) -> None:
    """Edit pesan bot lain (pesan tombol bukti) lewat `context.bot`; gagal → kirim sebagai pesan baru."""
    try:
        await context.bot.edit_message_text(text, chat_id=update.effective_chat.id, message_id=message_id,
                                            reply_markup=markup)
    except Exception as exc:
        if "not modified" in str(exc).lower():
            return
        logger.warning("pesan tombol bukti tidak bisa diedit (%s); dikirim pesan baru", exc)
        await update.message.reply_text(text, reply_markup=markup)


async def capture_note(update, context) -> bool:
    """Teks sesudah "✏️ Tambah catatan" menjadi catatan bukti (sebelum NLP): payload diperbarui (keterangan,
    catatan, urutan amplop menurut saran dengan catatan), pesan tombol aslinya diedit. False bila tidak ada catatan
    yang ditunggu (atau Redis mati): teks diproses seperti biasa."""
    from app.bot.handlers import get_or_create_user

    tg_user = update.effective_user
    try:
        r = _redis()
        try:
            raw = await r.getdel(NOTE_KEY.format(tg_user.id))
        finally:
            await r.aclose()
    except Exception:
        return False
    if not raw:
        return False
    state = json.loads(raw)
    note = (update.message.text or "").strip()
    payload = await _load_payload(state.get("key"))
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        item = await _own_item(db, _uuid(state.get("item_id")), user) if payload is not None else None
        if item is None:
            text = None
        else:
            text, markup = await _result_reply(db, user, item, key=state["key"], note=note, ready=True)
    if text is None:
        await update.message.reply_text(MSG_EXPIRED)
    else:
        await _edit_message(update, context, state.get("message_id"), text, markup)
    return True


async def handle_struk_callback(update, context):
    """struk_no_{item_id} = batal; struk_fix_{item_id} = nominal salah → catat manual. Item Kotak Struk keluar dari
    "Bukti menunggu" (`dilewati`, alasan batal); umpan balik belajar struk belanja (dan scan lama) tetap dicatat."""
    from app.bot.handlers import get_or_create_user
    from app.services.receipt_scan import apply_feedback

    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 2)
    if len(parts) < 3:
        return
    action, scan_id = parts[1], parts[2]
    item_id = _uuid(scan_id)
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(update.effective_user.id), update.effective_user.first_name, db)
        item = await db.get(ReceiptScan, item_id) if item_id is not None else None
        kotak = item is not None and item.status is not None
        store = item is None or item.doc_type == record.STORE_RECEIPT or item.status is None
        try:
            if kotak:
                await record.skip_item(db, item_id, user.id, "batal")
            if store:
                await apply_feedback(user, scan_id, db, saved=False, wrong=(action == "fix"))
        except Exception as exc:  # best-effort
            logger.warning("feedback struk gagal: %s", exc)
    if action == "fix":
        await query.edit_message_text(
            "✏️ Oke, ketik manual nominal yang benar, misalnya:\n`indomaret 140500`\n\n"
            "Laporan ini membantu scan struk makin akurat 🙏", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Struk dibatalkan.")


# ── jalur catat bot ─────────────────────────────────────────────────────────

async def learn_text_for_scan(db, scan_id, description: str) -> str | None:
    """`learn_text` untuk `after_expense_recorded` dari payload tombol: catatan user tanpa nama merchant untuk bukti
    bayar (`record.learn_text_for_item`); None (belajar dari keterangan utuh, perilaku lama) bila `scan_id` kosong,
    bukan id, struk belanja, atau item tidak ada. Galat → "" (tidak belajar apa pun, nama merchant tidak bocor)."""
    item_id = _uuid(scan_id) if scan_id else None
    if item_id is None:
        return None
    try:
        return await record.learn_text_for_item(db, item_id, description)
    except Exception:
        logger.warning("learn_text_for_item gagal untuk item %s; kata kunci tidak dipelajari", item_id, exc_info=True)
        return ""
