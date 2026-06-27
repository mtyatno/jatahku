# Smart Quick-Add Transaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-select the envelope from the description as the user types, make the add-transaction form reusable via a global FAB, and have web input contribute to the shared keyword→envelope learning.

**Architecture:** Extract the bot's classification helpers into `app/services/txn_nlp.py` (bot imports them back, behavior unchanged). Add `POST /transactions/suggest-envelope` and a best-effort learning hook in `create_transaction`. On the frontend, a reusable `QuickAddTransaction` component does debounced envelope suggestion; it is mounted in the Transaksi page and in a global FAB modal in `Layout.jsx`. A `window` event `jatahku:txn-added` triggers page refreshes.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, React/Vite, Tailwind. Backend tests use stdlib `unittest`; frontend validated by `npm run build`.

## Global Constraints

- Approach A: auto-select envelope only; the amount stays manual (the description field does NOT parse the amount).
- Behavior of the Telegram bot must be unchanged after the extraction (move code verbatim, import it back).
- Web learning is best-effort and must NEVER block or fail a transaction (mirror the existing streak `record_activity` try/except in `create_transaction`).
- Auto-select fires only when the suggestion is `confident` AND the user has not manually changed the envelope; a manual change suppresses auto-select until the description is cleared.
- Suggestion debounce ~400ms; description must be ≥2 non-space chars to trigger.
- Frontend validated by `npm run build`; do NOT commit `frontend/dist/`.
- Branch: `feat/smart-quick-add`.

---

## Task 1: Extract shared NLP service

**Files:**
- Create: `app/services/txn_nlp.py`
- Modify: `app/bot/handlers.py`

**Interfaces:**
- Produces: `app.services.txn_nlp` exporting `STOPWORDS`, `CATEGORY_KEYWORDS`, `extract_keywords(description) -> list`, `guess_envelope_name(description) -> str | None`, `save_learned_keywords(user_id, description, envelope_id, db)` (async), `find_best_envelope(description, household_id, db, user_id=None) -> (Envelope | None, bool)`.

- [ ] **Step 1: Create the service module**

Create `app/services/txn_nlp.py` with exactly this content (these are the functions/constants moved verbatim from `app/bot/handlers.py`):

```python
"""Shared transaction NLP: keyword extraction, category guessing, per-user
learned keyword matching. Used by both the Telegram bot and the web API so the
two channels share one classification + learning implementation."""
from sqlalchemy import select

from app.models.models import Envelope

STOPWORDS = {"di", "ke", "dari", "yang", "dan", "untuk", "dengan", "ya", "aku",
             "saya", "kamu", "ini", "itu", "ada", "buat", "sama", "juga", "mau",
             "beli", "bayar", "beli", "tadi", "lagi", "udah", "sudah", "pas", "aja"}

CATEGORY_KEYWORDS = {
    "makan": ["makan", "nasi", "ayam", "sate", "bakso", "mie", "noodle", "rice",
              "lunch", "dinner", "breakfast", "sarapan", "siang", "malam",
              "warteg", "padang", "resto", "restaurant", "cafe", "kafe",
              "kopi", "coffee", "starbucks", "mcd", "kfc", "pizza",
              "gofood", "grabfood", "shopeefood", "snack", "jajan"],
    "transport": ["grab", "gojek", "ojek", "taxi", "bensin", "parkir",
                  "tol", "busway", "mrt", "krl", "kereta", "bus",
                  "transport", "uber", "maxim", "indriver"],
    "hiburan": ["nonton", "film", "bioskop", "game", "steam", "netflix",
                "spotify", "youtube", "premium", "langganan", "subscribe",
                "hangout", "karaoke", "mall"],
    "belanja": ["baju", "pakaian", "fashion", "kaos", "celana", "jaket", "kemeja", "dress",
                "sepatu", "sandal", "tas", "dompet", "aksesoris", "jam tangan",
                "shopee", "tokped", "tokopedia", "lazada", "tiktok shop", "belanja", "online", "shop"],
    "tagihan": ["listrik", "air", "pdam", "internet", "wifi", "pulsa",
                "token", "indihome", "telkom", "pln"],
}


def extract_keywords(description: str) -> list:
    import re as _re
    words = _re.sub(r'[^\w\s]', '', description.lower()).split()
    keywords = [w for w in words if len(w) >= 3 and w not in STOPWORDS]
    # Also include full cleaned phrase for exact future matches
    phrase = " ".join(keywords)
    if phrase and phrase not in keywords:
        keywords.append(phrase)
    return keywords


def guess_envelope_name(description):
    desc_lower = description.lower()
    for envelope_name, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                return envelope_name
    return None


async def save_learned_keywords(user_id, description: str, envelope_id, db):
    from app.models.models import UserEnvelopeKeyword
    from sqlalchemy import select as _sel
    keywords = extract_keywords(description)
    for kw in keywords:
        res = await db.execute(
            _sel(UserEnvelopeKeyword).where(
                UserEnvelopeKeyword.user_id == user_id,
                UserEnvelopeKeyword.keyword == kw,
                UserEnvelopeKeyword.envelope_id == envelope_id,
            )
        )
        existing = res.scalar_one_or_none()
        if existing:
            existing.count += 1
        else:
            db.add(UserEnvelopeKeyword(user_id=user_id, keyword=kw, envelope_id=envelope_id))


async def find_best_envelope(description, household_id, db, user_id=None):
    result = await db.execute(
        select(Envelope).where(
            Envelope.household_id == household_id, Envelope.is_active == True,
        )
    )
    envelopes = result.scalars().all()
    if not envelopes:
        return None, False

    env_by_id = {str(e.id): e for e in envelopes}

    # 0. Learned keywords — highest score wins
    if user_id:
        from app.models.models import UserEnvelopeKeyword
        keywords = extract_keywords(description)
        if keywords:
            scores = {}
            for kw in keywords:
                kw_res = await db.execute(
                    select(UserEnvelopeKeyword).where(
                        UserEnvelopeKeyword.user_id == user_id,
                        UserEnvelopeKeyword.keyword == kw,
                    )
                )
                for row in kw_res.scalars().all():
                    eid = str(row.envelope_id)
                    if eid in env_by_id:
                        scores[eid] = scores.get(eid, 0) + row.count
            if scores:
                best_id = max(scores, key=lambda x: scores[x])
                return env_by_id[best_id], True

    guessed_name = guess_envelope_name(description)

    # 1. Exact match on guessed category name
    if guessed_name:
        for env in envelopes:
            if env.name.lower() == guessed_name.lower():
                return env, True

    # 2. Partial match — confident=False because partial matches are ambiguous
    if guessed_name:
        g = guessed_name.lower()
        for env in envelopes:
            e = env.name.lower()
            if g in e or e in g:
                return env, False

    # 3. Envelope name appears directly in description
    desc_lower = description.lower()
    for env in envelopes:
        if env.name.lower() in desc_lower:
            return env, True

    return None, False
```

- [ ] **Step 2: Remove the moved definitions from handlers.py and import them back**

In `app/bot/handlers.py`, DELETE the now-duplicated definitions: `STOPWORDS` (the `STOPWORDS = {...}` block), `CATEGORY_KEYWORDS` (the `CATEGORY_KEYWORDS = {...}` block), and the functions `extract_keywords`, `save_learned_keywords`, `guess_envelope_name`, and `find_best_envelope`. Leave everything else (including `AMOUNT_ANYWHERE`, `MULTIPLIERS`, `SUB_*`, `parse_amount`, `parse_subscription`, `format_currency`, etc.) untouched.

Then add this import near the other `from app.services...` imports (e.g. just after the `from app.services.behavior import ...` line):

```python
from app.services.txn_nlp import (
    STOPWORDS, CATEGORY_KEYWORDS, extract_keywords, guess_envelope_name,
    save_learned_keywords, find_best_envelope,
)
```

(Importing the names back keeps every existing reference in `handlers.py` — and any module that does `from app.bot.handlers import find_best_envelope` — working unchanged.)

- [ ] **Step 3: Validate compile**

Run: `python -m py_compile app/services/txn_nlp.py app/bot/handlers.py`
Expected: no output (success).

- [ ] **Step 4: Run the full backend suite (no regressions)**

Run: `python -m unittest discover -s app/tests -v`
Expected: `OK` (26 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/txn_nlp.py app/bot/handlers.py
git commit -m "refactor(nlp): extract shared txn classification into app/services/txn_nlp"
```

---

## Task 2: Unit tests for the pure helpers

**Files:**
- Create: `app/tests/test_txn_nlp.py`

**Interfaces:**
- Consumes: `extract_keywords`, `guess_envelope_name` from `app.services.txn_nlp`.

- [ ] **Step 1: Write the tests**

Create `app/tests/test_txn_nlp.py`:

```python
"""Tests for pure helpers in app/services/txn_nlp.py.

Run from repo root:  python -m unittest app.tests.test_txn_nlp
"""
import unittest

from app.services.txn_nlp import extract_keywords, guess_envelope_name


class TestExtractKeywords(unittest.TestCase):
    def test_drops_short_words_stopwords_and_punctuation(self):
        kws = extract_keywords("beli kopi di starbucks!")
        # 'beli' and 'di' are stopwords; punctuation stripped
        self.assertIn("kopi", kws)
        self.assertIn("starbucks", kws)
        self.assertNotIn("di", kws)
        self.assertNotIn("beli", kws)

    def test_appends_full_phrase(self):
        kws = extract_keywords("nasi padang")
        self.assertIn("nasi", kws)
        self.assertIn("padang", kws)
        self.assertIn("nasi padang", kws)


class TestGuessEnvelopeName(unittest.TestCase):
    def test_food_keyword(self):
        self.assertEqual(guess_envelope_name("kopi pagi"), "makan")

    def test_transport_keyword(self):
        self.assertEqual(guess_envelope_name("gojek ke kantor"), "transport")

    def test_no_match_returns_none(self):
        self.assertIsNone(guess_envelope_name("xyzzy qwerty"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests**

Run: `python -m unittest app.tests.test_txn_nlp -v`
Expected: PASS (5 tests OK).

- [ ] **Step 3: Run the full suite**

Run: `python -m unittest discover -s app/tests -v`
Expected: `OK` (31 tests now).

- [ ] **Step 4: Commit**

```bash
git add app/tests/test_txn_nlp.py
git commit -m "test(nlp): unit tests for extract_keywords and guess_envelope_name"
```

---

## Task 3: suggest-envelope endpoint + web learning hook

**Files:**
- Modify: `app/api/routes/transactions.py`

**Interfaces:**
- Consumes: `find_best_envelope`, `save_learned_keywords` from `app.services.txn_nlp`.
- Produces: `POST /transactions/suggest-envelope` `{description}` → `{envelope_id: UUID|null, envelope_name: str|null, confident: bool}`.

- [ ] **Step 1: Add the suggest request schema**

In `app/api/routes/transactions.py`, add after the `TransactionResponse` class:

```python
class SuggestEnvelopeRequest(BaseModel):
    description: str
```

- [ ] **Step 2: Add the suggest endpoint**

Add after the `create_transaction` function (before `list_transactions`):

```python
@router.post("/suggest-envelope")
async def suggest_envelope(
    req: SuggestEnvelopeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.txn_nlp import find_best_envelope
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()
    if not hid or not req.description.strip():
        return {"envelope_id": None, "envelope_name": None, "confident": False}
    envelope, confident = await find_best_envelope(req.description, hid, db, user.id)
    if not envelope:
        return {"envelope_id": None, "envelope_name": None, "confident": False}
    return {"envelope_id": str(envelope.id), "envelope_name": envelope.name, "confident": bool(confident)}
```

- [ ] **Step 3: Add the best-effort learning hook in create_transaction**

In `create_transaction`, immediately after the existing best-effort streak block (the `try: ... record_activity ... except Exception: pass`) and before `return txn`, add:

```python
    # Best-effort: learn keyword -> envelope from this transaction so web input
    # enriches the same per-user learning the bot uses. Never block the txn.
    try:
        from app.services.txn_nlp import save_learned_keywords
        await save_learned_keywords(user.id, req.description, req.envelope_id, db)
        await db.commit()
    except Exception:
        pass
```

- [ ] **Step 4: Validate compile + suite**

Run: `python -m py_compile app/api/routes/transactions.py`
Run: `python -m unittest discover -s app/tests -v`
Expected: compile clean; suite `OK` (31 tests).

- [ ] **Step 5: Commit**

```bash
git add app/api/routes/transactions.py
git commit -m "feat(transactions): suggest-envelope endpoint + best-effort web learning"
```

---

## Task 4: Frontend API client method

**Files:**
- Modify: `frontend/src/lib/api.js`

**Interfaces:**
- Produces: `api.suggestEnvelope(description)` → parsed JSON `{envelope_id, envelope_name, confident}` or `null` on failure/offline.

- [ ] **Step 1: Add the method**

In `frontend/src/lib/api.js`, add this method immediately after `createTransaction` (search for `async createTransaction`). If unsure of the exact location, add it next to the other transaction methods:

```javascript
  async suggestEnvelope(description) {
    try {
      const res = await this.request('/transactions/suggest-envelope', {
        method: 'POST',
        body: JSON.stringify({ description }),
      });
      if (res.ok) return res.json();
    } catch {}
    return null;
  }
```

- [ ] **Step 2: Validate build**

Run: `cd "Z:/jatahku.com-v3/jatahku/frontend" && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat(api): suggestEnvelope client method"
```

---

## Task 5: QuickAddTransaction component

**Files:**
- Create: `frontend/src/components/QuickAddTransaction.jsx`

**Interfaces:**
- Consumes: `api.getEnvelopes`, `api.suggestEnvelope`, `api.createTransaction`; `enqueueTransaction` from `../lib/offlineQueue`.
- Produces: default-exported `<QuickAddTransaction onSaved={fn} onCancel={fn} />`. Dispatches `window` `CustomEvent('jatahku:txn-added')` on successful save.

- [ ] **Step 1: Create the component**

Create `frontend/src/components/QuickAddTransaction.jsx`:

```jsx
import { useState, useEffect, useRef } from 'react';
import { api } from '../lib/api';
import { enqueueTransaction } from '../lib/offlineQueue';

export default function QuickAddTransaction({ onSaved, onCancel }) {
  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [envelopeId, setEnvelopeId] = useState('');
  const [envelopes, setEnvelopes] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [suggested, setSuggested] = useState(false);
  const userTouchedRef = useRef(false);
  const debounceRef = useRef(null);

  useEffect(() => { api.getEnvelopes().then(setEnvelopes); }, []);

  // Debounced envelope suggestion as the user types the description.
  useEffect(() => {
    if (userTouchedRef.current) return;
    const desc = description.trim();
    if (desc.length < 2) return;
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      const res = await api.suggestEnvelope(desc);
      if (res && res.confident && res.envelope_id && !userTouchedRef.current) {
        setEnvelopeId(res.envelope_id);
        setSuggested(true);
      }
    }, 400);
    return () => clearTimeout(debounceRef.current);
  }, [description]);

  const handleDescChange = (e) => {
    const v = e.target.value;
    setDescription(v);
    if (v.trim().length === 0) { userTouchedRef.current = false; setSuggested(false); }
  };

  const handleEnvelopeChange = (e) => {
    userTouchedRef.current = true;
    setSuggested(false);
    setEnvelopeId(e.target.value);
  };

  const reset = () => {
    setAmount(''); setDescription(''); setEnvelopeId('');
    setSuggested(false); userTouchedRef.current = false; setError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!envelopeId || !amount || Number(amount) <= 0) { setError('Lengkapi jumlah & amplop'); return; }
    setSaving(true); setError('');
    const payload = { envelope_id: envelopeId, amount: Number(amount), description, source: 'webapp' };

    if (!navigator.onLine) {
      await enqueueTransaction(payload);
      setSaving(false);
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      reset();
      onSaved?.();
      return;
    }

    const result = await api.createTransaction(payload);
    setSaving(false);
    if (result.ok) {
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      reset();
      onSaved?.();
    } else {
      setError(result.data?.detail || 'Gagal menyimpan transaksi');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div>
          <label className="label">Jumlah (Rp)</label>
          <input type="number" className="input font-mono" placeholder="35000" value={amount} onChange={e => setAmount(e.target.value)} required min="1" />
        </div>
        <div>
          <label className="label">Keterangan</label>
          <input type="text" className="input" placeholder="Starbucks, Gojek..." value={description} onChange={handleDescChange} required />
        </div>
        <div>
          <label className="label">Amplop {suggested && <span className="text-xs text-brand-600">· disarankan</span>}</label>
          <select className="input" value={envelopeId} onChange={handleEnvelopeChange} required>
            <option value="">Pilih amplop</option>
            {envelopes.map(env => (<option key={env.id} value={env.id}>{env.emoji} {env.name}</option>))}
          </select>
        </div>
        <div className="flex items-end gap-2">
          <button type="submit" disabled={saving} className="btn-primary flex-1 disabled:opacity-50">{saving ? '...' : 'Simpan'}</button>
          {onCancel && <button type="button" onClick={onCancel} className="btn-outline">Batal</button>}
        </div>
      </div>
      {error && <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>{error}</div>}
    </form>
  );
}
```

- [ ] **Step 2: Validate build**

Run: `cd "Z:/jatahku.com-v3/jatahku/frontend" && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/QuickAddTransaction.jsx
git commit -m "feat(ui): reusable QuickAddTransaction with debounced envelope auto-select"
```

---

## Task 6: Use QuickAddTransaction in the Transaksi page

**Files:**
- Modify: `frontend/src/pages/Transactions.jsx`

**Interfaces:**
- Consumes: `QuickAddTransaction` (Task 5); the `jatahku:txn-added` event.

- [ ] **Step 1: Import the component**

At the top of `frontend/src/pages/Transactions.jsx`, add:

```javascript
import QuickAddTransaction from '../components/QuickAddTransaction';
```

- [ ] **Step 2: Add a refresh tick + listener for the global event**

Add a `refreshTick` state next to the other `useState` hooks:

```javascript
  const [refreshTick, setRefreshTick] = useState(0);
```

Add this effect (near the other effects):

```javascript
  useEffect(() => {
    const onAdded = () => setRefreshTick(t => t + 1);
    window.addEventListener('jatahku:txn-added', onAdded);
    return () => window.removeEventListener('jatahku:txn-added', onAdded);
  }, []);
```

Add `refreshTick` to the load effect's dependency array — change `useEffect(load, [filter, periodIdx, periods]);` to:

```javascript
  useEffect(load, [filter, periodIdx, periods, refreshTick]);
```

- [ ] **Step 3: Replace the inline add form with the component**

Replace the entire `{showAdd && ( ... )}` block (the card containing the `<form onSubmit={handleAdd}>`) with:

```javascript
      {showAdd && (
        <div className="card border-brand-200">
          <QuickAddTransaction
            onSaved={() => { setShowAdd(false); load(); }}
            onCancel={() => setShowAdd(false)}
          />
        </div>
      )}
```

- [ ] **Step 4: Remove the now-unused add-form code**

Delete the now-unused pieces: the `handleAdd` function, and the state hooks `amount`, `description`, `envelopeId`, `saving`, `addError` (they were only used by the old inline form). Leave `showAdd`, the offline-sync `flushQueue`/`getPendingCount` logic, `pendingCount`, and everything else intact. If the build complains about an unused import, remove only the unused symbol.

- [ ] **Step 5: Validate build**

Run: `cd "Z:/jatahku.com-v3/jatahku/frontend" && npm run build`
Expected: build succeeds (no "X is not defined" errors — confirms all removed symbols are truly unused).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Transactions.jsx
git commit -m "feat(transactions): use shared QuickAddTransaction + refresh on txn-added"
```

---

## Task 7: Global quick-add FAB in Layout

**Files:**
- Modify: `frontend/src/components/Layout.jsx`

**Interfaces:**
- Consumes: `QuickAddTransaction` (Task 5).

- [ ] **Step 1: Import the component**

At the top of `frontend/src/components/Layout.jsx`, add:

```javascript
import QuickAddTransaction from './QuickAddTransaction';
```

- [ ] **Step 2: Add FAB open state**

Add next to the other `useState` hooks in `Layout`:

```javascript
  const [fabOpen, setFabOpen] = useState(false);
```

- [ ] **Step 3: Render the FAB + modal**

Inside the outer `<div className="min-h-screen bg-page">`, just before the closing `</div>` of that wrapper (after the `<main>...</main>` line), add:

```javascript
      {/* Global quick-add FAB (every page) */}
      <button
        onClick={() => setFabOpen(true)}
        className="fixed bottom-20 right-4 md:bottom-6 md:right-6 z-40 w-14 h-14 rounded-full bg-brand-600 text-white text-3xl leading-none shadow-lg flex items-center justify-center hover:bg-brand-700 transition-colors"
        title="Catat pengeluaran"
      >+</button>
      {fabOpen && (
        <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={() => setFabOpen(false)}>
          <div className="bg-white rounded-2xl w-full max-w-2xl p-6 shadow-xl" onClick={e => e.stopPropagation()}>
            <h3 className="font-display font-bold text-lg mb-4">💰 Catat pengeluaran</h3>
            <QuickAddTransaction onSaved={() => setFabOpen(false)} onCancel={() => setFabOpen(false)} />
          </div>
        </div>
      )}
```

- [ ] **Step 4: Validate build**

Run: `cd "Z:/jatahku.com-v3/jatahku/frontend" && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout.jsx
git commit -m "feat(layout): global quick-add FAB on every page"
```

---

## Task 8: Refresh Dashboard and Envelopes on txn-added

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`
- Modify: `frontend/src/pages/Envelopes.jsx`

**Interfaces:**
- Consumes: the `jatahku:txn-added` event.

- [ ] **Step 1: Dashboard — add refresh tick + listener**

In `frontend/src/pages/Dashboard.jsx`, add a `refreshTick` state next to the other `useState` hooks:

```javascript
  const [refreshTick, setRefreshTick] = useState(0);
```

Add a listener effect (near the mount effect):

```javascript
  useEffect(() => {
    const onAdded = () => setRefreshTick(t => t + 1);
    window.addEventListener('jatahku:txn-added', onAdded);
    return () => window.removeEventListener('jatahku:txn-added', onAdded);
  }, []);
```

Add `refreshTick` to the period-data reload effect's dependency array — change `}, [periodIdx, periods]);` (the effect that fetches `getEnvelopeSummary`/`getTransactions`/`getDailySpending`/`getEnvelopeBreakdown`) to:

```javascript
  }, [periodIdx, periods, refreshTick]);
```

- [ ] **Step 2: Envelopes — add refresh tick + listener**

In `frontend/src/pages/Envelopes.jsx`, add a `refreshTick` state next to the other `useState` hooks:

```javascript
  const [refreshTick, setRefreshTick] = useState(0);
```

Add a listener effect:

```javascript
  useEffect(() => {
    const onAdded = () => setRefreshTick(t => t + 1);
    window.addEventListener('jatahku:txn-added', onAdded);
    return () => window.removeEventListener('jatahku:txn-added', onAdded);
  }, []);
```

Change `useEffect(load, []);` to:

```javascript
  useEffect(load, [refreshTick]);
```

- [ ] **Step 3: Validate build**

Run: `cd "Z:/jatahku.com-v3/jatahku/frontend" && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Dashboard.jsx frontend/src/pages/Envelopes.jsx
git commit -m "feat(ui): refresh Dashboard and Envelopes on jatahku:txn-added"
```

---

## Task 9: Verification, manual smoke, finish branch

**Files:**
- Update this plan as steps pass.

- [ ] **Step 1: Full backend suite**

Run: `python -m unittest discover -s app/tests -v`
Expected: `OK` (31 tests).

- [ ] **Step 2: Frontend build**

Run: `cd "Z:/jatahku.com-v3/jatahku/frontend" && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Review diff**

Run `git diff main...feat/smart-quick-add --stat` and confirm only intended files changed and `frontend/dist/` is not staged.

- [ ] **Step 4: Manual smoke test**

With a logged-in user:
- Open the FAB from the Dashboard; type "kopi" in Keterangan; confirm the Amplop auto-selects a food envelope with a "disarankan" hint; type an amount; save; confirm the Dashboard balances refresh.
- On the Transaksi page, add via the form; change the suggested envelope manually and confirm auto-select stops; save and confirm the list updates.
- Save a transaction with a new word, then add another with the same word and confirm it now auto-selects (learning works).
- Confirm the Telegram bot still classifies expenses correctly (behavior unchanged after extraction).

- [ ] **Step 5: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill. Merging to `main` triggers auto-deploy; the PWA cache is versioned per build.

---

## Known Dirty Files When Plan Was Created

Do not revert or overwrite these unless the user explicitly asks:

- `docs/superpowers/plans/2026-04-17-whatsapp-integration.md`
- `frontend/dist/` (build artifacts)
- `landing.html`
- `.superpowers/`, `AGENTS.md`, `temporary_file/`
