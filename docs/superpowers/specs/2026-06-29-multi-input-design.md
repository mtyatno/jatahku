# Multi-Input Rapid Expense Entry - Design Spec

- **Date:** 2026-06-29
- **Status:** Draft (brainstorming phase)
- **Author:** mtyatno + Claude

## Summary

Bring the Telegram bot's multi-item expense parsing to the PWA/desktop: user
types several expenses in freeform text (e.g., `kopi 15k, sabun 5rb, gojek
12000`), the frontend parses each item live, auto-suggests envelopes via the
existing NLP, shows a preview table for review/correction, and bulk-saves all
items in one go. Not chat-style — uses a textarea + preview table pattern.

This is the natural evolution of Smart Quick-Add (2026-06-27): Quick-Add
handles the auto-suggest envelope for a single item; Multi-Input handles
bulk parsing + review + bulk save.

## Goal

- **Speed**: record 3–10 expenses in seconds by pasting/typing freeform text.
- **Review**: show a preview table so the user can correct auto-matched envelopes
  before saving — avoids silent misclassifications.
- **Parity**: same parsing logic (`parse_amount` + `parse_multi_expense`) the
  Telegram bot uses, so users have a consistent mental model.
- **Not chat**: the UI stays a form/table, not a chatbot interface.

## Current State

- **Telegram bot** (`app/bot/handlers.py`, `app/bot/nlp_cmd.py`):
  - `parse_amount(text)` — regex `AMOUNT_ANYWHERE` extracts `(amount, description)`
    from text like `kopi 15k`, `15rb sabun`, `Rp 5.000 air`.
  - `parse_multi_expense(text)` — splits by `\n`, `,`, `;`, `terus`, `lalu`,
    `dan`; parses each part; returns list if >= 2 valid items found.
  - `handle_multi_expense()` — for each item: `find_best_envelope()` →
    auto-create if matched, queue unmatched for interactive keyboard.
- **Web app** (`frontend/src/components/QuickAddTransaction.jsx`):
  - Single-item form: amount, description, envelope dropdown (with
    `/transactions/suggest-envelope` auto-suggest), save button.
  - Global FAB in `Layout.jsx` opens modal hosting this component.
- **API** (`app/api/routes/transactions.py`):
  - `POST /transactions/` — creates one transaction.
  - `POST /transactions/suggest-envelope` — NLP suggestion for one description.
  - No batch endpoint exists yet.
- **NLP service** (`app/services/txn_nlp.py`):
  - `find_best_envelope(description, household_id, db, user_id)` — returns
    `(envelope, confident)`.
  - `save_learned_keywords(...)` — per-user learning (already hooked into web
    `create_transaction`).

## Design

### 1. Frontend — New Component: `MultiAddTransaction`

**File:** `frontend/src/components/MultiAddTransaction.jsx`

Replaces `QuickAddTransaction` inside the FAB modal in `Layout.jsx`.

#### Layout

```
┌─────────────────────────────────────────────────────┐
│ 💰 Catat Pengeluaran                          [✕]   │
├─────────────────────────────────────────────────────┤
│                                                     │
│ 📝 Ketik beberapa pengeluaran:                       │
│ Pisahkan dengan koma, baris baru, atau "dan"         │
│ ┌─────────────────────────────────────────────────┐ │
│ │ kopi 15k                                         │ │
│ │ sabun 5.000                                      │ │
│ │ gojek 12rb, air mineral 5k                       │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ ── 4 item terdeteksi ──────────────────────────────│
│ ┌─────────────────────────────────────────────────┐ │
│ │           │ Jumlah   │ Amplop                 │ │
│ │───────────│──────────│────────────────────────│ │
│ │ ✕ kopi   │  15.000  │ 🍽️Makan ·disarankan▾ │ │
│ │ ✕ sabun  │   5.000  │ 🛒Belanja ·disarankan▾│ │
│ │ ✕ gojek  │  12.000  │ 🚗Transport ·saran ▾  │ │
│ │ ✕ air m..│   5.000  │ ─ Pilih amplop ─▾     │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ ┌──────────────┐  ┌──────┐                          │
│ │ Simpan Semua │  │ Batal│                          │
│ └──────────────┘  └──────┘                          │
└─────────────────────────────────────────────────────┘
```

#### Behavior

1. **Textarea** — always visible. Placeholder with usage examples.
2. **Live parse** — on every keystroke (debounced 300ms), run `parseMultiExpense`
   on the textarea content. Results shown in the preview table below.
3. **Preview table** — each row shows:
   - Delete button (✕) — removes that item from the list.
   - Description — read-only, as parsed from the textarea.
   - Amount — formatted as currency (Rp X.XXX), read-only.
   - Envelope dropdown — pre-populated with the envelope list. If
     `/suggest-envelope` returns a confident match, it auto-selects and shows
     the "· disarankan" badge. User can manually change per row.
   - Rows with no envelope selected are highlighted (border/background) to
     indicate action needed.
4. **Bulk suggest-envelope** — when items are first parsed, call
   `POST /transactions/suggest-envelopes` (new batch endpoint) with all
   descriptions at once. Each item gets its suggested envelope, if confident.
   Subsequent edits to individual rows can re-trigger single suggestion.
5. **"Simpan Semua" button** — enabled when ≥ 1 item has an envelope selected.
   Sends `POST /transactions/batch` with all items that have envelopes.
   Items without envelopes are skipped (with a visual warning).
6. **Result feedback** — after save, show a brief inline toast:
   - "3 berhasil disimpan" (green)
   - "1 gagal: Melebihi limit harian" (red, per-item reason)
   - Failed items stay in the table for the user to correct and retry.
7. **Clear/reset** — textarea and table reset after successful save. Modal closes
   if all items succeeded.
8. **Offline** — parsing runs entirely on frontend (no network needed).
   Envelope suggestion won't work → dropdown stays manual. Save uses
   `enqueueTransaction` per item via the existing offline queue.

#### Single-item fallback

Below the preview table, a collapsible section:

> **Atau catat satu per satu** [expand ▾]

Expanding reveals the existing `QuickAddTransaction` inline (single row: amount,
description, envelope, save). This gives a way to add one last item quickly
without switching modes.

#### Component API

```jsx
<MultiAddTransaction onSaved={() => void} onCancel={() => void} />
```

Same interface as `QuickAddTransaction` — drop-in replacement in `Layout.jsx`.

---

### 2. Frontend — Parsing Library

**File:** `frontend/src/lib/parseAmount.js`

JavaScript port of `parse_amount` + `parse_multi_expense` from
`app/bot/handlers.py`. Pure functions, no side effects.

```js
// Matches amount anywhere: "15k kopi", "kopi 15k", "Rp 5.000 air", "15.000 sabun"
const AMOUNT_RE = /(?:rp\.?\s*)?(\d{1,3}(?:\.\d{3})+|\d+\.\d{1,2}|\d+(?:,\d+)?)\s*(jt|juta|rb|ribu|k)?(?!\w)|(?:rp\.?\s*)(\d+)/i;
const MULTIPLIERS = { jt: 1_000_000, juta: 1_000_000, rb: 1_000, ribu: 1_000, k: 1_000 };

export function parseAmount(text)  // → { amount: number, description: string } | null
export function parseMultiExpense(text)  // → [{ amount, description }, ...]  (empty if <2 items)
```

**Separator priority** (same as Python):
1. Newline (`\n`)
2. Comma `,` or semicolon `;` (not preceded by digit — avoids splitting `1,5`)
3. `terus` / `lalu` (word boundary)
4. `dan` (word boundary)

Returns items only if >= 2 valid `parseAmount` results.

---

### 3. Backend — Batch Endpoints

#### `POST /transactions/batch`

**Request:**
```json
{
  "items": [
    { "envelope_id": "uuid", "amount": 15000, "description": "kopi", "source": "webapp" },
    { "envelope_id": "uuid", "amount": 5000,  "description": "sabun", "source": "webapp" }
  ]
}
```

**Response** (array, one per input item, same order):
```json
[
  { "index": 0, "ok": true,  "id": "uuid", "description": "kopi" },
  { "index": 1, "ok": false, "description": "sabun", "error": "Melebihi limit harian. Limit: ..." }
]
```

**Behavior:**
- Each item processed independently — one failure does not block others.
- Each item runs: envelope verification, `check_behavior`, create `Transaction`,
  best-effort streak + `save_learned_keywords`.
- Items with the same envelope are processed in order (first-come-first-served
  for balance/limit checks).
- Returns `207 Multi-Status` if mixed success/failure, `201` if all succeeded,
  `422` if all failed.
- Learning: each successful item's description → envelope is learned.

#### `POST /transactions/suggest-envelopes`

**Request:**
```json
{
  "descriptions": ["kopi", "sabun", "gojek", "air mineral"]
}
```

**Response:**
```json
{
  "results": [
    { "index": 0, "envelope_id": "uuid-1", "envelope_name": "Makan", "confident": true },
    { "index": 1, "envelope_id": "uuid-2", "envelope_name": "Belanja", "confident": true },
    { "index": 2, "envelope_id": "uuid-3", "envelope_name": "Transport", "confident": true },
    { "index": 3, "envelope_id": null, "envelope_name": null, "confident": false }
  ]
}
```

Same logic as single `suggest-envelope`, batched for N descriptions in one
round-trip.

**File:** Both endpoints added to `app/api/routes/transactions.py`.

---

### 4. Layout.jsx — Modal Integration

**File:** `frontend/src/components/Layout.jsx`

Replace the FAB modal content from:
```jsx
<QuickAddTransaction onSaved={...} onCancel={...} />
```
to:
```jsx
<MultiAddTransaction onSaved={...} onCancel={...} />
```

The modal wrapper (backdrop, rounded-2xl card, "💰 Catat pengeluaran" header)
stays unchanged. `max-w-2xl` width remains appropriate.

---

## Scope (v1) and Non-Goals

**In scope:**
- `MultiAddTransaction` component with textarea + preview table + bulk save.
- `parseAmount.js` frontend parsing library (JS port of Python `parse_amount` +
  `parse_multi_expense`).
- `POST /transactions/batch` endpoint with per-item success/failure reporting.
- `POST /transactions/suggest-envelopes` batch suggestion endpoint.
- Collapsible single-item fallback (`QuickAddTransaction` inline).
- Offline support via existing `enqueueTransaction` per item.
- Replace FAB modal content in `Layout.jsx`.

**Out of scope:**
- Changing the Telegram bot's parsing logic (web just replicates it in JS).
- Editing parsed amounts/descriptions inline in the table (v1: read-only; user
  edits the textarea and re-parses).
- Drag-to-reorder items.
- Saving only a subset of parsed items (v1: save-all or retry-failed).
- Multi-input on the Transactions page inline form (FAB modal only for v1).

## Validation Strategy

- **Frontend unit tests:** `parseAmount` and `parseMultiExpense` with various
  input formats (`15k kopi`, `kopi 15rb`, `Rp 5.000 air`, multi-line,
  comma-separated, `dan`-separated, edge cases).
- **Backend:** `python -m unittest discover -s app/tests -v` stays green.
  Add tests for `POST /transactions/batch` — all success, mixed, all fail,
  invalid envelope, behavior checks.
- **Frontend build:** `npm run build` from `frontend/` passes.
- **Manual:** type `kopi 15k, sabun 5rb, gojek 12000` in the FAB modal, verify
  all 3 items parsed with correct amounts, envelopes auto-suggested, bulk save
  creates 3 transactions, learning persists for next use.

## Risks

- **Regex port accuracy:** JS regex vs Python regex behavioral differences.
  Mitigation: unit test with same test cases on both sides; flag edge cases.
- **Batch suggest-envelope latency:** N descriptions in one call. Mitigation:
  `find_best_envelope` is a DB query per item anyway, but batch endpoint
  runs them as a single request (with parallel async inside if needed).
- **Partial failure UX:** some items succeed, some fail. Mitigation: per-item
  result reporting in the table; failed items remain editable for retry.
- **Concurrency with same envelope:** two items targeting the same envelope
  may both pass behavior checks if balance hasn't been consumed yet.
  Mitigation: process items sequentially within the batch for the same
  envelope (the endpoint processes items in order).
- **Mobile view:** table with 3 columns may overflow narrow screens.
  Mitigation: responsive design — stack rows vertically on mobile (card
  layout per item, not a table).
