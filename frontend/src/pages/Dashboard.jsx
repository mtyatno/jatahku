// Beranda (Plugin B2): memilih Beranda registry atau Beranda lama.
// GET /dashboard/layout membawa `enabled` = user ada di flag `beranda_registry_users` (AppSetting).
// Tata letak terakhir disimpan di localCache per user, supaya kunjungan berikutnya langsung memakai
// Beranda yang benar tanpa menunggu; sebelum ada jawaban atau bila gagal, Beranda lama tetap jalan.
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { loadCache, saveCache } from '../lib/localCache';
import { cacheKeyLayout } from '../lib/dashboardRegistry';
import BerandaLama from './BerandaLama';
import BerandaRegistry from './BerandaRegistry';

export default function Dashboard() {
  const { user } = useAuth();
  const uid = user?.id;
  const [layout, setLayout] = useState(() => (uid ? loadCache(cacheKeyLayout(uid)) : null));

  useEffect(() => {
    if (!uid) return undefined;
    let live = true;
    api.getDashboardLayout().then(l => {
      if (!live || !l) return;
      setLayout(l);
      saveCache(cacheKeyLayout(uid), l);
    });
    return () => { live = false; };
  }, [uid]);

  return layout?.enabled ? <BerandaRegistry layout={layout} /> : <BerandaLama />;
}
