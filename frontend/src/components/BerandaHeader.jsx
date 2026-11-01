// Banner dan kepala Beranda (Plugin B2): banner streak, panduan onboarding, pemilih periode + Laporan
// di top bar layar lebar, dan kepala ringkas di HP. Dipindah apa adanya dari Dashboard.jsx supaya
// Beranda lama dan Beranda registry memakai bagian yang sama.
import { createPortal } from 'react-dom';
import ExportButtons from './ExportButtons';
import { Icon } from './Icon';

const milestoneLabel = (n) => ({
  3: 'Kebiasaan baik dimulai 🌱', 7: 'Seminggu penuh disiplin!', 14: '2 minggu konsisten 💪',
  30: 'Sebulan penuh nyatat! 🏆', 50: '50 hari, luar biasa 🌟', 100: '100 hari, kamu legend 👑',
  150: '150 hari 🚀', 200: '200 hari, level dewa 🧘', 365: 'SATU TAHUN PENUH 🎉',
}[n] || `${n} hari berturut-turut!`);

export default function BerandaHeader({ shell, user, prediction, periodLoading, topbarSlot }) {
  const {
    periods, periodIdx, setPeriodIdx, isCurrentPeriod, selectedPeriod, streak, leaderboard,
    celebrate, setCelebrate, showOnboardingGuide, setShowOnboardingGuide,
  } = shell;

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

  return (
    <>
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
    </>
  );
}
