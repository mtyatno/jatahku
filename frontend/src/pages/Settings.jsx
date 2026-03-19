import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';

export default function Settings() {
  const { user, logout } = useAuth();
  const [linkCode, setLinkCode] = useState(null);
  const [linkLoading, setLinkLoading] = useState(false);
  const [household, setHousehold] = useState(null);
  const [members, setMembers] = useState([]);
  const [inviteCode, setInviteCode] = useState(null);
  const [inviteLoading, setInviteLoading] = useState(false);
  const [joinCode, setJoinCode] = useState('');
  const [joinLoading, setJoinLoading] = useState(false);
  const [joinError, setJoinError] = useState('');

  useEffect(() => {
    api.request('/household/').then(r => r.ok ? r.json() : null).then(setHousehold);
    api.request('/household/members').then(r => r.ok ? r.json() : []).then(setMembers);
  }, []);

  const generateLinkCode = async () => {
    setLinkLoading(true);
    const res = await api.request('/auth/link/generate', { method: 'POST' });
    if (res.ok) { const data = await res.json(); setLinkCode(data.code); }
    setLinkLoading(false);
  };

  const generateInvite = async () => {
    setInviteLoading(true);
    const res = await api.request('/household/invite', { method: 'POST' });
    if (res.ok) { const data = await res.json(); setInviteCode(data.code); }
    setInviteLoading(false);
  };

  const handleJoin = async (e) => {
    e.preventDefault();
    setJoinLoading(true);
    setJoinError('');
    const res = await api.request(`/household/join?code=${joinCode.trim().toUpperCase()}`, { method: 'POST' });
    const data = await res.json();
    setJoinLoading(false);
    if (res.ok) {
      window.location.reload();
    } else {
      setJoinError(data.detail || 'Gagal bergabung');
    }
  };

  const roleLabel = (role) => {
    if (role === 'owner') return '👑 Owner';
    if (role === 'admin') return '⭐ Admin';
    return '👤 Member';
  };

  return (
    <div className="space-y-6 max-w-lg">
      <div>
        <h1 className="text-2xl font-display font-bold">Settings</h1>
        <p className="text-sm text-gray-500">Kelola akun dan household</p>
      </div>

      {/* Profile */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">Profil</h3>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-gray-400">Nama</span><span className="font-medium">{user?.name}</span></div>
          <div className="flex justify-between"><span className="text-gray-400">Email</span><span className="font-medium">{user?.email || '-'}</span></div>
          <div className="flex justify-between"><span className="text-gray-400">Telegram</span><span className="font-medium">{user?.telegram_id ? '✅ Terhubung' : '❌ Belum terhubung'}</span></div>
        </div>
      </div>

      {/* Link Telegram */}
      {!user?.telegram_id && (
        <div className="card border-brand-200">
          <h3 className="font-semibold text-sm mb-2">Link Telegram</h3>
          <p className="text-xs text-gray-500 mb-3">Hubungkan akun Telegram supaya bisa catat pengeluaran lewat chat.</p>
          {linkCode ? (
            <div className="text-center py-4">
              <p className="text-xs text-gray-400 mb-2">Kirim perintah ini ke @JatahkuBot:</p>
              <div className="bg-gray-50 rounded-xl px-6 py-4 inline-block">
                <code className="font-mono text-2xl font-bold text-brand-600 tracking-widest">/link {linkCode}</code>
              </div>
              <p className="text-xs text-gray-400 mt-3">Kode berlaku 5 menit</p>
            </div>
          ) : (
            <button onClick={generateLinkCode} disabled={linkLoading} className="btn-primary disabled:opacity-50">
              {linkLoading ? '...' : 'Generate Kode Link'}
            </button>
          )}
        </div>
      )}

      {/* Household */}
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
                  <div className="w-8 h-8 rounded-full bg-brand-50 flex items-center justify-center text-sm font-bold text-brand-600">
                    {m.name.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{m.name}</p>
                    <p className="text-xs text-gray-400">{roleLabel(m.role)}{m.telegram_linked ? ' · 📱 TG' : ''}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Invite */}
          <div className="mt-4 pt-3 border-t border-gray-100">
            {inviteCode ? (
              <div className="text-center py-3">
                <p className="text-xs text-gray-400 mb-2">Share kode ini ke anggota baru:</p>
                <div className="bg-gray-50 rounded-xl px-6 py-3 inline-block">
                  <code className="font-mono text-xl font-bold text-brand-600 tracking-widest">{inviteCode}</code>
                </div>
                <p className="text-xs text-gray-400 mt-2">Berlaku 24 jam · WebApp atau Telegram <code className="text-brand-600">/join {inviteCode}</code></p>
              </div>
            ) : (
              <button onClick={generateInvite} disabled={inviteLoading} className="btn-outline w-full disabled:opacity-50">
                {inviteLoading ? '...' : '+ Invite Anggota Baru'}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Join household */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-2">Gabung Household</h3>
        <p className="text-xs text-gray-500 mb-3">Punya kode invite? Masukkan di sini untuk bergabung.</p>
        <form onSubmit={handleJoin} className="flex gap-2">
          <input
            type="text"
            className="input flex-1 font-mono uppercase tracking-widest"
            placeholder="KODE INVITE"
            value={joinCode}
            onChange={e => setJoinCode(e.target.value)}
            required
          />
          <button type="submit" disabled={joinLoading} className="btn-primary disabled:opacity-50">
            {joinLoading ? '...' : 'Gabung'}
          </button>
        </form>
        {joinError && <p className="text-xs text-danger-400 mt-2">{joinError}</p>}
      </div>

      <div className="card">
        <button onClick={logout} className="text-sm text-danger-400 hover:underline">Logout dari Jatahku</button>
      </div>
    </div>
  );
}
