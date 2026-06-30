import { useState, useEffect, useRef } from 'react';
import { NavLink, Outlet, Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import NotificationBell from './NotificationBell';
import TelegramPrompt from './TelegramPrompt';
import MultiAddTransaction from './MultiAddTransaction';
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

function QuickAddIncome({ onClose }) {
  const [envelopes, setEnvelopes] = useState([]);
  const [incomeAmount, setIncomeAmount] = useState('');
  const [incomeDesc, setIncomeDesc] = useState('Gaji');
  const [allocations, setAllocations] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  useEffect(() => { api.getEnvelopeSummary().then(e => { setEnvelopes(e); setReady(true); }); }, []);

  const incomeNum = Number(incomeAmount) || 0;
  const totalAllocated = Object.values(allocations).reduce((s, v) => s + (Number(v) || 0), 0);
  const remainder = incomeNum - totalAllocated;

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
      <div className="grid grid-cols-2 gap-3">
        <div><label className="label">Jumlah income (Rp)</label><input type="number" className="input font-mono" placeholder="8000000" value={incomeAmount} onChange={e => setIncomeAmount(e.target.value)} required min="1" /></div>
        <div><label className="label">Keterangan</label><input type="text" className="input" placeholder="Gaji, Freelance..." value={incomeDesc} onChange={e => setIncomeDesc(e.target.value)} required /></div>
      </div>
      {incomeNum > 0 && (
        <div className="space-y-3">
          <div className="flex gap-3 text-sm">
            <span className="text-gray-400">Income: <b className="text-gray-700">{incomeNum.toLocaleString('id-ID')}</b></span>
            <span className="text-gray-400">Dialokasi: <b className="text-amber-500">{totalAllocated.toLocaleString('id-ID')}</b></span>
            <span className="text-gray-400">Sisa: <b className={remainder >= 0 ? 'text-brand-600' : 'text-red-500'}>{remainder.toLocaleString('id-ID')}</b></span>
          </div>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {envelopes.filter(e => e.name !== 'Tabungan').map(env => {
              const val = allocations[env.id] || 0;
              return (
                <div key={env.id} className="flex items-center gap-2"><span className="w-6 flex justify-center"><EnvelopeIcon value={env.emoji} size={20} /></span><span className="text-sm flex-1">{env.name}</span>
                  <input type="number" className="input text-sm font-mono text-right w-28" placeholder="0" value={val || ''} min="0"
                    onChange={e => setAllocations(prev => ({ ...prev, [env.id]: Number(e.target.value) || 0 }))} />
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

function QuickAddLangganan({ onClose }) {
  return <RecurringModal onClose={onClose} onSaved={onClose} />;
}

const FAB_OPTIONS = [
  { key: 'expense', icon: 'expense', label: 'Pengeluaran' },
  { key: 'envelope', icon: 'envelope', label: 'Amplop' },
  { key: 'income', icon: 'income', label: 'Income' },
  { key: 'langganan', icon: 'langganan', label: 'Langganan' },
];

const navItems = [
  { to: '/', label: 'Dashboard', icon: 'dashboard' },
  { to: '/envelopes', label: 'Amplop', icon: 'envelope' },
  { to: '/transactions', label: 'Transaksi', icon: 'transaksi' },
  { to: '/allocate', label: 'Alokasi', icon: 'alokasi' },
  { to: '/langganan', label: 'Langganan', icon: 'langganan' },
];

const menuItems = [
  { to: '/settings', label: 'Settings', icon: 'settings' },
];

export default function Layout() {
  const { user, loading, logout } = useAuth();
  const { mode, toggleMode } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const [fabMenu, setFabMenu] = useState(false);
  const [fabAction, setFabAction] = useState(null);
  const menuRef = useRef(null);
  const fabRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-brand-600 font-display text-xl font-bold animate-pulse">Jatahku</div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" />;

  const initial = user.name ? user.name.charAt(0).toUpperCase() : '?';

  return (
    <div className="min-h-screen bg-page">
      <header className="bg-white/80 backdrop-blur-md border-b border-gray-100 sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <NavLink to="/" className="font-display text-xl font-bold text-brand-600">
              Jatah<span className="text-brand-400">ku</span>
            </NavLink>
            <nav className="hidden md:flex items-center gap-1">
              {[...navItems, ...menuItems].map(item => (
                <NavLink key={item.to} to={item.to} end={item.to === '/'}
                  className={({ isActive }) =>
                    `px-3 py-1.5 rounded-lg text-sm font-medium transition-colors inline-flex items-center gap-1.5 ${
                      isActive ? 'bg-brand-50 text-brand-600' : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'
                    }`}>
                  <Icon name={item.icon} size={17} />{item.label}
                </NavLink>
              ))}
            </nav>
          </div>

          {/* Notifications + Profile */}
          <div className="flex items-center gap-1">
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

      {/* Mobile bottom nav — 5 items only, no Settings */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-gray-100 z-50">
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
      <main className="max-w-6xl mx-auto px-4 py-6 pb-24 md:pb-6"><Outlet /></main>
      {/* Global FAB — speed dial */}
      {fabMenu && (
        <div className="fixed inset-0 z-50" onClick={() => setFabMenu(false)}>
          <div className="absolute bottom-36 right-4 md:bottom-28 md:right-6 flex flex-col-reverse items-center gap-3">
            {FAB_OPTIONS.map((opt, i) => (
              <button
                key={opt.key}
                onClick={(e) => {
                  e.stopPropagation();
                  setFabMenu(false);
                  setFabAction(opt.key);
                }}
                className="flex items-center gap-2 px-3 py-2 rounded-full bg-white border border-gray-200 shadow-lg text-sm font-medium text-gray-600 hover:border-brand-400 hover:text-brand-600 transition-all"
                style={{ animation: `fadeIn 0.15s ease-out ${i * 0.05}s both` }}
              >
                <Icon name={opt.icon} size={20} />
                <span>{opt.label}</span>
              </button>
            ))}
          </div>
          <button
            onClick={() => setFabMenu(false)}
            className="absolute bottom-24 right-4 md:bottom-6 md:right-6 z-50 w-14 h-14 rounded-full bg-brand-700 text-white text-3xl shadow-lg flex items-center justify-center transition-colors"
            style={{ lineHeight: 1, paddingTop: '1px', paddingLeft: '1px', transform: 'rotate(45deg)' }}
          >+</button>
        </div>
      )}
      {!fabMenu && (
        <button
          onClick={() => setFabMenu(true)}
          className="fixed bottom-24 right-4 md:bottom-6 md:right-6 z-50 w-14 h-14 rounded-full bg-brand-600 text-white text-3xl shadow-lg flex items-center justify-center hover:bg-brand-700 transition-colors"
          style={{ lineHeight: 1, paddingTop: '1px', paddingLeft: '1px' }}
          title="Menu cepat"
        >+</button>
      )}
      {/* Modals for speed dial actions */}
      {fabAction && (
        <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={() => setFabAction(null)}>
          <div className="bg-white rounded-2xl w-full max-w-2xl p-6 shadow-xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h3 className="font-display font-bold text-lg mb-4 flex items-center gap-2">
              {fabAction === 'expense' && <><Icon name="expense" size={22} /> Catat pengeluaran</>}
              {fabAction === 'envelope' && <><Icon name="envelope" size={22} /> Amplop baru</>}
              {fabAction === 'income' && <><Icon name="income" size={22} /> Income baru</>}
              {fabAction === 'langganan' && <><Icon name="langganan" size={22} /> Langganan baru</>}
            </h3>
            {fabAction === 'expense' && <MultiAddTransaction onSaved={() => setFabAction(null)} onCancel={() => setFabAction(null)} />}
            {fabAction === 'envelope' && <QuickAddEnvelope onClose={() => setFabAction(null)} />}
            {fabAction === 'income' && <QuickAddIncome onClose={() => setFabAction(null)} />}
            {fabAction === 'langganan' && <QuickAddLangganan onClose={() => setFabAction(null)} />}
          </div>
        </div>
      )}
    </div>
  );
}
