"""Kanal percakapan bot: Telegram atau chat di webapp (PWA).

Handler di `app/bot/*` ditulis untuk Telegram dan mengenali user lewat
`update.effective_user.id` (telegram_id). Chat di webapp memakai handler yang
sama lewat adapter (`app/bot/web_adapter.py`); di sana `effective_user.id`
berisi id chat web `web:<user_uuid>`, bukan telegram_id.

Modul ini satu-satunya tempat yang tahu bedanya:
- `find_chat_user` / `is_web_chat_id` — resolusi user untuk kedua bentuk id.
  Id `web:` hanya dihormati saat kanal web aktif (fail-closed), dan user web
  tidak pernah dibuat otomatis (akunnya sudah ada karena sudah login).
- `txn_source()` — transaksi dari chat web tercatat `webapp`, dari Telegram
  `telegram`, supaya laporan/ekspor sumber tetap jujur.
- `web_channel()` — context manager yang mengaktifkan kanal web untuk satu
  request; memakai contextvars sehingga aman untuk request yang berjalan
  bersamaan.
"""
from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager

from sqlalchemy import select

from app.models.models import TransactionSource, User

WEB_CHAT_PREFIX = "web:"
TELEGRAM = "telegram"
WEB = "web"

_channel: contextvars.ContextVar[str] = contextvars.ContextVar("bot_channel", default=TELEGRAM)


def current_channel() -> str:
    return _channel.get()


def is_web() -> bool:
    return _channel.get() == WEB


@contextmanager
def web_channel():
    """Aktifkan kanal web selama blok berjalan (satu request chat webapp)."""
    token = _channel.set(WEB)
    try:
        yield
    finally:
        _channel.reset(token)


def web_chat_id(user_id) -> str:
    return f"{WEB_CHAT_PREFIX}{user_id}"


def is_web_chat_id(chat_id) -> bool:
    return str(chat_id).startswith(WEB_CHAT_PREFIX)


def parse_web_chat_id(chat_id) -> uuid.UUID | None:
    if not is_web_chat_id(chat_id):
        return None
    try:
        return uuid.UUID(str(chat_id)[len(WEB_CHAT_PREFIX):])
    except ValueError:
        return None


async def find_chat_user(chat_id, db) -> User | None:
    """User pemilik percakapan: lewat telegram_id, atau lewat id user untuk
    chat web. Id `web:` di luar kanal web ditolak (None)."""
    if is_web_chat_id(chat_id):
        if not is_web():
            return None
        uid = parse_web_chat_id(chat_id)
        if uid is None:
            return None
        result = await db.execute(select(User).where(User.id == uid))
        return result.scalar_one_or_none()
    result = await db.execute(select(User).where(User.telegram_id == str(chat_id)))
    return result.scalar_one_or_none()


def txn_source() -> TransactionSource:
    """Sumber transaksi untuk kanal yang sedang aktif."""
    return TransactionSource.webapp if is_web() else TransactionSource.telegram
