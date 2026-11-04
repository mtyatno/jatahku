import { angkaUtama, trenTeks } from '../../lib/laporanView';
import UnduhPdfButton from './UnduhPdfButton';
import { periodeTeks } from './format';

// Layar ringkas untuk HP: angka utama, satu sorotan, tren, dan tombol unduh PDF selebar layar.
export default function LaporanRingkas({ laporan }) {
  const data = laporan.data || {};
  const tren = trenTeks(data.email?.tren_persen);
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-display font-bold">{laporan.judul}</h1>
        <p className="text-sm text-gray-500 mt-1">{periodeTeks(laporan.periode_mulai, laporan.periode_akhir)}</p>
      </div>
      <div className="card grid grid-cols-2 gap-3">
        {angkaUtama(data).map((a) => (
          <div key={a.label} className={a.label === 'Dibawa ke periode berikut' ? 'col-span-2' : ''}>
            <p className="text-xs text-gray-400">{a.label}</p>
            <p className="text-lg font-bold font-display">{a.nilai}</p>
          </div>
        ))}
      </div>
      {data.email?.sorotan && (
        <div className="card bg-brand-50 border-brand-100">
          <p className="text-sm text-brand-800">{data.email.sorotan}</p>
        </div>
      )}
      {tren && <p className="text-sm text-gray-600">{tren}</p>}
      <UnduhPdfButton laporan={laporan} className="[&>button]:w-full" />
    </div>
  );
}
