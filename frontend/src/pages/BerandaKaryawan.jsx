// Beranda template "Karyawan" (Plugin R6): untuk karyawan (peran member) di ruang usaha. Tata letak dan data dari
// registry yang sama dengan Beranda biasa (GET /dashboard/layout, POST /dashboard/data); server hanya mengirim
// kartu karyawan. Tanpa pemilih periode, laporan, atau onboarding amplop: itu milik pemilik dan admin.
//
// Di luar jam kerja (ADR-P17) server menjawab 403 `di_luar_jam_kerja` + `buka_lagi`: Beranda menampilkan kapan
// ruang dibuka lagi, dan pemilih ruang tetap bisa dipakai untuk kembali ke ruang keluarga.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import DashboardGrid from '../cards/DashboardGrid';
import { knownCard, refreshEvents } from '../cards/CardRegistry';
import '../cards/karyawan';
import { Icon } from '../components/Icon';
import { useIsPhone } from '../components/AdvisorChip';
import { localDateStr } from '../lib/kpiVisuals';
import { clearCache, loadCache, saveCache } from '../lib/localCache';
import { cacheKeyData, cacheKeyLayout, itemsForData } from '../lib/dashboardRegistry';

const GAGAL = { error: { kode: 'gagal_memuat', detail: 'Data kartu ini belum bisa dimuat. Coba lagi sebentar.' } };

function waktuBuka(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return null;
  return d.toLocaleString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' });
}

function Tutup({ detail, bukaLagi, ruangNama }) {
  const kapan = waktuBuka(bukaLagi);
  return (
    <section className="card !px-5 !py-8 text-center max-w-xl mx-auto" role="status">
      <span className="mx-auto w-12 h-12 rounded-2xl inline-flex items-center justify-center"
        style={{ background: 'rgba(245,184,74,0.18)', color: '#92400E' }}>
        <Icon name="clock" size={24} />
      </span>
      <h1 className="font-display font-bold text-xl mt-3" style={{ color: 'var(--text)' }}>{ruangNama || 'Ruang ini'} sedang tutup</h1>
      <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
        {kapan ? `Dibuka lagi ${kapan}, sesuai jam kerja dari admin.` : detail}
      </p>
      <p className="text-xs mt-3" style={{ color: 'var(--text-muted)' }}>
        Ruang keluargamu tetap bisa dibuka dari pemilih ruang di atas.
      </p>
    </section>
  );
}

export default function BerandaKaryawan() {
  const { user } = useAuth();
  const { mode } = useTheme();
  const { ruang } = useOutletContext() || {};
  const phone = useIsPhone();
  const uid = user?.id;
  const ruangNama = ruang?.aktif?.nama;

  // Cache sendiri untuk peran karyawan; cache Beranda umum ruang ini (dari peran lama) dibuang (review PR #185 no. 4).
  const kunciLayout = uid ? cacheKeyLayout(uid, 'karyawan') : null;
  const kunciData = uid ? cacheKeyData(uid, 'karyawan') : null;
  const [layout, setLayout] = useState(() => (kunciLayout ? loadCache(kunciLayout) : null));
  const [resp, setResp] = useState(() => (kunciData ? loadCache(kunciData) : null));
  useEffect(() => {
    if (!uid) return;
    clearCache(cacheKeyLayout(uid));
    clearCache(cacheKeyData(uid));
  }, [uid]);
  const [tutup, setTutup] = useState(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick(t => t + 1), []);
  const seq = useRef(0);

  useEffect(() => {
    const events = refreshEvents();
    events.forEach(e => window.addEventListener(e, refresh));
    return () => events.forEach(e => window.removeEventListener(e, refresh));
  }, [refresh]);

  useEffect(() => {
    if (!uid) return undefined;
    let live = true;
    api.ruangKirim('/dashboard/layout?surface=beranda').then(({ ok, data }) => {
      if (!live) return;
      if (ok && data) { setTutup(null); setLayout(data); saveCache(kunciLayout, data); return; }
      if (data?.kode === 'di_luar_jam_kerja') setTutup({ detail: data.detail, bukaLagi: data.buka_lagi });
    });
    return () => { live = false; };
  }, [uid, tick]);

  const items = useMemo(() => itemsForData(layout, knownCard), [layout]);
  const itemsKey = JSON.stringify(items);

  useEffect(() => {
    if (!items.length || tutup) return;
    const ini = ++seq.current;
    api.ruangKirim('/dashboard/data', 'POST', { periode: null, items }).then(({ ok, data }) => {
      if (ini !== seq.current) return;
      if (ok && data) { setResp(data); if (kunciData) saveCache(kunciData, data); return; }
      if (data?.kode === 'di_luar_jam_kerja') { setTutup({ detail: data.detail, bukaLagi: data.buka_lagi }); return; }
      const cached = kunciData ? loadCache(kunciData) : null;
      setResp(cached || { data: Object.fromEntries(items.map(i => [i.id, GAGAL])) });
    });
    // itemsKey mewakili `items` (lihat BerandaRegistry).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemsKey, tick, uid, tutup]);

  if (tutup) return <Tutup {...tutup} ruangNama={ruangNama} />;
  if (!layout || !resp) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  const ctx = { isDark: mode === 'dark', isCurrentPeriod: true, phone, today: localDateStr(), refresh, ruangNama };
  const firstName = (user?.name || '').trim().split(/\s+/)[0];
  return (
    <div className="space-y-4">
      <div className="lg:hidden">
        <p className="text-xl font-bold" style={{ color: 'var(--text)' }}>Halo, {firstName || 'kamu'}</p>
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Karyawan · {ruangNama}</p>
      </div>
      <p className="hidden lg:block text-sm" style={{ color: 'var(--text-muted)' }}>
        Kamu bekerja di <b style={{ color: 'var(--text)' }}>{ruangNama}</b> sebagai karyawan.
      </p>
      <DashboardGrid layout={layout} data={resp.data || {}} ctx={ctx} />
    </div>
  );
}
