import { useState, useEffect, useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import { createPortal } from 'react-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import ExportButtons from '../components/ExportButtons';
import SpendingEnvelopes from '../components/SpendingEnvelopes';
import SavingsTargets from '../components/SavingsTargets';
import RecentTransactions from '../components/RecentTransactions';
import SubscriptionsCard from '../components/SubscriptionsCard';
import DailySpendingChart from '../components/DailySpendingChart';
import AttentionCard from '../components/AttentionCard';
import AdvisorCard from '../components/AdvisorCard';
import SpendBreakdown from '../components/SpendBreakdown';
import { attentionItems, transfersInto } from '../lib/dashboardInsights';
import Onboarding from '../components/Onboarding';
import { Icon } from '../components/Icon';
import { KpiTile, tileTones, kpiPalette } from '../components/KpiCard';
import { rpFull, rpCompact, dailyMeter, predictionOver, daysLabel, periodDayLabel, periodProgress, savingRateLabel, cashFlowLabel, billsProgress } from '../lib/kpiCards';
import { savingsProgress, localDateStr } from '../lib/kpiVisuals';
import { formatLastChecked } from '../lib/balanceCheck';
import { advisorEnabled, advisorKpi, advisorDailySeries, chipLook, updatedLabel } from '../lib/advisorDashboard';
import { useIsPhone } from '../components/AdvisorChip';

// Uang pecahan terkecil Rp100: jatah harian dan selisihnya dibulatkan ke bawah ke kelipatan Rp100.
const floorRp100 = (v) => Math.floor((Number(v) || 0) / 100) * 100;

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
  // Layar lebar: periode & Laporan tampil di top bar Layout (lihat Layout.jsx).
  const { topbarSlot } = useOutletContext() || {};
  const [balanceStatus, setBalanceStatus] = useState(null);
  const [subscriptions, setSubscriptions] = useState([]);
  const [incomes, setIncomes] = useState([]);
  const [showOnboardingGuide, setShowOnboardingGuide] = useState(false);
  const [recurringStats, setRecurringStats] = useState(null);
  // Beranda AI Advisor (S6): GET /advisor/dashboard; {"enabled": false} atau gagal → UI lama.
  const [advisorDash, setAdvisorDash] = useState(null);
  const [advisorTick, setAdvisorTick] = useState(0);
  const [openKpi, setOpenKpi] = useState(null);
  const phone = useIsPhone();
  const closeKpi = useCallback(() => setOpenKpi(null), []);

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
    // Transfer antar amplop periode ini (untuk "ditambal N×" di Perlu perhatian).
    if (isCurrentPeriod) api.getIncomes().then(d => setIncomes(Array.isArray(d) ? d : [])).catch(() => setIncomes([]));
    else setIncomes([]);
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
  // Label pil periode di top bar: bulan Indonesia ("26 Okt"), tahun hanya di layar lebar.
  const periodStart = selectedPeriod?.period_start || prediction?.period_start;
  const periodEnd = selectedPeriod?.period_end || prediction?.period_end;
  const tglPendek = (iso, year) => new Date(`${String(iso).slice(0, 10)}T00:00:00`)
    .toLocaleDateString('id-ID', year ? { day: 'numeric', month: 'short', year: 'numeric' } : { day: 'numeric', month: 'short' });
  const periodShort = periodStart && periodEnd ? `${tglPendek(periodStart)} – ${tglPendek(periodEnd)}` : periodLabel;
  const periodFull = periodStart && periodEnd ? `${tglPendek(periodStart)} – ${tglPendek(periodEnd, true)}` : periodLabel;
  // Satu-satunya tempat jatah aman per hari dibulatkan (ke bawah, Rp100). Judul advisor,
  // rinciannya, baris Sisa bebas, dan garis Batas aman semua membaca angka ini.
  const safeDaily = floorRp100(prediction?.safe_daily);

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

  // Angka kartu & grafik dari metrics endpoint; hanya periode berjalan (endpoint tidak punya periode lalu).
  const adv = isCurrentPeriod && advisorEnabled(advisorDash);
  const k = adv ? advisorKpi(advisorDash.metrics) : null;
  const advMeter = adv ? dailyMeter(k.jatah.spent, k.jatah.j0) : null;
  const stamp = adv ? updatedLabel(advisorDash.generated_at) : '';
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
  // Hari ini menurut zona waktu user (generated_at), bukan jam browser.
  const advToday = (adv && (advisorDash.generated_at || '').slice(0, 10)) || localDateStr();

  const milestoneLabel = (n) => ({
    3: 'Kebiasaan baik dimulai 🌱', 7: 'Seminggu penuh disiplin!', 14: '2 minggu konsisten 💪',
    30: 'Sebulan penuh nyatat! 🏆', 50: '50 hari, luar biasa 🌟', 100: '100 hari, kamu legend 👑',
    150: '150 hari 🚀', 200: '200 hari, level dewa 🧘', 365: 'SATU TAHUN PENUH 🎉',
  }[n] || `${n} hari berturut-turut!`);

  return (
    <div className="space-y-6">
      {celebrate && (
        <div
          className="rounded-xl p-4 flex items-center justify-between gap-3 animate-pulse lg:mb-6"
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
        <div className="card border-brand-200 bg-brand-50/40 p-4 flex items-start justify-between gap-3 lg:mb-6">
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
      {topbarSlot && createPortal(
        <>
          <div className="h-[var(--nav-h)] rounded-xl inline-flex items-center gap-1 px-1"
            style={{ background: 'var(--card-bg)', border: '1px solid var(--border)' }}>
            <button type="button" onClick={() => setPeriodIdx(i => i - 1)} disabled={periodIdx === 0}
              className="w-8 h-[calc(var(--nav-h)-8px)] rounded-lg inline-flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed hover:bg-black/5"
              style={{ color: 'var(--text-muted)' }} aria-label="Periode sebelumnya">
              <Icon name="chevron" size={14} weight="bold" style={{ transform: 'rotate(90deg)' }} />
            </button>
            <span className="px-1.5 text-[15px] font-semibold whitespace-nowrap" style={{ color: 'var(--text)' }}
              title={isCurrentPeriod && daysLeft > 0 ? `${periodFull} · ${daysLeft} hari lagi` : periodFull}>
              <span className="2xl:hidden">{periodShort}</span>
              <span className="hidden 2xl:inline">{periodFull}</span>
              {isCurrentPeriod && daysLeft > 0 && <span className="hidden xl:inline font-normal" style={{ color: 'var(--text-muted)' }}> · {daysLeft} hari lagi</span>}
              {periodLoading && <span className="font-normal" style={{ color: 'var(--text-muted)' }}> …</span>}
            </span>
            <button type="button" onClick={() => setPeriodIdx(i => i + 1)} disabled={isCurrentPeriod}
              className="w-8 h-[calc(var(--nav-h)-8px)] rounded-lg inline-flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed hover:bg-black/5"
              style={{ color: 'var(--text-muted)' }} aria-label="Periode berikutnya">
              <Icon name="chevron" size={14} weight="bold" style={{ transform: 'rotate(-90deg)' }} />
            </button>
          </div>
          <ExportButtons compact
            periodStart={selectedPeriod?.period_start}
            periodEnd={selectedPeriod?.period_end}
            periodLabel={selectedPeriod?.label}
          />
        </>,
        topbarSlot,
      )}
      {/* Header mobile ringkas: baris 1 sapaan + streak + Laporan (menu PDF/CSV), baris 2 periode + papan disiplin (scroll-x). */}
      <div className="lg:hidden space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-display font-bold truncate">Hai, {user?.name || 'User'}</h1>
          {streak && streak.current_streak >= 1 && (
            <span
              className="text-xs px-2 py-0.5 rounded-full font-semibold flex-shrink-0 inline-flex items-center gap-1"
              style={{ background: streak.logged_today ? '#FEF3C7' : '#F3F4F6', color: streak.logged_today ? '#92400E' : '#6B7280' }}
              title={`Rekor ${streak.longest_streak} hari · total ${streak.total_logged_days} hari tercatat`}
            >
              <Icon name="fire" size={12} weight="fill" /> {streak.current_streak}
            </span>
          )}
          <div className="ml-auto flex-shrink-0">
            <ExportButtons compact
              periodStart={selectedPeriod?.period_start}
              periodEnd={selectedPeriod?.period_end}
              periodLabel={selectedPeriod?.label}
            />
          </div>
        </div>
        <div className="flex items-center gap-1 overflow-x-auto whitespace-nowrap text-xs text-gray-500 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <button
            onClick={() => setPeriodIdx(i => i - 1)}
            disabled={periodIdx === 0}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed leading-none flex-shrink-0"
            aria-label="Periode sebelumnya"
          >←</button>
          <span>{periodLabel}{isCurrentPeriod && daysLeft > 0 ? ` · ${daysLeft} hr lagi` : ''}</span>
          <button
            onClick={() => setPeriodIdx(i => i + 1)}
            disabled={isCurrentPeriod}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed leading-none flex-shrink-0"
            aria-label="Periode berikutnya"
          >→</button>
          {!isCurrentPeriod && (
            <button onClick={() => setPeriodIdx(periods.length - 1)}
              className="px-1.5 py-0.5 bg-brand-50 text-brand-600 rounded font-medium flex-shrink-0">Sekarang</button>
          )}
          {periodLoading && <span className="text-gray-400">…</span>}
          {isCurrentPeriod && leaderboard.length >= 2 && (
            <>
              <span className="mx-1.5 h-3 w-px bg-gray-300 flex-shrink-0" aria-hidden="true" />
              <span className="inline-flex items-center gap-2.5" title="Papan disiplin">
                <Icon name="trophy" size={12} className="text-gray-400" />
                {leaderboard.map((m, i) => (
                  <span key={m.user_id} className="inline-flex items-center gap-1">
                    <span>{['🥇', '🥈', '🥉'][i] || ''}</span>
                    <span className={m.is_me ? 'font-semibold text-brand-600' : ''}>{m.name.split(' ')[0]}</span>
                    <span className="font-medium text-gray-600">{m.current_streak > 0 ? `${m.current_streak}h` : '—'}</span>
                    {m.logged_today && <span className="text-[10px]" title="Sudah catat">✅</span>}
                  </span>
                ))}
              </span>
            </>
          )}
        </div>
      </div>

      {/* KPI Cards — lg:!mt-0: blok sapaan/periode di atasnya tersembunyi di layar lebar (pindah ke top bar) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 lg:!mt-0">
        {adv ? (
          <>
            <KpiTile
              isDark={isDark} label="Jatah hari ini" advisor={chipFor('jatah')}
              info="Belanja hari ini dibanding jatah sejak pagi (sisa bebas awal hari dibagi sisa hari). Garis putih: jatah."
              value={rpFull(k.jatah.spent)}
              suffix={k.jatah.j0 > 0 ? `/ ${rpFull(k.jatah.j0)}` : null}
              alert={advMeter.over}
              bar={{
                fill: advMeter.fill, marker: advMeter.marker,
                color: advMeter.over ? tt.danger.bar : tt.bars.green,
                ariaLabel: `Belanja hari ini ${rpFull(k.jatah.spent)} dari jatah ${rpFull(k.jatah.j0)}`,
              }}
              footer={todayCount > 0 ? `${todayCount} transaksi hari ini` : 'Belum ada transaksi hari ini'}
            />
            <KpiTile
              isDark={isDark} label="Sisa bebas" advisor={chipFor('sisa_bebas')}
              info="Dana amplop belanja dikurangi yang sudah terpakai dan tagihan yang belum dibayar. Batang: hari yang sudah lewat di periode ini."
              value={rpCompact(k.sisa.value)}
              valueColor={k.sisa.value < 0 ? tt.danger.text : null}
              suffix={k.sisa.sisaHari > 0 ? `untuk ${k.sisa.sisaHari} hari` : null}
              bar={{ fill: k.sisa.progress, color: tt.bars.slate, ariaLabel: k.sisa.dayLabel }}
              footer={[k.sisa.dayLabel, k.sisa.j1 != null ? `aman ${rpCompact(k.sisa.j1)}/hari` : null].filter(Boolean).join(' · ')}
            />
            <KpiTile
              isDark={isDark} label="Terpakai periode ini" advisor={chipFor('terpakai')}
              info="Belanja periode ini dari dana amplop belanja (tanpa tabungan). Garis tegak: hari yang sudah lewat; batang kuning = terpakai lebih cepat dari waktu."
              value={rpCompact(k.terpakai.value)}
              suffix="dari dana belanja"
              bar={{
                fill: k.terpakai.fill, split: k.terpakai.waktu, color: tt.bars.green, lateColor: tt.bars.amber,
                ariaLabel: `Terpakai ${rpCompact(k.terpakai.value)} dari ${rpCompact(k.terpakai.dana)}, waktu ${Math.round(k.terpakai.waktu * 100)}%`,
              }}
              footer={[
                k.terpakai.persen != null ? `${k.terpakai.persen}% · waktu ${Math.round(k.terpakai.waktu * 100)}%` : null,
                k.terpakai.proyeksi != null ? `perkiraan akhir ±${rpCompact(k.terpakai.proyeksi)}` : null,
              ].filter(Boolean).join(' · ')}
            />
            <KpiTile
              isDark={isDark} label="Income periode ini" advisor={chipFor('income')}
              info="Pemasukan rumah tangga periode ini (termasuk yang dicatat anggota lain). Batang: bagian yang kamu catat."
              value={rpCompact(k.income.value)}
              valueColor={k.income.value === 0 ? tt.warn.text : null}
              suffix={k.income.saya !== k.income.value ? `kamu ${rpCompact(k.income.saya)}` : null}
              badge={k.income.value === 0 ? { tone: 'warn', text: 'Belum dicatat' } : null}
              bar={{ fill: k.income.share, color: tt.bars.green, ariaLabel: `Pemasukanmu ${rpCompact(k.income.saya)} dari ${rpCompact(k.income.value)}` }}
              footer={k.income.kekurangan == null ? null
                : k.income.kekurangan > 0 ? `Arus kas kurang ±${rpCompact(k.income.kekurangan)} di akhir periode`
                  : 'Arus kas cukup sampai akhir periode'}
            />
          </>
        ) : (
          <>
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
          </>
        )}
        <KpiTile
          isDark={isDark} label="Tagihan belum dibayar" advisor={chipFor('tagihan')}
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
          isDark={isDark} label="Tabungan" advisor={chipFor('tabungan')}
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
