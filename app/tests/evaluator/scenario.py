"""Synthetic scenario harness for the advisor rules pipeline (Plan B2 §9).

Builds the exact inputs compute_insight_cards reads — no DB, no event loop —
and runs the full rule registry. Scenarios assert cards that MUST appear and
cards that MUST NOT (anti-false-alarm + privacy regression guards).
"""
from types import SimpleNamespace

from app.services.advisor.rules import compute_insight_cards
from app.tests.advisor_fixtures import (
    make_envelope, make_period_row, make_period_info, make_goal, build_stats,
)


def make_txn(amount, description="beli", transaction_date=None):
    from datetime import date
    from decimal import Decimal
    return SimpleNamespace(
        amount=Decimal(str(amount)),
        description=description,
        transaction_date=transaction_date or date(2026, 1, 5),
    )


def run_scenario(envelopes, stats, period_info=None, goals=None, balances=None,
                 txns_by_env=None, recurring_by_env=None):
    return compute_insight_cards(
        envelopes, stats, period_info or make_period_info(),
        goals or {}, balances or {},
        txns_by_env or {}, recurring_by_env or {},
    )


def card_types(result) -> set:
    return {card["type"] for card in result["cards"]}


def evidence_text(result) -> str:
    parts = []
    for card in result["cards"]:
        parts.append(card.get("title", ""))
        parts.append(card.get("body", ""))
        parts.extend(card.get("evidence", []))
    return " ".join(parts)
