import io
import csv
from decimal import Decimal
from datetime import date, timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.period import get_budget_period, _safe_date
from app.models.models import (
    User,
    Transaction,
    Envelope,
    HouseholdMember,
    Allocation,
    Income,
    MonthlySnapshot,
)
from app.services.visibility import masked_description

router = APIRouter()


def _resolve_period(
    user: User,
    period_start: date | None = None,
    period_end: date | None = None,
    year: int | None = None,
    month: int | None = None,
) -> tuple[date, date]:
    """Resolve period start and end dates from query params or user payday settings."""
    p_start = period_start if isinstance(period_start, date) else None
    p_end = period_end if isinstance(period_end, date) else None
    y = year if isinstance(year, int) else None
    m = month if isinstance(month, int) else None

    if p_start and p_end:
        return p_start, p_end
    payday_day = getattr(user, "payday_day", 1) or 1
    if y and m:
        target_date = _safe_date(y, m, payday_day)
        return get_budget_period(payday_day, target_date)
    return get_budget_period(payday_day)


async def _get_export_data(
    user: User,
    db: AsyncSession,
    period_start: date,
    period_end: date,
    envelope_id: str | None = None,
):
    """Get transactions + envelope summaries for export."""
    hid_result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = hid_result.scalar_one_or_none()
    if not hid:
        return [], [], {}

    # Get envelopes
    env_result = await db.execute(
        select(Envelope).where(
            Envelope.household_id == hid,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        ).order_by(Envelope.created_at)
    )
    envelopes = env_result.scalars().all()
    env_map = {str(e.id): e for e in envelopes}

    target_env_id = str(envelope_id) if isinstance(envelope_id, (str, UUID)) else None

    # Get transactions
    query = (
        select(Transaction, User.name.label("user_name"))
        .join(User, Transaction.user_id == User.id)
        .join(Envelope, Transaction.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            Transaction.is_deleted == False,
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date <= period_end,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )
    if target_env_id:
        query = query.where(Transaction.envelope_id == UUID(target_env_id))

    query = query.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
    result = await db.execute(query)
    transactions = result.all()

    payday_day = getattr(user, "payday_day", 1) or 1
    prev_start, _ = get_budget_period(payday_day, period_start - timedelta(days=1))

    # Envelope summaries
    summaries = []
    for env in envelopes:
        if target_env_id and str(env.id) != target_env_id:
            continue

        # Spent per envelope within [period_start, period_end]
        spent_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.envelope_id == env.id,
                Transaction.is_deleted == False,
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
            )
        )
        spent = Decimal(str(spent_result.scalar()))

        # Allocated per envelope within [period_start, period_end]
        alloc_result = await db.execute(
            select(func.coalesce(func.sum(Allocation.amount), 0))
            .join(Income, Allocation.income_id == Income.id)
            .where(
                Allocation.envelope_id == env.id,
                Income.income_date >= period_start,
                Income.income_date <= period_end,
            )
        )
        allocated = Decimal(str(alloc_result.scalar()))

        # Rollover from MonthlySnapshot for prev_start
        rollover = Decimal("0")
        if env.is_rollover:
            snap_result = await db.execute(
                select(MonthlySnapshot.rollover_amount).where(
                    MonthlySnapshot.envelope_id == env.id,
                    MonthlySnapshot.year == prev_start.year,
                    MonthlySnapshot.month == prev_start.month,
                )
            )
            snap_rollover = snap_result.scalar_one_or_none()
            if snap_rollover is not None:
                rollover = snap_rollover

        effective_budget = (allocated + rollover) if (allocated + rollover > 0) else env.budget_amount
        remaining = (allocated + rollover) - spent

        summaries.append({
            "name": env.name,
            "emoji": env.emoji,
            "budget": effective_budget,
            "spent": spent,
            "remaining": remaining,
            "allocated": allocated,
            "rollover": rollover,
        })

    return transactions, summaries, env_map


@router.get("/csv")
async def export_csv(
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
    year: int | None = Query(None),
    month: int | None = Query(None),
    envelope_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p_start, p_end = _resolve_period(user, period_start, period_end, year, month)
    env_id = str(envelope_id) if isinstance(envelope_id, (str, UUID)) else None

    transactions, summaries, env_map = await _get_export_data(user, db, p_start, p_end, env_id)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(["Jatahku — Laporan Keuangan"])
    writer.writerow([f"Periode: {p_start.strftime('%d %b %Y')} – {p_end.strftime('%d %b %Y')}"])
    writer.writerow([])

    # Summary
    writer.writerow(["RINGKASAN AMPLOP"])
    writer.writerow(["Amplop", "Budget", "Terpakai", "Sisa", "Persentase"])
    total_budget = Decimal("0")
    total_spent = Decimal("0")
    for s in summaries:
        pct = f"{int(s['spent'] / s['budget'] * 100)}%" if s['budget'] > 0 else "0%"
        writer.writerow([s['name'], int(s['budget']), int(s['spent']), int(s['remaining']), pct])
        total_budget += s['budget']
        total_spent += s['spent']
    writer.writerow(["TOTAL", int(total_budget), int(total_spent), int(total_budget - total_spent),
                      f"{int(total_spent / total_budget * 100)}%" if total_budget > 0 else "0%"])
    writer.writerow([])

    # Transactions
    writer.writerow(["DETAIL TRANSAKSI"])
    writer.writerow(["Tanggal", "Amplop", "Keterangan", "Jumlah", "Sumber", "User"])
    for txn, user_name in transactions:
        env = env_map.get(str(txn.envelope_id))
        writer.writerow([
            txn.transaction_date.strftime("%Y-%m-%d"),
            env.name if env else "-",
            masked_description(user.id, txn),
            int(txn.amount),
            txn.source.value,
            user_name,
        ])

    output.seek(0)
    filename = f"jatahku_{p_start.strftime('%Y-%m-%d')}_{p_end.strftime('%Y-%m-%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/pdf")
async def export_pdf(
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
    year: int | None = Query(None),
    month: int | None = Query(None),
    envelope_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p_start, p_end = _resolve_period(user, period_start, period_end, year, month)
    env_id = str(envelope_id) if isinstance(envelope_id, (str, UUID)) else None

    transactions, summaries, env_map = await _get_export_data(user, db, p_start, p_end, env_id)

    total_budget = sum((s['budget'] for s in summaries), Decimal("0"))
    total_spent = sum((s['spent'] for s in summaries), Decimal("0"))

    # Generate HTML → PDF using simple HTML
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
body {{ font-family: 'Helvetica', sans-serif; color: #2C2C2A; padding: 40px; font-size: 12px; }}
h1 {{ color: #0F6E56; font-size: 24px; margin-bottom: 4px; }}
h2 {{ color: #0F6E56; font-size: 16px; margin-top: 24px; border-bottom: 1px solid #e8e8e4; padding-bottom: 6px; }}
.subtitle {{ color: #888; font-size: 13px; margin-bottom: 20px; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
th {{ background: #E1F5EE; color: #085041; text-align: left; padding: 8px 10px; font-size: 11px; text-transform: uppercase; }}
td {{ padding: 7px 10px; border-bottom: 1px solid #f0f0ea; }}
.total td {{ font-weight: bold; border-top: 2px solid #0F6E56; }}
.amount {{ font-family: monospace; text-align: right; }}
.right {{ text-align: right; }}
.footer {{ margin-top: 30px; text-align: center; color: #aaa; font-size: 10px; }}
</style></head><body>
<h1>Jatahku</h1>
<p class="subtitle">Laporan Keuangan — Periode: {p_start.strftime('%d %b %Y')} – {p_end.strftime('%d %b %Y')}</p>

<h2>Ringkasan Amplop</h2>
<table>
<tr><th>Amplop</th><th class="right">Budget</th><th class="right">Terpakai</th><th class="right">Sisa</th><th class="right">%</th></tr>"""

    for s in summaries:
        pct = int(s['spent'] / s['budget'] * 100) if s['budget'] > 0 else 0
        html += f"""<tr><td>{s['emoji']} {s['name']}</td><td class="amount">Rp{int(s['budget']):,}</td><td class="amount">Rp{int(s['spent']):,}</td><td class="amount">Rp{int(s['remaining']):,}</td><td class="right">{pct}%</td></tr>"""

    total_pct = int(total_spent / total_budget * 100) if total_budget > 0 else 0
    html += f"""<tr class="total"><td>TOTAL</td><td class="amount">Rp{int(total_budget):,}</td><td class="amount">Rp{int(total_spent):,}</td><td class="amount">Rp{int(total_budget - total_spent):,}</td><td class="right">{total_pct}%</td></tr></table>

<h2>Detail Transaksi ({len(transactions)})</h2>
<table>
<tr><th>Tanggal</th><th>Amplop</th><th>Keterangan</th><th class="right">Jumlah</th><th>Sumber</th></tr>"""

    for txn, user_name in transactions:
        env = env_map.get(str(txn.envelope_id))
        src = "📱 TG" if txn.source.value == "telegram" else "🌐 Web"
        html += f"""<tr><td>{txn.transaction_date.strftime("%d %b")}</td><td>{env.name if env else '-'}</td><td>{masked_description(user.id, txn)}</td><td class="amount">Rp{int(txn.amount):,}</td><td>{src}</td></tr>"""

    html += f"""</table>
<p class="footer">Digenerate oleh Jatahku — Setiap rupiah ada jatahnya.<br>{date.today().strftime("%d %B %Y")}</p>
</body></html>"""

    # Generate real PDF using weasyprint
    filename = f"jatahku_{p_start.strftime('%Y-%m-%d')}_{p_end.strftime('%Y-%m-%d')}.pdf"
    try:
        from weasyprint import HTML as WeasyHTML
        pdf_bytes = WeasyHTML(string=html).write_pdf()
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except ImportError:
        # Fallback to HTML if weasyprint not available
        html_filename = f"jatahku_{p_start.strftime('%Y-%m-%d')}_{p_end.strftime('%Y-%m-%d')}.html"
        return StreamingResponse(
            iter([html]),
            media_type="text/html",
            headers={"Content-Disposition": f"inline; filename={html_filename}"},
        )
