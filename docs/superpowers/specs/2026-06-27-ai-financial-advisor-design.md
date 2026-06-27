# AI Financial Advisor - Design Spec

- **Date:** 2026-06-27
- **Status:** Draft
- **Author:** mtyatno + Codex

## Summary

Enhance Jatahku with non-chat AI-assisted financial decision features:

1. AI Allocation Assistant
2. Smart Insight Cards
3. Detailed Sinking Fund Advisor

The product surface is cards, recommendations, previews, and explicit action
buttons. The first implementation should be deterministic and explainable. LLM
usage can be added later behind a service boundary, but financial math and
safety checks must remain reproducible.

## Goal

Help users make better budgeting decisions at the moment they already act:

- allocating new income,
- checking dashboard status,
- managing predictable recurring or annual expenses.

This strengthens Jatahku's positioning as "pengendali keuangan", not a generic
finance chatbot.

## Product Principles

- **No chat UI:** recommendations appear as cards and buttons.
- **Explain every number:** each suggestion shows evidence and reasoning.
- **User stays in control:** nothing is applied without confirmation.
- **Conservative by default:** required reserves and locked envelopes are
  protected.
- **Privacy-conscious:** advisor endpoints should return derived summaries, not
  unnecessary raw transaction history.

## Current State

### Backend

- `app/models/models.py` already contains the needed entities:
  `User`, `Household`, `Envelope`, `Transaction`, `Income`, `Allocation`,
  `RecurringTransaction`, `Goal`, `MonthlySnapshot`, and envelope behavior
  controls.
- `app/api/routes/analytics.py` exposes rule-based analytics: daily spending,
  envelope breakdown, monthly trend, weekly pattern, and prediction.
- `app/api/routes/envelopes.py` exposes summary fields: allocated, rollover,
  spent, reserved, remaining, free, funded ratio, and spent ratio.
- `app/services/summary.py` builds deterministic daily and weekly summaries.
- `app/bot/handlers.py` and `app/bot/wa_handlers.py` use regex, category
  keywords, and learned keywords for transaction classification.

### Frontend

- `frontend/src/pages/Dashboard.jsx` has `DecisionBox`, monthly comparison,
  weekly pattern, and envelope status cards.
- `frontend/src/pages/Allocate.jsx` has manual allocation and a simple
  proportional split helper.
- `frontend/src/pages/Analytics.jsx` has charts and prediction.
- `frontend/src/lib/api.js` centralizes API calls.

## Feature 1: AI Allocation Assistant

### User Story

When a user enters income, Jatahku recommends how to split it across envelopes
using obligations, historical usage, rollover, and risk. The recommendation can
prefill the form only after explicit user approval.

### Inputs

- Income amount from the allocation form.
- Active envelopes visible to the user.
- Current and previous budget periods based on `User.payday_day`.
- Historical allocations and transactions for 3-6 prior periods.
- Active recurring monthly equivalents.
- Current rollover and negative balances.
- Envelope behavior controls.

### Output

The endpoint returns recommended amounts, minimum amounts, historical averages,
recurring reserves, risk levels, explanations, warnings, confidence, and any
unallocated or savings amount.

### Algorithm

1. Calculate required obligations:
   - active recurring monthly equivalent,
   - negative rollover repayment,
   - other unavoidable reserves when available.
2. Calculate historical need:
   - use 3-6 previous budget periods,
   - prefer median or trimmed average,
   - ignore empty periods,
   - cap outliers.
3. Establish envelope minimum:
   - max(required obligation, negative repayment),
   - essential category fallback when income is tight.
4. Rank envelopes:
   - required obligations,
   - essential routine categories,
   - high-confidence historical spend,
   - discretionary envelopes,
   - savings.
5. Allocate income:
   - fill minimums first,
   - distribute remaining toward recommended targets,
   - send leftover to `Tabungan` when present or return as `unallocated`.
6. Explain each recommendation with compact evidence.

## Feature 2: Smart Insight Cards

### User Story

On Dashboard, users see a short prioritized list of what matters now and what
they can do next.

### Card Types

- Overspend risk.
- Envelope depletion risk.
- Weekend or weekday spending pattern.
- Subscription pressure.
- Allocation drift.
- Safe surplus.
- Behavior control suggestion.

### Ranking

Rank by severity, rupiah impact, time sensitivity, and confidence. Dashboard
shows only the top 3 cards by default. Detailed pages may show more.

### Action Model

Cards can link to existing flows:

- `/allocate`
- `/envelopes`
- `/analytics`
- `/langganan`

No new modal-heavy workflow is required for the first iteration.

## Feature 3: Detailed Sinking Fund Advisor

### User Story

Jatahku detects predictable expenses that should be reserved monthly and guides
the user to create or adjust recurring/sinking-fund entries.

### Detection Sources

1. Existing `RecurringTransaction` entries.
2. Repeated transaction descriptions with similar amount and interval.
3. Large one-off annual or semiannual expenses from previous periods.
4. Keywords indicating subscriptions or obligations:
   `langganan`, `sewa`, `kontrak`, `internet`, `domain`, `hosting`, `pajak`,
   `asuransi`, `sekolah`, `service`, `perpanjang`, `renewal`.
5. Goals, if they are relevant and reliable.

### Pattern Detection

For each candidate:

- collect non-deleted transactions for 6-12 budget periods when available,
- normalize descriptions by removing amount words and stopwords,
- group similar descriptions by token overlap,
- detect interval:
  - weekly: 5-9 days,
  - monthly: 25-35 days,
  - quarterly, semiannual, yearly when enough evidence exists,
  - annual from one old transaction only when explicit words support it,
- detect amount stability:
  - exact or near-exact amount,
  - stable range,
  - variable recurring category.

### Recommendation Types

- `create_recurring`: recurring pattern exists but no active recurring entry.
- `adjust_recurring`: existing recurring appears stale.
- `reserve_more`: recurring exists but envelope is often underfunded.
- `annualize`: annual or semiannual expense should be split monthly.
- `review`: weak signal that needs user confirmation.

### Recommendation Detail

Each recommendation should include:

- title,
- description,
- confidence,
- envelope,
- suggested amount,
- monthly reserve,
- frequency,
- next expected date,
- evidence list,
- impact explanation,
- safe action payload.

### Safety Rules

- Never auto-create recurring transactions.
- Do not recommend moving money from locked envelopes.
- Do not claim certainty for single-observation annual predictions.
- Separate monthly reserve need from due-now status.
- If income is insufficient, show priority order instead of pretending all
  reserves can be funded.
- Ignore deleted transactions.
- Use payday-based periods, not calendar months.

## Backend Design

Create:

- `app/services/advisor.py`
- `app/api/routes/advisor.py`

Endpoints:

- `GET /advisor/insights`
- `POST /advisor/allocation-recommendation`
- `GET /advisor/sinking-funds`

Core math should live in helper functions that can be unit-tested without
FastAPI.

## Frontend Design

Update:

- `frontend/src/lib/api.js`
- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/pages/Allocate.jsx`
- `frontend/src/pages/Analytics.jsx` or `frontend/src/pages/Langganan.jsx`

Initial UI placement:

- Dashboard: compact smart insight cards.
- Allocate: recommendation button and apply-to-form behavior.
- Analytics or Langganan: detailed sinking fund advisor.

## LLM Boundary

Do not add direct OpenAI or other LLM calls in the first implementation. If an
LLM is added later:

- isolate it behind `app/services/ai_provider.py`,
- validate returned JSON with Pydantic,
- send derived summaries rather than raw full history by default,
- treat LLM text as suggestion copy, not authoritative financial math.

## Out of Scope

- Receipt OCR.
- Voice transcription.
- Bank or e-wallet import.
- Automatic recurring creation.
- Regulated investment or credit advice.

## Validation Strategy

- Unit-test deterministic helpers where practical.
- Compile backend files with `python -m py_compile`.
- Run backend tests with `python -m unittest discover -s app/tests -v`.
- Build frontend with `npm run build` from `frontend/`.
- Manually test with a user containing historical transactions, recurring
  entries, and at least one repeated subscription-like transaction.

## Risks

- Sparse user history can reduce quality. Return low-confidence fallback
  suggestions.
- Too many cards can become noisy. Dashboard must cap recommendations.
- Regex grouping can misclassify merchants. Show evidence and require explicit
  confirmation.
- Builds may alter `frontend/dist/`; do not commit dist by default.

