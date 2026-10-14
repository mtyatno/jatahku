"""Pencatatan multi-item via Telegram: "makan 30k, parkir 5k, kopi 20k".

Alur:
1. Item yang amplopnya dikenali melewati cek perilaku yang sama dengan web
   (check_behavior: kunci, dana, cooling, limit harian), berurutan, sehingga item
   sebelumnya ikut terhitung untuk item berikutnya. Yang lolos dicatat; cooling
   → transaksi pending; kunci/limit harian → tidak dicatat (alasan di ringkasan).
2. Item tanpa amplop atau yang kurang dana masuk antrean dan diproses satu per satu di satu pesan yang diedit:
   - amplop belum dikenali  → user memilih amplop
   - amplop kurang dana     → tawaran geser dana dari amplop lain (sama seperti
                              pencatatan satu item, lihat handlers._send_fund_shift_offer)
3. Di akhir tampil ringkasan: yang tercatat (dan dana yang digeser), serta item
   yang dilewati / tertahan beserta alasannya.

State antrean disimpan di Redis `batch:{key}` (TTL 10 menit). Ketukan tombol
diserialkan dengan kunci `batchlock:{key}` dan dicocokkan dengan posisi antrean
saat ini, jadi ketukan ganda atau tombol lama tidak mencatat/menggeser dua kali.
"""
import json
import secrets
from datetime import date
from decimal import Decimal

import redis.asyncio as aioredis
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.handlers import (
    AsyncSessionLocal, _esc, _is_setup_complete, check_behavior,
    create_pending_transaction, find_best_envelope, format_currency,
    get_envelopes_with_spent, get_household_id, get_or_create_user,
    save_learned_keywords, settings,
)
from app.bot.tglogin_cmd import reply_setup_needed
from app.models.models import Transaction, TransactionSource, User
from app.services.fund_shift import compute_shortfall, pick_sources, record_transfer

BATCH_TTL = 600
LOCK_TTL = 30
FUNDS_BLOCKS = ("not_funded", "insufficient")


# ── Format ───────────────────────────────────────────────────────────────────

def _env_label(env) -> str:
    return f"{env.emoji or '📁'} {_esc(env.name)}"


def _item_label(item) -> str:
    return f"{format_currency(item['amount'])} — {_esc(item['desc'])}"


def render_summary(data) -> str:
    lines = data.get("auto_lines", [])
    notes = data.get("notes", [])
    if lines:
        out = [f"✅ <b>{len(lines)} transaksi dicatat</b>", ""] + lines
    else:
        out = ["ℹ️ <b>Tidak ada transaksi yang dicatat</b>"]
    if notes:
        out += [""] + notes
    if lines and data.get("total") is not None:
        out += ["", f"💸 Total: <b>{format_currency(data['total'])}</b>"]
    return "\n".join(out)


def _progress_header(data, flash=None) -> str:
    done = data.get("auto_lines", []) + data.get("notes", [])
    parts = []
    if flash:
        parts.append(flash)
    if done:
        parts.append("\n".join(done))
    return ("\n\n".join(parts) + "\n" + "─" * 20 + "\n") if parts else ""


# ── Pencatatan ───────────────────────────────────────────────────────────────

def _add_txn(db, user, env, amount, desc):
    db.add(Transaction(
        envelope_id=env.id, user_id=user.id, amount=Decimal(amount),
        description=desc, source=TransactionSource.telegram,
        transaction_date=date.today(),
    ))


async def _record_item(db, user, hid, data, item, target_env, source_env=None,
                       moved=Decimal("0"), check=None):
    """Catat satu item antrean (opsional setelah menggeser `moved` dari
    `source_env`). Cek perilaku tetap berlaku; hasil masuk ke ringkasan."""
    amount, desc = Decimal(item["amount"]), item["desc"]
    shift_info = f" · 🔁 +{format_currency(moved)} dari {_env_label(source_env)}" if moved > 0 else ""

    savepoint = None
    if moved > 0:
        # Savepoint, bukan db.rollback(): rollback penuh meng-expire semua objek
        # sesi (user, amplop) dan aksesnya sesudah itu gagal di async
        # (MissingGreenlet) — padahal item antrean berikutnya masih memakainya.
        savepoint = await db.begin_nested()
        record_transfer(db, hid, user.id, source_env, target_env, moved)
        await db.flush()
        check = None  # dana berubah — cek ulang
    if check is None:
        check = await check_behavior(target_env.id, user.id, amount, db)

    if check.allowed:
        _add_txn(db, user, target_env, amount, desc)
        await save_learned_keywords(user.id, desc, target_env.id, db)
        await db.commit()
        data.setdefault("auto_lines", []).append(
            f"{_env_label(target_env)}: {_item_label(item)}{shift_info}")
        if "total" in data:
            data["total"] += int(amount)
    elif check.check_type == "cooling":
        # create_pending_transaction meng-commit transfer sekalian.
        await create_pending_transaction(
            target_env.id, user.id, amount, desc,
            TransactionSource.telegram, cooling_hours=24, db=db)
        data.setdefault("notes", []).append(
            f"⏳ {_item_label(item)}: masuk cooling period 24 jam (/pending){shift_info}")
    else:
        # Tanpa transfer tidak ada perubahan yang perlu dibatalkan.
        if savepoint is not None:
            await savepoint.rollback()
        tail = " Dana tidak digeser." if moved > 0 else ""
        if check.check_type == "daily_limit":
            tail += " Kirim sebagai pesan terpisah untuk opsi naikkan limit hari ini."
        data.setdefault("notes", []).append(
            f"⚠️ {_item_label(item)}: {_esc(check.reason)} Tidak dicatat.{tail}")


# ── Langkah antrean ──────────────────────────────────────────────────────────

async def render_step(key, data, user, hid, db, flash=None):
    """Maju ke item antrean berikutnya yang butuh keputusan user.

    Item yang tidak butuh keputusan (dana sudah cukup, amplop dikunci, tidak ada
    sumber dana) diselesaikan di sini. Mengembalikan (teks, markup|None, selesai).
    """
    queue = data["queue"]
    payday_day = getattr(user, "payday_day", 1) or 1
    while data["pos"] < len(queue):
        pos = data["pos"]
        item = queue[pos]
        progress = f" ({pos + 1}/{len(queue)})" if len(queue) > 1 else ""
        env_data = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)

        if not item.get("env_id"):
            data["stage"] = "pick"
            keyboard = [[InlineKeyboardButton(
                f"{e['envelope'].emoji or '📁'} {e['envelope'].name} (sisa {format_currency(max(e['remaining'], Decimal('0')))})",
                callback_data=f"batch_{key}_{pos}_{e['envelope'].id}",
            )] for e in env_data]
            keyboard.append([InlineKeyboardButton("⏭ Lewati", callback_data=f"batch_{key}_{pos}_skip")])
            text = (f"{_progress_header(data, flash)}"
                    f"💰 {_item_label(item)}{progress}\n\nMasuk ke amplop mana?")
            return text, InlineKeyboardMarkup(keyboard), False

        by_id = {str(e["envelope"].id): e for e in env_data}
        target = by_id.get(item["env_id"])
        if not target:
            data.setdefault("notes", []).append(
                f"⚠️ {_item_label(item)}: amplop tidak tersedia. Tidak dicatat.")
            data["pos"] += 1
            continue
        target_env = target["envelope"]

        check = await check_behavior(target_env.id, user.id, Decimal(item["amount"]), db)
        if check.allowed or check.check_type not in FUNDS_BLOCKS:
            # Dana cukup (mis. sudah diisi), atau terblokir hal lain (kunci, cooling, limit).
            await _record_item(db, user, hid, data, item, target_env, check=check)
            data["pos"] += 1
            continue

        shortfall = compute_shortfall(target["remaining"], Decimal(item["amount"]))
        sources = pick_sources(env_data, target_env.id, shortfall)
        if not sources:
            data.setdefault("notes", []).append(
                f"💸 {_item_label(item)}: {_env_label(target_env)} kurang {format_currency(shortfall)} "
                f"dan tidak ada amplop lain dengan dana bebas cukup. Tidak dicatat.")
            data["pos"] += 1
            continue

        data["stage"] = "shift"
        data["sources"] = [str(s["envelope"].id) for s in sources]
        keyboard = [[InlineKeyboardButton(
            f"{s['envelope'].emoji or '📁'} {s['envelope'].name} (bebas {format_currency(s['free'])})",
            callback_data=f"bshift_{key}_{pos}_{i}",
        )] for i, s in enumerate(sources)]
        keyboard.append([InlineKeyboardButton("⏭ Lewati item ini", callback_data=f"bshift_{key}_{pos}_skip")])
        text = (
            f"{_progress_header(data, flash)}"
            f"💸 <b>Dana amplop kurang</b>{progress}\n\n"
            f"{_item_label(item)}\n"
            f"{_env_label(target_env)} · sisa {format_currency(max(target['remaining'], Decimal('0')))}\n"
            f"Kurang <b>{format_currency(shortfall)}</b>\n\n"
            f"Geser <b>{format_currency(shortfall)}</b> dari amplop lain supaya item ini tetap tercatat?"
        )
        return text, InlineKeyboardMarkup(keyboard), False

    return render_summary(data), None, True


async def _pick_step(db, user, hid, data, choice):
    item = data["queue"][data["pos"]]
    if choice == "skip":
        data.setdefault("notes", []).append(f"⏭ {_item_label(item)}: dilewati.")
        data["pos"] += 1
        return None
    payday_day = getattr(user, "payday_day", 1) or 1
    env_data = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
    if choice not in {str(e["envelope"].id) for e in env_data}:
        return "⚠️ Amplop itu tidak tersedia. Pilih amplop lain."
    # render_step yang memutuskan: catat, tawarkan geser dana, atau tahan.
    item["env_id"] = choice
    return None


async def _shift_step(db, user, hid, data, choice):
    item = data["queue"][data["pos"]]
    if choice == "skip":
        data.setdefault("notes", []).append(f"⏭ {_item_label(item)}: dilewati, dana tidak digeser.")
        data["pos"] += 1
        return None
    try:
        source_id = data.get("sources", [])[int(choice)]
    except (ValueError, IndexError):
        return None

    payday_day = getattr(user, "payday_day", 1) or 1
    env_data = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
    by_id = {str(e["envelope"].id): e for e in env_data}
    target, source = by_id.get(item["env_id"]), by_id.get(source_id)
    if not target:
        return None  # render_step mencatatnya sebagai tidak tersedia
    if not source:
        return "⚠️ Amplop sumber tidak tersedia. Pilih amplop lain."

    moved = compute_shortfall(target["remaining"], Decimal(item["amount"]))
    if moved > 0 and source["free"] < moved:
        return (f"⚠️ Dana bebas {_env_label(source['envelope'])} tinggal "
                f"{format_currency(max(source['free'], Decimal('0')))}, tidak cukup. Pilih amplop lain.")
    await _record_item(db, user, hid, data, item, target["envelope"],
                       source_env=source["envelope"], moved=moved)
    data["pos"] += 1
    return None


async def _run_callback(update, expected_stage, step):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 3)
    if len(parts) != 4:
        return
    _, key, idx_str, choice = parts
    try:
        idx = int(idx_str)
    except ValueError:
        return

    r = aioredis.from_url(settings.REDIS_URL)
    try:
        if not await r.set(f"batchlock:{key}", "1", nx=True, ex=LOCK_TTL):
            return  # ketukan lain sedang diproses
        try:
            raw = await r.get(f"batch:{key}")
            if not raw:
                await query.edit_message_text("⏰ Sesi sudah selesai atau expired. Kirim ulang pesan.")
                return
            data = json.loads(raw)
            data.setdefault("pos", idx)          # state format lama
            data.setdefault("stage", "pick")
            if data["pos"] != idx or data["stage"] != expected_stage:
                return  # tombol lama / sudah diproses

            async with AsyncSessionLocal() as db:
                user = (await db.execute(
                    select(User).where(User.telegram_id == str(query.from_user.id))
                )).scalar_one_or_none()
                if not user or str(user.id) != str(data.get("user_id")):
                    return  # bukan pemilik antrean ini
                hid = await get_household_id(user, db)
                flash = await step(db, user, hid, data, choice)
                text, markup, done = await render_step(key, data, user, hid, db, flash=flash)

            if done:
                await r.delete(f"batch:{key}")
            else:
                await r.set(f"batch:{key}", json.dumps(data), ex=BATCH_TTL)
        finally:
            await r.delete(f"batchlock:{key}")
    finally:
        await r.aclose()

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)


async def handle_batch_callback(update, context):
    """batch_{key}_{pos}_{envelope_id|skip} — pilih amplop untuk item antrean."""
    await _run_callback(update, "pick", _pick_step)


async def handle_batch_shift_callback(update, context):
    """bshift_{key}_{pos}_{source_idx|skip} — geser dana untuk item antrean."""
    await _run_callback(update, "shift", _shift_step)


# ── Pesan masuk ──────────────────────────────────────────────────────────────

async def handle_multi_expense(update, context, items):
    """Catat beberapa pengeluaran dari satu pesan; lihat docstring modul."""
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        setup_ok, _ = await _is_setup_complete(user, db)
        if not setup_ok:
            await reply_setup_needed(update, user)
            return
        hid = await get_household_id(user, db)
        payday_day = getattr(user, "payday_day", 1) or 1

        env_data = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
        if not env_data:
            await update.message.reply_text("Belum ada amplop. Ketik /template untuk buat.")
            return
        key = secrets.token_hex(4)
        data = {
            "user_id": str(user.id),
            "queue": [],
            "pos": 0,
            "stage": "pick",
            "auto_lines": [],
            "notes": [],
            "total": 0,
        }
        for amount, desc in items:
            env, _ = await find_best_envelope(desc, hid, db, user_id=user.id)
            item = {"amount": int(amount), "desc": desc, "env_id": str(env.id) if env else None}
            if env is None:
                data["queue"].append(item)
                continue
            # Sama dengan POST /transactions/batch di web: setiap item dicek, dan
            # item yang sudah tercatat ikut terhitung untuk item berikutnya.
            check = await check_behavior(env.id, user.id, Decimal(amount), db)
            if not check.allowed and check.check_type in FUNDS_BLOCKS:
                data["queue"].append(item)  # → tawaran geser dana
                continue
            await _record_item(db, user, hid, data, item, env, check=check)

        text, markup, done = await render_step(key, data, user, hid, db)

    if not done:
        r = aioredis.from_url(settings.REDIS_URL)
        try:
            await r.set(f"batch:{key}", json.dumps(data), ex=BATCH_TTL)
        finally:
            await r.aclose()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)
