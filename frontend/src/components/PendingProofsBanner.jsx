import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { shareStore } from '../lib/shareInbox';
import { useAppConfig } from '../hooks/useAppConfig';
import {
  NO_COUNTS, bannerView, createPendingCounter, receiptInboxOn, watchRefreshTriggers,
} from '../lib/pendingProofs';

// Banner "N bukti menunggu dikirim / dicatat" di Layout, di samping banner antrean offline (spec 5b/5c). Ketuk →
// /bagikan, yang mengirim bukti lokal dan menampilkan kartunya. Semua aturan di lib/pendingProofs.js; komponen ini
// hanya menyambungkan saklar, router, API, dan kotak share.
export default function PendingProofsBanner() {
  const enabled = receiptInboxOn(useAppConfig());
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [counts, setCounts] = useState(NO_COUNTS);
  const counterRef = useRef(null);

  // Saklar menyala → satu penghitung dan pemicunya (online, txn-added, kotak-changed, terlihat lagi). Saklar mati,
  // juga sebelum config terbaca: tanpa permintaan, tanpa IndexedDB, tanpa listener. Mati sesudah menyala → semuanya
  // dilepas dan banner hilang.
  useEffect(() => {
    if (!enabled) return undefined;
    const store = shareStore();
    const counter = createPendingCounter({
      loadUnsent: () => store.all(),
      loadReady: () => api.kotakPendingCount(),
      onCounts: setCounts,
    });
    counterRef.current = counter;
    const unwatch = watchRefreshTriggers(() => counter.refresh(), { win: window, doc: document });
    return () => {
      unwatch();
      counter.stop();
      if (counterRef.current === counter) counterRef.current = null;
      setCounts(NO_COUNTS);
    };
  }, [enabled]);

  // Hitung saat dipasang atau saklar menyala, dan setiap pindah halaman: melewati kartu di /bagikan tidak mengirim
  // event, jadi meninggalkan /bagikan harus menghitung ulang.
  useEffect(() => {
    counterRef.current?.refresh();
  }, [enabled, pathname]);

  const view = bannerView({ enabled, pathname, counts });
  if (!view) return null;
  return (
    <div className="max-w-6xl mx-auto px-4 pt-3" role="status">
      <button
        type="button"
        onClick={() => navigate('/bagikan')}
        className="w-full text-left rounded-xl border border-amber-200 bg-amber-50 text-amber-600 text-sm px-3 py-2"
      >
        {view.lead} · <span className="underline font-medium">{view.action}</span>
      </button>
    </div>
  );
}
