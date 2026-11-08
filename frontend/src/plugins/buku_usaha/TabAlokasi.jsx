// Tab "Alokasi omzet" Buku Usaha (Plugin U2; 05-desain-buku-usaha.md artboard "Halaman Buku Usaha", A3: 45/30/15/9/1).
// Persen penjualan yang masuk ke tiap amplop ruang usaha; total harus 100% (dicek di sini untuk pesan cepat, ditegakkan
// server: `PUT /p/buku_usaha/alokasi` → 422 `alokasi_bukan_100`). Belum tersimpan = saran dari amplop bawaan.
import { useCallback, useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { Icon } from '../../components/Icon';
import { PLUGIN_ID, barisAlokasi, pesanUsahaGalat, totalPersen, validasiAlokasi } from './bukuUsaha';

export default function TabAlokasi({ ruangNama }) {
  const [data, setData] = useState(null);          // { baris, sisa, siap, tersimpan } | null = memuat
  const [ubah, setUbah] = useState(false);
  const [sibuk, setSibuk] = useState(false);
  const [pesan, setPesan] = useState(null);
  const [tambah, setTambah] = useState('');

  const muat = useCallback(async () => {
    const r = await api.pluginRute(PLUGIN_ID, '/alokasi');
    if (!r.ok) {
      setData(d => d || { baris: [], sisa: [], siap: false, tersimpan: false });
      setPesan({ ...pesanUsahaGalat(r.status, r.data), galat: true });
      return;
    }
    const b = barisAlokasi(r.data);
    setData(b);
    setUbah(!b.tersimpan);               // belum pernah disimpan: langsung bisa diubah dari saran
  }, []);
  useEffect(() => { muat(); }, [muat]);

  const setBaris = (fn) => setData(d => ({ ...d, baris: fn(d.baris) }));
  const ubahPersen = (id, v) => setBaris(bs => bs.map(b => (b.envelope_id === id
    ? { ...b, persen: v.replace(/[^\d.,]/g, '').slice(0, 6) } : b)));
  const buang = (id) => setData(d => {
    const b = d.baris.find(x => x.envelope_id === id);
    return { ...d, baris: d.baris.filter(x => x.envelope_id !== id), sisa: b ? [...d.sisa, { ...b, persen: '' }] : d.sisa };
  });
  const tambahkan = () => {
    if (!tambah) return;
    setData(d => {
      const a = d.sisa.find(x => x.envelope_id === tambah);
      return a ? { ...d, baris: [...d.baris, a], sisa: d.sisa.filter(x => x.envelope_id !== tambah) } : d;
    });
    setTambah('');
  };

  const simpan = async () => {
    const v = validasiAlokasi(data.baris);
    if (!v.ok) { setPesan({ teks: v.pesan, galat: true }); return; }
    setSibuk(true);
    setPesan(null);
    const r = await api.pluginRute(PLUGIN_ID, '/alokasi', 'PUT', v.body);
    setSibuk(false);
    if (!r.ok) { setPesan({ ...pesanUsahaGalat(r.status, r.data), galat: true }); return; }
    const b = barisAlokasi({ ...r.data, amplop: [...data.baris, ...data.sisa] });
    setData(b);
    setUbah(false);
    setPesan({ teks: `Alokasi omzet ${ruangNama} disimpan. Penjualan berikutnya dibagi otomatis.` });
  };

  if (!data) {
    return <section className="card !px-5 !py-6"><p className="text-sm" style={{ color: 'var(--text-muted)' }}>Memuat alokasi…</p></section>;
  }
  const total = totalPersen(data.baris);
  const pas = total === 100;

  return (
    <section className="card !px-4 md:!px-6 !py-5 min-w-0" aria-labelledby="bu-alokasi">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="bu-alokasi" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Alokasi omzet</h2>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            Setiap penjualan dibagi otomatis ke amplop ini. Modal, pinjaman, dan pemasukan lain tidak dibagi.
          </p>
        </div>
        {!ubah && data.tersimpan && (
          <button type="button" className="btn-outline !px-4 !py-2 inline-flex items-center gap-1.5" onClick={() => { setUbah(true); setPesan(null); }}>
            <Icon name="edit" size={16} /> Ubah
          </button>
        )}
      </div>

      {!data.tersimpan && data.baris.length > 0 && (
        <p className="text-sm mt-3 rounded-xl px-3 py-2" style={{ color: 'var(--text)', background: 'rgba(148,163,184,0.12)' }}>
          Saran awal untuk amplop usaha bawaan. Sesuaikan, lalu simpan supaya form penjualan bisa membagi otomatis.
        </p>
      )}
      {data.tersimpan && !data.siap && (
        <p className="text-sm mt-3 rounded-xl px-3 py-2" role="alert" style={{ color: '#92400E', background: 'rgba(245,158,11,0.14)' }}>
          Ada amplop di aturan ini yang sudah dihapus atau diarsipkan. Ubah dan simpan ulang supaya penjualan bisa dicatat.
        </p>
      )}

      {data.baris.length === 0 ? (
        <p className="text-sm mt-4 rounded-xl px-4 py-6 text-center" style={{ color: 'var(--text-muted)', background: 'rgba(148,163,184,0.08)' }}>
          Belum ada amplop di aturan ini. Tambahkan amplop usaha di bawah.
        </p>
      ) : (
        <ul className="mt-3">
          {data.baris.map(b => {
            const n = Number(String(b.persen).replace(',', '.')) || 0;
            return (
              <li key={b.envelope_id} className="py-2.5" style={{ borderTop: '1px solid var(--border)' }}>
                <div className="flex items-center gap-3">
                  <span className="flex-1 min-w-0 text-sm font-semibold truncate" style={{ color: 'var(--text)' }}>
                    {b.emoji ? `${b.emoji} ` : ''}{b.nama}
                  </span>
                  {ubah ? (
                    <>
                      <label className="flex items-center gap-1">
                        <span className="sr-only">Persen untuk {b.nama}</span>
                        <input className="input !w-20 !py-1.5 text-right tabular-nums" inputMode="decimal" value={b.persen}
                          onChange={e => ubahPersen(b.envelope_id, e.target.value)} />
                        <span className="text-sm" style={{ color: 'var(--text-muted)' }}>%</span>
                      </label>
                      <button type="button" onClick={() => buang(b.envelope_id)} aria-label={`Keluarkan ${b.nama}`}
                        className="shrink-0 w-8 h-8 rounded-lg inline-flex items-center justify-center hover:bg-black/5" style={{ color: 'var(--text-muted)' }}>
                        <Icon name="trash" size={16} />
                      </button>
                    </>
                  ) : (
                    <span className="text-sm font-semibold tabular-nums" style={{ color: 'var(--text)' }}>{b.persen}%</span>
                  )}
                </div>
                <div className="mt-1.5 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(148,163,184,0.18)' }} aria-hidden="true">
                  <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.max(0, n))}%`, background: 'var(--brand-500, #1D9E75)' }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {ubah && (
        <>
          {data.sisa.length > 0 && data.baris.length < 10 && (
            <div className="flex flex-wrap gap-2 mt-3">
              <label className="flex-1 min-w-[12rem]">
                <span className="sr-only">Amplop untuk ditambahkan</span>
                <select className="input text-sm" value={tambah} onChange={e => setTambah(e.target.value)}>
                  <option value="">Tambah amplop…</option>
                  {data.sisa.map(a => <option key={a.envelope_id} value={a.envelope_id}>{a.emoji ? `${a.emoji} ` : ''}{a.nama}</option>)}
                </select>
              </label>
              <button type="button" className="btn-outline" disabled={!tambah} onClick={tambahkan}>Tambah</button>
            </div>
          )}
          <div className="flex items-center justify-between gap-3 mt-4 rounded-xl px-3 py-2"
            style={pas ? { background: 'rgba(29,158,117,0.10)', color: 'var(--text)' } : { background: 'rgba(245,158,11,0.14)', color: '#92400E' }}
            aria-live="polite">
            <span className="text-sm font-semibold">Total</span>
            <span className="text-sm font-bold tabular-nums">
              {total.toLocaleString('id-ID')}%{pas ? '' : ` · ${total < 100 ? 'kurang' : 'lebih'} ${Math.abs(Math.round((100 - total) * 100) / 100).toLocaleString('id-ID')}%`}
            </span>
          </div>
          <div className="flex flex-wrap gap-2 mt-4">
            <button type="button" className="btn-primary disabled:opacity-50" disabled={sibuk || !pas} onClick={simpan}>
              {sibuk ? 'Menyimpan…' : 'Simpan alokasi'}
            </button>
            {data.tersimpan && (
              <button type="button" className="btn-outline" disabled={sibuk} onClick={() => { setPesan(null); muat(); }}>Batal</button>
            )}
          </div>
        </>
      )}
      {pesan && (
        <p role={pesan.galat ? 'alert' : 'status'} className="text-sm mt-3 rounded-xl px-3 py-2"
          style={pesan.galat ? { color: '#B91C1C', background: 'rgba(220,38,38,0.08)' } : { color: 'var(--text-muted)', background: 'rgba(148,163,184,0.12)' }}>
          {pesan.teks}
        </p>
      )}
    </section>
  );
}
