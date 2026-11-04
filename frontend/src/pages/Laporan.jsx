import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { periodeTeks, terbitTeks } from '../lib/laporanFormat';
import { HALAMAN_LAPORAN, isiHalaman, masihAdaHalaman, gabungLaporan } from '../lib/laporanView';

export default function Laporan() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState('');
  // Baris yang sudah diambil dari server (offset halaman berikutnya), bukan jumlah yang tampil: baris ganda dibuang.
  const [diambil, setDiambil] = useState(0);
  const [masihAda, setMasihAda] = useState(false);
  const [memuat, setMemuat] = useState(false);
  const [errorLagi, setErrorLagi] = useState('');

  useEffect(() => {
    let batal = false;
    api.getLaporanList({ limit: HALAMAN_LAPORAN, offset: 0 })
      .then((d) => {
        if (batal) return;
        const halaman = isiHalaman(d);
        setItems(halaman);
        setDiambil(halaman.length);
        setMasihAda(masihAdaHalaman(halaman));
      })
      .catch((e) => { if (!batal) setError(e.message); });
    return () => { batal = true; };
  }, []);

  const muatLagi = () => {
    if (memuat) return;
    setMemuat(true);
    setErrorLagi('');
    api.getLaporanList({ limit: HALAMAN_LAPORAN, offset: diambil })
      .then((d) => {
        const halaman = isiHalaman(d);
        setItems((lama) => gabungLaporan(lama, halaman));
        setDiambil((n) => n + halaman.length);
        setMasihAda(masihAdaHalaman(halaman));
      })
      .catch((e) => setErrorLagi(e.message))
      .finally(() => setMemuat(false));
  };

  return (
    <div className="space-y-4 max-w-3xl">
      <h1 className="text-2xl font-display font-bold">Laporan</h1>
      {error && <p className="text-sm text-danger-400" role="alert">{error}</p>}
      {!error && items === null && <div className="card h-20 animate-pulse" />}
      {items && items.length === 0 && (
        <div className="card text-center py-10">
          <p className="text-sm text-gray-500">Belum ada laporan. Laporan pertama terbit di hari gajian setelah periode berjalan tutup.</p>
        </div>
      )}
      {items && items.length > 0 && (
        <div className="space-y-2">
          {items.map((l) => (
            <Link key={l.id} to={`/laporan/${l.id}`} className="card flex items-center justify-between gap-3 hover:border-brand-200 transition-colors">
              <div className="min-w-0">
                <p className="font-semibold text-sm truncate">{l.judul}</p>
                <p className="text-xs text-gray-500 mt-0.5">{periodeTeks(l.periode_mulai, l.periode_akhir)}</p>
              </div>
              <p className="text-xs text-gray-400 shrink-0">Terbit {terbitTeks(l.terbit_at)}</p>
            </Link>
          ))}
        </div>
      )}
      {items && items.length > 0 && masihAda && (
        <button type="button" onClick={muatLagi} disabled={memuat} className="btn-outline text-sm py-2">
          {memuat ? 'Memuat…' : 'Tampilkan lebih banyak'}
        </button>
      )}
      {errorLagi && <p className="text-sm text-danger-400" role="alert">{errorLagi}</p>}
    </div>
  );
}
