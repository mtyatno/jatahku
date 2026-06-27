# Custom Envelope Groups - Design Spec

- **Date:** 2026-06-27
- **Status:** Approved (pending spec review)
- **Author:** mtyatno + Claude

## Summary

Let users organize envelopes into custom groups (e.g. "Tabungan", "Expense")
on the Amplop page, with each group header showing the total balance of its
envelopes. This supports the "one bank account, many savings purposes" workflow
(e.g. separate `Dana Darurat`, `Tabungan Sekolah` envelopes that the user keeps
in one physical BSI account) without merging their balances.

The `EnvelopeGroup` model and `Envelope.group_id` column already exist in the
initial schema, so **no database migration is required**.

## Goal

Give a second, purpose-based organizing axis on top of the existing ownership
axis (Shared/Personal), so users can see envelopes grouped by intent and read a
running total per group.

## Current State

- `Envelope` has `group_id` (nullable FK to `envelope_groups`) and an `EnvelopeGroup`
  model exists (`household_id`, `name`, `sort_order`) — but neither is used by any
  API route or frontend code today.
- `frontend/src/pages/Envelopes.jsx` sections envelopes into **Shared** vs
  **Personal** purely from `e.is_personal` (`Envelopes.jsx:361-362`). This is an
  ownership split, not `EnvelopeGroup`.
- Each envelope card already shows a `🔒 Personal` / `👥 Shared` badge and the
  envelope's balance (`free`) prominently with `Dana` (allocated) secondary.
- Envelope-to-envelope transfer already exists
  (`POST /envelopes/transfer?from_id&to_id&amount`).
- `envelope_groups` table and `envelopes.group_id` are present in the initial
  Alembic migration (`0f8fa68ae7b7_initial_schema.py`), so they exist in the
  production DB.

## Design

### 1. Layout (Amplop page)

Two-level hierarchy:

```
👥 SHARED
   ├─ Tabungan · saldo Rp5.2jt          (custom sub-group + total balance)
   │    [💰 Darurat] [🎓 Sekolah]
   ├─ Expense · saldo Rp910rb
   │    [📱 Tagihan] [🎬 Hiburan]
   └─ Lainnya                            (envelopes with no group)
        [📁 ...]
🔒 PERSONAL
   └─ (same structure)
```

- **Top sections stay Shared/Personal**, derived from `is_personal`.
- Within each section, envelopes are grouped by their custom group. Each sub-group
  header shows the group name and **total balance** = Σ (`allocated + rollover -
  spent`) of the group's members **within that section**.
- A group whose members span both ownership types appears under **both** sections,
  each with its own subtotal computed from the members present in that section.
- Envelopes with no group fall into a **"Lainnya"** sub-group.
- **Backward-compatible rendering:** if a section has no custom groups at all, it
  renders flat (no sub-headers), exactly like today, so existing users see no
  change until they create a group.

### 2. Group management

- **Create/Edit envelope modal** gains a **Grup** control: choose an existing
  group, choose "Tanpa grup", or pick "+ Grup baru" and type a name (the group is
  created on save, then the envelope is assigned to it).
- **Sub-group header** (on hover) shows ✏️ rename and 🗑 delete actions.
- **Deleting a group** sets `group_id = null` on its members (they move to
  "Lainnya"); it never deletes envelopes.
- Groups are **household-level** (per the existing model): the group vocabulary is
  shared across household members. Group order follows `sort_order` (assigned
  incrementally on creation). No manual reordering in v1.

### 3. Backend (`app/api/routes/envelopes.py`)

No migration needed. Add:

- `GET /envelopes/groups` — list groups for the user's household (ordered by
  `sort_order`, then name).
- `POST /envelopes/groups` `{ "name": str }` — create a group in the household;
  assign next `sort_order`.
- `PATCH /envelopes/groups/{group_id}` `{ "name": str }` — rename.
- `DELETE /envelopes/groups/{group_id}` — delete the group and null out
  `group_id` on its envelopes.
- Envelope **create** and **update** accept an optional `group_id`. Validate that
  the group belongs to the user's household; reject otherwise.
- Envelope **summary** response includes `group_id` and `group_name` per envelope
  so the frontend can render without a second round-trip.

All group endpoints scope to the caller's household and require auth, following
the existing route style.

### 4. Frontend

- `frontend/src/lib/api.js`: add `getEnvelopeGroups()`, `createEnvelopeGroup(name)`,
  `renameEnvelopeGroup(id, name)`, `deleteEnvelopeGroup(id)`; envelope create/update
  send `group_id`.
- `frontend/src/pages/Envelopes.jsx`:
  - Load groups alongside the envelope summary.
  - Render the two-level hierarchy with per-group balance subtotals.
  - Add the Grup dropdown (with inline create) to `CreateModal`.
  - Add rename/delete actions to sub-group headers.
- The per-group balance subtotal is computed by a small pure helper (group the
  envelopes by `group_id` within a section, sum balances) so it can be unit-tested
  in isolation.

### 5. Scope (v1) and non-goals

- **In scope:** Amplop page only — grouping UI, per-group balance totals, group
  CRUD, assigning envelopes via the modal.
- **Out of scope (possible later phases):** drag-and-drop assignment, manual group
  reordering, seeded/default groups, grouping shown on Dashboard or Allocate,
  Savings Goals UI.

## Validation Strategy

- Backend: unit-test the grouping/subtotal helper and any pure logic; run
  `python -m unittest discover -s app/tests -v`; `python -m py_compile` changed files.
- Frontend: `npm run build` from `frontend/`.
- **No DB migration** required (table and column already exist).
- Manual: create a group via the envelope modal, confirm balance subtotal,
  rename and delete a group (members move to "Lainnya"), confirm a section with no
  groups still renders flat.

## Risks

- **Mixed-ownership groups** could confuse if a user doesn't expect a group to
  appear under both sections. Mitigation: clear per-section subtotals and the
  same group name in both places.
- **Build artifacts:** do not commit `frontend/dist/`.
- **PWA cache:** existing service worker now versions its cache per build, so the
  new UI will reach users on the next deploy (see prior fix). No extra action.
