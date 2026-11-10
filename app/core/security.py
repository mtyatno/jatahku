from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
import jwt
from app.core.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, sid: str | None = None) -> str:
    """`sid` = id baris auth_sessions. Token tanpa `sid` hanya dibuat oleh kode
    lama; token baru selalu lewat app/services/auth_sessions.py."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": user_id, "exp": expire, "type": "access"}
    if sid:
        payload["sid"] = sid
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str, sid: str | None = None, jti: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {"sub": user_id, "exp": expire, "type": "refresh"}
    if sid:
        payload["sid"] = sid
        payload["jti"] = jti
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except RecursionError:
        # Header JWT berupa JSON bersarang ribuan tingkat: `json.loads` milik PyJWT melempar RecursionError, bukan
        # ValueError (yang diubah PyJWT menjadi DecodeError). Token seperti itu tidak sah: None, jadi 401, bukan 500.
        return None


_TUJUAN_SESI = ("access", "refresh")   # `type` token login; bukan milik token bertujuan


def _tolak_tujuan_sesi(tujuan: str) -> None:
    if tujuan in _TUJUAN_SESI:
        raise ValueError(f"token bertujuan tidak boleh bertujuan {tujuan!r} (itu token sesi)")


def create_purpose_token(user_id: str, tujuan: str, *, berlaku: timedelta | None, **klaim) -> str:
    """Token bertujuan (verifikasi email, berhenti email laporan): klaim `type` = `tujuan`, jadi tidak pernah lolos
    sebagai access (`get_current_user`, `kunci_per_user`) atau refresh (rotasi). `berlaku` wajib disebut (keyword,
    tanpa bawaan): `berlaku=None` → tanpa `exp`, jadi argumen yang terlupa tidak pernah mencetak token yang tidak
    kedaluwarsa. `tujuan` `access`/`refresh` → ValueError. `klaim` tidak boleh menimpa `sub`/`type`/`exp`."""
    _tolak_tujuan_sesi(tujuan)
    payload = {k: v for k, v in klaim.items() if k not in ("sub", "type", "exp")}
    payload.update({"sub": user_id, "type": tujuan})
    if berlaku is not None:
        payload["exp"] = datetime.now(timezone.utc) + berlaku
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_purpose_token(token: str, tujuan: str) -> dict | None:
    """Klaim token bila tanda tangan sah, belum kedaluwarsa, `type` == `tujuan`, dan `sub` berupa str tak kosong;
    selainnya None. `tujuan` `access`/`refresh` → ValueError: token sesi diperiksa `get_current_user` dan rotasi
    refresh, tidak pernah lewat sini."""
    _tolak_tujuan_sesi(tujuan)
    payload = decode_token(token)
    if not isinstance(payload, dict) or payload.get("type") != tujuan:
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    return payload
