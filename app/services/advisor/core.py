import logging
from datetime import date
from decimal import Decimal

from app.services.advisor.formatting import (
    _to_decimal, _fmt_rp, _fmt_months, _median_decimal, _card, _severity_rank,
)
from app.services.advisor.context import (
    _payday, _get_household_id, _load_visible_envelopes, _period_index,
    _sum_by_period, _count_by_period, _monthly_reserve,
    load_advisor_context, envelope_lifetime_balance,
)
from app.services.advisor.sinking import (
    normalize_description, detect_interval, _token_overlap, _frequency_monthly_reserve,
    _next_expected_date, _amount_stability, select_visible_samples, _sinking_group_id,
    build_sinking_fund_advice,
)
from app.services.advisor.allocation import (
    _is_saving_sink, allocate_income_to_targets, build_allocation_distribution,
    _is_essential_envelope, _allocation_priority, build_allocation_recommendation,
)
from app.services.advisor.rules import build_advisor_insights, compute_insight_cards  # noqa: F401

logger = logging.getLogger("jatahku.advisor")

# Don't project depletion/overspend before this many days into the period —
# early-period spend rates are too volatile and produce false alarms.
_MIN_PROJECTION_DAYS = 3

