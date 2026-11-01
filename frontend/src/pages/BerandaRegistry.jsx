// Beranda dari registry (Plugin B2): tata letak dari GET /dashboard/layout, data semua kartu dari satu
// POST /dashboard/data, kartu digambar DashboardGrid dari CardRegistry. Hanya untuk user di flag
// `beranda_registry_users` (Dashboard.jsx memilih); tampilan dan angka sama dengan Beranda lama.
//
// Offline: respons batch periode berjalan disimpan di localCache per user (dihapus saat logout),
// jadi Beranda tetap tampil dari cache saat jaringan putus.
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useOutletContext } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import { useBerandaShell } from '../hooks/useBerandaShell';
import BerandaHeader from '../components/BerandaHeader';
import Onboarding from '../components/Onboarding';
import DashboardGrid from '../cards/DashboardGrid';
import { knownCard, refreshEvents } from '../cards/CardRegistry';
import '../cards/core';
import { useIsPhone } from '../components/AdvisorChip';
import { localDateStr } from '../lib/kpiVisuals';
import { loadCache, saveCache } from '../lib/localCache';
import { cacheKeyData, itemsForData, sumberPertama } from '../lib/dashboardRegistry';

const GAGAL = { error: { kode: 'gagal_memuat', detail: 'Data kartu ini belum bisa dimuat. Coba lagi sebentar.' } };

export default function BerandaRegistry({ layout }) {
  const { user } = useAuth();
  const { mode } = useTheme();
  const shell = useBerandaShell();
  const { periods, periodIdx, isCurrentPeriod, selectedPeriod } = shell;
  const { topbarSlot } = useOutletContext() || {};
  const phone = useIsPhone();
  const uid = user?.id;

  const [resp, setResp] = useState(() => (uid ? loadCache(cacheKeyData(uid)) : null));
  const [periodLoading, setPeriodLoading] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [openKpi, setOpenKpi] = useState(null);
  const closeKpi = useCallback(() => setOpenKpi(null), []);
  const refresh = useCallback(() => setRefreshTick(t => t + 1), []);
  const seq = useRef(0);

  useEffect(() => {
    const events = refreshEvents();
    events.forEach(e => window.addEventListener(e, refresh));
    return () => events.forEach(e => window.removeEventListener(e, refresh));
  }, [refresh]);

  const items = useMemo(() => itemsForData(layout, knownCard), [layout]);
  const itemsKey = JSON.stringify(items);

  useEffect(() => {
    if (periods.length === 0 || periodIdx === null || items.length === 0) return;
    const current = periodIdx === periods.length - 1;
    const periode = current ? null : periods[periodIdx].period_start;
    const ini = ++seq.current;
    setPeriodLoading(true);
    api.getDashboardData(items, periode).then(r => {
      if (ini !== seq.current) return;   // ada permintaan yang lebih baru
      setPeriodLoading(false);
      if (r) {
        setResp(r);
        if (current && uid) saveCache(cacheKeyData(uid), r);
        const envs = sumberPertama(r.data, 'ringkasan_amplop');
        if (current && Array.isArray(envs) && envs.length === 0) setShowOnboarding(true);
        return;
      }
      // Gagal: periode berjalan tetap dari cache bila ada; selain itu setiap kartu menampilkan galat.
      const cached = current && uid ? loadCache(cacheKeyData(uid)) : null;
      setResp(cached || { data: Object.fromEntries(items.map(i => [i.id, GAGAL])) });
    });
    // itemsKey mewakili `items`; mengikuti `items` langsung memicu muat ulang di setiap render tata letak yang sama.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodIdx, periods, refreshTick, itemsKey, uid]);

  if (!resp) return <div className="text-center py-12 text-gray-400">Loading...</div>;
  if (showOnboarding) return <Onboarding onDone={() => { setShowOnboarding(false); window.location.reload(); }} />;

  const data = resp.data || {};
  // Respons dari cache bisa milik periode lain saat pemilih periode baru berpindah: kartu menunggu.
  const cocok = !resp.periode || !selectedPeriod || resp.periode.start === selectedPeriod.period_start;
  const prediction = isCurrentPeriod ? (sumberPertama(data, 'prediksi') ?? null) : null;
  const ctx = {
    isDark: mode === 'dark', isCurrentPeriod, selectedPeriod, phone, openKpi, setOpenKpi, closeKpi, refresh,
    today: localDateStr(),
  };

  return (
    <div className="space-y-6">
      <BerandaHeader shell={shell} user={user} prediction={prediction} periodLoading={periodLoading} topbarSlot={topbarSlot} />
      <DashboardGrid layout={layout} data={cocok ? data : {}} ctx={ctx} />
    </div>
  );
}
