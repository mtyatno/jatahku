import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export default function Login() {
  const { user, login, register } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to="/" />;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    const result = isRegister
      ? await register(email, password, name)
      : await login(email, password);

    setLoading(false);
    if (!result.ok) {
      setError(result.data?.detail || 'Terjadi kesalahan');
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
          <div className="flex rounded-lg bg-gray-50 p-0.5 mb-5">
            <button
              onClick={() => setIsRegister(false)}
              className={`flex-1 py-2 text-sm font-semibold rounded-md transition-all ${
                !isRegister ? 'bg-white text-brand-600 shadow-sm' : 'text-gray-400'
              }`}
            >
              Masuk
            </button>
            <button
              onClick={() => setIsRegister(true)}
              className={`flex-1 py-2 text-sm font-semibold rounded-md transition-all ${
                isRegister ? 'bg-white text-brand-600 shadow-sm' : 'text-gray-400'
              }`}
            >
              Daftar
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3">
            {isRegister && (
              <div>
                <label className="label">Nama</label>
                <input
                  type="text"
                  className="input"
                  placeholder="Nama kamu"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  required={isRegister}
                />
              </div>
            )}
            <div>
              <label className="label">Email</label>
              <input
                type="email"
                className="input"
                placeholder="email@example.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="label">Password</label>
              <input
                type="password"
                className="input"
                placeholder="Min. 6 karakter"
                value={password}
                onChange={e => setPassword(e.target.value)}
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
              className="btn-primary w-full mt-2 disabled:opacity-50"
            >
              {loading ? '...' : isRegister ? 'Buat Akun' : 'Masuk'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-gray-400 mt-6">
          Punya bot Telegram? Link akun di Settings.
        </p>
      </div>
    </div>
  );
}
