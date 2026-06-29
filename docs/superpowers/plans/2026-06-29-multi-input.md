# Multi-Input Rapid Expense Entry — Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-item expense entry to the PWA via a textarea + preview table pattern. User types freeform text (e.g., `kopi 15k, sabun 5rb, gojek 12000`), frontend parses live, NLP auto-suggests envelopes per item, user reviews/corrects, bulk saves.

**Architecture:** New `parseAmount.js` frontend lib (JS port of Python `parse_amount` + `parse_multi_expense`). New `MultiAddTransaction` component replaces `QuickAddTransaction` in the FAB modal. Two new batch API endpoints: `POST /transactions/suggest-envelopes` and `POST /transactions/batch`. Existing `QuickAddTransaction` kept as collapsible fallback inside the new component.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, React/Vite, Tailwind. Backend tests use `unittest`; frontend validated by `npm run build`.

## Global Constraints

- Parsing logic must match the Telegram bot's `parse_amount` + `parse_multi_expense` behavior (separator priority: `\n` → `,` / `;` → `terus`/`lalu` → `dan`).
- Batch save processes items sequentially per envelope to avoid balance/limit race conditions.
- Each item in batch is independent — one failure does not block others.
- Web learning (`save_learned_keywords`) runs per successful item, best-effort.
- Envelope auto-suggest only when `confident === true`.
- Frontend parse is offline-capable (pure JS, no network).
- Offline: each item queued individually via existing `enqueueTransaction`.
- Modal `max-w-2xl` width stays; responsive table → card layout on mobile.

---

## Task 1: Create frontend parsing library

**Files:**
- Create: `frontend/src/lib/parseAmount.js`
- Create: `frontend/src/lib/parseAmount.test.js` (if test framework exists)

**Interfaces:**
- Exports: `parseAmount(text: string) → { amount: number, description: string } | null`
- Exports: `parseMultiExpense(text: string) → [{ amount: number, description: string }, ...] | null`

- [ ] **Step 1: Port `parseAmount` from Python to JavaScript**

Port `AMOUNT_ANYWHERE` regex, `MULTIPLIERS` map, and the `parse_amount` logic from `app/bot/handlers.py` lines 47–93. The JS function:
1. Matches amount anywhere in input text via regex.
2. Handles dot-thousand (`1.500` → 1500), comma-thousand (`1,500` → 1500), decimal comma (`1,5` → 1.5).
3. Applies multiplier (k, rb, ribu, jt, juta).
4. Extracts description (everything except the matched amount portion).
5. Returns `{ amount: number, description: string }` or `null`.

Key differences from Python: JS regex needs `\b` for word boundaries; Python's raw strings become JS regex literals. Test with: `"35k kopi"`, `"kopi 15rb"`, `"Rp 5.000 air"`, `"sabun 5,5"`, `"beli 1.500 sabun"`, `"1,5 kopi"`.

- [ ] **Step 2: Port `parseMultiExpense`**

Port `parse_multi_expense` from `app/bot/nlp_cmd.py` lines 299–317. Same separator priority:
1. `\n` (newline)
2. `,` or `;` (comma NOT preceded by digit)
3. `terus` / `lalu` (word boundary)
4. `dan` (word boundary)

Returns list only when >= 2 valid `parseAmount` results. Returns `null` (or empty array) otherwise.

Test with: `"kopi 15k\nsabun 5k"`, `"kopi 15k, sabun 5k"`, `"kopi 15k dan sabun 5rb"`, `"gojek 12rb; bakso 15k"`, `"kopi 15k"` (single item → null).

**Validation:** `npm run build` from `frontend/` passes.

---

## Task 2: Create batch envelope suggestion endpoint

**Files:**
- Modify: `app/api/routes/transactions.py`

- [ ] **Step 1: Add request/response schemas**

```python
class BatchSuggestEnvelopeItem(BaseModel):
    index: int
    description: str

class BatchSuggestEnvelopeRequest(BaseModel):
    descriptions: list[str]

class BatchSuggestEnvelopeResult(BaseModel):
    index: int
    envelope_id: str | None
    envelope_name: str | None
    confident: bool
```

- [ ] **Step 2: Add `POST /transactions/suggest-envelopes` endpoint**

Accepts `{ descriptions: [...] }`, returns `{ results: [...] }`. For each description, calls `find_best_envelope()`. Same auth + household scope as `/suggest-envelope`. Returns per-item result with same index position.

**Validation:** `python -m pytest app/tests/ -k suggest_envelopes -v` or manual curl test.

---

## Task 3: Create batch transaction creation endpoint

**Files:**
- Modify: `app/api/routes/transactions.py`

- [ ] **Step 1: Add request/response schemas**

```python
class BatchTransactionItem(BaseModel):
    envelope_id: UUID
    amount: Decimal
    description: str
    source: TransactionSource = TransactionSource.webapp
    transaction_date: date | None = None

class BatchTransactionCreate(BaseModel):
    items: list[BatchTransactionItem]

class BatchTransactionResult(BaseModel):
    index: int
    ok: bool
    id: UUID | None = None
    description: str
    error: str | None = None
```

- [ ] **Step 2: Add `POST /transactions/batch` endpoint**

For each item:
1. Verify envelope belongs to user's household.
2. Run `check_behavior`.
3. If allowed: create `Transaction`, commit, refresh, best-effort `record_activity` + `save_learned_keywords`.
4. If not allowed: return error message in result. DO NOT block subsequent items.
5. Items are processed sequentially to avoid same-envelope race conditions.

Return HTTP 207 if mixed, 201 if all success, 422 if all failed.

- [ ] **Step 3: Handle edge cases**

- Duplicate envelope_id in multiple items → process in order, balance/limit may exhaust.
- Invalid envelope → `ok: false` with "Envelope not found".
- Behavior checks: locked, daily_limit, cooling, not_funded, insufficient → proper error messages.

**Validation:** `python -m pytest app/tests/ -k batch -v`

---

## Task 4: Add frontend API client methods

**Files:**
- Modify: `frontend/src/lib/api.js`

- [ ] **Step 1: Add `batchSuggestEnvelopes(descriptions)`**

```js
batchSuggestEnvelopes(descriptions) // → { results: [...] } or null on failure
```

Sends `POST /transactions/suggest-envelopes`. Parses JSON. Returns null on error/offline (never throws).

- [ ] **Step 2: Add `batchCreateTransactions(items)`**

```js
batchCreateTransactions(items) // → [{ index, ok, id, description, error }, ...] or null
```

Sends `POST /transactions/batch`. Parses JSON array of per-item results. Returns null on network error.

**Validation:** `npm run build` from `frontend/` passes.

---

## Task 5: Create `MultiAddTransaction` component

**Files:**
- Create: `frontend/src/components/MultiAddTransaction.jsx`

**Interfaces:**
- Props: `onSaved: () => void`, `onCancel: () => void`
- Same signature as `QuickAddTransaction` for drop-in replacement.

- [ ] **Step 1: Wire up textarea with live parse**

1. State: `rawText` (textarea content), `items` (parsed array).
2. `useEffect` with debounce 300ms: call `parseMultiExpense(rawText)` → set `items`.
3. If `parseMultiExpense` returns null (0–1 items), but `parseAmount(rawText)` returns 1 item → show single row anyway (user might be typing second item).
4. If textarea is empty → `items = []`, no table shown.

- [ ] **Step 2: Build preview table with envelope dropdowns**

Table columns: **Keterangan** | **Jumlah (Rp)** | **Amplop**

For each item in `items`:
1. Description column: read-only text + delete button (✕).
2. Amount column: formatted as `Rp 15.000` (read-only).
3. Envelope column: `<select>` dropdown populated from `api.getEnvelopes()`. Shows `"· disarankan"` badge when auto-suggested.
4. Row highlighting: if `envelopeId` is null after suggestions are fetched, show a subtle border/background to flag it.

- [ ] **Step 3: Implement bulk envelope suggestion**

When `items` first populate (new parse result), call `api.batchSuggestEnvelopes(items.map(i => i.description))`. For each result where `confident === true`, auto-select that envelope in the corresponding row. Store per-row `userTouched` ref (similar to QuickAddTransaction) — manual envelope change stops auto-suggest for that row.

If offline (`batchSuggestEnvelopes` returns null), skip auto-suggest; user selects envelopes manually.

- [ ] **Step 4: Implement bulk save ("Simpan Semua")**

1. Filter `items` that have `envelopeId` selected.
2. If none selected → show error "Pilih amplop untuk setiap item".
3. Call `api.batchCreateTransactions(filteredItems.map(...))`.
4. Parse results:
   - Items with `ok: true`: mark as saved (green checkmark or remove from table).
   - Items with `ok: false`: show error message inline on the row, keep in table for retry.
5. After all processed, dispatch `jatahku:txn-added` event, count successes vs failures.
6. If all succeeded → close modal via `onSaved`. If partial → show toast and keep failed rows.

- [ ] **Step 5: Offline handling**

When `!navigator.onLine`:
1. Parse still works (pure JS).
2. Envelope suggestions won't work → manual envelope selection only.
3. Save: call `enqueueTransaction(payload)` for each item individually.
4. Show "Disimpan offline — akan dikirim saat online" message.
5. Reset form and close modal.

- [ ] **Step 6: Add collapsible single-item fallback**

Below the preview table, a collapsible section:
> **Atau catat satu per satu** `[▼/▲]`

Expanded: renders `<QuickAddTransaction />` inline (no modal wrapper, just the form). This gives a way to add one last item quickly. After save, it resets independently of the multi-input.

- [ ] **Step 7: Responsive layout**

Desktop: 3-column table (desc | amount | envelope).
Mobile (< 768px): card layout per item (stacked vertically):
```
┌──────────────────┐
│ Keterangan  ✕    │
│ Rp 15.000         │
│ [🍽️ Makan ▾]    │
└──────────────────┘
```

- [ ] **Step 8: Empty state**

When textarea is empty: show a simple illustration or helper text: "Ketik pengeluaran Anda di atas. Pisahkan dengan koma atau baris baru."

**Validation:** `npm run build` from `frontend/` passes; manual testing in browser.

---

## Task 6: Integrate into Layout.jsx FAB modal

**Files:**
- Modify: `frontend/src/components/Layout.jsx`

- [ ] **Step 1: Replace component in FAB modal**

In `Layout.jsx`, replace:
```jsx
import QuickAddTransaction from './QuickAddTransaction';
...
<QuickAddTransaction onSaved={() => setFabOpen(false)} onCancel={() => setFabOpen(false)} />
```
with:
```jsx
import MultiAddTransaction from './MultiAddTransaction';
...
<MultiAddTransaction onSaved={() => setFabOpen(false)} onCancel={() => setFabOpen(false)} />
```

The modal wrapper (backdrop, card, header) stays unchanged.

**Validation:** `npm run build` passes.

---

## Task 7: Tests

- [ ] **Step 1: Frontend parseAmount tests**

Test cases for `parseAmount`:
- `"35k kopi"` → `{ amount: 35000, description: "kopi" }`
- `"kopi 15rb"` → `{ amount: 15000, description: "kopi" }`
- `"Rp 5.000 air"` → `{ amount: 5000, description: "air" }`
- `"sabun 5,5"` → `{ amount: 5.5, description: "sabun" }` (decimal comma → 5.5)
- `"beli 1.500 sabun"` → `{ amount: 1500, description: "beli sabun" }`
- `"1,5 juta kopi"` → `{ amount: 1500000, description: "kopi" }`
- `"bayar listrik 500rb"` → `{ amount: 500000, description: "bayar listrik" }`
- `"tanpa angka"` → `null`
- `"0 k"` → `null` (amount <= 0)
- `"Rp5000 kopi"` → `{ amount: 5000, description: "kopi" }` (no space after Rp)

Test cases for `parseMultiExpense`:
- `"kopi 15k\nsabun 5k"` → 2 items
- `"kopi 15k, sabun 5rb"` → 2 items
- `"kopi 15k dan sabun 5rb"` → 2 items
- `"gojek 12rb; bakso 15k"` → 2 items
- `"kopi 15k"` → null (single item)
- `"1,5 kopi, 2,5 sabun"` → 2 items (comma after digit = decimal, not separator)
- `"kopi 15k, sabun"` → null (second item has no amount)
- Empty string → null
- `"kopi 15k terus bakso 10k lalu aqua 5k"` → 3 items

- [ ] **Step 2: Backend batch endpoint tests**

Test `POST /transactions/batch`:
- All items valid → 201, all ok with IDs.
- Mixed (some invalid envelope, some behavior fail, some ok) → 207, per-item results.
- All items fail (invalid envelopes) → 422 or 207 with all errors.
- Same envelope in multiple items → both succeed if balance sufficient; second fails "insufficient" if first consumed budget.
- Empty items array → 400 or 422.

Test `POST /transactions/suggest-envelopes`:
- Multiple known descriptions → per-item results.
- Empty descriptions array → still returns 200 with empty results.
- Unauth → 401.

- [ ] **Step 3: Build verification**

```bash
cd frontend; if ($?) { npm run build }
```

Must pass with zero errors.

**Validation:** All test suites green + build green.

---

## Task 8: Manual integration test

- [ ] **Step 1: Test freeform parsing**

Open the app, click FAB (+), type:
```
kopi 15k
sabun 5.000
gojek 12rb, air mineral 5k
```
Verify: 4 items parsed with correct amounts (15.000, 5.000, 12.000, 5.000).

- [ ] **Step 2: Test envelope auto-suggest**

After parsing, verify envelopes are auto-selected for recognized keywords (kopi → Makan, gojek → Transport). Verify "· disarankan" badge appears.

- [ ] **Step 3: Test manual envelope correction**

Change an auto-selected envelope, verify the change persists and badge disappears.

- [ ] **Step 4: Test bulk save**

Click "Simpan Semua", verify all transactions appear on Transactions page, balances update on Envelopes page.

- [ ] **Step 5: Test partial failure**

Try to save an item with amount exceeding envelope balance. Verify: that item shows error, others are saved, failed item stays in table for retry.

- [ ] **Step 6: Test offline flow**

Disconnect network. Parse text, manually select envelopes, save. Verify items are queued in IndexedDB. Reconnect, verify sync.

- [ ] **Step 7: Test mobile view**

Open on narrow viewport. Verify card layout (not table) works correctly.

- [ ] **Step 8: Test single-item fallback**

Expand "Atau catat satu per satu", verify QuickAddTransaction works, save one item, verify it appears in transactions.

---

## Deployment Notes

- No database migrations needed for this feature (no new models).
- New endpoints are additive; existing single-item flow unchanged.
- `MultiAddTransaction` replaces `QuickAddTransaction` in FAB modal only; `QuickAddTransaction` component remains for inline use on Transactions page.
- Frontend build artifact `dist/` must not be committed.
