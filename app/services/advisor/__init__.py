"""Advisor package — dipecah dari advisor.py (Plan B1). Perilaku identik;
__init__ mempertahankan API publik + surface yang dipakai test.
Selama refactor, implementasi masih di core.py dan dikupas bertahap."""
from app.services.advisor.rules import build_advisor_insights  # noqa: F401
from app.services.advisor.core import (  # noqa: F401
    build_allocation_recommendation,
    build_sinking_fund_advice,
    build_allocation_distribution,
    envelope_lifetime_balance,
    load_advisor_context,
    allocate_income_to_targets,
    detect_interval,
    normalize_description,
    select_visible_samples,
    _sinking_group_id,
    _fmt_rp,
    _period_index,
    _sum_by_period,
    _count_by_period,
)
