import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export default function TelegramPrompt() {
  const { user } = useAuth();
  const [show, setShow] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (user && !user.telegram_id) {
      const timer = setTimeout(() => setShow(true), 500);
      return () => clearTimeout(timer);
    }
  }, [user]);

  if (!show) return null;

  return (
    <div className="fixed inset-0 z-[999] flex items-center justify-center bg-black/40 backdrop-blur-sm px-4">
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 space-y-4 animate-fade-in">
        <div className="text-center">
          <span className="text-5xl block mb-3">📱</span>
          <h2 className="font-display text-xl font-bold mb-2">Hubungkan Telegram</h2>
          <p className="text-sm text-gray-500 leading-relaxed">
            Dengan menghubungkan Telegram, kamu bisa catat pengeluaran secepat kirim chat.
            Cukup ketik <span className="font-mono text-brand-600 bg-brand-50 px-1.5 py-0.5 rounded">kopi 35k</span> dan langsung tercatat!
          </p>
        </div>

        <div className="bg-gray-50 rounded-xl p-4 space-y-2">
          <div className="flex items-center gap-3 text-sm">
            <span className="text-lg">⚡</span>
            <span>Catat pengeluaran dalam 3 detik</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-lg">🔔</span>
            <span>Notifikasi budget & langganan otomatis</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-lg">📊</span>
            <span>Ringkasan harian & mingguan</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-lg">🔄</span>
            <span>Sync real-time dengan WebApp</span>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <button onClick={() => { setShow(false); navigate('/settings'); }}
            className="btn-primary w-full justify-center text-center py-3">
            Hubungkan Sekarang →
          </button>
          <button onClick={() => setShow(false)}
            className="text-sm text-gray-400 hover:text-gray-600 py-2 transition-colors">
            Nanti saja
          </button>
        </div>
      </div>
    </div>
  );
}
