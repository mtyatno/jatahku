import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency } from '../lib/utils';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area, CartesianGrid } from 'recharts';

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 shadow-sm">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-sm font-semibold" style={{color: p.color}}>{p.name}: {typeof p.value === 'number' && p.value > 1000 ? formatCurrency(p.value) : p.value}</p>
      ))}
    </div>
  );
}

function KPI({ label, value, sub, color }) {
  return (
    <div className="card">
      <p className="text-xs text-gray-400">{label}</p>
      <p className={`font-display text-2xl font-bold mt-1 ${color || ''}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

function UserRow({ u, onAction }) {
  const [loading, setLoading] = useState(false);

  const doAction = async (action) => {
    if (action === 'ban' && !confirm(`Ban ${u.name}?`)) return;
    setLoading(true);
    await onAction(u.id, action);
    setLoading(false);
  };

  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-50 last:border-0">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-brand-50 flex items-center justify-center text-sm font-bold text-brand-600">
          {u.name?.charAt(0)?.toUpperCase() || '?'}
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{u.name}</span>
            {u.is_admin && <span className="text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded">Admin</span>}
            <span className={`text-xs px-1.5 py-0.5 rounded ${u.plan === 'pro' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
              {u.plan === 'pro' ? 'Pro' : 'Free'}
            </span>
          </div>
          <p className="text-xs text-gray-400">{u.email} · {u.txn_count} txn {u.telegram_id ? '· 📱 TG' : ''}</p>
        </div>
      </div>
      <div className="flex gap-1">
        {u.plan !== 'pro' ? (
          <button onClick={() => doAction('upgrade')} disabled={loading}
            className="text-xs px-2 py-1 bg-brand-50 text-brand-600 rounded-lg hover:bg-brand-100 disabled:opacity-50">⬆ Pro</button>
        ) : (
          <button onClick={() => doAction('downgrade')} disabled={loading}
            className="text-xs px-2 py-1 bg-gray-50 text-gray-500 rounded-lg hover:bg-gray-100 disabled:opacity-50">⬇ Basic</button>
        )}
        {!u.is_admin ? (
          <button onClick={() => doAction('make_admin')} disabled={loading}
            className="text-xs px-2 py-1 bg-amber-50 text-amber-600 rounded-lg hover:bg-amber-100 disabled:opacity-50">👑</button>
        ) : (
          <button onClick={() => doAction('remove_admin')} disabled={loading}
            className="text-xs px-2 py-1 bg-gray-50 text-gray-400 rounded-lg hover:bg-gray-100 disabled:opacity-50">👤</button>
        )}
        <button onClick={() => doAction('ban')} disabled={loading}
          className="text-xs px-2 py-1 bg-red-50 text-red-400 rounded-lg hover:bg-red-100 disabled:opacity-50">🚫</button>
      </div>
    </div>
  );
}

export default function Admin() {
  const [dash, setDash] = useState(null);
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('dashboard');
  const [notifTitle, setNotifTitle] = useState('');
  const [notifMsg, setNotifMsg] = useState('');
  const [actionMsg, setActionMsg] = useState('');

  const loadDash = async () => {
    const res = await api.request('/admin/dashboard');
    if (res.ok) setDash(await res.json());
    else setError('Admin access required');
    setLoading(false);
  };

  const loadUsers = async (q) => {
    const url = q ? `/admin/users?search=${encodeURIComponent(q)}` : '/admin/users';
    const res = await api.request(url);
    if (res.ok) setUsers(await res.json());
  };

  useEffect(() => { loadDash(); loadUsers(); }, []);

  const handleUserAction = async (userId, action) => {
    const res = await api.request(`/admin/users/${userId}/action`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    });
    if (res.ok) {
      const d = await res.json();
      setActionMsg(`✅ ${d.action}: ${d.user}`);
      setTimeout(() => setActionMsg(''), 3000);
      loadUsers(search);
      loadDash();
    }
  };

  const handleSearch = (val) => {
    setSearch(val);
    loadUsers(val);
  };

  const upgradeAll = async () => {
    if (!confirm('Upgrade semua user ke Pro?')) return;
    const res = await api.request('/admin/users/upgrade-all', { method: 'POST' });
    if (res.ok) {
      const d = await res.json();
      setActionMsg(`✅ ${d.total_pro} users sekarang Pro`);
      setTimeout(() => setActionMsg(''), 3000);
      loadUsers(search);
      loadDash();
    }
  };

  const batchUpgrade = async () => {
    const n = prompt('Berapa user random yang mau di-upgrade?', '5');
    if (!n) return;
    const res = await api.request(`/admin/users/batch-upgrade?count=${n}`, { method: 'POST' });
    if (res.ok) {
      const d = await res.json();
      setActionMsg(`✅ Upgraded: ${d.upgraded.join(', ')}`);
      setTimeout(() => setActionMsg(''), 5000);
      loadUsers(search);
      loadDash();
    }
  };

  const sendNotifAll = async () => {
    if (!notifTitle || !notifMsg) return;
    const res = await api.request(`/admin/notify-all?title=${encodeURIComponent(notifTitle)}&message=${encodeURIComponent(notifMsg)}`, { method: 'POST' });
    if (res.ok) {
      const d = await res.json();
      setActionMsg(`✅ Notifikasi terkirim ke ${d.sent} user`);
      setNotifTitle(''); setNotifMsg('');
      setTimeout(() => setActionMsg(''), 3000);
    }
  };

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;
  if (error) return <div className="text-center py-12 text-red-400">{error}</div>;
  if (!dash) return null;

  const d = dash;
  const signups = d.charts.signups.map(s => ({ ...s, date: s.date.slice(5) }));
  const txns = d.charts.daily_txns.map(t => ({ ...t, date: t.date.slice(5) }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-display font-bold">Admin</h1>
        <div className="flex gap-2">
          <button onClick={() => setTab('dashboard')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium ${tab === 'dashboard' ? 'bg-brand-50 text-brand-600' : 'text-gray-400'}`}>Dashboard</button>
          <button onClick={() => setTab('users')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium ${tab === 'users' ? 'bg-brand-50 text-brand-600' : 'text-gray-400'}`}>Users</button>
          <button onClick={() => setTab('tools')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium ${tab === 'tools' ? 'bg-brand-50 text-brand-600' : 'text-gray-400'}`}>Tools</button>
          <button onClick={() => setTab('payments')}
        </div>
      </div>

      {actionMsg && <div className="bg-green-50 border border-green-200 text-sm px-4 py-3 rounded-xl text-green-700">{actionMsg}</div>}

      {tab === 'dashboard' && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KPI label="Total Users" value={d.users.total} sub={`+${d.users.this_week} minggu ini`} color="text-brand-600" />
            <KPI label="Pro Users" value={d.users.pro} sub={`${d.users.basic} basic`} color="text-amber-500" />
            <KPI label="TG Linked" value={d.users.tg_linked} sub={`${Math.round(d.users.tg_linked/d.users.total*100)}% adoption`} color="text-blue-500" />
            <KPI label="Total Transaksi" value={d.transactions.total} sub={`${d.transactions.today} hari ini`} />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <KPI label="Spending hari ini" value={d.transactions.today_amount} />
            <KPI label="Spending bulan ini" value={d.transactions.month_amount} />
            <KPI label="Total dikelola" value={d.transactions.total_managed} color="text-brand-600" />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="card">
              <h3 className="font-semibold text-sm mb-3">Signups (14 hari)</h3>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={signups}>
                  <XAxis dataKey="date" tick={{fontSize: 10}} tickLine={false} axisLine={false} />
                  <YAxis tick={{fontSize: 10}} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="count" name="Signups" fill="#0F6E56" radius={[3,3,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="card">
              <h3 className="font-semibold text-sm mb-3">Transaksi (14 hari)</h3>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={txns}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                  <XAxis dataKey="date" tick={{fontSize: 10}} tickLine={false} axisLine={false} />
                  <YAxis tick={{fontSize: 10}} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip content={<CustomTooltip />} />
                  <Area type="monotone" dataKey="count" name="Transaksi" stroke="#BA7517" fill="#BA7517" fillOpacity={0.15} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}

      {tab === 'users' && (
        <>
          <div className="flex gap-2">
            <input className="input text-sm flex-1" placeholder="Cari nama atau email..." value={search}
              onChange={e => handleSearch(e.target.value)} />
            <span className="text-sm text-gray-400 self-center">{users.length} users</span>
          </div>
          <div className="card">
            {users.map(u => <UserRow key={u.id} u={u} onAction={handleUserAction} />)}
            {users.length === 0 && <p className="text-center text-gray-400 py-8 text-sm">Tidak ada user ditemukan</p>}
          </div>
        </>
      )}


      {tab === 'tools' && (
        <div className="space-y-4">
          <div className="card">
            <h3 className="font-semibold text-sm mb-3">🎁 Promo Tools</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Upgrade semua user ke Pro</p>
                  <p className="text-xs text-gray-400">First 100 promo — semua user aktif jadi Pro</p>
                </div>
                <button onClick={upgradeAll} className="text-sm px-3 py-1.5 bg-brand-50 text-brand-600 rounded-lg hover:bg-brand-100">Upgrade All</button>
              </div>
              <div className="flex items-center justify-between border-t border-gray-50 pt-3">
                <div>
                  <p className="text-sm font-medium">Random upgrade</p>
                  <p className="text-xs text-gray-400">Pilih N user basic random → Pro</p>
                </div>
                <button onClick={batchUpgrade} className="text-sm px-3 py-1.5 bg-amber-50 text-amber-600 rounded-lg hover:bg-amber-100">Random Upgrade</button>
              </div>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-sm mb-3">📱 Telegram Reminder</h3>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Email reminder ke user tanpa Telegram</p>
                <p className="text-xs text-gray-400">Kirim email ajakan link Telegram ke semua user yang belum connect</p>
              </div>
              <button onClick={async () => {
                if (!confirm('Kirim email reminder ke semua user tanpa Telegram?')) return;
                const res = await api.request('/admin/send-tg-reminders', { method: 'POST' });
                if (res.ok) { const d = await res.json(); setActionMsg(`✅ Email terkirim ke ${d.sent} dari ${d.total_unlinked} user`); setTimeout(() => setActionMsg(''), 5000); }
              }} className="text-sm px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100">
                Kirim Reminder
              </button>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-sm mb-3">📢 Broadcast Notification</h3>
            <div className="space-y-2">
              <input className="input text-sm" placeholder="Judul notifikasi" value={notifTitle} onChange={e => setNotifTitle(e.target.value)} />
              <textarea className="input text-sm" rows="3" placeholder="Isi pesan..." value={notifMsg} onChange={e => setNotifMsg(e.target.value)} />
              <button onClick={sendNotifAll} disabled={!notifTitle || !notifMsg}
                className="btn-primary text-sm py-2 disabled:opacity-50">Kirim ke semua user</button>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-sm mb-3">🖥️ System Info</h3>
            <div className="space-y-1 text-sm text-gray-500">
              <p>API: <a href="https://api.jatahku.com/health" target="_blank" className="text-brand-600">api.jatahku.com/health</a></p>
              <p>GitHub: <a href="https://github.com/mtyatno/jatahku" target="_blank" className="text-brand-600">mtyatno/jatahku</a></p>
              <p>VPS: 2vCPU / 4GB RAM / Ubuntu 24.04</p>
              <p>Stack: FastAPI + PostgreSQL + Redis + React</p>
            </div>
          </div>
        </div>
      )}
      {tab === 'payments' && <PaymentsTab onAction={() => { setActionMsg('✅ Done'); setTimeout(() => setActionMsg(''), 3000); }} />}
    </div>
  );
}

function PaymentsTab({ onAction }) {
  const [orders, setOrders] = useState([]);
  const [promos, setPromos] = useState([]);
  const [banks, setBanks] = useState([]);
  const [filter, setFilter] = useState('');
  const [newBank, setNewBank] = useState({ bank: '', account_number: '', account_name: '' });
  const [newPromo, setNewPromo] = useState({ code: '', discount_pct: 0, is_free: false, max_uses: '', event_name: '', valid_days: '' });
  const [showAddBank, setShowAddBank] = useState(false);
  const [showAddPromo, setShowAddPromo] = useState(false);

  const load = async () => {
    const url = filter ? `/admin/payment-orders?status=${filter}` : '/admin/payment-orders';
    const r = await api.request(url);
    if (r.ok) setOrders(await r.json());
    const pr = await api.request('/admin/promo-codes');
    if (pr.ok) setPromos(await pr.json());
    const br = await api.request('/admin/settings/bank_accounts');
    if (br.ok) setBanks(br.value || []);
    try {
      const bData = await (await api.request('/admin/settings/bank_accounts')).json();
      setBanks(Array.isArray(bData.value) ? bData.value : JSON.parse(bData.value || '[]'));
    } catch { setBanks([]); }
  };

  useEffect(() => { load(); }, [filter]);

  const approveOrder = async (id) => {
    await api.request(`/admin/payment-orders/${id}/approve`, { method: 'POST' });
    onAction(); load();
  };

  const rejectOrder = async (id) => {
    const reason = prompt('Alasan penolakan:');
    if (!reason) return;
    await api.request(`/admin/payment-orders/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: 'POST' });
    onAction(); load();
  };

  const saveBanks = async (list) => {
    await api.request(`/admin/settings/bank_accounts?value=${encodeURIComponent(JSON.stringify(list))}`, { method: 'PUT' });
    setBanks(list); onAction();
  };

  const addBank = () => {
    if (!newBank.bank || !newBank.account_number) return;
    saveBanks([...banks, newBank]);
    setNewBank({ bank: '', account_number: '', account_name: '' });
    setShowAddBank(false);
  };

  const removeBank = (idx) => saveBanks(banks.filter((_, i) => i !== idx));

  const createPromo = async () => {
    await api.request('/admin/promo-codes', {
      method: 'POST',
      body: JSON.stringify({
        ...newPromo,
        max_uses: newPromo.max_uses ? parseInt(newPromo.max_uses) : null,
        valid_days: newPromo.valid_days ? parseInt(newPromo.valid_days) : null,
      }),
    });
    setNewPromo({ code: '', discount_pct: 0, is_free: false, max_uses: '', event_name: '', valid_days: '' });
    setShowAddPromo(false);
    onAction(); load();
  };

  const deletePromo = async (id) => {
    if (!confirm('Nonaktifkan promo ini?')) return;
    await api.request(`/admin/promo-codes/${id}`, { method: 'DELETE' });
    onAction(); load();
  };

  return (
    <div className="space-y-4">
      {/* Bank Accounts */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">🏦 Rekening Tujuan</h3>
        {banks.map((b, i) => (
          <div key={i} className="flex items-center justify-between py-2 border-b border-gray-50">
            <div><p className="text-sm font-semibold">{b.bank}</p><p className="text-xs text-gray-500">{b.account_number} — {b.account_name}</p></div>
            <button onClick={() => removeBank(i)} className="text-xs text-red-400 hover:underline">Hapus</button>
          </div>
        ))}
        {!showAddBank ? (
          <button onClick={() => setShowAddBank(true)} className="text-sm text-brand-600 hover:underline mt-2">+ Tambah rekening</button>
        ) : (
          <div className="mt-3 space-y-2 p-3 bg-gray-50 rounded-xl">
            <input className="input text-sm" placeholder="Nama bank (BCA, Mandiri, dll)" value={newBank.bank} onChange={e => setNewBank({...newBank, bank: e.target.value})} />
            <input className="input text-sm" placeholder="No rekening" value={newBank.account_number} onChange={e => setNewBank({...newBank, account_number: e.target.value})} />
            <input className="input text-sm" placeholder="Atas nama" value={newBank.account_name} onChange={e => setNewBank({...newBank, account_name: e.target.value})} />
            <div className="flex gap-2">
              <button onClick={addBank} className="btn-primary text-sm py-1.5">Simpan</button>
              <button onClick={() => setShowAddBank(false)} className="text-xs text-gray-400">Batal</button>
            </div>
          </div>
        )}
      </div>

      {/* Promo Codes */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">🎁 Kode Promo</h3>
        {promos.map(p => (
          <div key={p.id} className="flex items-center justify-between py-2 border-b border-gray-50">
            <div>
              <span className="font-mono font-bold text-brand-600">{p.code}</span>
              <span className="text-xs text-gray-400 ml-2">{p.is_free ? 'FREE' : `-${p.discount_pct}%`} · {p.used_count}/{p.max_uses || '∞'} used</span>
              {p.event_name && <span className="text-xs text-amber-600 ml-1">· {p.event_name}</span>}
            </div>
            <button onClick={() => deletePromo(p.id)} className="text-xs text-red-400 hover:underline">{p.is_active ? 'Nonaktifkan' : 'Inactive'}</button>
          </div>
        ))}
        {!showAddPromo ? (
          <button onClick={() => setShowAddPromo(true)} className="text-sm text-brand-600 hover:underline mt-2">+ Buat promo</button>
        ) : (
          <div className="mt-3 space-y-2 p-3 bg-gray-50 rounded-xl">
            <input className="input text-sm" placeholder="Kode promo (contoh: MERDEKA)" value={newPromo.code} onChange={e => setNewPromo({...newPromo, code: e.target.value})} />
            <div className="flex gap-2 items-center">
              <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={newPromo.is_free} onChange={e => setNewPromo({...newPromo, is_free: e.target.checked, discount_pct: e.target.checked ? 100 : 0})} /> Gratis</label>
              {!newPromo.is_free && <input className="input text-sm w-24" type="number" placeholder="Diskon %" value={newPromo.discount_pct} onChange={e => setNewPromo({...newPromo, discount_pct: parseInt(e.target.value)||0})} />}
            </div>
            <input className="input text-sm" type="number" placeholder="Max penggunaan (kosong=unlimited)" value={newPromo.max_uses} onChange={e => setNewPromo({...newPromo, max_uses: e.target.value})} />
            <input className="input text-sm" placeholder="Event (contoh: 17 Agustus)" value={newPromo.event_name} onChange={e => setNewPromo({...newPromo, event_name: e.target.value})} />
            <input className="input text-sm" type="number" placeholder="Berlaku berapa hari (kosong=forever)" value={newPromo.valid_days} onChange={e => setNewPromo({...newPromo, valid_days: e.target.value})} />
            <div className="flex gap-2">
              <button onClick={createPromo} disabled={!newPromo.code} className="btn-primary text-sm py-1.5 disabled:opacity-50">Buat</button>
              <button onClick={() => setShowAddPromo(false)} className="text-xs text-gray-400">Batal</button>
            </div>
          </div>
        )}
      </div>

      {/* Payment Orders */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-sm">💳 Payment Orders</h3>
          <div className="flex gap-1">
            {['', 'waiting_confirmation', 'pending', 'completed', 'rejected'].map(s => (
              <button key={s} onClick={() => setFilter(s)}
                className={`text-xs px-2 py-1 rounded-lg ${filter === s ? 'bg-brand-50 text-brand-600' : 'text-gray-400'}`}>
                {s || 'All'}
              </button>
            ))}
          </div>
        </div>
        {orders.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-4">Belum ada order</p>
        ) : orders.map(o => (
          <div key={o.id} className="py-3 border-b border-gray-50">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold">{o.user_name}</p>
                <p className="text-xs text-gray-400">{o.user_email} · {formatCurrency(o.amount)} · {new Date(o.created_at).toLocaleDateString('id-ID')}</p>
                {o.promo_code && <span className="text-xs text-amber-600">Promo: {o.promo_code} (-{o.discount_pct}%)</span>}
              </div>
              <div className="flex items-center gap-2">
                {o.proof_url && <a href={o.proof_url} target="_blank" className="text-xs text-blue-500 hover:underline">📸 Bukti</a>}
                {(o.status === 'waiting_confirmation' || o.status === 'pending') && (
                  <>
                    <button onClick={() => approveOrder(o.id)} className="text-xs px-2 py-1 bg-green-50 text-green-600 rounded-lg hover:bg-green-100">✅ Approve</button>
                    <button onClick={() => rejectOrder(o.id)} className="text-xs px-2 py-1 bg-red-50 text-red-400 rounded-lg hover:bg-red-100">❌ Reject</button>
                  </>
                )}
                {o.status === 'completed' && <span className="text-xs text-green-600">✅</span>}
                {o.status === 'rejected' && <span className="text-xs text-red-400">❌</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
