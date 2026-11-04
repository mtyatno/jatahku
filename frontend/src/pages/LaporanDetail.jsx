import { useState, useEffect } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../lib/api';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { BREAKPOINT_DESKTOP, tampilanLaporan, bannerLaporan } from '../lib/laporanView';
import LaporanLengkap from '../components/laporan/LaporanLengkap';
import LaporanRingkas from '../components/laporan/LaporanRingkas';

export default function LaporanDetail() {
  const { id } = useParams();
  const desktop = useMediaQuery(BREAKPOINT_DESKTOP);
  const [laporan, setLaporan] = useState(null);
  const [pengaturan, setPengaturan] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let batal = false;
    setLaporan(null);
    setError('');
    api.getLaporan(id)
      .then((d) => { if (!batal) setLaporan(d); })
      .catch((e) => { if (!batal) setError(e.message); });
    // Pengaturan hanya untuk banner; gagal memuatnya tidak boleh menutup laporan.
    api.getLaporanPengaturan()
      .then((d) => { if (!batal) setPengaturan(d); })
      .catch(() => {});
    return () => { batal = true; };
  }, [id]);

  if (error) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-danger-400" role="alert">{error}</p>
        <Link to="/laporan" className="text-sm text-brand-600 font-semibold">Kembali ke daftar laporan</Link>
      </div>
    );
  }
  if (!laporan) return <div className="card h-40 animate-pulse" />;

  const banner = bannerLaporan(pengaturan);
  return (
    <div className="space-y-4">
      {banner && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 text-amber-600 px-4 py-3 text-sm">
          {banner.teks}{' '}
          <Link to={banner.tautan} className="font-semibold underline">Atur sekarang</Link>
        </div>
      )}
      {tampilanLaporan(desktop) === 'lengkap'
        ? <LaporanLengkap laporan={laporan} />
        : <LaporanRingkas laporan={laporan} />}
    </div>
  );
}
