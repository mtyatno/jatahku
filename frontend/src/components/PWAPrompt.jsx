import { useState, useEffect } from 'react';

// Offline banner shown when network is lost
export function OfflineBanner() {
  const [offline, setOffline] = useState(!navigator.onLine);

  useEffect(() => {
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off); };
  }, []);

  if (!offline) return null;
  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 9999,
      background: '#1f2937', color: '#fff', textAlign: 'center',
      padding: '8px 16px', fontSize: '13px', fontWeight: 500,
      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
    }}>
      <span>📵</span>
      <span>Tidak ada koneksi — transaksi akan tersimpan sementara</span>
    </div>
  );
}

// Install prompt shown on supporting browsers
export function InstallPrompt() {
  const [prompt, setPrompt] = useState(null);
  const [shown, setShown] = useState(false);
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem('pwa-dismissed') === '1'
  );

  useEffect(() => {
    const handler = (e) => {
      e.preventDefault();
      setPrompt(e);
      setShown(true);
    };
    window.addEventListener('beforeinstallprompt', handler);
    return () => window.removeEventListener('beforeinstallprompt', handler);
  }, []);

  if (!shown || dismissed || !prompt) return null;

  const install = async () => {
    prompt.prompt();
    const { outcome } = await prompt.userChoice;
    if (outcome === 'accepted') setShown(false);
    setPrompt(null);
  };

  const dismiss = () => {
    setDismissed(true);
    localStorage.setItem('pwa-dismissed', '1');
  };

  return (
    <div style={{
      position: 'fixed', bottom: '80px', left: '50%', transform: 'translateX(-50%)',
      zIndex: 9000, width: 'min(360px, calc(100vw - 32px)',
      background: '#fff', borderRadius: '16px', padding: '16px 20px',
      boxShadow: '0 8px 32px rgba(0,0,0,0.15)', border: '1px solid #E8E8E4',
      display: 'flex', alignItems: 'center', gap: '12px',
    }}>
      <img src="/icon-192.svg" alt="" width="44" height="44" style={{ borderRadius: '10px', flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: '14px', color: '#2C2C2A' }}>Install Jatahku</div>
        <div style={{ fontSize: '12px', color: '#5F5E5A', marginTop: '2px' }}>Akses cepat dari home screen</div>
      </div>
      <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
        <button
          onClick={dismiss}
          style={{ padding: '6px 10px', borderRadius: '8px', border: '1px solid #E8E8E4', background: 'none', fontSize: '13px', cursor: 'pointer', color: '#5F5E5A' }}
        >Nanti</button>
        <button
          onClick={install}
          style={{ padding: '6px 14px', borderRadius: '8px', border: 'none', background: '#0F6E56', color: '#fff', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
        >Install</button>
      </div>
    </div>
  );
}
