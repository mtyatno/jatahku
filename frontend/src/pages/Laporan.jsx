import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { periodeTeks, terbitTeks } from '../components/laporan/format';

export default function Laporan() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let batal = false;
    api.getLaporanList()
      .then((d) => { if (!batal) setItems(Array.isArray(d) ? d : (d?.items || [])); })
      .catch((e) => { if (!batal) setError(e.message); });
    return () => { batal = true; };
  }, []);

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
    </div>
  );
}
