# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Jatahku Dashboard page into a warm, editorial layout — a "money still intact" hero, one "Catatan dari Jatahku" advice card (two separate blocks), clean Shared/Personal envelope cards, and a compact three-card insight row — without any backend or API change.

**Architecture:** Extract the dashboard's presentational pieces into small co-located components under `frontend/src/components/dashboard/`. `Dashboard.jsx` keeps all its existing data fetching, period navigation, streak/leaderboard/celebrate/onboarding logic, and becomes a thin composer of these components. The four recharts-heavy sections (Perbandingan periode, Pengeluaran harian, Breakdown amplop, and the full Pola mingguan) are replaced by three compact insight cards; only the weekly mini-chart keeps recharts. Visual identity comes from a few theme-aware CSS tokens plus the existing display font.

**Tech Stack:** React (function components + hooks), Vite, Tailwind CSS with CSS-variable theme tokens (`frontend/src/index.css`), recharts (weekly mini-chart only), existing `api` client and `lib/utils` helpers.

## Global Constraints

- **Scope: Dashboard page only.** Do not modify any other page, the backend, or the API. (spec: "Scope is the Dashboard page only. No backend or API changes.")
- **All data comes from existing endpoints** already fetched in `Dashboard.jsx`: `getEnvelopeSummary`, `getAdvisorInsights`, `getWeeklyPattern`, `getDailySpending`, `getEnvelopeBreakdown`, `/analytics/prediction`, `getTransactions`, `getPeriods`, `/user/streak`, `/household/leaderboard`. Add no new endpoint.
- **Hero number = total Sisa = `shared.reduce((s,e) => s + Number(e.free ?? e.remaining), 0)`** — identical to the current "Sisa" KPI (shared envelopes only). Do not change this derivation.
- **Advisor + Decision stay SEPARATE inside ONE card.** Reuse the existing `AdvisorCards` rendering and the existing `DecisionBox` derivation verbatim; render them as two blocks divided by a rule. Do not merge their text. (spec design decision "Advisor + Decision".)
- **No envelope motif.** Clean rounded cards only — no diagonal "envelope flap" graphic. (spec: "No envelope motif".)
- **Custom envelope groups unchanged.** The Dashboard envelope section stays Shared/Personal via `is_personal`; do NOT show custom groups here. (spec: "Custom envelope groups unchanged".)
- **Dark mode: legible, not broken.** Polish the light/cream variant; ensure dark stays readable via mode-aware tokens. A polished dark variant is out of scope.
- **Do NOT commit `frontend/dist/`.** Build artifacts stay out of git.
- **No frontend unit-test runner exists** in this project (backend uses `unittest`; there is no JS test harness). The per-task gate is `npm run build` from `frontend/` succeeding, plus the self-review described in each task. To make each component task build-verifiable, the task that creates a component also adds its `import` to `Dashboard.jsx`, so Vite pulls it into the module graph and compiles it.
- **Preserve existing behaviors in `Dashboard.jsx`:** the `jatahku:txn-added` refresh listener, `refreshTick` on the period-data effect, period navigator (`periodIdx`/`periods`), `ExportButtons` (current period only), streak pill, household leaderboard, milestone celebrate banner, `Onboarding`, and the recent-transactions list.

---

### Task 1: Theme tokens for the warm dashboard palette

**Files:**
- Modify: `frontend/src/index.css` (the `:root` fallback block at lines 2-9, and the dark structural section near lines 100-189)

**Interfaces:**
- Consumes: nothing.
- Produces: CSS variables `--hero-bg`, `--hero-fg`, `--hero-accent`, `--note-divider` available to all components via `var(...)`. Light defaults live in `:root` (inherited by every `-light` theme since they don't override these); a single `html[data-theme*="-dark"]` rule provides dark values for every dark theme.

- [ ] **Step 1: Add light/cream token defaults to the `:root` fallback block**

In `frontend/src/index.css`, inside the existing `:root { ... }` block (currently lines 2-9), append these variables before the closing brace:

```css
  /* Dashboard warm palette (light default; inherited by all -light themes) */
  --hero-bg: #0F6E56;        /* sage/brand green hero surface */
  --hero-fg: #F4FBF8;        /* near-white text on hero */
  --hero-accent: #9FE1CB;    /* mint accent / labels on hero */
  --note-divider: #ECE7DC;   /* warm divider between Catatan blocks */
```

- [ ] **Step 2: Add dark overrides in the structural dark section**

In the same file, in the `/* ── DARK MODE: structural overrides ── */` region (after the existing `html[data-theme*="-dark"] .card { ... }` rule near line 116), add a new rule:

```css
/* Dashboard warm palette — dark overrides (legible, not polished) */
html[data-theme*="-dark"] {
  --hero-bg: #0b3b30;
  --hero-fg: #e2e8f0;
  --hero-accent: #6ee7b7;
  --note-divider: #334155;
}
```

- [ ] **Step 3: Verify the build still succeeds**

Run: `cd frontend && npm run build`
Expected: build completes with no CSS/parse errors (warnings about chunk size are pre-existing and fine).

- [ ] **Step 4: Self-review**

Confirm: the four tokens exist in `:root`; the dark rule sets all four; no existing theme variable was renamed or removed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat(dashboard): warm palette theme tokens for redesign"
```

---

### Task 2: HeroSummary component

**Files:**
- Create: `frontend/src/components/dashboard/HeroSummary.jsx`
- Modify: `frontend/src/pages/Dashboard.jsx` (add import only, near the other component imports at the top)

**Interfaces:**
- Consumes: `formatShort` from `../../lib/utils`; the `--hero-*` tokens from Task 1.
- Produces: `export default function HeroSummary({ totalRemaining, totalAllocated, totalSpent, activeCount })`. `totalRemaining`/`totalAllocated`/`totalSpent` are numbers (Rupiah); `activeCount` is an integer envelope count. Renders one card.

- [ ] **Step 1: Create the component**

Create `frontend/src/components/dashboard/HeroSummary.jsx`:

```jsx
import { formatShort } from '../../lib/utils';

export default function HeroSummary({ totalRemaining, totalAllocated, totalSpent, activeCount }) {
  const negative = totalRemaining < 0;
  return (
    <div
      className="rounded-2xl p-6 flex flex-col justify-between"
      style={{ background: 'var(--hero-bg)', color: 'var(--hero-fg)' }}
    >
      <div>
        <p className="text-xs font-bold uppercase tracking-widest" style={{ color: 'var(--hero-accent)' }}>
          Amplop bulan ini
        </p>
        <p className="text-sm mt-1" style={{ color: 'var(--hero-fg)', opacity: 0.85 }}>
          Masih utuh di amplop
        </p>
        <p className="font-display font-bold text-4xl md:text-5xl mt-3 leading-none">
          {negative ? '-' : ''}{formatShort(Math.abs(totalRemaining))}
        </p>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-6 pt-4" style={{ borderTop: '1px solid rgba(255,255,255,0.18)' }}>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--hero-accent)' }}>Dialokasi</p>
          <p className="font-display font-bold text-sm mt-0.5">{formatShort(totalAllocated)}</p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--hero-accent)' }}>Terpakai</p>
          <p className="font-display font-bold text-sm mt-0.5">{formatShort(totalSpent)}</p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--hero-accent)' }}>Amplop aktif</p>
          <p className="font-display font-bold text-sm mt-0.5">{activeCount}</p>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add the import to Dashboard.jsx**

In `frontend/src/pages/Dashboard.jsx`, after the existing `import Onboarding from '../components/Onboarding';` line, add:

```jsx
import HeroSummary from '../components/dashboard/HeroSummary';
```

(The component is not rendered yet — this only pulls it into the build graph for verification.)

- [ ] **Step 3: Verify the build compiles the component**

Run: `cd frontend && npm run build`
Expected: build succeeds (an "unused import" is not a build error). No JSX/syntax errors from `HeroSummary.jsx`.

- [ ] **Step 4: Self-review**

Confirm: uses `--hero-*` tokens; shows label, subline, big `totalRemaining`, and the DIALOKASI/TERPAKAI/AMPLOP AKTIF triad; negative remaining renders with a leading `-`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/HeroSummary.jsx frontend/src/pages/Dashboard.jsx
git commit -m "feat(dashboard): HeroSummary card"
```

---

### Task 3: JatahkuNote component (advisor block + DecisionBox block)

**Files:**
- Create: `frontend/src/components/dashboard/JatahkuNote.jsx`
- Modify: `frontend/src/pages/Dashboard.jsx` (add import only)

**Interfaces:**
- Consumes: `Link` from `react-router-dom`; `formatCurrency`, `titleCase` from `../../lib/utils`; the `--note-divider` token.
- Produces: `export default function JatahkuNote({ cards, envelopes, prediction, todaySpent })`. `cards` = `advisorInsights?.dashboard_cards` (array or undefined); `envelopes` = full envelope array; `prediction` = `/analytics/prediction` object or null; `todaySpent` = number. Returns one `.card` with up to two blocks separated by a rule, or `null` when both blocks are empty.

This task moves the existing `AdvisorCards` rendering and the existing `DecisionBox` derivation/rendering (currently inline in `Dashboard.jsx`) into this component **verbatim in behavior**. The advisor block keeps the severity-colored mini-cards; the decision block keeps its alert/positive colored boxes. The only change is they now live as two blocks inside one wrapping `.card` with a divider between them, plus a "Lihat detail →" link to `/analytics`.

- [ ] **Step 1: Create the component**

Create `frontend/src/components/dashboard/JatahkuNote.jsx`:

```jsx
import { Link } from 'react-router-dom';
import { formatCurrency, titleCase } from '../../lib/utils';

// ── Advisor block (moved verbatim from Dashboard AdvisorCards) ──
const ADVISOR_STYLES = {
  danger: { bg: '#FEF2F2', border: '#FECACA', title: '#991B1B', text: '#7F1D1D' },
  warning: { bg: '#FFFBEB', border: '#FDE68A', title: '#92400E', text: '#78350F' },
  info: { bg: '#EFF6FF', border: '#BFDBFE', title: '#1D4ED8', text: '#1E3A8A' },
  positive: { bg: '#F0FDF9', border: '#A7F3D0', title: '#065F46', text: '#065F46' },
};

function AdvisorBlock({ cards }) {
  if (!cards?.length) return null;
  return (
    <div className="space-y-3">
      {cards.map(card => {
        const style = ADVISOR_STYLES[card.severity] || ADVISOR_STYLES.info;
        return (
          <div key={card.id} className="rounded-xl p-4" style={{ background: style.bg, border: `1px solid ${style.border}` }}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-bold mb-1 uppercase tracking-wide" style={{ color: style.title }}>Advisor</p>
                <p className="text-sm font-semibold" style={{ color: style.text }}>{card.title}</p>
                <p className="text-xs mt-1" style={{ color: style.text }}>{card.body}</p>
              </div>
              {card.primary_action?.route && (
                <Link to={card.primary_action.route} className="text-xs font-semibold text-brand-600 hover:underline flex-shrink-0">
                  {card.primary_action.label || 'Lihat'}
                </Link>
              )}
            </div>
            {card.evidence?.length > 0 && (
              <div className="mt-2 pt-2 border-t text-xs space-y-1" style={{ borderColor: style.border, color: style.text }}>
                {card.evidence.map((item, idx) => <p key={idx}>{item}</p>)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Decision block (derivation moved verbatim from Dashboard DecisionBox) ──
function buildDecision({ envelopes, prediction, todaySpent }) {
  if (!prediction || prediction.total_allocated === 0) return null;

  const safeDaily = prediction.safe_daily;
  const items = [];

  if (todaySpent > 0 && safeDaily > 0) {
    const ratio = todaySpent / safeDaily;
    const sisa = safeDaily - todaySpent;
    if (ratio >= 1.5) {
      items.push({ icon: '🔴', text: `Hari ini kamu overspend ${ratio.toFixed(1)}x dari batas aman (${formatCurrency(safeDaily)}/hari)`, level: 'danger' });
    } else if (ratio >= 1.0) {
      items.push({ icon: '🟠', text: `Pengeluaran hari ini (${formatCurrency(todaySpent)}) melebihi batas aman ${formatCurrency(safeDaily)}/hari`, level: 'warning' });
    } else if (ratio <= 0.5) {
      items.push({ icon: '🎉', text: `Mantap! Hari ini kamu hemat. Sisa jatah ${formatCurrency(sisa)} bisa ditabung atau carry ke besok.`, level: 'reward' });
    } else {
      items.push({ icon: '✅', text: `Pengeluaran hari ini ${formatCurrency(todaySpent)} — masih aman, sisa ${formatCurrency(sisa)} hari ini.`, level: 'safe' });
    }
  } else if (safeDaily > 0) {
    items.push({ icon: '🎉', text: `Belum ada pengeluaran hari ini. Jatah ${formatCurrency(safeDaily)} masih utuh — mantap!`, level: 'reward' });
  }

  const urgent = [...envelopes]
    .filter(e => Number(e.allocated) > 0 && e.spent_ratio >= 0.7)
    .sort((a, b) => b.spent_ratio - a.spent_ratio)
    .slice(0, 3);

  urgent.forEach(e => {
    const pct = Math.round(e.spent_ratio * 100);
    if (e.spent_ratio >= 1.0) {
      items.push({ icon: '🔴', text: `${e.emoji} ${titleCase(e.name)} sudah habis (${pct}%)`, level: 'danger' });
    } else if (e.spent_ratio >= 0.9) {
      items.push({ icon: '🔴', text: `${e.emoji} ${titleCase(e.name)} hampir habis (${pct}%)`, level: 'danger' });
    } else {
      items.push({ icon: '⚠️', text: `${e.emoji} ${titleCase(e.name)} mulai menipis (${pct}%)`, level: 'warning' });
    }
  });

  const safeCount = envelopes.filter(e => Number(e.allocated) > 0 && e.spent_ratio < 0.7).length;
  if (safeCount > 0 && urgent.length > 0) {
    items.push({ icon: '✅', text: `${safeCount} amplop lainnya masih aman`, level: 'safe' });
  }

  if (items.length === 0) return null;

  const alertItems = items.filter(i => i.level === 'danger' || i.level === 'warning');
  const positiveItems = items.filter(i => i.level === 'reward' || i.level === 'safe');
  const hasDanger = alertItems.some(i => i.level === 'danger');
  return { alertItems, positiveItems, hasDanger, safeDaily, prediction };
}

function DecisionBlock({ envelopes, prediction, todaySpent }) {
  const data = buildDecision({ envelopes, prediction, todaySpent });
  if (!data) return null;
  const { alertItems, positiveItems, hasDanger, safeDaily, prediction: pred } = data;

  return (
    <div className="space-y-3">
      {alertItems.length > 0 && (
        <div className="rounded-xl p-4" style={{ background: hasDanger ? '#FEF2F2' : '#FFFBEB', border: `1px solid ${hasDanger ? '#FECACA' : '#FDE68A'}` }}>
          <p className="text-xs font-bold mb-2.5 uppercase tracking-wide" style={{ color: hasDanger ? '#991B1B' : '#92400E' }}>
            {hasDanger ? '🚨 Perlu perhatian' : '⚠️ Mulai menipis'}
          </p>
          <div className="space-y-1.5">
            {alertItems.map((item, i) => (
              <p key={i} className="text-sm" style={{ color: item.level === 'danger' ? '#7F1D1D' : '#78350F' }}>
                {item.icon} {item.text}
              </p>
            ))}
          </div>
          {safeDaily > 0 && (
            <p className="text-xs mt-2.5 pt-2.5 border-t" style={{ borderColor: hasDanger ? '#FECACA' : '#FDE68A', color: hasDanger ? '#991B1B' : '#92400E' }}>
              👉 Batas aman: <strong>{formatCurrency(safeDaily)}/hari</strong> · Sisa {pred.days_left} hari · Dana bebas {formatCurrency(pred.free)}
            </p>
          )}
        </div>
      )}
      {positiveItems.length > 0 && (
        <div className="rounded-xl p-4" style={{ background: '#F0FDF9', border: '1px solid #A7F3D0' }}>
          <p className="text-xs font-bold mb-2.5 uppercase tracking-wide" style={{ color: '#065F46' }}>
            {positiveItems.some(i => i.level === 'reward') ? '🎉 Kabar baik' : '✅ Status aman'}
          </p>
          <div className="space-y-1.5">
            {positiveItems.map((item, i) => (
              <p key={i} className="text-sm" style={{ color: '#065F46' }}>
                {item.icon} {item.text}
              </p>
            ))}
          </div>
          {alertItems.length === 0 && safeDaily > 0 && (
            <p className="text-xs mt-2.5 pt-2.5 border-t border-green-200" style={{ color: '#065F46' }}>
              👉 Batas aman: <strong>{formatCurrency(safeDaily)}/hari</strong> · Sisa {pred.days_left} hari · Dana bebas {formatCurrency(pred.free)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function JatahkuNote({ cards, envelopes, prediction, todaySpent }) {
  const hasAdvisor = !!cards?.length;
  const decision = buildDecision({ envelopes, prediction, todaySpent });
  const hasDecision = !!decision;

  if (!hasAdvisor && !hasDecision) return null;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-display font-bold text-base">Catatan dari Jatahku</h3>
        <Link to="/analytics" className="text-xs font-semibold text-brand-600 hover:underline flex-shrink-0">
          Lihat detail →
        </Link>
      </div>
      {hasAdvisor && <AdvisorBlock cards={cards} />}
      {hasAdvisor && hasDecision && (
        <div className="my-4" style={{ borderTop: '1px solid var(--note-divider)' }} />
      )}
      {hasDecision && <DecisionBlock envelopes={envelopes} prediction={prediction} todaySpent={todaySpent} />}
    </div>
  );
}
```

- [ ] **Step 2: Add the import to Dashboard.jsx**

In `frontend/src/pages/Dashboard.jsx`, after the `HeroSummary` import, add:

```jsx
import JatahkuNote from '../components/dashboard/JatahkuNote';
```

- [ ] **Step 3: Verify the build compiles the component**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors from `JatahkuNote.jsx`.

- [ ] **Step 4: Self-review**

Confirm against the current inline `DecisionBox` (Dashboard.jsx lines 67-162) and `AdvisorCards` (lines 314-350): the moved logic is byte-for-byte equivalent in behavior (same thresholds, same copy, same severity styles). Confirm: both empty → `null`; only advisor → advisor block, no divider; only decision → decision block, no divider; both → divider between. "Lihat detail →" points to `/analytics`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/JatahkuNote.jsx frontend/src/pages/Dashboard.jsx
git commit -m "feat(dashboard): JatahkuNote combining advisor + decision blocks"
```

---

### Task 4: DashboardEnvelopeCard component

**Files:**
- Create: `frontend/src/components/dashboard/DashboardEnvelopeCard.jsx`
- Modify: `frontend/src/pages/Dashboard.jsx` (add import only)

**Interfaces:**
- Consumes: `formatShort`, `titleCase` from `../../lib/utils`.
- Produces: `export default function DashboardEnvelopeCard({ env })` where `env` is one `EnvelopeSummary` object (fields: `id`, `name`, `emoji`, `allocated`, `spent`, `reserved`, `free`, `remaining`, `rollover`, `spent_ratio`, `is_locked`). Renders one clean envelope card. This is the current `EnvelopeRow` (Dashboard.jsx lines 352-411) moved verbatim — no envelope-flap motif (it never had one).

- [ ] **Step 1: Create the component**

Create `frontend/src/components/dashboard/DashboardEnvelopeCard.jsx`:

```jsx
import { formatShort, titleCase } from '../../lib/utils';

export default function DashboardEnvelopeCard({ env }) {
  const allocated = Number(env.allocated);
  const rollover = Number(env.rollover || 0);
  const spent = Number(env.spent);
  const reserved = Number(env.reserved || 0);
  const free = Number(env.free || env.remaining);
  const ratio = env.spent_ratio;
  const isUnfunded = allocated <= 0 && rollover === 0 && env.name !== 'Tabungan';

  const barColor = ratio >= 0.9 ? 'bg-danger-400' : ratio >= 0.7 ? 'bg-amber-400' : 'bg-brand-400';
  const freeColor = free <= 0 ? 'text-danger-400' : ratio >= 0.7 ? 'text-amber-400' : 'text-brand-600';

  const badge = ratio >= 1.0
    ? <span className="text-xs px-1.5 py-0.5 rounded-md bg-red-100 text-danger-400 font-semibold">Habis</span>
    : ratio >= 0.9
    ? <span className="text-xs px-1.5 py-0.5 rounded-md bg-red-50 text-danger-400 font-medium">🔴 {Math.round(ratio * 100)}%</span>
    : ratio >= 0.7
    ? <span className="text-xs px-1.5 py-0.5 rounded-md bg-amber-50 text-amber-600 font-medium">🟡 {Math.round(ratio * 100)}%</span>
    : null;

  return (
    <div className={`card hover:border-brand-200 transition-colors ${env.is_locked ? 'opacity-60' : ''}`}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-lg">{env.emoji || '📁'}</span>
          <span className="font-semibold text-sm">{titleCase(env.name)}</span>
          {badge}
        </div>
        <span className={`font-display font-bold text-sm ${freeColor}`}>{formatShort(free)}</span>
      </div>
      {isUnfunded ? (
        <div className="bg-amber-50 text-amber-600 text-xs px-3 py-2 rounded-lg">💡 Belum ada dana.</div>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden flex-1">
              <div className={`h-full rounded-full transition-all duration-500 ${env.is_locked ? 'bg-gray-300' : barColor}`}
                style={{ width: `${Math.min(Math.max(ratio * 100, 1), 100)}%` }} />
            </div>
            <span className={`text-xs font-semibold w-10 text-right ${freeColor}`}>
              {free <= 0 ? '0%' : `Sisa ${Math.round((1 - ratio) * 100)}%`}
            </span>
          </div>
          <div className="flex justify-between mt-1 text-xs text-gray-400">
            <span>Terpakai {formatShort(spent)}</span>
            {reserved > 0 && <span>⏳ {formatShort(reserved)}</span>}
            <span>Dana {formatShort(allocated)}</span>
          </div>
          {rollover !== 0 && (
            <p className={`text-xs mt-0.5 ${rollover > 0 ? 'text-brand-500' : 'text-danger-400'}`}>
              {rollover > 0
                ? `🔄 +${formatShort(rollover)} rollover`
                : `🔄 ${formatShort(Math.abs(rollover))} minus dari periode lalu`}
            </p>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add the import to Dashboard.jsx**

In `frontend/src/pages/Dashboard.jsx`, after the `JatahkuNote` import, add:

```jsx
import DashboardEnvelopeCard from '../components/dashboard/DashboardEnvelopeCard';
```

- [ ] **Step 3: Verify the build compiles the component**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors from `DashboardEnvelopeCard.jsx`.

- [ ] **Step 4: Self-review**

Diff the component against `EnvelopeRow` (Dashboard.jsx lines 352-411): logic identical; only the import source for `formatShort`/`titleCase` changed (now `../../lib/utils`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/DashboardEnvelopeCard.jsx frontend/src/pages/Dashboard.jsx
git commit -m "feat(dashboard): DashboardEnvelopeCard"
```

---

### Task 5: Three insight cards (InsightTempo, InsightWeekly, InsightBreakdown)

**Files:**
- Create: `frontend/src/components/dashboard/InsightTempo.jsx`
- Create: `frontend/src/components/dashboard/InsightWeekly.jsx`
- Create: `frontend/src/components/dashboard/InsightBreakdown.jsx`
- Modify: `frontend/src/pages/Dashboard.jsx` (add three imports only)

**Interfaces:**
- `InsightTempo`: `export default function InsightTempo({ prediction, todaySpent })`. `prediction` = `/analytics/prediction` object or null (fields `safe_daily`, `days_left`); `todaySpent` = number. Today's spend vs safe daily, a progress bar, "Terpakai X% · Aman/Hati-hati", a one-line note. Renders a muted empty state when `prediction` is null or `safe_daily <= 0`.
- `InsightWeekly`: `export default function InsightWeekly({ data })`. `data` = `getWeeklyPattern` array of `{ dow, name, avg }`. Mini weekday bar chart (recharts) + "paling boros {day}". Renders muted empty state when no data.
- `InsightBreakdown`: `export default function InsightBreakdown({ breakdown })`. `breakdown` = array of `{ name, emoji, spent }` (already filtered to `spent > 0` by Dashboard). Top categories + % + total. Muted empty state when empty.
- Consumes: `formatShort`, `formatCurrency`, `titleCase` from `../../lib/utils`; recharts (`InsightWeekly` only).

- [ ] **Step 1: Create InsightTempo**

Create `frontend/src/components/dashboard/InsightTempo.jsx`:

```jsx
import { formatShort } from '../../lib/utils';

export default function InsightTempo({ prediction, todaySpent }) {
  const safeDaily = prediction?.safe_daily || 0;
  if (!prediction || safeDaily <= 0) {
    return (
      <div className="card">
        <h3 className="font-semibold text-sm mb-1">Tempo hari ini</h3>
        <p className="text-xs text-gray-400 mt-3">Belum ada batas aman untuk periode ini.</p>
      </div>
    );
  }

  const ratio = safeDaily > 0 ? todaySpent / safeDaily : 0;
  const pct = Math.round(ratio * 100);
  const aman = ratio < 1.0;
  const barColor = ratio >= 1.0 ? 'bg-danger-400' : ratio >= 0.7 ? 'bg-amber-400' : 'bg-brand-400';
  const note = todaySpent <= 0
    ? `Jatah ${formatShort(safeDaily)}/hari masih utuh.`
    : aman
    ? `Sisa ${formatShort(Math.max(safeDaily - todaySpent, 0))} untuk hari ini.`
    : `Lewat ${formatShort(todaySpent - safeDaily)} dari batas aman.`;

  return (
    <div className="card">
      <h3 className="font-semibold text-sm mb-1">Tempo hari ini</h3>
      <p className="font-display font-bold text-xl mt-1">{formatShort(todaySpent)}</p>
      <p className="text-xs text-gray-400">dari batas {formatShort(safeDaily)}/hari</p>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden mt-3">
        <div className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${Math.min(Math.max(pct, 1), 100)}%` }} />
      </div>
      <p className="text-xs mt-2">
        <span className="text-gray-500">Terpakai {pct}% · </span>
        <span className={aman ? 'text-brand-600 font-semibold' : 'text-danger-400 font-semibold'}>
          {aman ? 'Aman' : 'Hati-hati'}
        </span>
      </p>
      <p className="text-xs text-gray-400 mt-1">{note}</p>
    </div>
  );
}
```

- [ ] **Step 2: Create InsightWeekly**

Create `frontend/src/components/dashboard/InsightWeekly.jsx`. The bar logic mirrors the current `WeeklyPattern` (Dashboard.jsx lines 261-312), compacted:

```jsx
import { formatCurrency } from '../../lib/utils';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

const TOOLTIP_STYLE = {
  background: 'var(--card-bg)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  color: 'var(--text)',
};

export default function InsightWeekly({ data }) {
  const ordered = [1, 2, 3, 4, 5, 6, 0]
    .map(dow => (data || []).find(d => d.dow === dow))
    .filter(Boolean);
  const hasData = ordered.some(d => d.avg > 0);

  if (!hasData) {
    return (
      <div className="card">
        <h3 className="font-semibold text-sm mb-1">Pola mingguan</h3>
        <p className="text-xs text-gray-400 mt-3">Belum ada cukup data mingguan.</p>
      </div>
    );
  }

  const maxAvg = Math.max(...ordered.map(d => d.avg));
  const chartData = ordered.map(d => ({
    name: d.name.slice(0, 3),
    fullName: d.name,
    avg: d.avg,
    isPeak: d.avg === maxAvg && maxAvg > 0,
  }));
  const peakDay = chartData.find(d => d.isPeak);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-sm">Pola mingguan</h3>
        {peakDay && (
          <span className="text-xs text-gray-400">
            Paling boros <span className="font-medium text-amber-500">{peakDay.fullName}</span>
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={110}>
        <BarChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }} barCategoryGap="15%">
          <XAxis dataKey="name" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontSize: 9 }} tickLine={false} axisLine={false} width={36}
            tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
          <Tooltip
            formatter={v => [formatCurrency(v), 'Rata-rata']}
            labelFormatter={(_, payload) => payload?.[0]?.payload?.fullName || ''}
            contentStyle={TOOLTIP_STYLE}
            labelStyle={{ color: 'var(--text-muted)', fontSize: 11 }}
            itemStyle={{ color: 'var(--text)' }}
          />
          <Bar dataKey="avg" radius={[3, 3, 0, 0]}
            shape={(props) => <rect {...props} fill={props.isPeak ? '#BA7517' : '#1D9E75'} rx={3} ry={3} />}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 3: Create InsightBreakdown**

Create `frontend/src/components/dashboard/InsightBreakdown.jsx`:

```jsx
import { formatShort, titleCase } from '../../lib/utils';

const DOTS = ['#0F6E56', '#BA7517', '#1D9E75', '#D85A30', '#534AB7'];

export default function InsightBreakdown({ breakdown }) {
  const items = breakdown || [];
  if (items.length === 0) {
    return (
      <div className="card">
        <h3 className="font-semibold text-sm mb-1">Ke mana uangnya</h3>
        <p className="text-xs text-gray-400 mt-3">Belum ada pengeluaran periode ini.</p>
      </div>
    );
  }

  const total = items.reduce((s, x) => s + x.spent, 0);
  const top = [...items].sort((a, b) => b.spent - a.spent).slice(0, 5);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-sm">Ke mana uangnya</h3>
        <span className="text-xs text-gray-400">Total {formatShort(total)}</span>
      </div>
      <div className="space-y-1.5">
        {top.map((item, i) => {
          const pct = total > 0 ? Math.round((item.spent / total) * 100) : 0;
          return (
            <div key={i} className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-1.5 min-w-0">
                <div className="w-2.5 h-2.5 flex-shrink-0 rounded-sm" style={{ background: DOTS[i % DOTS.length] }} />
                <span className="truncate">{item.emoji} {titleCase(item.name)}</span>
              </div>
              <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                <span className="font-mono font-medium">{formatShort(item.spent)}</span>
                <span className="text-gray-400">({pct}%)</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Add the three imports to Dashboard.jsx**

In `frontend/src/pages/Dashboard.jsx`, after the `DashboardEnvelopeCard` import, add:

```jsx
import InsightTempo from '../components/dashboard/InsightTempo';
import InsightWeekly from '../components/dashboard/InsightWeekly';
import InsightBreakdown from '../components/dashboard/InsightBreakdown';
```

- [ ] **Step 5: Verify the build compiles all three components**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors from the three new files.

- [ ] **Step 6: Self-review**

Confirm: each card has a clear empty/zero state (Rp0 / no data) that does not throw; `InsightWeekly` reuses the same DOW ordering and peak logic as the current `WeeklyPattern`; `InsightTempo` "Aman/Hati-hati" flips at `ratio >= 1.0`; `InsightBreakdown` shows at most 5 rows with a total.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/dashboard/InsightTempo.jsx frontend/src/components/dashboard/InsightWeekly.jsx frontend/src/components/dashboard/InsightBreakdown.jsx frontend/src/pages/Dashboard.jsx
git commit -m "feat(dashboard): three compact insight cards"
```

---

### Task 6: Assemble the new Dashboard layout and remove old chart code

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`

**Interfaces:**
- Consumes: `HeroSummary`, `JatahkuNote`, `DashboardEnvelopeCard`, `InsightTempo`, `InsightWeekly`, `InsightBreakdown` (imported in Tasks 2-5); all existing state and derived values already present in the component.
- Produces: the final Dashboard render. No exported API change.

This task rewrites the render (and trims now-dead code) while preserving all data fetching and the behaviors listed in Global Constraints.

- [ ] **Step 1: Remove now-dead chart code and unused imports**

In `frontend/src/pages/Dashboard.jsx`:

1. Replace the recharts import block (lines 8-11) with nothing — delete it entirely (the only remaining recharts usage now lives inside `InsightWeekly`).
2. Delete these now-unused module-level definitions: `COLORS` (line 13), `TOOLTIP_STYLE`/`TOOLTIP_LABEL_STYLE`/`TOOLTIP_ITEM_STYLE` (lines 15-22), `CustomTooltip` (24-36), `buildDailyData` (38-65), `DecisionBox` (67-162), `buildInsights` (164-195), `MonthlyComparison` (197-259), `WeeklyPattern` (261-312), `AdvisorCards` (314-350), and `EnvelopeRow` (352-411). Keep `sortEnvelopes` (413-421) — the render still uses it.
3. Remove the now-unused derived locals in the component body: `chartData` (line 528) and `daysLeft` if it becomes unused (it is still shown in the period navigator — keep `daysLeft`). Keep `todaySpent`, `isCurrentPeriod`, `selectedPeriod`, `shared`, `personal`, `totalAllocated`, `totalSpent`, `totalRemaining`, `periodLabel`, `milestoneLabel`.

After this step the file imports `formatShort, formatCurrency, titleCase` from utils — verify which are still referenced in the remaining JSX (the recent-transactions list uses `formatShort`; `milestoneLabel`/period code use none of `formatCurrency`/`titleCase` directly). Remove any util import that is no longer referenced anywhere in the file to keep the build lint-clean. (`titleCase` and `formatCurrency` are used only by the moved components now — drop them from the Dashboard import if unreferenced; keep `formatShort`.)

- [ ] **Step 2: Replace the render body**

Replace the JSX returned by the component (currently the KPI grid at line 620 through the end of the charts block at line 718, plus the envelope sections 720-741) with the new structure below. Keep the celebrate banner (540-554), the header + period navigator block (555-588), `{isCurrentPeriod && <ExportButtons />}` (590), and the leaderboard block (592-618) exactly as they are, and keep the transactions block (743-776) exactly as it is.

Insert, in place of the old KPI grid + advisor/decision + MonthlyComparison + WeeklyPattern + charts + envelope sections, the following:

```jsx
      {/* Hero + Catatan */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <HeroSummary
          totalRemaining={totalRemaining}
          totalAllocated={totalAllocated}
          totalSpent={totalSpent}
          activeCount={envelopes.length}
        />
        {isCurrentPeriod && (
          <JatahkuNote
            cards={advisorInsights?.dashboard_cards}
            envelopes={envelopes}
            prediction={prediction}
            todaySpent={todaySpent}
          />
        )}
      </div>

      {/* Amplop kamu — Shared then Personal (custom groups stay on /envelopes) */}
      {shared.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display font-bold text-lg">👥 Shared</h2>
            <Link to="/envelopes" className="text-sm text-brand-600 font-medium hover:underline">Lihat semua →</Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {shared.map(env => <DashboardEnvelopeCard key={env.id} env={env} />)}
          </div>
        </div>
      )}
      {personal.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display font-bold text-lg">🔒 Personal</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {personal.map(env => <DashboardEnvelopeCard key={env.id} env={env} />)}
          </div>
        </div>
      )}

      {/* Insight bulan ini */}
      <div>
        <h2 className="font-display font-bold text-lg mb-3">Insight bulan ini</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {isCurrentPeriod
            ? <InsightTempo prediction={prediction} todaySpent={todaySpent} />
            : <InsightBreakdown breakdown={breakdown} />}
          <InsightWeekly data={weeklyPattern} />
          {isCurrentPeriod && <InsightBreakdown breakdown={breakdown} />}
        </div>
      </div>
```

Notes on the insight row: for the current period, all three cards show (Tempo, Pola mingguan, Ke mana uangnya). For a past period there is no `prediction` (Tempo would be empty), so show Breakdown in the first slot instead and render two cards. This keeps every slot meaningful without an empty Tempo card on historical periods.

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds. No "is defined but never used" errors for removed symbols, no "X is not defined" errors. If the build reports an unused import (e.g. `formatCurrency`/`titleCase`), remove it (Step 1 note) and rebuild.

- [ ] **Step 4: Self-review against the spec layout**

Walk the spec "Layout (top to bottom)": header unchanged ✓; hero row two columns ✓; Catatan card with two blocks (only current period) ✓; Amplop Shared then Personal with clean cards ✓; three insight cards ✓; recent transactions ✓; FAB untouched (lives in `Layout.jsx`) ✓. Confirm the hero number equals `totalRemaining` (the old "Sisa" KPI). Confirm celebrate/streak/leaderboard/ExportButtons/Onboarding still present. Confirm no `dist/` files are staged.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Dashboard.jsx
git commit -m "feat(dashboard): assemble redesigned layout, remove legacy charts"
```

---

### Task 7: Final verification and branch finish

**Files:** none (verification + git).

- [ ] **Step 1: Full frontend build**

Run: `cd frontend && npm run build`
Expected: success, no errors.

- [ ] **Step 2: Backend suite still green (sanity — no backend change expected)**

Run: `python -m unittest discover -s app/tests`
Expected: same pass count as before this branch (this plan touches no backend file).

- [ ] **Step 3: Confirm no build artifacts committed**

Run: `git status --porcelain frontend/dist`
Expected: no staged/committed changes under `frontend/dist` from this branch's commits. (Pre-existing working-tree noise in `dist` from earlier sessions is not added by these commits.)

- [ ] **Step 4: Manual smoke checklist (note results)**

With `npm run dev` (or against a deploy preview): current period shows hero = Sisa, Catatan card with advisor + decision divided, Shared/Personal envelope cards, three insight cards populated, recent transactions; switch to a past period → no Tempo-empty card, Breakdown + Pola mingguan render, no crash; new/Rp0 period renders without errors; toggle a dark theme → dashboard legible; resize to mobile → single-column, no overflow.

- [ ] **Step 5: Finish the branch**

Use superpowers:finishing-a-development-branch to verify tests, present merge/PR options, and complete.

---

## Self-Review (plan vs. spec)

**Spec coverage:**
- Scope Dashboard-only, no backend/API → Global Constraints + Task 6 (frontend only). ✓
- Hero "Masih utuh" = total Sisa, triad footer → Task 2 + Task 6 wiring (`totalRemaining`). ✓
- Catatan dari Jatahku, two blocks + divider, empty-state rules, "Lihat detail →" → Task 3. ✓
- Clean cards, no envelope motif → Task 4 (port of EnvelopeRow, which has no flap). ✓
- Shared/Personal only, custom groups not shown → Task 6 render. ✓
- Three insight cards (Tempo, Pola mingguan, Ke mana uangnya) replacing the four chart sections → Task 5 + Task 6 (removal of MonthlyComparison/daily-line/donut). ✓
- Warm palette + display typography as theme-aware tokens; dark legible → Task 1 + component styles. ✓
- Components under `components/dashboard/` → Tasks 2-5. ✓
- Recent transactions preserved; FAB untouched → Task 6 (transactions block kept; FAB in Layout.jsx not touched). ✓
- Validation: `npm run build`, manual smoke, backend green → Task 7. ✓
- Don't commit `dist/` → Global Constraints + Task 7 Step 3. ✓

**Risk note (spec "Shared chart components"):** verified `MonthlyComparison`, `WeeklyPattern`, `buildInsights`, `buildDailyData` are local to `Dashboard.jsx` and NOT imported by Analytics, so removing them in Task 6 is safe; Analytics keeps its own charts.

**Placeholder scan:** no TBD/TODO; every code step contains complete code. ✓

**Type/name consistency:** component prop names (`totalRemaining`, `totalAllocated`, `totalSpent`, `activeCount`, `cards`, `envelopes`, `prediction`, `todaySpent`, `env`, `data`, `breakdown`) match between their defining task and the Task 6 call sites. ✓
