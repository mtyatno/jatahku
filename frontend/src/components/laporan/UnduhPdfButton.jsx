import { useState, useRef } from 'react';
import { api } from '../../lib/api';
import { native } from '../../native';
import { unduhPdf } from '../../lib/laporanView';
import KataSandiForm from './KataSandiForm';

// Tombol "Unduh PDF". Belum ada kata sandi (409) → dialog kata sandi; setelah tersimpan unduhan diulang sekali.
export default function UnduhPdfButton({ laporan, className = '' }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [dialog, setDialog] = useState(false);
  const pendingRef = useRef(null);

  const mintaKataSandi = () => new Promise((resolve) => {
    pendingRef.current = resolve;
    setDialog(true);
  });

  const tutupDialog = (hasil) => {
    setDialog(false);
    pendingRef.current?.(hasil);
    pendingRef.current = null;
  };

  const klik = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await unduhPdf({ api, native, laporan, mintaKataSandi });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={className}>
      <button type="button" onClick={klik} disabled={busy} className="btn-primary text-sm py-2.5 disabled:opacity-50 w-full sm:w-auto">
        {busy ? 'Menyiapkan...' : 'Unduh PDF'}
      </button>
      {error && <p className="text-sm text-danger-400 mt-2" role="alert">{error}</p>}
      {dialog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" role="dialog" aria-modal="true" aria-labelledby="laporan-sandi-title">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 space-y-4 shadow-xl">
            <h3 id="laporan-sandi-title" className="text-lg font-semibold">🔒 Atur kata sandi laporan</h3>
            <p className="text-sm text-gray-600">Atur kata sandi laporan dulu untuk mengunduh PDF.</p>
            <KataSandiForm onSaved={() => tutupDialog(true)} onCancel={() => tutupDialog(false)} />
          </div>
        </div>
      )}
    </div>
  );
}
