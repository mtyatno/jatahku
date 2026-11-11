import { useState, useEffect } from 'react';
import { api } from '../../lib/api';
import { barisKartu, teksAlarm, PESAN_GAGAL_MUAT } from '../../lib/emailLaporanView';

const WARNA = { baik: 'text-brand-600', biasa: '', bahaya: 'text-danger-600' };

// Kartu status antrean email laporan; memuat sendiri, galatnya hanya menampilkan pesan di kartu ini.
export default function EmailLaporanCard() {
  const [status, setStatus] = useState('memuat');
  const [data, setData] = useState(null);

  useEffect(() => {
    let batal = false;
    api.adminEmailLaporan()
      .then((res) => {
        if (batal) return;
        if (res?.ok && res.data) { setData(res.data); setStatus('siap'); } else setStatus('gagal');
      })
      .catch(() => { if (!batal) setStatus('gagal'); });
    return () => { batal = true; };
  }, []);

  let isi;
  if (status === 'memuat') {
    isi = <div className="space-y-2" aria-hidden="true"><div className="h-4 w-1/2 rounded bg-gray-100 animate-pulse" /><div className="h-4 w-2/3 rounded bg-gray-100 animate-pulse" /></div>;
  } else if (status === 'gagal') {
    isi = <p className="text-sm text-gray-400">{PESAN_GAGAL_MUAT}</p>;
  } else {
    const alarm = (data.alarm || []).map((kode) => ({ kode, teks: teksAlarm(kode) })).filter((a) => a.teks);
    isi = (
      <>
        {alarm.length > 0 && (
          <ul className="mb-3 space-y-1">
            {alarm.map((a) => (
              <li key={a.kode} className="text-xs font-medium px-2 py-1 rounded-lg bg-amber-50 text-amber-600">{a.teks}</li>
            ))}
          </ul>
        )}
        <dl className="text-sm space-y-1.5">
          {barisKartu(data).map((b) => (
            <div key={b.label} className="flex justify-between gap-3">
              <dt className="text-gray-400 shrink-0">{b.label}</dt>
              <dd className={`font-medium text-right ${WARNA[b.nada] || ''}`}>{b.nilai}</dd>
            </div>
          ))}
        </dl>
      </>
    );
  }

  return (
    <div className="card">
      <h3 className="font-semibold text-sm mb-3">Email laporan</h3>
      {isi}
    </div>
  );
}
