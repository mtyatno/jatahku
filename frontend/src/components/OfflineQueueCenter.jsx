import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';
import { getPendingCount, getRejected, syncNow, retryRejected, discardRejected, onBackgroundSynced } from '../lib/offlineQueue';

function rupiah(n) {
  return 'Rp ' + Number(n || 0).toLocaleString('id-ID');
}

function isDailyLimit(msg) {
  return String(msg || '').toLowerCase().includes('limit harian');
}

function fmtDate(item) {
  const d = item.transaction_date ? new Date(`${item.transaction_date}T00:00:00`) : new Date(item.queuedAt || Date.now());
  return d.toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });
}

const send = items => api.batchCreateTransactions(items);

// Antrean transaksi offline: dikirim sekali (batch) saat app dibuka / online lagi,
// hanya bila ada isinya. Transaksi yang DITOLAK saat sinkron (dana kurang, kuota
// habis, amplop dikunci, …) tidak hilang: ditampilkan di sini untuk diperbaiki,
// dicoba lagi, atau dihapus.
export default function OfflineQueueCenter() {
  const [rejected, setRejected] = useState([]);
  const [notice, setNotice] = useState(null);
  const [open, setOpen] = useState(false);
  const [envelopes, setEnvelopes] = useState([]);
  const [busyId, setBusyId] = useState(null);

  const refresh = useCallback(async () => {
    try {
      setRejected(await getRejected());
    } catch {
      // IndexedDB tidak tersedia (mode privat tertentu) — tidak ada antrean
    }
  }, []);

  const sync = useCallback(async () => {
    if (!navigator.onLine) return null;
    try {
      if ((await getPendingCount()) === 0) return null;
      const summary = await syncNow(send);
      if (summary?.notice) setNotice(summary.notice);
      return summary;
    } catch {
      return null; // tetap di antrean, dicoba lagi pada pemicu berikutnya
    } finally {
      refresh();
    }
  }, [refresh]);

  useEffect(() => {
    refresh();
    sync();
    const onQueue = () => refresh();
    const offSynced = onBackgroundSynced((summary) => {
      refresh();
      if (summary.notice) setNotice(summary.notice);
      if (summary.saved > 0) window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
    });
    window.addEventListener('online', sync);
    window.addEventListener('jatahku:offline-queue', onQueue);
    return () => {
      window.removeEventListener('online', sync);
      window.removeEventListener('jatahku:offline-queue', onQueue);
      offSynced();
    };
  }, [refresh, sync]);

  useEffect(() => {
    if (!open || envelopes.length) return;
    api.getEnvelopes()
      .then(list => setEnvelopes((Array.isArray(list) ? list : []).filter(e => e.purpose !== 'saving' && e.purpose !== 'sinking_fund')))
      .catch(() => {});
  }, [open, envelopes.length]);

  useEffect(() => {
    if (open && rejected.length === 0) setOpen(false);
  }, [open, rejected.length]);

  const retry = async (item, patch = {}) => {
    setBusyId(item.id);
    try {
      await retryRejected(item.id, patch);
      await sync();
    } finally {
      setBusyId(null);
    }
  };

  const retryAll = async () => {
    setBusyId('all');
    try {
      for (const item of rejected) await retryRejected(item.id);
      await sync();
    } finally {
      setBusyId(null);
    }
  };

  const discard = async (item) => {
    if (!window.confirm(`Hapus "${item.description || 'transaksi'}" ${rupiah(item.amount)}? Transaksi ini tidak akan dicatat.`)) return;
    await discardRejected(item.id);
  };

  if (rejected.length === 0 && !notice) return null;

  return (
    <>
      <div className="max-w-6xl mx-auto px-4 pt-3 space-y-2">
        {rejected.length > 0 && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 text-amber-800 text-sm px-3 py-2 flex items-center gap-2 flex-wrap" role="status">
            <span>⚠️ {rejected.length} transaksi yang dicatat saat offline gagal tersimpan.</span>
            <button type="button" onClick={() => setOpen(true)} className="underline font-medium">Tinjau</button>
          </div>
        )}
        {notice && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 text-amber-800 text-sm px-3 py-2 flex items-start gap-2" role="status">
            <span className="flex-1">{notice}</span>
            <button type="button" onClick={() => setNotice(null)} className="shrink-0 text-amber-700" aria-label="Tutup pemberitahuan">&times;</button>
          </div>
        )}
      </div>

      {open && (
        <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={() => setOpen(false)}>
          <div className="bg-white rounded-2xl w-full max-w-lg p-5 shadow-xl max-h-[90vh] overflow-y-auto space-y-3" onClick={e => e.stopPropagation()}>
            <div>
              <h3 className="font-display font-bold text-lg">Transaksi offline yang ditolak</h3>
              <p className="text-sm text-gray-500">
                Dicatat saat offline, lalu ditolak waktu disinkronkan. Perbaiki lalu coba lagi, atau hapus.
              </p>
            </div>
            <ul className="divide-y divide-gray-100 border border-gray-100 rounded-xl">
              {rejected.map(item => (
                <li key={item.id} className="p-3 space-y-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-medium text-sm truncate">{item.description || 'Pengeluaran'}</span>
                    <span className="font-mono text-sm shrink-0">{rupiah(item.amount)}</span>
                  </div>
                  <div className="text-xs text-gray-400">{fmtDate(item)}</div>
                  <div className="text-xs text-red-600">{item.rejected?.message}</div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <select
                      className="input text-xs py-1 flex-1 min-w-0"
                      value={item.envelope_id || ''}
                      disabled={busyId != null}
                      onChange={e => retry(item, { envelope_id: e.target.value })}
                      aria-label={`Amplop untuk ${item.description || 'transaksi'}`}
                    >
                      {!envelopes.some(env => env.id === item.envelope_id) && <option value={item.envelope_id || ''}>Amplop semula</option>}
                      {envelopes.map(env => (
                        <option key={env.id} value={env.id}>{env.emoji} {env.name}</option>
                      ))}
                    </select>
                    <button type="button" disabled={busyId != null} onClick={() => retry(item)} className="text-xs text-brand-600 underline font-medium disabled:opacity-50">
                      {busyId === item.id ? 'Mengirim…' : 'Coba lagi'}
                    </button>
                    {isDailyLimit(item.rejected?.message) && (
                      <button type="button" disabled={busyId != null} onClick={() => retry(item, { raise_daily_limit: true })} className="text-xs text-brand-600 underline font-medium disabled:opacity-50">
                        Catat, naikkan limit
                      </button>
                    )}
                    <button type="button" disabled={busyId != null} onClick={() => discard(item)} className="text-xs text-gray-500 underline disabled:opacity-50">
                      Hapus
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            <p className="text-xs text-gray-400">
              Dana kurang? Isi atau geser dana amplopnya dulu, lalu tekan Coba lagi. Ganti amplop langsung mengirim ulang.
            </p>
            <div className="flex items-center gap-3">
              <button type="button" disabled={busyId != null} onClick={retryAll} className="btn-primary disabled:opacity-50">
                {busyId === 'all' ? 'Mengirim…' : 'Coba lagi semua'}
              </button>
              <button type="button" onClick={() => setOpen(false)} className="btn-outline">Tutup</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
