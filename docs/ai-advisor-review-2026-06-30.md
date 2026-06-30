# AI Advisor — Review & Findings (2026-06-30)

Study of the "AI Advisor" brain + workflow. **Analysis only — no fixes applied.**
The actual rework is planned as a **dedicated session focused on household-share
privacy**. This doc records logic anomalies, privacy concerns, and enhancement
opportunities so that session can start with full context.

## What it is / how it works

There is **no LLM** — the advisor is a deterministic rules engine.

- **Entry:** `GET /advisor/insights` → `build_advisor_insights(user, db)`
  (`app/services/advisor.py`). Also `POST /advisor/allocation-recommendation`
  → `build_allocation_recommendation`, and `GET /advisor/sinking-funds` →
  `build_sinking_fund_advice`.
- **Context loading:** `load_advisor_context` resolves the user's household,
  loads **visible envelopes** = shared (`owner_id IS NULL`) **+** the caller's
  own personal envelopes (`owner_id == user.id`), then for each envelope × each
  of the last 6 periods computes allocated / spent / txn_count / rollover, plus a
  monthly `reserved` from active recurring txns.
- **Cards built** (sorted by severity danger→warning→info→positive, top 3 →
  `dashboard_cards`):
  - `env_depletion` (expense only): linear projection `(spent/days_used)*days_total`
    vs `allocated+rollover`.
  - `subscription_pressure`: `reserved>0 and free < reserved*0.25`.
  - `allocation_drift` (expense): `median(historical spent) > budget*1.15`.
  - `goal_progress` (consolidated): saving = balance vs target + months-to-goal
    estimate from median historical deposits; sinking_fund = monthly-needed vs
    `target_date`.
  - `budget_overspend` (global): `projected_total > total_allocated`.
- **Allocation recommendation:** obligations (reserve / negative-rollover repay)
  first by priority, then fill toward targets, leftover → an envelope **named**
  "tabungan".
- **Sinking-fund advice:** groups all transactions on visible envelopes by
  normalized description over 12 periods, detects interval/amount stability,
  recommends create/adjust recurring.

## Privacy — household sharing (PRIMARY focus for the dedicated session)

- **Good:** `_load_visible_envelopes` correctly excludes *other* members'
  personal envelopes (`owner_id == user.id OR owner_id IS NULL`). The advisor
  never surfaces another member's personal envelope.
- **Concern 1 — raw transaction descriptions of other members leak via shared
  envelopes.** `_spent_for_period` / `_transaction_count_for_period` and
  especially `build_sinking_fund_advice` aggregate **all** transactions on a
  shared envelope regardless of `Transaction.user_id`. The sinking-fund evidence
  prints raw samples: `"3 transaksi cocok: {samples}"` — these can be another
  member's transaction text. Decide: are shared-envelope transactions (and their
  descriptions) meant to be fully visible to every member, or only aggregates?
- **Concern 2 — no concept of a private transaction inside a shared envelope.**
  Today "shared" = fully shared. If the product wants per-member privacy, the
  advisor (and dashboard/transactions) need a visibility rule, and the advisor
  must aggregate without exposing per-member detail.
- **Concern 3 — allocations on shared envelopes mix members' incomes.**
  `_allocated_for_period` joins `Income` with no user filter; another member's
  contributions count toward the shared envelope (expected for shared, but worth
  stating explicitly in the privacy model).
- **Decision needed:** define the visibility contract — what each member may see
  on shared vs personal envelopes (aggregates vs raw descriptions vs amounts),
  then scope every advisor query/evidence string to it.

## Logic anomalies / smells

1. **Performance (biggest):** `load_advisor_context` is O(envelopes × periods)
   with ~4 sequential awaited queries per cell (e.g., 10 env × 6 periods ≈ 240
   round-trips) **on every dashboard load**. Should be 2–3 grouped aggregate
   queries (GROUP BY envelope_id, period). Same for `build_sinking_fund_advice`
   loading all transactions into memory.
2. **Stale "tabungan" name-matching post-purpose-feature.**
   `allocate_income_to_targets` (skip + leftover) and `_allocation_priority` key
   off `name.lower() == "tabungan"`. Now envelopes have `purpose`
   (`saving`/`sinking_fund`); a savings envelope named otherwise is mishandled,
   and an expense envelope named "Tabungan" would be mistreated. Switch to
   `purpose`.
3. **Goal % may disagree with the Goals page.** Advisor computes
   `balance = (allocated + rollover) − spent` for the *current period*, while
   `goals.py` computes `current_balance` from **all-time** allocations − spent.
   If `MonthlySnapshot.rollover_amount` isn't the full cumulative saldo, the two
   progress numbers diverge → inconsistent % between dashboard advisor and the
   envelope/goal cards. (Consistency across surfaces is a known user expectation.)
   Prefer a single shared balance source.
4. **`budget_overspend` mixes savings into the global projection.** It sums
   `total_allocated`/`total_spent` over **all** visible envelopes (incl.
   saving/sinking), while `/analytics/prediction` and the "Sisa bebas" KPI are
   **expense-only**. Savings deposits inflate `allocated` and aren't "spent",
   skewing the overspend signal and making the advisor inconsistent with the
   prediction card. Scope to `purpose == "expense"`.
5. **Early-period projection volatility.** `(spent/days_used)*days_total` on day
   1–2 produces wild projections → likely false `env_depletion` /
   `budget_overspend` alarms early in the period. Add a min-days guard or smooth.
6. **Dead branch:** in the saving block, `avg_contribution` is floored to ≥1
   just above, so the later `if avg_contribution <= 0 ...` can never be true.
7. **Brittle severity:** consolidated goals card severity is decided by
   substring-matching the ⚠️ emoji in generated lines instead of structured
   state. Saving items never escalate severity even when "belum ada setoran".
8. **Number formatting:** card bodies use Python `f"{x:,}"` (comma thousands,
   e.g. `Rp1,520,000`) while the Indonesian UI elsewhere uses dot grouping
   (`Rp1.520.000`). Verify/normalize for consistency.
9. **Robustness:** the advisor route intentionally does not swallow errors (per
   AGENTS.md). Keep that, but the perf/early-period issues above can still make
   it slow or noisy rather than wrong.

## Enhancement opportunities

- Batch context queries (GROUP BY) + optional short-TTL per-user cache; advisor
  runs on every dashboard mount.
- Single source of truth for envelope balance / goal progress (reuse the goals
  computation) so dashboard and advisor never disagree.
- Purpose-driven logic everywhere (drop name=="tabungan").
- Expense-only scoping for global overspend, matching the prediction/KPI.
- Privacy-aware advisor: visibility contract for shared vs personal; aggregate
  evidence that never prints other members' raw descriptions; optionally a
  "private" flag on transactions.
- Dismissible cards with server-side persistence; structured severity instead of
  emoji-string heuristics.
- Confidence labels + plain-language "why" on each card.

## For the dedicated (privacy) session — quick checklist

- [ ] Define household visibility contract (shared vs personal; aggregates vs raw).
- [ ] Scope sinking-fund evidence + spent aggregates to that contract (no raw
      cross-member descriptions).
- [ ] Decide on per-transaction privacy flag (model + migration) if needed.
- [ ] Fix goal-balance consistency (single source) and expense-only overspend.
- [ ] Replace name=="tabungan" with purpose.
- [ ] Batch queries for performance.
- [ ] Early-period projection guard; structured severity; number formatting.
