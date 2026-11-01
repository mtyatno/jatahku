// Kartu inti Beranda (Plugin B2). Setiap kartu menggambar komponen Beranda yang sama dari `sumber`
// di POST /dashboard/data (04-kontrak-api.md §4: respons endpoint lama dengan nama sumber), jadi
// tampilan dan angka sama dengan Beranda lama. Turunan angka lewat berandaModel.
import { registerCard } from '../CardRegistry';
import SpendingEnvelopes from '../../components/SpendingEnvelopes';
import SavingsTargets from '../../components/SavingsTargets';
import RecentTransactions from '../../components/RecentTransactions';
import SubscriptionsCard from '../../components/SubscriptionsCard';
import DailySpendingChart from '../../components/DailySpendingChart';
import AttentionCard from '../../components/AttentionCard';
import AdvisorCard from '../../components/AdvisorCard';
import SpendBreakdown from '../../components/SpendBreakdown';
import { KpiJatah, KpiSisaBebas, KpiTerpakai, KpiIncome, KpiTagihan, KpiTabungan } from '../../components/BerandaKpi';
import { Icon } from '../../components/Icon';
import { kpiPalette } from '../../components/KpiCard';
import { formatLastChecked } from '../../lib/balanceCheck';
import { advisorDailySeries, advisorEnabled, chipLook } from '../../lib/advisorDashboard';
import { attentionItems, transfersInto } from '../../lib/dashboardInsights';
import { berandaModel } from '../../lib/berandaModel';

const ADV = ['jatahku:txn-added', 'jatahku:envelope-updated', 'jatahku:advisor-dismissed', 'jatahku:advisor-undismissed'];
const TXN = ['jatahku:txn-added'];
const TXN_ENV = ['jatahku:txn-added', 'jatahku:envelope-updated'];

const arr = (v) => (Array.isArray(v) ? v : []);

// Model dari sumber satu kartu. `advisorSlice`: KPI menerima potongan metrik tanpa deret harian.
function modelDari(s, ctx, { advisorSlice = false } = {}) {
  return berandaModel({
    envelopes: arr(s.ringkasan_amplop), prediction: s.prediksi ?? null, daily: arr(s.harian),
    recurringStats: s.tagihan ?? null, goals: arr(s.target), advisorDash: s.advisor ?? null,
    isCurrentPeriod: ctx.isCurrentPeriod, today: ctx.today, advisorSlice,
  });
}

// Chip AI Advisor satu kartu KPI (sama dengan chipFor di Beranda lama).
function chipDari(s, m, kartu, ctx) {
  const insight = m.adv ? s.advisor?.kpi : null;
  if (!insight) return undefined;
  return {
    look: chipLook(insight, s.advisor.redam_chip),
    insight, stamp: m.stamp, phone: ctx.phone,
    open: ctx.openKpi === kartu,
    onToggle: () => ctx.setOpenKpi(o => (o === kartu ? null : kartu)),
    onClose: ctx.closeKpi,
  };
}

function kpi(key, kartu, Tile) {
  registerCard({
    key, kind: 'kpi', refreshOn: ADV,
    Component: function KartuKpi({ entri, ctx }) {
      const s = entri.sumber || {};
      const m = modelDari(s, ctx, { advisorSlice: true });
      return (
        <Tile m={m} isDark={ctx.isDark} chip={chipDari(s, m, kartu, ctx)} prediction={s.prediksi ?? null}
          isCurrentPeriod={ctx.isCurrentPeriod} recurringStats={s.tagihan ?? null}
          goals={arr(s.target)} envelopes={arr(s.ringkasan_amplop)} />
      );
    },
  });
}

kpi('core.kpi.jatah', 'jatah', KpiJatah);
kpi('core.kpi.sisa_bebas', 'sisa_bebas', KpiSisaBebas);
kpi('core.kpi.terpakai', 'terpakai', KpiTerpakai);
kpi('core.kpi.income', 'income', KpiIncome);
kpi('core.kpi.tagihan', 'tagihan', KpiTagihan);
kpi('core.kpi.tabungan', 'tabungan', KpiTabungan);

registerCard({
  key: 'core.cocokkan_saldo', kind: 'link', ownRow: true, refreshOn: TXN,
  kosong: (_e, ctx) => !ctx.isCurrentPeriod,
  Component: function CocokkanSaldo({ entri }) {
    const status = entri.sumber?.saldo_cek;
    return (
      <div className="flex justify-end">
        <button type="button"
          onClick={() => window.dispatchEvent(new CustomEvent('jatahku:open-action', { detail: 'balance' }))}
          className="inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand-600">
          <Icon name="balance" size={14} />
          <span>Cocokkan saldo · terakhir {formatLastChecked(status?.last_checked_at)}</span>
        </button>
      </div>
    );
  },
});

registerCard({
  key: 'core.pengeluaran_harian', refreshOn: ADV,
  Component: function PengeluaranHarian({ entri, ctx }) {
    const s = entri.sumber || {};
    const m = modelDari(s, ctx);
    const pred = s.prediksi;
    const ps = pred?.period_start || ctx.selectedPeriod?.period_start;
    const pe = pred?.period_end || ctx.selectedPeriod?.period_end;
    return (
      <DailySpendingChart
        daily={arr(s.harian)} periodStart={ps} periodEnd={pe} today={m.advToday}
        safeDaily={ctx.isCurrentPeriod ? m.safeDaily : 0} isDark={ctx.isDark}
        advisor={m.adv ? { series: advisorDailySeries(s.advisor.metrics, ps, pe, m.advToday), grafik: s.advisor.grafik } : null}
      />
    );
  },
});

registerCard({
  key: 'core.advisor', refreshOn: ADV,
  kosong: (_e, ctx) => !ctx.isCurrentPeriod,
  Component: function KartuAdvisor({ entri, ctx }) {
    const s = entri.sumber || {};
    const m = modelDari(s, ctx);
    if (advisorEnabled(s.advisor)) return <AdvisorCard dash={s.advisor} stamp={m.stamp} isDark={ctx.isDark} />;
    // UI lama (flag advisor_v2_users belum mencakup user ini): Perlu perhatian.
    return (
      <AttentionCard
        isDark={ctx.isDark}
        error={false}
        items={attentionItems({
          subscriptions: arr(s.langganan), envelopes: arr(s.ringkasan_amplop), income: m.income,
          isCurrentPeriod: ctx.isCurrentPeriod, advisorCards: s.insights?.cards,
          transfers: transfersInto(arr(s.pemasukan)), today: ctx.today,
        })}
      />
    );
  },
});

const rincianTerpakai = (e) => arr(e?.sumber?.rincian).filter(x => x.spent > 0);

registerCard({
  key: 'core.ke_mana_uangmu', refreshOn: TXN,
  // SpendBreakdown tidak menggambar apa pun tanpa belanja; kartu ikut tidak disusun supaya tidak ada jarak kosong.
  kosong: (e) => !rincianTerpakai(e).reduce((s, x) => s + Number(x.spent || 0), 0),
  Component: function KeManaUangmu({ entri, ctx }) {
    return <SpendBreakdown breakdown={rincianTerpakai(entri)} isDark={ctx.isDark} />;
  },
});

registerCard({
  key: 'core.amplop_pengeluaran', alignStart: true, refreshOn: TXN_ENV,
  kosong: (e, ctx) => modelDari(e.sumber || {}, ctx).spending.length === 0,
  Component: function AmplopPengeluaran({ entri, ctx }) {
    const envs = arr(entri.sumber?.ringkasan_amplop);
    const m = modelDari(entri.sumber || {}, ctx);
    return (
      <SpendingEnvelopes envelopes={m.spending} allEnvelopes={envs} isDark={ctx.isDark}
        track={kpiPalette(ctx.isDark).track} actionable={ctx.isCurrentPeriod} onChanged={ctx.refresh} />
    );
  },
});

registerCard({
  key: 'core.target_tabungan', alignStart: true, refreshOn: TXN_ENV,
  kosong: (e, ctx) => modelDari(e.sumber || {}, ctx).savingEnvelopes.length === 0,
  Component: function TargetTabungan({ entri, ctx }) {
    const m = modelDari(entri.sumber || {}, ctx);
    const kc = kpiPalette(ctx.isDark);
    return (
      <SavingsTargets envelopes={m.savingEnvelopes} goals={arr(entri.sumber?.target)} isDark={ctx.isDark}
        accent={kc.indigo} done="var(--brand-600)" track={kc.track} />
    );
  },
});

registerCard({
  key: 'core.transaksi_terbaru', alignStart: true, refreshOn: TXN,
  Component: function TransaksiTerbaru({ entri, ctx }) {
    const s = entri.sumber || {};
    return <RecentTransactions transactions={arr(s.transaksi)} envelopes={arr(s.ringkasan_amplop)} isCurrentPeriod={ctx.isCurrentPeriod} />;
  },
});

registerCard({
  key: 'core.langganan', alignStart: true, refreshOn: TXN,
  Component: function Langganan({ entri }) {
    return <SubscriptionsCard items={arr(entri.sumber?.langganan)} />;
  },
});

registerCard({
  key: 'core.papan_disiplin', alignStart: true, refreshOn: TXN,
  kosong: (e) => arr(e.sumber?.papan).length < 2,
  Component: function PapanDisiplin({ entri }) {
    const papan = arr(entri.sumber?.papan);
    return (
      <section aria-labelledby="papan-disiplin-title" className="card !px-4 md:!px-6 !pt-5 md:!pt-6 !pb-4 min-w-0">
        <h2 id="papan-disiplin-title" className="font-display font-bold text-lg px-1 pb-2" style={{ color: 'var(--text)' }}>Papan disiplin</h2>
        <ol className="space-y-1.5 px-1">
          {papan.map((m, i) => (
            <li key={m.user_id} className="flex items-center gap-2 text-sm">
              <span className="w-5">{['🥇', '🥈', '🥉'][i] || ''}</span>
              <span className={`flex-1 truncate ${m.is_me ? 'font-semibold text-brand-600' : ''}`}>{m.name}</span>
              <span className="font-medium" style={{ color: 'var(--text-muted)' }}>{m.current_streak > 0 ? `${m.current_streak} hari` : '—'}</span>
              {m.logged_today && <span className="text-xs" title="Sudah catat">✅</span>}
            </li>
          ))}
        </ol>
      </section>
    );
  },
});
