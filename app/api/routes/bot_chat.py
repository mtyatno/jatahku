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
@limiter.limit("30/hour", key_func=chat_key_func)
async def chat_photo(
    request: Request,
    image: UploadFile = File(...),
    client_id: str | None = Form(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    user: User = Depends(get_current_user),
):
    """Foto struk dari chat → alur scan struk bot (kuota & batas sama)."""
    # Validasi format/ukuran sama dengan tombol Struk di form transaksi.
    from app.api.routes.transactions import _read_receipt_upload
    data, mime = await _read_receipt_upload(image)
    return {"ops": await run_photo(user, data, mime, client_id)}
