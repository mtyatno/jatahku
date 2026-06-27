# Custom Envelope Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users organize envelopes into custom groups (e.g. "Tabungan", "Expense") on the Amplop page, with each group header showing the total balance of its envelopes.

**Architecture:** Add envelope-group CRUD endpoints to the existing envelopes router and surface `group_id`/`group_name` in the envelope summary. The Amplop page renders a two-level hierarchy: ownership section (Shared/Personal) → custom group → envelope cards, with a balance subtotal per group computed on the frontend. Group assignment happens through the existing create/edit envelope modal.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, React/Vite, Tailwind CSS. Backend tests use stdlib `unittest`; frontend validation uses `npm run build`.

## Global Constraints

- **No DB migration:** `envelope_groups` table and `envelopes.group_id` already exist in the initial schema (`0f8fa68ae7b7_initial_schema.py`). Do not add a migration.
- **Group total metric = balance:** `allocated + rollover - spent` (the summary's `remaining`), summed per group within a section.
- **Backward compatible:** a section with no grouped envelopes renders flat (no sub-headers), exactly like today.
- **Groups are household-level** (the `EnvelopeGroup` model is keyed by `household_id`).
- **Scope = Amplop page only.** Do not touch Dashboard or Allocate.
- **Do not commit `frontend/dist/`.**
- **Testing reality:** the project has no DB-integration test client and no JS test runner. Backend routes are validated by `py_compile` + the full `unittest` suite still passing + manual smoke (same pattern as the advisor feature). Frontend is validated by `npm run build` + manual smoke. Do not add new test frameworks.
- Work happens on branch `feat/envelope-groups` (already created; the spec is committed there).

---

## Task 1: Backend — envelope group CRUD endpoints

**Files:**
- Modify: `app/api/routes/envelopes.py`

**Interfaces:**
- Produces: `GET /envelopes/groups`, `POST /envelopes/groups` `{name}`, `PATCH /envelopes/groups/{group_id}` `{name}`, `DELETE /envelopes/groups/{group_id}`. Group JSON shape: `{ id: UUID, name: str, sort_order: int }`.

- [ ] **Step 1: Import the EnvelopeGroup model**

In `app/api/routes/envelopes.py`, add `EnvelopeGroup` to the existing models import (lines 13-16):

```python
from app.models.models import (
    User, Envelope, EnvelopeGroup, HouseholdMember, Transaction, Allocation, MonthlySnapshot,
    RecurringTransaction, RecurringFrequency,
)
```

- [ ] **Step 2: Add group schemas**

Add after the `EnvelopeSummary` class (after line 65):

```python
class EnvelopeGroupCreate(BaseModel):
    name: str


class EnvelopeGroupResponse(BaseModel):
    id: UUID
    name: str
    sort_order: int
    model_config = {"from_attributes": True}
```

- [ ] **Step 3: Add the group CRUD endpoints**

Add immediately after the `envelope_summary` endpoint (after line 211, before `create_envelope`). Defining static `/groups` paths here keeps them clearly separate from the `/{envelope_id}` routes:

```python
@router.get("/groups", response_model=list[EnvelopeGroupResponse])
async def list_groups(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        return []
    result = await db.execute(
        select(EnvelopeGroup)
        .where(EnvelopeGroup.household_id == hid)
        .order_by(EnvelopeGroup.sort_order, EnvelopeGroup.name)
    )
    return result.scalars().all()


@router.post("/groups", response_model=EnvelopeGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    req: EnvelopeGroupCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        raise HTTPException(status_code=400, detail="Belum punya household")
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nama grup tidak boleh kosong")
    max_result = await db.execute(
        select(func.coalesce(func.max(EnvelopeGroup.sort_order), -1))
        .where(EnvelopeGroup.household_id == hid)
    )
    next_order = int(max_result.scalar()) + 1
    group = EnvelopeGroup(household_id=hid, name=name, sort_order=next_order)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


@router.patch("/groups/{group_id}", response_model=EnvelopeGroupResponse)
async def rename_group(
    group_id: UUID,
    req: EnvelopeGroupCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    result = await db.execute(
        select(EnvelopeGroup).where(EnvelopeGroup.id == group_id, EnvelopeGroup.household_id == hid)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Grup tidak ditemukan")
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nama grup tidak boleh kosong")
    group.name = name
    await db.commit()
    await db.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import update
    hid = await _get_hid(user, db)
    result = await db.execute(
        select(EnvelopeGroup).where(EnvelopeGroup.id == group_id, EnvelopeGroup.household_id == hid)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Grup tidak ditemukan")
    await db.execute(
        update(Envelope).where(Envelope.group_id == group_id).values(group_id=None)
    )
    await db.delete(group)
    await db.commit()
```

- [ ] **Step 4: Validate compile**

Run: `python -m py_compile app/api/routes/envelopes.py`
Expected: no output (success).

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `python -m unittest discover -s app/tests -v`
Expected: `OK` (26 tests, same as before — this task adds no unit tests because there is no DB test client; routes are smoke-tested manually in Task 5).

- [ ] **Step 6: Commit**

```bash
git add app/api/routes/envelopes.py
git commit -m "feat(envelopes): add envelope group CRUD endpoints"
```

---

## Task 2: Backend — expose group on the envelope summary + validate group_id

**Files:**
- Modify: `app/api/routes/envelopes.py`

**Interfaces:**
- Consumes: `EnvelopeGroup` (imported in Task 1).
- Produces: each `GET /envelopes/summary` item gains `group_id: UUID | None` and `group_name: str | None`. `POST /` and `PUT /{id}` reject a `group_id` that is not in the caller's household.

- [ ] **Step 1: Add group fields to EnvelopeSummary**

In the `EnvelopeSummary` class, add two fields after `spent_ratio` (after line 64):

```python
    spent_ratio: float      # spent / allocated
    group_id: UUID | None = None
    group_name: str | None = None
```

- [ ] **Step 2: Build a group-name lookup in envelope_summary**

In `envelope_summary`, right after `envelopes = result.scalars().all()` (line 114), add:

```python
    group_result = await db.execute(
        select(EnvelopeGroup.id, EnvelopeGroup.name).where(EnvelopeGroup.household_id == hid)
    )
    group_names = {gid: gname for gid, gname in group_result.all()}
```

- [ ] **Step 3: Populate group fields per summary**

In the `EnvelopeSummary(...)` constructor inside the loop, add the two fields (after `spent_ratio=...`, around line 208):

```python
            funded_ratio=round(funded_ratio, 4),
            spent_ratio=round(spent_ratio, 4),
            group_id=env.group_id,
            group_name=group_names.get(env.group_id),
        ))
```

- [ ] **Step 4: Validate group_id on create**

In `create_envelope`, after the `if not hid:` guard (after line 228), add:

```python
    if req.group_id is not None:
        grp_check = await db.execute(
            select(EnvelopeGroup).where(
                EnvelopeGroup.id == req.group_id, EnvelopeGroup.household_id == hid
            )
        )
        if grp_check.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Grup tidak valid")
```

- [ ] **Step 5: Validate group_id on update**

In `update_envelope`, after the `if not envelope:` guard (after line 257), add:

```python
    if req.group_id is not None:
        grp_check = await db.execute(
            select(EnvelopeGroup).where(
                EnvelopeGroup.id == req.group_id, EnvelopeGroup.household_id == hid
            )
        )
        if grp_check.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Grup tidak valid")
```

- [ ] **Step 6: Validate compile + suite**

Run: `python -m py_compile app/api/routes/envelopes.py`
Run: `python -m unittest discover -s app/tests -v`
Expected: compile clean; suite `OK`.

- [ ] **Step 7: Commit**

```bash
git add app/api/routes/envelopes.py
git commit -m "feat(envelopes): expose group_id/group_name on summary and validate group_id"
```

---

## Task 3: Frontend — API client methods for groups

**Files:**
- Modify: `frontend/src/lib/api.js`

**Interfaces:**
- Produces: `api.getEnvelopeGroups()` → array; `api.createEnvelopeGroup(name)` → `{ok, data}`; `api.renameEnvelopeGroup(id, name)` → `{ok, data}`; `api.deleteEnvelopeGroup(id)` → boolean.

- [ ] **Step 1: Add the group methods**

In `frontend/src/lib/api.js`, add these methods immediately after `deleteEnvelope` (after line 184):

```javascript
  async getEnvelopeGroups() {
    try {
      const res = await this.request('/envelopes/groups');
      if (res.ok) return res.json();
    } catch {}
    return [];
  }

  async createEnvelopeGroup(name) {
    const res = await this.request('/envelopes/groups', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
    return { ok: res.ok, data: await res.json() };
  }

  async renameEnvelopeGroup(id, name) {
    const res = await this.request(`/envelopes/groups/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
    return { ok: res.ok, data: await res.json() };
  }

  async deleteEnvelopeGroup(id) {
    const res = await this.request(`/envelopes/groups/${id}`, { method: 'DELETE' });
    return res.ok;
  }
```

- [ ] **Step 2: Validate build**

Run: `cd frontend && npm run build`
Expected: build succeeds (do not commit `frontend/dist/`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat(api): envelope group client methods"
```

---

## Task 4: Frontend — grouped Amplop layout + group control in modal

**Files:**
- Modify: `frontend/src/pages/Envelopes.jsx`

**Interfaces:**
- Consumes: `api.getEnvelopeGroups`, `api.createEnvelopeGroup`, `api.renameEnvelopeGroup`, `api.deleteEnvelopeGroup`; summary items with `group_id`/`group_name`.

- [ ] **Step 1: Add pure grouping helpers**

In `frontend/src/pages/Envelopes.jsx`, add these top-level functions just below the `EMOJIS` constant (after line 5):

```javascript
// Balance of a list of envelopes = sum of (allocated + rollover - spent)
function groupBalance(envelopes) {
  return envelopes.reduce(
    (sum, e) => sum + (Number(e.allocated || 0) + Number(e.rollover || 0) - Number(e.spent || 0)),
    0,
  );
}

// Split a section's envelopes into ordered custom groups + a trailing "Lainnya"
// bucket for ungrouped envelopes. Returns [] of { id, name, envelopes }.
function buildGroupSections(envelopes, groups) {
  const byGroup = {};
  envelopes.forEach((e) => {
    const key = e.group_id || '__none__';
    (byGroup[key] = byGroup[key] || []).push(e);
  });
  const sections = [...groups]
    .sort((a, b) => a.sort_order - b.sort_order)
    .filter((g) => byGroup[g.id]?.length)
    .map((g) => ({ id: g.id, name: g.name, envelopes: byGroup[g.id] }));
  if (byGroup['__none__']?.length) {
    sections.push({ id: null, name: 'Lainnya', envelopes: byGroup['__none__'] });
  }
  return sections;
}
```

- [ ] **Step 2: Add a section renderer component**

Add this component just above the `export default function Envelopes()` (before line 343). It renders flat when the section has no grouped envelopes, otherwise renders per-group sub-headers with balance subtotals and rename/delete actions:

```javascript
function EnvelopeSection({ title, envelopes, groups, onEdit, onDelete, onTransfer, onGroupChanged }) {
  const hasGroups = envelopes.some((e) => e.group_id);

  const renderGrid = (items) => (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {items.map((env) => (
        <EnvelopeCard key={env.id} env={env} onEdit={onEdit} onDelete={onDelete} onTransfer={onTransfer} />
      ))}
    </div>
  );

  if (!hasGroups) {
    return (
      <div>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">{title} ({envelopes.length})</h2>
        {renderGrid(envelopes)}
      </div>
    );
  }

  const sections = buildGroupSections(envelopes, groups);

  const handleRename = async (g) => {
    const next = window.prompt('Nama grup baru:', g.name);
    if (!next || !next.trim() || next.trim() === g.name) return;
    await api.renameEnvelopeGroup(g.id, next.trim());
    onGroupChanged();
  };

  const handleDeleteGroup = async (g) => {
    if (!confirm(`Hapus grup "${g.name}"? Amplop di dalamnya pindah ke Lainnya.`)) return;
    await api.deleteEnvelopeGroup(g.id);
    onGroupChanged();
  };

  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">{title} ({envelopes.length})</h2>
      <div className="space-y-5">
        {sections.map((sec) => (
          <div key={sec.id ?? '__none__'}>
            <div className="group flex items-center justify-between mb-2">
              <div className="flex items-baseline gap-2">
                <h3 className="text-sm font-semibold text-gray-600">{sec.name}</h3>
                <span className="text-xs text-gray-400">· saldo {formatCurrency(groupBalance(sec.envelopes))}</span>
              </div>
              {sec.id && (
                <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-2">
                  <button onClick={() => handleRename(sec)} className="text-xs text-gray-400 hover:text-brand-600">✏️ Rename</button>
                  <button onClick={() => handleDeleteGroup(sec)} className="text-xs text-gray-400 hover:text-danger-400">🗑 Hapus</button>
                </div>
              )}
            </div>
            {renderGrid(sec.envelopes)}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Load groups and pass them through the page**

Replace the `Envelopes` component body's state/load and the Shared/Personal render blocks. Change the state + load (lines 344-351) to:

```javascript
  const [envelopes, setEnvelopes] = useState([]);
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState(null);
  const [transferTarget, setTransferTarget] = useState(null);

  const load = () => {
    Promise.all([api.getEnvelopeSummary(), api.getEnvelopeGroups()]).then(([env, grp]) => {
      setEnvelopes(env);
      setGroups(grp);
      setLoading(false);
    });
  };
  useEffect(load, []);
```

- [ ] **Step 4: Use EnvelopeSection in the render**

Replace the two `{shared.length > 0 && (...)}` and `{personal.length > 0 && (...)}` blocks (lines 374-385) with:

```javascript
          {shared.length > 0 && (
            <EnvelopeSection title="👥 Shared" envelopes={shared} groups={groups}
              onEdit={setEditing} onDelete={handleDelete} onTransfer={setTransferTarget} onGroupChanged={load} />
          )}
          {personal.length > 0 && (
            <EnvelopeSection title="🔒 Personal" envelopes={personal} groups={groups}
              onEdit={setEditing} onDelete={handleDelete} onTransfer={setTransferTarget} onGroupChanged={load} />
          )}
```

- [ ] **Step 5: Pass groups into the modal**

Update the modal render line (line 388) to pass `groups`:

```javascript
      {(showCreate || editing) && <CreateModal editing={editing} envelopes={envelopes} groups={groups} onClose={() => { setShowCreate(false); setEditing(null); }} onCreated={load} />}
```

- [ ] **Step 6: Add the Grup control to CreateModal**

Update the `CreateModal` signature (line 7) to accept `groups`:

```javascript
function CreateModal({ onClose, onCreated, editing, envelopes: existingEnvelopes, groups = [] }) {
```

Add group state next to the other `useState` hooks (after line 17):

```javascript
  const [groupId, setGroupId] = useState(editing?.group_id || '');
  const [newGroupName, setNewGroupName] = useState('');
```

In `handleSubmit`, resolve the group id before building the payload. For the **edit** branch, replace the `data` object (lines 35-40) so it includes the resolved group; for the **create** branch, do the same. Add this helper at the very top of `handleSubmit` (after `setError('')`, line 32):

```javascript
    // Resolve group: '__new__' means create from the typed name first.
    let resolvedGroupId = groupId || null;
    if (groupId === '__new__' && newGroupName.trim()) {
      const gres = await api.createEnvelopeGroup(newGroupName.trim());
      if (!gres.ok) { setSaving(false); setError('Gagal buat grup'); return; }
      resolvedGroupId = gres.data.id;
    } else if (groupId === '__new__') {
      resolvedGroupId = null;
    }
```

Then add `group_id: resolvedGroupId,` to **both** the edit `data` object (after `is_rollover: rollover,`, line 36) and the create `data` object (after `is_rollover: rollover,`, line 49).

- [ ] **Step 7: Render the Grup dropdown in the modal**

Add this block right after the "Nama amplop" field (after line 109):

```javascript
          <div>
            <label className="label">Grup</label>
            <select className="input" value={groupId} onChange={(e) => setGroupId(e.target.value)}>
              <option value="">Tanpa grup</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
              <option value="__new__">+ Grup baru…</option>
            </select>
            {groupId === '__new__' && (
              <input type="text" className="input mt-2" placeholder="Nama grup baru (mis. Tabungan)"
                value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} />
            )}
          </div>
```

- [ ] **Step 8: Validate build**

Run: `cd frontend && npm run build`
Expected: build succeeds (do not commit `frontend/dist/`).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/Envelopes.jsx
git commit -m "feat(envelopes): grouped Amplop layout with per-group balance + group control in modal"
```

---

## Task 5: Verification, manual smoke, and branch finish

**Files:**
- Update this plan as steps pass.

- [ ] **Step 1: Full backend suite**

Run: `python -m unittest discover -s app/tests -v`
Expected: `OK`.

- [ ] **Step 2: Frontend build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Review diff**

Run: `git diff main...feat/envelope-groups --stat` and `git diff main...feat/envelope-groups`.
Confirm only intended files changed and `frontend/dist/` is not staged.

- [ ] **Step 4: Manual smoke test**

With a logged-in user on the Amplop page:
- Create a group "Tabungan" via the envelope modal (+ Grup baru) while creating/editing a personal envelope; confirm it appears as a sub-group with a balance subtotal.
- Add a second envelope to the same group; confirm the subtotal sums both balances.
- Rename the group from its header; confirm the new name shows.
- Delete the group; confirm its envelopes move to "Lainnya" and are not deleted.
- Confirm a section with no groups still renders flat (unchanged from before).

- [ ] **Step 5: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to choose merge/PR. Merging to `main` triggers auto-deploy; the PWA cache is versioned per build, so users get the new UI on next load.

---

## Known Dirty Files When Plan Was Created

Do not revert or overwrite these unless the user explicitly asks:

- `docs/superpowers/plans/2026-04-17-whatsapp-integration.md`
- `frontend/dist/` (build artifacts)
- `landing.html`
- `.superpowers/`, `AGENTS.md`, `temporary_file/`
