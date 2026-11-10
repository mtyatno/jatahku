// Wizard pasang Buku Usaha (Plugin U1; 03-workflow.md baris U1 "wizard pasang dengan 5 amplop bawaan").
//
// Tampil di halaman Fitur Tambahan sesudah pasang (status `terpasang`, manifest `setup: true`). Amplop bawaan ruang
// usaha (Bahan, Operasional, Prive, Laba ditahan, Pajak) dibuat lewat `POST /envelopes/` inti atas nama user yang
// memasang — plugin tidak menulis data inti (U1). Nama boleh diubah, centang boleh dilepas; yang sudah ada di ruang
// dilewati. Sesudahnya `lanjut` → plugin aktif. "Lewati" = langsung `lanjut` tanpa amplop baru.
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { PLUGIN_ID, barisWizard, digitSaja, rencanaAmplop } from './bukuUsaha';

const ribuan = (t) => (t ? Number(t).toLocaleString('id-ID') : '');

export default function Wizard({ ruangNama, sibuk, onSelesai, onLewati }) {
  const [baris, setBaris] = useState(null);
  const [galat, setGalat] = useState('');
  const [proses, setProses] = useState(false);

  const [namaAda, setNamaAda] = useState([]);

  useEffect(() => {
    let hidup = true;
    (async () => {
      // Daftar amplop bawaan dan mana yang sudah ada datang dari server (rute GET terbuka saat `terpasang`); nama
      // semua amplop bersama ruang dibaca dari inti supaya nama yang diketik user tidak kembar.
      const [peng, amplop] = await Promise.all([api.pluginRute(PLUGIN_ID, '/pengaturan'), api.getEnvelopes()]);
      if (!hidup) return;
      if (!peng.ok) { setGalat(peng.status === 0 ? 'Koneksi terputus. Coba lagi.' : 'Pengaturan belum bisa dibaca. Lewati, lalu buka Buku Usaha.'); }
      setBaris(barisWizard(peng.ok ? peng.data : null));
      setNamaAda((Array.isArray(amplop) ? amplop : []).filter(e => !e.owner_id && e.is_active !== false).map(e => e.name));
    })();
    return () => { hidup = false; };
  }, []);

  const ubah = (i, isi) => setBaris(b => b.map((x, j) => (j === i ? { ...x, ...isi } : x)));

  const buat = async () => {
    const { rencana, kurang } = rencanaAmplop(baris, namaAda);
    if (kurang.length) {
      setGalat(`Isi anggaran bulanan untuk ${kurang.join(', ')}, atau lepaskan centangnya.`);
      return;
    }
    setProses(true);
    setGalat('');
    const gagal = [];
    for (const body of rencana) {
      try {
        const r = await api.createEnvelope(body);
        if (!r.ok) gagal.push(`${body.name}${typeof r.data?.detail === 'string' ? ` (${r.data.detail})` : ''}`);
      } catch {
        gagal.push(body.name);
      }
    }
    setProses(false);
    if (gagal.length) {
      setGalat(`Amplop belum dibuat: ${gagal.join(', ')}. Coba lagi, atau lewati dan buat dari menu Amplop.`);
      return;
    }
    window.dispatchEvent(new CustomEvent('jatahku:envelope-updated'));
    await onSelesai(rencana.length);
  };

  const { rencana: terpilih, kurang } = baris ? rencanaAmplop(baris, namaAda) : { rencana: [], kurang: [] };
  const macet = sibuk || proses;

  return (
    <div>
      <h3 className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Siapkan amplop usaha di {ruangNama}</h3>
      <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
        Buku Usaha membagi omzet ke amplop ini (persentasenya diatur nanti di tab Alokasi omzet). Nama boleh diubah;
        yang sudah ada di ruang ini dilewati. Amplop belanja (Bahan, Operasional) butuh perkiraan anggaran sebulan;
        cadangan (Prive, Laba ditahan, Pajak) terisi dari omzet.
      </p>
      {baris === null ? (
        <p className="text-sm mt-3" style={{ color: 'var(--text-muted)' }}>Memeriksa amplop yang sudah ada…</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {baris.map((b, i) => (
            <li key={b.kunci} className="flex items-center gap-3 rounded-xl px-3 py-2" style={{ background: 'rgba(148,163,184,0.10)' }}>
              <input type="checkbox" checked={b.ada || b.pilih} disabled={b.ada || macet} onChange={e => ubah(i, { pilih: e.target.checked })}
                aria-label={`Buat amplop ${b.nama}`} />
              <span className="text-lg" aria-hidden="true">{b.emoji}</span>
              <div className="min-w-0 flex-1 grid gap-1 sm:grid-cols-[1fr_9rem]">
                <input className="input !py-1 text-sm" value={b.nama} disabled={b.ada || macet} maxLength={50}
                  onChange={e => ubah(i, { nama: e.target.value })} aria-label={`Nama amplop ${b.kunci}`} />
                {b.tujuan === 'expense' && !b.ada ? (
                  <label className="relative">
                    <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs" style={{ color: 'var(--text-muted)' }}>Rp</span>
                    <input className="input !py-1 !pl-7 text-sm" value={ribuan(b.anggaran)} disabled={!b.pilih || macet} inputMode="numeric"
                      placeholder="anggaran/bulan" onChange={e => ubah(i, { anggaran: digitSaja(e.target.value) })}
                      aria-label={`Anggaran bulanan ${b.kunci}`} />
                  </label>
                ) : (
                  <span className="text-xs self-center" style={{ color: 'var(--text-muted)' }}>{b.ada ? '' : 'Cadangan'}</span>
                )}
                <p className="text-xs truncate sm:col-span-2" style={{ color: 'var(--text-muted)' }}>
                  {b.ada ? 'Sudah ada di ruang ini' : b.keterangan}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
      {galat && <p role="alert" className="text-sm mt-3" style={{ color: '#DC2626' }}>{galat}</p>}
      <div className="flex flex-wrap gap-2 mt-4">
        <button type="button" className="btn-primary disabled:opacity-50" disabled={macet || baris === null} onClick={buat}>
          {proses ? 'Membuat amplop…'
            : terpilih.length + kurang.length ? `Buat ${terpilih.length + kurang.length} amplop dan mulai` : 'Mulai tanpa amplop baru'}
        </button>
        <button type="button" className="btn-outline" disabled={macet} onClick={onLewati}>Lewati</button>
      </div>
    </div>
  );
}
