# Savings Goal Target - Design Spec

- **Date:** 2026-06-29
- **Status:** Draft (brainstorming phase)
- **Author:** mtyatno + Claude

## Summary

User sets a savings goal on an envelope (e.g., "Tabungan" → target Rp 10.000.000).
System tracks progress from envelope balance, calculates monthly savings needed if
deadline is set, shows progress bar on Envelope cards and Dashboard, and sends
notification when target is reached.

## Goal

Make users goal-oriented: see a concrete target, track progress, get reminded how
much to save per month. Turns abstract "saving money" into measurable milestones.

## Current State

- The `Goal` model already exists in `app/models/models.py` with fields: `id`,
  `envelope_id` (FK), `name`, `target_amount`, `target_date`.
- `Envelope` model has `goals` relationship (one-to-many).
- **No API routes, no frontend UI, no usage anywhere** except deletion in hard
  reset (`user_settings.py`).
- Amplop "Tabungan" is treated as a regular envelope with no special goal UI.
- Dashboard has KPI cards (allocated/spent/remaining/active envelopes), AdvisorCards,
  DecisionBox, charts. No savings goal widget.
- Envelope page shows cards with name, balance, progress bar (spent vs allocated),
  badges (locked, daily limit, cooling). No goal target.

## Design

### 1. Backend — Goal CRUD

**File:** `app/api/routes/goals.py` (new)

Restrict to **one goal per envelope** in v1.

#### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/goals/` | List all goals for user's household (envelope-scoped) |
| `POST` | `/goals/` | Create a goal (rejects if envelope already has a goal) |
| `GET` | `/goals/{goal_id}` | Get single goal with progress fields |
| `PUT` | `/goals/{goal_id}` | Update goal (name, target_amount, target_date) |
| `DELETE` | `/goals/{goal_id}` | Delete goal |

#### Schemas

```python
class GoalCreate(BaseModel):
    envelope_id: UUID
    name: str
    target_amount: Decimal
    target_date: date | None = None

class GoalUpdate(BaseModel):
    name: str | None = None
    target_amount: Decimal | None = None
    target_date: date | None = None

class GoalResponse(BaseModel):
    id: UUID
    envelope_id: UUID
    envelope_name: str
    envelope_emoji: str
    name: str
    target_amount: Decimal
    target_date: date | None
    current_balance: Decimal       # allocated + rollover - spent
    progress_pct: float            # min(current_balance / target_amount * 100, 100)
    monthly_needed: Decimal | None # (target - balance) / months_remaining, None if no target_date
    months_remaining: int | None
    created_at: datetime
    updated_at: datetime
```

#### Goal achievement check

After every transaction creation (in the batch/single create endpoint), check if
the envelope's balance reaches or exceeds the goal target. If so, generate a
notification:

```
🔔 Title: "🎯 Goal tercapai!"
Message: "Tabungan Rp 10.000.000 untuk Nikah sudah tercapai. Selamat!"
Type: system
```

This check runs best-effort (never blocks transaction).

### 2. Frontend — Envelope Card

**File:** `frontend/src/pages/Envelopes.jsx`

Each `EnvelopeCard` already shows a progress bar (spent vs allocated). When the
envelope has a goal, add a second progress bar below:

```
┌─────────────────────────────────────────────┐
│ 💰 Tabungan                                 │
│ Budget: Rp 1.000.000 / bulan                │
│ ┌─────────────────────────────────┐         │
│ │ ████████████░░░░░░  60%         │         │  ← spent vs allocated
│ │ Terpakai Rp 600rb               │         │
│ └─────────────────────────────────┘         │
│ Saldo: Rp 2.500.000                         │
│ ┌─────────────────────────────────┐         │
│ │ ██████░░░░░░░░░░░░  25%         │         │  ← goal progress
│ │ 🎯 Rp 2,5jt / Rp 10jt (Nikah)  │         │
│ │ 📅 4 bulan · Rp 1,875jt/bln    │         │
│ └─────────────────────────────────┘         │
│ [🔒] [📊] [⏳]   [✏️ Edit]                  │
└─────────────────────────────────────────────┘
```

Goal bar uses gold/amber color (`#F59E0B`) to differentiate from spending bar (green).

### 3. Frontend — Goal Form

Adding/editing goal via an inline expander or a small modal triggered from the
EnvelopeCard. Fields:
- **Nama target** (e.g., "Nikah", "Dana darurat", "Umroh")
- **Jumlah target** (Rp, required)
- **Tanggal target** (optional date picker)
- **Hapus target** button (if editing existing goal)

### 4. Frontend — Allocation Goal Reminder

**File:** `frontend/src/pages/Allocate.jsx`

When a goal exists on the Tabungan envelope, show a reminder in the allocation form.
The remainder (income - allocated) is what goes to Tabungan. Compare it against the
`monthly_needed` from the goal:

```
┌── Sisa → Tabungan ───────────────────────────┐
│ Rp 1.500.000                                  │
│ 🎯 Target Nikah: butuh Rp 1.875.000/bulan     │
│ ⚠️ Kurang Rp 375.000 dari rekomendasi         │  ← if sisa < goal needed
│ - atau -                                       │
│ ✅ Cukup! Sesuai rekomendasi bulanan           │  ← if sisa >= goal needed
│ - atau -                                       │
│ ℹ️ Set target tanggal untuk lihat rekomendasi  │  ← if goal has no target_date
└───────────────────────────────────────────────┘
```

This is a nudge, not enforcement. User tetap bisa alokasi lebih sedikit
atau lebih banyak. Placement: below the 3 KPI cards (Income / Dialokasikan / →
Tabungan) and above the envelope distribution list.

If there is no goal on Tabungan, this section is not shown (same as current behavior).

### 5. Frontend — Dashboard Widget

**File:** `frontend/src/pages/Dashboard.jsx`

A new section below KPI cards (above AdvisorCards) showing active goals:

```
┌── Target Menabung ──────────────────────────┐
│ 🎯 Nikah (Tabungan)                          │
│ ████████░░░░░░░░░░░░ 25%                     │
│ Rp 2,5jt / Rp 10jt · 4 bulan lagi            │
│ Rp 1,875jt/bulan untuk capai target          │
└──────────────────────────────────────────────┘
```

Only shown when user has at least one active goal (not achieved). Hidden if no
goals set.

### 5. Goal Achievement Notification

When a goal is reached (envelope balance >= target_amount):

1. Create a `Notification` with type `system`:
   - Title: `🎯 Goal tercapai!`
   - Message: `{envelope_emoji} {envelope_name} sudah mencapai target {goal_name} sebesar Rp {target_amount:,}. Selamat!`

2. Badge on envelope: show "✅ Tercapai" badge on the EnvelopeCard.

3. Dashboard: achieved goals shown in a separate "Tercapai" section or with a
   checkmark badge.

## Scope (v1)

**In scope:**
- Goal CRUD API (one goal per envelope).
- Goal form in Envelope page (expandable from card or modal).
- Goal progress bar on Envelope card (second bar, gold color).
- Allocation goal reminder in Allocate page (compare remainder vs monthly_needed).
- Goal progress widget on Dashboard (shown when goals exist).
- Goal achievement notification + badge.

**Out of scope:**
- Multiple goals per envelope.
- Automatic fund allocation toward goals (user always in control).
- Goal template/suggestions.
- Goal-based budget adjustment.
- Social/sharing of goal achievement.

## Validation Strategy

- Backend: `python -m py_compile` + `python -m pytest app/tests/ -v` on goal routes.
- Frontend: `npm run build`.
- Manual: create goal → verify progress bar on Envelope page → verify Dashboard
  widget → add transaction → verify progress updates → reach target → verify
  notification.

## Risks

- Goal target_date in the past → handle gracefully (show "Terlambat" badge, still
  show progress).
- Envelope balance decreases (spending) → goal progress can go backward. This is
  correct behavior.
- Goal on envelope that gets deleted → cascade delete goal (FK handles this).
