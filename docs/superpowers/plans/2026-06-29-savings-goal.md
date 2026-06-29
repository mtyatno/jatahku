# Savings Goal Target — Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate the existing `Goal` model with full CRUD, progress tracking, goal-aware allocation distribution, progress bars on Envelope cards, Dashboard widget, and achievement notifications.

**Architecture:** New `app/api/routes/goals.py` with CRUD + progress calculation. Frontend consumes through new API client methods. `EnvelopeCard` gains a second progress bar. `Allocate.jsx` gets goal-aware proportional distribution. `Dashboard.jsx` gets a goal widget. Goal achievement check hooks into existing transaction creation.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, React/Vite, Tailwind.

---

## Global Constraints

- One goal per envelope (enforced at API level on create).
- Goal progress reads current envelope balance (`allocated + rollover - spent`) — NOT just allocated in current period.
- `monthly_needed = (target_amount - current_balance) / months_remaining`, rounded up. Only computed when `target_date` is set.
- Goal achievement notification is best-effort, never blocks transaction creation.
- Allocation distribution is a nudge, not enforcement — user always overrides manually.
- Goal-aware distribution tracks `envelope.allocated` for current period to avoid double-filling.
- Envelope page already fetches envelope summary — goal data can be added to that response or fetched separately.
- No DB migration needed (Goal table already exists).

---

## Task 1: Backend — Goal CRUD routes

**Files:**
- Create: `app/api/routes/goals.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create schemas**

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
    current_balance: Decimal
    progress_pct: float
    monthly_needed: Decimal | None
    months_remaining: int | None
    is_achieved: bool
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Add `GET /goals/`**

List all goals for user's household-scoped envelopes. Include `current_balance`, `progress_pct`, `monthly_needed`, `months_remaining` as computed fields. Use `get_budget_period` for current period context.

Computation for each goal:
```python
balance = envelope.allocated + envelope.rollover - envelope.spent  # from current period summary
progress_pct = min(float(balance / target_amount) * 100, 100)
if target_date and target_date > today:
    months_remaining = max(1, (target_date.year - today.year) * 12 + target_date.month - today.month)
    monthly_needed = max(0, (target_amount - balance)) / months_remaining
else:
    months_remaining = None
    monthly_needed = None
is_achieved = balance >= target_amount
```

- [ ] **Step 3: Add `POST /goals/`**

Create a goal. Reject if envelope already has a goal (check existing). Verify envelope belongs to user's household.

- [ ] **Step 4: Add `GET /goals/{goal_id}`**

Single goal with same computed fields.

- [ ] **Step 5: Add `PUT /goals/{goal_id}`**

Update name, target_amount, target_date. Verify ownership.

- [ ] **Step 6: Add `DELETE /goals/{goal_id}`**

Delete goal. Verify ownership.

- [ ] **Step 7: Register router in `app/main.py`**

```python
from app.api.routes import goals
app.include_router(goals.router, prefix="/goals", tags=["goals"])
```

**Validation:** `python -m py_compile app/api/routes/goals.py app/main.py`

---

## Task 2: Backend — Goal achievement notification hook

**Files:**
- Modify: `app/api/routes/transactions.py`

- [ ] **Step 1: Add goal check after transaction creation**

In `create_transaction` (single), after `db.refresh(txn)`, add a best-effort block:

```python
try:
    from app.models.models import Goal
    from app.services.notification_service import send_notification
    result = await db.execute(
        select(Goal).where(
            Goal.envelope_id == req.envelope_id,
        )
    )
    goal = result.scalar_one_or_none()
    if goal:
        bal_result = await db.execute(
            select(
                func.coalesce(func.sum(Allocation.amount), 0) +
                func.coalesce(Envelope.rollover_amount, 0) -
                func.coalesce(func.sum(Transaction.amount), 0)
            )
            .select_from(Envelope)
            .outerjoin(Allocation, ...)
            . ...
        )
        balance = bal_result.scalar_one()
        if balance >= goal.target_amount:
            await send_notification(
                db, user.id,
                type=NotificationType.system,
                title="🎯 Goal tercapai!",
                message=f"{envelope.emoji} {envelope.name} sudah mencapai target {goal.name} sebesar Rp {int(goal.target_amount):,}. Selamat!"
            )
except Exception:
    pass
```

Also add to `batch_create_transactions` inside the per-item success block.

**Validation:** `python -m py_compile app/api/routes/transactions.py`

---

## Task 3: Frontend — API client

**Files:**
- Modify: `frontend/src/lib/api.js`

- [ ] **Step 1: Add goal methods**

```js
async getGoals()           // GET /goals/ → array of GoalResponse
async createGoal(data)     // POST /goals/
async updateGoal(id, data) // PUT /goals/{id}
async deleteGoal(id)       // DELETE /goals/{id}
```

Follow existing client pattern (return `{ ok, data }` for mutations, return data or `[]` for GET).

**Validation:** `npm run build`

---

## Task 4: Frontend — Goal form in Envelope page

**Files:**
- Modify: `frontend/src/pages/Envelopes.jsx`

- [ ] **Step 1: Add goal state to EnvelopeCard**

Load goals via `api.getGoals()` on page mount. Pass `goal` and callbacks into each `EnvelopeCard`.

- [ ] **Step 2: Add inline goal editor**

Below the existing envelope info, if the envelope has no goal, show a collapsible:
```
[+ 🎯 Tambah target tabungan]
```

Expanded: input fields for name, target_amount, target_date, and "Simpan" button.

If the envelope has a goal, show the goal progress bar (Task 5) and an "Edit" trigger that expands into the same form pre-filled with current values + "Hapus target" button.

- [ ] **Step 3: Wire save/edit/delete**

Calls `api.createGoal()`, `api.updateGoal()`, `api.deleteGoal()`. Re-fetch goals on change.

**Validation:** `npm run build`

---

## Task 5: Frontend — Goal progress bar on EnvelopeCard

**Files:**
- Modify: `frontend/src/pages/Envelopes.jsx`

- [ ] **Step 1: Add goal progress bar**

Below the existing spending progress bar, if the envelope has a goal:

```jsx
<div className="mt-2 pt-2 border-t border-gray-100">
  <div className="flex justify-between items-end mb-1">
    <span className="text-xs text-gray-400">🎯 {goal.name}</span>
    <span className="text-xs font-medium text-amber-600">{Math.round(goal.progress_pct)}%</span>
  </div>
  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
    <div className="h-full bg-amber-400 rounded-full transition-all duration-700"
      style={{ width: `${Math.max(goal.progress_pct, 2)}%` }} />
  </div>
  <p className="text-xs text-gray-400 mt-1">
    {formatShort(goal.current_balance)} / {formatShort(goal.target_amount)}
  </p>
  {goal.monthly_needed !== null && (
    <p className="text-xs text-gray-400 mt-0.5">
      📅 {goal.months_remaining} bulan · {formatShort(goal.monthly_needed)}/bulan
    </p>
  )}
  {goal.is_achieved && (
    <span className="inline-block mt-1 text-xs font-medium px-2 py-0.5 rounded-md bg-green-100 text-green-700">✅ Tercapai</span>
  )}
  {goal.target_date && new Date(goal.target_date) < new Date() && !goal.is_achieved && (
    <span className="inline-block mt-1 text-xs font-medium px-2 py-0.5 rounded-md bg-red-100 text-red-700">⚠️ Terlambat</span>
  )}
</div>
```

**Validation:** `npm run build`

---

## Task 6: Frontend — Dashboard goal widget

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`

- [ ] **Step 1: Load goals**

Fetch `api.getGoals()` on dashboard mount alongside existing data fetches.

- [ ] **Step 2: Render goals section**

Below KPI cards (above AdvisorCards), if any active goals exist:

```jsx
{goals?.length > 0 && (
  <div className="space-y-3">
    <h3 className="text-sm font-semibold text-gray-600">🎯 Target Menabung</h3>
    {goals.filter(g => !g.is_achieved).map(goal => (
      <div key={goal.id} className="card !p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-xl">{goal.envelope_emoji}</span>
            <span className="font-medium text-sm">{goal.name}</span>
            <span className="text-xs text-gray-400">({goal.envelope_name})</span>
          </div>
          <span className="text-sm font-bold text-amber-600">{Math.round(goal.progress_pct)}%</span>
        </div>
        <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
          <div className="h-full bg-amber-400 rounded-full transition-all duration-700"
            style={{ width: `${Math.max(goal.progress_pct, 2)}%` }} />
        </div>
        <div className="flex justify-between mt-1.5">
          <span className="text-xs text-gray-400">{formatShort(goal.current_balance)} / {formatShort(goal.target_amount)}</span>
          {goal.monthly_needed !== null && (
            <span className="text-xs text-gray-400">📅 {goal.months_remaining} bulan · {formatShort(goal.monthly_needed)}/bln</span>
          )}
        </div>
      </div>
    ))}
  </div>
)}
```

**Validation:** `npm run build`

---

## Task 7: Frontend — Goal-aware allocation distribution

**Files:**
- Modify: `frontend/src/pages/Allocate.jsx`

- [ ] **Step 1: Load goals**

Fetch `api.getGoals()` alongside envelopes. Find the goal for the Tabungan envelope (if any).

- [ ] **Step 2: Rewrite `distributeByBudget` to be goal-aware**

```js
const distributeByBudget = () => {
  if (envelopes.length === 0 || incomeNum <= 0) return;
  const tabunganEnv = envelopes.find(e => e.name === 'Tabungan');
  const tabunganGoal = goals?.find(g => g.envelope_id === tabunganEnv?.id);

  // Calculate goal amount for Tabungan
  let tabunganAmount = 0;
  if (tabunganGoal && tabunganGoal.monthly_needed !== null) {
    const alreadyAllocated = Number(tabunganEnv?.allocated || 0);
    const stillNeeded = Math.max(0, Number(tabunganGoal.monthly_needed) - alreadyAllocated);
    tabunganAmount = Math.min(stillNeeded, incomeNum);
  }

  const remaining = incomeNum - tabunganAmount;
  const otherEnvelopes = envelopes.filter(e => e.name !== 'Tabungan');
  const totalBudget = otherEnvelopes.reduce((s, e) => s + Number(e.budget_amount), 0);

  const newAlloc = {};
  if (tabunganAmount > 0 && tabunganEnv) {
    newAlloc[tabunganEnv.id] = tabunganAmount;
  }

  if (totalBudget > 0) {
    otherEnvelopes.forEach(env => {
      const ratio = Number(env.budget_amount) / totalBudget;
      newAlloc[env.id] = Math.round(remaining * ratio);
    });
  }

  setAllocations(newAlloc);
};
```

- [ ] **Step 3: Add goal reminder in allocation UI**

In the 3 KPI cards area, below "→ Tabungan" card, add a goal reminder line:

```jsx
{tabunganGoal && (
  <div className="col-span-3">
    <p className="text-xs text-gray-400">
      🎯 Target {tabunganGoal.name}: butuh{' '}
      <b className="text-amber-600">{formatShort(tabunganGoal.monthly_needed)}</b>/bulan
      {tabunganGoal.monthly_needed !== null && Number(remainder) >= Number(tabunganGoal.monthly_needed)
        ? ' ✅ Cukup'
        : ` ⚠️ Kurang ${formatShort(Math.max(0, Number(tabunganGoal.monthly_needed || 0) - remainder))}`}
    </p>
  </div>
)}
```

- [ ] **Step 4: Show Tabungan row in allocation list when goal exists**

Currently Tabungan is filtered out: `envelopes.filter(e => e.name !== 'Tabungan')`.

When a goal exists on Tabungan, show it as a row with the monthly_needed hint:

```jsx
{tabunganGoal && tabunganEnv && (
  <div key={tabunganEnv.id} className="flex items-center gap-3 bg-amber-50/30 rounded-lg p-2 -mx-2">
    <span className="text-lg w-8">{tabunganEnv.emoji}</span>
    <div className="flex-1">
      <div className="flex justify-between">
        <span className="text-sm font-medium">{tabunganEnv.name}</span>
        <span className="text-xs text-amber-600">
          🎯 {tabunganGoal.name} · {formatShort(tabunganGoal.monthly_needed)}/bln
        </span>
      </div>
    </div>
    <div className="relative w-32">
      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">Rp</span>
      <input type="number" className="input font-mono text-right pl-8 pr-10 text-sm"
        value={allocations[tabunganEnv.id] || remainder}
        onChange={e => {
          const val = Number(e.target.value) || 0;
          setAllocations(prev => ({ ...prev, [tabunganEnv.id]: val }));
        }}
      />
    </div>
  </div>
)}
```

**Validation:** `npm run build`

---

## Task 8: Tests and build verification

- [ ] **Step 1: Run backend tests**

```bash
python -m pytest app/tests/ -v
```

All 31 existing tests must stay green.

- [ ] **Step 2: Backend compile check**

```bash
python -m py_compile app/api/routes/goals.py app/main.py app/api/routes/transactions.py
```

- [ ] **Step 3: Frontend build**

```bash
cd frontend && npm run build
```

**Validation:** All tests pass + build succeeds with zero errors.

---

## Task 9: Manual smoke test

- [ ] **Step 1: Create a goal**

Go to Envelope page → click Tabungan card → add target "Nikah", Rp 10.000.000, target date 4 months from now. Verify goal appears with progress bar.

- [ ] **Step 2: Allocate with goal-aware distribution**

Go to Allocate page → enter income Rp 8.000.000 → click "Bagi proporsional". Verify:
- Tabungan gets `monthly_needed` amount first
- Remaining income distributed proportionally to other envelopes
- Goal reminder shows "Cukup" or "Kurang" appropriately

- [ ] **Step 3: Second allocation in same period (bonus)**

Add another income Rp 2.000.000 → click "Bagi proporsional". Verify:
- Tabungan gets 0 (already met monthly_needed from first allocation)
- All Rp 2.000.000 goes to other envelopes

- [ ] **Step 4: Dashboard widget**

Go to Dashboard → verify goals section appears with progress bar and monthly_needed info.

- [ ] **Step 5: Goal achievement**

Add transactions or allocations until Tabungan balance reaches target → verify notification appears and badge shows "✅ Tercapai".

---

## Deployment Notes

- No DB migration needed (`goals` table already exists).
- New router registration in `main.py`.
- Frontend build artifacts in `dist/` — do not commit.
