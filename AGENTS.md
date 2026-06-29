# Jatahku Agent Workflow

This repository uses the Superpowers-style workflow for multi-session,
multi-agent development. Codex, Claude, and other coding agents should use the
same durable process so work can be resumed without chat history.

## Required Development Flow

For any non-trivial coding task, do not jump straight into implementation.
Use this sequence:

1. `brainstorming`
   - Clarify intent, constraints, options, risks, and acceptance criteria.
   - Output a design spec in `docs/superpowers/specs/`.
   - The spec answers WHAT and WHY.
2. `writing-plans`
   - Convert the spec into a task-by-task implementation plan in
     `docs/superpowers/plans/`.
   - The plan answers HOW.
   - Use checkbox syntax (`- [ ]`) for every resumable step.
3. `executing-plans` or `subagent-driven-development`
   - Execute the plan task by task.
   - Update checkboxes as each step is actually completed.
   - Use `subagent-driven-development` only when tasks are independent enough
     to be delegated safely.
4. Inside each task, use:
   - `test-driven-development`: failing test first, then implementation, then
     green test.
   - `systematic-debugging`: when tests or runtime behavior fail, investigate
     root cause before patching.
5. Before claiming completion, use:
   - `verification-before-completion`: run the verification commands and inspect
     real output.
   - `requesting-code-review` / `receiving-code-review`: review the diff before
     merge when the change is meaningful.
   - `finishing-a-development-branch`: handle merge, cleanup, and deployment
     notes when requested.

## Durable State

- Long-lived cross-feature facts belong in agent memory outside the repo.
- Feature specs live in `docs/superpowers/specs/YYYY-MM-DD-feature-design.md`.
- Feature plans live in `docs/superpowers/plans/YYYY-MM-DD-feature.md`.
- `.superpowers/` and `temporary_file/` are scratch areas, not durable state.

## Plan Format

Plans must be executable by a fresh session:

- Include goal, architecture, and tech stack.
- Split work into `Task 1`, `Task 2`, etc.
- Each task lists exact files to modify or create.
- Each task uses `- [ ] Step ...` checkboxes.
- Prefer `Step 1: Write the failing test` when behavior can be tested.
- Include validation commands for each task.
- Include deployment or migration notes when production behavior changes.

## Current AI Advisor Work

The AI enhancement feature is tracked here:

- `docs/superpowers/specs/2026-06-27-ai-financial-advisor-design.md`
- `docs/superpowers/plans/2026-06-27-ai-financial-advisor.md`
