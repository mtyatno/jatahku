# AI Financial Advisor Implementation Plan

> **For agentic workers:** REQUIRED WORKFLOW: use the repository Superpowers
> pattern. Execute task-by-task, update checkbox state as work completes, use
> TDD where practical, debug systematically, and verify before claiming done.

**Goal:** Add non-chat AI-assisted decision features to Jatahku: allocation
recommendations, smart dashboard insight cards, and a detailed sinking fund
advisor.

**Architecture:** Add deterministic advisor logic in `app/services/advisor.py`
and expose it through `app/api/routes/advisor.py`. Frontend consumes advisor
endpoints through `frontend/src/lib/api.js`, then surfaces recommendations in
`Dashboard.jsx`, `Allocate.jsx`, and a detailed advisor section in either
`Analytics.jsx` or `Langganan.jsx`. The first iteration does not call an LLM.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, React/Vite, Tailwind CSS,
Recharts. Backend tests use stdlib `unittest` where possible. Frontend
validation uses `npm run build`.

---

## Task 1: Advisor helper tests

**Files:**
- Create: `app/tests/test_advisor.py`
- Later modify: `app/services/advisor.py`

- [x] **Step 1: Write failing tests for normalization**

Create tests for a future `normalize_description` helper:

- removes amount-like tokens,
- removes common filler words,
- keeps merchant/category terms,
- returns stable lowercase output.

- [x] **Step 2: Write failing tests for interval detection**

Create tests for a future `detect_interval` helper:

- dates 29-31 days apart => monthly,
- dates 6-8 days apart => weekly,
- sparse explicit annual keyword => yearly with low confidence,
- inconsistent dates => review/unknown.

- [x] **Step 3: Write failing tests for allocation distribution**

Create tests for a pure allocation helper:

- obligations are filled before discretionary targets,
- insufficient income returns warnings,
- leftover goes to `Tabungan` when present,
- locked envelopes are not used as transfer sources.

- [x] **Step 4: Verify tests fail for missing helpers**

Run:

```bash
python -m unittest app.tests.test_advisor -v
```

Expected: failing import or missing helper errors.

---

## Task 2: Backend advisor route skeleton

**Files:**
- Create: `app/api/routes/advisor.py`
- Modify: `app/main.py`
- Modify: `app/services/advisor.py`

- [x] **Step 1: Create placeholder service**

Create `app/services/advisor.py` with minimal async functions:

- `build_advisor_insights(user, db)`
- `build_allocation_recommendation(user, income_amount, db)`
- `build_sinking_fund_advice(user, db)`

Return safe empty structures until later tasks implement logic.

- [x] **Step 2: Add route module**

Create `app/api/routes/advisor.py` with:

- `GET /insights`
- `POST /allocation-recommendation`
- `GET /sinking-funds`

Use auth and DB dependencies following existing route style.

- [x] **Step 3: Register router**

Modify `app/main.py` to include the advisor router with prefix `/advisor` and
tag `advisor`.

- [x] **Step 4: Validate compile**

Run:

```bash
python -m py_compile app/services/advisor.py app/api/routes/advisor.py app/main.py
```

---

## Task 3: Shared advisor data loader

**Files:**
- Modify: `app/services/advisor.py`
- Test: `app/tests/test_advisor.py` if helper extraction allows it

- [x] **Step 1: Implement household lookup**

Add helper to resolve the current user's household id from `HouseholdMember`.
Return safe empty results when missing.

- [x] **Step 2: Implement period loader**

Use `get_budget_period` and `get_last_n_periods` to derive current and previous
payday-based periods from `user.payday_day`.

- [x] **Step 3: Implement envelope loader**

Load active envelopes visible to the user:

- shared envelopes,
- personal envelopes owned by the user.

- [x] **Step 4: Implement historical stats loader**

For each envelope and period, calculate:

- allocated,
- spent,
- transaction count,
- recurring monthly reserve,
- rollover when available.

- [x] **Step 5: Validate compile**

Run:

```bash
python -m py_compile app/services/advisor.py
```

---

## Task 4: Allocation recommendation engine

**Files:**
- Modify: `app/services/advisor.py`
- Modify: `app/api/routes/advisor.py`
- Test: `app/tests/test_advisor.py`

- [x] **Step 1: Make allocation helper tests pass**

Implement pure helper logic required by Task 1 allocation tests.

- [x] **Step 2: Add request schema**

Create request schema for `POST /advisor/allocation-recommendation`:

```json
{
  "income_amount": 8000000
}
```

Reject non-positive income amounts.

- [x] **Step 3: Calculate obligation minimums**

For every active envelope, calculate:

- active recurring monthly equivalent,
- negative rollover repayment,
- current underfunding against target,
- essential-category flag based on envelope name/keywords.

- [x] **Step 4: Calculate historical targets**

Use 3-6 previous budget periods. Prefer median or trimmed average spend. Fall
back to `Envelope.budget_amount` when history is sparse.

- [x] **Step 5: Allocate income conservatively**

Fill minimums first, then distribute remaining toward targets. Put leftover into
active `Tabungan` if it exists; otherwise return it as `unallocated`.

- [x] **Step 6: Return explanations**

Each item includes recommended amount, minimum amount, historical average,
recurring reserve, risk level, and evidence strings.

- [x] **Step 7: Run targeted tests and compile**

Run:

```bash
python -m unittest app.tests.test_advisor -v
python -m py_compile app/services/advisor.py app/api/routes/advisor.py
```

---

## Task 5: Smart insight cards engine

**Files:**
- Modify: `app/services/advisor.py`
- Modify: `app/api/routes/advisor.py`

- [x] **Step 1: Build current period score inputs**

Load current period totals:

- allocated,
- spent,
- reserved,
- free,
- safe daily amount,
- days used and remaining,
- per-envelope burn rate.

- [x] **Step 2: Generate risk cards**

Generate cards for:

- budget overspend risk,
- envelope depletion risk,
- subscription pressure,
- allocation drift,
- behavior control suggestion.

- [x] **Step 3: Generate positive cards**

Generate cards for:

- safe surplus,
- spending below safe daily,
- enough reserve for recurring obligations.

- [x] **Step 4: Rank and cap cards**

Sort by severity, rupiah impact, urgency, and confidence. Return all cards plus
`dashboard_cards` capped to the top 3.

- [x] **Step 5: Validate compile**

Run:

```bash
python -m py_compile app/services/advisor.py app/api/routes/advisor.py
```

---

## Task 6: Detailed sinking fund advisor engine

**Files:**
- Modify: `app/services/advisor.py`
- Modify: `app/api/routes/advisor.py`
- Test: `app/tests/test_advisor.py`

- [x] **Step 1: Make normalization and interval tests pass**

Implement `normalize_description` and `detect_interval` helpers from Task 1.

- [x] **Step 2: Load candidate transactions**

Load non-deleted transactions for the last 6-12 budget periods, joined to
visible envelopes. Load active recurring entries for duplicate detection.

- [x] **Step 3: Group similar candidates**

Group by normalized phrase and token overlap. Keep metadata:

- count,
- amount list,
- dates,
- envelope candidates,
- sample descriptions.

- [x] **Step 4: Detect amount stability**

Classify amount behavior as exact, stable range, variable recurring, or
unstable.

- [x] **Step 5: Compare against existing recurring entries**

Classify recommendations as:

- `create_recurring`,
- `adjust_recurring`,
- `reserve_more`,
- `annualize`,
- `review`.

Avoid duplicate recurring suggestions.

- [x] **Step 6: Build detailed recommendation output**

Each recommendation includes title, description, confidence, envelope, suggested
amount, monthly reserve, frequency, next expected date, evidence, impact, and
action payload.

- [x] **Step 7: Run targeted tests and compile**

Run:

```bash
python -m unittest app.tests.test_advisor -v
python -m py_compile app/services/advisor.py app/api/routes/advisor.py
```

---

## Task 7: Frontend API client

**Files:**
- Modify: `frontend/src/lib/api.js`

- [x] **Step 1: Add advisor methods**

Add:

- `getAdvisorInsights()`
- `getSinkingFundAdvice()`
- `getAllocationRecommendation(incomeAmount)`

- [x] **Step 2: Return safe fallbacks**

Follow existing client style. Failed GET calls should return empty cards or
recommendations where possible.

- [x] **Step 3: Validate frontend build**

Run:

```bash
cd frontend
npm run build
```

Do not commit `frontend/dist/` unless explicitly requested.

---

## Task 8: Allocation Assistant UI

**Files:**
- Modify: `frontend/src/pages/Allocate.jsx`

- [x] **Step 1: Add recommendation state**

Track loading state, recommendation response, advisor error, and whether the
recommendation has been applied.

- [x] **Step 2: Add recommendation button**

When `incomeNum > 0`, show `Rekomendasikan alokasi` near `Bagi proporsional`.
The button calls `api.getAllocationRecommendation(incomeNum)`.

- [x] **Step 3: Add explicit apply behavior**

Only prefill `allocations` after the user clicks an apply button. Preserve full
manual editability before save.

- [x] **Step 4: Show compact explanation**

Show total recommended, unallocated/tabungan amount, confidence, and top
warnings/reasons.

- [x] **Step 5: Validate frontend build**

Run:

```bash
cd frontend
npm run build
```

---

## Task 9: Smart Insight Cards UI

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`

- [x] **Step 1: Load advisor insights**

Fetch `api.getAdvisorInsights()` with existing dashboard data.

- [x] **Step 2: Render advisor cards**

Show top `dashboard_cards` above or in place of the current `DecisionBox`.
Keep `DecisionBox` as fallback if advisor returns no cards.

- [x] **Step 3: Wire routes**

Support card actions that route to existing pages. Avoid new modal workflows in
this task.

- [x] **Step 4: Validate frontend build**

Run:

```bash
cd frontend
npm run build
```

---

## Task 10: Sinking Fund Advisor UI

**Files:**
- Modify one:
  - `frontend/src/pages/Analytics.jsx`
  - `frontend/src/pages/Langganan.jsx`

- [x] **Step 1: Choose placement**

Prefer `Langganan.jsx` if it already manages recurring entries cleanly. Prefer
`Analytics.jsx` for a read-only first version.

- [x] **Step 2: Load advisor data**

Fetch `api.getSinkingFundAdvice()` on page load.

- [x] **Step 3: Render detailed recommendations**

For each recommendation, show confidence, monthly reserve, suggested amount,
frequency, next expected date, evidence, impact, and actions.

- [x] **Step 4: Keep actions cautious**

Initial actions can navigate to existing recurring/allocation pages. Dismiss can
remain frontend-only until backend persistence is designed.

- [x] **Step 5: Validate frontend build**

Run:

```bash
cd frontend
npm run build
```

---

## Task 11: Verification and review

**Files:**
- Update this plan as commands pass.

- [x] **Step 1: Run backend tests**

Run:

```bash
python -m unittest discover -s app/tests -v
```

- [x] **Step 2: Run frontend build**

Run:

```bash
cd frontend
npm run build
```

- [x] **Step 3: Review diff**

Review changed files before presenting as complete:

```bash
git diff --stat
git diff
```

- [ ] **Step 4: Manual smoke test**

Use a user with historical transactions and recurring entries. Verify:

- allocation recommendation gives useful amounts,
- dashboard cards rank urgent items first,
- sinking fund advisor explains repeated expenses with evidence,
- no recommendation auto-applies without confirmation.

---

## Known Dirty Files When Plan Was Created

Do not revert or overwrite these unless the user explicitly asks:

- `docs/superpowers/plans/2026-04-17-whatsapp-integration.md`
- `frontend/dist/favicon.svg`
- `frontend/dist/index.html`
- `landing.html`
- `.superpowers/`
- `temporary_file/`

