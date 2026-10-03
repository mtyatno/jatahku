import { useState, useEffect } from 'react';
import { useAuth } from '../hooks/useAuth';
import { api } from '../lib/api';
import { telegramPromptMode, isLinkCodeUsable } from '../lib/telegramPrompt';
import { Icon, BRAND } from './Icon';

const LAST_SHOWN_KEY = 'jatahku_tg_prompt_last_shown';

function readLastShown() {
  try {
    const v = Number(localStorage.getItem(LAST_SHOWN_KEY));
    return v > 0 ? v : null;
  } catch {
    return null;
  }
}

function markShown(now) {
  try { localStorage.setItem(LAST_SHOWN_KEY, String(now)); } catch { /* storage diblok: modal boleh muncul lagi */ }
}

function takeJustOnboarded() {
  try {
    const v = sessionStorage.getItem('just_onboarded') === '1';
    if (v) sessionStorage.removeItem('just_onboarded');
    return v;
  } catch {
    return false;
  }
}

export default function TelegramPrompt() {
  const { user } = useAuth();
  const [show, setShow] = useState(false);
  // 'connect' = ajak hubungkan Telegram; 'return' = datang dari bot, baru onboarding
  const [mode, setMode] = useState('connect');
  // ready → waiting (bot dibuka, menunggu START) → linked | expired
  const [phase, setPhase] = useState('ready');
  const [code, setCode] = useState(null);
  const [codeAt, setCodeAt] = useState(0);
  const [codeError, setCodeError] = useState(false);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const justOnboarded = takeJustOnboarded();
    const reveal = (m, delay) => setTimeout(() => {
      if (!cancelled) { setMode(m); setShow(true); }
    }, delay);

    if (user.telegram_id) {
      // Datang dari bot: setelah onboarding di web, ajak kembali ke Telegram.
      if (telegramPromptMode({ telegramLinked: true, justOnboarded }) === 'return') reveal('return', 800);
      return () => { cancelled = true; };
    }

    (justOnboarded ? Promise.resolve(null) : api.getEnvelopeSummary()).then((envs) => {
      if (cancelled) return;
      const now = Date.now();
      const m = telegramPromptMode({
        telegramLinked: false,
        hasEnvelopes: Array.isArray(envs) && envs.length > 0,
        justOnboarded,
        lastShownAt: readLastShown(),
        now,
      });
      if (m !== 'connect') return;
      markShown(now);
      reveal('connect', justOnboarded ? 800 : 500);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [user]);

  // Kode disiapkan saat modal terbuka, jadi tombolnya link t.me sungguhan:
  // window.open setelah await diblokir popup blocker di HP.
  const prepareCode = async () => {
    setCode(null);
    setCodeError(false);
    try {
      const res = await api.request('/auth/link/generate', { method: 'POST' });
      if (!res.ok) throw new Error('generate failed');
      const data = await res.json();
      setCode(data.code);
      setCodeAt(Date.now());
    } catch {
      setCodeError(true);
    }
  };

  useEffect(() => { if (show && mode === 'connect') prepareCode(); }, [show, mode]);

  // Setelah bot dibuka: cek tiap 3 detik apakah Telegram sudah tertaut,
  // berhenti saat kode kedaluwarsa.
  useEffect(() => {
    if (!show || phase !== 'waiting') return;
    const interval = setInterval(async () => {
      if (!isLinkCodeUsable(codeAt, Date.now())) {
        clearInterval(interval);
        setPhase('expired');
        return;
      }
      try {
        const res = await api.request('/auth/me');
        if (res.ok && (await res.json()).telegram_id) {
          clearInterval(interval);
          setPhase('linked');
        }
      } catch { /* jaringan putus sesaat: coba lagi di putaran berikutnya */ }
    }, 3000);
    return () => clearInterval(interval);
  }, [show, phase, codeAt]);

  const openBot = (e) => {
    if (!code || !isLinkCodeUsable(codeAt, Date.now(), 15000)) {
      e.preventDefault();
      prepareCode();
      return;
    }
    setPhase('waiting');
  };

  const retry = () => {
    setPhase('ready');
    prepareCode();
  };

  if (!show) return null;

  return (
    <div className="fixed inset-0 z-[999] flex items-center justify-center bg-black/40 backdrop-blur-sm px-4">
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 space-y-4 animate-fade-in">
        {mode === 'return' ? (
          <div className="text-center space-y-3">
            <span className="w-14 h-14 rounded-full mx-auto flex items-center justify-center" style={{ background: 'rgba(15,110,86,0.10)' }}>
              <Icon name="check" size={28} color={BRAND} />
            </span>
            <h2 className="font-display text-xl font-bold">Budget kamu siap!</h2>
            <p className="text-sm text-gray-500 leading-relaxed">
              Kembali ke Telegram dan catat pengeluaran pertamamu. Cukup kirim <span className="font-mono text-brand-600 bg-brand-50 px-1.5 py-0.5 rounded">kopi 35k</span> ke @JatahkuBot.
            </p>
            <a href="https://t.me/JatahkuBot" target="_blank" rel="noreferrer" onClick={() => setShow(false)}
              className="btn-primary w-full justify-center text-center py-3">
              Buka @JatahkuBot →
            </a>
            <button onClick={() => setShow(false)}
              className="text-sm text-gray-400 hover:text-gray-600 py-2 transition-colors">
              Nanti saja
            </button>
          </div>
        ) : phase === 'linked' ? (
          <div className="text-center space-y-3">
            <span className="w-14 h-14 rounded-full mx-auto flex items-center justify-center" style={{ background: 'rgba(15,110,86,0.10)' }}>
              <Icon name="check" size={28} color={BRAND} />
            </span>
            <h2 className="font-display text-xl font-bold">Telegram terhubung!</h2>
            <p className="text-sm text-gray-500 leading-relaxed">
              Coba kirim <span className="font-mono text-brand-600 bg-brand-50 px-1.5 py-0.5 rounded">kopi 35k</span> ke @JatahkuBot, langsung tercatat di amplopmu.
            </p>
            <button onClick={() => setShow(false)} className="btn-primary w-full justify-center text-center py-3">
              Selesai
            </button>
          </div>
        ) : (
          <>
            <div className="text-center">
              <span className="text-5xl block mb-3">📱</span>
              <h2 className="font-display text-xl font-bold mb-2">Hubungkan Telegram</h2>
              <p className="text-sm text-gray-500 leading-relaxed">
                Catat pengeluaran secepat kirim chat. Cukup ketik <span className="font-mono text-brand-600 bg-brand-50 px-1.5 py-0.5 rounded">kopi 35k</span> dan langsung tercatat!
              </p>
            </div>

            <div className="bg-gray-50 rounded-xl p-4 space-y-2">
              <div className="flex items-center gap-3 text-sm">
                <Icon name="bolt" size={18} color={BRAND} />
                <span>Catat pengeluaran dalam 3 detik</span>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <Icon name="bell" size={18} color={BRAND} />
                <span>Diingatkan tiap malam kalau lupa mencatat</span>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <Icon name="dashboard" size={18} color={BRAND} />
                <span>Ringkasan harian & mingguan</span>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <Icon name="langganan" size={18} color={BRAND} />
                <span>Sync real-time dengan WebApp</span>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              {phase === 'waiting' ? (
                <div className="text-sm text-center text-gray-600 bg-brand-50 rounded-xl px-4 py-3 space-y-1">
                  <p>Tekan <b>START</b> di Telegram. Halaman ini akan memperbarui sendiri setelah terhubung.</p>
                  <a href={`https://t.me/JatahkuBot?start=link_${code}`} target="_blank" rel="noreferrer"
                    className="text-xs text-brand-600 hover:underline">
                    Telegram belum terbuka? Buka lagi
                  </a>
                </div>
              ) : phase === 'expired' || codeError ? (
                <>
                  <p className="text-xs text-center text-gray-500">
                    {codeError ? 'Gagal menyiapkan link.' : 'Link sudah kedaluwarsa.'}
                  </p>
                  <button onClick={retry} className="btn-primary w-full justify-center text-center py-3">
                    Buat link baru
                  </button>
                </>
              ) : code ? (
                <a href={`https://t.me/JatahkuBot?start=link_${code}`} target="_blank" rel="noreferrer" onClick={openBot}
                  className="btn-primary w-full justify-center text-center py-3">
                  Hubungkan Telegram →
                </a>
              ) : (
                <button disabled className="btn-primary w-full justify-center text-center py-3 opacity-50">
                  Menyiapkan link...
                </button>
              )}
              <button onClick={() => setShow(false)}
                className="text-sm text-gray-400 hover:text-gray-600 py-2 transition-colors">
                Nanti saja
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
