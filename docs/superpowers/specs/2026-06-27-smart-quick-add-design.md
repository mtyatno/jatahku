# Smart Quick-Add Transaction - Design Spec

- **Date:** 2026-06-27
- **Status:** Approved (pending spec review)
- **Author:** mtyatno + Claude

## Summary

Bring the Telegram bot's "learn-parse" envelope detection to the web, and make
the add-transaction form reusable beyond the Transaksi page. As the user types
the Keterangan (description), the Amplop (envelope) dropdown auto-selects the
best match using the same per-user learned-keyword + category logic the bot
uses. A global floating action button (FAB) opens a quick-add modal on every
page. Web-created transactions also contribute to the shared learning.

Approach is "A" (auto-select envelope only; the amount stays manual — the
description field does NOT parse the amount).

## Goal

- Reduce friction: the right envelope is pre-picked from the description.
- Make adding a transaction possible from anywhere (FAB), not only the Transaksi
  page.
- Unify learning: web input both consumes and reinforces the per-user
  keyword→envelope learning that today only the Telegram bot writes.

## Current State

- Classification + learning lives in `app/bot/handlers.py` (server-side, not
  Telegram-specific): `extract_keywords`, `guess_envelope_name`,
  `find_best_envelope(description, household_id, db, user_id)`,
  `save_learned_keywords(user_id, description, envelope_id, db)`, plus the
  `STOPWORDS` and `CATEGORY_KEYWORDS` constants. `parse_amount` also lives there.
- `find_best_envelope` ranking: (0) learned keywords per user (`UserEnvelopeKeyword`,
  highest count wins, `confident=True`); (1) exact category-name match
  (`confident=True`); (2) partial match (`confident=False`); (3) envelope name
  appears in description (`confident=True`). Returns `(envelope, confident)`.
- Importing from `bot/handlers.py` into a web route would pull Telegram
  dependencies, so the shared functions must be extracted.
- `app/api/routes/transactions.py` `create_transaction` (POST `/transactions/`)
  builds the `Transaction`, commits, then runs a best-effort `record_activity`
  (streak) inside try/except after `db.refresh(txn)`. That is the model for the
  learning hook. (Note: the handler currently has two consecutive `check_behavior`
  blocks — pre-existing, out of scope here.)
- `frontend/src/pages/Transactions.jsx` has an inline add form (amount /
  description / envelope dropdown) with offline-queue support via
  `app/lib/offlineQueue`.
- `frontend/src/components/Layout.jsx` wraps all pages — the home for a global FAB.

## Design

### 1. Backend

**Shared service (`app/services/txn_nlp.py`)** — move these from
`app/bot/handlers.py`, unchanged in behavior: `STOPWORDS`, `CATEGORY_KEYWORDS`,
`extract_keywords`, `guess_envelope_name`, `find_best_envelope`,
`save_learned_keywords`. `app/bot/handlers.py` imports them back from the service
(single source of truth; the bot's behavior is identical). `parse_amount` stays
in the bot (the web does not need it — amount is manual).

**Endpoint** — add to `app/api/routes/transactions.py`:
`POST /transactions/suggest-envelope` with body `{ "description": str }`,
returning `{ "envelope_id": UUID | null, "envelope_name": str | null,
"confident": bool }`. It resolves the caller's household, calls
`find_best_envelope(description, hid, db, user.id)`, and returns the match (or
nulls + `confident=false` when none). Auth + household-scoped like the rest of
the router.

**Learning hook** — in `create_transaction`, after `db.refresh(txn)`, add a
best-effort try/except call to `save_learned_keywords(user.id, req.description,
req.envelope_id, db)` followed by a commit, mirroring the streak block. It must
never block or fail the transaction. Applies to all sources that carry a
description (so web input reinforces learning alongside the bot).

### 2. Frontend

**`QuickAddTransaction` component** (`frontend/src/components/QuickAddTransaction.jsx`):
- Fields: Jumlah (Rp), Keterangan, Amplop (dropdown), Simpan/Batal.
- Loads the envelope list (via `api.getEnvelopes()`); accepts an `onSaved`
  callback and an optional `onCancel`.
- As the user types Keterangan, debounce ~400ms then call
  `api.suggestEnvelope(desc)`. If the result is `confident` AND the user has not
  manually chosen an envelope yet, auto-select the suggested envelope and show a
  small "disarankan" hint. Once the user changes the dropdown manually, stop
  auto-selecting for that entry.
- Save uses `api.createTransaction({ envelope_id, amount, description, source:
  'webapp' })`, preserving the existing offline-queue behavior (when offline,
  skip the suggestion call and enqueue the transaction).
- On successful save, dispatch a `window` `CustomEvent('jatahku:txn-added')` and
  call `onSaved`.

**Reuse:**
- `Transactions.jsx` replaces its inline form with `QuickAddTransaction`.
- A global **FAB** in `Layout.jsx`: a floating "+" button on every page that
  opens a modal hosting `QuickAddTransaction`.

**API client (`frontend/src/lib/api.js`):** add
`suggestEnvelope(description)` → returns the parsed JSON, or `null` on failure /
offline (never throws).

### 3. Cross-page refresh

Because the FAB is global, after a successful save the component dispatches
`window` event `jatahku:txn-added`. Pages that display transactions or balances
(Transaksi, Dashboard, Envelopes) add a listener that re-runs their existing
`load()`. Decoupled; no global state store.

### 4. Auto-select rules (precise)

- Trigger: description length ≥ 2 non-space chars, debounced 400ms.
- Apply suggestion only when `confident === true` and the user has not manually
  edited the envelope dropdown since the last clear.
- A manual dropdown change sets a "user touched" flag that suppresses further
  auto-select until the description is cleared/the form resets.
- Offline or failed suggest call: no-op (form remains fully manual).

## Scope (v1) and non-goals

- **In scope:** auto-select envelope from description, global FAB + quick-add
  modal, reusable `QuickAddTransaction` component, web learning on save, the
  `txn_nlp.py` extraction.
- **Out of scope:** free-text Telegram-style parsing of the amount, amount
  suggestions, any change to the bot's classification logic, fixing the
  duplicate `check_behavior` block, mounting the form on pages other than via the
  FAB (and the Transaksi page).

## Validation Strategy

- Backend: `python -m py_compile` changed files; `python -m unittest discover -s
  app/tests -v` stays green. Add a small unit test for the now-importable pure
  helpers `extract_keywords` and `guess_envelope_name` in `app/tests/`.
- Frontend: `npm run build` from `frontend/`.
- Manual: type "kopi" / "gojek" in the quick-add Keterangan and confirm the
  envelope auto-selects; change it manually and confirm auto-select stops; save
  from the FAB on the Dashboard and confirm the Transaksi list reflects it;
  confirm a saved keyword is reused next time.

## Risks

- **Behavior parity after extraction:** the bot must behave identically after the
  move. Mitigation: move code verbatim, import back, run the existing suite.
- **Suggestion latency/abuse:** debounce + only-when-confident keeps calls modest;
  failures are silent no-ops.
- **Cross-page event missed:** if a page has no listener it simply won't auto-refresh
  (acceptable; data is correct on next load). Build artifacts: do not commit
  `frontend/dist/`.
- **PWA cache:** service worker is versioned per build, so the new UI reaches
  users on next load.
