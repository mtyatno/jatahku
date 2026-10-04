import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import { formatShort, formatShortSigned, formatCurrency, titleCase } from '../lib/utils';
import ExportButtons from '../components/ExportButtons';
import Onboarding from '../components/Onboarding';
import { Icon, EnvelopeIcon, BRAND, renderWithIcons } from '../components/Icon';
import { InfoTooltip } from '../components/InfoTooltip';
import { KpiCard, Meter, FundsBar, EnvelopeStrip, SpendSparkline, kpiPalette } from '../components/KpiCard';
import { envelopeStrip, fundsBreakdown, freeShare, savingsProgress, dailySeries, localDateStr } from '../lib/kpiVisuals';
import { fundingState } from '../lib/envelopeFunding';
import { formatLastChecked } from '../lib/balanceCheck';
import {
  ComposedChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
  PieChart, Pie, Cell,
} from 'recharts';

const COLORS = ['#0F6E56', '#BA7517', '#1D9E75', '#D85A30', '#534AB7', '#993556', '#378ADD', '#639922'];

const TOOLTIP_STYLE = {
  background: 'var(--card-bg)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  color: 'var(--text)',
};
const TOOLTIP_LABEL_STYLE = { color: 'var(--text-muted)', fontSize: 11 };
const TOOLTIP_ITEM_STYLE = { color: 'var(--text)' };

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2 shadow-sm">
      <p className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>Tgl {label}</p>
      {payload.map((p, i) => p.value > 0 && (
        <p key={i} className="text-sm font-semibold" style={{color: p.color}}>
          {formatCurrency(p.value)}
        </p>
      ))}
    </div>
  );
}

function buildDailyData(raw, prediction, periodDates = null) {
  const pStart = prediction?.period_start || periodDates?.period_start;
  const pEnd = prediction?.period_end || periodDates?.period_end;
  if (!pStart) {
    return raw.map(x => ({ date: new Date(x.date).getDate() + '', total: x.total, isFuture: false }));
  }
  const spendMap = {};
  raw.forEach(d => { spendMap[d.date] = d.total; });

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = new Date(pStart);
  const end = new Date(pEnd);
  const result = [];
  const cur = new Date(start);
  while (cur <= end) {
    const dateStr = cur.toISOString().split('T')[0];
    const isFuture = cur > today;
    result.push({
      date: cur.getDate() + '',
      dateStr,
      total: spendMap[dateStr] || 0,
      isFuture,
    });
    cur.setDate(cur.getDate() + 1);
  }
  return result;
}

function CalcRow({ label, value, strong, color }) {
  return (
    <div className="flex justify-between gap-3 py-0.5">
      <span>{label}</span>
      <span className={strong ? 'font-semibold' : ''} style={color ? { color } : undefined}>{value}</span>
    </div>
  );
}

function AdviceCalc({ detail, clr }) {
  const d = detail;
  const excluded = [
    d.excluded_adjustment > 0 && `penyesuaian cocokkan saldo ${formatCurrency(d.excluded_adjustment)}`,
    d.excluded_recurring > 0 && `tagihan rutin ${formatCurrency(d.excluded_recurring)}`,
    d.excluded_outlier > 0 && `belanja besar satu kali ${formatCurrency(d.excluded_outlier)}`,
  ].filter(Boolean);
  return (
    <div className="mt-2 rounded-lg px-3 py-2 text-xs" style={{ background: clr.inset, color: clr.text }}>
      <CalcRow label="Dana amplop" value={formatCurrency(d.available)} />
      <CalcRow label="Terpakai" value={`− ${formatCurrency(d.spent)}`} />
      <CalcRow label="Sisa" value={formatCurrency(d.remaining)} strong />
      <div className="my-1.5 border-t" style={{ borderColor: clr.border }} />
      <CalcRow label={`Hari tersisa${d.period_end ? ` (s.d. ${d.period_end})` : ''}`} value={`${d.days_remaining} hari`} />
      {d.remaining > 0 && (
        <CalcRow label="Batas aman = sisa ÷ hari tersisa" value={`${formatCurrency(d.safe_daily)}/hari`} strong color={clr.accent} />
      )}
      <CalcRow label={`Kecepatan sekarang (${d.days_used} hari berjalan)`} value={`${formatCurrency(d.daily_rate)}/hari`} />
      {excluded.length > 0 && (
        <p className="mt-1.5" style={{ color: clr.muted }}>Tidak dihitung sebagai kebiasaan harian: {excluded.join(', ')}.</p>
      )}
    </div>
  );
}

const ACTION_TYPES = ['env_depletion', 'subscription_pressure'];

function AdvisorRow({ open, onToggle, dot, clr, children, title }) {
  return (
    <div className="py-3" style={{ borderColor: clr.border }}>
      <button type="button" onClick={onToggle} aria-expanded={open}
        className="w-full flex items-center gap-3 text-left">
        {dot && <span className="w-2 h-2 rounded-full shrink-0" style={{ background: dot }} />}
        <span className="flex-1 min-w-0 text-sm font-medium leading-snug" style={{ color: clr.title }}>{title}</span>
        <span className="text-xs shrink-0 transition-transform" style={{ color: clr.muted, transform: open ? 'rotate(180deg)' : 'none' }}>▾</span>
      </button>
      {open && <div className={dot ? 'pl-5' : ''}>{children}</div>}
    </div>
  );
}

function HeroAdvisor({ cards, advisorError, prediction, todaySpent, goals }) {
  const { mode } = useTheme();
  const isDark = mode === 'dark';
  const [openId, setOpenId] = useState(null);
  const toggle = (id) => setOpenId(openId === id ? null : id);

  const safeDaily = prediction?.safe_daily || 0;
  const hasPrediction = prediction && (prediction.total_available ?? prediction.total_allocated) > 0;
  const showToday = hasPrediction && safeDaily > 0;
  const overToday = todaySpent > safeDaily;
  const leftToday = Math.floor(Math.abs(safeDaily - todaySpent) / 1000) * 1000;
  const items = (cards || [])
    .filter(c => ACTION_TYPES.includes(c.type) && (c.severity === 'danger' || c.severity === 'warning'))
    .slice(0, 2);
  const activeGoals = (goals || []).filter(g => !g.is_achieved);
  if (!showToday && !items.length && !activeGoals.length && !advisorError) return null;

  const clr = isDark ? {
    bg: '#1e293b', border: '#334155', accent: '#34d399', title: '#f1f5f9', text: '#cbd5e1', muted: '#94a3b8', inset: '#0f172a',
    dot: { danger: '#f87171', warning: '#fbbf24' },
  } : {
    bg: '#FFFFFF', border: '#E2E8F0', accent: '#0F6E56', title: '#1E293B', text: '#475569', muted: '#64748B', inset: '#F1F5F9',
    dot: { danger: '#DC2626', warning: '#D97706' },
  };

  return (
    <div className="rounded-2xl px-5 py-4" style={{
      background: clr.bg, border: `1px solid ${clr.border}`,
      boxShadow: isDark ? '0 4px 20px rgba(0,0,0,0.3)' : '0 1px 3px rgba(15,110,86,0.06)',
    }}>
      <div className="flex items-center gap-2 mb-1">
        <Icon name="advisor" size={18} color={clr.accent} />
        <h2 className="font-display font-bold text-sm" style={{ color: clr.title }}>AI Advisor</h2>
      </div>

      {advisorError && (
        <p className="text-xs py-2" style={{ color: clr.muted }}>Saran sementara tidak tersedia.</p>
      )}

      <div className="divide-y" style={{ borderColor: clr.border }}>
        {showToday && (
          <AdvisorRow clr={clr} open={openId === 'today'} onToggle={() => toggle('today')}
            title={overToday
              ? <>Hari ini sudah lewat <b>{formatCurrency(leftToday)}</b> dari jatah harian</>
              : <>Hari ini masih aman belanja <b>{formatCurrency(leftToday)}</b></>}>
            <div className="mt-2 rounded-lg px-3 py-2 text-xs" style={{ background: clr.inset, color: clr.text }}>
              <CalcRow label="Sisa bebas semua amplop" value={formatCurrency(prediction.free)} />
              <CalcRow label="Hari tersisa" value={`${prediction.days_left} hari`} />
              <CalcRow label="Jatah per hari = sisa ÷ hari" value={formatCurrency(safeDaily)} strong color={clr.accent} />
              <CalcRow label="Terpakai hari ini" value={`− ${formatCurrency(todaySpent)}`} />
            </div>
          </AdvisorRow>
        )}

        {items.map(card => (
          <AdvisorRow key={card.id} clr={clr} dot={clr.dot[card.severity]}
            open={openId === card.id} onToggle={() => toggle(card.id)}
            title={renderWithIcons(card.title, 15, clr.title)}>
            <p className="text-xs mt-1.5 leading-relaxed" style={{ color: clr.text }}>{card.body}</p>
            {card.detail
              ? <AdviceCalc detail={card.detail} clr={clr} />
              : (card.evidence?.length > 0 && (
                <div className="mt-2 rounded-lg px-3 py-2 text-xs space-y-0.5" style={{ background: clr.inset, color: clr.text }}>
                  {card.evidence.map((l, i) => <p key={i}>{l}</p>)}
                </div>
              ))}
            {card.primary_action?.route && (
              <Link to={card.primary_action.route} className="inline-block text-xs font-medium mt-2 hover:underline" style={{ color: clr.accent }}>
                {card.primary_action.label} →
              </Link>
            )}
          </AdvisorRow>
        ))}

        {activeGoals.length > 0 && (
          <AdvisorRow clr={clr} open={openId === 'goals'} onToggle={() => toggle('goals')}
            title={<>Target menabung: <b>{activeGoals.length}</b> berjalan</>}>
            <div className="mt-2 space-y-2.5">
              {activeGoals.map(goal => {
                const pct = Math.round(goal.progress_pct);
                return (
                  <div key={goal.id}>
                    <div className="flex items-center gap-2 text-xs mb-1" style={{ color: clr.text }}>
                      <EnvelopeIcon value={goal.envelope_emoji} size={14} color={SAVING_ACCENT} />
                      <span className="truncate">{goal.name}</span>
                      <span className="font-semibold ml-auto">{pct}%</span>
                    </div>
                    <div className="h-1.5 rounded-full overflow-hidden" style={{ background: isDark ? '#334155' : '#F1F5F9' }}>
                      <div className="h-full rounded-full" style={{ width: `${Math.max(pct, 2)}%`, background: SAVING_ACCENT }} />
                    </div>
                  </div>
                );
              })}
              <Link to="/envelopes" className="inline-block text-xs font-medium hover:underline" style={{ color: clr.accent }}>Atur target →</Link>
            </div>
          </AdvisorRow>
        )}
      </div>
    </div>
  );
}



// Savings accent — distinct from spending-risk colors (green/amber/red)
const SAVING_ACCENT = '#6366F1';
const SAVING_TRACK = 'rgba(99,102,241,0.16)';

function EnvelopeRow({ env, goal }) {
  const allocated = Number(env.allocated);
  const rollover = Number(env.rollover || 0);
  const spent = Number(env.spent);
  const reserved = Number(env.reserved || 0);
  const free = Number(env.free || env.remaining);
  const isSaving = env.purpose === 'saving' || env.purpose === 'sinking_fund';

  // ── Saving / sinking fund: balance-vs-target, NOT spent-vs-budget ──
  if (isSaving) {
    const balance = goal ? Number(goal.current_balance) : free;
    if (goal) {
      const pct = Math.round(goal.progress_pct);
      const target = Number(goal.target_amount);
      const achieved = goal.is_achieved;
      const toTarget = Math.max(target - Number(goal.current_balance), 0);
      const accent = achieved ? '#059669' : SAVING_ACCENT;
      return (
        <div className={`card hover:border-brand-200 transition-colors ${env.is_locked ? 'opacity-60' : ''}`}>
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-center gap-2">
              <EnvelopeIcon value={env.emoji} size={22} color={achieved ? '#059669' : SAVING_ACCENT} />
              <span className="font-semibold text-sm">{titleCase(env.name)}</span>
              {achieved && (
                <span className="text-xs px-1.5 py-0.5 rounded-md font-medium" style={{ background: '#ECFDF5', color: '#059669' }}>🎉 Tercapai</span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <span className="font-display font-bold text-sm" style={{ color: accent }}>{formatShort(balance)}</span>
              <InfoTooltip text="Saldo saat ini untuk envelope tabungan" position="left" />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-2 rounded-full overflow-hidden flex-1" style={{ background: SAVING_TRACK }}>
              <div className="h-full rounded-full transition-all duration-500"
                style={{ width: `${Math.min(Math.max(pct, 2), 100)}%`, background: accent }} />
            </div>
            <span className="text-xs font-semibold w-12 text-right" style={{ color: accent }}>{pct}% target</span>
          </div>
          <div className="flex justify-between mt-1 text-xs text-gray-400">
            <span>Target {formatShort(target)}</span>
            <span>{achieved ? 'Lengkap 🎯' : `Kurang ${formatShort(toTarget)}`}</span>
          </div>
          {goal.monthly_needed != null && !achieved && (
            <p className="text-xs mt-0.5" style={{ color: SAVING_ACCENT }}>
              ≈ {formatShort(goal.monthly_needed)}/bln biar tepat waktu
            </p>
          )}
        </div>
      );
    }
    // Saving envelope without a target yet
    return (
      <div className={`card hover:border-brand-200 transition-colors ${env.is_locked ? 'opacity-60' : ''}`}>
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-2">
            <EnvelopeIcon value={env.emoji} size={22} color={SAVING_ACCENT} />
            <span className="font-semibold text-sm">{titleCase(env.name)}</span>
            <span className="text-xs px-1.5 py-0.5 rounded-md font-medium" style={{ background: SAVING_TRACK, color: SAVING_ACCENT }}>Menabung</span>
          </div>
          <span className="font-display font-bold text-sm" style={{ color: SAVING_ACCENT }}>{formatShort(balance)}</span>
        </div>
        <p className="text-xs text-gray-400 mb-1">Saldo tabungan · belum ada target</p>
        <Link to="/envelopes" className="text-xs font-medium text-brand-600 hover:underline">+ Tambah target</Link>
      </div>
    );
  }

  // ── Expense: spent-vs-budget (risk colors) ──
  const ratio = env.spent_ratio;
  const isUnfunded = allocated <= 0 && rollover === 0;
  const remaining = allocated + rollover - spent;
  const fstate = fundingState(env);

  const barColor = fstate === 'overspent' ? 'bg-danger-400' : fstate === 'reserve_short' ? 'bg-amber-400' : ratio >= 0.7 ? 'bg-amber-400' : 'bg-brand-400';
  const freeColor = fstate === 'overspent' ? 'text-danger-400' : fstate === 'reserve_short' ? 'text-amber-500' : ratio >= 0.7 ? 'text-amber-400' : 'text-brand-600';

  const badge = fstate === 'overspent'
    ? <span className="text-xs px-1.5 py-0.5 rounded-md bg-red-100 text-danger-400 font-semibold">Habis</span>
    : fstate === 'reserve_short'
    ? <span className="text-xs px-1.5 py-0.5 rounded-md bg-amber-50 text-amber-600 font-medium">⚠️ kurang tagihan</span>
    : ratio >= 0.9
    ? <span className="text-xs px-1.5 py-0.5 rounded-md bg-red-50 text-danger-400 font-medium">🔴 {Math.round(ratio * 100)}%</span>
    : ratio >= 0.7
    ? <span className="text-xs px-1.5 py-0.5 rounded-md bg-amber-50 text-amber-600 font-medium">🟡 {Math.round(ratio * 100)}%</span>
    : null;

  return (
    <div className={`card hover:border-brand-200 transition-colors ${env.is_locked ? 'opacity-60' : ''}`}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <EnvelopeIcon value={env.emoji} size={22} />
          <span className="font-semibold text-sm">{titleCase(env.name)}</span>
          {badge}
        </div>
        <div className="flex items-center gap-1">
          <span className={`font-display font-bold text-sm ${freeColor}`}>{formatShort(free)}</span>
          <InfoTooltip text="Dana yang tersisa untuk dibelanjakan (alokasi - pengeluaran - reserve)" position="left" />
        </div>
      </div>
      {isUnfunded ? (
        <div className="bg-gray-50 text-gray-400 text-xs px-3 py-2 rounded-lg">Belum ada dana.</div>
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
            <span className="flex items-center gap-1">
              Terpakai {formatShort(spent)}
              <InfoTooltip text="Pengeluaran di periode ini" position="top" />
            </span>
            {reserved > 0 && <span className="flex items-center gap-1">
              ⏳ {formatShort(reserved)}
              <InfoTooltip text="Tagihan yang sudah disimpan untuk periode depan" position="top" />
            </span>}
            <span className="flex items-center gap-1">
              Dana {formatShort(allocated)}
              <InfoTooltip text="Alokasi periode ini untuk envelope" position="top" />
            </span>
          </div>
          {rollover !== 0 && (
            <p className={`text-xs mt-0.5 ${rollover > 0 ? 'text-brand-500' : 'text-danger-400'}`}>
              <span className="flex items-center gap-1">
                {rollover > 0
                  ? `🔄 +${formatShort(rollover)} rollover`
                  : `🔄 ${formatShort(Math.abs(rollover))} minus dari periode lalu`}
                <InfoTooltip text={rollover > 0 ? "Sisa periode lalu yang terbawa ke periode ini" : "Kekurangan dari periode lalu yang dikurangi dari periode ini"} position="top" />
              </span>
            </p>
          )}
          {fstate === 'reserve_short' && (
            <p className="text-xs text-amber-500 mt-0.5 flex items-center gap-1">
              <span>
                ⚠️ Reserve tagihan {formatShort(reserved)} &gt; sisa {formatShort(remaining)} — kurang {formatShort(reserved - remaining)}
              </span>
              <InfoTooltip text="Uang yang disimpan untuk tagihan lebih besar dari dana tersisa. Alokasikan lagi untuk menghindari keterlambatan pembayaran" position="top" />
              {' '}<Link to="/allocate" className="font-medium hover:underline">Alokasikan lagi →</Link>
            </p>
          )}
        </>
      )}
    </div>
  );
}

function sortEnvelopes(envs) {
  return [...envs].sort((a, b) => {
    const aFunded = Number(a.allocated) > 0;
    const bFunded = Number(b.allocated) > 0;
    if (aFunded && !bFunded) return -1;
    if (!aFunded && bFunded) return 1;
    return b.spent_ratio - a.spent_ratio;
  });
}

export default function Dashboard() {
  const { user } = useAuth();
  const { mode } = useTheme();
  const [envelopes, setEnvelopes] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [periodLoading, setPeriodLoading] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [daily, setDaily] = useState([]);
  const [breakdown, setBreakdown] = useState([]);
  const [prediction, setPrediction] = useState(null);
  const [periods, setPeriods] = useState([]);
  const [periodIdx, setPeriodIdx] = useState(null);
  const [advisorInsights, setAdvisorInsights] = useState(null);
  const [goals, setGoals] = useState([]);
  const [streak, setStreak] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [celebrate, setCelebrate] = useState(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [balanceStatus, setBalanceStatus] = useState(null);
  const [showOnboardingGuide, setShowOnboardingGuide] = useState(false);

  useEffect(() => {
    const mode = sessionStorage.getItem('onboarded_income_mode');
    if (mode === 'daily' || mode === 'weekly') {
      setShowOnboardingGuide(true);
    }
  }, []);

  useEffect(() => {
    const onAdded = () => setRefreshTick(t => t + 1);
    window.addEventListener('jatahku:txn-added', onAdded);
    return () => window.removeEventListener('jatahku:txn-added', onAdded);
  }, []);

  useEffect(() => {
    api.getBalanceCheckStatus().then(setBalanceStatus);
  }, [refreshTick]);

  useEffect(() => {
    Promise.all([
      api.getPeriods(12),
      api.getAdvisorInsights(),
      api.getGoals(),
    ]).then(([p, insights, gls]) => {
      setPeriods(p);
      setAdvisorInsights(insights);
      setGoals(gls);
      setPeriodIdx(p.length - 1);
    });
    api.request('/user/streak').then(r => r.ok ? r.json() : null).then(s => {
      if (!s) return;
      setStreak(s);
      // Celebrate each milestone once per device.
      const MILESTONES = [3, 7, 14, 30, 50, 100, 150, 200, 365];
      if (MILESTONES.includes(s.current_streak)) {
        const key = `jatahku_celebrated_${s.current_streak}`;
        if (!localStorage.getItem(key)) {
          setCelebrate(s.current_streak);
          localStorage.setItem(key, '1');
        }
      }
    });
    api.request('/household/leaderboard').then(r => r.ok ? r.json() : []).then(setLeaderboard);
  }, []);

  // Reload data whenever selected period changes
  useEffect(() => {
    if (periods.length === 0 || periodIdx === null) return;
    const isCurrentPeriod = periodIdx === periods.length - 1;
    const period = periods[periodIdx];
    // Pass null for current period so backend uses its own default (handles edge cases)
    const ps = isCurrentPeriod ? null : period.period_start;
    const pe = isCurrentPeriod ? null : period.period_end;

    setPeriodLoading(true);
    Promise.all([
      api.getEnvelopeSummary(ps, pe),
      api.getTransactions(null, 10, period.period_start, period.period_end),
      api.getDailySpending(ps, pe),
      api.getEnvelopeBreakdown(ps, pe),
      isCurrentPeriod
        ? api.request('/analytics/prediction').then(r => r.ok ? r.json() : null)
        : Promise.resolve(null),
    ]).then(([env, txn, d, b, pred]) => {
      setEnvelopes(env);
      setTransactions(txn);
      setDaily(d);
      setBreakdown(b.filter(x => x.spent > 0));
      setPrediction(pred);
      setPeriodLoading(false);
      setLoading(false);
      if (env.length === 0 && isCurrentPeriod) setShowOnboarding(true);
    });
  }, [periodIdx, periods, refreshTick]);

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;
  if (showOnboarding) return <Onboarding onDone={() => { setShowOnboarding(false); window.location.reload(); }} />;

  const isCurrentPeriod = periodIdx === periods.length - 1;
  const selectedPeriod = periods[periodIdx];

  const shared = sortEnvelopes(envelopes.filter(e => !e.is_personal));
  const personal = sortEnvelopes(envelopes.filter(e => e.is_personal));

  const goalByEnv = {};
  goals.forEach(g => { goalByEnv[g.envelope_id] = g; });

  const totalAllocated = envelopes.reduce((s, e) => s + Number(e.allocated), 0);
  const totalRollover = envelopes.reduce((s, e) => s + Number(e.rollover || 0), 0);
  const totalSpent = envelopes.reduce((s, e) => s + Number(e.spent), 0);
  const totalRemaining = envelopes.reduce((s, e) => s + Number(e.free ?? e.remaining), 0);
  const savingEnvelopes = envelopes.filter(e => e.purpose === 'saving' || e.purpose === 'sinking_fund');
  const totalSaving = savingEnvelopes.reduce((s, e) => s + Number(e.free ?? e.remaining), 0);
  const sharedSaving = savingEnvelopes.filter(e => !e.is_personal).reduce((s, e) => s + Number(e.free ?? e.remaining), 0);
  const personalSaving = totalSaving - sharedSaving;
  const sharedSavingGoals = goals.filter(g => savingEnvelopes.some(e => e.id === g.envelope_id && !e.is_personal)).length;
  const personalSavingGoals = goals.filter(g => savingEnvelopes.some(e => e.id === g.envelope_id && e.is_personal)).length;
  const sisaBebas = totalRemaining - totalSaving;

  const periodLabel = selectedPeriod?.label
    || (prediction?.period_start
      ? `${new Date(prediction.period_start).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })} – ${new Date(prediction.period_end).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}`
      : new Date().toLocaleString('id-ID', { month: 'long', year: 'numeric' }));
  const daysLeft = prediction?.days_left ?? 0;

  const chartData = buildDailyData(daily, prediction, selectedPeriod);
  const todayStr = new Date().toISOString().split('T')[0];
  const todaySpent = daily.find(d => d.date === todayStr)?.total || 0;

  const isDark = mode === 'dark';
  const kc = kpiPalette(isDark);
  const fundsTotal = totalAllocated + totalRollover;
  const spendSeries = dailySeries(
    daily,
    prediction?.period_start || selectedPeriod?.period_start,
    prediction?.period_end || selectedPeriod?.period_end,
    localDateStr(),
  );
  const funds = fundsBreakdown(envelopes);
  const freePart = freeShare(envelopes);
  const sharedProgress = savingsProgress(goals, envelopes, false);
  const personalProgress = savingsProgress(goals, envelopes, true);
  const pct = (v) => (v > 0 && v < 0.005 ? '<1%' : `${Math.round(v * 100)}%`);

  const milestoneLabel = (n) => ({
    3: 'Kebiasaan baik dimulai 🌱', 7: 'Seminggu penuh disiplin!', 14: '2 minggu konsisten 💪',
    30: 'Sebulan penuh nyatat! 🏆', 50: '50 hari, luar biasa 🌟', 100: '100 hari, kamu legend 👑',
    150: '150 hari 🚀', 200: '200 hari, level dewa 🧘', 365: 'SATU TAHUN PENUH 🎉',
  }[n] || `${n} hari berturut-turut!`);

  return (
    <div className="space-y-6">
      {celebrate && (
        <div
          className="rounded-xl p-4 flex items-center justify-between gap-3 animate-pulse"
          style={{ background: 'linear-gradient(90deg,#FEF3C7,#FDE68A)', border: '1px solid #FCD34D' }}
        >
          <div>
            <p className="font-bold text-amber-900 flex items-center gap-1.5"><Icon name="fire" size={18} weight="fill" /> Streak {celebrate} hari!</p>
            <p className="text-sm text-amber-800">{milestoneLabel(celebrate)}</p>
          </div>
          <button
            onClick={() => setCelebrate(null)}
            className="text-amber-700 text-sm px-3 py-1 rounded-lg hover:bg-amber-200/60 flex-shrink-0"
          >Tutup</button>
        </div>
      )}
      {showOnboardingGuide && (
        <div className="card border-brand-200 bg-brand-50/40 p-4 flex items-start justify-between gap-3">
          <div className="flex gap-3">
            <span className="text-2xl">🎉</span>
            <div>
              <h4 className="font-semibold text-brand-900 text-sm">Amplop Jatahmu Sudah Siap!</h4>
              <p className="text-xs text-brand-700 mt-1">
                Target jatah bulanan sudah terpasang. Tiap kali selesai narik order atau menerima uang, tekan tombol <strong>+ Pemasukan</strong> untuk membagi uang ke amplop-amplopmu.
              </p>
            </div>
          </div>
          <button
            onClick={() => {
              sessionStorage.removeItem('onboarded_income_mode');
              setShowOnboardingGuide(false);
            }}
            className="text-gray-400 hover:text-gray-600 text-sm px-2 py-1"
          >
            ✕
          </button>
        </div>
      )}
      <div>
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-2xl font-display font-bold">Hai, {user?.name || 'User'}</h1>
          {streak && streak.current_streak >= 1 && (
            <span
              className="text-sm px-2.5 py-1 rounded-full font-semibold flex-shrink-0 inline-flex items-center gap-1"
              style={{ background: streak.logged_today ? '#FEF3C7' : '#F3F4F6', color: streak.logged_today ? '#92400E' : '#6B7280' }}
              title={`Rekor ${streak.longest_streak} hari · total ${streak.total_logged_days} hari tercatat`}
            >
              <Icon name="fire" size={14} weight="fill" /> {streak.current_streak} hari
            </span>
          )}
        </div>
        {/* Period Navigator */}
        <div className="flex items-center gap-1 mt-1">
          <button
            onClick={() => setPeriodIdx(i => i - 1)}
            disabled={periodIdx === 0}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-500 text-sm leading-none"
            aria-label="Periode sebelumnya"
          >←</button>
          <span className="text-sm text-gray-500">{periodLabel}{isCurrentPeriod && daysLeft > 0 ? ` · ${daysLeft} hari lagi` : ''}</span>
          {isCurrentPeriod && (
            <span className="text-xs px-1.5 py-0.5 bg-brand-50 text-brand-600 rounded font-medium">Sekarang</span>
          )}
          <button
            onClick={() => setPeriodIdx(i => i + 1)}
            disabled={isCurrentPeriod}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-500 text-sm leading-none"
            aria-label="Periode berikutnya"
          >→</button>
          {periodLoading && <span className="text-xs text-gray-400 ml-1">...</span>}
        </div>
      </div>

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <ExportButtons
          periodStart={selectedPeriod?.period_start}
          periodEnd={selectedPeriod?.period_end}
          periodLabel={selectedPeriod?.label}
        />
        {isCurrentPeriod && leaderboard.length >= 2 && (
          <div className="flex items-center gap-3 px-3 py-1.5 rounded-xl bg-white border border-gray-200">
            <span className="text-xs font-medium text-gray-400 inline-flex items-center gap-1"><Icon name="trophy" size={14} /> Papan disiplin</span>
            <div className="flex items-center gap-3">
              {leaderboard.map((m, i) => {
                const medal = ['🥇', '🥈', '🥉'][i] || '';
                return (
                  <span key={m.user_id} className="flex items-center gap-1 text-xs">
                    <span className="shrink-0">{medal}</span>
                    <span className={m.is_me ? 'font-semibold text-brand-600' : 'text-gray-500'}>
                      {m.name.split(' ')[0]}
                    </span>
                    <span className="font-medium text-gray-600">{m.current_streak > 0 ? `${m.current_streak}h` : '—'}</span>
                    {m.logged_today && <span className="text-[10px]" title="Sudah catat">✅</span>}
                  </span>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <KpiCard
          label="Dana dialokasi" icon="wallet" color={kc.brand} isDark={isDark}
          info="Alokasi periode ini ditambah sisa dari periode lalu. Batang: posisi dana itu sekarang, dari kiri: terpakai, tagihan, tabungan, bebas. Sentuh batang untuk angkanya."
          value={formatShort(totalAllocated)}
          sub={totalRollover > 0
            ? `+${formatShort(totalRollover)} rollover`
            : totalRollover < 0
            ? <span className="text-danger-400">−{formatShort(Math.abs(totalRollover))} dari periode lalu</span>
            : 'Belum ada rollover'}
        >
          <FundsBar
            track={kc.track}
            ariaLabel={`Terpakai ${formatShort(funds.spent)}, tagihan ${formatShort(funds.reserved)}, tabungan ${formatShort(funds.saving)}, bebas ${formatShort(funds.free)}`}
            parts={[
              { key: 'spent', label: 'Terpakai', value: funds.spent, color: kc.amber },
              { key: 'reserved', label: 'Tagihan', value: funds.reserved, color: kc.reserved },
              { key: 'saving', label: 'Tabungan', value: funds.saving, color: kc.indigo },
              { key: 'free', label: 'Bebas', value: funds.free, color: kc.brandMeter },
            ]}
          />
        </KpiCard>
        <KpiCard
          label="Terpakai" icon="expense" color={kc.amber} isDark={isDark}
          info="Pengeluaran periode ini termasuk penyesuaian cocokkan saldo. Garis: belanja per hari sejak awal periode. Sentuh garis untuk angka per hari."
          value={formatShort(totalSpent)}
          sub={fundsTotal > 0 ? `${Math.round(totalSpent / fundsTotal * 100)}% dari dana` : 'Belum ada dana'}
        >
          <SpendSparkline series={spendSeries} color={kc.amber} fill={kc.amberFill} track={kc.track} ring="var(--card-bg)" />
        </KpiCard>
        <KpiCard
          label="Sisa bebas" icon="coins" color={kc.brand} isDark={isDark}
          info="Total saldo amplop dikurangi amplop tabungan dan uang yang disimpan untuk tagihan. Batang: porsi dana belanja yang masih bebas."
          value={formatShortSigned(sisaBebas)}
          valueClassName={sisaBebas < 0 ? 'text-danger-400' : ''}
          sub={isCurrentPeriod && prediction?.safe_daily > 0 ? `≈${formatShort(prediction.safe_daily)}/hari aman` : daysLeft > 0 ? `${daysLeft} hari lagi` : 'Periode selesai'}
        >
          <Meter
            value={freePart} color={kc.brandMeter} track={sisaBebas < 0 ? kc.dangerTrack : kc.brandTrack}
            label={freePart != null ? pct(freePart) : null}
            ariaLabel={freePart != null ? `${pct(freePart)} dana belanja masih bebas` : 'Belum ada dana belanja'}
          />
        </KpiCard>
        <KpiCard
          label="Tabungan shared" icon="piggy" color={kc.indigo} isDark={isDark}
          info="Saldo amplop tabungan yang dibagikan dengan anggota rumah tangga lainnya. Batang: kemajuan menuju target."
          value={formatShort(sharedSaving)}
          sub={sharedSavingGoals > 0 ? `${sharedSavingGoals} target aktif` : 'Tanpa target'}
        >
          <Meter
            value={sharedProgress} color={kc.indigo} track={kc.indigoTrack}
            label={sharedProgress != null ? pct(sharedProgress) : null}
            ariaLabel={sharedProgress != null ? `${pct(sharedProgress)} dari target tercapai` : 'Belum ada target'}
          />
        </KpiCard>
        <KpiCard
          label="Tabungan personal" icon="piggy" color={kc.indigo} isDark={isDark}
          info="Saldo amplop tabungan pribadi Anda. Batang: kemajuan menuju target."
          value={formatShort(personalSaving)}
          sub={personalSavingGoals > 0 ? `${personalSavingGoals} target aktif` : 'Tanpa target'}
        >
          <Meter
            value={personalProgress} color={kc.indigo} track={kc.indigoTrack}
            label={personalProgress != null ? pct(personalProgress) : null}
            ariaLabel={personalProgress != null ? `${pct(personalProgress)} dari target tercapai` : 'Belum ada target'}
          />
        </KpiCard>
        <KpiCard
          label="Amplop aktif" icon="envelope" color={kc.slate} isDark={isDark}
          info="Jumlah amplop yang sedang Anda gunakan (shared dan personal). Tiap titik satu amplop: merah habis, kuning hampir habis, hijau aman, ungu tabungan, abu-abu belum ada dana. Sentuh titik untuk nama amplopnya."
          value={envelopes.length}
          sub={`${shared.length} shared · ${personal.length} personal`}
        >
          <EnvelopeStrip strip={envelopeStrip(envelopes)} colors={kc.status} />
        </KpiCard>
      </div>

      {isCurrentPeriod && (
        <div className="flex justify-end -mt-1">
          <button type="button"
            onClick={() => window.dispatchEvent(new CustomEvent('jatahku:open-action', { detail: 'balance' }))}
            className="inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand-600">
            <Icon name="balance" size={14} />
            <span>Cocokkan saldo · terakhir {formatLastChecked(balanceStatus?.last_checked_at)}</span>
          </button>
        </div>
      )}

      {/* Hero AI Advisor — today's status + strategic insights */}
      {isCurrentPeriod && (
        <HeroAdvisor
          cards={advisorInsights?.cards}
          advisorError={advisorInsights?._error}
          prediction={prediction}
          todaySpent={todaySpent}
          goals={goals}
        />
      )}

      {/* Daily spending chart + breakdown */}
      {(chartData.length > 0 || breakdown.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {chartData.length > 0 && (
            <div className="card">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-1">
                  <h3 className="font-semibold text-sm">Pengeluaran harian</h3>
                  <InfoTooltip text="Grafik pengeluaran harian selama periode ini. Garis merah adalah batas aman yang disarankan per hari" position="bottom" />
                </div>
                {prediction?.safe_daily > 0 && (
                  <span className="text-xs text-gray-400 flex items-center gap-1">
                    <span className="inline-block w-4 border-t-2 border-dashed border-danger-400"></span>
                    Batas aman {formatShort(prediction.safe_daily)}/hari
                  </span>
                )}
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <ComposedChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <XAxis dataKey="date" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={45}
                    tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
                  <Tooltip content={<CustomTooltip />} />
                  {prediction?.safe_daily > 0 && (
                    <ReferenceLine y={prediction.safe_daily} stroke="#E24B4A" strokeDasharray="4 3" strokeWidth={1.5}
                      label={{ value: '', position: 'right' }} />
                  )}
                  <Bar dataKey="total" name="Pengeluaran" radius={[3, 3, 0, 0]}
                    fill="#0F6E56"
                    shape={(props) => {
                      const { isFuture, ...rest } = props;
                      return <rect {...rest} fill={props.isFuture ? '#E5E7EB' : '#0F6E56'} rx={3} ry={3} />;
                    }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
          {breakdown.length > 0 && (
            <div className="card">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-1">
                  <h3 className="font-semibold text-sm">Breakdown amplop</h3>
                  <InfoTooltip text="Perbandingan pengeluaran antara amplop-amplop Anda dalam bentuk pie chart" position="bottom" />
                </div>
                <span className="text-xs text-gray-400">Total {formatShort(breakdown.reduce((s, x) => s + x.spent, 0))}</span>
              </div>
              <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                <div className="mx-auto sm:mx-0" style={{ width: 140, height: 140, flexShrink: 0 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={breakdown} dataKey="spent" nameKey="name" cx="50%" cy="50%"
                        outerRadius={58} innerRadius={34} paddingAngle={2}>
                        {breakdown.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                      </Pie>
                      <Tooltip formatter={v => formatCurrency(v)} contentStyle={TOOLTIP_STYLE} itemStyle={TOOLTIP_ITEM_STYLE} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 min-w-0 space-y-1.5">
                  {(() => {
                    const total = breakdown.reduce((s, x) => s + x.spent, 0);
                    return breakdown.map((item, i) => {
                      const pct = total > 0 ? Math.round((item.spent / total) * 100) : 0;
                      return (
                        <div key={i} className="flex items-center justify-between text-xs">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <div className="w-2.5 h-2.5 flex-shrink-0 rounded-sm" style={{ background: COLORS[i % COLORS.length] }} />
                            <span className="truncate inline-flex items-center gap-1"><EnvelopeIcon value={item.emoji} size={14} color="currentColor" /> {titleCase(item.name)}</span>
                          </div>
                          <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                            <span className="font-mono font-medium">{formatShort(item.spent)}</span>
                            <span className="text-gray-400">({pct}%)</span>
                          </div>
                        </div>
                      );
                    });
                  })()}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Envelopes — sorted by urgency, max 6 */}
      {shared.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display font-bold text-lg flex items-center gap-2"><Icon name="users" size={20} color={BRAND} /> Shared</h2>
            <Link to="/envelopes" className="text-sm text-brand-600 font-medium hover:underline">Lihat semua ({shared.length}) →</Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {[...shared].sort((a,b) => (b.spent_ratio||0) - (a.spent_ratio||0)).slice(0, 6).map(env => <EnvelopeRow key={env.id} env={env} goal={goalByEnv[env.id]} />)}
          </div>
        </div>
      )}
      {personal.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display font-bold text-lg flex items-center gap-2"><Icon name="lock" size={20} color={BRAND} /> Personal</h2>
            <Link to="/envelopes" className="text-sm text-brand-600 font-medium hover:underline">Lihat semua ({personal.length}) →</Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {[...personal].sort((a,b) => (b.spent_ratio||0) - (a.spent_ratio||0)).slice(0, 6).map(env => <EnvelopeRow key={env.id} env={env} goal={goalByEnv[env.id]} />)}
          </div>
        </div>
      )}

      {/* Transactions for selected period */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display font-bold text-lg">Transaksi{isCurrentPeriod ? ' terbaru' : ''}</h2>
          <Link to="/transactions" className="text-sm text-brand-600 font-medium hover:underline">Lihat semua →</Link>
        </div>
        {transactions.length === 0 ? (
          <div className="card text-center py-8"><p className="text-gray-400">Belum ada transaksi</p></div>
        ) : (
          <div className="card divide-y divide-gray-50">
            {transactions.slice(0, 8).map(txn => {
              const env = envelopes.find(e => e.id === txn.envelope_id);
              return (
                <div key={txn.id} className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
                  <div className="flex items-center gap-3">
                    <EnvelopeIcon value={env?.emoji} size={22} />
                    <div>
                      <p className="text-sm font-medium">{txn.description}</p>
                      <p className="text-xs text-gray-400">{env?.name} · {txn.source === 'telegram' ? '📱' : '🌐'}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="font-display font-bold text-sm text-gray-900">-{formatShort(txn.amount)}</p>
                    <p className="text-xs text-gray-400">
                      {new Date(txn.transaction_date).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}
                      {txn.created_at && <> · {new Date(txn.created_at).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}</>}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
