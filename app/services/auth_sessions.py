"""Sesi login per perangkat (ADR-M7, mobile paket 1.1).

Setiap login membuat satu baris `auth_sessions`. Access token membawa `sid`;
refresh token membawa `sid` + `jti`. Setiap /auth/refresh merotasi `jti`:

- `jti` terkini → dirotasi, `jti` lama disimpan di `prev_refresh_jti`.
- `jti` sebelumnya, masih dalam REFRESH_GRACE sejak rotasi → dianggap balapan
  (dua tab web, app + widget) dan dijawab dengan token `jti` terkini, tanpa rotasi.
- selain itu → refresh token dipakai ulang (bocor) → sesi dicabut.

Token lama (dibuat sebelum tabel ini ada) tidak punya `sid`. Access token lama
diterima sampai kedaluwarsa (30 menit); refresh token lama ditukar sekali menjadi
sesi baru. Keduanya ditolak setelah logout-all (`users.tokens_revoked_at`).
"""
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models.models import AuthSession, User

REFRESH_GRACE = timedelta(seconds=30)


class RefreshError(Exception):
    """Refresh token tidak sah, sudah dicabut, atau dipakai ulang."""


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite (tes) mengembalikan datetime naif; Postgres sudah UTC-aware.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _new_jti() -> str:
    return secrets.token_urlsafe(24)


def _ttl() -> timedelta:
    return timedelta(days=get_settings().JWT_REFRESH_TOKEN_EXPIRE_DAYS)


def _pair(sess: AuthSession) -> TokenPair:
    uid, sid = str(sess.user_id), str(sess.id)
    return TokenPair(
        access_token=create_access_token(uid, sid=sid),
        refresh_token=create_refresh_token(uid, sid=sid, jti=sess.refresh_jti),
    )


def _touch(sess: AuthSession, request: Request | None, now: datetime) -> None:
    sess.last_used_at = now
    sess.expires_at = now + _ttl()
    if request is not None:
        client = request.headers.get("x-jatahku-client")
        ua = request.headers.get("user-agent")
        if client:
            sess.client = client[:100]
        if ua:
            sess.user_agent = ua[:255]


def is_active(sess: AuthSession | None, user_id: uuid.UUID, now: datetime | None = None) -> bool:
    now = now or _now()
    return (
        sess is not None
        and sess.user_id == user_id
        and sess.revoked_at is None
        and _aware(sess.expires_at) > now
    )


async def start_session(db: AsyncSession, user: User, request: Request | None = None) -> TokenPair:
    """Login berhasil (password, Google, Telegram, reset sandi) → sesi baru. Commit."""
    now = _now()
    sess = AuthSession(id=uuid.uuid4(), user_id=user.id, refresh_jti=_new_jti())
    _touch(sess, request, now)
    db.add(sess)
    await db.commit()
    return _pair(sess)


async def rotate(db: AsyncSession, refresh_token: str, request: Request | None = None) -> TokenPair:
    payload = decode_token(refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise RefreshError("Invalid refresh token")
    try:
        user_id = uuid.UUID(payload.get("sub") or "")
        sid = uuid.UUID(payload["sid"]) if payload.get("sid") else None
    except ValueError:
        raise RefreshError("Invalid refresh token")

    if sid is None:
        return await _upgrade_legacy(db, user_id, refresh_token, request)

    sess = (await db.execute(
        select(AuthSession).where(AuthSession.id == sid).with_for_update()
    )).scalar_one_or_none()
    now = _now()
    if not is_active(sess, user_id, now):
        raise RefreshError("Session revoked")

    jti = payload.get("jti")
    if jti and jti == sess.refresh_jti:
        sess.prev_refresh_jti = jti
        sess.refresh_jti = _new_jti()
        sess.rotated_at = now
    elif not (jti and jti == sess.prev_refresh_jti and _in_grace(sess, now)):
        _revoke(sess, "reuse", now)
        await db.commit()
        raise RefreshError("Refresh token reused")
    _touch(sess, request, now)
    await db.commit()
    return _pair(sess)


def _in_grace(sess: AuthSession, now: datetime) -> bool:
    rotated = _aware(sess.rotated_at)
    return rotated is not None and now - rotated <= REFRESH_GRACE


async def _upgrade_legacy(db: AsyncSession, user_id: uuid.UUID, token: str, request: Request | None) -> TokenPair:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.tokens_revoked_at is not None:
        raise RefreshError("Session revoked")
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = _now()
    sess = (await db.execute(
        select(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.legacy_token_hash == digest)
        .with_for_update()
    )).scalar_one_or_none()
    if sess is not None:
        # Token lama yang sama datang lagi: balapan bila masih dalam masa tenggang
        # pertukaran pertama, selain itu dipakai ulang.
        created = _aware(sess.created_at) or now
        if is_active(sess, user_id, now) and now - created <= REFRESH_GRACE:
            return _pair(sess)
        _revoke(sess, "reuse", now)
        await db.commit()
        raise RefreshError("Refresh token reused")

    sess = AuthSession(
        id=uuid.uuid4(), user_id=user_id, refresh_jti=_new_jti(),
        legacy_token_hash=digest, created_at=now,
    )
    _touch(sess, request, now)
    db.add(sess)
    await db.commit()
    return _pair(sess)


def _revoke(sess: AuthSession, reason: str, now: datetime) -> None:
    if sess.revoked_at is None:
        sess.revoked_at = now
        sess.revoked_reason = reason


async def revoke_session(db: AsyncSession, user_id: uuid.UUID, sid: uuid.UUID, reason: str = "logout") -> bool:
    """Cabut satu sesi milik user. False bila tidak ada / milik orang lain."""
    sess = (await db.execute(
        select(AuthSession).where(AuthSession.id == sid, AuthSession.user_id == user_id)
    )).scalar_one_or_none()
    if sess is None:
        return False
    _revoke(sess, reason, _now())
    await db.commit()
    return True


async def revoke_all(db: AsyncSession, user: User, reason: str, except_sid: uuid.UUID | None = None) -> None:
    """Cabut semua sesi user (kecuali `except_sid`) dan semua token lama tanpa sid. Commit."""
    now = _now()
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason)
    )
    if except_sid is not None:
        stmt = stmt.where(AuthSession.id != except_sid)
    await db.execute(stmt)
    user.tokens_revoked_at = now
    await db.commit()


async def list_active(db: AsyncSession, user_id: uuid.UUID) -> list[AuthSession]:
    now = _now()
    rows = (await db.execute(
        select(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .order_by(AuthSession.last_used_at.desc())
    )).scalars().all()
    return [s for s in rows if _aware(s.expires_at) > now]
