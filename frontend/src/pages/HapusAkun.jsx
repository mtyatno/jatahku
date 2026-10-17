import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { api } from '../lib/api';

// Halaman permintaan hapus akun tanpa login (syarat Google Play: URL hapus akun di web).
// Tanpa token: isi email → link konfirmasi dikirim. Dengan token (dari email): konfirmasi → hapus.

function Shell({ children }) {
  return (
    <div className="min-h-screen bg-page flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <a href="/" className="font-display text-4xl font-bold text-brand-600 mb-2 block" style={{textDecoration:'none'}}>
            Jatah<span className="text-brand-400">ku</span>
          </a>
          <p className="text-sm text-gray-500">Hapus akun</p>
        </div>
        {children}
      </div>
    </div>
  );
}

function WhatIsDeleted() {
  return (
    <ul className="text-xs text-gray-500 space-y-1 list-disc pl-4">
      <li>Akun, amplop pribadi, transaksi, pemasukan, langganan, dan notifikasi dihapus permanen.</li>
      <li>Semua perangkat langsung keluar; Telegram tidak lagi tertaut.</li>
      <li>Catatan kamu di amplop bersama household tetap ada tanpa nama ("Mantan anggota") supaya saldo anggota lain tidak berubah.</li>
      <li>Penghapusan tidak bisa dibatalkan. Unduh data dulu di Pengaturan bila perlu.</li>
    </ul>
  );
}

export default function HapusAkun() {
  const { user, logout } = useAuth();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');

  const [email, setEmail] = useState('');
  const [confirm, setConfirm] = useState('');
  const [sent, setSent] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submitRequest = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    const result = await api.requestAccountDeletion(email);
    setLoading(false);
    if (result.ok) setSent(true);
    else setError(result.data?.detail || 'Terjadi kesalahan. Silakan coba lagi.');
  };

  const submitConfirm = async (e) => {
    e.preventDefault();
    if (confirm !== 'HAPUS') return;
    setError('');
    setLoading(true);
    const result = await api.confirmAccountDeletion(token);
    setLoading(false);
    if (!result.ok) {
      setError(result.data?.detail || 'Link tidak valid atau sudah kadaluarsa');
      return;
    }
    setDeleted(true);
    if (user) logout();
  };

  if (deleted) {
    return (
      <Shell>
        <div className="card text-center space-y-3">
          <div className="text-4xl">✅</div>
          <h2 className="text-lg font-semibold">Akun sudah dihapus</h2>
          <p className="text-sm text-gray-500">Semua data kamu sudah dihapus dan semua perangkat sudah keluar. Terima kasih sudah memakai Jatahku.</p>
        </div>
      </Shell>
    );
  }

  if (token) {
    return (
      <Shell>
        <div className="card space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-red-600 mb-1">⚠️ Hapus akun permanen?</h2>
            <p className="text-sm text-gray-500">Langkah terakhir. Setelah ini akun tidak bisa dipulihkan.</p>
          </div>
          <WhatIsDeleted />
          <form onSubmit={submitConfirm} className="space-y-3">
            <input className="input text-sm border-red-200" placeholder='Ketik "HAPUS" untuk konfirmasi'
              value={confirm} onChange={e => setConfirm(e.target.value)} autoFocus />
            {error && <div className="text-sm text-danger-400 bg-red-50 px-3 py-2 rounded-lg">{error}</div>}
            <button type="submit" disabled={confirm !== 'HAPUS' || loading}
              className="w-full px-4 py-2 bg-red-500 text-white text-sm font-medium rounded-xl disabled:opacity-50">
              {loading ? '...' : 'Hapus akun permanen'}
            </button>
          </form>
          {error && (
            <Link to="/hapus-akun" className="text-sm text-brand-600 hover:underline block text-center">Minta link baru →</Link>
          )}
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="card space-y-4">
        {sent ? (
          <div className="text-center space-y-3">
            <div className="text-4xl">📧</div>
            <h2 className="text-lg font-semibold">Cek email kamu</h2>
            <p className="text-sm text-gray-500">
              Kalau <strong>{email}</strong> terdaftar, link konfirmasi sudah dikirim. Link berlaku 1 jam.
            </p>
          </div>
        ) : (
          <>
            <div>
              <h2 className="text-lg font-semibold mb-1">Minta hapus akun</h2>
              <p className="text-sm text-gray-500">Masukkan email akun Jatahku kamu. Kami kirim link untuk mengonfirmasi penghapusan.</p>
            </div>
            <WhatIsDeleted />
            <form onSubmit={submitRequest} className="space-y-3">
              <div>
                <label className="label">Email</label>
                <input type="email" className="input" placeholder="nama@email.com" required
                  value={email} onChange={e => setEmail(e.target.value)} />
              </div>
              {error && <div className="text-sm text-danger-400 bg-red-50 px-3 py-2 rounded-lg">{error}</div>}
              <button type="submit" disabled={loading} className="btn-primary w-full disabled:opacity-50">
                {loading ? '...' : 'Kirim link konfirmasi'}
              </button>
            </form>
          </>
        )}
        <p className="text-xs text-gray-400 border-t border-gray-100 pt-3">
          Akun tanpa email (masuk lewat Telegram)? Masuk ke Jatahku lalu buka Pengaturan → Hapus akun saya,
          atau kirim permintaan ke <a href="mailto:hi@jatahku.com" className="text-brand-600">hi@jatahku.com</a>.
        </p>
      </div>
    </Shell>
  );
}
