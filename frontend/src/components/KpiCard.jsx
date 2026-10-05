import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { InfoTooltip } from './InfoTooltip';
import { formatShort, titleCase } from '../lib/utils';
import { monotonePath, STATUS_ORDER } from '../lib/kpiVisuals';

const tint = (c, pct) => `color-mix(in srgb, ${c} ${pct}%, transparent)`;

// Status colors stay fixed (Senja's brand is amber) and are checked for color-blind separation.
export function kpiPalette(isDark) {
  return isDark ? {
    brand: 'var(--brand-600)',
    brandMeter: 'var(--brand-400)',
    brandTrack: 'var(--brand-50)',
    amber: '#E09A2C',
    amberFill: 'rgba(224,154,44,0.16)',
    indigo: '#7C80F2',
    indigoTrack: 'rgba(124,128,242,0.22)',
    slate: '#94A3B8',
    reserved: '#64748B',
    dangerTrack: 'rgba(229,84,79,0.22)',
    track: '#334155',
    status: { over: '#E5544F', low: '#E09A2C', ok: '#22A57D', saving: '#7C80F2', empty: '#475569' },
  } : {
    brand: 'var(--brand-600)',
    brandMeter: 'var(--brand-400)',
    brandTrack: 'var(--brand-50)',
    amber: '#D97706',
    amberFill: 'rgba(217,119,6,0.12)',
    indigo: '#6366F1',
    indigoTrack: 'rgba(99,102,241,0.16)',
    slate: '#64748B',
    reserved: '#A3ADBA',
    dangerTrack: 'rgba(226,75,74,0.14)',
    track: '#E8EBEF',
    status: { over: '#E24B4A', low: '#EF9F27', ok: '#1D9E75', saving: '#6366F1', empty: '#E2E5EA' },
  };
}

export function KpiCard({ label, info, value, valueClassName = '', sub, icon, color, isDark, children }) {
  return (
    <div className="card flex flex-col gap-3 min-w-0">
      {/* Floated icon: on phones the subtitle runs under it instead of wrapping beside it. */}
      <div className="flow-root">
        <span
          className="float-right ml-2 w-9 h-9 rounded-xl flex items-center justify-center"
          style={{
            color,
            background: `linear-gradient(135deg, ${tint(color, isDark ? 28 : 16)}, ${tint(color, isDark ? 10 : 5)})`,
            boxShadow: `inset 0 0 0 1px ${tint(color, isDark ? 32 : 14)}`,
          }}
        >
          <Icon name={icon} size={20} />
        </span>
        <div className="flex items-center gap-1">
          <p className="text-xs text-gray-400 font-medium">{label}</p>
          <InfoTooltip text={info} position="bottom" />
        </div>
        <p className={`font-display text-xl font-bold mt-1 leading-tight ${valueClassName}`}>{value}</p>
        <p className="text-xs mt-0.5 text-gray-400">{sub}</p>
      </div>
      <div className="mt-auto">{children}</div>
    </div>
  );
}

// Hover, tap, or arrow keys pick one item; tapping elsewhere clears it.
function useReadout(count) {
  const [active, setActive] = useState(null);
  const ref = useRef(null);
  useEffect(() => {
    if (active == null) return undefined;
    const close = (e) => { if (!ref.current?.contains(e.target)) setActive(null); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [active]);
  const props = {
    ref,
    tabIndex: count > 0 ? 0 : undefined,
    onPointerLeave: (e) => { if (e.pointerType === 'mouse') setActive(null); },
    onFocus: () => setActive((a) => a ?? count - 1),
    onBlur: () => setActive(null),
    onKeyDown: (e) => {
      if (e.key === 'ArrowLeft') { e.preventDefault(); setActive((a) => Math.max((a ?? count) - 1, 0)); }
      if (e.key === 'ArrowRight') { e.preventDefault(); setActive((a) => Math.min((a ?? -1) + 1, count - 1)); }
      if (e.key === 'Escape') setActive(null);
    },
  };
  return { active, setActive, props };
}

function Readout({ x, children }) {
  return (
    <span
      className="absolute bottom-full mb-1.5 z-10 whitespace-nowrap rounded-md bg-gray-700 px-2 py-1 text-[11px] font-medium text-white shadow-sm pointer-events-none"
      style={{ left: `${x}%`, transform: `translateX(-${x}%)` }}
    >
      {children}
    </span>
  );
}

export function Meter({ value, color, track, label, ariaLabel }) {
  const pct = value == null ? 0 : Math.min(Math.max(value, 0), 1) * 100;
  return (
    <div className="flex items-center gap-2" role="img" aria-label={ariaLabel}>
      <div className="h-1.5 flex-1 rounded-full overflow-hidden" style={{ background: track }}>
        {pct > 0 && <div className="h-full rounded-full" style={{ width: `${Math.max(pct, 4)}%`, background: color }} />}
      </div>
      {label != null && <span className="text-[11px] font-semibold text-gray-500 leading-none">{label}</span>}
    </div>
  );
}

// Each 6px segment gets a 24px hit area that hangs into the card's bottom padding.
function SegmentBar({ items, track, ariaLabel, round = 'ends' }) {
  const { active, setActive, props } = useReadout(items.length);
  if (!items.length) return <div className="h-1.5 rounded-full" style={{ background: track }} role="img" aria-label={ariaLabel} />;
  const total = items.reduce((s, it) => s + it.grow, 0);
  let acc = 0;
  const centers = items.map((it) => { const c = ((acc + it.grow / 2) / total) * 100; acc += it.grow; return c; });
  const radius = (i) => {
    if (round === 'all') return 'rounded-full';
    return `${i === 0 ? 'rounded-l-full' : ''} ${i === items.length - 1 ? 'rounded-r-full' : ''}`;
  };
  return (
    <div {...props} className="relative -mb-[18px] outline-none rounded focus-visible:ring-2 focus-visible:ring-brand-200" role="img" aria-label={ariaLabel}>
      <div className="flex h-6 items-start gap-0.5">
        {items.map((it, i) => (
          <span
            key={it.key}
            className="h-full flex items-start cursor-default"
            style={{ flexGrow: it.grow, flexBasis: 0, minWidth: 3 }}
            onPointerEnter={(e) => { if (e.pointerType === 'mouse') setActive(i); }}
            onPointerDown={() => setActive(i)}
          >
            <span
              className={`block h-1.5 w-full transition-opacity ${radius(i)}`}
              style={{ background: it.color, opacity: active == null || active === i ? 1 : 0.45 }}
            />
          </span>
        ))}
      </div>
      {active != null && <Readout x={centers[active]}>{items[active].label}</Readout>}
    </div>
  );
}

export function FundsBar({ parts, track, ariaLabel }) {
  const items = parts
    .filter((p) => p.value > 0)
    .map((p) => ({ key: p.key, grow: p.value, color: p.color, label: `${p.label} · ${formatShort(p.value)}` }));
  return <SegmentBar items={items} track={track} ariaLabel={ariaLabel} />;
}

const STATUS_LABEL = { over: 'habis', low: 'hampir habis', ok: 'aman', saving: 'tabungan', empty: 'belum ada dana' };

// Past 24 envelopes the ticks get too thin on a phone, so group them by status.
export function EnvelopeStrip({ strip, colors }) {
  const attention = strip.filter((s) => s.status === 'over' || s.status === 'low').length;
  const ariaLabel = attention > 0
    ? `${attention} dari ${strip.length} amplop perlu perhatian`
    : `${strip.length} amplop, tidak ada yang hampir habis`;
  const items = strip.length <= 24
    ? strip.map((s) => ({ key: s.id, grow: 1, color: colors[s.status], label: `${titleCase(s.name)} · ${STATUS_LABEL[s.status]}` }))
    : STATUS_ORDER
      .map((st) => ({ key: st, grow: strip.filter((s) => s.status === st).length, color: colors[st] }))
      .filter((it) => it.grow > 0)
      .map((it) => ({ ...it, label: `${it.grow} amplop ${STATUS_LABEL[it.key]}` }));
  return <SegmentBar items={items} track={colors.empty} ariaLabel={ariaLabel} round="all" />;
}

const H = 30;
const TOP = 4;
const BASE = H - 2;

const dayLabel = (date) => new Date(`${date}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });

// Spans only the days so far, with today at the right edge.
export function SpendSparkline({ series, color, fill, track, ring }) {
  const shown = series.filter((d) => d.total != null);
  const last = shown.length - 1;
  const { active, setActive, props } = useReadout(shown.length);

  if (last < 0) return <div className="h-px" style={{ background: track }} />;

  const max = Math.max(0, ...shown.map((d) => d.total));
  const y = (v) => (max > 0 ? BASE - (v / max) * (BASE - TOP) : BASE);
  const span = Math.max(last, 1);
  const xOf = (i) => (last === 0 ? span : i);
  const pts = shown.map((d, i) => [xOf(i), y(d.total)]);
  const line = monotonePath(pts);
  const area = last > 0 ? `${line}L${span},${BASE}L0,${BASE}Z` : '';
  const xPct = (i) => (xOf(i) / span) * 100;

  const peak = shown.reduce((a, d) => (d.total > a.total ? d : a), shown[0]);
  const ariaLabel = max > 0
    ? `Belanja harian periode ini, tertinggi ${dayLabel(peak.date)} ${formatShort(peak.total)}`
    : 'Belum ada belanja periode ini';

  const pick = (clientX) => {
    const r = props.ref.current.getBoundingClientRect();
    setActive(last === 0 ? 0 : Math.min(Math.max(Math.round(((clientX - r.left) / r.width) * last), 0), last));
  };

  const dot = (i, key) => (
    <span
      key={key}
      className="absolute w-2 h-2 rounded-full pointer-events-none"
      style={{ left: `${xPct(i)}%`, top: pts[i][1], transform: 'translate(-50%, -50%)', background: color, boxShadow: `0 0 0 2px ${ring}` }}
    />
  );

  return (
    <div
      {...props}
      className="relative select-none rounded outline-none focus-visible:ring-2 focus-visible:ring-brand-200"
      style={{ height: H, touchAction: 'pan-y' }}
      role="img"
      aria-label={ariaLabel}
      onPointerDown={(e) => pick(e.clientX)}
      onPointerMove={(e) => { if (e.pointerType === 'mouse' || e.buttons) pick(e.clientX); }}
    >
      <svg viewBox={`0 0 ${span} ${H}`} preserveAspectRatio="none" className="absolute inset-0 w-full h-full overflow-visible" aria-hidden="true">
        <line x1="0" y1={BASE} x2={span} y2={BASE} stroke={track} strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {area && <path d={area} fill={fill} />}
        {last > 0 && (
          <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        )}
        {active != null && (
          <line x1={xOf(active)} y1={0} x2={xOf(active)} y2={BASE} stroke={track} strokeWidth="1" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      {dot(last, 'end')}
      {active != null && active !== last && dot(active, 'active')}
      {active != null && (
        <Readout x={xPct(active)}>{dayLabel(shown[active].date)} · {formatShort(shown[active].total)}</Readout>
      )}
    </div>
  );
}
