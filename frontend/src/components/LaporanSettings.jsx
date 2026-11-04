import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import KataSandiForm from './laporan/KataSandiForm';

// Kartu pengaturan laporan (tahap 1): hanya kata sandi PDF yang bisa diubah.
export default function LaporanSettings() {
  const [pengaturan, setPengaturan] = useState(null);
  const [error, setError] = useState('');
  const [edit, setEdit] = useState(false);
  const [sukses, setSukses] = useState('');

  const muat = () => api.getLaporanPengaturan().then(setPengaturan).catch((e) => setError(e.message));
  useEffect(() => { muat(); }, []);

  // Tautan "/settings#laporan" dari banner: halaman SPA tidak menggulir ke jangkar sendiri.
  useEffect(() => {
    if (window.location.hash === '#laporan') {
      document.getElementById('laporan')?.scrollIntoView({ block: 'start' });
    }
  }, []);

  const tersimpan = () => {
    setEdit(false);
    setSukses('Kata sandi laporan disimpan');
    setTimeout(() => setSukses(''), 3000);
    muat();
  };

  if (error) return <p className="text-sm text-danger-400">{error}</p>;
  if (!pengaturan) return <div className="h-12 animate-pulse rounded-lg bg-gray-100" />;
  const diatur = !!pengaturan.kata_sandi_diatur;
  const label = diatur ? 'Ganti kata sandi' : 'Atur kata sandi';
  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-600">
        {diatur ? 'Kata sandi laporan sudah diatur.' : 'Belum ada kata sandi laporan.'}
      </p>
      {!edit ? (
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setEdit(true)} className="btn-outline text-sm py-2">{label}</button>
          {sukses && <span className="text-xs text-brand-600 animate-pulse">{sukses}</span>}
        </div>
      ) : (
        <KataSandiForm label={label} onSaved={tersimpan} onCancel={() => setEdit(false)} />
      )}
    </div>
  );
}
