"""Route klien aplikasi (paket mobile 1.3, ADR-M9).

- `GET /app/config`  — config per platform; publik, tanpa login, boleh di-cache.
- `POST /app/errors` — laporan error dari klien; hanya ditulis ke log.

Isi config: `app/services/app_config.py`. Identitas klien: header
`X-Jatahku-Client` (`app/core/client.py`).
"""
import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client import HEADER, client_of
from app.core.database import get_db
from app.models.models import AppSetting
from app.services.app_config import SETTING_KEY, build_config, parse_overrides

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
log = logging.getLogger(__name__)
error_log = logging.getLogger("jatahku.client_errors")


@router.get("/config")
async def app_config(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = None
    try:
        raw = (await db.execute(
            select(AppSetting.value).where(AppSetting.key == SETTING_KEY)
        )).scalar_one_or_none()
    except Exception:
        # Config tidak boleh gagal: tanpa DB pun klien tetap dapat nilai bawaan.
        log.warning("Gagal membaca AppSetting %s; memakai bawaan", SETTING_KEY, exc_info=True)
    # Isi bergantung pada header klien; cache singkat supaya perubahan
    # versi minimum cepat sampai.
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["Vary"] = HEADER
    return build_config(client_of(request), parse_overrides(raw))


class ClientErrorReport(BaseModel):
    message: str = Field(..., max_length=2000)
    stack: str | None = Field(None, max_length=8000)
    url: str | None = Field(None, max_length=2000)
    kind: str | None = Field(None, max_length=50)  # error | unhandledrejection | react


@router.post("/errors", status_code=204)
@limiter.limit("20/minute")
async def client_error(request: Request, report: ClientErrorReport):
    client = client_of(request)
    # Hanya path: query string bisa berisi token (mis. /auth/tg?token=…).
    path = urlsplit(report.url).path[:200] if report.url else None
    error_log.warning(
        "client_error platform=%s version=%s build=%s kind=%s path=%s message=%s\n%s",
        client.platform, client.version, client.build, report.kind, path,
        report.message[:500], (report.stack or "")[:2000],
    )
    return Response(status_code=204)
