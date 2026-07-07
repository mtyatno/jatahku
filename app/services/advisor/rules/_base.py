"""Shared context object for advisor rules.

`AdvisorContext` is a thin, read-only bundle of the pre-loaded data that
`compute_insight_cards` needs. It is introduced in Plan B1 Task 7 as
groundwork for splitting `compute_insight_cards` into per-rule modules
(Task 8); no rule logic lives here."""
from dataclasses import dataclass, field

# Don't project depletion/overspend before this many days into the period —
# early-period spend rates are too volatile and produce false alarms.
_MIN_PROJECTION_DAYS = 3


@dataclass
class AdvisorContext:
    envelopes: list
    stats: dict
    period_info: dict
    goals_by_env: dict
    balances_by_env: dict
    txns_by_env: dict = field(default_factory=dict)
    recurring_by_env: dict = field(default_factory=dict)

    @property
    def days_used(self) -> int:
        return max(self.period_info["days_used"], 1)

    @property
    def days_total(self) -> int:
        return max(self.period_info["days_total"], 1)

    @property
    def days_remaining(self) -> int:
        return max(self.period_info["days_remaining"], 0)
