# Multi-Session Workflow Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained, agent-agnostic, copy-into-any-repo bundle that ports the superpowers multi-session pattern (brainstorm → spec → plan → TDD → review → verify, plus in-repo memory) **without depending on the superpowers plugin**.

**Architecture:** The bundle is its own git repo at `Z:\jatahku.com-v3\multisession-bundle\`. All workflow content lives in plain Markdown under `docs/superpowers/` so any agent follows it just by reading files. Instruction files in target repos only need a one-line pointer to `docs/superpowers/WORKFLOW.md` (pointer-based → zero conflict with existing AGENTS.md/CLAUDE.md). A bash `verify.sh` checks the file tree and cross-file link integrity, and dry-runs a new-repo and existing-repo install.

**Tech Stack:** Markdown documents + templates; bash for the verification harness (`test -f`, `grep`); git for per-task commits. (No application code — "tests" are structural/link assertions in bash.)

## Global Constraints

- Bundle root: `Z:\jatahku.com-v3\multisession-bundle\` (OUTSIDE the jatahku repo).
- Bundle is its own git repo (`git init`); commit after each task.
- Copied-to-target subtree is exactly `docs/superpowers/**`. `INSTALL.md`, `_snippets/`, and `verify.sh` are NOT copied to targets.
- Canonical workflow content lives only in `docs/superpowers/WORKFLOW.md`. Instruction files point to it; they never duplicate it.
- Everything is plugin-independent and tool-agnostic (no Claude-only assumptions in copied files).
- Memory layer is in-repo and committed (shared with team), not external/per-machine.
- Use forward-slash paths inside files; run bash via the Bash tool.

---

## Task 1: Initialize bundle repo + directory skeleton

**Files:**
- Create: `Z:/jatahku.com-v3/multisession-bundle/.gitignore`
- Create: `Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/specs/.gitkeep`
- Create: `Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/plans/.gitkeep`
- Create: `Z:/jatahku.com-v3/multisession-bundle/_snippets/.gitkeep`

**Interfaces:**
- Produces: bundle git repo + directory tree `docs/superpowers/{specs,plans,memory}`, `_snippets/`. Later tasks place files into these dirs.

- [ ] **Step 1: Write the failing test**

```bash
BUNDLE="Z:/jatahku.com-v3/multisession-bundle"
test -d "$BUNDLE/.git" \
 && test -d "$BUNDLE/docs/superpowers/specs" \
 && test -d "$BUNDLE/docs/superpowers/plans" \
 && test -d "$BUNDLE/docs/superpowers/memory" \
 && test -d "$BUNDLE/_snippets" \
 && echo "SKELETON_OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run the Step 1 block.
Expected: FAIL — prints nothing / non-zero (dirs do not exist yet).

- [ ] **Step 3: Create skeleton**

```bash
BUNDLE="Z:/jatahku.com-v3/multisession-bundle"
mkdir -p "$BUNDLE/docs/superpowers/specs" \
         "$BUNDLE/docs/superpowers/plans" \
         "$BUNDLE/docs/superpowers/memory" \
         "$BUNDLE/_snippets"
git -C "$BUNDLE" init -q
printf '%s\n' "/scratch/" "/.scratch/" "*.scratch.md" > "$BUNDLE/.gitignore"
: > "$BUNDLE/docs/superpowers/specs/.gitkeep"
: > "$BUNDLE/docs/superpowers/plans/.gitkeep"
: > "$BUNDLE/_snippets/.gitkeep"
```

- [ ] **Step 4: Run test to verify it passes**

Run the Step 1 block.
Expected: PASS — prints `SKELETON_OK`.

- [ ] **Step 5: Commit**

```bash
BUNDLE="Z:/jatahku.com-v3/multisession-bundle"
git -C "$BUNDLE" add -A
git -C "$BUNDLE" commit -q -m "chore: bundle repo skeleton"
```

---

## Task 2: Canonical workflow doc (`WORKFLOW.md`)

**Files:**
- Create: `Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/WORKFLOW.md`

**Interfaces:**
- Produces: `docs/superpowers/WORKFLOW.md` containing anchor strings later checked by `verify.sh` and pointed to by AGENTS.md/README/INSTALL: the lifecycle line `brainstorm → spec → plan → execute (TDD) → review → verify → finish`, and section headings `## Memory`, `## Resuming across sessions`.

- [ ] **Step 1: Write the failing test**

```bash
F="Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/WORKFLOW.md"
test -f "$F" \
 && grep -q "brainstorm → spec → plan → execute (TDD) → review → verify → finish" "$F" \
 && grep -q "## Resuming across sessions" "$F" \
 && grep -q "## Memory" "$F" \
 && echo "WORKFLOW_OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run Step 1. Expected: FAIL — file missing.

- [ ] **Step 3: Write the file**

Create `docs/superpowers/WORKFLOW.md` with EXACTLY this content:

```markdown
# Multi-Session Workflow

This repo follows a lightweight, **session-resumable** workflow. Any AI coding
agent (or human) working here should follow it. It needs **no plugins** — these
files are the whole system.

## The lifecycle

brainstorm → spec → plan → execute (TDD) → review → verify → finish

1. **Brainstorm.** Before building anything, clarify intent, constraints, and
   success criteria. Explore 2-3 approaches with trade-offs. Do not write code yet.
2. **Spec.** Write the agreed design to
   `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` using
   `specs/_TEMPLATE-design.md`. Commit it.
3. **Plan.** Break the spec into bite-sized, independently testable tasks in
   `docs/superpowers/plans/YYYY-MM-DD-<topic>.md` using `plans/_TEMPLATE-plan.md`.
   Each task starts with a failing test. Checkboxes `- [ ]` are your resume points.
4. **Execute (TDD).** Per task: write a failing test → run it, see it fail →
   minimal implementation → run, see it pass → commit. Red, green, refactor.
5. **Debug systematically.** On any failure, find the root cause before guessing
   a fix. State a hypothesis, test it, then change one thing.
6. **Verify before completion.** Before claiming done, run the actual verification
   command and read the real output. Evidence before assertions.
7. **Review & finish.** Review the diff against the spec. Then merge / PR / clean up.

## Resuming across sessions

The spec and plan are committed, so work survives session boundaries:

- A new session reads the latest plan and continues from the first unchecked `- [ ]`.
- Update checkboxes as you complete steps so the next session knows where to start.

## Memory

Record non-obvious, lasting facts (infra, gotchas, decisions) as **one fact per
file** in `docs/superpowers/memory/`, indexed in `memory/MEMORY.md`. This memory
is **committed and shared with the team** — not personal or per-machine. Write a
memory when you learn something the code itself does not record and a future
session would waste time rediscovering. Do not record what the code, git history,
or this file already says.

## Scratch / working files

Keep throwaway working files (experiments, brainstorm dumps) in an untracked
directory and never commit them. Such paths are listed in `.gitignore`.

## Optional: superpowers plugin

If your agent happens to have the "superpowers" plugin installed, its skills
(brainstorming, writing-plans, test-driven-development, systematic-debugging,
verification-before-completion) implement this exact workflow in more depth. This
repo does not require it — these docs stand alone.
```

- [ ] **Step 4: Run test to verify it passes**

Run Step 1. Expected: PASS — prints `WORKFLOW_OK`.

- [ ] **Step 5: Commit**

```bash
BUNDLE="Z:/jatahku.com-v3/multisession-bundle"
git -C "$BUNDLE" add -A
git -C "$BUNDLE" commit -q -m "docs: canonical WORKFLOW.md"
```

---

## Task 3: Spec & plan templates

**Files:**
- Create: `Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/specs/_TEMPLATE-design.md`
- Create: `Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/plans/_TEMPLATE-plan.md`

**Interfaces:**
- Produces: two template files referenced by WORKFLOW.md and README. Anchor checks: design template has `## Approaches`; plan template has `Step 1: Write the failing test`.

- [ ] **Step 1: Write the failing test**

```bash
D="Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/specs/_TEMPLATE-design.md"
P="Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/plans/_TEMPLATE-plan.md"
test -f "$D" && grep -q "## Approaches" "$D" \
 && test -f "$P" && grep -q "Step 1: Write the failing test" "$P" \
 && echo "TEMPLATES_OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run Step 1. Expected: FAIL — files missing.

- [ ] **Step 3a: Write `specs/_TEMPLATE-design.md`**

```markdown
# <Title> — Design

**Date:** YYYY-MM-DD
**Status:** Draft | Approved

## Goal

<One paragraph: what this builds and why.>

## Context

<Current state, constraints, relevant existing code.>

## Approaches

<2-3 options with trade-offs. Mark the recommended one and say why.>

## Design / Architecture

<Components, structure, data flow.>

## Components

<Per unit: what it does, how it is used, what it depends on.>

## Error Handling / Edge Cases

<What can go wrong and how it is handled.>

## Testing

<How this will be verified.>

## Out of Scope (YAGNI)

<Explicitly excluded.>
```

- [ ] **Step 3b: Write `plans/_TEMPLATE-plan.md`**

```markdown
# <Feature> Implementation Plan

> Implement task-by-task. Each task is independently testable. Checkboxes `- [ ]`
> are resume points across sessions.

**Goal:** <one sentence>
**Architecture:** <2-3 sentences>
**Tech Stack:** <key tech>

## Global Constraints

<Project-wide rules copied verbatim from the spec — one line each.>

---

## Task 1: <Component>

**Files:**
- Create: `exact/path`
- Test: `exact/test/path`

- [ ] **Step 1: Write the failing test**

<actual test code>

- [ ] **Step 2: Run it, confirm it fails**

Run: `<command>`  Expected: FAIL (<reason>)

- [ ] **Step 3: Minimal implementation**

<actual code>

- [ ] **Step 4: Run it, confirm it passes**

Run: `<command>`  Expected: PASS

- [ ] **Step 5: Commit**

`git add <paths> && git commit -m "<message>"`
```

- [ ] **Step 4: Run test to verify it passes**

Run Step 1. Expected: PASS — prints `TEMPLATES_OK`.

- [ ] **Step 5: Commit**

```bash
BUNDLE="Z:/jatahku.com-v3/multisession-bundle"
git -C "$BUNDLE" add -A
git -C "$BUNDLE" commit -q -m "docs: spec & plan templates"
```

---

## Task 4: Memory layer (`memory/MEMORY.md` + `_TEMPLATE.md`)

**Files:**
- Create: `Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/memory/MEMORY.md`
- Create: `Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/memory/_TEMPLATE.md`

**Interfaces:**
- Produces: committed memory index + per-fact template. Anchor checks: `MEMORY.md` contains `# Memory Index`; `_TEMPLATE.md` contains `description:`.

- [ ] **Step 1: Write the failing test**

```bash
M="Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/memory/MEMORY.md"
T="Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/memory/_TEMPLATE.md"
test -f "$M" && grep -q "# Memory Index" "$M" \
 && test -f "$T" && grep -q "description:" "$T" \
 && echo "MEMORY_OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run Step 1. Expected: FAIL — files missing.

- [ ] **Step 3a: Write `memory/MEMORY.md`**

```markdown
# Memory Index

One fact per file in this directory. Each entry below is a single line:
`- [Title](file.md) — short hook`

This memory is **committed and shared with the team**. Record durable, non-obvious
facts (infra, gotchas, decisions) a future session would otherwise rediscover. See
`_TEMPLATE.md` for the per-file format.

<!-- entries below -->
```

- [ ] **Step 3b: Write `memory/_TEMPLATE.md`**

````markdown
<!-- Copy to <slug>.md (one fact per file) and add a line to MEMORY.md. -->
---
name: <short-kebab-case-slug>
description: <one-line summary used to judge relevance during recall>
type: project | reference | decision
---

<The single fact. For decisions, add **Why:** and **How to apply:** lines.
Link related memories with [[their-slug]].>
````

- [ ] **Step 4: Run test to verify it passes**

Run Step 1. Expected: PASS — prints `MEMORY_OK`.

- [ ] **Step 5: Commit**

```bash
BUNDLE="Z:/jatahku.com-v3/multisession-bundle"
git -C "$BUNDLE" add -A
git -C "$BUNDLE" commit -q -m "docs: in-repo memory layer"
```

---

## Task 5: README + install snippets

**Files:**
- Create: `Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/README.md`
- Create: `Z:/jatahku.com-v3/multisession-bundle/_snippets/agents-pointer.md`
- Create: `Z:/jatahku.com-v3/multisession-bundle/_snippets/gitignore.txt`
- Delete: `Z:/jatahku.com-v3/multisession-bundle/_snippets/.gitkeep`

**Interfaces:**
- Produces: README (references WORKFLOW.md, specs, plans, memory) and the pointer snippet that target AGENTS.md/CLAUDE.md will contain. Anchor checks: README mentions `WORKFLOW.md`; pointer snippet references `docs/superpowers/WORKFLOW.md`.

- [ ] **Step 1: Write the failing test**

```bash
R="Z:/jatahku.com-v3/multisession-bundle/docs/superpowers/README.md"
A="Z:/jatahku.com-v3/multisession-bundle/_snippets/agents-pointer.md"
G="Z:/jatahku.com-v3/multisession-bundle/_snippets/gitignore.txt"
test -f "$R" && grep -q "WORKFLOW.md" "$R" \
 && test -f "$A" && grep -q "docs/superpowers/WORKFLOW.md" "$A" \
 && test -f "$G" && grep -q "scratch" "$G" \
 && echo "README_OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run Step 1. Expected: FAIL — files missing.

- [ ] **Step 3a: Write `docs/superpowers/README.md`**

```markdown
# Multi-Session Workflow (docs/superpowers)

A self-contained, plugin-free workflow for resumable, multi-session development.

- **WORKFLOW.md** — the workflow every agent here follows. Start here.
- **specs/** — design docs, one per feature. Template: `_TEMPLATE-design.md`.
- **plans/** — task-by-task implementation plans. Template: `_TEMPLATE-plan.md`.
- **memory/** — durable, committed project facts. Index: `MEMORY.md`.

Flow: brainstorm → spec → plan → execute (TDD) → review → verify → finish.
```

- [ ] **Step 3b: Write `_snippets/agents-pointer.md`**

```markdown
<!-- Append this to your AGENTS.md (and/or CLAUDE.md). Do not overwrite. -->
## Workflow

This repo uses a session-resumable workflow. Before building, read and follow
`docs/superpowers/WORKFLOW.md` (brainstorm → spec → plan → TDD → review → verify).
Specs live in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`, and
durable facts in `docs/superpowers/memory/`.
```

- [ ] **Step 3c: Write `_snippets/gitignore.txt` and drop the placeholder**

```bash
BUNDLE="Z:/jatahku.com-v3/multisession-bundle"
printf '%s\n' \
  "# Multi-session workflow scratch (untracked working files)" \
  "/scratch/" \
  "/.scratch/" \
  "*.scratch.md" > "$BUNDLE/_snippets/gitignore.txt"
rm -f "$BUNDLE/_snippets/.gitkeep"
```

- [ ] **Step 4: Run test to verify it passes**

Run Step 1. Expected: PASS — prints `README_OK`.

- [ ] **Step 5: Commit**

```bash
BUNDLE="Z:/jatahku.com-v3/multisession-bundle"
git -C "$BUNDLE" add -A
git -C "$BUNDLE" commit -q -m "docs: README + install snippets"
```

---

## Task 6: INSTALL.md + verify harness + integration dry-runs

**Files:**
- Create: `Z:/jatahku.com-v3/multisession-bundle/INSTALL.md`
- Create: `Z:/jatahku.com-v3/multisession-bundle/verify.sh`

**Interfaces:**
- Consumes: every file from Tasks 1-5.
- Produces: `verify.sh` — runnable structural + link + dry-run check covering the whole bundle. This is the bundle's integration test.

- [ ] **Step 1: Write the failing test**

```bash
BUNDLE="Z:/jatahku.com-v3/multisession-bundle"
test -f "$BUNDLE/INSTALL.md" \
 && test -f "$BUNDLE/verify.sh" \
 && bash "$BUNDLE/verify.sh"
```

- [ ] **Step 2: Run test to verify it fails**

Run Step 1. Expected: FAIL — `INSTALL.md`/`verify.sh` missing.

- [ ] **Step 3a: Write `INSTALL.md`**

```markdown
# Installing the Multi-Session Workflow Bundle

Copy the `docs/` folder into your target repo's root, then wire up one pointer
line. Works for new and existing repos.

## What gets copied

- `docs/superpowers/**` → your repo root.
- Do NOT copy `INSTALL.md`, `_snippets/`, or `verify.sh`.

## New repo

1. Copy `docs/superpowers/` to your repo root.
2. Create `AGENTS.md` (and optionally `CLAUDE.md`) containing the contents of
   `_snippets/agents-pointer.md`.
3. Append `_snippets/gitignore.txt` to your `.gitignore`.
4. Commit.

## Existing repo

1. Copy `docs/superpowers/` to your repo root (new dir → no conflicts).
2. Append the contents of `_snippets/agents-pointer.md` to your existing
   `AGENTS.md` (and/or `CLAUDE.md`). Append — do not overwrite.
3. Append `_snippets/gitignore.txt` to your existing `.gitignore`.
4. Commit.

## Verify

- `docs/superpowers/WORKFLOW.md` exists and is readable.
- Your AGENTS.md points to it.
- `.gitignore` includes the scratch lines.
```

- [ ] **Step 3b: Write `verify.sh`**

```bash
#!/usr/bin/env bash
# Structural + link + install dry-run check for the bundle.
set -u
BUNDLE="$(cd "$(dirname "$0")" && pwd)"
fail=0
chk() { if eval "$2"; then echo "ok   - $1"; else echo "FAIL - $1"; fail=1; fi; }

D="$BUNDLE/docs/superpowers"

# 1. Tree exists
chk "WORKFLOW.md"            "test -f '$D/WORKFLOW.md'"
chk "README.md"             "test -f '$D/README.md'"
chk "specs template"        "test -f '$D/specs/_TEMPLATE-design.md'"
chk "plans template"        "test -f '$D/plans/_TEMPLATE-plan.md'"
chk "memory index"          "test -f '$D/memory/MEMORY.md'"
chk "memory template"       "test -f '$D/memory/_TEMPLATE.md'"
chk "agents-pointer snippet" "test -f '$BUNDLE/_snippets/agents-pointer.md'"
chk "gitignore snippet"     "test -f '$BUNDLE/_snippets/gitignore.txt'"
chk "INSTALL.md"            "test -f '$BUNDLE/INSTALL.md'"

# 2. Link / anchor integrity
chk "WORKFLOW lifecycle line" "grep -q 'brainstorm → spec → plan → execute (TDD) → review → verify → finish' '$D/WORKFLOW.md'"
chk "README -> WORKFLOW"      "grep -q 'WORKFLOW.md' '$D/README.md'"
chk "pointer -> WORKFLOW"     "grep -q 'docs/superpowers/WORKFLOW.md' '$BUNDLE/_snippets/agents-pointer.md'"
chk "INSTALL -> docs subtree" "grep -q 'docs/superpowers' '$BUNDLE/INSTALL.md'"

# 3. Dry-run: new repo
NEW="$(mktemp -d)"
cp -r "$D" "$NEW/" 2>/dev/null
cat "$BUNDLE/_snippets/agents-pointer.md" > "$NEW/AGENTS.md"
cat "$BUNDLE/_snippets/gitignore.txt" > "$NEW/.gitignore"
chk "new-repo: docs copied"      "test -f '$NEW/superpowers/WORKFLOW.md'"
chk "new-repo: AGENTS points"    "grep -q 'docs/superpowers/WORKFLOW.md' '$NEW/AGENTS.md'"
rm -rf "$NEW"

# 4. Dry-run: existing repo (pre-existing AGENTS.md must survive)
EX="$(mktemp -d)"
printf '%s\n' "# Existing AGENTS" "Keep me." > "$EX/AGENTS.md"
printf '%s\n' "node_modules/" > "$EX/.gitignore"
cp -r "$D" "$EX/" 2>/dev/null
cat "$BUNDLE/_snippets/agents-pointer.md" >> "$EX/AGENTS.md"
cat "$BUNDLE/_snippets/gitignore.txt" >> "$EX/.gitignore"
chk "existing: original kept"    "grep -q 'Keep me.' '$EX/AGENTS.md'"
chk "existing: pointer appended" "grep -q 'docs/superpowers/WORKFLOW.md' '$EX/AGENTS.md'"
chk "existing: gitignore kept"   "grep -q 'node_modules/' '$EX/.gitignore'"
chk "existing: scratch appended" "grep -q 'scratch' '$EX/.gitignore'"
rm -rf "$EX"

if [ "$fail" -eq 0 ]; then echo "ALL_VERIFY_OK"; else echo "VERIFY_FAILED"; exit 1; fi
```

- [ ] **Step 4: Run test to verify it passes**

```bash
bash "Z:/jatahku.com-v3/multisession-bundle/verify.sh"
```
Expected: every line `ok - ...` then `ALL_VERIFY_OK` (exit 0).

- [ ] **Step 5: Commit**

```bash
BUNDLE="Z:/jatahku.com-v3/multisession-bundle"
git -C "$BUNDLE" add -A
git -C "$BUNDLE" commit -q -m "docs: INSTALL.md + verify harness"
```

---

## Self-Review

**1. Spec coverage**
- WORKFLOW.md (full lifecycle, plugin-independent, tool-agnostic, optional-plugin note) → Task 2. ✓
- Spec & plan templates (TDD baked into plan template) → Task 3. ✓
- Memory layer in-repo & committed (MEMORY.md + template) → Task 4. ✓
- README → Task 5. ✓
- `_snippets/` (agents-pointer, gitignore) → Task 5. ✓
- INSTALL.md (new vs existing repo, pointer-based) → Task 6. ✓
- Pointer-based, zero-conflict for existing repos → exercised by verify dry-run #4 (Task 6). ✓
- Bundle outside jatahku repo, its own git repo → Task 1 + Global Constraints. ✓
- Testing: smoke structure, new-repo dry-run, existing-repo dry-run, link lint → Task 6 `verify.sh`. ✓

**2. Placeholder scan:** Angle-bracket `<...>` text appears only INSIDE template file contents (intentional — they are fill-in templates), not as plan instructions. No TBD/TODO in plan steps. ✓

**3. Type consistency:** Path `Z:/jatahku.com-v3/multisession-bundle`, subtree `docs/superpowers/`, and anchor strings (`brainstorm → spec → plan → execute (TDD) → review → verify → finish`, `docs/superpowers/WORKFLOW.md`) are identical across Tasks 2, 5, 6 and verify.sh. ✓
