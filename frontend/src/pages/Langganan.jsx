import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatShort } from '../lib/utils';
import { EnvelopeIcon, Icon } from '../components/Icon';
import StatCard from '../components/StatCard';
import AdvisorRowStrip from '../components/AdvisorRowStrip';
import { useTheme } from '../hooks/useTheme';
import { focusItems, localAction, pageEnabled, rowInsight, summaryLine } from '../lib/advisorLangganan';
import {
  statusMeta, unpaidMonthlyTotal,
  monthlyEquivalentTotal, paidMonthlyTotal, nearestDue, isUnpaid, canPay, payableFromLabel,
  searchSubscriptions, sortSubscriptions,
} from '../lib/subscriptionStatus';

const TONE_CLS = {
  danger: 'bg-red-50 text-danger-400', warning: 'bg-amber-50 text-amber-600',
  safe: 'bg-brand-50 text-brand-600', neutral: 'bg-gray-100 text-gray-500',
};

// inline: tampil sebagai isi (mis. tab di modal Langganan top bar), tanpa overlay sendiri.
// prefill (mode buat): isian awal dari CTA "Jadikan langganan" — lihat recurringPrefill().
export function RecurringModal({ onClose, onSaved, item, inline = false, prefill = null }) {
  const isEdit = !!item;
  const pre = !isEdit && prefill ? prefill : {};
  const [envelopes, setEnvelopes] = useState([]);
  const [desc, setDesc] = useState(item?.description || pre.description || '');
  const [amount, setAmount] = useState(item?.amount ? String(item.amount) : (pre.amount || ''));
  const [frequency, setFrequency] = useState(item?.frequency || pre.frequency || 'monthly');
  const [envelopeId, setEnvelopeId] = useState(item?.envelope_id || pre.envelopeId || '');
  const [nextRun, setNextRun] = useState(item?.next_run || pre.nextRun || (() => {
    const d = new Date();
    d.setMonth(d.getMonth() + 1);
    return d.toISOString().split('T')[0];
  })());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.getEnvelopeSummary().then(envs => {
      setEnvelopes(envs || []);
      if (!isEdit && envs?.length) {
        setEnvelopeId(cur => (envs.some(e => e.id === cur) ? cur : envs[0].id));
      }
    });
  }, []);

  const handleSubmit = async () => {
    if (!desc || !amount || !envelopeId) { setError('Lengkapi semua field'); return; }
    setSaving(true);
    setError('');
    const res = await api.request(isEdit ? `/recurring/${item.id}` : '/recurring/', {
      method: isEdit ? 'PUT' : 'POST',
      body: JSON.stringify({
        description: desc,
        amount: Number(amount),
        frequency,
        envelope_id: envelopeId,
        next_run: nextRun,
      }),
    });
    setSaving(false);
    if (res.ok) { onSaved(); onClose(); }
    else { const d = await res.json(); setError(d.detail || 'Gagal menyimpan'); }
  };

  const form = (
    <>
        <div className="space-y-3">
          <div>
            <label className="label">Nama langganan</label>
            <input type="text" className="input" placeholder="Netflix, Sewa server..." value={desc} onChange={e => setDesc(e.target.value)} />
          </div>
          <div>
            <label className="label">Jumlah (Rp)</label>
            <input type="number" className="input font-mono" placeholder="54000" value={amount} onChange={e => setAmount(e.target.value)} min="1" />
          </div>
          <div>
            <label className="label">Frekuensi</label>
            <select className="input" value={frequency} onChange={e => setFrequency(e.target.value)}>
              <option value="weekly">Mingguan</option>
              <option value="monthly">Bulanan</option>
              <option value="yearly">Tahunan</option>
            </select>
          </div>
          <div>
            <label className="label">Amplop</label>
            <select className="input" value={envelopeId} onChange={e => setEnvelopeId(e.target.value)}>
              {envelopes.map(e => <option key={e.id} value={e.id}>{e.emoji} {e.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Jatuh tempo pertama</label>
            <input type="date" className="input" value={nextRun} onChange={e => setNextRun(e.target.value)} />
          </div>
        </div>
        {error && <div className="mt-3 bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>{error}</div>}
        <div className="flex gap-2 mt-4">
          <button type="button" onClick={onClose} className="btn-outline flex-1">Batal</button>
          <button type="button" onClick={handleSubmit} disabled={saving} className="btn-primary flex-1 disabled:opacity-50">
            {saving ? '...' : 'Simpan'}
          </button>
        </div>
    </>
  );

  if (inline) return form;
  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-sm p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-bold text-lg mb-4">{isEdit ? 'Edit Langganan' : 'Tambah Langganan'}</h3>
        {form}
      </div>
    </div>
  );
}

export default function Langganan() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editItem, setEditItem] = useState(null);
  const [busy, setBusy] = useState(null); // id sedang diproses — cegah double-pay
  const [search, setSearch] = useState('');
  const [sortMode, setSortMode] = useState('priority');
  // AI Advisor (S12): GET /advisor/page/langganan, hanya untuk user di flag advisor_v2_users.
  const [advisor, setAdvisor] = useState(null);
  const [hiddenKeys, setHiddenKeys] = useState([]);
  const [focusIds, setFocusIds] = useState(null);
  const { mode } = useTheme();
  const isDark = mode === 'dark';

  const load = () => {
    api.request('/recurring/').then(r => r.ok ? r.json() : []).then(d => { setItems(d); setLoading(false); });
    api.getAdvisorLangganan().then(p => { setAdvisor(pageEnabled(p) ? p : null); setHiddenKeys([]); });
  };
  useEffect(load, []);
  // Tambah/bayar/geser lewat top bar, FAB, atau CTA juga menyegarkan halaman ini.
  useEffect(() => {
    const events = ['jatahku:txn-added', 'jatahku:envelope-updated', 'jatahku:advisor-undismissed'];
    events.forEach(e => window.addEventListener(e, load));
    return () => events.forEach(e => window.removeEventListener(e, load));
  }, []);

  // CTA yang menuju halaman ini sendiri → aksi lokal (lihat localAction).
  const onLocal = (ctx) => (aksi) => {
    const act = localAction(aksi, ctx);
    if (!act) return false;
    if (act.type === 'edit') {
      const it = items.find(i => String(i.id) === String(act.recurringId));
      if (it) setEditItem(it);
    } else if (act.type === 'focus') setFocusIds(act.recurringIds);
    else if (act.type === 'sort') setSortMode(act.mode);
    return true;
  };
  const hideKey = (kunci) => setHiddenKeys(k => [...k, kunci]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('new') === '1') setShowAdd(true);
  }, []);

  const handleDelete = async (id, name) => {
    if (!confirm(`Hapus langganan "${name}"?`)) return;
    await api.request(`/recurring/${id}`, { method: 'DELETE' });
    load();
  };

  const handlePay = async (item) => {
    if (busy) return;
    setBusy(item.id);
    const r = await api.payRecurring(item.id);
    setBusy(null);
    if (!r.ok && r.data?.detail) alert(r.data.detail);
    load();
  };
  const handleSkip = async (item) => {
    if (busy) return;
    setBusy(item.id);
    const r = await api.skipRecurring(item.id);
    setBusy(null);
    if (!r.ok && r.data?.detail) alert(r.data.detail);
    load();
  };

  const freqLabel = (f) => {
    const map = { weekly: 'Mingguan', monthly: 'Bulanan', yearly: 'Tahunan' };
    return map[f] || f;
  };

  // KPI — semua dari list /recurring/ (status server-computed), tanpa fetch tambahan
  const totalMonthly = monthlyEquivalentTotal(items);
  const paidTotal = paidMonthlyTotal(items);
  const unpaidTotal = unpaidMonthlyTotal(items);
  const monthlyCount = items.filter(i => i.frequency === 'monthly').length;
  const paidCount = items.filter(i => i.frequency === 'monthly' && i.status === 'paid').length;
  const unpaidCount = items.filter(i => i.frequency === 'monthly' && isUnpaid(i)).length;
  const overdueCount = items.filter(i => i.status === 'overdue').length;
  const nearest = nearestDue(items);
  const nearestIsLate = nearest?.status === 'overdue';
  const fmtDate = (d) => new Date(d).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });
  const shown = sortSubscriptions(searchSubscriptions(focusItems(items, focusIds), search), sortMode);
  const ringkasan = advisor?.ringkasan;
  const ringkasLine = summaryLine(ringkasan, formatShort);
  const visible = (list) => (list || []).filter(i => !hiddenKeys.includes(i.dismiss?.kunci || i.id));

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold">Langganan</h1>
          <p className="text-sm text-gray-500">Pembayaran rutin yang tercatat otomatis</p>
        </div>
      </div>

      {items.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard icon="langganan" tone="indigo" label="Total per Bulan"
            value={formatShort(totalMonthly)} sub={`${items.length} langganan aktif`} />
          <StatCard icon="check" tone="green" label="Sudah Dibayar"
            value={formatShort(paidTotal)} sub={`${paidCount} dari ${monthlyCount} bulanan`} />
          <StatCard icon="warning" tone={overdueCount > 0 ? 'red' : 'orange'} label="Belum Dibayar"
            value={formatShort(unpaidTotal)}
            sub={overdueCount > 0 ? `${overdueCount} terlambat!` : `${unpaidCount} tagihan menunggu`} />
          <StatCard icon="calendar" tone={nearestIsLate ? 'red' : 'purple'} label="Jatuh Tempo Terdekat"
            value={nearest ? fmtDate(nearest.next_run) : '—'}
            sub={nearest ? `${nearestIsLate ? 'Terlambat · ' : ''}${nearest.description}` : 'Semua terbayar'} />
        </div>
      )}

      {advisor && (ringkasLine || ringkasan?.insight || visible(advisor.lain).length > 0 || visible(advisor.pola).length > 0) && (
        <div className="card space-y-2">
          <div className="flex items-center gap-2">
            <Icon name="advisor" size={16} weight="fill" className="text-brand-600" />
            <h2 className="font-semibold text-sm">AI Advisor</h2>
          </div>
          {ringkasLine && <p className="text-sm" style={{ color: 'var(--text-muted)' }}>{ringkasLine}</p>}
          {visible([ringkasan?.insight].filter(Boolean)).map(ins => (
            <AdvisorRowStrip key={ins.id} insight={ins} isDark={isDark} onLocal={onLocal({})} onHide={hideKey} />
          ))}
          {visible(advisor.lain).map(ins => (
            <AdvisorRowStrip key={ins.id} insight={ins} isDark={isDark}
              onLocal={onLocal({ recurringIds: ins.recurring_ids })} onHide={hideKey} />
          ))}
          {visible(advisor.pola).map(ins => (
            <AdvisorRowStrip key={ins.id} insight={ins} isDark={isDark} onLocal={onLocal({})} onHide={hideKey} />
          ))}
        </div>
      )}

      {focusIds && (
        <div className="flex items-center justify-between text-sm px-1">
          <span style={{ color: 'var(--text-muted)' }}>Menampilkan {focusIds.length} langganan yang mirip</span>
          <button type="button" onClick={() => setFocusIds(null)} className="text-brand-600 font-medium hover:underline">
            Tampilkan semua
          </button>
        </div>
      )}

      {items.length > 0 && (
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Icon name="search" size={18} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari langganan atau amplop..."
              className="input !pl-11" />
          </div>
          <select value={sortMode} onChange={e => setSortMode(e.target.value)}
            className="input !w-auto flex-shrink-0 text-sm">
            <option value="priority">Prioritas bayar</option>
            <option value="due">Jatuh tempo terdekat</option>
            <option value="expensive">Termahal</option>
            <option value="cheap">Termurah</option>
            <option value="name">Nama A-Z</option>
          </select>
        </div>
      )}

      {items.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-4xl mb-3">🔄</p>
          <p className="text-gray-500 mb-2">Belum ada langganan</p>
          <p className="text-sm text-gray-400 mb-4">Tambah lewat tombol di atas atau via Telegram</p>
          <button onClick={() => setShowAdd(true)} className="btn-primary">+ Tambah Langganan</button>
        </div>
      ) : shown.length === 0 ? (
        <div className="card text-center py-8 text-sm text-gray-400">Tidak ada langganan yang cocok dengan "{search}"</div>
      ) : (
        <div className="space-y-3">
          {shown.map(item => {
            const meta = statusMeta(item.status);
            const isPaid = item.status === 'paid';
            const ai = rowInsight(advisor, item.id, hiddenKeys);
            return (
            <div key={item.id} className="card group hover:border-brand-200 transition-all">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <EnvelopeIcon value={item.envelope_emoji} size={26} />
                  <div>
                    <h3 className="font-semibold">{item.description}</h3>
                    <p className="text-xs text-gray-400">
                      {item.envelope_name} · {freqLabel(item.frequency)}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="font-display font-bold text-lg">{formatShort(item.amount)}</p>
                  <p className="text-xs text-gray-400">Next: {new Date(item.next_run).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' })}</p>
                  {item.status && (
                    <span className={`inline-block text-[11px] px-1.5 py-0.5 rounded-md mt-1 ${TONE_CLS[meta.tone]}`}>{meta.label}</span>
                  )}
                </div>
              </div>
              {ai && (
                <AdvisorRowStrip insight={ai} isDark={isDark} className="mt-3"
                  onLocal={onLocal({ recurringId: item.id })} onHide={hideKey} />
              )}
              <div className="flex items-center justify-end gap-3 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
                {isPaid ? (
                  <span className="text-xs text-brand-600 flex items-center gap-1"><Icon name="check" size={14} weight="fill" /> Sudah bayar</span>
                ) : !canPay(item) ? (
                  <span className="text-xs text-gray-400">{payableFromLabel(item)}</span>
                ) : (
                  <>
                    <button disabled={busy === item.id} onClick={() => handleSkip(item)}
                      className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-50">Lewati</button>
                    <button disabled={busy === item.id} onClick={() => handlePay(item)}
                      className="text-xs font-medium px-3 py-1 rounded-lg bg-brand-600 text-white disabled:opacity-50">Bayar</button>
                  </>
                )}
                <button onClick={() => setEditItem(item)}
                  className="text-xs text-brand-500 hover:underline">Edit</button>
                <button onClick={() => handleDelete(item.id, item.description)}
                  className="text-xs text-danger-400 hover:underline">Hapus</button>
              </div>
            </div>
            );
          })}
        </div>
      )}

      {showAdd && <RecurringModal onClose={() => setShowAdd(false)} onSaved={load} />}
      {editItem && <RecurringModal onClose={() => setEditItem(null)} onSaved={load} item={editItem} />}
    </div>
  );
}
