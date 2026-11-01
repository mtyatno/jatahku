"""Saran amplop untuk item Kotak Struk (spec 2026-10-26 bagian 4a).

Urutan sinyal: catatan user, peta merchant rumah tangga, kata kunci nama merchant, tanpa saran.
Amplop yang disarankan selalu dari daftar yang boleh dilihat user di rumah tangganya SEKARANG
(bukan `item.household_id` begitu saja): user yang sudah keluar dari sebuah rumah tangga tidak
pernah disarankan amplop bersamanya.
"""
import uuid
from fractions import Fraction

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ruang import ruang_keluarga_id
from app.models.models import Envelope, MerchantEnvelopeMap, ReceiptScan, User
from app.services.kotak_struk.config import CONFIDENT_SHARE
from app.services.kotak_struk.merchants import merchant_for_item
from app.services.txn_nlp import find_best_envelope


async def visible_expense_envelopes(db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID) -> list[Envelope]:
    """Amplop yang boleh disarankan ke user: aktif, `purpose == "expense"`, bersama atau pribadi user itu
    sendiri. Aturan yang sama dengan `find_best_envelope` dan dropdown amplop di web."""
    return list((await db.execute(
        select(Envelope).where(
            Envelope.household_id == household_id, Envelope.is_active == True,  # noqa: E712
            Envelope.purpose == "expense", or_(Envelope.owner_id == None, Envelope.owner_id == user_id))  # noqa: E711
    )).scalars().all())


def _suggestion(env: Envelope | None, confident: bool, source: str) -> dict:
    if env is None:
        return {"envelope_id": None, "envelope_name": None, "confident": False, "source": "none"}
    return {"envelope_id": str(env.id), "envelope_name": env.name, "confident": bool(confident), "source": source}


async def suggest_for_item(db: AsyncSession, item: ReceiptScan, user: User, *, note: str | None = None) -> dict:
    """`{envelope_id, envelope_name, confident, source: note|merchant|keyword|none}` untuk item `item` milik `user`."""
    household_id = await ruang_keluarga_id(db, user.id)  # saran amplop per ruang menyusul di R7
    if household_id is None:
        return _suggestion(None, False, "none")

    # 1. catatan user
    if note and note.strip():
        env, confident = await find_best_envelope(note, household_id, db, user.id)
        if env is not None:
            return _suggestion(env, confident, "note")

    # Item dari rumah tangga lain (user pindah) tidak memakai peta ataupun nama panggilan rumah tangga itu.
    same_household = item.household_id == household_id
    merchant = await merchant_for_item(db, item) if same_household else None

    # 2. peta merchant rumah tangga
    if merchant is not None:
        visible = {e.id: e for e in await visible_expense_envelopes(db, household_id, user.id)}
        rows = [r for r in (await db.execute(
            select(MerchantEnvelopeMap).where(MerchantEnvelopeMap.merchant_id == merchant.id)
        )).scalars().all() if r.envelope_id in visible and r.count > 0]
        if rows:
            top = max(rows, key=lambda r: (r.count, r.last_used_at, str(r.envelope_id)))
            confident = Fraction(top.count, sum(r.count for r in rows)) >= CONFIDENT_SHARE
            return _suggestion(visible[top.envelope_id], confident, "merchant")

    # 3. kata kunci nama merchant
    name = (merchant.display_name or merchant.raw_name) if merchant is not None else item.merchant
    if name:
        env, confident = await find_best_envelope(name, household_id, db, user.id)
        if env is not None:
            return _suggestion(env, confident, "keyword")

    # 4. tanpa saran
    return _suggestion(None, False, "none")
