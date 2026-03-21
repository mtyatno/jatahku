import io
import csv
from decimal import Decimal
from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Transaction, Envelope, HouseholdMember, Allocation

router = APIRouter()


async def _get_export_data(user: User, db: AsyncSession, year: int, month: int, envelope_id: str = None):
    """Get transactions + envelope summaries for export."""
    hid_result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = hid_result.scalar_one_or_none()
    if not hid:
        return [], []

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

    # Get transactions
    query = (
        select(Transaction, User.name.label("user_name"))
        .join(User, Transaction.user_id == User.id)
        .join(Envelope, Transaction.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            Transaction.is_deleted == False,
            func.extract("year", Transaction.transaction_date) == year,
            func.extract("month", Transaction.transaction_date) == month,
        )
    )
    if envelope_id:
        query = query.where(Transaction.envelope_id == UUID(envelope_id))

    query = query.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
    result = await db.execute(query)
    transactions = result.all()

    # Envelope summaries
    summaries = []
    for env in envelopes:
        if envelope_id and str(env.id) != envelope_id:
            continue
        spent_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.envelope_id == env.id,
                Transaction.is_deleted == False,
                func.extract("year", Transaction.transaction_date) == year,
                func.extract("month", Transaction.transaction_date) == month,
            )
        )
        spent = Decimal(str(spent_result.scalar()))
        summaries.append({
            "name": env.name,
            "emoji": env.emoji,
            "budget": env.budget_amount,
            "spent": spent,
            "remaining": env.budget_amount - spent,
        })

    return transactions, summaries, env_map


@router.get("/csv")
async def export_csv(
    year: int = Query(None),
    month: int = Query(None),
    envelope_id: str = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = date.today()
    y = year or now.year
    m = month or now.month

    transactions, summaries, env_map = await _get_export_data(user, db, y, m, envelope_id)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(["Jatahku — Laporan Keuangan"])
    month_name = date(y, m, 1).strftime("%B %Y")
    writer.writerow([f"Periode: {month_name}"])
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
            txn.description,
            int(txn.amount),
            txn.source.value,
            user_name,
        ])

    output.seek(0)
    filename = f"jatahku_{y}-{m:02d}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/pdf")
async def export_pdf(
    year: int = Query(None),
    month: int = Query(None),
    envelope_id: str = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = date.today()
    y = year or now.year
    m = month or now.month

    transactions, summaries, env_map = await _get_export_data(user, db, y, m, envelope_id)
    month_name = date(y, m, 1).strftime("%B %Y")

    total_budget = sum(s['budget'] for s in summaries)
    total_spent = sum(s['spent'] for s in summaries)

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
<p class="subtitle">Laporan Keuangan — {month_name}</p>

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
        html += f"""<tr><td>{txn.transaction_date.strftime("%d %b")}</td><td>{env.name if env else '-'}</td><td>{txn.description}</td><td class="amount">Rp{int(txn.amount):,}</td><td>{src}</td></tr>"""

    html += f"""</table>
<p class="footer">Digenerate oleh Jatahku — Setiap rupiah ada jatahnya.<br>{date.today().strftime("%d %B %Y %H:%M")}</p>
</body></html>"""

    # Return as HTML (can be printed to PDF from browser)
    filename = f"jatahku_{y}-{m:02d}.html"
    return StreamingResponse(
        iter([html]),
        media_type="text/html",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )
