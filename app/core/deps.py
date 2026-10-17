from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import decode_token
from app.models.models import AuthSession, User
from app.services.auth_sessions import is_active

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    try:
        user_id = UUID(payload.get("sub") or "")
        sid = UUID(payload["sid"]) if payload.get("sid") else None
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Sesi per perangkat (app/services/auth_sessions.py): token ber-sid harus
    # menunjuk sesi yang belum dicabut; token lama tanpa sid mati oleh logout-all.
    if sid is not None:
        sess = (await db.execute(select(AuthSession).where(AuthSession.id == sid))).scalar_one_or_none()
        if not is_active(sess, user.id):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")
    elif user.tokens_revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")
    return user


def get_current_session_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UUID | None:
    """`sid` dari access token (None untuk token lama). Dipakai bersama
    get_current_user, yang sudah memvalidasi tokennya."""
    payload = decode_token(credentials.credentials) if credentials else None
    try:
        return UUID(payload["sid"]) if payload and payload.get("sid") else None
    except ValueError:
        return None


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency untuk endpoint khusus admin (dashboard admin, pemicu manual
    yang berdampak ke semua user)."""
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
