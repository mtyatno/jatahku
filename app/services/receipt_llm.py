"""Fallback LLM (Groq vision) untuk struk yang gagal dibaca OCR — dengan plafon biaya.

MATI secara default (RECEIPT_LLM_ENABLED=False). Saat hidup, dua pengaman:

1. Plafon biaya bulanan global (rupiah). Sebelum memanggil API, biaya
   TERBURUK di-reservasi secara atomik di Redis (INCRBY). Kalau reservasi
   melewati plafon, reservasi dibatalkan dan LLM tidak dipanggil. Setelah
   panggilan selesai, reservasi disesuaikan ke biaya sebenarnya dari `usage`.
   Jadi total tagihan bulan ini tidak bisa melewati plafon, walau banyak
   request bersamaan.
2. Kuota per user per bulan (Basic/Pro dibedakan).

Semua kegagalan (plafon habis, kuota habis, API error) → kembalikan None;
pemanggil cukup memakai hasil OCR apa adanya.
"""
from __future__ import annotations

import base64
import json
import math
import re
from datetime import date

import httpx

from app.core.config import get_settings

IMAGE_TOKENS = 2048  # tarif Groq: tiap gambar dihitung 2048 token input
PROMPT_TOKENS = 450  # instruksi + overhead pesan (dibulatkan ke atas)

PROMPT = (
    "Kamu membaca foto struk belanja Indonesia. Jawab HANYA JSON: "
    '{"merchant": nama toko atau null, "date": "YYYY-MM-DD" atau null, '
    '"total": total akhir yang dibayar dalam rupiah (integer) atau null}. '
    "Total = GRAND TOTAL / TOTAL BELANJA setelah diskon & pajak, BUKAN tunai/kembalian/DPP/PPN. "
    "Angka 35.000 atau 35,000 = 35000. Jika bukan struk, semua null."
)


def _month_key() -> str:
    return date.today().strftime("%Y-%m")


def _cost_idr(tokens_in: int, tokens_out: int) -> int:
    s = get_settings()
    usd = tokens_in * s.RECEIPT_LLM_PRICE_IN_USD / 1e6 + tokens_out * s.RECEIPT_LLM_PRICE_OUT_USD / 1e6
    return max(1, math.ceil(usd * s.RECEIPT_LLM_USD_IDR))


def worst_case_cost_idr() -> int:
    s = get_settings()
    return _cost_idr(IMAGE_TOKENS + PROMPT_TOKENS, s.RECEIPT_LLM_MAX_OUTPUT_TOKENS)


def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(get_settings().REDIS_URL)


async def budget_status() -> dict:
    """Untuk halaman Admin: pemakaian bulan ini vs plafon."""
    s = get_settings()
    r = _redis()
    try:
        spent = int(await r.get(f"receipt_llm:cost:{_month_key()}") or 0)
        calls = int(await r.get(f"receipt_llm:calls:{_month_key()}") or 0)
    finally:
        await r.aclose()
    return {
        "enabled": s.RECEIPT_LLM_ENABLED,
        "budget_idr": s.RECEIPT_LLM_MONTHLY_BUDGET_IDR,
        "spent_idr": spent,
        "calls": calls,
    }


def _parse_reply(content: str) -> dict | None:
    content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S)
    m = re.search(r"\{.*\}", content, flags=re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    total = data.get("total")
    if isinstance(total, str):
        total = re.sub(r"[^\d]", "", total) or None
    try:
        total = int(float(total)) if total is not None else None
    except (TypeError, ValueError):
        total = None
    if total is not None and not (100 <= total <= 100_000_000):
        total = None
    parsed_date = None
    if isinstance(data.get("date"), str):
        try:
            parsed_date = date.fromisoformat(data["date"][:10])
        except ValueError:
            parsed_date = None
        # Sama dengan parser OCR: tolak tanggal masa depan / lebih dari setahun lalu.
        if parsed_date and not (-1 <= (date.today() - parsed_date).days <= 366):
            parsed_date = None
    merchant = data.get("merchant")
    merchant = str(merchant).strip()[:100] if merchant else None
    if total is None and merchant is None and parsed_date is None:
        return None
    return {"merchant": merchant, "date": parsed_date, "total": total}


async def try_llm_fallback(image_bytes: bytes, content_type: str, user_id, plan: str) -> dict | None:
    """Kembalikan {"merchant","date","total"} atau None (mati/plafon/kuota/error)."""
    s = get_settings()
    if not s.RECEIPT_LLM_ENABLED or not s.GROQ_API_KEY:
        return None

    month = _month_key()
    user_limit = s.RECEIPT_LLM_USER_MONTHLY_PRO if plan == "pro" else s.RECEIPT_LLM_USER_MONTHLY_BASIC
    cost_key = f"receipt_llm:cost:{month}"
    calls_key = f"receipt_llm:calls:{month}"
    user_key = f"receipt_llm:user:{user_id}:{month}"
    reserve = worst_case_cost_idr()
    ttl = 40 * 24 * 3600

    r = _redis()
    try:
        # 1) Kuota per user
        used = await r.incr(user_key)
        await r.expire(user_key, ttl)
        if used > user_limit:
            await r.decr(user_key)
            return None
        # 2) Reservasi biaya terburuk terhadap plafon global (atomik)
        spent = await r.incrby(cost_key, reserve)
        await r.expire(cost_key, ttl)
        if spent > s.RECEIPT_LLM_MONTHLY_BUDGET_IDR:
            await r.decrby(cost_key, reserve)
            await r.decr(user_key)
            return None

        # Default: anggap ditagih sebesar reservasi. Reservasi hanya dikembalikan
        # kalau request pasti tidak sampai/ditolak (tidak ditagih Groq).
        actual = reserve
        result = None
        try:
            b64 = base64.b64encode(image_bytes).decode()
            mime = content_type if content_type.startswith("image/") else "image/jpeg"
            body = {
                "model": s.RECEIPT_LLM_MODEL,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]}],
                "response_format": {"type": "json_object"},
                "max_tokens": s.RECEIPT_LLM_MAX_OUTPUT_TOKENS,
                "temperature": 0,
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    s.RECEIPT_LLM_API_URL, json=body,
                    headers={"Authorization": f"Bearer {s.GROQ_API_KEY}"},
                )
            if res.status_code == 200:
                payload = res.json()
                usage = payload.get("usage") or {}
                if usage:
                    actual = _cost_idr(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))
                message = ((payload.get("choices") or [{}])[0] or {}).get("message") or {}
                result = _parse_reply(message.get("content") or "")
            elif 400 <= res.status_code < 500:
                actual = 0  # ditolak (kunci/limit/format) → tidak ditagih
            # 5xx: tidak pasti → reservasi tetap dihitung
        except (httpx.ConnectError, httpx.ConnectTimeout):
            actual = 0  # request tidak pernah terkirim
        except Exception:  # timeout baca, respons rusak, dll. → tetap dihitung
            result = None
        # 3) Sesuaikan reservasi ke biaya sebenarnya. Reservasi sudah dibuat
        #    pesimis, jadi biasanya ini pengembalian; kalaupun lebih, selisihnya
        #    dicatat agar panggilan berikutnya ikut tertahan plafon.
        delta = actual - reserve
        if delta < 0:
            await r.decrby(cost_key, -delta)
        elif delta > 0:
            await r.incrby(cost_key, delta)
        if actual:
            await r.incr(calls_key)
            await r.expire(calls_key, ttl)
        else:
            await r.decr(user_key)  # gagal → kuota user dikembalikan
        return result
    finally:
        await r.aclose()
