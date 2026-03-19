import { useState } from 'react';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';

export default function Settings() {
  const { user, logout } = useAuth();
  const [linkCode, setLinkCode] = useState(null);
  const [loading, setLoading] = useState(false);

  const generateCode = async () => {
    setLoading(true);
    const res = await api.request('/auth/link/generate', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      setLinkCode(data.code);
    }
    setLoading(false);
  };

  return (
    <div className="space-y-6 max-w-lg">
      <div>
        <h1 className="text-2xl font-display font-bold">Settings</h1>
        <p className="text-sm text-gray-500">Kelola akun kamu</p>
      </div>
      <div className="card">
        <h3 className="font-semibold text-sm mb-3">Profil</h3>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-gray-400">Nama</span><span className="font-medium">{user?.name}</span></div>
          <div className="flex justify-between"><span className="text-gray-400">Email</span><span className="font-medium">{user?.email || '-'}</span></div>
          <div className="flex justify-between"><span className="text-gray-400">Telegram</span><span className="font-medium">{user?.telegram_id ? '✅ Terhubung' : '❌ Belum terhubung'}</span></div>
        </div>
      </div>
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
            <button onClick={generateCode} disabled={loading} className="btn-primary disabled:opacity-50">
              {loading ? '...' : 'Generate Kode Link'}
            </button>
          )}
        </div>
      )}
      <div className="card">
        <button onClick={logout} className="text-sm text-danger-400 hover:underline">Logout dari Jatahku</button>
      </div>
    </div>
  );
}
