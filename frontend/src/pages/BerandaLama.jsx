// Beranda lama (sebelum registry): satu komponen yang memanggil endpoint satu per satu. Tetap dipakai
// user di luar flag `beranda_registry_users` sampai B3; isinya sama dengan Dashboard.jsx sebelum B2.
// Turunan angka, enam KPI, dan kepala halaman dibagi dengan Beranda registry (berandaModel,
// BerandaKpi, BerandaHeader), jadi keduanya tidak bisa menyimpang.
import { useState, useEffect, useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import { useBerandaShell } from '../hooks/useBerandaShell';
import SpendingEnvelopes from '../components/SpendingEnvelopes';
import SavingsTargets from '../components/SavingsTargets';
import RecentTransactions from '../components/RecentTransactions';
import SubscriptionsCard from '../components/SubscriptionsCard';
import DailySpendingChart from '../components/DailySpendingChart';
import AttentionCard from '../components/AttentionCard';
import AdvisorCard from '../components/AdvisorCard';
import SpendBreakdown from '../components/SpendBreakdown';
import BerandaHeader from '../components/BerandaHeader';
import { KpiJatah, KpiSisaBebas, KpiTerpakai, KpiIncome, KpiTagihan, KpiTabungan } from '../components/BerandaKpi';
import { attentionItems, transfersInto } from '../lib/dashboardInsights';
import Onboarding from '../components/Onboarding';
import { Icon } from '../components/Icon';
import { kpiPalette } from '../components/KpiCard';
import { localDateStr } from '../lib/kpiVisuals';
import { formatLastChecked } from '../lib/balanceCheck';
import { advisorDailySeries, chipLook } from '../lib/advisorDashboard';
import { berandaModel } from '../lib/berandaModel';
import { useIsPhone } from '../components/AdvisorChip';

export default function BerandaLama() {
  const { user } = useAuth();
  const { mode } = useTheme();
  const shell = useBerandaShell();
  const { periods, periodIdx, isCurrentPeriod, selectedPeriod } = shell;
  const [envelopes, setEnvelopes] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [periodLoading, setPeriodLoading] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [daily, setDaily] = useState([]);
  const [breakdown, setBreakdown] = useState([]);
  const [prediction, setPrediction] = useState(null);
  const [advisorInsights, setAdvisorInsights] = useState(null);
  const [goals, setGoals] = useState([]);
  const [refreshTick, setRefreshTick] = useState(0);
  // Layar lebar: periode & Laporan tampil di top bar Layout (lihat Layout.jsx).
  const { topbarSlot } = useOutletContext() || {};
  const [balanceStatus, setBalanceStatus] = useState(null);
  const [subscriptions, setSubscriptions] = useState([]);
  const [incomes, setIncomes] = useState([]);
  const [recurringStats, setRecurringStats] = useState(null);
  // Beranda AI Advisor (S6): GET /advisor/dashboard; {"enabled": false} atau gagal → UI lama.
  const [advisorDash, setAdvisorDash] = useState(null);
  const [advisorTick, setAdvisorTick] = useState(0);
  const [openKpi, setOpenKpi] = useState(null);
  const phone = useIsPhone();
  const closeKpi = useCallback(() => setOpenKpi(null), []);

  useEffect(() => {
    const onAdded = () => setRefreshTick(t => t + 1);
    window.addEventListener('jatahku:txn-added', onAdded);
    return () => window.removeEventListener('jatahku:txn-added', onAdded);
  }, []);

  useEffect(() => {
    const onChanged = () => setAdvisorTick(t => t + 1);
    window.addEventListener('jatahku:advisor-dismissed', onChanged);
    window.addEventListener('jatahku:advisor-undismissed', onChanged);
    window.addEventListener('jatahku:envelope-updated', onChanged);
    return () => {
      window.removeEventListener('jatahku:advisor-dismissed', onChanged);
      window.removeEventListener('jatahku:advisor-undismissed', onChanged);
      window.removeEventListener('jatahku:envelope-updated', onChanged);
    };
  }, []);

  useEffect(() => {
    let live = true;
    api.getAdvisorDashboard().then(d => { if (live) setAdvisorDash(d); });
    return () => { live = false; };
  }, [refreshTick, advisorTick]);

  useEffect(() => {
    api.getBalanceCheckStatus().then(setBalanceStatus);
    api.getRecurring().then(r => setSubscriptions(Array.isArray(r) ? r : []));
  }, [refreshTick]);

  useEffect(() => {
    api.getAdvisorInsights().then(setAdvisorInsights);
    api.getGoals().then(setGoals);
  }, []);

  // Reload data whenever selected period changes
  useEffect(() => {
    if (periods.length === 0 || periodIdx === null) return;
    const current = periodIdx === periods.length - 1;
    const period = periods[periodIdx];
    // Pass null for current period so backend uses its own default (handles edge cases)
    const ps = current ? null : period.period_start;
    const pe = current ? null : period.period_end;

    setPeriodLoading(true);
    // Transfer antar amplop periode ini (untuk "ditambal N×" di Perlu perhatian).
    if (current) api.getIncomes().then(d => setIncomes(Array.isArray(d) ? d : [])).catch(() => setIncomes([]));
    else setIncomes([]);
    Promise.all([
      api.getEnvelopeSummary(ps, pe),
      api.getTransactions(null, 10, period.period_start, period.period_end),
      api.getDailySpending(ps, pe),
      api.getEnvelopeBreakdown(ps, pe),
      current
        ? api.request('/analytics/prediction').then(r => r.ok ? r.json() : null)
        : Promise.resolve(null),
      current
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
      if (env.length === 0 && current) setShowOnboarding(true);
    });
  }, [periodIdx, periods, refreshTick]);

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;
  if (showOnboarding) return <Onboarding onDone={() => { setShowOnboarding(false); window.location.reload(); }} />;

  const isDark = mode === 'dark';
  const kc = kpiPalette(isDark);
  const m = berandaModel({
    envelopes, prediction, daily, recurringStats, goals, advisorDash, isCurrentPeriod, today: localDateStr(),
  });
  const { savingEnvelopes, spending, safeDaily, income, adv, stamp, advToday } = m;

  const chipFor = (kartu) => {
    const insight = adv ? advisorDash.kpi?.[kartu] : null;
    if (!insight) return undefined;
    return {
      look: chipLook(insight, advisorDash.redam_chip),
      insight, stamp, phone,
      open: openKpi === kartu,
      onToggle: () => setOpenKpi(o => (o === kartu ? null : kartu)),
      onClose: closeKpi,
    };
  };

  return (
    <div className="space-y-6">
      <BerandaHeader shell={shell} user={user} prediction={prediction} periodLoading={periodLoading} topbarSlot={topbarSlot} />

      {/* KPI Cards — lg:!mt-0: blok sapaan/periode di atasnya tersembunyi di layar lebar (pindah ke top bar) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 lg:!mt-0">
        <KpiJatah m={m} isDark={isDark} chip={chipFor('jatah')} />
        <KpiSisaBebas m={m} isDark={isDark} chip={chipFor('sisa_bebas')} prediction={prediction} isCurrentPeriod={isCurrentPeriod} />
        <KpiTerpakai m={m} isDark={isDark} chip={chipFor('terpakai')} prediction={prediction} />
        <KpiIncome m={m} isDark={isDark} chip={chipFor('income')} prediction={prediction} />
        <KpiTagihan m={m} isDark={isDark} chip={chipFor('tagihan')} recurringStats={recurringStats} />
        <KpiTabungan m={m} isDark={isDark} chip={chipFor('tabungan')} goals={goals} envelopes={envelopes} />
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

      {/* Pengeluaran harian + kartu AI Advisor (flag) / Perlu perhatian (UI lama) berdampingan di layar lebar */}
      <div className={`grid grid-cols-1 gap-4 ${isCurrentPeriod ? 'xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]' : ''}`}>
        <DailySpendingChart
          daily={daily}
          periodStart={prediction?.period_start || selectedPeriod?.period_start}
          periodEnd={prediction?.period_end || selectedPeriod?.period_end}
          today={advToday}
          safeDaily={isCurrentPeriod ? safeDaily : 0}
          isDark={isDark}
          advisor={adv ? {
            series: advisorDailySeries(advisorDash.metrics, prediction?.period_start || selectedPeriod?.period_start,
              prediction?.period_end || selectedPeriod?.period_end, advToday),
            grafik: advisorDash.grafik,
          } : null}
        />
        {adv && <AdvisorCard dash={advisorDash} stamp={stamp} isDark={isDark} />}
        {isCurrentPeriod && !adv && (
          <AttentionCard
            isDark={isDark}
            error={!!advisorInsights?._error}
            items={attentionItems({
              subscriptions,
              envelopes,
              income,
              isCurrentPeriod,
              advisorCards: advisorInsights?.cards,
              transfers: transfersInto(incomes),
              today: localDateStr(),
            })}
          />
        )}
      </div>

      <SpendBreakdown breakdown={breakdown} isDark={isDark} />

      {/* Amplop pengeluaran (bertab) + Target tabungan berdampingan di layar lebar */}
      {(spending.length > 0 || savingEnvelopes.length > 0) && (
        <div className={`grid grid-cols-1 gap-4 items-start ${spending.length > 0 && savingEnvelopes.length > 0 ? 'xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]' : ''}`}>
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
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] gap-4 items-start">
        <RecentTransactions transactions={transactions} envelopes={envelopes} isCurrentPeriod={isCurrentPeriod} />
        <SubscriptionsCard items={subscriptions} />
      </div>
    </div>
  );
}
