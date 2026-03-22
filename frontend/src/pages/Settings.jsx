import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';


function NotifPrefs() {
  const [prefs, setPrefs] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.request('/notifications/preferences').then(r => r.ok ? r.json() : null).then(setPrefs);
  }, []);

  const toggle = async (key) => {
    const updated = { ...prefs, [key]: !prefs[key] };
    setPrefs(updated);
    setSaving(true);
    await api.request('/notifications/preferences', {
      method: 'PUT',
      body: JSON.stringify(updated),
    });
    setSaving(false);
  };

  if (!prefs) return <p className="text-xs text-gray-400">Loading...</p>;

  const rows = [
    { label: 'Budget warning', key: 'budget_warning' },
    { label: 'Langganan jatuh tempo', key: 'subscription_due' },
    { label: 'Ringkasan harian', key: 'daily_summary' },
    { label: 'Ringkasan mingguan', key: 'weekly_summary' },
    { label: 'Cooling period selesai', key: 'cooling_ready' },
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2 text-xs text-gray-400 font-medium px-1">
        <span></span><span className="text-center">Telegram</span><span className="text-center">WebApp</span>
      </div>
      {rows.map(r => (
        <div key={r.key} className="grid grid-cols-3 gap-2 items-center">
          <span className="text-sm text-gray-600">{r.label}</span>
          <label className="flex justify-center"><input type="checkbox" checked={prefs[r.key + '_tg']} onChange={() => toggle(r.key + '_tg')} className="w-4 h-4 rounded border-gray-300 text-brand-600" /></label>
          <label className="flex justify-center"><input type="checkbox" checked={prefs[r.key + '_web']} onChange={() => toggle(r.key + '_web')} className="w-4 h-4 rounded border-gray-300 text-brand-600" /></label>
        </div>
      ))}
      {saving && <p className="text-xs text-gray-400">Menyimpan...</p>}
    </div>
  );
}

export default function Settings() {
  const { user, logout } = useAuth();
  const [linkCode, setLinkCode] = useState(null);
  const [copied, setCopied] = useState(false);
  const [linkLoading, setLinkLoading] = useState(false);
  const [unlinkLoading, setUnlinkLoading] = useState(false);
  const [household, setHousehold] = useState(null);
  const [members, setMembers] = useState([]);
  const [inviteCode, setInviteCode] = useState(null);
  const [inviteLoading, setInviteLoading] = useState(false);
  const [joinCode, setJoinCode] = useState('');
  const [joinLoading, setJoinLoading] = useState(false);
  const [joinError, setJoinError] = useState('');

  const load = () => {
    api.getMe().then(u => { if (u) window.__user = u; });
    api.request('/household/').then(r => r.ok ? r.json() : null).then(setHousehold);
    api.request('/household/members').then(r => r.ok ? r.json() : []).then(setMembers);
  };
  useEffect(load, []);

  const generateLinkCode = async () => {
    setLinkLoading(true);
    const res = await api.request('/auth/link/generate', { method: 'POST' });
    if (res.ok) { const data = await res.json(); setLinkCode(data.code); }
    setLinkLoading(false);
  };

  // Poll to detect when Telegram is linked
  useEffect(() => {
    if (!linkCode || user?.telegram_id) return;
    const interval = setInterval(async () => {
      const res = await api.request('/auth/me');
      if (res.ok) {
        const me = await res.json();
        if (me.telegram_id) {
          window.location.reload();
        }
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [linkCode, user?.telegram_id]);

  const handleUnlink = async () => {
    if (!confirm('Yakin mau unlink Telegram? Data tetap aman, tapi kamu nggak bisa catat lewat Telegram sampai link ulang.')) return;
    setUnlinkLoading(true);
    const res = await api.request('/auth/link/unlink', { method: 'POST' });
    setUnlinkLoading(false);
    if (res.ok) { window.location.reload(); }
  };

  const generateInvite = async () => {
    setInviteLoading(true);
    const res = await api.request('/household/invite', { method: 'POST' });
    if (res.ok) { const data = await res.json(); setInviteCode(data.code); }
    setInviteLoading(false);
  };

  const handleJoin = async (e) => {
    e.preventDefault();
    setJoinLoading(true); setJoinError('');
    const res = await api.request(`/household/join?code=${joinCode.trim().toUpperCase()}`, { method: 'POST' });
    const data = await res.json();
    setJoinLoading(false);
    if (res.ok) { window.location.reload(); } else { setJoinError(data.detail || 'Gagal bergabung'); }
  };

  const roleLabel = (role) => role === 'owner' ? '👑 Owner' : role === 'admin' ? '⭐ Admin' : '👤 Member';

  return (
    <div className="space-y-6 max-w-lg">
      <div><h1 className="text-2xl font-display font-bold">Settings</h1><p className="text-sm text-gray-500">Kelola akun dan household</p></div>

      <div className="card">
        <h3 className="font-semibold text-sm mb-3">Profil</h3>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-gray-400">Nama</span><span className="font-medium">{user?.name}</span></div>
          <div className="flex justify-between"><span className="text-gray-400">Email</span><span className="font-medium">{user?.email || '-'}</span></div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Telegram</span>
            {user?.telegram_id ? (
              <div className="flex items-center gap-2">
                <span className="font-medium text-brand-600">✅ Terhubung</span>
                <button onClick={handleUnlink} disabled={unlinkLoading} className="text-xs text-danger-400 hover:underline disabled:opacity-50">
                  {unlinkLoading ? '...' : 'Unlink'}
                </button>
              </div>
            ) : (
              <span className="font-medium">❌ Belum terhubung</span>
            )}
          </div>
        </div>
      </div>

      {!user?.telegram_id && (
        <div className="card border-brand-200">
          <h3 className="font-semibold text-sm mb-2">Link Telegram</h3>
          <p className="text-xs text-gray-500 mb-3">Hubungkan akun Telegram supaya bisa catat pengeluaran lewat chat.</p>

          {linkCode ? (
            <div className="text-center py-4">
              <p className="text-xs text-gray-400 mb-2">Kirim perintah ini ke @JatahkuBot:</p>
              <div className="bg-gray-50 rounded-xl px-4 py-4 inline-flex items-center gap-3">
                <code className="font-mono text-2xl font-bold text-brand-600 tracking-widest">/link {linkCode}</code>
                <button onClick={() => {navigator.clipboard.writeText('/link ' + linkCode); setCopied(true); setTimeout(() => setCopied(false), 2000);}}
                  className="px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-xs font-medium text-gray-500 hover:text-brand-600 hover:border-brand-400 transition-all">
                  {copied ? '✅ Copied!' : '📋 Copy'}
                </button>
              </div>
              <p className="text-xs text-gray-400 mt-2">Kode berlaku 5 menit</p>
              <a href="https://t.me/JatahkuBot" target="_blank"
                className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-blue-500 text-white text-sm font-medium rounded-xl hover:bg-blue-600 transition-colors">
                📱 Buka @JatahkuBot di Telegram
              </a>
            </div>
          ) : (
            <button onClick={generateLinkCode} disabled={linkLoading} className="btn-primary disabled:opacity-50">
              {linkLoading ? '...' : 'Generate Kode Link'}
            </button>
          )}
        </div>
      )}

      {household && (
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-sm">🏠 {household.name}</h3>
            <span className="text-xs text-gray-400">{household.member_count} anggota</span>
          </div>
          <div className="space-y-2">
            {members.map(m => (
              <div key={m.user_id} className="flex items-center justify-between py-2 border-b border-gray-50 last:border-0">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-full bg-brand-50 flex items-center justify-center text-sm font-bold text-brand-600">{m.name.charAt(0).toUpperCase()}</div>
                  <div><p className="text-sm font-medium">{m.name}</p><p className="text-xs text-gray-400">{roleLabel(m.role)}{m.telegram_linked ? ' · 📱 TG' : ''}</p></div>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-3 border-t border-gray-100">
            {inviteCode ? (
              <div className="text-center py-3">
                <p className="text-xs text-gray-400 mb-2">Share kode ini ke anggota baru:</p>
                <div className="bg-gray-50 rounded-xl px-6 py-3 inline-block">
                  <code className="font-mono text-xl font-bold text-brand-600 tracking-widest">{inviteCode}</code>
                </div>
                <p className="text-xs text-gray-400 mt-2">Berlaku 24 jam · <code className="text-brand-600">/join {inviteCode}</code></p>
              </div>
            ) : (
              <button onClick={generateInvite} disabled={inviteLoading} className="btn-outline w-full disabled:opacity-50">
                {inviteLoading ? '...' : '+ Invite Anggota Baru'}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="card">
        <h3 className="font-semibold text-sm mb-2">Gabung Household</h3>
        <p className="text-xs text-gray-500 mb-3">Punya kode invite? Masukkan di sini.</p>
        <form onSubmit={handleJoin} className="flex gap-2">
          <input type="text" className="input flex-1 font-mono uppercase tracking-widest" placeholder="KODE INVITE" value={joinCode} onChange={e => setJoinCode(e.target.value)} required />
          <button type="submit" disabled={joinLoading} className="btn-primary disabled:opacity-50">{joinLoading ? '...' : 'Gabung'}</button>
        </form>
        {joinError && <p className="text-xs text-danger-400 mt-2">{joinError}</p>}
      </div>

      <div className="card">
        <h3 className="font-semibold text-sm mb-3">🔔 Notifikasi</h3>
        <NotifPrefs />
      </div>

      <div className="card">
        <button onClick={logout} className="text-sm text-danger-400 hover:underline">Logout dari Jatahku</button>
      </div>
    </div>
  );
}
