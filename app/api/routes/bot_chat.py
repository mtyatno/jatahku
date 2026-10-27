"""Chat bot di webapp: endpoint untuk panel chat PWA.

Pesan dan tombol diproses oleh handler bot Telegram yang sama lewat
`app/bot/web_adapter.py`, jadi perilaku chat di web = perilaku @JatahkuBot.
"""
import hashlib

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.bot.web_adapter import run_action, run_message, run_photo
from app.core.deps import get_current_user
from app.models.models import User

router = APIRouter()

# Pola sama dengan transactions.py: limiter lokal, kunci per token user.
limiter = Limiter(key_func=get_remote_address)


def chat_key_func(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth:
        return "chat:" + hashlib.sha256(auth.encode()).hexdigest()[:16]
    return get_remote_address(request)


class ChatMessageIn(BaseModel):
    # Bot sendiri menolak >500 karakter dengan pesan yang ramah; batas di sini
    # hanya mencegah payload besar.
    text: str = Field(min_length=1, max_length=2000)
    # Id pesan dari webapp — kirim ulang dengan id yang sama tidak diproses dua kali.
    client_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ChatActionIn(BaseModel):
    message_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9a-f]+$")
    data: str = Field(min_length=1, max_length=64)  # batas callback_data Telegram


@router.post("/message")
@limiter.limit("60/minute", key_func=chat_key_func)
async def chat_message(request: Request, body: ChatMessageIn, user: User = Depends(get_current_user)):
    return {"ops": await run_message(user, body.text, body.client_id)}


@router.post("/action")
@limiter.limit("60/minute", key_func=chat_key_func)
async def chat_action(request: Request, body: ChatActionIn, user: User = Depends(get_current_user)):
    return {"ops": await run_action(user, body.message_id, body.data)}


@router.post("/photo")
async def chat_photo(
    request: Request,
    image: UploadFile = File(...),
    client_id: str | None = Form(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    user: User = Depends(get_current_user),
):
    """Foto struk/bukti dari chat → Kotak Struk lewat alur foto bot (`handle_non_text`); batas intake Kotak Struk
    berlaku; PDF belum diterima di route ini (keputusan Bagian B)."""
    # Validasi format/ukuran sama dengan tombol Struk di form transaksi, kecuali PDF (lihat docstring).
    from app.api.routes.transactions import _read_receipt_upload
    data, mime = await _read_receipt_upload(image, allow_pdf=False)
    return {"ops": await run_photo(user, data, mime, client_id)}


@router.post("/proaktif")
@limiter.limit("30/minute", key_func=chat_key_func)
async def chat_proaktif(request: Request, user: User = Depends(get_current_user)):
    """Pesan proaktif AI Advisor untuk chat web, ditarik saat panel dibuka (S16, 02-aturan.md §9):
    item hari ini, sekali per hari, mengikuti batas 1/hari & 2 permukaan. Kosong = `ops: []`."""
    from app.bot.web_adapter import Outbox
    from app.services.advisor.proaktif import untuk_chat
    text = await untuk_chat(user)
    outbox = Outbox()
    if text:
        outbox.send(text, parse_mode="HTML")
    return {"ops": outbox.ops}
