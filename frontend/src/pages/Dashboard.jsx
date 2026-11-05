// Beranda (Plugin B2): memilih Beranda registry atau Beranda lama.
// GET /dashboard/layout membawa `enabled` = user ada di flag `beranda_registry_users` (AppSetting).
// Tata letak terakhir disimpan di localCache per user, supaya kunjungan berikutnya langsung memakai
// Beranda yang benar tanpa menunggu; sebelum ada jawaban atau bila gagal, Beranda lama tetap jalan.
// `?beranda=lama|registry` memaksa salah satu untuk membandingkan tampilan (B3, alat banding).
//
// Karyawan ruang usaha (Plugin R6): selalu Beranda template "Karyawan" (BerandaKaryawan). Dikenali dari peran di
// ruang aktif (GET /ruang) atau dari tata letak (`untuk: "karyawan"`), mana yang lebih dulu ada.
import { useEffect, useState } from 'react';
import { useLocation, useOutletContext } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { loadCache, saveCache } from '../lib/localCache';
import { cacheKeyLayout, paksaDariUrl, pilihBeranda } from '../lib/dashboardRegistry';
import { adaKartuPlugin } from '../lib/pluginHost';
import BerandaLama from './BerandaLama';
import BerandaRegistry from './BerandaRegistry';
import BerandaKaryawan from './BerandaKaryawan';

export default function Dashboard() {
  const { user } = useAuth();
  const { search } = useLocation();
  const { akses, plugin } = useOutletContext() || {};
  const uid = user?.id;
  const [layout, setLayout] = useState(() => (uid ? loadCache(cacheKeyLayout(uid)) : null));
  // Peran dari GET /ruang menang bila sudah ada (tata letak di cache bisa milik peran lama).
  const karyawan = akses?.ruangId ? akses.karyawan : layout?.untuk === 'karyawan';

  useEffect(() => {
    if (!uid || karyawan) return undefined;
    let live = true;
    api.getDashboardLayout().then(l => {
      if (!live || !l) return;
      setLayout(l);
      saveCache(cacheKeyLayout(uid), l);
    });
    return () => { live = false; };
  }, [uid, karyawan]);

  if (karyawan) return <BerandaKaryawan />;
  const paksa = paksaDariUrl(search);
  // Kartu Fitur Tambahan hanya dikenal Beranda registry (Plugin H3): tata letak yang memuatnya selalu digambar registry,
  // walau user di luar flag `beranda_registry_users`.
  const pilihan = !paksa && adaKartuPlugin(layout, plugin?.kontribusi) ? 'registry' : pilihBeranda(layout, paksa);
  if (pilihan === 'memuat') return <div className="text-center py-12 text-gray-400">Loading...</div>;
  return pilihan === 'registry' ? <BerandaRegistry layout={layout} /> : <BerandaLama />;
}
