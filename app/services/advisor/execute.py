"""Rencana dana AI Advisor v2 ke database: `POST /advisor/plan` dan `POST /advisor/execute`
(02-aturan.md §8.9, §14).

execute = satu langkah konfirmasi:
1. idempoten dengan `client_ref` (Redis `txnref:*`, sama dengan pencatatan transaksi);
2. kunci baris household (`FOR NO KEY UPDATE`, pola `balance_check.apply`) — dua anggota
   yang mengeksekusi bersamaan diserialkan, dan `POST /envelopes/transfer` memakai
   kunci yang sama;
3. snapshot + metrik dihitung ulang DI DALAM kunci; `saldo_versi` beda → 409 dengan
   rencana baru;
4. semua transfer + pembayaran tagihan dalam satu commit.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from app.services.advisor.metrics import compute_metrics, rupiah
from app.services.advisor.planner import PlanInputError, saldo_versi, susun_rencana
from app.services.advisor.snapshot import load_snapshot

ZERO = Decimal("0")
logger = logging.getLogger("jatahku.advisor.execute")


class PlanError(Exception):
    def __init__(self, status: int, detail: str, rencana_baru: dict | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.rencana_baru = rencana_baru


def _rp(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


async def lock_household(db, hid) -> None:
    """Kunci baris household sampai commit (dipakai execute & transfer manual)."""
    from sqlalchemy import select
    from app.models.models import Household
    await db.execute(select(Household.id).where(Household.id == hid).with_for_update(key_share=True))


def _plan(snap, m, kebutuhan, kecuali, sertakan) -> dict:
    try:
        rencana = susun_rencana(snap, m, kebutuhan, kecuali, sertakan)
    except PlanInputError as exc:
        raise PlanError(400, str(exc)) from exc
    return rencana.to_api(saldo_versi(snap, m))


async def build_plan(user, db, kebutuhan: list[dict], kecuali=None, sertakan=None, today=None) -> dict:
    snap = await load_snapshot(user, db, today=today)
    if snap.household_id is None:
        raise PlanError(400, "Belum punya household")
    return _plan(snap, compute_metrics(snap), kebutuhan, kecuali, sertakan)


def _kebutuhan_dari_baris(rencana: list[dict], bayar: list[dict]) -> list[dict]:
    """Cadangan bila klien tidak mengirim `kebutuhan`: jumlahkan `ke` per tujuan."""
    per = defaultdict(lambda: ZERO)
    for row in rencana:
        for k in row.get("ke") or []:
            per[str(k["tujuan_id"])] += Decimal(str(k["jumlah"]))
    return [{"tujuan_id": t, "jumlah": j} for t, j in per.items() if j > 0]


def _validasi(snap, m, rencana: list[dict], bayar: list[dict]):
    """Baris tercentang → [(dari, ke, jumlah)], tagihan → [RecurringSnap]. PlanError 400 bila tidak sah."""
    envs = {e.id: e for e in snap.envelopes}
    moves = []
    keluar = defaultdict(lambda: ZERO)
    for row in rencana:
        if row.get("tercentang") is False:
            continue
        dari = str(row["dari_id"])
        src = envs.get(dari)
        if src is None or dari not in m.amplop:
            raise PlanError(400, "Amplop sumber tidak ditemukan")
        if src.is_locked:
            raise PlanError(400, f"Amplop {src.name} terkunci")
        if src.owner_id is not None and src.owner_id != snap.viewer_id:
            raise PlanError(400, "Amplop sumber tidak ditemukan")
        for k in row.get("ke") or []:
            ke = str(k["tujuan_id"])
            jumlah = _rp(k["jumlah"])
            if ke not in m.amplop:
                raise PlanError(400, "Amplop tujuan tidak ditemukan")
            if ke == dari:
                raise PlanError(400, "Amplop sumber dan tujuan tidak boleh sama")
            if jumlah <= 0:
                raise PlanError(400, "Jumlah harus lebih dari 0")
            moves.append((dari, ke, jumlah))
            keluar[dari] += jumlah
    tujuan = {ke for _, ke, _ in moves}
    for dari, total in keluar.items():
        if dari in tujuan:
            raise PlanError(400, "Amplop tujuan tidak bisa sekaligus jadi sumber")
        batas = max(m.amplop[dari].sisa, ZERO)  # sama dengan fund_shift.max_transferable
        if total > batas:
            raise PlanError(400, f"Maksimal transfer dari {envs[dari].name}: Rp{rupiah(batas):,}".replace(",", "."))

    from app.services.recurring_status import payment_window_error
    recs = {r.id: r for r in snap.recurring}
    tagihan = []
    seen = set()
    for item in bayar:
        rid = str(item["recurring_id"])
        rec = recs.get(rid)
        if rec is None:
            raise PlanError(400, "Langganan tidak ditemukan")
        if rid in seen:
            continue
        seen.add(rid)
        err = payment_window_error(rec.next_run, snap.payday_day, snap.today)
        if err:
            raise PlanError(409, err)
        tagihan.append(rec)
    return moves, tagihan


async def execute_plan(user, db, body: dict, today=None) -> dict:
    """body = {"rencana", "bayar", "saldo_versi", "client_ref", "kebutuhan"?, "kecuali"?, "sertakan"?}."""
    from app.services import idempotency

    ref = body.get("client_ref")
    done = await idempotency.lookup(user.id, ref)
    if done == idempotency.PENDING:
        raise PlanError(409, "Rencana ini sedang diproses")
    if done:
        try:
            return json.loads(done)
        except ValueError:
            return {"status": "ok", "transfer": [], "dibayar": []}
    if not await idempotency.reserve(user.id, ref):
        raise PlanError(409, "Rencana ini sedang diproses")

    try:
        result, goals_before = await _execute_locked(user, db, body, today)
    except BaseException:
        await db.rollback()
        await idempotency.release(user.id, ref)
        raise
    await idempotency.store(user.id, ref, json.dumps(result))
    try:  # sesudah commit: gagal kirim notifikasi target tidak membatalkan rencana
        from app.services.goal_notify import notify_goals_reached
        await notify_goals_reached(db, user, goals_before)
    except Exception as exc:
        logger.warning("notify_goals_reached gagal: %s", exc)
    return result


async def _execute_locked(user, db, body: dict, today) -> dict:
    from sqlalchemy import select
    from app.models.models import (
        Envelope, HouseholdMember, RecurringFrequency, RecurringTransaction, Transaction, TransactionSource,
    )
    from app.services.fund_shift import record_transfer
    from app.services.goal_notify import goal_snapshot
    from app.services.recurring_processor import _next_date

    hid = (await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )).scalar_one_or_none()
    if not hid:
        raise PlanError(400, "Belum punya household")
    await lock_household(db, hid)

    snap = await load_snapshot(user, db, today=today)
    m = compute_metrics(snap)
    rencana = body.get("rencana") or []
    bayar = body.get("bayar") or []
    if saldo_versi(snap, m) != body.get("saldo_versi"):
        kebutuhan = body.get("kebutuhan") or _kebutuhan_dari_baris(rencana, bayar)
        baru = None
        if kebutuhan:
            try:
                baru = _plan(snap, m, kebutuhan, body.get("kecuali"), body.get("sertakan"))
            except PlanError:
                baru = None
        raise PlanError(409, "Saldo berubah", rencana_baru=baru)

    moves, tagihan = _validasi(snap, m, rencana, bayar)
    if not moves and not tagihan:
        raise PlanError(400, "Rencana kosong")

    goals_before = await goal_snapshot(db, hid)
    ids = {dari for dari, _, _ in moves} | {ke for _, ke, _ in moves}
    rows = (await db.execute(select(Envelope).where(Envelope.id.in_(_uuids(ids))))).scalars().all() if ids else []
    env_rows = {str(e.id): e for e in rows}

    gabung = defaultdict(lambda: ZERO)
    for dari, ke, jumlah in moves:
        gabung[(dari, ke)] += jumlah
    transfer = []
    for (dari, ke), jumlah in gabung.items():
        income = record_transfer(db, hid, user.id, env_rows[dari], env_rows[ke], jumlah)
        transfer.append({"dari_id": dari, "dari_nama": env_rows[dari].name, "ke_id": ke,
                         "ke_nama": env_rows[ke].name, "jumlah": rupiah(jumlah), "income_id": str(income.id)})

    dibayar = []
    if tagihan:
        rec_rows = (await db.execute(
            select(RecurringTransaction).where(RecurringTransaction.id.in_(_uuids(r.id for r in tagihan)))
        )).scalars().all()
        by_id = {str(r.id): r for r in rec_rows}
        for snap_rec in tagihan:
            rec = by_id[snap_rec.id]
            txn = Transaction(
                envelope_id=rec.envelope_id, user_id=user.id, amount=rec.amount,
                description=f"🔄 {rec.description}", source=TransactionSource.webapp,
                transaction_date=snap.today,
            )
            db.add(txn)
            freq = rec.frequency if isinstance(rec.frequency, RecurringFrequency) else RecurringFrequency(rec.frequency)
            rec.next_run = _next_date(rec.next_run, freq)
            await db.flush()
            dibayar.append({"recurring_id": snap_rec.id, "deskripsi": rec.description, "jumlah": rupiah(rec.amount),
                            "txn_id": str(txn.id), "next_run": rec.next_run.isoformat()})

    await db.commit()
    return {"status": "ok", "transfer": transfer, "dibayar": dibayar}, goals_before


def _uuids(ids):
    import uuid
    return [uuid.UUID(str(i)) for i in ids]
