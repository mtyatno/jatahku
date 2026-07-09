"""Advisor package — dipecah dari advisor.py (Plan B1). Perilaku identik;
__init__ mempertahankan API publik + surface yang dipakai test.
Setiap nama diimpor langsung dari modul fokusnya (formatting/context/
allocation/sinking/rules) — tidak ada lagi core.py perantara."""
from app.services.advisor.formatting import _fmt_rp  # noqa: F401
from app.services.advisor.context import (  # noqa: F401
    load_advisor_context,
    envelope_lifetime_balance,
    _period_index,
    _sum_by_period,
    _count_by_period,
)
from app.services.advisor.allocation import (  # noqa: F401
    allocate_income_to_targets,
    build_allocation_distribution,
    build_allocation_recommendation,
    build_envelope_distribution,
)
from app.services.advisor.sinking import (  # noqa: F401
    build_sinking_fund_advice,
    detect_interval,
    normalize_description,
    select_visible_samples,
    _sinking_group_id,
)
from app.services.advisor.rules import build_advisor_insights  # noqa: F401
