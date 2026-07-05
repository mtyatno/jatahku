from decimal import Decimal


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


def _card(card_id: str, card_type: str, severity: str, title: str, body: str, route: str, evidence: list[str]) -> dict:
    return {
        "id": card_id,
        "type": card_type,
        "severity": severity,
        "title": title,
        "body": body,
        "primary_action": {"label": "Lihat detail", "route": route},
        "evidence": evidence[:3],
    }


def _severity_rank(severity: str) -> int:
    return {"danger": 0, "warning": 1, "info": 2, "positive": 3}.get(severity, 4)


def _money(value: Decimal) -> int:
    return int(_to_decimal(value).quantize(Decimal("1")))


def _fmt_rp(value) -> str:
    """Indonesian Rupiah grouping with dots: 1520000 -> '1.520.000'."""
    return f"{_money(value):,}".replace(",", ".")


def _fmt_months(months: int) -> str:
    """Format months as 'X tahun Y bulan' or 'X bulan'."""
    years = months // 12
    remaining = months % 12
    if years > 0 and remaining > 0:
        return f"{years} tahun {remaining} bulan"
    elif years > 0:
        return f"{years} tahun"
    else:
        return f"{months} bulan"


def _median_decimal(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2
