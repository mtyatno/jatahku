import { useState, useEffect, useRef, useCallback } from 'react';
import { NavLink, Outlet, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import NotificationBell from './NotificationBell';
import TelegramPrompt from './TelegramPrompt';
import OfflineQueueCenter from './OfflineQueueCenter';
import MultiAddTransaction from './MultiAddTransaction';
import PaySubscriptions from './PaySubscriptions';
import BalanceCheck from './BalanceCheck';
import ChatPanel from './ChatPanel';
import Sidebar, { SIDEBAR_WIDTH } from './Sidebar';
import { CreateModal } from '../pages/Envelopes';
import { RecurringModal } from '../pages/Langganan';
import { api } from '../lib/api';
import { Icon, EnvelopeIcon } from './Icon';

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

// Smallest rupiah denomination in use is Rp100, so allocations snap to it; the leftover goes to Tabungan.
const RUPIAH_STEP = 100;
const floorRupiah = v => Math.floor(v / RUPIAH_STEP) * RUPIAH_STEP;

function QuickAddIncome({ onClose }) {
  const [envelopes, setEnvelopes] = useState([]);
  const [incomeAmount, setIncomeAmount] = useState('');
  const [incomeDesc, setIncomeDesc] = useState('Gaji');
  const [allocations, setAllocations] = useState({});
  const [percentages, setPercentages] = useState({});
  const [typedAmounts, setTypedAmounts] = useState({});
  const [saving, setSaving] = useState(false);
  const [loadingAuto, setLoadingAuto] = useState(false);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  useEffect(() => { api.getEnvelopeSummary().then(e => { setEnvelopes(e); setReady(true); }); }, []);

  const incomeNum = Number(incomeAmount) || 0;
  const totalAllocated = Object.values(allocations).reduce((s, v) => s + (Number(v) || 0), 0);
  const remainder = incomeNum - totalAllocated;

  const handleAutoAllocate = async () => {
    if (incomeNum <= 0) { setError('Masukkan jumlah income terlebih dahulu'); return; }
    setLoadingAuto(true);
    setError('');
    try {
      const res = await api.request('/advisor/allocation-recommendation', { method: 'POST', body: JSON.stringify({ income_amount: incomeNum }) });
      setLoadingAuto(false);
      if (!res.ok) { setError('Gagal mendapatkan saran alokasi'); return; }
      const data = await res.json();
      const isSink = it => it.purpose === 'saving' || (it.name || '').toLowerCase() === 'tabungan';
      const fundable = new Set(envelopes.filter(e => e.name !== 'Tabungan' && !e.is_locked).map(e => String(e.id)));
      const needs = (data.items || [])
        .filter(it => !isSink(it) && fundable.has(String(it.envelope_id)))
        .map(it => ({ id: it.envelope_id, need: Math.max(Number(it.target_amount) || 0, Number(it.minimum_amount) || 0) }))
        .filter(it => it.need > 0);
      const totalNeed = needs.reduce((s, it) => s + it.need, 0);
      if (totalNeed <= 0) { setError('Belum ada target atau riwayat belanja amplop untuk dijadikan acuan. Isi manual dulu, ya.'); return; }
      // Split in proportion to each envelope's monthly need, so a small or daily income is shared instead of filling one envelope first.
      const scale = Math.min(1, incomeNum / totalNeed);
      const newAllocations = {}, newPercentages = {};
      needs.forEach(({ id, need }) => {
        const amt = floorRupiah(need * scale);
        if (amt > 0) {
          newAllocations[id] = amt;
          newPercentages[id] = Math.round((amt / incomeNum) * 100);
        }
      });
      setAllocations(newAllocations);
      setPercentages(newPercentages);
      setTypedAmounts({});
    } catch (err) {
      setLoadingAuto(false);
      setError('Gagal mendapatkan saran alokasi');
    }
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
    if (res.ok) { onClose(); } else { const d = await res.json(); setError(d.detail || 'Gagal'); }
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
            {envelopes.filter(e => e.name !== 'Tabungan').map(env => {
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
          {remainder > 0 && <p className="text-xs text-brand-600">💰 {remainder.toLocaleString('id-ID')} → Tabungan</p>}
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

function CombinedLanggananModal({ onClose }) {
  const [tab, setTab] = useState('add');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getRecurring().then(d => {
      setItems(d || []);
      const unpaid = d?.some(i => i.status !== 'paid');
      if (unpaid) setTab('pay');
      setLoading(false);
    });
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex gap-2 border-b border-gray-200">
        <button
          onClick={() => setTab('add')}
          className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors ${
            tab === 'add'
              ? 'border-brand-600 text-brand-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Tambah Langganan
        </button>
        <button
          onClick={() => setTab('pay')}
          className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors ${
            tab === 'pay'
              ? 'border-brand-600 text-brand-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Bayar Langganan
        </button>
      </div>

      <div>
        {tab === 'add' && <RecurringModal onClose={onClose} onSaved={() => { api.getRecurring().then(d => setItems(d || [])); }} />}
        {tab === 'pay' && loading ? (
          <div className="text-center py-8 text-gray-400">Loading...</div>
        ) : (
          <PaySubscriptions onClose={onClose} />
        )}
      </div>
    </div>
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

  // Pintu masuk lain (mis. link di Dashboard) membuka modal aksi FAB lewat event.
  useEffect(() => {
    const onOpen = (e) => {
      setFabMenu(false);
      if (e.detail === 'chat') { setChatMounted(true); setChatOpen(true); } else setFabAction(e.detail);
    };
    window.addEventListener('jatahku:open-action', onOpen);
    return () => window.removeEventListener('jatahku:open-action', onOpen);
  }, []);

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
  const openAction = (key) => { setCatatMenu(false); setFabMenu(false); setFabAction(key); };
  const squareBtn = 'w-12 h-12 shrink-0 rounded-xl inline-flex items-center justify-center transition-colors';
  const squareStyle = { background: 'var(--card-bg)', border: '1px solid var(--border)', color: 'var(--text-muted)' };

  return (
    <div className="min-h-screen bg-page">
      <Sidebar items={sidebarItems} langgananBadge={langgananBadge} leaderboard={leaderboard}
        isAdmin={!!user?.is_admin} mode={mode} onToggleMode={toggleMode} />

      <div className="lg:pl-[var(--sidebar-w)]" style={{ '--sidebar-w': `${SIDEBAR_WIDTH}px` }}>
      {/* Top bar layar lebar: sapaan + slot halaman (mis. periode & Laporan di Beranda) + chat, notifikasi, Catat.
          Tanpa backdrop-filter: modal laporan yang dirender di slot ini memakai position: fixed. */}
      <div className="hidden lg:flex sticky top-0 z-40 items-center justify-between gap-6 px-8"
        style={{ height: TOPBAR_HEIGHT, background: 'var(--page)', borderBottom: '1px solid var(--border)' }}>
        <div className="min-w-0">
          <p className="text-[26px] font-bold leading-tight truncate" style={{ color: 'var(--text)' }}>Halo, {firstName}</p>
          <p className="text-[15px] mt-0.5" style={{ color: 'var(--text-muted)' }}>{todayLabel()}</p>
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
              className="h-12 pl-4 pr-4 rounded-l-xl inline-flex items-center gap-2 text-[15px] font-bold transition-opacity hover:opacity-90"
              style={{ background: 'var(--brand-400)', color: '#0f172a' }}>
              <Icon name="plus" size={18} weight="bold" /> Catat
            </button>
            <button type="button" onClick={() => setCatatMenu(m => !m)} aria-expanded={catatMenu} aria-haspopup="menu"
              aria-label="Catat lainnya: pemasukan, amplop, langganan, cocokkan saldo"
              className="h-12 w-10 rounded-r-xl inline-flex items-center justify-center transition-opacity hover:opacity-90"
              style={{ background: 'var(--brand-400)', color: '#0f172a', borderLeft: '1px solid rgba(15,23,42,0.18)' }}>
              <Icon name="chevron" size={14} weight="bold" />
            </button>
            {catatMenu && (
              <div role="menu" className="absolute right-0 top-14 w-60 rounded-xl py-2 shadow-lg z-50"
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
                    onClick={() => {
                      setFabMenu(false);
                      setFabAction(opt.key);
                    }}
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
      {chatMounted && <ChatPanel open={chatOpen} onClose={closeChat} />}
      {/* Modals for speed dial actions */}
      {fabAction && (
        <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={() => setFabAction(null)}>
          <div className="bg-white rounded-2xl w-full max-w-2xl p-6 shadow-xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h3 className="font-display font-bold text-lg mb-4 flex items-center gap-2">
              {fabAction === 'expense' && <><Icon name="expense" size={22} /> Catat pengeluaran</>}
              {fabAction === 'envelope' && <><Icon name="envelope" size={22} /> Amplop baru</>}
              {fabAction === 'income' && <><Icon name="income" size={22} /> Income baru</>}
              {fabAction === 'langganan' && <><Icon name="langganan" size={22} /> Langganan</>}
              {fabAction === 'balance' && <><Icon name="balance" size={22} /> Cocokkan saldo</>}
            </h3>
            {fabAction === 'expense' && <MultiAddTransaction onSaved={() => setFabAction(null)} onCancel={() => setFabAction(null)} />}
            {fabAction === 'envelope' && <QuickAddEnvelope onClose={() => setFabAction(null)} />}
            {fabAction === 'income' && <QuickAddIncome onClose={() => setFabAction(null)} />}
            {fabAction === 'langganan' && <CombinedLanggananModal onClose={() => setFabAction(null)} />}
            {fabAction === 'balance' && <BalanceCheck onClose={() => setFabAction(null)} />}
          </div>
        </div>
      )}
    </div>
  );
}
