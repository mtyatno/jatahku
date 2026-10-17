import logging
from decimal import ROUND_FLOOR, Decimal
from itertools import groupby

from app.services.advisor.formatting import _to_decimal, _money, _fmt_rp, _median_decimal
from app.services.advisor.context import load_advisor_context
from app.services.advisor.sinking import normalize_description, _ESSENTIAL_KEYWORDS
from app.services.advisor.confidence import assess_confidence
from app.services.advisor.render import alasan_alokasi


logger = logging.getLogger("jatahku.advisor.allocation")

_STEP = Decimal("100")  # pecahan rupiah terkecil yang dipakai


def _is_saving_sink(item) -> bool:
    """Pure-savings envelope that receives leftover income — purpose 'saving'
    (or the legacy 'Tabungan' name as fallback)."""
    if str(item.get("purpose") or "") == "saving":
        return True
    return str(item.get("name", "")).lower() == "tabungan"


def allocate_income_to_targets(income_amount: Decimal, envelopes: list[dict]) -> dict:
    remaining_income = _to_decimal(income_amount)
    items = []
    warnings = []

    for envelope in envelopes:
        items.append({
            **envelope,
            "minimum": _to_decimal(envelope.get("minimum")),
            "target": _to_decimal(envelope.get("target")),
            "recommended_amount": Decimal("0"),
        })

    allocatable_items = [item for item in items if not item.get("is_locked")]
    sorted_items = sorted(allocatable_items, key=lambda item: item.get("priority", 50))
    total_minimum = sum((max(item["minimum"], Decimal("0")) for item in sorted_items), Decimal("0"))

    # Minimum per tingkat prioritas. Bila income tidak cukup untuk satu tingkat, income dibagi
    # proporsional ke minimum tingkat itu (dibulatkan ke bawah Rp100, sisa pembulatan ke minimum
    # terbesar) — income kecil/harian terbagi rata, tidak mengisi satu amplop dulu (S14).
    short = False
    for _, group in groupby(sorted_items, key=lambda item: item.get("priority", 50)):
        group = [item for item in group if item["minimum"] > 0]
        need = sum((item["minimum"] for item in group), Decimal("0"))
        if not group or remaining_income <= 0:
            continue
        if need <= remaining_income:
            for item in group:
                item["recommended_amount"] += item["minimum"]
            remaining_income -= need
            continue
        scale = remaining_income / need
        for item in group:
            item["recommended_amount"] += (item["minimum"] * scale / _STEP).to_integral_value(ROUND_FLOOR) * _STEP
        given = sum((item["recommended_amount"] for item in group), Decimal("0"))
        max(group, key=lambda item: item["minimum"])["recommended_amount"] += remaining_income - given
        remaining_income = Decimal("0")
        short = True
        break

    if short or income_amount < total_minimum:
        warnings.append("Income tidak cukup untuk memenuhi semua minimum.")

    target_items = sorted(sorted_items, key=lambda item: (item["minimum"] > 0, item.get("priority", 50)))
    for item in target_items:
        if _is_saving_sink(item) or remaining_income <= 0:
            continue
        target_gap = max(item["target"] - item["recommended_amount"], Decimal("0"))
        if target_gap <= 0:
            continue
        amount = min(target_gap, remaining_income)
        item["recommended_amount"] += amount
        remaining_income -= amount

    sink = next((item for item in items if _is_saving_sink(item)), None)
    if sink and remaining_income > 0:
        sink["recommended_amount"] += remaining_income
        remaining_income = Decimal("0")

    return {
        "items": items,
        "total_recommended": sum((item["recommended_amount"] for item in items), Decimal("0")),
        "unallocated": remaining_income,
        "warnings": warnings,
    }


def build_allocation_distribution(rows, total_income) -> dict:
    """Group per-envelope net allocations into named categories with percentages.

    rows: list of (category_name, net_amount). Categories with equal names are
    summed. Non-positive categories are dropped. Percentages are of total_income.
    """
    total = _to_decimal(total_income)
    merged: dict[str, Decimal] = {}
    for name, amount in rows:
        merged[name] = merged.get(name, Decimal("0")) + _to_decimal(amount)

    positive = {k: v for k, v in merged.items() if v > 0}
    allocated_total = sum(positive.values(), Decimal("0"))

    def pct(v: Decimal) -> int:
        return int(round(float(v) / float(total) * 100)) if total > 0 else 0

    distribution = [
        {"category": name, "amount": float(amount), "pct": pct(amount)}
        for name, amount in sorted(positive.items(), key=lambda kv: kv[1], reverse=True)
    ]
    saving_amount = positive.get("Tabungan", Decimal("0")) + positive.get("Sinking Fund", Decimal("0"))
    return {
        "distribution": distribution,
        "allocated_pct": pct(allocated_total),
        "saving_amount": float(saving_amount),
        "saving_pct": pct(saving_amount),
    }


def build_envelope_distribution(env_rows, total_income) -> list[dict]:
    """Per-envelope net allocations with percentages, for the Alokasi donut toggle.

    env_rows: list of (name, emoji, net_amount). Non-positive nets are dropped,
    result sorted by amount desc. Percentages are of total_income (0 if income <= 0).
    """
    total = _to_decimal(total_income)

    def pct(v: Decimal) -> int:
        return int(round(float(v) / float(total) * 100)) if total > 0 else 0

    positive = [(name, emoji, _to_decimal(net)) for name, emoji, net in env_rows if _to_decimal(net) > 0]
    return [
        {"name": name, "emoji": emoji, "amount": float(net), "pct": pct(net)}
        for name, emoji, net in sorted(positive, key=lambda r: r[2], reverse=True)
    ]


def _is_essential_envelope(name: str) -> bool:
    normalized = normalize_description(name)
    return bool(set(normalized.split()) & _ESSENTIAL_KEYWORDS)


def _allocation_priority(name: str, minimum: Decimal, essential: bool, purpose: str = "expense") -> int:
    if purpose == "saving" or name.lower() == "tabungan":
        return 90
    if minimum > 0:
        return 10
    if essential:
        return 20
    return 40



# ── AI Advisor v2: alasan & penyesuaian dari aturan (02-aturan.md §7 "Alokasi", S14) ──
# Angka rekomendasi tetap dari allocate_income_to_targets; aturan yang menyala hanya
# menggeser minimum/target amplopnya. Kalimat alasan dari render.alasan_alokasi.
ATURAN_ALOKASI = ("AMP-01", "AMP-04", "AMP-05", "AMP-06", "TAG-04", "TAB-02")
BANNER_ALOKASI = ("INC-04", "INC-03")   # di atas form, urutan §7
SISA_KE = "Tabungan"  # amplop penerima sisa income — sama dengan routes/incomes.py


def sesuaikan_dengan_aturan(inputs: list[dict], insights) -> dict[str, list]:
    """Murni. Ubah `minimum`/`target` allocation input sesuai aturan yang menyala:
    - AMP-01 minus → minimum ≥ minus (ditutup dulu);
    - AMP-04 / AMP-05 jatah kekecilan → target ≥ saran;
    - AMP-06 jatah kebesaran → target turun ke saran (tidak di bawah minimum);
    - TAG-04 tagihan tahunan → minimum ≥ sisihan per bulan;
    - TAB-02 target tertinggal → minimum ≥ kurang periode ini, kecuali ditunda (penekanan 7).
    Mengembalikan {envelope_id: [Insight]} untuk alasan per amplop."""
    by_id = {item["id"]: item for item in inputs}
    out: dict[str, list] = {}
    for ins in sorted(insights, key=lambda i: (ATURAN_ALOKASI.index(i.aturan), i.id)):
        eid = ins.amplop_id or ins.data.get("amplop_id")
        item = by_id.get(eid)
        if item is None:
            continue
        d = ins.data
        if ins.aturan == "AMP-01":
            item["minimum"] = max(item["minimum"], _to_decimal(d["minus"]).quantize(Decimal("1")))
        elif ins.aturan in ("AMP-04", "AMP-05"):
            if d.get("saran"):
                item["target"] = max(item["target"], _to_decimal(d["saran"]))
        elif ins.aturan == "AMP-06":
            item["target"] = max(_to_decimal(d["saran"]), item["minimum"])
        elif ins.aturan == "TAG-04":
            item["minimum"] = max(item["minimum"], _to_decimal(d["per_bulan"]).quantize(Decimal("1")))
        elif ins.aturan == "TAB-02" and not d.get("tunda"):
            item["minimum"] = max(item["minimum"], _to_decimal(d["kurang"]).quantize(Decimal("1")))
        item["target"] = max(item["target"], item["minimum"])
        if item["minimum"] > 0 and item.get("purpose") != "saving":
            item["priority"] = min(item.get("priority", 50), 10)  # sama dengan _allocation_priority
        out.setdefault(eid, []).append(ins)
    return out


def sisa_ke(envelopes) -> dict:
    """Amplop yang menerima sisa income saat disimpan (`POST /incomes/`). Frontend tidak
    mencocokkan nama sendiri; envelope_id None = akan dibuat saat simpan."""
    env = next((e for e in envelopes if getattr(e, "name", None) == SISA_KE), None)
    return {"envelope_id": str(env.id) if env else None, "name": SISA_KE}


async def analisa_alokasi(user, db):
    """(Konteks, Seleksi) v2 untuk halaman Alokasi, atau None bila flag mati / gagal
    (rekomendasi lama tetap jalan)."""
    from datetime import datetime
    from app.services.advisor import advisor_cache, dashboard
    from app.services.advisor.snapshot import load_snapshot
    try:
        pengaturan = await dashboard.muat_pengaturan(db)
        if not dashboard.flag_aktif(pengaturan.get(dashboard.FLAG_KEY), user.id):
            return None
        now_local = datetime.now(dashboard._tz(user))
        snap = await load_snapshot(user, db, today=now_local.date())
        km, ks, ka = dashboard.bangun_konstanta(pengaturan.get(dashboard.KONSTANTA_KEY))
        dismiss = await advisor_cache.muat_dismiss(snap.viewer_id)
        return dashboard.analisa(snap, now_local=now_local, dismiss=dismiss, km=km, ks=ks, ka=ka)
    except Exception:
        logger.exception("analisa alokasi v2 gagal user=%s", getattr(user, "id", None))
        return None


def _terlihat(sel, kode) -> list:
    hidden = set(sel.disembunyikan)
    return [i for i in sel.semua if i.aturan in kode and i.id not in hidden]


def banner_alokasi(ctx, sel) -> list[dict]:
    """INC-04 / INC-03 yang menyala dan tidak disembunyikan, sudah dirender."""
    from app.services.advisor.render import render_insight
    items = sorted(_terlihat(sel, BANNER_ALOKASI), key=lambda i: BANNER_ALOKASI.index(i.aturan))
    return [render_insight(i, ctx) for i in items]


async def build_alokasi_page(user, db) -> dict:
    """`GET /advisor/page/alokasi`: banner di atas form + amplop penerima sisa."""
    hasil = await analisa_alokasi(user, db)
    if hasil is None:
        context = await load_advisor_context(user, db)
        return {"enabled": False, "banner": [], "sisa_ke": sisa_ke(context.get("envelopes", []))}
    ctx, sel = hasil
    return {"enabled": True, "banner": banner_alokasi(ctx, sel), "sisa_ke": sisa_ke(ctx.snap.envelopes)}


async def build_allocation_recommendation(user, income_amount: Decimal, db) -> dict:
    context = await load_advisor_context(user, db)
    envelopes = context.get("envelopes", [])
    stats = context.get("stats", {})

    if not envelopes:
        return {
            "income_amount": _money(income_amount),
            "total_recommended": 0,
            "unallocated": _money(income_amount),
            "confidence": "low",
            "confidence_reasons": ["Belum ada amplop aktif untuk direkomendasikan."],
            "method": "no_envelopes",
            "items": [],
            "warnings": ["Belum ada amplop aktif untuk direkomendasikan."],
            "sisa_ke": sisa_ke([]),
            "banner": [],
        }

    allocation_inputs = []
    item_meta = {}

    for envelope in envelopes:
        envelope_stats = stats.get(str(envelope.id), [])
        current_stats = envelope_stats[-1] if envelope_stats else {}
        historical_stats = envelope_stats[:-1]
        historical_spends = [
            _to_decimal(row["spent"])
            for row in historical_stats
            if _to_decimal(row.get("spent")) > 0 or _to_decimal(row.get("allocated")) > 0
        ]
        historical_average = _median_decimal(historical_spends)
        recurring_reserve = _to_decimal(current_stats.get("reserved"))
        current_rollover = _to_decimal(current_stats.get("rollover"))
        negative_repayment = abs(current_rollover) if current_rollover < 0 else Decimal("0")
        budget_target = _to_decimal(getattr(envelope, "budget_amount", 0))
        essential = _is_essential_envelope(envelope.name)

        minimum = max(recurring_reserve, negative_repayment)
        if essential and minimum == 0 and historical_average > 0:
            minimum = historical_average * Decimal("0.6")

        target = max(budget_target, historical_average, minimum)
        env_purpose = str(getattr(envelope, "purpose", "expense") or "expense")
        priority = _allocation_priority(envelope.name, minimum, essential, env_purpose)
        reasons = []
        if recurring_reserve > 0:
            reasons.append(f"Reserve langganan sekitar Rp{_fmt_rp(recurring_reserve)}/periode")
        if negative_repayment > 0:
            reasons.append(f"Perlu menutup rollover negatif Rp{_fmt_rp(negative_repayment)}")
        if historical_average > 0:
            reasons.append(f"Median historis Rp{_fmt_rp(historical_average)}")
        if not reasons and budget_target > 0:
            reasons.append(f"Mengikuti target amplop Rp{_fmt_rp(budget_target)}")

        if recurring_reserve > target * Decimal("0.7") and target > 0:
            risk_level = "reserve_pressure"
        elif historical_average > budget_target and budget_target > 0:
            risk_level = "watch"
        else:
            risk_level = "normal"

        allocation_input = {
            "id": str(envelope.id),
            "name": envelope.name,
            "emoji": envelope.emoji,
            "minimum": minimum.quantize(Decimal("1")),
            "target": target.quantize(Decimal("1")),
            "priority": priority,
            "purpose": env_purpose,
            "is_locked": bool(getattr(envelope, "is_locked", False)),
        }
        allocation_inputs.append(allocation_input)
        item_meta[str(envelope.id)] = {
            "envelope": envelope,
            "historical_average": historical_average,
            "recurring_reserve": recurring_reserve,
            "current_rollover": current_rollover,
            "risk_level": risk_level,
            "reasons": reasons[:3],
            "keyakinan": assess_confidence(historical_spends)["level"],
        }

    hasil = await analisa_alokasi(user, db)
    alasan_v2: dict[str, list] = {}
    if hasil is not None:
        ctx, sel = hasil
        alasan_v2 = sesuaikan_dengan_aturan(allocation_inputs, _terlihat(sel, ATURAN_ALOKASI))

    allocation = allocate_income_to_targets(income_amount, allocation_inputs)
    response_items = []

    for item in allocation["items"]:
        meta = item_meta[item["id"]]
        envelope = meta["envelope"]
        response_items.append({
            "envelope_id": item["id"],
            "name": envelope.name,
            "emoji": envelope.emoji,
            "purpose": str(getattr(envelope, "purpose", "expense") or "expense"),
            "recommended_amount": _money(item["recommended_amount"]),
            "minimum_amount": _money(item["minimum"]),
            "target_amount": _money(item["target"]),
            "historical_average": _money(meta["historical_average"]),
            "recurring_reserve": _money(meta["recurring_reserve"]),
            "current_rollover": _money(meta["current_rollover"]),
            "risk_level": meta["risk_level"],
            "reasons": meta["reasons"],
            "alasan": [{"aturan": ins.aturan, "id": ins.id, "teks": alasan_alokasi(ins, ctx)}
                       for ins in alasan_v2.get(item["id"], [])],
            "keyakinan": meta["keyakinan"],
        })

    # Aggregate spend per historical period (all-but-last per envelope), aligned
    # by period index; each envelope's stats list is period-aligned oldest-first.
    period_totals: dict[int, Decimal] = {}
    for envelope_stats in stats.values():
        for idx, row in enumerate(envelope_stats[:-1]):
            period_totals[idx] = period_totals.get(idx, Decimal("0")) + _to_decimal(row.get("spent"))
    confidence_model = assess_confidence(list(period_totals.values()))
    confidence = confidence_model["level"]

    return {
        "income_amount": _money(income_amount),
        "total_recommended": _money(allocation["total_recommended"]),
        "unallocated": _money(allocation["unallocated"]),
        "confidence": confidence,
        "confidence_reasons": confidence_model["reasons"],
        "method": "obligations_then_historical_median",
        "items": response_items,
        "warnings": allocation["warnings"],
        "sisa_ke": sisa_ke(envelopes),
        "banner": banner_alokasi(ctx, sel) if hasil is not None else [],
    }
