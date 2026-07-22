import { useState } from 'react';
import { Navigate, Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { api } from '../lib/api';

export default function ForgotPassword() {
  const { user } = useAuth();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to="/" />;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = await api.forgotPassword(email);
      if (!result.ok) {
        setError(result.data?.detail || 'Terjadi kesalahan');
      } else {
        setSent(true);
      }
    } catch {
      setError('Terjadi kesalahan jaringan. Silakan coba lagi.');
    } finally {
      setLoading(false);
    }
  };

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
          {!sent ? (
            <>
              <h2 className="text-lg font-semibold mb-1">Lupa password?</h2>
              <p className="text-sm text-gray-500 mb-4">
                Masukkan email kamu, kami akan kirim link untuk reset password.
              </p>

              <form onSubmit={handleSubmit} className="space-y-3">
                <div>
                  <label className="label">Email</label>
                  <input
                    type="email"
                    className="input"
                    placeholder="email@example.com"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    required
                    autoFocus
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
                  {loading ? '...' : 'Kirim Link Reset'}
                </button>
              </form>
            </>
          ) : (
            <div className="text-center space-y-3">
              <div className="text-4xl">📧</div>
              <h2 className="text-lg font-semibold">Cek email kamu</h2>
              <p className="text-sm text-gray-500">
                Kalau email terdaftar, link reset password sudah dikirim ke{' '}
                <span className="font-medium text-gray-700">{email}</span>.
              </p>
              <p className="text-xs text-gray-400">
                Link berlaku 30 menit dan hanya bisa dipakai sekali.
              </p>
            </div>
          )}

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
