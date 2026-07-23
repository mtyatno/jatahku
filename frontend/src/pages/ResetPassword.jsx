import { useState } from 'react';
import { Navigate, Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export default function ResetPassword() {
  const { user, resetPassword } = useAuth();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to="/" />;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (password.length < 6) {
      setError('Password minimal 6 karakter');
      return;
    }
    if (password !== confirm) {
      setError('Password dan konfirmasi tidak cocok');
      return;
    }

    setLoading(true);
    try {
      const result = await resetPassword(token, password);
      if (!result.ok) {
        setError(result.data?.detail || 'Link tidak valid atau sudah kadaluarsa');
      } else {
        setSuccess(true);
      }
    } catch {
      setError('Terjadi kesalahan jaringan. Silakan coba lagi.');
    } finally {
      setLoading(false);
    }
  };

  // Token missing — show error state
  if (!token) {
    return (
      <div className="min-h-screen bg-page flex items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <a href="/" className="font-display text-4xl font-bold text-brand-600 mb-2 block" style={{textDecoration:'none'}}>
              Jatah<span className="text-brand-400">ku</span>
            </a>
          </div>
          <div className="card text-center space-y-3">
            <div className="text-4xl">⚠️</div>
            <h2 className="text-lg font-semibold">Link tidak valid</h2>
            <p className="text-sm text-gray-500">
              Link reset password tidak lengkap. Pastikan kamu membuka link dari email dengan benar.
            </p>
            <Link to="/forgot-password" className="text-sm text-brand-600 hover:underline block">
              Minta link baru →
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Success — brief message, will auto-redirect as user state updates
  if (success) {
    return (
      <div className="min-h-screen bg-page flex items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="card text-center space-y-3">
            <div className="text-4xl">✅</div>
            <h2 className="text-lg font-semibold">Password berhasil direset!</h2>
            <p className="text-sm text-gray-500">
              Password baru sudah disimpan. Mengalihkan ke dashboard...
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-page flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <a href="/" className="font-display text-4xl font-bold text-brand-600 mb-2 block" style={{textDecoration:'none'}}>
            Jatah<span className="text-brand-400">ku</span>
          </a>
          <p className="text-sm text-gray-500">Setiap rupiah ada jatahnya.</p>
        </div>

        <div className="card">
          <h2 className="text-lg font-semibold mb-1">Buat password baru</h2>
          <p className="text-sm text-gray-500 mb-4">
            Masukkan password baru untuk akun kamu.
          </p>

          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="label">Password baru</label>
              <input
                type="password"
                className="input"
                placeholder="Min. 6 karakter"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div>
              <label className="label">Konfirmasi password</label>
              <input
                type="password"
                className="input"
                placeholder="Ketik ulang password"
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                required
              />
            </div>

            {error && (
              <div className="text-sm text-danger-400 bg-red-50 px-3 py-2 rounded-lg">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full disabled:opacity-50"
            >
              {loading ? '...' : 'Reset Password'}
            </button>
          </form>

          <div className="text-center mt-5 pt-4 border-t border-gray-100">
            <Link to="/login" className="text-sm text-brand-600 hover:underline">
              ← Kembali ke login
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
