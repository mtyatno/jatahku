"""Bot (Telegram dan chat web): bukti bayar dan struk masuk Kotak Struk, lalu dicatat lewat tombol (spec 2026-10-26
bagian 5a).

Foto, dokumen gambar, PDF, dan teks bukti → `intake.create_item` (source `telegram` atau `web_chat`) → tunggu worker
paling lama `WAIT_BOT_S` → pesan hasil yang menggantikan "🧾 Membaca bukti...":
- QRIS/transfer: `proof_message` dengan tombol amplop (saran teratas, ⭐ bila yakin), "✏️ Tambah catatan",
  "🚫 Bukan pengeluaran", dan "❌ Batal"; atau tawaran lewati (top-up, uang masuk, rekening sendiri, duplikat lunak);
  atau pemberitahuan saja (transaksi gagal, sudah tercatat).
- Struk belanja dan tidak dikenali: pesan struk yang lama (rincian, cocok/selisih), tanpa baris kuota scan.
- Lewat batas tunggu: Telegram dikabari worker lewat `send_ready_message`; chat web menanyakan hasilnya sendiri
  (gelembung "Masih dibaca" membawa id item; panel memanggil `web_adapter.run_bukti` → `reply_item_result`).

Pencatatan memakai callback `t_{key}_{idx}` yang sudah ada (handle_txn_callback) dengan payload Redis `txn:{key}`:
"date" (tanggal struk/bayar) dan "scan_id" (id item), ditambah untuk bukti bayar "kind": "proof", "item_id", "note".

Tanggal dokumen sebelum awal periode anggaran berjalan user (Task H1): tombol amplop diganti pertanyaan "Catat untuk
tanggal berapa?" (`kt_{key}_h` hari ini, `kt_{key}_d` tanggal dokumen, `handle_date_callback`). Jawabannya mengubah
payload yang sama: "date" hari ini, atau "past_period" (dicatat di tanggal dokumen tanpa geser dana dan limit
harian); keduanya "date_answered". Tanggal yang belum lewat (salah baca) langsung dicatat hari ini.

Nominal kurang yakin (Task H3): payload menyimpan "confidence" (keyakinan total: struk `item.confidence`, bukti
`document.confidence.total`) dan "noun" ("struk"/"bukti"). Total `rendah` → ketukan amplop belum mencatat, pesannya
menjadi pertanyaan `amount_question` (handlers._handle_txn_callback): "Ya, catat ke ..." (`ky_{key}_{idx}`, jalur catat
yang sama dengan `t_`), "Nominal salah" (`struk_fix_`), "Batal" (`struk_no_`). Bot tidak memecah struk per barang
(itu di webapp), jadi satu pertanyaan sebelum satu-satunya pencatatan.

Nominal ketikan sesudah "Nominal salah" (plan 2026-11-01 Task L2b, pre-flight K4): `struk_fix_` yang melewati item
QRIS/transfer/tidak dikenali menyimpan `kotak:fix:{id user chat}` = id item (TTL `FIX_TTL_S`). Ketikan berikutnya user
itu (`note_fix_amount`, dari handlers.handle_message) mengambil kunci itu sekali; satu nominal → suara koreksi nominal
untuk item (`belajar.learn_from_correction`). Ketikannya tetap ke NLP dan dicatat persis seperti biasa, tidak tertaut ke
item.
"""
import asyncio
import json
import logging
import re
import secrets
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.channel import find_chat_user, is_web
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.period import document_date_kind, get_budget_period
from app.models.models import ReceiptScan, User
from app.services.kotak_struk import belajar, intake, record, view, waiter
from app.services.kotak_struk.config import (
    FIX_TTL_S, IMAGE_MAX_BYTES, LAYOUT_TYPES, NOTE_TTL_S, PDF_MAX_BYTES, PROOF_TYPES, ST_DILEWATI, ST_DIPROSES,
    ST_DITERIMA, ST_GAGAL, ST_KEDALUWARSA, ST_SIAP, WAIT_BOT_S,
)
from app.services.kotak_struk.merchants import display_name
from app.services.kotak_struk.readers.labels import WIB

logger = logging.getLogger("jatahku.bot")

TXN_TTL = 600                       # detik; sesi tombol `txn:{key}` sama dengan alur bot lain
NOTE_KEY = "kotak:note:{}"          # catatan yang ditunggu dari user (tombol "✏️ Tambah catatan")
FIX_KEY = "kotak:fix:{}"            # item yang nominalnya salah: ketikan berikutnya = suara koreksi (`note_fix_amount`)
WAITING = (ST_DITERIMA, ST_DIPROSES)

MSG_READING = "🧾 Membaca bukti..."
MSG_WAIT_TELEGRAM = "⏳ Masih dibaca, nanti kukabari."
MSG_WAIT_WEB = "⏳ Masih dibaca, nanti kukabari di sini."
MSG_SAME_TELEGRAM = "⏳ Bukti ini sudah dikirim tadi dan masih dibaca. Hasilnya nanti di pesan sebelumnya."
MSG_SAME_WEB = "⏳ Bukti ini sudah dikirim tadi dan masih dibaca. Hasilnya nanti di sini."
MSG_UNREADABLE = "😕 Bukti tidak bisa dibaca. Coba kirim ulang."
MSG_GONE_WEB = "😕 Bukti ini sudah tidak ada. Kirim ulang fotonya."   # /bot/chat/bukti: item hilang atau bukan milik user
MSG_EXPIRED = f"⚠️ {record.MSG_EXPIRED}."                             # bukti bayar kedaluwarsa (struk tetap bisa dicatat)
MSG_SEND_FILE = "📄 Kirim bukti sebagai foto (JPG/PNG) atau PDF."
MSG_FAILED_TXN = "⚠️ Transaksi ini gagal di bank, jadi tidak dicatat."
MSG_ALREADY_RECORDED = "✅ Bukti ini sudah tercatat."
MSG_SKIPPED = "❌ Dilewati."
MSG_ASK_NOTE = "Ketik isi belanjaannya (atau /batal)"
MSG_NOTE_CANCELLED = "❌ Tambah catatan dibatalkan."
MSG_NOTE_BUSY = "⏳ Sedang diproses, kirim ulang catatannya."
MSG_NOTE_LATE = "⚠️ Bukti ini sudah diproses, catatannya tidak ditambahkan."
NOTE_LOCK_TRIES = 20      # catatan menunggu kunci sesi tombol (tombol amplop/tanggal yang sedang diproses) ...
NOTE_LOCK_WAIT_S = 0.1    # ... paling lama 20 × 0,1 detik
MSG_SESSION_EXPIRED = "⏰ Session expired. Kirim ulang."
MSG_FIX_PROOF = "✏️ Oke, ketik manual nominal yang benar, misalnya:\n`bakso 25000`"   # "Nominal salah" bukti bayar
MSG_NO_ENVELOPE = "Belum ada amplop. Ketik /template untuk buat."
ASK_ENVELOPE = "Masuk ke amplop mana?"

# Tanggal dokumen di luar periode berjalan (Task H1). {noun}: "struk" (struk belanja, tidak dikenali) atau "bukti".
ASK_DATE = "📅 Tanggal di {noun}: {doc} — di luar periode sekarang ({period}). Catat untuk tanggal berapa?"
DATE_FUTURE = "📅 Tanggal di {noun} ({doc}) belum lewat — dicatat hari ini."
DATE_SET = "📅 Dicatat untuk {day}"
BTN_DATE_TODAY = "📅 Hari ini ({day})"
BTN_DATE_DOC = "📅 {day}"
DATE_ANSWERED = "date_answered"   # payload `txn:{key}`: pertanyaan tanggal sudah dijawab

# Nominal kurang yakin (Task H3): ditanya saat tombol amplop diketuk, sebelum dicatat.
ASK_AMOUNT = "Nominal {amount} belum pasti — cek dengan {noun}. Sudah benar?"
BTN_AMOUNT_OK = "✅ Ya, catat ke {emoji} {name}"
AMOUNT_OK = "ky"                  # callback `ky_{key}_{idx}`: nominal dikonfirmasi, catat ke amplop idx
TXN_LOCK = "txnlock:{}"           # kunci sesi tombol yang sama dengan tombol amplop (handlers.handle_txn_callback)

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


def short_date(value: date, today: date) -> str:
    """"26 Okt"; dengan tahun bila bukan tahun `today` ("30 Sep 2025")."""
    text = f"{value.day} {BULAN[value.month - 1]}"
    return text if value.year == today.year else f"{text} {value.year}"


def period_label(start: date, end: date, today: date) -> str:
    """"27 Okt–26 Nov" (tahun tiap tanggal seperti `short_date`)."""
    return f"{short_date(start, today)}–{short_date(end, today)}"


def _iso_day(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


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


def _proof_reading(detail: dict, note: str | None = None) -> str:
    """Teks bacaan bukti bayar tanpa pertanyaannya: pihak, nominal/waktu/status, peringatan, dan catatan user."""
    flags = detail.get("flags") or {}
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
    return "\n".join(lines)


def proof_message(detail: dict, *, recorded: dict | None = None, note: str | None = None) -> str:
    """Pesan bot untuk bukti bayar (QRIS/transfer) dari `view.item_detail`. `recorded` = `{date, envelope_name}`
    transaksi yang sudah mencatat bukti ini (`view.recorded_summary`); `note` = catatan user (keterangannya
    ditampilkan)."""
    flags = detail.get("flags") or {}
    if flags.get("blocked") == view.BLOCKED_FAILED:
        return MSG_FAILED_TXN
    if flags.get("blocked"):
        return _recorded_text(recorded)

    prompt = _prompt(detail)
    if prompt == "skip":
        ask = SKIP_TEXT[flags["skip_suggestion"]]
    elif prompt == "soft":
        txn = flags["duplicate_of"].get("transaction") or {}
        at = _wib(txn.get("created_at"))
        ask = f'🤔 Mirip "{txn.get("description")}" yang dicatat {_clock(at) if at else "tadi"}. Sama?'
    else:
        ask = ASK_ENVELOPE
    return _proof_reading(detail, note) + "\n\n" + ask


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


async def _txn_lock(key: str):
    """Kunci sesi tombol `txnlock:{key}` (SET NX, 30 dtk), sama dengan tombol amplop (handlers.handle_txn_callback):
    jawaban tanggal, "Tetap catat", dan catatan yang menulis ulang `txn:{key}` tidak saling menyalip, jadi pesan yang
    tampil dan payload-nya selalu dari render yang sama. Klien Redis bila didapat (lepas dengan `_txn_unlock`), False
    bila sedang dipakai, None bila Redis mati (lanjut tanpa kunci, seperti tombol amplop)."""
    try:
        r = _redis()
    except Exception:
        return None
    try:
        if await r.set(TXN_LOCK.format(key), "1", nx=True, ex=30):
            return r
        busy = False
    except Exception:
        busy = None
    try:
        await r.aclose()
    except Exception:
        pass
    return busy


async def _txn_unlock(key: str, lock) -> None:
    """Lepas kunci yang didapat `_txn_lock` (False/None: tidak ada yang dilepas)."""
    if lock is None or lock is False:
        return
    try:
        await lock.delete(TXN_LOCK.format(key))
        await lock.aclose()
    except Exception:
        pass   # kunci habis sendiri setelah 30 dtk


async def forget_note(tg_user_id) -> bool:
    """Hapus catatan yang ditunggu (`kotak:note:{tg}`): /batal, dan setiap tombol catat/lewati (bukti sudah diurus,
    ketikan berikutnya bukan catatan lagi). True bila memang ada yang ditunggu. Redis mati: False, tanpa galat."""
    try:
        r = _redis()
        try:
            return bool(await r.getdel(NOTE_KEY.format(tg_user_id)))
        finally:
            await r.aclose()
    except Exception:
        return False


# ── pesan hasil ─────────────────────────────────────────────────────────────

def _second_row(payload: dict) -> list:
    """Baris tombol di bawah amplop (atau pertanyaan tanggal): bukti "Bukan pengeluaran" + "Batal", struk "Nominal
    salah" + "Batal"."""
    if payload.get("kind") == "proof":
        item_id = payload["item_id"]
        return [InlineKeyboardButton("🚫 Bukan pengeluaran", callback_data=f"kx_{item_id}"),
                InlineKeyboardButton("❌ Batal", callback_data=f"struk_no_{item_id}")]
    scan_id = payload["scan_id"]
    return [InlineKeyboardButton("✏️ Nominal salah", callback_data=f"struk_fix_{scan_id}"),
            InlineKeyboardButton("❌ Batal", callback_data=f"struk_no_{scan_id}")]


def needs_amount_check(payload: dict) -> bool:
    """Total dokumen ini kurang yakin: ketukan amplop ditanya dulu (`amount_question`)."""
    return payload.get("confidence") == "rendah"


def amount_question(key: str, env_idx: str, payload: dict, envelope) -> tuple[str, InlineKeyboardMarkup]:
    """Pertanyaan nominal kurang yakin untuk amplop yang diketuk: "Ya, catat ke {amplop}" (`ky_{key}_{idx}`),
    "Nominal salah" (`struk_fix_`, catat manual), dan "Batal" (`struk_no_`)."""
    amount = "Rp" + f"{int(payload['amount']):,}".replace(",", ".")
    text = ASK_AMOUNT.format(amount=amount, noun=payload.get("noun") or "struk")
    rows = [[InlineKeyboardButton(BTN_AMOUNT_OK.format(emoji=envelope.emoji or "📁", name=envelope.name),
                                  callback_data=f"{AMOUNT_OK}_{key}_{env_idx}")]]
    scan_id = payload.get("scan_id")
    if scan_id:
        rows.append([InlineKeyboardButton("✏️ Nominal salah", callback_data=f"struk_fix_{scan_id}"),
                     InlineKeyboardButton("❌ Batal", callback_data=f"struk_no_{scan_id}")])
    return text, InlineKeyboardMarkup(rows)


def _envelope_reply(key: str, payload: dict, reading: str, labels: list[str],
                    line: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    """Pesan tombol amplop: teks bacaan (+ `line` tanggal), "Masuk ke amplop mana?", satu tombol per amplop (`t_{key}_{i}`,
    urutan `payload["envs"]`), "Tambah catatan" untuk bukti, lalu `_second_row`."""
    proof = payload.get("kind") == "proof"
    if line:   # bukti: satu baris di blok bacaan (seperti peringatan dan catatan); struk: paragraf sendiri
        reading += ("\n" if proof else "\n\n") + line
    rows = [[InlineKeyboardButton(label, callback_data=f"t_{key}_{i}")] for i, label in enumerate(labels)]
    if proof:
        rows.append([InlineKeyboardButton("✏️ Tambah catatan", callback_data=f"kn_{key}")])
    rows.append(_second_row(payload))
    return f"{reading}\n\n{ASK_ENVELOPE}", InlineKeyboardMarkup(rows)


def _date_question(key: str, payload: dict, reading: str, doc_day: date, today: date,
                   period: tuple[date, date]) -> tuple[str, InlineKeyboardMarkup]:
    """Dokumen dari periode lalu: pertanyaan tanggal menggantikan "Masuk ke amplop mana?", tombol "Hari ini" dan
    tanggal dokumen (`kt_{key}_h` / `kt_{key}_d`) menggantikan tombol amplop; `_second_row` tetap."""
    noun = "bukti" if payload.get("kind") == "proof" else "struk"
    ask = ASK_DATE.format(noun=noun, doc=short_date(doc_day, today), period=period_label(*period, today))
    rows = [[InlineKeyboardButton(BTN_DATE_TODAY.format(day=short_date(today, today)), callback_data=f"kt_{key}_h"),
             InlineKeyboardButton(BTN_DATE_DOC.format(day=short_date(doc_day, today)), callback_data=f"kt_{key}_d")],
            _second_row(payload)]
    return f"{reading}\n\n{ask}", InlineKeyboardMarkup(rows)


async def _dated_reply(key: str, payload: dict, payday_day: int, reading: str, labels: list[str], *,
                       old: dict | None = None) -> tuple[str, InlineKeyboardMarkup]:
    """Simpan payload `txn:{key}` lalu susun pesan tombol amplopnya menurut tanggal dokumen (`payload["date"]`)
    terhadap periode berjalan (Task H1): sebelum awal periode → tanya dulu dicatat untuk tanggal berapa (teks bacaan
    dan label tombol amplop ikut disimpan untuk jawabannya, `handle_date_callback`); belum lewat (salah baca) →
    dicatat hari ini dengan satu baris keterangan; tanpa tanggal atau di periode berjalan → seperti biasa. `old`:
    payload sesi tombol yang sama (render ulang sesudah "Tetap catat" atau catatan): jawaban tanggalnya tetap
    berlaku."""
    today = date.today()
    answered = _iso_day(old.get("date")) if old and old.get(DATE_ANSWERED) else None
    line = None
    if answered is not None:
        payload.update({k: old[k] for k in ("date", "past_period") if k in old})
        payload[DATE_ANSWERED] = True
        line = DATE_SET.format(day=short_date(answered, today))
    else:
        doc_day = _iso_day(payload.get("date"))
        kind = document_date_kind(doc_day, payday_day=payday_day, today=today)
        if kind == "past":
            payload.update(reading=reading, labels=labels)
            await _save_payload(key, payload)
            return _date_question(key, payload, reading, doc_day, today, get_budget_period(payday_day, today))
        if kind == "future":
            noun = "bukti" if payload.get("kind") == "proof" else "struk"
            line = DATE_FUTURE.format(noun=noun, doc=short_date(doc_day, today))
            payload["date"] = today.isoformat()
    await _save_payload(key, payload)
    return _envelope_reply(key, payload, reading, labels, line)


async def _store_reply(db, user, item, detail) -> tuple[str, InlineKeyboardMarkup | None]:
    """Pesan struk yang lama (struk belanja dan tidak dikenali), tanpa baris kuota scan; tanggal struk di luar periode
    berjalan lewat `_dated_reply`."""
    from app.bot.handlers import get_envelopes_with_spent, ruang_keluarga
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

    hid = await ruang_keluarga(user, db)
    payday_day = getattr(user, "payday_day", 1) or 1
    envs = [e for e in await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
            if str(getattr(e["envelope"], "purpose", "expense")) not in ("saving", "sinking_fund")]
    if not envs:
        return MSG_NO_ENVELOPE, None
    suggested, confident = await find_best_envelope(merchant, hid, db, user_id=user.id)
    if suggested and confident:   # amplop yang disarankan di urutan teratas
        envs.sort(key=lambda e: e["envelope"].id != suggested.id)

    txn_key = secrets.token_hex(4)
    payload = {
        "amount": int(total), "desc": merchant,
        "envs": {str(i): str(e["envelope"].id) for i, e in enumerate(envs)},
        "date": result.get("date"), "scan_id": result.get("scan_id"),
        "confidence": result.get("confidence"), "noun": "struk",
    }
    labels = []
    for e in envs:
        env = e["envelope"]
        star = "⭐ " if (suggested and confident and env.id == suggested.id) else ""
        labels.append(f"{star}{env.emoji or '📁'} {env.name}")

    conf = CONF_TEXT.get(result.get("confidence"), "")
    if result.get("confidence") == "tinggi" and result.get("confidence_source") == "items":
        conf = "✅ cocok dengan rincian barang"
    elif result.get("confidence_source") == "items_sum":
        conf = "⚠️ dihitung dari rincian, cek dengan struk"
    summary = _items_summary(result)
    reading = (f"🧾 Struk {merchant} · {_fmt_date(result.get('date'))}\n"
               f"Total: {_rp(total)}  {conf}"
               + (f"\n\n{summary}" if summary else ""))
    return await _dated_reply(txn_key, payload, payday_day, reading, labels)


async def _proof_reply(db, user, detail, *, recorded=None, key=None, note=None) -> tuple[str, InlineKeyboardMarkup | None]:
    """Pesan bukti bayar + tombolnya; payload `txn:{key}` (baru, atau yang sudah ada bila `key`, dengan jawaban
    tanggalnya) diperbarui. Tombol amplop lewat `_dated_reply`."""
    from app.bot.handlers import _spendable_rows, get_envelopes_with_spent, ruang_keluarga

    prompt = _prompt(detail)
    if prompt == "blocked":
        return proof_message(detail, recorded=recorded, note=note), None
    hid = await ruang_keluarga(user, db)
    payday_day = getattr(user, "payday_day", 1) or 1
    envs = _spendable_rows(await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day))
    if not envs:
        return MSG_NO_ENVELOPE, None
    suggestion = detail.get("suggestion") or {}
    suggested = suggestion.get("envelope_id")
    if suggested:   # yang disarankan teratas; ⭐ hanya bila yakin
        envs.sort(key=lambda e: str(e["envelope"].id) != suggested)

    old = await _load_payload(key) if key else None
    key = key or secrets.token_hex(4)
    item_id = detail["id"]
    paid = _wib(detail.get("paid_at"))
    payload = {
        "amount": int(_total(detail)), "desc": detail.get("description_preview"),
        "envs": {str(i): str(e["envelope"].id) for i, e in enumerate(envs)},
        "date": paid.date().isoformat() if paid else None, "scan_id": item_id,
        "kind": "proof", "item_id": item_id, "note": note,
        "confidence": ((detail.get("document") or {}).get("confidence") or {}).get("total"), "noun": "bukti",
    }
    if prompt in ("skip", "soft"):   # tawaran lewati dulu; tanggal ditanyakan sesudah "Tetap catat"/"Beda, catat"
        await _save_payload(key, payload)
        if prompt == "skip":
            rows = [[InlineKeyboardButton("Oke, lewati", callback_data=f"kx_{item_id}"),
                     InlineKeyboardButton("Tetap catat", callback_data=f"ko_{key}")]]
        else:
            rows = [[InlineKeyboardButton("Sama, lewati", callback_data=f"kd_{item_id}"),
                     InlineKeyboardButton("Beda, catat", callback_data=f"ko_{key}")]]
        return proof_message(detail, recorded=recorded, note=note), InlineKeyboardMarkup(rows)
    labels = []
    for e in envs:
        env = e["envelope"]
        star = "⭐ " if suggestion.get("confident") and str(env.id) == suggested else ""
        labels.append(f"{star}{env.emoji or '📁'} {env.name}")
    return await _dated_reply(key, payload, payday_day, _proof_reading(detail, note), labels, old=old)


async def _result_reply(db, user, item, *, key=None, note=None, ready=False) -> tuple[str, InlineKeyboardMarkup | None]:
    """Pesan hasil untuk item yang sudah selesai dibaca. `ready`: langsung tombol amplop (tanpa tawaran lewati);
    `key`/`note`: sesi tombol yang sudah ada dan catatan user. Item yang sudah selesai di tempat lain (dilewati di
    web, kedaluwarsa) hanya dikabari tanpa tombol catat — dirender ulang chat web (`reply_item_result`); kirim ulang
    file yang sama di bot membuka item baru, jadi jalur bot tidak pernah sampai ke sini dengan status itu."""
    if item is None:
        return MSG_UNREADABLE, None
    if item.status in WAITING:
        return (MSG_WAIT_WEB if is_web() else MSG_WAIT_TELEGRAM), None
    if item.status == ST_GAGAL:
        return f"😕 {item.error or 'Bukti tidak bisa dibaca. Coba kirim ulang.'}", None
    if item.status == ST_DILEWATI:
        return MSG_SKIPPED, None
    if item.status == ST_KEDALUWARSA and not record.late_recordable(item):
        return MSG_EXPIRED, None
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


def _answered_elsewhere(old_meta: dict | None, meta: dict) -> bool:
    """Item lama yang masih dibaca sudah punya pesan yang akan menerima hasilnya: di chat web selalu dianggap begitu
    (gelembung chat web menanyakan hasilnya sendiri, tanpa janji worker); di Telegram bila pesan sebelumnya di chat
    yang sama (masih menunggu, atau sudah dijanjikan kabar) atau kabar sudah dijanjikan ke pesan lain. Selain itu
    (mis. item dari form web atau PWA) pesan baru ini yang dijanjikan kabar seperti biasa."""
    if is_web():
        return True
    old_meta = old_meta or {}
    return bool(old_meta.get("notify")) or (old_meta.get("chat_id") is not None
                                            and old_meta.get("chat_id") == meta.get("chat_id"))


def _web_tags(item_id, *, pending: bool = False) -> dict:
    """Kwarg tambahan `edit_text` untuk gelembung bukti di chat web (`WebMessage.edit_text`: op membawa `item` dan
    `pending`, lihat web_adapter). Di Telegram kosong — `telegram.Message.edit_text` tidak mengenalnya."""
    if not is_web():
        return {}
    tags = {"kotak_item": str(item_id)}
    if pending:
        tags["kotak_pending"] = True
    return tags


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
                item, created = await intake.create_item(db, req)
            except intake.IntakeRejected as exc:
                await status.edit_text(exc.detail)
                return
            item_id = item.id
            again = not created and item.status in WAITING and _answered_elsewhere(item.channel_meta, meta)
            await db.commit()   # item lama dikembalikan dengan transaksi baca terbuka: jangan ditahan selama menunggu
        if again:   # bukti yang sama selagi dibaca: janji pesan pertama tetap, `channel_meta` tidak diambil alih
            if is_web():   # gelembung ini pun menanyakan hasilnya sendiri (pesan pertama bisa ada di perangkat lain)
                await status.edit_text(MSG_SAME_WEB, **_web_tags(item_id, pending=True))
            else:
                await status.edit_text(MSG_SAME_TELEGRAM)
            return

        item = await waiter.wait_for_item(item_id, WAIT_BOT_S)
        if item is not None and item.status in WAITING:
            if is_web():   # tanpa `notify`: panel chat menanyakan hasilnya lewat /bot/chat/bukti (`reply_item_result`)
                await status.edit_text(MSG_WAIT_WEB, **_web_tags(item_id, pending=True))
                return
            if await _promise_notification(status, item, meta):
                return
        async with AsyncSessionLocal() as db:
            text, markup = await _result_reply(db, await db.get(User, user_id), await db.get(ReceiptScan, item_id))
        await status.edit_text(text, reply_markup=markup, **_web_tags(item_id))
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


# ── hasil untuk chat web yang ditanyakan panel (padanan send_ready_message) ──

async def reply_item_result(message, user_id, item_id) -> bool:
    """Chat web (`web_adapter.run_bukti`): ganti `message` (gelembung "Masih dibaca" di riwayat lokal panel) dengan
    pesan hasil item `item_id` milik user `user_id` — teks dan tombol yang sama dengan Telegram (`_result_reply`,
    sesi tombol `txn:{key}` baru). Mengembalikan True bila item masih dibaca (pesan tidak disentuh, panel bertanya
    lagi nanti). Item yang tidak ada atau bukan milik user (termasuk anggota rumah tangga yang sama) dijawab
    MSG_GONE_WEB tanpa `item`, supaya panel berhenti bertanya. Dipanggil ulang untuk pesan yang sudah berhasil pun
    aman: hasilnya dirender lagi dari status item saat ini (tercatat, dilewati, kedaluwarsa dikabari tanpa tombol)."""
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        item = await _own_item(db, item_id, user) if user is not None else None
        if item is None:
            await message.edit_text(MSG_GONE_WEB)
            return False
        if item.status in WAITING:
            return True
        text, markup = await _result_reply(db, user, item)
    await message.edit_text(text, reply_markup=markup, **_web_tags(item_id))
    return False


# ── tombol ──────────────────────────────────────────────────────────────────

async def handle_kotak_callback(update, context):
    """kn_{key} tambah catatan · kx_{item_id} bukan pengeluaran · kd_{item_id} duplikat (lewati) ·
    ko_{key} tetap catat (tampilkan tombol amplop). ko_ menulis ulang `txn:{key}`, jadi memakai kunci sesi tombol
    (`_txn_lock`) sampai pesannya diedit; sedang dipakai → "Sedang diproses..."."""
    query = update.callback_query
    action, _, arg = (query.data or "").partition("_")
    lock = await _txn_lock(arg) if action == "ko" else None
    if lock is False:
        await query.answer("Sedang diproses...")
        return
    try:
        await _kotak_action(update, query, action, arg)
    finally:
        await _txn_unlock(arg, lock)


async def _kotak_action(update, query, action: str, arg: str) -> None:
    from app.bot.handlers import get_or_create_user

    await query.answer()
    tg_user = update.effective_user

    if action in ("kx", "kd"):
        await forget_note(tg_user.id)
        item_id = _uuid(arg)
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
            reason = "bukan_pengeluaran" if action == "kx" else "duplikat"
            done = item_id is not None and await record.skip_item(db, item_id, user.id, reason)
        await query.edit_message_text(MSG_SKIPPED if done else f"⚠️ {record.MSG_CANNOT_SKIP}.")
        return

    payload = await _load_payload(arg)
    if payload is None:
        await query.edit_message_text(MSG_SESSION_EXPIRED)
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
                text, markup = MSG_SESSION_EXPIRED, None
            else:
                text, markup = await _result_reply(db, user, item, key=arg, note=payload.get("note"), ready=True)
        await query.edit_message_text(text, reply_markup=markup)


async def handle_date_callback(update, context):
    """kt_{key}_h = catat untuk hari ini, kt_{key}_d = catat untuk tanggal dokumen (periode lalu: tanpa geser dana dan
    limit harian, lihat handlers._handle_txn_callback). Memakai kunci sesi tombol (`_txn_lock`, sama dengan tombol
    amplop, "Tetap catat", dan catatan): dua ketukan bersamaan tidak saling menimpa jawaban, dan jawaban tidak
    berselang dengan pencatatan atau render ulang. Redis mati: lanjut tanpa kunci, seperti tombol amplop."""
    query = update.callback_query
    _, key, choice = ((query.data or "").split("_") + ["", ""])[:3]
    lock = await _txn_lock(key)
    if lock is False:
        await query.answer("Sedang diproses...")
        return
    try:
        await _answer_date(query, key, choice)
    finally:
        await _txn_unlock(key, lock)


async def _answer_date(query, key: str, choice: str) -> None:
    """Jawaban pertanyaan tanggal: payload `txn:{key}` yang SAMA diperbarui ("date" hari ini, atau "past_period";
    keduanya "date_answered"), lalu pesannya menjadi pesan tombol amplop dari teks bacaan dan label yang disimpan saat
    bertanya: item tidak dibaca ulang, daftar dan urutan amplop tetap. Sesi habis → MSG_SESSION_EXPIRED. Sudah
    dijawab: jawaban pertama ditampilkan lagi dari label yang tersimpan (memulihkan edit yang tadi gagal; edit yang
    sama persis diabaikan); payload yang sudah dirender ulang catatan/"Tetap catat" (tanpa label) tidak disentuh."""
    await query.answer()
    payload = await _load_payload(key)
    if payload is None:
        await query.edit_message_text(MSG_SESSION_EXPIRED)
        return
    answered = bool(payload.get(DATE_ANSWERED))
    if "labels" not in payload or _iso_day(payload.get("date")) is None or \
            (not answered and choice not in ("h", "d")):
        if not answered:
            await query.edit_message_text(MSG_SESSION_EXPIRED)
        return
    today = date.today()
    if not answered:
        if choice == "h":
            payload["date"] = today.isoformat()
        else:
            payload["past_period"] = True
        payload[DATE_ANSWERED] = True
        await _save_payload(key, payload)
    line = DATE_SET.format(day=short_date(_iso_day(payload["date"]), today))
    text, markup = _envelope_reply(key, payload, payload["reading"], payload["labels"], line)
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except Exception as exc:
        if not answered or "not modified" not in str(exc).lower():
            raise


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
    catatan, urutan amplop menurut saran dengan catatan), pesan tombol aslinya diedit. False (teks diproses seperti
    biasa, pesan lama tidak disentuh) bila tidak ada catatan yang ditunggu, Redis mati, sesi tombolnya sudah habis
    atau dipakai mencatat, atau itemnya tidak lagi `siap` (sudah tercatat/dilewati, mis. lewat web). Dari membaca
    payload sampai pesannya diedit memakai kunci sesi tombol (`_txn_lock`), ditunggu paling lama NOTE_LOCK_TRIES ×
    NOTE_LOCK_WAIT_S; masih dipakai → catatannya dikembalikan (bertanda `busy`) dan user diminta mengirim ulang.
    Catatan yang sempat menunggu (sekarang, atau kiriman ulang sesudah MSG_NOTE_BUSY) tidak pernah sampai ke NLP:
    bila tombol itu sudah memakai sesinya (payload habis, item tidak lagi `siap`) → MSG_NOTE_LATE (True)."""
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
    key = state.get("key")
    if not key:
        return False
    lock = await _txn_lock(key)
    # Tombol sesi ini (t_, kt_, ko_) sedang berjalan saat catatan masuk, atau ini kiriman ulang sesudah MSG_NOTE_BUSY:
    # sesi yang habis dipakai tombol itu bukan alasan membaca teksnya sebagai pengeluaran baru.
    waited = lock is False or bool(state.get("busy"))
    for _ in range(NOTE_LOCK_TRIES):
        if lock is not False:
            break
        await asyncio.sleep(NOTE_LOCK_WAIT_S)
        lock = await _txn_lock(key)
    if lock is False:
        await _keep_note(tg_user.id, json.dumps({**state, "busy": True}))
        await update.message.reply_text(MSG_NOTE_BUSY)
        return True
    try:
        if await _load_payload(key) is None:
            return await _late_note(update) if waited else False
        note = (update.message.text or "").strip()
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
            item = await _own_item(db, _uuid(state.get("item_id")), user)
            if item is None or item.status != ST_SIAP:
                return await _late_note(update) if waited else False
            text, markup = await _result_reply(db, user, item, key=key, note=note, ready=True)
        await _edit_message(update, context, state.get("message_id"), text, markup)
        return True
    finally:
        await _txn_unlock(key, lock)


async def _late_note(update) -> bool:
    """Catatan yang masuk SELAGI tombol sesi yang sama diproses, lalu sesinya habis dipakai tombol itu (mis. tombol
    amplop mencatat tanpa catatan ini): teksnya catatan, bukan ketikan baru, jadi tidak ke NLP."""
    await update.message.reply_text(MSG_NOTE_LATE)
    return True


async def _keep_note(tg_user_id, raw) -> None:
    """Kembalikan catatan yang ditunggu (`kotak:note:{tg}`) yang tadi diambil `capture_note`. Redis mati: diabaikan."""
    try:
        r = _redis()
        try:
            await r.set(NOTE_KEY.format(tg_user_id), raw, ex=NOTE_TTL_S)
        finally:
            await r.aclose()
    except Exception:
        pass


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
    await forget_note(update.effective_user.id)
    action, scan_id = parts[1], parts[2]
    item_id = _uuid(scan_id)
    skipped = False
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(update.effective_user.id), update.effective_user.first_name, db)
        item = await db.get(ReceiptScan, item_id) if item_id is not None else None
        kotak = item is not None and item.status is not None
        proof = item is not None and item.doc_type in PROOF_TYPES
        store = item is None or item.doc_type == record.STORE_RECEIPT or item.status is None
        learnable = kotak and item.doc_type in LAYOUT_TYPES
        try:
            if kotak:
                skipped = await record.skip_item(db, item_id, user.id, "batal")
            if store:
                await apply_feedback(user, scan_id, db, saved=False, wrong=(action == "fix"))
        except Exception as exc:  # best-effort
            logger.warning("feedback struk gagal: %s", exc)
    if action == "fix" and skipped and learnable:
        await _remember_fix(update.effective_user.id, item_id)
    if action == "fix" and proof:
        await query.edit_message_text(MSG_FIX_PROOF, parse_mode="Markdown")
    elif action == "fix":
        await query.edit_message_text(
            "✏️ Oke, ketik manual nominal yang benar, misalnya:\n`indomaret 140500`\n\n"
            "Laporan ini membantu scan struk makin akurat 🙏", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Struk dibatalkan.")


async def _remember_fix(chat_user_id, item_id: uuid.UUID) -> None:
    """Ingat item yang baru dilewati lewat "Nominal salah" (`FIX_KEY`, TTL FIX_TTL_S) untuk `note_fix_amount`. Redis
    mati: tanpa suara nanti, tanpa galat (pesan "ketik manual" tetap tampil)."""
    try:
        r = _redis()
        try:
            await r.set(FIX_KEY.format(chat_user_id), str(item_id), ex=FIX_TTL_S)
        finally:
            await r.aclose()
    except Exception:
        logger.warning("kunci Nominal salah untuk item %s tidak tersimpan", item_id, exc_info=True)


def fix_amount(text: str) -> int | None:
    """Nominal koreksi dari ketikan sesudah "Nominal salah": tepat satu pengeluaran ber-nominal (`parse_amount`).
    Ketikan beberapa barang (`parse_multi_expense`), teks bukti yang ditempel, teks kepanjangan, atau tanpa nominal →
    None."""
    from app.bot.handlers import parse_amount
    from app.bot.nlp_cmd import parse_multi_expense

    text = (text or "").strip()
    # 500 = batas panjang ketikan NLP (handlers.handle_message): ketikan yang ditolak NLP bukan koreksi.
    if not text or len(text) > 500 or looks_like_proof_text(text) or parse_multi_expense(text):
        return None
    parsed = parse_amount(text)
    if parsed is None or parsed[0] <= 0 or parsed[0] != parsed[0].to_integral_value():
        return None
    return int(parsed[0])


async def note_fix_amount(update, text: str) -> None:
    """Ketikan pertama user sesudah "✏️ Nominal salah" (handlers.handle_message, sesudah `capture_note`): kunci
    `FIX_KEY` diambil sekali (`getdel`); satu nominal (`fix_amount`) → suara koreksi nominal untuk item itu
    (`belajar.learn_from_correction` dengan `Final(nominal, None, None, hari ini WIB)`) lalu commit. Item milik user lain
    / tidak ada / tanpa kerangka / struk belanja → tanpa suara. Tidak pernah melempar dan tidak pernah menahan teks:
    pemanggil selalu lanjut ke NLP, yang mencatat ketikan itu seperti biasa (tidak tertaut ke item). Redis mati → tanpa
    suara."""
    try:
        tg_user = update.effective_user
        r = _redis()
        try:
            raw = await r.getdel(FIX_KEY.format(tg_user.id))
        finally:
            await r.aclose()
        if not raw:
            return
        item_id = _uuid(raw.decode() if isinstance(raw, bytes) else raw)
        amount = fix_amount(text)
        if item_id is None or amount is None:
            return
        async with AsyncSessionLocal() as db:
            user = await find_chat_user(str(tg_user.id), db)
            item = await _own_item(db, item_id, user) if user is not None else None
            if item is None:
                return
            final = belajar.Final(amount, None, None, belajar.today_wib())
            if await belajar.learn_from_correction(db, item, final, user_id=user.id):
                await db.commit()
    except Exception:
        logger.warning("suara Nominal salah tidak dicatat", exc_info=True)


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
