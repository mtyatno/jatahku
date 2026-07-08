import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';
import { Icon, EnvelopeIcon, BRAND } from './Icon';
import { unpaidMonthlyTotal, sortForPayment, statusMeta } from '../lib/subscriptionStatus';

const TONE_CLS = {
  danger: 'bg-red-50 text-danger-400', warning: 'bg-amber-50 text-amber-600',
  safe: 'bg-brand-50 text-brand-600', neutral: 'bg-gray-100 text-gray-500',
};

export default function PaySubscriptions({ onClose }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [edit, setEdit] = useState({});          // id -> nominal string (editable)
  const [busy, setBusy] = useState(null);        // id sedang diproses
  const [toast, setToast] = useState(null);      // { text, undo }

  const load = () => api.getRecurring().then(d => { setItems(d || []); setLoading(false); });
  useEffect(() => { load(); }, []);

  const flip = (id, status) => setItems(prev => prev.map(i => i.id === id ? { ...i, status } : i));

  const pay = async (item) => {
    setBusy(item.id);
    const amt = edit[item.id] != null && edit[item.id] !== '' ? edit[item.id] : null;
    const res = await api.payRecurring(item.id, amt);
    setBusy(null);
    if (!res.ok) { setToast({ text: 'Gagal mencatat pembayaran' }); return; }
    flip(item.id, 'paid');
    window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
    setToast({
      text: `Tercatat: ${item.description}`,
      undo: async () => {
        await api.deleteTransaction(res.data.txn_id);
        await api.restoreRecurringNextRun(item, res.data.prev_next_run);
        flip(item.id, 'due');
        window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
        setToast(null);
      },
    });
    setTimeout(() => setToast(t => (t && t.text.includes(item.description) ? null : t)), 6000);
  };

  const skip = async (item) => {
    setBusy(item.id);
    const res = await api.skipRecurring(item.id);
    setBusy(null);
    if (res.ok) { flip(item.id, 'paid'); }
  };

  const sorted = sortForPayment(items);
  const sisa = unpaidMonthlyTotal(items);

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-gray-500">Sisa belum bayar bulan ini</p>
        <p className="font-display font-bold text-amber-500">{formatCurrency(sisa)}</p>
      </div>
      {loading ? (
        <div className="text-center py-8 text-gray-400 text-sm">Loading...</div>
      ) : sorted.length === 0 ? (
        <div className="text-center py-8 text-gray-400 text-sm">Belum ada langganan.</div>
      ) : (
        <div className="space-y-2 max-h-[60vh] overflow-y-auto">
          {sorted.map(item => {
            const meta = statusMeta(item.status);
            const isPaid = item.status === 'paid';
            return (
              <div key={item.id} className="flex items-center gap-3 border border-gray-100 rounded-xl p-3">
                <EnvelopeIcon value={item.envelope_emoji} size={22} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{item.description}</p>
                  <p className="text-xs text-gray-400 truncate">{item.envelope_name}</p>
                  <span className={`inline-block text-[11px] px-1.5 py-0.5 rounded-md mt-1 ${TONE_CLS[meta.tone]}`}>{meta.label}</span>
                </div>
                {isPaid ? (
                  <Icon name="check" size={20} weight="fill" color={BRAND} />
                ) : (
                  <div className="flex flex-col items-end gap-1">
                    <input type="number" className="input font-mono text-right text-sm !py-1 w-28"
                      value={edit[item.id] ?? String(Math.round(Number(item.amount)))}
                      onChange={e => setEdit(p => ({ ...p, [item.id]: e.target.value }))} />
                    <div className="flex gap-2">
                      <button disabled={busy === item.id} onClick={() => skip(item)}
                        className="text-xs text-gray-400 hover:text-gray-600">Lewati</button>
                      <button disabled={busy === item.id} onClick={() => pay(item)}
                        className="text-xs font-medium px-3 py-1 rounded-lg bg-brand-600 text-white disabled:opacity-50">Bayar</button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {toast && (
        <div className="mt-3 flex items-center justify-between gap-2 rounded-xl px-3 py-2 bg-gray-900 text-white text-sm">
          <span className="truncate">{toast.text}</span>
          {toast.undo && <button onClick={toast.undo} className="font-medium text-brand-200 shrink-0">Urungkan</button>}
        </div>
      )}
    </div>
  );
}
