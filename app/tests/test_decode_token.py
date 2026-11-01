"""`decode_token` (app/core/security.py): token yang bisa dikirim siapa saja tidak boleh membuatnya melempar.

JWT yang segmen header-nya JSON bersarang ribuan tingkat membuat `json.loads` milik PyJWT melempar `RecursionError`
(bukan `ValueError`, yang diubah PyJWT menjadi `DecodeError`). Dulu itu lolos dari `decode_token` dan
`get_current_user` menjawab 500; kini token itu tidak sah seperti token rusak lainnya: `None`, jadi 401.

Run: python -m unittest app.tests.test_decode_token -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import base64
import json
import unittest

import httpx
from fastapi import Depends, FastAPI

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import decode_token

# Jauh melewati batas rekursi `json.loads` di Python mana pun ≥ 3.11 (di 3.13 sudah cukup ±10_000 tingkat).
KEDALAMAN = 100_000


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def token_header_bersarang(kedalaman: int = KEDALAMAN) -> str:
    """Token berbentuk JWT (tiga segmen) dengan header `[[[...]]]` sedalam `kedalaman` tingkat. Tanda tangannya palsu:
    PyJWT mengurai header lebih dulu, sebelum memeriksa tanda tangan."""
    header = _b64(b"[" * kedalaman + b"]" * kedalaman)
    isi = _b64(json.dumps({"sub": "x", "type": "access"}).encode())
    return f"{header}.{isi}.{_b64(b'tanda-tangan-palsu')}"


class TokenHeaderBersarangTests(unittest.IsolatedAsyncioTestCase):
    def test_decode_token_header_bersarang_terlalu_dalam_menghasilkan_none(self):
        self.assertIsNone(decode_token(token_header_bersarang()))

    async def test_route_ber_auth_menjawab_401_bukan_500(self):
        app = FastAPI()

        @app.get("/aku")
        async def aku(user=Depends(get_current_user)):
            return {"ok": True}

        async def _db():   # tidak tersentuh: token ditolak sebelum database dibaca
            yield None
        app.dependency_overrides[get_db] = _db   # `get_current_user` yang asli
        # raise_app_exceptions=False: galat yang tak tertangani muncul sebagai respons 500 seperti di server,
        # bukan sebagai lemparan di tes.
        klien = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t",
        )
        self.addAsyncCleanup(klien.aclose)
        r = await klien.get("/aku", headers={"Authorization": f"Bearer {token_header_bersarang()}"})
        self.assertEqual(r.status_code, 401, r.text)


if __name__ == "__main__":
    unittest.main()
