"""Pencatatan multi-item via Telegram: "makan 30k, parkir 5k, kopi 20k".

Aturannya sama dengan web (POST /transactions/batch + FundEnvelopeModal), lewat
service bersama app/services/expense_rules.py dan app/services/fund_shift.py.

Alur:
1. Item yang amplopnya dikenali dicek berurutan dengan check_expense (amplop
   tabungan, batas paket, kunci, dana, cooling, limit harian), sehingga item
   sebelumnya ikut terhitung untuk item berikutnya. Yang lolos dicatat;
   cooling → transaksi pending; blok lain → tidak dicatat (alasan di ringkasan).
2. Item tanpa amplop atau yang kurang dana masuk antrean dan diproses satu per
   satu di satu pesan yang diedit:
   - amplop belum dikenali → user memilih amplop (tanpa tabungan/sinking fund,
     sama dengan dropdown web)
   - amplop kurang dana    → geser dari amplop lain atau top-up pemasukan
                             (dua tab modal web)
3. Di akhir tampil ringkasan: yang tercatat (dan dana yang ditambahkan), item
   yang dilewati / tertahan beserta alasannya, total, dan streak.

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
    AsyncSessionLocal, _esc, _is_setup_complete, _spendable_rows, _streak_text,
    create_pending_transaction, find_best_envelope, format_currency,
    get_envelopes_with_spent, get_household_id, get_or_create_user, settings,
)
from app.bot.tglogin_cmd import reply_setup_needed
from app.models.models import Transaction, TransactionSource, User
from app.services.expense_rules import FUNDS_BLOCKS, after_expense_recorded, check_expense
from app.services.fund_shift import (
    compute_shortfall, pick_sources, record_topup, record_transfer, transfer_error,
)

BATCH_TTL = 600
LOCK_TTL = 30


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
    if data.get("streak"):
        out += ["", data["streak"]]
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

async def _record_item(db, user, hid, data, item, target_env, source_env=None,
                       funded=Decimal("0"), topup=False, check=None):
    """Catat satu item, opsional setelah menambah `funded` ke amplop tujuan
    (geser dari `source_env`, atau top-up pemasukan bila `topup`). Semua aturan
    check_expense tetap berlaku; hasilnya masuk ke ringkasan."""
    amount, desc = Decimal(item["amount"]), item["desc"]
    info = ""
    if funded > 0:
        info = (f" · 💰 top-up +{format_currency(funded)}" if topup
                else f" · 🔁 +{format_currency(funded)} dari {_env_label(source_env)}")

    savepoint = None
    if funded > 0:
        # Savepoint, bukan db.rollback(): rollback penuh meng-expire semua objek
        # sesi (user, amplop) dan aksesnya sesudah itu gagal di async
        # (MissingGreenlet) — padahal item antrean berikutnya masih memakainya.
        savepoint = await db.begin_nested()
        if topup:
            record_topup(db, hid, user.id, target_env, funded)
        else:
            record_transfer(db, hid, user.id, source_env, target_env, funded)
        await db.flush()
        check = None  # dana berubah — cek ulang
    if check is None:
        check = await check_expense(target_env, user, amount, db)

    if check.allowed:
        db.add(Transaction(
            envelope_id=target_env.id, user_id=user.id, amount=amount,
            description=desc, source=TransactionSource.telegram,
            transaction_date=date.today(),
        ))
        await db.commit()
        streak = _streak_text(await after_expense_recorded(db, user, target_env.id, desc)).strip()
        if streak:
            data["streak"] = streak
        data.setdefault("auto_lines", []).append(
            f"{_env_label(target_env)}: {_item_label(item)}{info}")
        if "total" in data:
            data["total"] += int(amount)
    elif check.check_type == "cooling":
        # create_pending_transaction meng-commit dana tambahan sekalian.
        await create_pending_transaction(
            target_env.id, user.id, amount, desc,
            TransactionSource.telegram, cooling_hours=24, db=db)
        data.setdefault("notes", []).append(
            f"⏳ {_item_label(item)}: masuk cooling period 24 jam (/pending){info}")
    else:
        # Tanpa dana tambahan tidak ada perubahan yang perlu dibatalkan.
        if savepoint is not None:
            await savepoint.rollback()
        tail = ""
        if funded > 0:
            tail = " Pemasukan tidak dicatat." if topup else " Dana tidak digeser."
        if check.check_type == "daily_limit":
            tail += " Kirim sebagai pesan terpisah untuk opsi naikkan limit hari ini."
        data.setdefault("notes", []).append(
            f"⚠️ {_item_label(item)}: {_esc(check.reason)} Tidak dicatat.{tail}")


# ── Langkah antrean ──────────────────────────────────────────────────────────

async def render_step(key, data, user, hid, db, flash=None):
    """Maju ke item antrean berikutnya yang butuh keputusan user.

    Item yang tidak butuh keputusan (dana sudah cukup, amplop dikunci, dsb.)
    diselesaikan di sini. Mengembalikan (teks, markup|None, selesai).
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
            )] for e in _spendable_rows(env_data)]
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

        check = await check_expense(target_env, user, Decimal(item["amount"]), db)
        if check.allowed or check.check_type not in FUNDS_BLOCKS:
            # Dana cukup (mis. sudah diisi), atau terblokir hal lain (kunci, cooling, limit…).
            await _record_item(db, user, hid, data, item, target_env, check=check)
            data["pos"] += 1
            continue

        shortfall = compute_shortfall(target["remaining"], Decimal(item["amount"]))
        sources = pick_sources(env_data, target_env.id, shortfall)
        data["stage"] = "shift"
        data["sources"] = [str(s["envelope"].id) for s in sources]
        keyboard = [[InlineKeyboardButton(
            f"🔁 {s['envelope'].emoji or '📁'} {s['envelope'].name} (sisa {format_currency(s['remaining'])})",
            callback_data=f"bshift_{key}_{pos}_{i}",
        )] for i, s in enumerate(sources)]
        keyboard.append([InlineKeyboardButton(
            f"💰 Top-up pemasukan {format_currency(shortfall)}", callback_data=f"bshift_{key}_{pos}_t")])
        keyboard.append([InlineKeyboardButton("⏭ Lewati item ini", callback_data=f"bshift_{key}_{pos}_skip")])
        ask = (f"Geser <b>{format_currency(shortfall)}</b> dari amplop lain, atau catat pemasukan "
               f"sebesar kekurangannya, supaya item ini tetap tercatat?" if sources else
               f"Tidak ada amplop lain yang sisanya cukup. Catat pemasukan "
               f"<b>{format_currency(shortfall)}</b> ke {_env_label(target_env)} supaya item ini tetap tercatat?")
        text = (
            f"{_progress_header(data, flash)}"
            f"💸 <b>Dana amplop kurang</b>{progress}\n\n"
            f"{_item_label(item)}\n"
            f"{_env_label(target_env)} · sisa {format_currency(max(target['remaining'], Decimal('0')))}\n"
            f"Kurang <b>{format_currency(shortfall)}</b>\n\n{ask}"
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
    if choice not in {str(e["envelope"].id) for e in _spendable_rows(env_data)}:
        return "⚠️ Amplop itu tidak bisa dipilih. Pilih amplop lain."
    # render_step yang memutuskan: catat, tawarkan isi dana, atau tahan.
    item["env_id"] = choice
    return None


async def _shift_step(db, user, hid, data, choice):
    item = data["queue"][data["pos"]]
    if choice == "skip":
        data.setdefault("notes", []).append(f"⏭ {_item_label(item)}: dilewati, dana tidak diubah.")
        data["pos"] += 1
        return None
    topup = choice == "t"
    source_id = None
    if not topup:
        try:
            source_id = data.get("sources", [])[int(choice)]
        except (ValueError, IndexError):
            return None

    payday_day = getattr(user, "payday_day", 1) or 1
    env_data = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
    by_id = {str(e["envelope"].id): e for e in env_data}
    target = by_id.get(item["env_id"])
    source = by_id.get(source_id) if source_id else None
    if not target:
        return None  # render_step mencatatnya sebagai tidak tersedia
    if not topup and not source:
        return "⚠️ Amplop sumber tidak tersedia. Pilih cara lain."

    funded = compute_shortfall(target["remaining"], Decimal(item["amount"]))
    if funded > 0 and not topup:
        error = transfer_error(source, target, funded)
        if error:
            return f"⚠️ {_esc(error)}. Pilih cara lain."
    await _record_item(db, user, hid, data, item, target["envelope"],
                       source_env=source["envelope"] if source else None,
                       funded=funded, topup=topup)
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
    """bshift_{key}_{pos}_{source_idx|t|skip} — geser dana / top-up untuk item antrean."""
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
            check = await check_expense(env, user, Decimal(amount), db)
            if not check.allowed and check.check_type in FUNDS_BLOCKS:
                data["queue"].append(item)  # → tawaran isi dana
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
