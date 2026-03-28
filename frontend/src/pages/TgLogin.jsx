import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export default function TgLogin() {
  const [status, setStatus] = useState('loading');
  const navigate = useNavigate();
  const { loginWithTgToken } = useAuth();

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get('token');
    if (!token) {
      setStatus('invalid');
      return;
    }
    loginWithTgToken(token)
      .then(result => {
        if (result.ok) {
          navigate('/', { replace: true });
        } else {
          setStatus('error');
        }
      })
      .catch(() => setStatus('error'));
  }, []);

  return (
    <div className="min-h-screen bg-page flex items-center justify-center px-4">
      <div className="w-full max-w-sm text-center">
        <a href="/" className="font-display text-4xl font-bold text-brand-600 mb-2 block" style={{ textDecoration: 'none' }}>
          Jatah<span className="text-brand-400">ku</span>
        </a>

        <div className="card mt-8">
          {status === 'loading' && (
            <>
              <div className="text-2xl mb-3">⏳</div>
              <p className="text-sm text-gray-500">Memverifikasi link login...</p>
            </>
          )}
          {status === 'error' && (
            <>
              <div className="text-2xl mb-3">❌</div>
              <p className="font-semibold text-gray-700 mb-1">Link tidak valid</p>
              <p className="text-sm text-gray-400 mb-4">Link sudah kadaluarsa atau sudah digunakan. Ketik /webapp di bot untuk mendapatkan link baru.</p>
              <a href="/login" className="btn-primary w-full block text-center">Masuk manual</a>
            </>
          )}
          {status === 'invalid' && (
            <>
              <div className="text-2xl mb-3">⚠️</div>
              <p className="font-semibold text-gray-700 mb-1">Token tidak ditemukan</p>
              <a href="/login" className="btn-primary w-full block text-center mt-4">Masuk manual</a>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
