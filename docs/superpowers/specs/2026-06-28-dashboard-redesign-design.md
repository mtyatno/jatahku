# Dashboard Redesign - Design Spec

- **Date:** 2026-06-28
- **Status:** Approved (pending spec review)
- **Author:** mtyatno + Claude

## Summary

Redesign the Jatahku Dashboard page to feel distinctive and intentional instead
of generic/templated. Keep all existing data and behavior; change layout,
hierarchy, palette, and typography. The new dashboard leads with a "money still
intact this period" hero, a single "Catatan dari Jatahku" advice card (two
separate blocks inside it), clean envelope cards (Shared/Personal as today), a
condensed three-card "Insight bulan ini" row, and recent transactions.

Scope is the Dashboard page only. No backend or API changes.

## Goal

Give the Dashboard a warm, editorial identity (cream/sage palette, large display
numbers) that reads as Jatahku's own, while reducing the "full of charts /
template" feeling. All numbers shown already exist in current endpoints.

## Design decisions (locked during brainstorming)

- **Scope:** Dashboard page only. Other pages unchanged.
- **Charts:** replace the four current chart sections (Perbandingan periode,
  Pola mingguan, Pengeluaran harian, Breakdown amplop) with three compact
  insight cards (Tempo hari ini, Pola mingguan, Ke mana uangnya). The detailed
  period-comparison and daily-spending charts remain available on the Analytics
  page (already there).
- **Advisor + Decision:** combine into ONE "Catatan dari Jatahku" card, but keep
  the advisor insight and the DecisionBox (kabar baik / batas aman) as TWO
  visually separate blocks within that card (divider between them). Reuse the
  existing ranking/derivation logic; do not merge their text.
- **No envelope motif:** use clean cards (no diagonal "envelope flap" graphic).
  Distinctiveness comes from palette, typography, and layout.
- **Custom envelope groups unchanged:** the Dashboard envelope section stays
  Shared/Personal as today; group logic stays on the Amplop page.
- **Dark mode:** polish the light/cream variant now; ensure dark mode stays
  legible/not-broken via mode-aware tokens, but a polished dark variant is later.

## Current State

`frontend/src/pages/Dashboard.jsx` currently renders: header (greeting, period
nav, streak, export buttons), four KPI cards, `AdvisorCards` (top
`dashboard_cards`) with `DecisionBox` fallback, `MonthlyComparison`,
`WeeklyPattern`, daily-spending + breakdown charts, envelope rows grouped
Shared/Personal, and recent transactions. Data comes from `getEnvelopeSummary`,
`getAdvisorInsights`, `getWeeklyPattern`, `getDailySpending`,
`getEnvelopeBreakdown`, `/analytics/prediction`, `getTransactions`, plus streak/
leaderboard. A global quick-add FAB lives in `Layout.jsx`.

## Design

### Layout (top to bottom)

1. **Header** — unchanged: "Hai, {name} 👋", period navigation, streak pill,
   Download CSV + Laporan buttons.
2. **Hero row (two columns, stacks on mobile):**
   - **Left — hero card:** label "AMPLOP BULAN INI", subline "Masih utuh di
     amplop", a large display number = **total Sisa** (sum of envelope
     `remaining`), and a footer triad: DIALOKASI (sum allocated), TERPAKAI (sum
     spent), AMPLOP AKTIF (count). Clean card, warm accent.
   - **Right — "Catatan dari Jatahku" card:** one card containing two separate
     blocks divided by a rule: (1) the top advisor insight (from
     `getAdvisorInsights().dashboard_cards`), (2) the DecisionBox content (kabar
     baik / batas aman / dana bebas). "Lihat detail →" links to /analytics. If
     advisor has no cards, show only the DecisionBox block; if DecisionBox is
     empty (no allocation), show only the advisor block; if both empty, hide the
     card.
3. **Amplop kamu** — section heading + "Shared · Lihat semua →" to /envelopes.
   Clean envelope cards in a responsive grid (name, balance, Terpakai/Dana, Sisa
   %), Shared first, then a "Personal" sub-label and personal cards, plus a
   dashed "Buat amplop baru" card that links to /envelopes (creation happens
   there).
   Sorting/grouping = existing Shared/Personal split (`is_personal`); custom
   groups are NOT shown here.
4. **Insight bulan ini** — three compact cards:
   - **Tempo hari ini:** today's spend vs safe daily, a progress bar, "Terpakai
     X% · Aman/Hati-hati", and a one-line note. From prediction + today's spend.
   - **Pola mingguan:** mini weekday bar chart, "paling boros {day}". From
     `getWeeklyPattern`.
   - **Ke mana uangnya:** category breakdown (top categories + %), total. From
     `getEnvelopeBreakdown`.
5. **Transaksi terbaru** — heading + "Lihat semua →" and a compact list. From
   `getTransactions`.
6. The global quick-add FAB (in `Layout.jsx`) is unchanged.

### Visual identity

- **Palette:** warm cream/ivory page background; sage/brand green for accents and
  display numbers; amber for caution. Introduce as theme-aware tokens (Tailwind
  config or CSS variables) so dark mode degrades gracefully.
- **Typography:** large numbers and section titles use the existing display font
  (`font-display`); body stays in the current sans. Generous spacing.
- **Cards:** clean, rounded, soft shadow/border — no envelope-flap graphic.

### Components & files

- `frontend/src/pages/Dashboard.jsx` restructured as a thin composer of sections.
- New small presentational components (co-located, e.g.
  `frontend/src/components/dashboard/`): `HeroSummary`, `JatahkuNote` (renders the
  two blocks), `DashboardEnvelopeCard`, `InsightTempo`, `InsightWeekly`,
  `InsightBreakdown`. The existing `AdvisorCards`/`DecisionBox` logic is reused
  inside `JatahkuNote` (kept as two blocks).
- Color/typography tokens defined once (Tailwind config and/or a CSS variables
  block) and reused.
- Removed from the Dashboard: `MonthlyComparison`, the large daily-spending line
  chart, and the donut breakdown component usages (their data is re-presented
  compactly or remains on Analytics). Do not delete shared chart components if
  Analytics imports them.

## Validation Strategy

- `npm run build` from `frontend/` succeeds.
- Manual smoke: hero number equals current "Sisa" KPI; advisor + decision blocks
  both render with correct content and divider; envelope cards show Shared then
  Personal with correct balances; the three insight cards populate; recent
  transactions list correct; layout is responsive on mobile; dark mode is legible
  (not polished, but not broken); empty/new-period states (Rp0) render without
  errors.
- No backend tests affected (frontend-only change); the backend suite should
  remain green.

## Risks

- **Theme tokens vs dark mode:** introducing a cream palette can clash with the
  existing dark theme. Mitigation: use mode-aware tokens and verify dark is
  legible; defer dark polish.
- **Shared chart components:** Analytics may import `MonthlyComparison`/chart
  components; only remove their usage from Dashboard, not the components, unless
  confirmed unused elsewhere.
- **Empty states:** new-period (Rp0 allocated/spent) must not break the hero,
  insight cards, or the Catatan card. Handle zero/empty gracefully.
- Build artifacts: do not commit `frontend/dist/`.
- PWA cache is versioned per build, so users get the new dashboard on next load.
