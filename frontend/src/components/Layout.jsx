import { useState, useEffect, useRef, useCallback } from 'react';
import { NavLink, Outlet, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import NotificationBell from './NotificationBell';
import TelegramPrompt from './TelegramPrompt';
import OfflineQueueCenter from './OfflineQueueCenter';
import PendingProofsBanner from './PendingProofsBanner';
import MultiAddTransaction from './MultiAddTransaction';
import { pickReceiptPhoto } from './ReceiptInput';
import PaySubscriptions from './PaySubscriptions';
import BalanceCheck from './BalanceCheck';
import ChatPanel from './ChatPanel';
import FundEnvelopeModal from './FundEnvelopeModal';
import PlanSheet from './PlanSheet';
import Sidebar, { SIDEBAR_WIDTH } from './Sidebar';
import { CreateModal } from '../pages/Envelopes';
import { RecurringModal } from '../pages/Langganan';
import { api } from '../lib/api';
import { native } from '../native';
import { formatCurrency } from '../lib/utils';
import { chatDraft, dismissNotice, incomePrefill, normalizeAction, recurringPrefill, safeRoute } from '../lib/advisorAction';
import { formEnvelopes, percentagesFor, recommendationAllocations } from '../lib/allocationAdvice';
import { Icon, EnvelopeIcon } from './Icon';
import UpdateRequired from './UpdateRequired';
import { AppConfigProvider, useAppConfigLoader } from '../hooks/useAppConfig';
import { isUpdateRequired } from '../lib/appConfig';

function QuickAddEnvelope({ onClose }) {
  const [envelopes, setEnvelopes] = useState([]);
  const [groups, setGroups] = useState([]);
  const [goals, setGoals] = useState([]);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    Promise.all([api.getEnvelopeSummary(), api.getEnvelopeGroups(), api.getGoals()])
      .then(([e, g, gl]) => { setEnvelopes(e); setGroups(g); setGoals(gl); setReady(true); });
  }, []);
  return ready
    ? <CreateModal onClose={onClose} onCreated={onClose} envelopes={envelopes} groups={groups} goals={goals} />
    : <div className="text-center py-8 text-gray-400">Loading...</div>;
}

// Smallest rupiah denomination in use is Rp100, so allocations snap to it; the leftover goes to the sisa_ke envelope.
const RUPIAH_STEP = 100;
const floorRupiah = v => Math.floor(v / RUPIAH_STEP) * RUPIAH_STEP;

// prefill: { amount, source, envelopeId } dari CTA "Catat pemasukan" (incomePrefill()).
function QuickAddIncome({ onClose, prefill = null }) {
  const [envelopes, setEnvelopes] = useState([]);
  const [incomeAmount, setIncomeAmount] = useState(prefill?.amount || '');
  const [incomeDesc, setIncomeDesc] = useState(prefill?.source || 'Gaji');
  const [allocations, setAllocations] = useState(() => (
    prefill?.envelopeId && Number(prefill.amount) > 0 ? { [prefill.envelopeId]: Number(prefill.amount) } : {}
  ));
  const [percentages, setPercentages] = useState(() => (
    prefill?.envelopeId && Number(prefill.amount) > 0 ? { [prefill.envelopeId]: 100 } : {}
  ));
  const [typedAmounts, setTypedAmounts] = useState(() => (
    prefill?.envelopeId && Number(prefill.amount) > 0 ? { [prefill.envelopeId]: true } : {}
  ));
  const [saving, setSaving] = useState(false);
  const [loadingAuto, setLoadingAuto] = useState(false);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [sisaKe, setSisaKe] = useState(null);
  useEffect(() => {
    Promise.all([api.getEnvelopeSummary(), api.getAlokasiPage()])
      .then(([e, page]) => { setEnvelopes(e); setSisaKe(page?.sisa_ke || null); setReady(true); });
  }, []);

  const incomeNum = Number(incomeAmount) || 0;
  const totalAllocated = Object.values(allocations).reduce((s, v) => s + (Number(v) || 0), 0);
  const remainder = incomeNum - totalAllocated;

  // "Bagi otomatis" = rekomendasi yang sama dengan halaman Alokasi (S14).
  const handleAutoAllocate = async () => {
    if (incomeNum <= 0) { setError('Masukkan jumlah income terlebih dahulu'); return; }
    setLoadingAuto(true);
    setError('');
    const res = await api.getAllocationRecommendation(incomeNum).catch(() => null);
    setLoadingAuto(false);
    if (!res?.ok) { setError('Gagal mendapatkan saran alokasi'); return; }
    setSisaKe(res.data.sisa_ke || null);
    const fundable = new Set(formEnvelopes(envelopes, res.data.sisa_ke).filter(e => !e.is_locked).map(e => String(e.id)));
    const newAllocations = recommendationAllocations(res.data, fundable);
    if (Object.keys(newAllocations).length === 0) { setError('Belum ada target atau riwayat belanja amplop untuk dijadikan acuan. Isi manual dulu, ya.'); return; }
    setAllocations(newAllocations);
    setPercentages(percentagesFor(newAllocations, incomeNum));
    setTypedAmounts({});
  };

  const handlePercentageChange = (envId, pct) => {
    const newPct = Number(pct) || 0;
    if (newPct > 100) return;
    const newPercentages = { ...percentages };
    const newAllocations = { ...allocations };
    if (newPct === 0) {
      delete newPercentages[envId];
      delete newAllocations[envId];
    } else {
      newPercentages[envId] = newPct;
      newAllocations[envId] = floorRupiah((incomeNum * newPct) / 100);
    }
    setPercentages(newPercentages);
    setAllocations(newAllocations);
    setTypedAmounts(prev => { const next = { ...prev }; delete next[envId]; return next; });
  };

  const handleAmountChange = (envId, amt) => {
    const newAmt = Number(amt) || 0;
    const newAllocations = { ...allocations };
    const newPercentages = { ...percentages };
    if (newAmt === 0) {
      delete newAllocations[envId];
      delete newPercentages[envId];
    } else {
      if (newAmt > incomeNum) return;
      newAllocations[envId] = newAmt;
      newPercentages[envId] = incomeNum > 0 ? Math.round((newAmt / incomeNum) * 100) : 0;
    }
    setAllocations(newAllocations);
    setPercentages(newPercentages);
    setTypedAmounts(prev => {
      const next = { ...prev };
      if (newAmt === 0) delete next[envId]; else next[envId] = true;
      return next;
    });
  };

  // When the income changes, percent-based rows follow it; rupiah amounts the user typed stay put.
  useEffect(() => {
    if (incomeNum <= 0) return;
    setAllocations(prev => {
      const next = {};
      Object.keys(prev).forEach(id => {
        next[id] = typedAmounts[id] ? prev[id] : floorRupiah((incomeNum * (percentages[id] || 0)) / 100);
      });
      return next;
    });
    setPercentages(prev => {
      const next = { ...prev };
      Object.keys(typedAmounts).forEach(id => {
        if (allocations[id]) next[id] = Math.round((allocations[id] / incomeNum) * 100);
      });
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incomeNum]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (totalAllocated > incomeNum) { setError('Total alokasi melebihi income'); return; }
    setSaving(true); setError('');
    const items = Object.entries(allocations).filter(([, amt]) => Number(amt) > 0).map(([envId, amt]) => ({ envelope_id: envId, amount: Number(amt) }));
    const res = await api.request('/incomes/', { method: 'POST', body: JSON.stringify({ amount: incomeNum, source: incomeDesc, allocations: items }) });
    setSaving(false);
    if (res.ok) {
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      onClose();
    } else { const d = await res.json(); setError(d.detail || 'Gagal'); }
  };

  if (!ready) return <div className="text-center py-8 text-gray-400">Loading...</div>;
  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3 items-end">
        <div><label className="label">Jumlah (Rp)</label><input type="number" className="input font-mono" placeholder="8000000" value={incomeAmount} onChange={e => setIncomeAmount(e.target.value)} required min="1" /></div>
        <div><label className="label">Keterangan</label><input type="text" className="input" placeholder="Gaji atau Pendapatan harian" value={incomeDesc} onChange={e => setIncomeDesc(e.target.value)} required /></div>
      </div>
      {incomeNum > 0 && (
        <div className="space-y-3">
          <div className="flex gap-3 text-sm">
            <span className="text-gray-400">Income: <b className="text-gray-700">{incomeNum.toLocaleString('id-ID')}</b></span>
            <span className="text-gray-400">Dialokasi: <b className="text-amber-500">{totalAllocated.toLocaleString('id-ID')}</b></span>
            <span className="text-gray-400">{remainder >= 0 ? 'Sisa' : 'Kelebihan'}: <b className={remainder >= 0 ? 'text-brand-600' : 'text-red-500'}>{Math.abs(remainder).toLocaleString('id-ID')}</b></span>
          </div>
          {remainder < 0 && (
            <p className="text-xs text-red-500">
              Total alokasi {Math.round((totalAllocated / incomeNum) * 100)}% dari income, lebih Rp{Math.abs(remainder).toLocaleString('id-ID')}. Kurangi persen atau jumlah di salah satu amplop supaya bisa disimpan.
            </p>
          )}
          <button type="button" onClick={handleAutoAllocate} disabled={loadingAuto} className="text-xs px-3 py-2 bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100 disabled:opacity-50">
            {loadingAuto ? 'Memproses...' : 'Bagi otomatis'}
          </button>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {formEnvelopes(envelopes, sisaKe).map(env => {
              const val = allocations[env.id] || 0;
              const pct = percentages[env.id] || 0;
              return (
                <div key={env.id} className="flex items-start gap-2">
                  <span className="w-6 flex-shrink-0 flex justify-center pt-2"><EnvelopeIcon value={env.emoji} size={20} /></span>
                  <div className="flex-1 min-w-0">
                    <span className="text-sm line-clamp-2 block mb-1.5">{env.name}</span>
                    <div className="flex items-center gap-1">
                      <input type="number" className="input text-xs font-mono text-right w-12" placeholder="%" min="0" max="100"
                        value={pct || ''} onChange={e => handlePercentageChange(env.id, e.target.value)} />
                      <span className="text-xs text-gray-500 flex-shrink-0">%</span>
                      <input type="number" className="input text-xs font-mono text-right flex-1 min-w-0" placeholder="0" value={val || ''} min="0"
                        onChange={e => handleAmountChange(env.id, e.target.value)} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          {remainder > 0 && <p className="text-xs text-brand-600">💰 {remainder.toLocaleString('id-ID')} → {sisaKe?.name || 'Tabungan'}</p>}
        </div>
      )}
      {error && <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{ color: '#E24B4A' }}>{error}</div>}
      <div className="flex gap-2">
        <button type="button" onClick={onClose} className="btn-outline flex-1">Batal</button>
        <button type="submit" disabled={saving || incomeNum <= 0 || remainder < 0} className="btn-primary flex-1 disabled:opacity-50">{saving ? '...' : 'Simpan Income'}</button>
      </div>
    </form>
  );
}

// Selalu dibuka di daftar langganan; "Tambah" ada di tab sendiri dan kembali ke daftar setelah disimpan/batal.
// CTA AI Advisor: focusId + mode ('pay' | 'mark_paid') membuka satu langganan;
// prefill membuka tab Tambah terisi ("Jadikan langganan").
function CombinedLanggananModal({ onClose, focusId = null, mode = 'pay', prefill = null }) {
  const [tab, setTab] = useState(prefill ? 'add' : 'list');
  const [reloadKey, setReloadKey] = useState(0);
  const tabCls = active => `px-4 py-2 font-medium text-sm border-b-2 transition-colors ${
    active ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-500 hover:text-gray-700'
  }`;

  return (
    <div className="space-y-4">
      <div className="flex gap-2 border-b border-gray-200">
        <button onClick={() => setTab('list')} className={tabCls(tab === 'list')}>Daftar Langganan</button>
        <button onClick={() => setTab('add')} className={tabCls(tab === 'add')}>Tambah Langganan</button>
      </div>

      <div>
        {tab === 'list' && <PaySubscriptions onClose={onClose} reloadKey={reloadKey} focusId={focusId} mode={mode} />}
        {tab === 'add' && (
          <RecurringModal inline prefill={prefill}
            onClose={() => setTab('list')}
            onSaved={() => { setReloadKey(k => k + 1); window.dispatchEvent(new CustomEvent('jatahku:txn-added')); }} />
        )}
      </div>
    </div>
  );
}

// CTA "Naikkan jatah" (budget_amount, berlaku untuk alokasi berikutnya) dan
// "Pasang limit harian" (daily_limit, peringatan). Konfirmasi dulu, lalu PUT amplop.
const ENVELOPE_FIELD = {
  raise_budget: { field: 'budget_amount', title: 'Naikkan jatah', verb: 'Jatah', note: 'Berlaku untuk alokasi berikutnya; dana periode ini tidak berubah.' },
  daily_limit: { field: 'daily_limit', title: 'Pasang limit harian', verb: 'Limit harian', note: 'Kamu diberi peringatan saat belanja amplop ini lewat batas per hari.' },
};

function EnvelopeFieldConfirm({ kind, payload, onClose }) {
  const cfg = ENVELOPE_FIELD[kind];
  const envId = payload.amplop_id ?? payload.envelope_id;
  const [env, setEnv] = useState(null);
  const [value, setValue] = useState(() => {
    const n = Math.round(Number(payload.jumlah ?? payload.amount));
    return n > 0 ? String(n) : '';
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    api.getEnvelopeSummary().then(envs => {
      const found = (envs || []).find(e => e.id === envId);
      if (found) setEnv(found); else setError('Amplop tidak ditemukan.');
    });
  }, [envId]);

  const submit = async (e) => {
    e.preventDefault();
    const n = Math.round(Number(value));
    if (!n || n <= 0) { setError('Jumlah harus lebih dari 0'); return; }
    setSaving(true); setError('');
    const res = await api.updateEnvelopeFields(env, { [cfg.field]: n });
    setSaving(false);
    if (!res.ok) { setError(res.data?.detail || 'Gagal menyimpan'); return; }
    window.dispatchEvent(new CustomEvent('jatahku:envelope-updated'));
    window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
    onClose();
  };

  if (!env) return error
    ? <p className="text-sm text-red-500">{error}</p>
    : <div className="text-center py-8 text-gray-400">Loading...</div>;
  const current = Number(env[cfg.field]) || 0;
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="flex items-center gap-2">
        <EnvelopeIcon value={env.emoji} size={22} />
        <span className="font-medium">{env.name}</span>
      </div>
      <div className="text-sm text-gray-500">{cfg.verb} sekarang: <b className="font-mono text-gray-700">{current ? formatCurrency(current) : '—'}</b></div>
      <div>
        <label className="label">{cfg.verb} baru (Rp)</label>
        <input type="number" className="input font-mono" value={value} onChange={e => setValue(e.target.value)} min="1" required />
        <p className="text-xs text-gray-400 mt-1">{cfg.note}</p>
      </div>
      {error && <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{ color: '#E24B4A' }}>{error}</div>}
      <div className="flex gap-2">
        <button type="button" onClick={onClose} className="btn-outline flex-1">Batal</button>
        <button type="submit" disabled={saving} className="btn-primary flex-1 disabled:opacity-50">{saving ? '...' : 'Simpan'}</button>
      </div>
    </form>
  );
}

const FAB_OPTIONS = [
  { key: 'expense', icon: 'expense', label: 'Pengeluaran' },
  { key: 'envelope', icon: 'envelope', label: 'Amplop' },
  { key: 'income', icon: 'income', label: 'Income' },
  { key: 'langganan', icon: 'langganan', label: 'Langganan' },
  { key: 'balance', icon: 'balance', label: 'Cocokkan saldo' },
];

const navItems = [
  { to: '/', label: 'Beranda', icon: 'dashboard' },
  { to: '/envelopes', label: 'Amplop', icon: 'envelope' },
  { to: '/transactions', label: 'Transaksi', icon: 'transaksi' },
  { to: '/allocate', label: 'Alokasi', icon: 'alokasi' },
  { to: '/langganan', label: 'Langganan', icon: 'langganan' },
];

// Menu kiri (lg+): bottom nav HP sudah penuh 5 item, Analitik hanya di sidebar.
// Ikon garis sesuai desain sidebar.
const SIDEBAR_ICONS = { '/': 'grid', '/transactions': 'listbullets', '/allocate': 'transfer' };
const sidebarItems = [
  ...navItems.map(item => ({ ...item, icon: SIDEBAR_ICONS[item.to] || item.icon })),
  { to: '/analytics', label: 'Analitik', icon: 'chartpie' },
];

// Aksi lain di samping tombol "Catat" (top bar desktop); di HP lewat FAB.
const MORE_ACTIONS = FAB_OPTIONS.filter(o => o.key !== 'expense');

const TOPBAR_HEIGHT = 88;

const todayLabel = () => new Date().toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long' });

export default function Layout() {
  const { user, loading, logout } = useAuth();
  const { mode, toggleMode } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const [fabMenu, setFabMenu] = useState(false);
  const [fabAction, setFabAction] = useState(null);
  const [actionPayload, setActionPayload] = useState(null); // isian awal modal dari CTA AI Advisor
  const [actionSeq, setActionSeq] = useState(0);             // CTA baru → isi modal dipasang ulang
  const [planAction, setPlanAction] = useState(null);       // { kebutuhan, title } → PlanSheet
  const [fundAction, setFundAction] = useState(null);       // { target, amount, envelopes } → FundEnvelopeModal
  const [chatDraftState, setChatDraftState] = useState(null);
  const [notice, setNotice] = useState(null);
  // Chat bot: dipasang sekali saat pertama dibuka, lalu hanya disembunyikan,
  // supaya balasan yang sedang ditunggu tidak hilang saat panel ditutup.
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMounted, setChatMounted] = useState(false);
  // Layar lebar: isi sidebar (badge Langganan, Papan disiplin) dan slot top bar untuk halaman.
  const [langgananBadge, setLanggananBadge] = useState(0);
  const [leaderboard, setLeaderboard] = useState([]);
  const [topbarSlot, setTopbarSlot] = useState(null);
  const [catatMenu, setCatatMenu] = useState(false);
  const menuRef = useRef(null);
  const fabRef = useRef(null);
  const catatRef = useRef(null);
  const navigate = useNavigate();
  const location = useLocation();
  const appConfig = useAppConfigLoader();

  const openChat = () => { setFabMenu(false); setChatMounted(true); setChatOpen(true); };
  const closeChat = useCallback(() => setChatOpen(false), []);

  useEffect(() => {
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
      if (catatRef.current && !catatRef.current.contains(e.target)) setCatatMenu(false);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // Toast kecil; `action` = {label, run} menambah tombol (mis. Urungkan, #91) dan waktu tampil lebih lama.
  const showNotice = useCallback((text, action = null) => {
    const n = { text, action };
    setNotice(n);
    setTimeout(() => setNotice(cur => (cur === n ? null : cur)), action ? 6000 : 3500);
  }, []);

  // "Foto struk": buka kamera, lalu form Catat terbuka dan langsung membaca fotonya.
  // Di sini (bukan di openAction, yang dideklarasikan setelah early return) supaya bisa dipakai
  // efek pemulihan di bawah. Dipanggil dari ketukan (FAB, menu Catat, tombol toast): kamera
  // harus dibuka sinkron di dalam handler itu (iPhone Safari), jadi tidak ada await sebelum pickReceiptPhoto.
  const openReceiptCamera = useCallback(() => {
    setFabMenu(false);
    setCatatMenu(false);
    pickReceiptPhoto('camera', {
      onFile: (photo) => { setActionPayload({ photo }); setActionSeq(n => n + 1); setFabAction('expense'); },
      onError: showNotice,
    });
  }, [showNotice]);

  // Pintu masuk lain membuka aksi lewat event `jatahku:open-action`:
  // string lama ('expense', 'income', 'chat', …) atau CTA AI Advisor {kind, payload}
  // (docs/ai-advisor/04-kontrak-api.md). Lihat lib/advisorAction.js.
  useEffect(() => {
    const openModal = (key, payload = null) => { setActionPayload(payload); setActionSeq(n => n + 1); setFabAction(key); };
    // Munculkan lagi insight yang disembunyikan (§9, #91): Urungkan di toast atau daftar di kartu.
    const undismiss = async (kunci) => {
      const res = await api.advisorUndismiss(kunci);
      if (!res.ok) { showNotice('Gagal memunculkan lagi'); return; }
      window.dispatchEvent(new CustomEvent('jatahku:advisor-undismissed', { detail: { kunci } }));
      showNotice('Ditampilkan lagi');
    };
    const onOpen = async (e) => {
      const action = normalizeAction(e.detail);
      if (!action) return;
      const { kind, payload, label } = action;
      setFabMenu(false);
      setCatatMenu(false);
      switch (kind) {
        case 'chat': {
          const d = chatDraft(payload);
          if (d.text || d.chips.length) setChatDraftState({ ...d, nonce: Date.now() });
          setChatMounted(true);
          setChatOpen(true);
          return;
        }
        case 'income':
          openModal('income', Object.keys(payload).length ? incomePrefill(payload) : null);
          return;
        case 'pay':
        case 'mark_paid':
          openModal('langganan', payload.recurring_id ? { focusId: payload.recurring_id, mode: kind } : null);
          return;
        case 'make_recurring':
          openModal('langganan', { prefill: recurringPrefill(payload) });
          return;
        case 'raise_budget':
        case 'daily_limit':
          if (payload.amplop_id ?? payload.envelope_id) openModal(kind, payload);
          return;
        case 'plan':
          if (Array.isArray(payload.kebutuhan) && payload.kebutuhan.length) {
            setPlanAction({ kebutuhan: payload.kebutuhan, title: label || 'Rencana dana' });
          }
          return;
        case 'fund': {
          const envId = payload.amplop_id ?? payload.envelope_id ?? payload.tujuan_id;
          const envs = await api.getEnvelopeSummary();
          const target = (envs || []).find(x => x.id === envId);
          if (!target) { showNotice('Amplop tidak ditemukan'); return; }
          setFundAction({ target, envelopes: envs, amount: Math.max(0, Math.round(Number(payload.jumlah ?? payload.amount) || 0)) });
          return;
        }
        case 'route': {
          const path = safeRoute(payload.path ?? payload.url);
          if (path) navigate(path);
          return;
        }
        case 'dismiss':
        case 'not_duplicate': {
          if (!payload.kunci) return;
          // not_duplicate membawa pilihan bukan_dobel / bukan_tagihan dari server (#93); tidak_relevan
          // hanya cadangan untuk payload lama yang belum membawanya.
          const pilihan = payload.pilihan || (kind === 'not_duplicate' ? 'tidak_relevan' : 'nanti');
          const res = await api.advisorDismiss(payload.kunci, pilihan);
          if (!res.ok) { showNotice(res.status === 404 ? 'Belum tersedia, coba lagi nanti' : 'Gagal menyimpan'); return; }
          window.dispatchEvent(new CustomEvent('jatahku:advisor-dismissed', { detail: { kunci: payload.kunci, pilihan } }));
          showNotice(dismissNotice(kind, pilihan), { label: 'Urungkan', run: () => undismiss(payload.kunci) });
          return;
        }
        case 'undismiss':
          if (payload.kunci) await undismiss(payload.kunci);
          return;
        case 'delete_txn': {
          // txn_ids: struk terkirim dua kali (DAT-03 S4b) → hapus seluruh rantai kedua sekaligus.
          const ids = Array.isArray(payload.txn_ids) && payload.txn_ids.length
            ? payload.txn_ids : [payload.txn_id ?? payload.transaction_id].filter(Boolean);
          const tanya = ids.length > 1 ? `Hapus ${ids.length} transaksi duplikat?` : 'Hapus transaksi ini?';
          if (!ids.length || !window.confirm(payload.konfirmasi || tanya)) return;
          let gagal = 0;
          for (const id of ids) {
            if (!(await api.deleteTransaction(id))) gagal += 1;
          }
          if (gagal < ids.length) window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
          if (gagal) { showNotice(gagal === ids.length ? 'Gagal menghapus transaksi' : `${gagal} transaksi gagal dihapus`); return; }
          showNotice(ids.length > 1 ? `${ids.length} transaksi dihapus` : 'Transaksi dihapus');
          return;
        }
        default:
          openModal(kind); // expense, envelope, langganan, balance
      }
    };
    window.addEventListener('jatahku:open-action', onOpen);
    return () => window.removeEventListener('jatahku:open-action', onOpen);
  }, [navigate, showNotice]);

  // Badge Langganan (telat + belum bayar periode ini) dan Papan disiplin untuk sidebar.
  useEffect(() => {
    if (!user) return undefined;
    const load = () => {
      api.getRecurring().then(items => setLanggananBadge(
        (items || []).filter(i => i.is_active !== false && (i.status === 'overdue' || i.status === 'due')).length,
      ));
      api.request('/household/leaderboard')
        .then(r => (r.ok ? r.json() : []))
        .then(d => setLeaderboard(Array.isArray(d) ? d : []))
        .catch(() => {});
    };
    load();
    window.addEventListener('jatahku:txn-added', load);
    return () => window.removeEventListener('jatahku:txn-added', load);
  }, [user]);

  // Pintasan PWA / tautan: ?chat=1 membuka chat bot.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('chat') !== '1') return;
    setChatMounted(true);
    setChatOpen(true);
    params.delete('chat');
    const search = params.toString();
    navigate({ pathname: location.pathname, search: search ? `?${search}` : '' }, { replace: true });
  }, [location.search, location.pathname, navigate]);

  // Shortcut PWA "Foto struk" (?struk=1): form Catat terbuka dalam mode siap difoto
  // (tombol besar "Ambil foto struk"). Kamera tidak bisa dibuka dari sini — butuh ketukan.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('struk') !== '1') return;
    setActionPayload({ photoMode: 'ready' });
    setActionSeq(n => n + 1);
    setFabAction('expense');
    params.delete('struk');
    const search = params.toString();
    navigate({ pathname: location.pathname, search: search ? `?${search}` : '' }, { replace: true });
  }, [location.search, location.pathname, navigate]);

  // Pemulihan: OS mematikan app saat kamera terbuka → sekali setelah user tersedia (bukan saat layar
  // loading, supaya toast tidak habis waktunya sebelum terlihat) cek fotonya sempat sampai atau tidak.
  // Tanpa pembersih efek: StrictMode (dev) menjalankan efek dua kali, dan recover() menghapus penanda
  // sekali baca; hasil panggilan pertama tetap harus dipakai.
  const recoverChecked = useRef(false);
  useEffect(() => {
    if (!user || recoverChecked.current) return;
    recoverChecked.current = true;
    native.camera.recover().then(({ file, lost }) => {
      if (file) {
        setActionPayload({ photo: file });
        setActionSeq(n => n + 1);
        setFabAction('expense');
      } else if (lost) {
        showNotice('Foto struk tadi tidak sempat diterima, coba lagi.', { label: 'Foto ulang', run: openReceiptCamera });
      }
    }).catch(() => {});
  }, [user, showNotice, openReceiptCamera]);

  if (isUpdateRequired(appConfig)) return <UpdateRequired config={appConfig} />;
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-brand-600 font-display text-xl font-bold animate-pulse">Jatahku</div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" />;

  const initial = user.name ? user.name.charAt(0).toUpperCase() : '?';
  const firstName = (user.name || '').trim().split(/\s+/)[0] || 'kamu';
  const openAction = (key) => {
    setCatatMenu(false); setFabMenu(false); setActionPayload(null); setFabAction(key);
  };
  const closeAction = () => { setFabAction(null); setActionPayload(null); };
  const squareBtn = 'w-[var(--nav-h)] h-[var(--nav-h)] shrink-0 rounded-xl inline-flex items-center justify-center transition-colors';
  const squareStyle = { background: 'var(--card-bg)', border: '1px solid var(--border)', color: 'var(--text-muted)' };

  return (
    <AppConfigProvider value={appConfig}>
    <div className="min-h-screen bg-page">
      <Sidebar items={sidebarItems} langgananBadge={langgananBadge} leaderboard={leaderboard}
        isAdmin={!!user?.is_admin} mode={mode} onToggleMode={toggleMode} />

      <div className="lg:pl-[var(--sidebar-w)]" style={{ '--sidebar-w': `${SIDEBAR_WIDTH}px` }}>
      {/* Top bar layar lebar: sapaan + slot halaman (mis. periode & Laporan di Beranda) + chat, notifikasi, Catat.
          Tanpa backdrop-filter: modal laporan yang dirender di slot ini memakai position: fixed. */}
      <div className="hidden lg:flex sticky top-0 z-40 items-center justify-between gap-6 px-8"
        style={{ height: TOPBAR_HEIGHT, background: 'var(--page)', borderBottom: '1px solid var(--border)' }}>
        <div className="min-w-0 flex-1">
          <p className="text-[26px] font-bold leading-tight truncate" style={{ color: 'var(--text)' }}>Halo, {firstName}</p>
          <p className="text-[15px] mt-0.5 truncate" style={{ color: 'var(--text-muted)' }}>{todayLabel()}</p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <div ref={setTopbarSlot} className="flex items-center gap-3" />
          <button type="button" onClick={openChat} className={squareBtn}
            style={chatOpen ? { ...squareStyle, color: 'var(--brand-600)' } : squareStyle}
            title="Chat bot" aria-label="Buka chat bot">
            <Icon name="chat" size={21} weight="regular" />
          </button>
          <div className={`${squareBtn} [&>div>button]:p-2`} style={squareStyle}>
            <NotificationBell />
          </div>
          <div className="relative flex" ref={catatRef}>
            <button type="button" onClick={() => openAction('expense')}
              className="h-[var(--nav-h)] px-4 rounded-l-xl inline-flex items-center gap-2 text-[15px] font-bold transition-opacity hover:opacity-90"
              style={{ background: 'var(--brand-400)', color: '#0f172a' }}>
              <Icon name="plus" size={18} weight="bold" /> Catat
            </button>
            <button type="button" onClick={() => setCatatMenu(m => !m)} aria-expanded={catatMenu} aria-haspopup="menu"
              aria-label="Catat lainnya: pemasukan, amplop, langganan, cocokkan saldo"
              className="h-[var(--nav-h)] w-10 rounded-r-xl inline-flex items-center justify-center transition-opacity hover:opacity-90"
              style={{ background: 'var(--brand-400)', color: '#0f172a', borderLeft: '1px solid rgba(15,23,42,0.18)' }}>
              <Icon name="chevron" size={14} weight="bold" />
            </button>
            {catatMenu && (
              <div role="menu" className="absolute right-0 top-[calc(var(--nav-h)+8px)] w-60 rounded-xl py-2 shadow-lg z-50"
                style={{ background: 'var(--card-bg)', border: '1px solid var(--border)' }}>
                {MORE_ACTIONS.map(opt => (
                  <button key={opt.key} type="button" role="menuitem" onClick={() => openAction(opt.key)}
                    className="w-full text-left px-4 py-2.5 text-sm flex items-center gap-3 hover:bg-black/5"
                    style={{ color: 'var(--text)' }}>
                    <Icon name={opt.icon} size={18} /> {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <header className="lg:hidden bg-white/80 backdrop-blur-md border-b border-gray-100 sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <NavLink to="/" className="font-display text-xl font-bold text-brand-600">
              Jatah<span className="text-brand-400">ku</span>
            </NavLink>
          </div>

          {/* Notifications + Profile */}
          <div className="flex items-center gap-1">
          <button
            onClick={openChat}
            className={`w-8 h-8 flex items-center justify-center rounded-lg transition-colors ${chatOpen ? 'bg-brand-50 text-brand-600' : 'text-gray-500 hover:bg-gray-100'}`}
            title="Chat bot"
            aria-label="Buka chat bot"
          >
            <Icon name="chat" size={19} />
          </button>
          <NotificationBell />
          <button
            onClick={toggleMode}
            className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 transition-colors text-gray-500"
            title={mode === 'light' ? 'Mode Gelap' : 'Mode Terang'}
          >
            <Icon name={mode === 'light' ? 'moon' : 'sun'} size={18} />
          </button>
          <div className="relative" ref={menuRef}>
            <button onClick={() => setMenuOpen(!menuOpen)}
              className="flex items-center gap-2 px-2 py-1 rounded-lg hover:bg-gray-50 transition-colors">
              <div className="w-8 h-8 rounded-full bg-brand-50 flex items-center justify-center text-sm font-bold text-brand-600">
                {initial}
              </div>
              <span className="text-sm text-gray-600 hidden sm:block">{user.name}</span>
              <Icon name="chevron" size={14} weight="bold" className="text-gray-400" />
            </button>

            {menuOpen && (
              <div className="absolute right-0 top-12 w-56 bg-white rounded-xl shadow-lg border border-gray-100 py-2 z-50">
                <div className="px-4 py-2 border-b border-gray-50">
                  <p className="text-sm font-semibold">{user.name}</p>
                  <p className="text-xs text-gray-400">{user.email}</p>
                </div>
                {user?.is_admin && (
                  <button onClick={() => { navigate('/admin'); setMenuOpen(false); }}
                    className="w-full text-left px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-3">
                    <Icon name="admin" size={18} /> Admin
                  </button>
                )}
                <button onClick={() => { navigate('/settings'); setMenuOpen(false); }}
                  className="w-full text-left px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-3">
                  <Icon name="settings" size={18} /> Profil & Settings
                </button>

                <div className="border-t border-gray-50 mt-1 pt-1">
                  <button onClick={() => { logout(); setMenuOpen(false); }}
                    className="w-full text-left px-4 py-2.5 text-sm text-red-500 hover:bg-red-50 flex items-center gap-3">
                    <Icon name="logout" size={18} color="currentColor" /> Logout
                  </button>
                </div>
              </div>
            )}
          </div>
          </div>
        </div>
      </header>

      {/* Bottom nav HP & tablet — 5 item; layar lebar memakai sidebar */}
      <nav className="lg:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-gray-100 z-50">
        <div className="flex justify-around py-2">
          {navItems.map(item => (
            <NavLink key={item.to} to={item.to} end={item.to === '/'}
              className={({ isActive }) =>
                `flex flex-col items-center gap-0.5 px-2 py-1 text-xs font-medium transition-colors ${
                  isActive ? 'text-brand-600' : 'text-gray-400'
                }`}>
              <Icon name={item.icon} size={22} />{item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <TelegramPrompt />
      <OfflineQueueCenter />
      <PendingProofsBanner />
      <main className="max-w-6xl lg:max-w-[1520px] mx-auto lg:mx-0 px-4 lg:px-8 py-6 lg:py-8 pb-24 lg:pb-10"><Outlet context={{ topbarSlot }} /></main>
      </div>
      {/* Global FAB — speed dial */}
      {fabMenu && (
        <div className="fixed inset-0 z-50" onClick={() => setFabMenu(false)} />
      )}
      <div className="lg:hidden fixed bottom-24 inset-x-0 pointer-events-none z-50">
        <div className="max-w-6xl mx-auto px-4 flex justify-end items-center gap-3">
          {/* Mobile: chat sekali ketuk, di jangkauan jempol di samping FAB */}
          {!fabMenu && (
            <button
              onClick={openChat}
              className="md:hidden pointer-events-auto w-12 h-12 rounded-2xl bg-white border border-brand-200 text-brand-600 shadow-lg flex items-center justify-center transition-all active:scale-95"
              title="Chat bot"
              aria-label="Buka chat bot"
            >
              <Icon name="chat" size={24} weight="fill" />
            </button>
          )}
          <div className="pointer-events-auto relative">
            {fabMenu && (
              <div className="absolute bottom-16 right-0 flex flex-col-reverse items-end gap-3 pb-2">
                {FAB_OPTIONS.map((opt, i) => (
                  <button
                    key={opt.key}
                    onClick={() => openAction(opt.key)}
                    className="flex items-center gap-2 px-3.5 py-2 rounded-full bg-white border border-gray-200 shadow-lg text-sm font-medium text-gray-600 hover:border-brand-400 hover:text-brand-600 transition-all whitespace-nowrap"
                    style={{ animation: `fadeIn 0.15s ease-out ${i * 0.05}s both` }}
                  >
                    <Icon name={opt.icon} size={20} />
                    <span>{opt.label}</span>
                  </button>
                ))}
              </div>
            )}
            <button
              onClick={() => setFabMenu(m => !m)}
              className={`w-14 h-14 rounded-2xl text-white flex items-center justify-center transition-all active:scale-95 ${!fabMenu ? 'hover:scale-105' : ''}`}
              style={{ background: 'linear-gradient(145deg,#1D9E75,#0F6E56)', boxShadow: '0 10px 24px -8px rgba(15,110,86,0.6)' }}
              title={fabMenu ? 'Tutup menu' : 'Menu cepat'}
              aria-label={fabMenu ? 'Tutup menu' : 'Menu cepat'}
            >
              <Icon name={fabMenu ? 'close' : 'plus'} size={26} weight="bold" />
            </button>
          </div>
        </div>
      </div>
      {chatMounted && <ChatPanel open={chatOpen} onClose={closeChat} draft={chatDraftState} />}
      {planAction && (
        <PlanSheet kebutuhan={planAction.kebutuhan} title={planAction.title} onClose={() => setPlanAction(null)}
          onIncome={amt => { setPlanAction(null); setActionPayload(incomePrefill({ jumlah: amt })); setActionSeq(n => n + 1); setFabAction('income'); }} />
      )}
      {fundAction && (
        <FundEnvelopeModal isOpen advisor targetEnvelope={fundAction.target} neededAmount={fundAction.amount}
          envelopes={fundAction.envelopes} onClose={() => setFundAction(null)} />
      )}
      {notice && (
        <div role="status" className="fixed bottom-24 lg:bottom-8 left-1/2 -translate-x-1/2 z-[70] rounded-xl px-4 py-2 bg-gray-900 text-white text-sm shadow-lg flex items-center gap-4">
          <span>{notice.text}</span>
          {notice.action && (
            <button type="button" className="font-semibold text-white underline underline-offset-2"
              onClick={() => { const { run } = notice.action; setNotice(null); run(); }}>
              {notice.action.label}
            </button>
          )}
        </div>
      )}
      {/* Modals for speed dial actions */}
      {fabAction && (
        <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={closeAction}>
          <div key={actionSeq} className="bg-white rounded-2xl w-full max-w-2xl p-6 shadow-xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h3 className="font-display font-bold text-lg mb-4 flex items-center gap-2">
              {fabAction === 'expense' && <><Icon name="expense" size={22} /> Catat pengeluaran</>}
              {fabAction === 'envelope' && <><Icon name="envelope" size={22} /> Amplop baru</>}
              {fabAction === 'income' && <><Icon name="income" size={22} /> Income baru</>}
              {fabAction === 'langganan' && <><Icon name="langganan" size={22} /> Langganan</>}
              {fabAction === 'balance' && <><Icon name="balance" size={22} /> Cocokkan saldo</>}
              {ENVELOPE_FIELD[fabAction] && <><Icon name="envelope" size={22} /> {ENVELOPE_FIELD[fabAction].title}</>}
            </h3>
            {fabAction === 'expense' && (
              <MultiAddTransaction onSaved={closeAction} onCancel={closeAction}
                initialPhoto={actionPayload?.photo} photoMode={actionPayload?.photoMode} />
            )}
            {fabAction === 'envelope' && <QuickAddEnvelope onClose={closeAction} />}
            {fabAction === 'income' && <QuickAddIncome onClose={closeAction} prefill={actionPayload} />}
            {fabAction === 'langganan' && (
              <CombinedLanggananModal onClose={closeAction} focusId={actionPayload?.focusId} mode={actionPayload?.mode}
                prefill={actionPayload?.prefill} />
            )}
            {fabAction === 'balance' && <BalanceCheck onClose={closeAction} />}
            {ENVELOPE_FIELD[fabAction] && <EnvelopeFieldConfirm kind={fabAction} payload={actionPayload || {}} onClose={closeAction} />}
          </div>
        </div>
      )}
    </div>
    </AppConfigProvider>
  );
}
