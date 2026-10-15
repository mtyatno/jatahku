import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import { formatShort, formatShortSigned, formatCurrency, titleCase } from '../lib/utils';
import ExportButtons from '../components/ExportButtons';
import SpendingEnvelopes from '../components/SpendingEnvelopes';
import SavingsTargets from '../components/SavingsTargets';
import RecentTransactions from '../components/RecentTransactions';
import SubscriptionsCard from '../components/SubscriptionsCard';
import Onboarding from '../components/Onboarding';
import { Icon, EnvelopeIcon, renderWithIcons } from '../components/Icon';
import { InfoTooltip } from '../components/InfoTooltip';
import { KpiTile, tileTones, kpiPalette } from '../components/KpiCard';
import { rpFull, rpCompact, dailyMeter, predictionOver, daysLabel, periodDayLabel, periodProgress, savingRateLabel, cashFlowLabel, billsProgress } from '../lib/kpiCards';
import { savingsProgress, localDateStr } from '../lib/kpiVisuals';
import { todayAdvice } from '../lib/advisorToday';
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
      {d.horizon_days ? (
        <>
          <CalcRow label="Sampai income berikutnya" value={`${d.horizon_days} hari`} />
          {d.remaining > 0 && (
            <CalcRow label={`Batas aman = sisa ÷ ${d.horizon_days} hari`} value={`${formatCurrency(d.safe_daily)}/hari`} strong color={clr.accent} />
          )}
        </>
      ) : (
        <>
          <CalcRow label={`Hari tersisa${d.period_end ? ` (s.d. ${d.period_end})` : ''}`} value={`${d.days_remaining} hari`} />
          {d.remaining > 0 && (
            <CalcRow label="Batas aman = sisa ÷ hari tersisa" value={`${formatCurrency(d.safe_daily)}/hari`} strong color={clr.accent} />
          )}
        </>
      )}
      <CalcRow label={`Kecepatan sekarang (${d.days_used} hari berjalan)`} value={`${formatCurrency(d.daily_rate)}/hari`} />
      {excluded.length > 0 && (
        <p className="mt-1.5" style={{ color: clr.muted }}>Tidak dihitung sebagai kebiasaan harian: {excluded.join(', ')}.</p>
      )}
    </div>
  );
}

const ACTION_TYPES = ['env_depletion', 'subscription_pressure'];

// Uang pecahan terkecil Rp100: jatah harian dan selisihnya dibulatkan ke bawah ke kelipatan Rp100.
const floorRp100 = (v) => Math.floor((Number(v) || 0) / 100) * 100;
// Format singkat angka kelipatan Rp100 tanpa membulatkan lagi: 1.900 → Rp1,9rb, 50.000 → Rp50rb.
const shortRp100 = (v) => (v >= 1000
  ? `Rp${(v / 1000).toLocaleString('id-ID', { maximumFractionDigits: 1 })}rb`
  : `Rp${v}`);

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

function HeroAdvisor({ cards, advisorError, prediction, safeDaily, todaySpent, goals }) {
  const { mode } = useTheme();
  const isDark = mode === 'dark';
  const [openId, setOpenId] = useState(null);
  const toggle = (id) => setOpenId(openId === id ? null : id);

  const today = todayAdvice(prediction, todaySpent, safeDaily);
  const overBy = floorRp100(today.overBy);
  const rounded = safeDaily !== (prediction?.safe_daily || 0) || overBy !== today.overBy;
  const items = (cards || [])
    .filter(c => ACTION_TYPES.includes(c.type) && (c.severity === 'danger' || c.severity === 'warning'))
    .slice(0, 2);
  const activeGoals = (goals || []).filter(g => !g.is_achieved);
  if (!today.show && !items.length && !activeGoals.length && !advisorError) return null;

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
        {today.show && (
          <AdvisorRow clr={clr} open={openId === 'today'} onToggle={() => toggle('today')}
            title={today.over
              ? <>Hari ini sudah lewat <b>{formatCurrency(overBy)}</b> dari jatah harian</>
              : <>Hari ini masih aman belanja <b>{formatCurrency(safeDaily)}</b></>}>
            <div className="mt-2 rounded-lg px-3 py-2 text-xs" style={{ background: clr.inset, color: clr.text }}>
              <CalcRow label="Sisa bebas semua amplop" value={formatCurrency(prediction.free)} />
              {today.perIncome ? (
                <>
                  <CalcRow label="Sampai income berikutnya" value={`${today.days} hari`} />
                  <CalcRow label={`Jatah hari ini = sisa ÷ ${today.days} hari`} value={formatCurrency(safeDaily)} strong color={clr.accent} />
                  <CalcRow label="Terpakai hari ini (sudah dipotong)" value={formatCurrency(todaySpent)} />
                </>
              ) : (
                <>
                  <CalcRow label="Hari tersisa" value={`${prediction.days_left} hari`} />
                  <CalcRow label="Jatah per hari = sisa ÷ hari" value={formatCurrency(safeDaily)} strong color={clr.accent} />
                  <CalcRow label="Terpakai hari ini" value={`− ${formatCurrency(todaySpent)}`} />
                </>
              )}
              {rounded && <p className="mt-1" style={{ color: clr.muted }}>Dibulatkan ke bawah ke kelipatan Rp100.</p>}
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
  const [subscriptions, setSubscriptions] = useState([]);
  const [showOnboardingGuide, setShowOnboardingGuide] = useState(false);
  const [recurringStats, setRecurringStats] = useState(null);

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
    api.getRecurring().then(r => setSubscriptions(Array.isArray(r) ? r : []));
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
      isCurrentPeriod
        ? api.request('/recurring/summary/period').then(r => r.ok ? r.json() : null)
        : Promise.resolve(null),
    ]).then(([env, txn, d, b, pred, recurStats]) => {
      setEnvelopes(env);
      setTransactions(txn);
      setDaily(d);
      setBreakdown(b.filter(x => x.spent > 0));
      setPrediction(pred);
      setRecurringStats(recurStats);
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

  const totalAllocated = envelopes.reduce((s, e) => s + Number(e.allocated), 0);
  const totalRollover = envelopes.reduce((s, e) => s + Number(e.rollover || 0), 0);
  const totalSpent = envelopes.reduce((s, e) => s + Number(e.spent), 0);
  const totalRemaining = envelopes.reduce((s, e) => s + Number(e.free ?? e.remaining), 0);
  const savingEnvelopes = envelopes.filter(e => e.purpose === 'saving' || e.purpose === 'sinking_fund');
  const spending = sortEnvelopes(envelopes.filter(e => !savingEnvelopes.includes(e)));
  const totalSaving = savingEnvelopes.reduce((s, e) => s + Number(e.free ?? e.remaining), 0);
  const sharedSaving = savingEnvelopes.filter(e => !e.is_personal).reduce((s, e) => s + Number(e.free ?? e.remaining), 0);
  const personalSaving = totalSaving - sharedSaving;
  const sisaBebas = totalRemaining - totalSaving;

  const periodLabel = selectedPeriod?.label
    || (prediction?.period_start
      ? `${new Date(prediction.period_start).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })} – ${new Date(prediction.period_end).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}`
      : new Date().toLocaleString('id-ID', { month: 'long', year: 'numeric' }));
  const daysLeft = prediction?.days_left ?? 0;
  // Satu-satunya tempat jatah aman per hari dibulatkan (ke bawah, Rp100). Judul advisor,
  // rinciannya, baris Sisa bebas, dan garis Batas aman semua membaca angka ini.
  const safeDaily = floorRp100(prediction?.safe_daily);

  const chartData = buildDailyData(daily, prediction, selectedPeriod);
  const todayRow = daily.find(d => d.date === localDateStr());
  const todaySpent = todayRow?.total || 0;
  const todayCount = todayRow?.count || 0;

  const isDark = mode === 'dark';
  const kc = kpiPalette(isDark);
  const fundsTotal = totalAllocated + totalRollover;
  const tt = tileTones(isDark);
  const meter = dailyMeter(todaySpent, safeDaily);
  const income = Number(prediction?.total_income) || 0;
  const bills = billsProgress(recurringStats);
  const savingGoalCount = goals.filter(g => savingEnvelopes.some(e => e.id === g.envelope_id)).length;

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
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <KpiTile
          isDark={isDark} label="Jatah hari ini"
          info="Belanja hari ini dibanding batas aman per hari. Garis putih: batas aman."
          value={rpFull(todaySpent)}
          suffix={safeDaily > 0 ? `/ ${rpFull(safeDaily)}` : null}
          badge={meter.over ? { tone: 'danger', text: `Lewat ${rpFull(meter.overBy)}` } : null}
          alert={meter.over}
          bar={{
            fill: meter.fill, marker: meter.marker,
            color: meter.over ? tt.danger.bar : tt.bars.green,
            ariaLabel: `Belanja hari ini ${rpFull(todaySpent)} dari batas aman ${rpFull(safeDaily)}`,
          }}
          footer={todayCount > 0 ? `${todayCount} transaksi hari ini` : 'Belum ada transaksi hari ini'}
        />
        <KpiTile
          isDark={isDark} label="Sisa bebas"
          info="Saldo amplop belanja dikurangi tabungan dan tagihan yang belum dibayar. Batang: hari yang sudah lewat di periode ini."
          value={rpCompact(sisaBebas)}
          valueColor={sisaBebas < 0 ? tt.danger.text : null}
          suffix={isCurrentPeriod ? daysLabel(prediction) : null}
          bar={{ fill: isCurrentPeriod ? periodProgress(prediction) : 1, color: tt.bars.slate, ariaLabel: isCurrentPeriod ? periodDayLabel(prediction) : 'Periode selesai' }}
          footer={isCurrentPeriod && prediction
            ? `${periodDayLabel(prediction)} · aman ${rpCompact(safeDaily)}/hari`
            : null}
        />
        <KpiTile
          isDark={isDark} label="Terpakai periode ini"
          info="Belanja periode ini dari dana amplop (alokasi + rollover). Prediksi lewat: perkiraan akhir periode di atas dana itu."
          value={rpCompact(totalSpent)}
          suffix="dari dana amplop"
          badge={predictionOver(prediction) ? { tone: 'warn', text: 'Prediksi lewat' } : null}
          bar={{ fill: fundsTotal > 0 ? totalSpent / fundsTotal : 0, color: tt.bars.green, ariaLabel: `Terpakai ${rpCompact(totalSpent)} dari ${rpCompact(fundsTotal)}` }}
          footer={[
            fundsTotal > 0 ? `${Math.round((totalSpent / fundsTotal) * 100)}%` : null,
            prediction ? `prediksi akhir periode ${rpCompact(prediction.predicted_total)}` : null,
          ].filter(Boolean).join(' · ')}
        />
        <KpiTile
          isDark={isDark} label="Income periode ini"
          info="Pemasukan periode ini. Saving rate: uang yang masuk ke amplop tabungan dan sinking fund dibagi pemasukan."
          value={rpCompact(income)}
          valueColor={prediction && income === 0 ? tt.warn.text : null}
          suffix={prediction ? savingRateLabel(prediction) : null}
          badge={prediction && income === 0 ? { tone: 'warn', text: 'Belum dicatat' } : null}
          bar={{ fill: (Number(prediction?.saving_rate) || 0) / 100, color: tt.bars.green, ariaLabel: savingRateLabel(prediction) }}
          footer={cashFlowLabel(prediction)}
        />
        <KpiTile
          isDark={isDark} label="Tagihan belum dibayar"
          info="Tagihan bulanan yang jatuh tempo periode ini dan belum dibayar. Telat: ada yang lewat tanggal jatuh tempo."
          value={rpCompact(bills.due)}
          valueColor={recurringStats?.has_overdue ? tt.danger.text : null}
          suffix={recurringStats?.count_total ? `${recurringStats.count_due} dari ${recurringStats.count_total} tagihan` : 'tidak ada tagihan'}
          badge={recurringStats?.has_overdue ? { tone: 'danger', text: 'Telat' } : null}
          alert={!!recurringStats?.has_overdue}
          bar={{ fill: bills.fill, color: tt.bars.green, ariaLabel: `Lunas ${rpCompact(bills.paid)} dari ${rpCompact(bills.total)}` }}
          footer={bills.total > 0 ? `Lunas ${rpCompact(bills.paid)} dari ${rpCompact(bills.total)} bulan ini` : null}
        />
        <KpiTile
          isDark={isDark} label="Tabungan"
          info="Saldo amplop tabungan dan sinking fund. Batang: kemajuan semua target tabungan."
          value={rpCompact(totalSaving)}
          suffix={savingGoalCount > 0 ? `${savingGoalCount} target` : 'tanpa target'}
          bar={{ fill: savingsProgress(goals, envelopes, null) || 0, color: tt.bars.purple, ariaLabel: 'Kemajuan target tabungan' }}
          footer={`Bersama ${rpCompact(sharedSaving)} · Pribadi ${rpCompact(personalSaving)}`}
        />
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
          safeDaily={safeDaily}
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
                {safeDaily > 0 && (
                  <span className="text-xs text-gray-400 flex items-center gap-1">
                    <span className="inline-block w-4 border-t-2 border-dashed border-danger-400"></span>
                    Batas aman {shortRp100(safeDaily)}/hari
                  </span>
                )}
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <ComposedChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <XAxis dataKey="date" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={45}
                    tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
                  <Tooltip content={<CustomTooltip />} />
                  {safeDaily > 0 && (
                    <ReferenceLine y={safeDaily} stroke="#E24B4A" strokeDasharray="4 3" strokeWidth={1.5}
                      ifOverflow="extendDomain" label={{ value: '', position: 'right' }} />
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

      {/* Amplop pengeluaran (bertab) + Target tabungan berdampingan di layar lebar */}
      {(spending.length > 0 || savingEnvelopes.length > 0) && (
        <div className={`grid grid-cols-1 gap-4 items-start ${spending.length > 0 && savingEnvelopes.length > 0 ? 'lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]' : ''}`}>
          {spending.length > 0 && (
            <SpendingEnvelopes
              envelopes={spending}
              allEnvelopes={envelopes}
              isDark={isDark}
              track={kc.track}
              actionable={isCurrentPeriod}
              onChanged={() => setRefreshTick(t => t + 1)}
            />
          )}
          {savingEnvelopes.length > 0 && (
            <SavingsTargets
              envelopes={savingEnvelopes}
              goals={goals}
              isDark={isDark}
              accent={kc.indigo}
              done="var(--brand-600)"
              track={kc.track}
            />
          )}
        </div>
      )}

      {/* Transaksi terbaru + Langganan berdampingan di layar lebar */}
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] gap-4 items-start">
        <RecentTransactions transactions={transactions} envelopes={envelopes} isCurrentPeriod={isCurrentPeriod} />
        <SubscriptionsCard items={subscriptions} />
      </div>
    </div>
  );
}
