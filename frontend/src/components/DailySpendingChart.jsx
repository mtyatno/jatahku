import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid } from 'recharts';
import { rpFull, rpCompact } from '../lib/kpiCards';
import { buildDailySeries, dailyTicks, tickLabel, niceStep, axisLabel, parseDay } from '../lib/dashboardInsights';
import { tileTones } from './KpiCard';

// Card "Pengeluaran harian": satu batang per hari periode ini. Hijau = dalam batas aman per hari,
// merah = lewat; hari tanpa belanja dan hari yang belum terjadi tampil sebagai batang tipis.
// Garis titik-titik = batas aman per hari; batang hari ini diberi garis tepi.

const HARI = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu'];
const BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const fullDay = (s) => { const d = parseDay(s); return `${HARI[d.getDay()]}, ${d.getDate()} ${BULAN[d.getMonth()]}`; };

function BarShape({ x, y, width, height, payload, colors }) {
  if (!(width > 0)) return null;
  const { status, isToday } = payload;
  const r = Math.min(4, width / 2);
  const stub = status === 'future' || status === 'empty';
  const fill = stub ? colors.stub : status === 'over' ? colors.over : colors.ok;
  return (
    <g>
      <rect x={x} y={y} width={width} height={Math.max(height, 0)} rx={stub ? 1.5 : r} ry={stub ? 1.5 : r} style={{ fill }} />
      {isToday && !stub && (
        <rect x={x - 3} y={y - 3} width={width + 6} height={Math.max(height, 0) + 3} rx={r + 2} ry={r + 2}
          style={{ fill: 'none', stroke: 'var(--text)', strokeWidth: 1.5 }} />
      )}
    </g>
  );
}

function XTick({ x, y, payload, series, today }) {
  const isToday = payload.value === today;
  return (
    <text x={x} y={y + 14} textAnchor="middle"
      style={{ fill: isToday ? 'var(--text)' : 'var(--text-muted)', fontSize: 12, fontWeight: isToday ? 700 : 400 }}>
      {tickLabel(payload.value, series)}
    </text>
  );
}

function YTick({ x, y, payload }) {
  return (
    <text x={x - 6} y={y + 4} textAnchor="end" style={{ fill: 'var(--text-muted)', fontSize: 12 }}>
      {axisLabel(payload.value)}
    </text>
  );
}

function ChartTooltip({ active, payload, safeDaily }) {
  const row = active && payload?.[0]?.payload;
  if (!row || row.status === 'future') return null;
  const over = safeDaily > 0 && row.total > safeDaily;
  return (
    <div className="rounded-lg px-3 py-2 shadow-lg text-xs" style={{ background: 'var(--card-bg)', border: '1px solid var(--border)' }}>
      <p style={{ color: 'var(--text-muted)' }}>{fullDay(row.day)}{row.isToday ? ' · hari ini' : ''}</p>
      <p className="text-sm font-semibold mt-0.5" style={{ color: 'var(--text)' }}>{row.total > 0 ? rpFull(row.total) : 'Tidak ada belanja'}</p>
      {row.total > 0 && safeDaily > 0 && (
        <p style={{ color: 'var(--text-muted)' }}>{over ? `Lewat ${rpCompact(row.total - safeDaily)} dari batas aman` : 'Dalam batas aman'}</p>
      )}
    </div>
  );
}

function LegendDot({ color, children }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="w-2.5 h-2.5 rounded-[3px]" style={{ background: color }} aria-hidden="true" />
      {children}
    </span>
  );
}

export default function DailySpendingChart({ daily, periodStart, periodEnd, today, safeDaily, isDark }) {
  const tones = tileTones(isDark);
  const colors = { ok: tones.bars.green, over: tones.danger.bar, stub: isDark ? '#2A3245' : '#E5E7EB' };
  const series = buildDailySeries(daily, periodStart, periodEnd, today, safeDaily);
  const maxTotal = series.reduce((m, r) => Math.max(m, r.total), 0);
  const step = niceStep(Math.max(maxTotal, safeDaily || 0));
  const top = step * 2;
  const stubValue = top * 0.025;
  const data = series.map(r => ({ ...r, value: r.status === 'future' || r.status === 'empty' ? stubValue : r.total }));
  const ticks = dailyTicks(series);
  const overDays = series.filter(r => r.status === 'over').length;
  const spentDays = series.filter(r => r.status === 'ok' || r.status === 'over').length;

  return (
    <section aria-labelledby="pengeluaran-harian-title" className="card !px-4 md:!px-6 !pt-5 md:!pt-6 !pb-4 min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 px-1">
        <h2 id="pengeluaran-harian-title" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Pengeluaran harian</h2>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]" style={{ color: 'var(--text-muted)' }}>
          <LegendDot color={colors.ok}>Dalam jatah</LegendDot>
          {safeDaily > 0 && <LegendDot color={colors.over}>Lewat jatah</LegendDot>}
          {safeDaily > 0 && (
            <span className="inline-flex items-center gap-1.5">
              <svg width="18" height="2" aria-hidden="true"><line x1="0" y1="1" x2="18" y2="1" style={{ stroke: 'var(--text-muted)', strokeWidth: 1.5, strokeDasharray: '2 3' }} /></svg>
              {rpCompact(safeDaily)}/hari
            </span>
          )}
        </div>
      </div>
      <div className="mt-4 h-[230px]" role="img"
        aria-label={`Pengeluaran harian periode ini: ${spentDays} hari ada belanja${safeDaily > 0 ? `, ${overDays} hari lewat batas aman ${rpCompact(safeDaily)} per hari` : ''}.`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 4 }} barCategoryGap="22%">
            <CartesianGrid vertical={false} style={{ stroke: 'var(--border)' }} strokeOpacity={0.6} />
            <XAxis dataKey="day" ticks={ticks} interval={0} tickLine={false} axisLine={false} height={24}
              tick={<XTick series={series} today={today} />} />
            <YAxis domain={[0, top]} ticks={[0, step, top]} tickLine={false} axisLine={false} width={48} tick={<YTick />} />
            <Tooltip content={<ChartTooltip safeDaily={safeDaily} />} cursor={{ fill: isDark ? 'rgba(148,163,184,0.08)' : 'rgba(15,23,42,0.04)' }} />
            {safeDaily > 0 && (
              <ReferenceLine y={safeDaily} ifOverflow="extendDomain"
                style={{ stroke: 'var(--text-muted)' }} strokeWidth={1.5} strokeDasharray="2 4" />
            )}
            <Bar dataKey="value" isAnimationActive={false} shape={<BarShape colors={colors} />} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
