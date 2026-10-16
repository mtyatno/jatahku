import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { formatCurrency } from '../lib/utils';
import { Icon } from './Icon';
import {
  executeBody, kebutuhanTotal, newClientRef, rencanaTotal, toggleRow, TINGKAT_LABEL,
} from '../lib/advisorAction';

// Lembar konfirmasi rencana dana AI Advisor (02-aturan.md §8.9): rencana dari
// POST /advisor/plan, centang sumber bisa dilepas (server menghitung ulang
// tanpa sumber itu), satu tap → POST /advisor/execute dengan client_ref.
// 409 "Saldo berubah" → rencana baru ditampilkan untuk dicek lagi.
// Frontend tidak menghitung sumber sendiri dan tidak mentransfer tanpa rencana.
export function PlanReview({ kebutuhan, onDone, onCancel, onIncome, confirmLabel }) {
  const [plan, setPlan] = useState(null);
  const [kecuali, setKecuali] = useState([]);
  const [names, setNames] = useState({});     // dari_id → nama, untuk sumber yang dilepas
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const clientRef = useRef(newClientRef());

  const adopt = useCallback((p) => {
    setPlan(p);
    setNames(prev => ({ ...prev, ...Object.fromEntries((p?.rencana || []).map(r => [r.dari_id, r.dari_nama])) }));
    clientRef.current = newClientRef(); // rencana baru = permintaan baru
  }, []);

  const load = useCallback(async (excl) => {
    setLoading(true);
    setError('');
    const res = await api.advisorPlan(kebutuhan, excl);
    setLoading(false);
    if (res.ok) { adopt(res.data); return; }
    setError(res.status === 404 ? 'Rencana dana belum tersedia di server. Coba lagi nanti.' : (res.data?.detail || 'Gagal menyusun rencana'));
  }, [kebutuhan, adopt]);

  useEffect(() => { load(kecuali); }, [load, kecuali]);

  const toggle = (row) => {
    if (row.tercentang) setKecuali(k => [...new Set([...k, row.dari_id])]);   // dilepas → hitung ulang
    else setPlan(p => ({ ...p, rencana: toggleRow(p.rencana, row.dari_id) })); // sumber opsional dicentang
  };
  const restore = id => setKecuali(k => k.filter(x => x !== id));

  const execute = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    const res = await api.advisorExecute(executeBody(plan, clientRef.current));
    setBusy(false);
    if (res.ok) {
      window.dispatchEvent(new CustomEvent('jatahku:envelope-updated'));
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      onDone?.(res.data);
      return;
    }
    const baru = res.data?.rencana_baru ?? res.data?.detail?.rencana_baru;
    if (res.status === 409 && baru) {
      adopt(baru);
      setNotice('Saldo amplop berubah sejak rencana dibuat. Rencana sudah dihitung ulang — cek lagi lalu konfirmasi.');
      return;
    }
    const detail = res.data?.detail;
    setError(typeof detail === 'string' ? detail : 'Gagal menjalankan rencana. Coba lagi.');
  };

  const need = kebutuhanTotal(kebutuhan);
  const rows = plan?.rencana || [];
  const chosen = rencanaTotal(rows);
  const bayar = plan?.bayar || [];
  const bayarTotal = bayar.reduce((s, b) => s + (Number(b.jumlah) || 0), 0);
  const kurang = Number(plan?.kurang) || 0;
  const label = confirmLabel || (bayar.length ? 'Geser & bayar' : 'Geser dana');

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-500">Dibutuhkan</span>
        <span className="font-mono font-semibold">{formatCurrency(need)}</span>
      </div>

      {notice && <div className="bg-amber-50 border border-amber-200 text-xs px-3 py-2 rounded-xl text-amber-800">{notice}</div>}
      {error && <div className="bg-red-50 border border-red-200 text-xs px-3 py-2 rounded-xl text-red-600 font-medium">{error}</div>}

      {loading && !plan ? (
        <div className="text-center py-6 text-gray-400 text-sm">Menyusun rencana…</div>
      ) : !plan ? (
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="btn-outline text-xs py-2 px-3">Tutup</button>
          <button type="button" onClick={() => load(kecuali)} className="btn-primary text-xs py-2 px-4">Coba lagi</button>
        </div>
      ) : (
        <>
          <ul className={`space-y-2 ${loading ? 'opacity-50' : ''}`}>
            {rows.length === 0 && <li className="text-xs text-gray-500">Tidak ada amplop yang bisa digeser.</li>}
            {rows.map(r => (
              <li key={r.dari_id} className="flex items-start gap-2.5 border border-gray-100 rounded-xl p-2.5">
                <input type="checkbox" className="mt-1" checked={!!r.tercentang} disabled={loading || busy}
                  onChange={() => toggle(r)} aria-label={`Pakai ${r.dari_nama}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium truncate">{r.dari_nama}</span>
                    <span className="font-mono text-sm shrink-0">{formatCurrency(r.jumlah)}</span>
                  </div>
                  {r.alasan && <p className="text-xs text-gray-500 mt-0.5">{r.alasan}</p>}
                  {r.tingkat === 'c' && (
                    <span className="inline-block text-[11px] px-1.5 py-0.5 rounded-md mt-1 bg-amber-50 text-amber-700">
                      {TINGKAT_LABEL.c}: belum ada riwayat belanja
                    </span>
                  )}
                </div>
              </li>
            ))}
            {kecuali.map(id => (
              <li key={`x-${id}`} className="flex items-center justify-between gap-2 text-xs text-gray-400 px-2.5">
                <span className="truncate line-through">{names[id] || 'Amplop'}</span>
                <button type="button" onClick={() => restore(id)} disabled={loading || busy}
                  className="text-brand-600 hover:underline shrink-0">Pakai lagi</button>
              </li>
            ))}
          </ul>

          {bayarTotal > 0 && (
            <div className="flex items-center justify-between text-xs text-gray-600">
              <span>Lalu bayar {bayar.length} tagihan</span>
              <span className="font-mono">{formatCurrency(bayarTotal)}</span>
            </div>
          )}

          {kurang > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-800 flex items-center justify-between gap-2">
              <span>Masih kurang <b className="font-mono">{formatCurrency(kurang)}</b></span>
              {onIncome && (
                <button type="button" onClick={() => onIncome(kurang)} className="text-brand-700 font-medium hover:underline shrink-0">
                  Catat pemasukan
                </button>
              )}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100">
            <button type="button" onClick={onCancel} className="btn-outline text-xs py-2 px-3" disabled={busy}>Batal</button>
            <button type="button" onClick={execute}
              disabled={busy || loading || (chosen <= 0 && bayar.length === 0)}
              className="btn-primary text-xs py-2 px-4 disabled:opacity-50 flex items-center gap-1.5">
              <Icon name="transfer" size={14} />
              {busy ? 'Memproses…' : `${label}${chosen > 0 ? ` ${formatCurrency(chosen)}` : ''}`}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// Aksi `plan` dari open-action: lembar rencana sebagai modal.
export default function PlanSheet({ kebutuhan, title, onClose, onIncome }) {
  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60] flex items-end sm:items-center justify-center sm:p-4" onClick={onClose}>
      <div className="bg-white rounded-t-2xl sm:rounded-2xl w-full max-w-md p-5 shadow-2xl space-y-4 max-h-[92vh] overflow-y-auto"
        onClick={e => e.stopPropagation()} role="dialog" aria-label={title || 'Rencana dana'}>
        <div className="flex items-start justify-between gap-3 border-b border-gray-100 pb-3">
          <div>
            <h3 className="font-display font-bold text-base text-gray-900 leading-tight">{title || 'Rencana dana'}</h3>
            <p className="text-xs text-gray-500 mt-0.5">Cek sumber dana, lepas centang yang tidak mau dipakai.</p>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100" aria-label="Tutup">
            <Icon name="close" size={18} />
          </button>
        </div>
        <PlanReview kebutuhan={kebutuhan} onDone={onClose} onCancel={onClose} onIncome={onIncome} />
      </div>
    </div>
  );
}
