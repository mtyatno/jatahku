import { useState } from 'react';
import { api } from '../../lib/api';

// Form kata sandi laporan (6–64 karakter). Dipakai di Pengaturan dan di dialog "Unduh PDF".
export default function KataSandiForm({ label = 'Atur kata sandi', onSaved, onCancel }) {
  const [kataSandi, setKataSandi] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await api.simpanLaporanPengaturan({ kata_sandi: kataSandi });
      setKataSandi('');
      onSaved?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <label htmlFor="laporan-kata-sandi" className="text-sm text-gray-600">Kata sandi laporan</label>
        <input
          id="laporan-kata-sandi"
          className="input text-sm mt-1"
          type="password"
          autoComplete="new-password"
          minLength={6}
          maxLength={64}
          required
          value={kataSandi}
          onChange={(e) => setKataSandi(e.target.value)}
        />
        <p className="text-xs text-gray-400 mt-1">6–64 karakter. PDF laporan dikunci dengan kata sandi ini.</p>
      </div>
      {error && <p className="text-sm text-danger-400" role="alert">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || kataSandi.length < 6} className="btn-primary text-sm py-2 disabled:opacity-50">
          {busy ? 'Menyimpan...' : label}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} disabled={busy} className="btn-secondary text-sm py-2 disabled:opacity-50">
            Batal
          </button>
        )}
      </div>
    </form>
  );
}
