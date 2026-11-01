"""API Admin "Aturan belajar" Kotak Struk (spec 2026-11-01 §6; pre-flight §6, G5, G6, G10, K10). Admin saja.

- `GET /admin/kotak/rules?status=` — aturan per status (bawaan `menunggu`; `semua`) + jumlah per status. Tiap baris
  membawa contoh SINTETIS (label + "Rp##.###", tanpa data user) dan `warning` bila label memuat kata status/metode
  (aturan seperti itu tidak bisa melewati blokir status, tetapi bisa membuat nama/nominal yang salah tampak yakin).
- `POST /admin/kotak/rules/{id}/setujui|tolak|cabut` — keputusan pemilik (transisi G5 di `belajar.DECISIONS`;
  selain itu 409, id tidak ada 404; setujui aturan dengan < 2 user juga 409). Body hanya `note` (≤ 200 karakter
  sesudah dirapikan, tanpa karakter kontrol) dan `from_status` opsional (status yang dilihat admin; keputusan hanya
  berlaku bila aturan masih berstatus itu, jadi dua keputusan bersamaan tidak saling menimpa). Teks, jenis, kunci, dan
  hitungan aturan tidak pernah diambil dari klien, karena pembaca mempercayai bahwa nilai aturan adalah label aman dari
  suara. Commit LALU `invalidate_rules_cache()` (L3), supaya pembaca memakai keputusan baru tanpa menunggu cache
  5 menit; juga bila balasan commit gagal (commit bisa saja sudah sampai), karena memuat ulang hanya membaca isi
  database.
- `GET /admin/kotak/votes` — angka suara per (aplikasi, jenis): jumlah user berbeda dan jumlah label berbeda, termasuk
  pola satu user, TANPA teks label (G6: ambang 2 user ada untuk menyembunyikan data satu user).

Daftar dibaca langsung dari tabel, bukan dari cache pembaca `approved_rules` (hanya yang disetujui, tanpa hitungan).
"""
import unicodedata
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.models import ProofRule, ProofRuleVote, User
from app.services.kotak_struk import belajar
from app.services.kotak_struk.kerangka import _words as label_words   # normalisasi kata yang sama dengan safe_label

router = APIRouter()

NOTE_MAX = 200   # = kolom proof_rules.note String(200); `decide` tidak memotong

# Kata status, metode/sumber dana, dan label teks bebas (keterangan transfer user, nomor referensi): label seperti
# "status", "metode pembayaran", atau "keterangan" hampir pasti bukan label nominal/penerima/tanggal (review L2,
# catatan L3, review L4a m-5). Hanya peringatan untuk pemilik, bukan gerbang. "selesai" sengaja tidak: "waktu selesai"
# label tanggal sungguhan.
WARNING_WORDS = frozenset({
    "status", "berhasil", "gagal", "pending", "dibatalkan", "batal",
    "metode", "sumber",
    "keterangan", "catatan", "berita", "pesan", "deskripsi", "ref", "referensi", "kode",
})

# Contoh sintetis per jenis: hanya label aturan + nilai tersamar.
EXAMPLE_VALUE = {
    belajar.KIND_TOTAL: "Rp##.###",
    belajar.KIND_PIHAK: "NAMA PENERIMA",
    belajar.KIND_TANGGAL: "## Okt ####",
}

StatusFilter = Literal["menunggu", "disetujui", "ditolak", "dicabut", "semua"]


class RuleCounts(BaseModel):
    menunggu: int = 0
    disetujui: int = 0
    ditolak: int = 0
    dicabut: int = 0


class ProofRuleOut(BaseModel):
    id: UUID
    kind: str
    rule_key: str
    value: str
    users: int
    households: int
    status: str
    created_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[UUID] = None
    decided_by_name: Optional[str] = None
    note: Optional[str] = None
    example: str
    warning: bool


class ProofRulesResponse(BaseModel):
    counts: RuleCounts
    rules: list[ProofRuleOut]


class RuleDecisionIn(BaseModel):
    """Hanya catatan; field lain (value, kind, status, ...) ditolak 422."""
    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)
    # Status yang dilihat admin (review L4a m-2). Tanpa field ini: syaratnya semua status asal yang sah (G5).
    from_status: Optional[Literal["menunggu", "disetujui", "ditolak", "dicabut"]] = None

    @field_validator("note", mode="before")
    @classmethod
    def _trim(cls, v):
        """Dirapikan SEBELUM batas panjang; kosong -> null."""
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("note")
    @classmethod
    def _no_control_chars(cls, v):
        """NUL dan karakter kontrol lain (baris baru, tab, C1) -> 422, bukan galat database (review L4a m-3)."""
        if v is not None and any(unicodedata.category(ch) == "Cc" for ch in v):
            raise ValueError("Catatan tidak boleh memuat karakter kontrol")
        return v


class ProofVoteRow(BaseModel):
    rule_key: str
    kind: str
    users: int
    values: int


class ProofVotesResponse(BaseModel):
    rows: list[ProofVoteRow]


def synthetic_example(kind: str, value: str) -> str:
    """"Total bayar Rp##.###": label aturan (huruf awal kapital) + nilai tersamar; tidak pernah data user."""
    label = value[:1].upper() + value[1:]
    return f"{label} {EXAMPLE_VALUE.get(kind, '…')}"


def has_warning(value: str) -> bool:
    """Kata utuh, tanda baca di tepi kata dilepas seperti `safe_label` ("(status) bayar", "keterangan:")."""
    return bool(set(label_words(value)) & WARNING_WORDS)


def _rule_out(rule: ProofRule, decided_by_name: str | None) -> ProofRuleOut:
    return ProofRuleOut(
        id=rule.id, kind=rule.kind, rule_key=rule.rule_key, value=rule.value, users=rule.users,
        households=rule.households, status=rule.status, created_at=rule.created_at, decided_at=rule.decided_at,
        decided_by=rule.decided_by, decided_by_name=decided_by_name,
        note=rule.note, example=synthetic_example(rule.kind, rule.value), warning=has_warning(rule.value),
    )


@router.get("/rules", response_model=ProofRulesResponse)
async def list_rules(
    status: StatusFilter = Query("menunggu"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Aturan belajar per status, urut pendukung terbanyak lalu yang lebih dulu dibuat."""
    counts = RuleCounts()
    for st, n in (await db.execute(select(ProofRule.status, func.count()).group_by(ProofRule.status))).all():
        if st in belajar.RULE_STATUSES:
            setattr(counts, st, n)
    q = (select(ProofRule, User.name).outerjoin(User, User.id == ProofRule.decided_by)
         .order_by(ProofRule.users.desc(), ProofRule.created_at.asc(), ProofRule.id.asc()))
    if status != "semua":
        q = q.where(ProofRule.status == status)
    rows = (await db.execute(q)).all()
    return ProofRulesResponse(counts=counts, rules=[_rule_out(rule, name) for rule, name in rows])


async def _decide(action: str, rule_id: UUID, body: RuleDecisionIn | None, admin: User, db: AsyncSession) -> ProofRuleOut:
    body = body or RuleDecisionIn()
    try:
        rule = await belajar.decide(db, rule_id, action, by=admin.id, note=body.note, now=datetime.now(timezone.utc),
                                    from_status=body.from_status)
    except belajar.RuleNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except belajar.RuleConflict as e:          # juga RuleBelowThreshold
        raise HTTPException(status_code=409, detail=str(e))
    out = _rule_out(rule, admin.name)
    try:
        await db.commit()
    finally:
        # SESUDAH percobaan commit (L3; review L4a m-1): bila balasan COMMIT hilang, keputusan mungkin sudah tersimpan.
        belajar.invalidate_rules_cache()
    return out


@router.post("/rules/{rule_id}/setujui", response_model=ProofRuleOut)
async def approve_rule(
    rule_id: UUID,
    body: Optional[RuleDecisionIn] = Body(None),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Setujui (dari menunggu, ditolak, atau dicabut): pembaca memakai label ini mulai pembacaan berikutnya."""
    return await _decide("setujui", rule_id, body, admin, db)


@router.post("/rules/{rule_id}/tolak", response_model=ProofRuleOut)
async def reject_rule(
    rule_id: UUID,
    body: Optional[RuleDecisionIn] = Body(None),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Tolak (dari menunggu). Suara tetap tersimpan."""
    return await _decide("tolak", rule_id, body, admin, db)


@router.post("/rules/{rule_id}/cabut", response_model=ProofRuleOut)
async def revoke_rule(
    rule_id: UUID,
    body: Optional[RuleDecisionIn] = Body(None),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Cabut (dari disetujui): pembaca berhenti memakai label ini."""
    return await _decide("cabut", rule_id, body, admin, db)


@router.get("/votes", response_model=ProofVotesResponse)
async def list_votes(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Angka suara per (aplikasi, jenis), termasuk pola satu user; tanpa teks label (G6)."""
    users = func.count(distinct(ProofRuleVote.user_id))
    rows = (await db.execute(
        select(ProofRuleVote.rule_key, ProofRuleVote.kind, users, func.count(distinct(ProofRuleVote.value)))
        .group_by(ProofRuleVote.rule_key, ProofRuleVote.kind)
        .order_by(users.desc(), ProofRuleVote.rule_key.asc(), ProofRuleVote.kind.asc())
    )).all()
    return ProofVotesResponse(rows=[ProofVoteRow(rule_key=k, kind=kind, users=u, values=v) for k, kind, u, v in rows])
