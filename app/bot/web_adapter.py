"""Chat bot di webapp (PWA) — memakai handler bot Telegram yang sama.

Handler di `app/bot/*` hanya memakai sebagian kecil API Telegram:
`update.message.reply_text`, `update.callback_query.{answer, edit_message_text}`,
`update.effective_user`, `context.args`, dan (pesan teks) `context.bot.edit_message_text`
untuk mengedit pesan bot lain. Adapter ini menyediakan objek
pengganti dengan bentuk yang sama, lalu mengumpulkan balasan sebagai "ops"
JSON yang dirender webapp:

    {"type": "message", "id", "text", "format", "buttons"}  # pesan bot baru
    {"type": "edit",    "id", "text", "format", "buttons"}  # ganti pesan (tombol ditekan)
    {"type": "buttons", "id", "buttons"}                    # ganti tombol saja
    {"type": "delete",  "id"}                               # hapus pesan bot
    {"type": "toast",   "text"}                             # notifikasi singkat

Foto struk dari webapp diproses `handle_non_text` yang sama dengan foto di
Telegram (→ app/bot/receipt_cmd.py), lewat pengganti `PhotoSize`/`Document`.
Op "edit" untuk gelembung bukti itu membawa `item` (id item Kotak Struk) dan,
selagi bukti masih dibaca lewat batas tunggu bot, `pending: true`: panel chat
menyimpan keduanya di riwayat lokal dan menanyakan hasilnya lewat `run_bukti`
(`POST /bot/chat/bukti`) sampai pesan yang sama diganti hasilnya — padanan
`send_ready_message` Telegram, tetapi ditarik klien, bukan didorong worker
(riwayat chat web hanya ada di perangkat user, server tidak menyimpannya).

`format` = "html" | "markdown" | "plain" (parse_mode Telegram apa adanya);
`buttons` = baris tombol `[[{"text", "data"} | {"text", "url"}]]`.

Keamanan tombol: di Telegram, callback_data hanya bisa dikirim dari tombol
yang benar-benar dikirim bot ke chat itu. Di web jaminan yang sama ditegakkan
di sini: setiap tombol yang dikirim ke user dicatat di Redis per pesan
(`webchat:btn:<user_id>:<msg_id>`), dan tombol yang ditekan hanya diproses bila
tercatat untuk pesan itu. Redis tidak tersedia → ditolak. Satu pesan hanya
memproses satu tombol pada satu waktu (`webchat:lock:…`), supaya dua ketukan
bersamaan (dua tab/perangkat) tidak mencatat transaksi dua kali.

Kirim ulang: pesan membawa `client_id` dari webapp; hasilnya disimpan sebentar
(`webchat:req:…`), jadi pesan yang dikirim ulang setelah koneksi putus tidak
diproses dua kali — ops yang sama dikembalikan.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from types import SimpleNamespace

import redis.asyncio as aioredis

from app.bot.channel import web_channel, web_chat_id
from app.core.config import get_settings

logger = logging.getLogger("jatahku.webchat")

BUTTONS_TTL = 3 * 24 * 3600  # detik — sesi bot sendiri jauh lebih pendek (5–10 menit)
ACTION_LOCK_TTL = 30          # detik — batas aman satu tombol diproses
REQUEST_TTL = 10 * 60         # detik — jendela deteksi kirim ulang

# Perintah/tombol yang hanya bermakna di Telegram (penautan & login akun).
TELEGRAM_ONLY_COMMANDS = {"link", "unlink", "webapp"}
TELEGRAM_ONLY_CALLBACKS = re.compile(r"^(merge_|unlink_)")

ERROR_REPLY = "⚠️ Ada kendala saat memproses pesan. Coba lagi sebentar."
STALE_BUTTON = "Tombol ini sudah tidak berlaku. Kirim ulang pesannya."
BUTTONS_UNAVAILABLE = "Tombol tidak bisa diproses sekarang. Coba lagi sebentar."
PROCESSING = "Masih diproses, tunggu sebentar."

_FORMATS = {"html": "html", "markdown": "markdown", "markdownv2": "markdown"}


def _redis():
    return aioredis.from_url(get_settings().REDIS_URL)


def buttons_key(user_id, message_id) -> str:
    return f"webchat:btn:{user_id}:{message_id}"


def lock_key(user_id, message_id) -> str:
    return f"webchat:lock:{user_id}:{message_id}"


def request_key(user_id, client_id) -> str:
    return f"webchat:req:{user_id}:{client_id}"


def new_message_id() -> str:
    return secrets.token_hex(6)


def message_format(parse_mode) -> str:
    return _FORMATS.get(str(parse_mode or "").lower(), "plain")


def serialize_markup(markup) -> list:
    """InlineKeyboardMarkup → [[{"text", "data"|"url"}]]. Tombol tanpa aksi dibuang."""
    rows = []
    for row in getattr(markup, "inline_keyboard", None) or ():
        out = []
        for btn in row:
            data = getattr(btn, "callback_data", None)
            url = getattr(btn, "url", None)
            if data is not None:
                out.append({"text": str(btn.text), "data": str(data)})
            elif url and re.match(r"^https?://", str(url), re.IGNORECASE):
                out.append({"text": str(btn.text), "url": str(url)})
        if out:
            rows.append(out)
    return rows


def button_data(buttons) -> list[str]:
    return [b["data"] for row in buttons for b in row if "data" in b]


class Outbox:
    """Mengumpulkan balasan handler sebagai ops + tombol yang perlu dicatat."""

    def __init__(self):
        self.ops: list[dict] = []
        self.buttons: dict[str, list[str]] = {}  # msg_id → callback_data ([] = hapus)

    def send(self, text, parse_mode=None, reply_markup=None) -> str:
        msg_id = new_message_id()
        buttons = serialize_markup(reply_markup)
        self.ops.append({
            "type": "message", "id": msg_id, "text": str(text),
            "format": message_format(parse_mode), "buttons": buttons,
        })
        self.buttons[msg_id] = button_data(buttons)
        return msg_id

    def edit(self, msg_id, text, parse_mode=None, reply_markup=None, *, kotak_item=None, kotak_pending=False):
        # Seperti Telegram: edit tanpa reply_markup menghapus tombol. `kotak_item`/`kotak_pending`: gelembung bukti
        # Kotak Struk (lihat docstring modul); tanpa keduanya op tidak memuat `item`/`pending`.
        buttons = serialize_markup(reply_markup)
        op = {
            "type": "edit", "id": msg_id, "text": str(text),
            "format": message_format(parse_mode), "buttons": buttons,
        }
        if kotak_item is not None:
            op["item"] = str(kotak_item)
            if kotak_pending:
                op["pending"] = True
        self.ops.append(op)
        self.buttons[msg_id] = button_data(buttons)

    def set_buttons(self, msg_id, reply_markup=None):
        buttons = serialize_markup(reply_markup)
        self.ops.append({"type": "buttons", "id": msg_id, "buttons": buttons})
        self.buttons[msg_id] = button_data(buttons)

    def toast(self, text):
        if text:
            self.ops.append({"type": "toast", "text": str(text)})

    def delete(self, msg_id):
        self.ops.append({"type": "delete", "id": msg_id})
        self.buttons[msg_id] = []

    async def persist(self, user_id):
        """Catat tombol yang dikirim/diubah, supaya hanya tombol itu yang bisa ditekan."""
        if not self.buttons:
            return
        r = _redis()
        try:
            pipe = r.pipeline()
            for msg_id, data in self.buttons.items():
                key = buttons_key(user_id, msg_id)
                if data:
                    pipe.set(key, json.dumps(data), ex=BUTTONS_TTL)
                else:
                    pipe.delete(key)
            await pipe.execute()
        finally:
            await r.aclose()


# ── Objek pengganti Telegram ────────────────────────────────────────────────

class WebChatUser:
    """Pengganti telegram.User. `id` = id chat web (lihat app/bot/channel.py)."""

    is_bot = False
    username = None
    language_code = "id"

    def __init__(self, user):
        self.id = web_chat_id(user.id)
        name = (getattr(user, "name", None) or "").strip()
        self.first_name = name.split()[0] if name else "Kamu"
        self.full_name = name or self.first_name


class WebFile:
    """Pengganti telegram.File: isi file sudah ada di memori (upload webapp)."""

    def __init__(self, data: bytes):
        self._data = data
        self.file_size = len(data)

    async def download_as_bytearray(self, *_, **__):
        return bytearray(self._data)


class WebPhotoSize:
    """Pengganti telegram.PhotoSize (foto JPEG dari webapp)."""

    def __init__(self, data: bytes):
        self._data = data
        self.file_size = len(data)

    async def get_file(self, *_, **__):
        return WebFile(self._data)


class WebDocument(WebPhotoSize):
    """Pengganti telegram.Document (gambar non-JPEG, mis. PNG/WebP)."""

    def __init__(self, data: bytes, mime_type: str):
        super().__init__(data)
        self.mime_type = mime_type
        self.file_name = "struk"


class WebMessage:
    """Pengganti telegram.Message: pesan user (teks/foto) atau pesan bot (tombol)."""

    photo = sticker = voice = audio = document = None

    def __init__(self, outbox: Outbox, text=None, message_id=None, from_user=None):
        self._outbox = outbox
        self.text = text
        self.message_id = message_id
        self.from_user = from_user
        self.chat = SimpleNamespace(id=getattr(from_user, "id", None), type="private")
        self.chat_id = self.chat.id

    async def reply_text(self, text, parse_mode=None, reply_markup=None, **_):
        msg_id = self._outbox.send(text, parse_mode, reply_markup)
        return WebMessage(self._outbox, text=text, message_id=msg_id, from_user=self.from_user)

    async def edit_text(self, text, parse_mode=None, reply_markup=None, *, kotak_item=None, kotak_pending=False, **_):
        # `kotak_item`/`kotak_pending` hanya dikirim receipt_cmd di kanal web (telegram.Message.edit_text tidak
        # mengenalnya): gelembung bukti yang bisa ditanyakan ulang lewat /bot/chat/bukti.
        self._outbox.edit(self.message_id, text, parse_mode, reply_markup,
                          kotak_item=kotak_item, kotak_pending=kotak_pending)
        return self

    async def delete(self, *_, **__):
        if self.message_id:
            self._outbox.delete(self.message_id)
        return True


class WebCallbackQuery:
    """Pengganti telegram.CallbackQuery untuk tombol yang ditekan di webapp."""

    def __init__(self, outbox: Outbox, data: str, from_user, message_id: str):
        self._outbox = outbox
        self.id = secrets.token_hex(4)
        self.data = data
        self.from_user = from_user
        self.message = WebMessage(outbox, message_id=message_id, from_user=from_user)

    async def answer(self, text=None, show_alert=False, **_):
        self._outbox.toast(text)
        return True

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None, **_):
        self._outbox.edit(self.message.message_id, text, parse_mode, reply_markup)
        return self.message

    async def edit_message_reply_markup(self, reply_markup=None, **_):
        self._outbox.set_buttons(self.message.message_id, reply_markup)
        return self.message


class WebUpdate:
    def __init__(self, user: WebChatUser, message=None, callback_query=None):
        self.effective_user = user
        self.message = message
        self.callback_query = callback_query
        self.effective_message = message or (callback_query.message if callback_query else None)
        self.effective_chat = SimpleNamespace(id=user.id, type="private")


class WebBot:
    """Pengganti telegram.Bot untuk handler yang mengedit pesan bot lain lewat id-nya (mis. catatan bukti mengedit
    pesan tombolnya): `context.bot.edit_message_text(...)` menjadi op "edit" untuk pesan itu."""

    def __init__(self, outbox: Outbox):
        self._outbox = outbox

    async def edit_message_text(self, text, chat_id=None, message_id=None, parse_mode=None, reply_markup=None, **_):
        self._outbox.edit(message_id, text, parse_mode, reply_markup)
        return True


class WebContext:
    def __init__(self, args=None, bot=None):
        self.args = list(args or [])
        self.user_data: dict = {}
        self.chat_data: dict = {}
        self.bot_data: dict = {}
        self.bot = bot


# ── Dispatch ────────────────────────────────────────────────────────────────

def parse_command(text: str):
    """'/Status@JatahkuBot a b' → ('status', ['a', 'b']). Bukan perintah → None."""
    if not text.startswith("/"):
        return None
    head, *args = text.split()
    name = head[1:].split("@", 1)[0].lower()
    if not name or not re.fullmatch(r"[a-z0-9_]{1,32}", name):
        return None
    return name, args


async def _dispatch_text(outbox: Outbox, tg_user: WebChatUser, text: str):
    from app.bot.handlers import bot_commands, handle_message

    message = WebMessage(outbox, text=text, from_user=tg_user)
    update = WebUpdate(tg_user, message=message)
    command = parse_command(text)
    if command is None:
        if text.startswith("/"):
            outbox.send("Perintah tidak dikenal. Ketik /help untuk daftar perintah.")
            return
        await handle_message(update, WebContext(bot=WebBot(outbox)))
        return
    name, args = command
    if name in TELEGRAM_ONLY_COMMANDS:
        outbox.send(
            f"/{name} khusus untuk Telegram. Di webapp kamu sudah masuk — "
            "untuk menghubungkan Telegram, buka Settings."
        )
        return
    handler = bot_commands().get(name)
    if handler is None:
        outbox.send(f"Perintah /{name} tidak dikenal. Ketik /help untuk daftar perintah.")
        return
    if name == "start":
        args = []  # deep link (/start link_KODE) hanya untuk Telegram
    await handler(update, WebContext(args))


def _find_callback(data: str):
    from app.bot.handlers import bot_callbacks

    if TELEGRAM_ONLY_CALLBACKS.match(data):
        return None
    for pattern, handler in bot_callbacks():
        if re.match(pattern, data):
            return handler
    return None


async def _issued_buttons(user_id, message_id) -> list[str] | None:
    """callback_data yang tercatat untuk pesan ini; None bila Redis gagal."""
    r = _redis()
    try:
        raw = await r.get(buttons_key(user_id, message_id))
    except Exception:
        logger.warning("webchat: gagal membaca tombol dari Redis", exc_info=True)
        return None
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    if not raw:
        return []
    try:
        return list(json.loads(raw))
    except (TypeError, ValueError):
        return []


async def _finish(outbox: Outbox, user_id) -> list[dict]:
    try:
        await outbox.persist(user_id)
    except Exception:
        # Pesan tetap dikirim; tombolnya saja yang tidak akan bisa ditekan.
        logger.warning("webchat: gagal mencatat tombol ke Redis", exc_info=True)
    return outbox.ops


async def _claim_request(user_id, client_id):
    """Tandai pesan `client_id` sedang diproses. Mengembalikan None bila boleh
    diproses, atau ops yang harus dikembalikan (hasil tersimpan / masih diproses).
    Redis gagal → diproses saja (deteksi kirim ulang bersifat best-effort)."""
    r = _redis()
    try:
        key = request_key(user_id, client_id)
        if await r.set(key, "pending", nx=True, ex=REQUEST_TTL):
            return None
        raw = await r.get(key)
    except Exception:
        logger.warning("webchat: deteksi kirim ulang tidak tersedia", exc_info=True)
        return None
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    if raw in (None, b"pending", "pending"):
        return [{"type": "toast", "text": PROCESSING}] if raw is not None else None
    try:
        return list(json.loads(raw))
    except (TypeError, ValueError):
        return [{"type": "toast", "text": PROCESSING}]


async def _store_request(user_id, client_id, ops):
    r = _redis()
    try:
        await r.set(request_key(user_id, client_id), json.dumps(ops), ex=REQUEST_TTL)
    except Exception:
        logger.warning("webchat: gagal menyimpan hasil pesan", exc_info=True)
    finally:
        try:
            await r.aclose()
        except Exception:
            pass


async def _run_user_message(user, client_id, dispatch) -> list[dict]:
    """Jalankan satu pesan user (teks/foto) sekali saja per `client_id`."""
    if client_id:
        earlier = await _claim_request(user.id, client_id)
        if earlier is not None:
            return earlier
    outbox = Outbox()
    tg_user = WebChatUser(user)
    with web_channel():
        try:
            await dispatch(outbox, tg_user)
        except Exception:
            logger.exception("webchat: gagal memproses pesan")
            outbox.send(ERROR_REPLY)
    ops = await _finish(outbox, user.id)
    if client_id:
        await _store_request(user.id, client_id, ops)
    return ops


async def run_message(user, text: str, client_id: str | None = None) -> list[dict]:
    """Proses satu pesan teks dari chat webapp. `user` = User yang login.
    `client_id` (dari webapp) membuat kirim ulang pesan yang sama aman."""
    text = (text or "").strip()
    if not text:
        return []
    return await _run_user_message(user, client_id, lambda outbox, tg_user: _dispatch_text(outbox, tg_user, text))


JPEG_MIME = {"image/jpeg", "image/jpg"}


async def run_photo(user, data: bytes, mime: str, client_id: str | None = None) -> list[dict]:
    """Foto struk/bukti dari chat webapp → `handle_non_text` → Kotak Struk (source `web_chat`), alur foto bot
    Telegram yang sama. JPEG dikirim sebagai foto, format lain sebagai dokumen gambar — sama
    dengan dua cara user Telegram mengirim gambar."""
    from app.bot.handlers import handle_non_text

    async def dispatch(outbox, tg_user):
        message = WebMessage(outbox, from_user=tg_user)
        if mime in JPEG_MIME:
            message.photo = [WebPhotoSize(data)]
        else:
            message.document = WebDocument(data, mime)
        await handle_non_text(WebUpdate(tg_user, message=message), WebContext())

    return await _run_user_message(user, client_id, dispatch)


async def run_bukti(user, items: list[tuple]) -> dict:
    """Hasil bukti chat web yang dibaca lewat batas tunggu bot: untuk tiap `(item_id, message_id)` dari riwayat
    lokal panel, pesan `message_id` diganti pesan hasil item itu (teks dan tombol yang sama dengan Telegram,
    `receipt_cmd.reply_item_result`), atau dibiarkan bila masih dibaca. Mengembalikan `{"ops", "pending"}`:
    `pending` = id item yang masih dibaca (klien bertanya lagi nanti). Galat merender satu item dicatat dan item itu
    dianggap masih dibaca, supaya hasilnya tidak hilang dari chat; item lain tetap dijawab."""
    from app.bot.receipt_cmd import reply_item_result

    outbox = Outbox()
    tg_user = WebChatUser(user)
    pending: list[str] = []
    with web_channel():
        for item_id, message_id in items:
            message = WebMessage(outbox, message_id=message_id, from_user=tg_user)
            try:
                still_reading = await reply_item_result(message, user.id, item_id)
            except Exception:
                logger.exception("webchat: gagal memuat hasil bukti %s", item_id)
                still_reading = True
            if still_reading:
                pending.append(str(item_id))
    return {"ops": await _finish(outbox, user.id), "pending": pending}


async def run_action(user, message_id: str, data: str) -> list[dict]:
    """Proses tombol yang ditekan pada pesan bot `message_id`."""
    outbox = Outbox()
    issued = await _issued_buttons(user.id, message_id)
    if issued is None:
        outbox.toast(BUTTONS_UNAVAILABLE)
        return outbox.ops
    handler = _find_callback(data) if data in issued else None
    if handler is None:
        outbox.toast(STALE_BUTTON)
        outbox.set_buttons(message_id, None)
        return await _finish(outbox, user.id)
    r = _redis()
    try:
        # SET NX: True bila kunci didapat, None bila tombol ini sedang diproses.
        locked = bool(await r.set(lock_key(user.id, message_id), "1", nx=True, ex=ACTION_LOCK_TTL))
        lock_error = False
    except Exception:
        logger.warning("webchat: gagal mengunci tombol", exc_info=True)
        locked, lock_error = False, True
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    if not locked:
        outbox.toast(BUTTONS_UNAVAILABLE if lock_error else PROCESSING)
        return outbox.ops
    try:
        tg_user = WebChatUser(user)
        query = WebCallbackQuery(outbox, data, tg_user, message_id)
        with web_channel():
            try:
                await handler(WebUpdate(tg_user, callback_query=query), WebContext())
            except Exception:
                logger.exception("webchat: gagal memproses tombol")
                outbox.send(ERROR_REPLY)
        return await _finish(outbox, user.id)
    finally:
        r = _redis()
        try:
            await r.delete(lock_key(user.id, message_id))
        except Exception:
            pass  # kunci habis sendiri setelah ACTION_LOCK_TTL
        finally:
            try:
                await r.aclose()
            except Exception:
                pass
