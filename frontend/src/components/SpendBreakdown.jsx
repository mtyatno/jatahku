import { useState } from 'react';
import { titleCase } from '../lib/utils';
import { rpCompact } from '../lib/kpiCards';
import { breakdownSegments } from '../lib/dashboardInsights';

// Card "Ke mana uangmu periode ini": satu batang bertumpuk per amplop (3 terbesar + Lainnya)
// dengan legenda berlabel nominal dan persen. Pengganti pie "Breakdown amplop".
// Palet hijau sudah dicek validator dataviz (pemisahan CVD & normal lolos); warna terang yang
// kontrasnya < 3:1 diimbangi legenda berlabel.
const PALETTE = {
  dark: ['#34D399', '#1F9D6B', '#A7F3D0'],
  light: ['#1D9E75', '#0B5E46', '#5DCAA5'],
};
const OTHER = { dark: '#64748B', light: '#94A3B8' };

const pct = (share) => (share > 0 && share < 0.005 ? '<1%' : `${Math.round(share * 100)}%`);

export default function SpendBreakdown({ breakdown, isDark }) {
  const [hover, setHover] = useState(null);
  const { total, segments } = breakdownSegments(breakdown);
  if (!total) return null;
  const pal = PALETTE[isDark ? 'dark' : 'light'];
  const colorOf = (s, i) => (s.other ? OTHER[isDark ? 'dark' : 'light'] : pal[i % pal.length]);
  const label = (s) => (s.other ? s.name : titleCase(s.name));

  return (
    <section aria-labelledby="ke-mana-uangmu-title" className="card !px-4 md:!px-6 !pt-5 md:!pt-6 !pb-5 min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-1">
        <h2 id="ke-mana-uangmu-title" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Ke mana uangmu periode ini</h2>
        <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
          Total terpakai <b className="font-bold" style={{ color: 'var(--text)' }}>{rpCompact(total)}</b>
        </p>
      </div>

      <div className="mt-4 px-1 flex gap-[3px] h-4" role="img"
        aria-label={segments.map(s => `${label(s)} ${rpCompact(s.amount)} (${pct(s.share)})`).join(', ')}>
        {segments.map((s, i) => (
          <span key={s.key} title={`${label(s)} · ${rpCompact(s.amount)} · ${pct(s.share)}`}
            onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)}
            className="h-full rounded-[4px] transition-opacity"
            style={{ flexGrow: s.share, flexBasis: 0, minWidth: 6, background: colorOf(s, i), opacity: hover && hover !== s.key ? 0.45 : 1 }} />
        ))}
      </div>

      <ul className="mt-4 px-1 grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-3">
        {segments.map((s, i) => (
          <li key={s.key} className="flex items-start gap-2.5 min-w-0"
            onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)}>
            <span className="w-3 h-3 rounded-[3px] mt-[5px] shrink-0" style={{ background: colorOf(s, i) }} aria-hidden="true" />
            <span className="min-w-0">
              <span className="block text-[15px] font-semibold leading-snug md:truncate" style={{ color: 'var(--text)' }}>{label(s)}</span>
              <span className="block text-[13px] tabular-nums" style={{ color: 'var(--text-muted)' }}>{rpCompact(s.amount)} · {pct(s.share)}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
