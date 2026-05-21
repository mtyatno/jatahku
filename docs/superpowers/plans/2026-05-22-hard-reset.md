# Hard Reset Data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Reset Semua Data" feature that wipes all financial data (envelopes, transactions, allocations, incomes, recurring) while preserving account settings and pro status, with email backup before deletion.

**Architecture:** New `POST /user/reset` endpoint in `user_settings.py` collects export data, sends JSON backup email (via a new `send_data_backup_email` in `email_service.py`), then hard-deletes all financial records in FK-safe order within one DB transaction. Frontend adds a multi-step `HardResetDialog` component and a "Zona Berbahaya" section in Settings.

**Tech Stack:** FastAPI + SQLAlchemy (async) + PostgreSQL, React + Vite, SMTP via `email_service.py`

---

## File Map

| File | Change |
|---|---|
| `app/services/email_service.py` | Add `send_data_backup_email()` with JSON attachment |
| `app/api/routes/user_settings.py` | Add `ResetDataRequest` model + `POST /user/reset` endpoint |
| `frontend/src/lib/api.js` | Add `resetData(email?)` method |
| `frontend/src/pages/Settings.jsx` | Add `HardResetDialog` component + state + Zona Berbahaya section |

---

## Task 1: email_service.py — add `send_data_backup_email`

**Files:**
- Modify: `app/services/email_service.py`

- [ ] **Step 1: Add import at the top of the file**

At the top of `app/services/email_service.py`, after the existing imports, add:

```python
import json as _json
from email.mime.application import MIMEApplication
```

- [ ] **Step 2: Add the function at the bottom of the file**

Append this function after `send_subscription_due_email`:

```python
def send_data_backup_email(to_email: str, name: str, data: dict, filename: str) -> bool:
    """Send backup JSON as attachment before a data reset."""
    try:
        msg = MIMEMultipart("mixed")
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM}>"
        msg["To"] = to_email
        msg["Subject"] = "Backup data Jatahku kamu sebelum reset"
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="jatahku.com")

        html_body = email_template(
            "Backup data kamu tersedia",
            f"""<p>Hai {name},</p>
            <p>Data Jatahku kamu terlampir sebagai file <strong>{filename}</strong>.</p>
            <p>Ini adalah salinan lengkap semua data kamu sebelum reset dilakukan.
            Simpan sebagai referensi jika sewaktu-waktu diperlukan.</p>""",
        )
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(f"Backup data Jatahku kamu terlampir: {filename}", "plain"))
        body_part.attach(MIMEText(html_body, "html"))
        msg.attach(body_part)

        json_bytes = _json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        attachment = MIMEApplication(json_bytes, _subtype="json")
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(attachment)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())

        logger.info(f"Backup email sent to {to_email}: {filename}")
        return True
    except Exception as e:
        logger.error(f"Backup email failed to {to_email}: {e}")
        return False
```

- [ ] **Step 3: Commit**

```bash
git add app/services/email_service.py
git commit -m "feat: add send_data_backup_email with JSON attachment"
```

---

## Task 2: user_settings.py — add `POST /user/reset`

**Files:**
- Modify: `app/api/routes/user_settings.py`

The endpoint collects export data, emails backup, then hard-deletes in FK-safe order:
`PendingTransaction` → `Transaction` → `Allocation` → `Goal` → `MonthlySnapshot` → `RecurringTransaction` → `UserEnvelopeKeyword` → `Envelope` → `Income` → `EnvelopeGroup`

- [ ] **Step 1: Update the imports block at the top of the file**

Replace the existing `from app.models.models import (...)` block with:

```python
from app.models.models import (
    User, Envelope, Transaction, Allocation, Income,
    RecurringTransaction, Notification, NotificationPreference,
    HouseholdMember, Household,
    Goal, MonthlySnapshot, PendingTransaction, EnvelopeGroup, UserEnvelopeKeyword,
)
```

Also add `delete` to the sqlalchemy import line (it already has `select, func, update`):

```python
from sqlalchemy import select, func, update, delete
```

- [ ] **Step 2: Add the request model after the existing `DefaultBehavior` model**

```python
class ResetDataRequest(BaseModel):
    email: str | None = None  # only provided if user has no email yet
```

- [ ] **Step 3: Add the endpoint at the bottom of the file**

```python
@router.post("/reset")
async def reset_data(
    req: ResetDataRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import date as _date
    from app.services.email_service import send_data_backup_email

    # Save new email if provided (user had no email before)
    if req.email:
        existing = await db.execute(
            select(User).where(User.email == req.email, User.id != user.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Email sudah digunakan")
        user.email = req.email
        await db.flush()

    # Resolve household id
    hid_result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = hid_result.scalar_one_or_none()

    # Collect envelope ids
    env_ids: list = []
    if hid:
        env_ids_result = await db.execute(
            select(Envelope.id).where(Envelope.household_id == hid)
        )
        env_ids = [row[0] for row in env_ids_result.all()]

    # --- Build export payload ---
    envelopes_data = []
    if env_ids:
        env_result = await db.execute(select(Envelope).where(Envelope.id.in_(env_ids)))
        envelopes_data = [
            {"name": e.name, "emoji": e.emoji, "budget": str(e.budget_amount)}
            for e in env_result.scalars().all()
        ]

    txn_result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user.id, Transaction.is_deleted == False)
        .order_by(Transaction.created_at)
    )
    transactions_data = [
        {"date": str(t.transaction_date), "amount": str(t.amount), "description": t.description}
        for t in txn_result.scalars().all()
    ]

    inc_result = await db.execute(
        select(Income).where(Income.user_id == user.id).order_by(Income.created_at)
    )
    incomes_data = [
        {"date": str(i.income_date), "amount": str(i.amount), "description": i.description}
        for i in inc_result.scalars().all()
    ]

    recurring_data = []
    if env_ids:
        rec_result = await db.execute(
            select(RecurringTransaction)
            .where(RecurringTransaction.envelope_id.in_(env_ids))
        )
        recurring_data = [
            {"description": r.description, "amount": str(r.amount), "frequency": r.frequency.value}
            for r in rec_result.scalars().all()
        ]

    export = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {"name": user.name, "email": user.email},
        "envelopes": envelopes_data,
        "transactions": transactions_data,
        "incomes": incomes_data,
        "recurring": recurring_data,
    }

    # --- Send backup email (non-blocking: reset proceeds even if email fails) ---
    email_sent = False
    if user.email:
        filename = f"jatahku-backup-{_date.today().isoformat()}.json"
        email_sent = send_data_backup_email(user.email, user.name, export, filename)

    # --- Hard delete in FK-safe order ---
    if env_ids:
        await db.execute(delete(PendingTransaction).where(PendingTransaction.envelope_id.in_(env_ids)))
        await db.execute(delete(Transaction).where(Transaction.envelope_id.in_(env_ids)))
        await db.execute(delete(Allocation).where(Allocation.envelope_id.in_(env_ids)))
        await db.execute(delete(Goal).where(Goal.envelope_id.in_(env_ids)))
        await db.execute(delete(MonthlySnapshot).where(MonthlySnapshot.envelope_id.in_(env_ids)))
        await db.execute(delete(RecurringTransaction).where(RecurringTransaction.envelope_id.in_(env_ids)))
        await db.execute(delete(UserEnvelopeKeyword).where(UserEnvelopeKeyword.envelope_id.in_(env_ids)))
        await db.execute(delete(Envelope).where(Envelope.id.in_(env_ids)))

    await db.execute(delete(Income).where(Income.user_id == user.id))

    if hid:
        await db.execute(delete(EnvelopeGroup).where(EnvelopeGroup.household_id == hid))

    await db.commit()
    return {"success": True, "email_sent": email_sent}
```

- [ ] **Step 4: Smoke-test the endpoint via curl (on dev or VPS)**

```bash
# Get a token first
TOKEN=$(curl -s -X POST https://api.jatahku.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"<your-test-email>","password":"<your-password>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Call reset (dry run with a test account that has no important data)
curl -s -X POST https://api.jatahku.com/user/reset \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool
```

Expected response:
```json
{
  "success": true,
  "email_sent": true
}
```
or `"email_sent": false` if no email on account.

- [ ] **Step 5: Commit**

```bash
git add app/api/routes/user_settings.py
git commit -m "feat: add POST /user/reset endpoint with backup email + hard delete"
```

---

## Task 3: api.js — add `resetData` method

**Files:**
- Modify: `frontend/src/lib/api.js`

- [ ] **Step 1: Add the method inside the ApiClient class**

Find the last method in the `ApiClient` class (look for the closing `}` of the class) and add before it:

```javascript
async resetData(email = null) {
  const body = email ? { email } : {};
  return this.request('/user/reset', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat: add api.resetData() method"
```

---

## Task 4: Settings.jsx — HardResetDialog + Zona Berbahaya

**Files:**
- Modify: `frontend/src/pages/Settings.jsx`

- [ ] **Step 1: Add `showReset` state to the Settings component**

In the Settings component, find the existing state declarations (near the `showDelete` state) and add:

```javascript
const [showReset, setShowReset] = useState(false);
```

- [ ] **Step 2: Add the `HardResetDialog` component**

Add this new component function above the `export default function Settings()` line:

```javascript
function HardResetDialog({ profile, members, onClose, onSuccess }) {
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState('');
  const [confirmText, setConfirmText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const hasEmail = !!profile.email;
  const hasHousehold = members.length > 1;

  const goToConfirm = () => {
    if (!hasEmail) {
      if (!email || !email.includes('@')) { setError('Masukkan email yang valid'); return; }
      setError('');
    }
    setStep(3);
  };

  const handleReset = async () => {
    if (confirmText !== 'RESET') return;
    setLoading(true);
    try {
      const res = await api.resetData(!hasEmail ? email : null);
      const data = await res.json();
      if (res.ok) {
        onSuccess(data.email_sent, profile.email || email);
      } else {
        setError(data.detail || 'Gagal reset data');
      }
    } catch {
      setError('Terjadi kesalahan jaringan');
    }
    setLoading(false);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-xl">

        {step === 1 && (
          <>
            <h3 className="text-lg font-semibold text-red-600">⚠️ Reset Semua Data?</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">Data berikut akan dihapus permanen dan tidak bisa dikembalikan:</p>
            <ul className="text-sm text-gray-600 dark:text-gray-400 space-y-1 list-disc list-inside">
              <li>Semua amplop</li>
              <li>Semua transaksi</li>
              <li>Semua alokasi</li>
              <li>Semua catatan pemasukan</li>
              <li>Semua langganan & recurring</li>
            </ul>
            {hasHousehold && (
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-sm text-amber-700">
                <strong>Perhatian:</strong> Kamu adalah anggota household. Amplop yang kamu share dengan anggota lain juga akan terdampak.
              </div>
            )}
            <p className="text-xs text-gray-400">Setting akun (payday, timezone, notifikasi, status Pro) tidak akan dihapus.</p>
            <div className="flex gap-2 pt-2">
              <button
                onClick={() => hasEmail ? setStep(3) : setStep(2)}
                className="flex-1 px-4 py-2 bg-red-500 text-white text-sm font-medium rounded-xl hover:bg-red-600 transition-colors"
              >
                Lanjutkan
              </button>
              <button onClick={onClose} className="px-4 py-2 text-sm text-gray-500 border border-gray-200 rounded-xl hover:bg-gray-50">
                Batal
              </button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h3 className="text-lg font-semibold">📧 Email untuk backup</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Data kamu akan di-backup dan dikirim ke email ini sebelum dihapus. Email juga akan disimpan ke akun kamu.
            </p>
            <input
              type="email"
              className="input text-sm w-full"
              placeholder="email@kamu.com"
              value={email}
              onChange={e => { setEmail(e.target.value); setError(''); }}
              autoFocus
            />
            {error && <p className="text-xs text-red-500">{error}</p>}
            <div className="flex gap-2 pt-2">
              <button
                onClick={goToConfirm}
                disabled={!email}
                className="flex-1 px-4 py-2 bg-red-500 text-white text-sm font-medium rounded-xl hover:bg-red-600 disabled:opacity-50 transition-colors"
              >
                Lanjutkan
              </button>
              <button onClick={() => setStep(1)} className="px-4 py-2 text-sm text-gray-500 border border-gray-200 rounded-xl hover:bg-gray-50">
                Kembali
              </button>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <h3 className="text-lg font-semibold text-red-600">🔴 Konfirmasi Reset</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Ketik <strong className="font-mono">RESET</strong> untuk melanjutkan. Tindakan ini tidak bisa dibatalkan.
            </p>
            <input
              className="input text-sm w-full font-mono tracking-widest"
              placeholder="ketik RESET untuk melanjutkan"
              value={confirmText}
              onChange={e => { setConfirmText(e.target.value); setError(''); }}
              autoFocus
            />
            {error && <p className="text-xs text-red-500">{error}</p>}
            <div className="flex gap-2 pt-2">
              <button
                onClick={handleReset}
                disabled={confirmText !== 'RESET' || loading}
                className="flex-1 px-4 py-2 bg-red-500 text-white text-sm font-medium rounded-xl hover:bg-red-600 disabled:opacity-50 transition-colors"
              >
                {loading ? 'Mereset...' : 'Reset Sekarang'}
              </button>
              <button
                onClick={() => { hasEmail ? setStep(1) : setStep(2); setConfirmText(''); setError(''); }}
                disabled={loading}
                className="px-4 py-2 text-sm text-gray-500 border border-gray-200 rounded-xl hover:bg-gray-50"
              >
                Kembali
              </button>
            </div>
          </>
        )}

      </div>
    </div>
  );
}
```

- [ ] **Step 3: Add `onResetSuccess` handler in the Settings component**

Inside the `Settings` component function body (after the existing `logoutAll` function), add:

```javascript
const onResetSuccess = (emailSent, emailAddr) => {
  setShowReset(false);
  const msg = emailSent
    ? `Data berhasil direset. Backup dikirim ke ${emailAddr}.`
    : 'Data berhasil direset. (Backup tidak berhasil dikirim)';
  flash(msg, 'global');
  setTimeout(() => navigate('/envelopes'), 2000);
};
```

- [ ] **Step 4: Add the Zona Berbahaya section in the JSX**

Find the Logout card (the last `<div className="card">` containing the Logout button) and add this new section **before** it:

```jsx
{/* Zona Berbahaya */}
<div className="card border border-red-200 bg-red-50 dark:bg-red-950/20 dark:border-red-900">
  <h3 className="font-semibold text-sm text-red-600 mb-1">⚠️ Zona Berbahaya</h3>
  <div className="flex items-center justify-between">
    <div>
      <p className="text-sm">Reset Semua Data</p>
      <p className="text-xs text-gray-400">Hapus semua amplop, transaksi, dan data finansial. Tidak bisa dibatalkan.</p>
    </div>
    <button
      onClick={() => setShowReset(true)}
      className="text-sm text-red-400 border border-red-200 rounded-xl px-3 py-1.5 hover:bg-red-50 hover:text-red-600 hover:border-red-400 transition-all whitespace-nowrap ml-4"
    >
      Reset data
    </button>
  </div>
</div>
```

- [ ] **Step 5: Render the dialog at the bottom of the JSX return**

Inside the main `return (...)` of the Settings component, just before the closing `</div>` of the root element, add:

```jsx
{showReset && (
  <HardResetDialog
    profile={profile}
    members={members}
    onClose={() => setShowReset(false)}
    onSuccess={onResetSuccess}
  />
)}
```

- [ ] **Step 6: Build frontend and verify in browser**

```bash
cd frontend && npm run build
```

Open `http://localhost:5173/settings` (or the dev server), scroll to the bottom of Settings, and verify:
1. "Zona Berbahaya" section with red border appears above Logout
2. Clicking "Reset data" opens the dialog
3. Step 1 shows warning list + household warning (if applicable)
4. Step 2 (email input) appears only if account has no email
5. Step 3 shows type-to-confirm; "Reset Sekarang" button is disabled until "RESET" is typed exactly
6. After reset: toast appears and page redirects to /envelopes after 2 seconds

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Settings.jsx
git commit -m "feat: add HardResetDialog and Zona Berbahaya section in Settings"
```

---

## Deploy

```bash
git push origin main
# GitHub Actions will build and deploy automatically
# Monitor at: https://github.com/mtyatno/jatahku/actions
```
