// Form aksi cepat "Penjualan" Buku Usaha (Plugin U2; 05-desain-buku-usaha.md artboard "Pemilih ruang, menu Catat, form
// penjualan"). Jenis pemasukan + jumlah + pelanggan (penjualan) atau amplop tujuan (jenis lain) + pratinjau pembagian.
//
// Server yang membagi dan menyimpan (`POST /p/buku_usaha/penjualan`: pemasukan inti dan jenisnya dalam satu commit);
// pratinjau dari `POST /p/buku_usaha/penjualan/pratinjau` memakai hitungan yang sama, jadi angka di layar = yang dicatat.
// Dibuka dari menu Catat ▾ dan FAB (Layout, `aksi['buku_usaha.penjualan']`); props { onDone, onCancel }.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/api';
import { Icon } from '../../components/Icon';
import {
  JENIS_PEMASUKAN, PLUGIN_ID, amplopBawaanNonPenjualan, digitSaja, pesanUsahaGalat, rapikanKontak, rupiah,
  urutkanKontak, validasiPenjualan,
} from './bukuUsaha';

function hariIniLokal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const ribuan = (digit) => (digit ? Number(digit).toLocaleString('id-ID') : '');

function TautanLanjut({ perlu, onCancel }) {
  if (perlu === 'alokasi') {
    return <Link to={`/p/${PLUGIN_ID}/alokasi`} onClick={onCancel} className="underline font-semibold">Atur alokasi omzet</Link>;
  }
  if (perlu === 'izin' || perlu === 'fitur') {
    return <Link to="/fitur-tambahan" onClick={onCancel} className="underline font-semibold">Buka Fitur Tambahan</Link>;
  }
  return null;
}

export default function FormPenjualan({ onDone, onCancel }) {
  const hariIni = useMemo(hariIniLokal, []);
  const [form, setForm] = useState({ jenis: 'penjualan', jumlah: '', kontak_id: '', envelope_id: '', tanggal: hariIni,
    keterangan: '' });
  const [pelanggan, setPelanggan] = useState([]);
  const [amplop, setAmplop] = useState([]);
  const [pratinjau, setPratinjau] = useState(null);         // { pembagian } | { galat: {teks, perlu} } | null
  const [galat, setGalat] = useState({});
  const [pesan, setPesan] = useState(null);
  const [sibuk, setSibuk] = useState(false);
  const urutPratinjau = useRef(0);

  useEffect(() => {
    let live = true;
    Promise.all([
      api.pluginRute(PLUGIN_ID, '/kontak?peran=pelanggan'),
      api.pluginRute(PLUGIN_ID, '/alokasi'),
    ]).then(([k, a]) => {
      if (!live) return;
      if (k.ok) setPelanggan(urutkanKontak(rapikanKontak(k.data)));
      if (a.ok) {
        const daftar = Array.isArray(a.data?.amplop) ? a.data.amplop : [];
        setAmplop(daftar);
        setForm(f => (f.envelope_id ? f : { ...f, envelope_id: amplopBawaanNonPenjualan(daftar) }));
      } else {
        setPesan({ ...pesanUsahaGalat(a.status, a.data), galat: true });
      }
    });
    return () => { live = false; };
  }, []);

  // Pratinjau pembagian sambil mengetik (jeda 300 ms; jawaban lama dibuang).
  useEffect(() => {
    const jumlah = digitSaja(form.jumlah);
    if (!(Number(jumlah) > 0) || (form.jenis !== 'penjualan' && !form.envelope_id)) { setPratinjau(null); return undefined; }
    const nomor = ++urutPratinjau.current;
    const t = setTimeout(async () => {
      const body = { jumlah, jenis: form.jenis, ...(form.jenis !== 'penjualan' ? { envelope_id: form.envelope_id } : {}) };
      const r = await api.pluginRute(PLUGIN_ID, '/penjualan/pratinjau', 'POST', body);
      if (nomor !== urutPratinjau.current) return;
      setPratinjau(r.ok ? { pembagian: Array.isArray(r.data?.pembagian) ? r.data.pembagian : [] }
        : { galat: pesanUsahaGalat(r.status, r.data) });
    }, 300);
    return () => clearTimeout(t);
  }, [form.jumlah, form.jenis, form.envelope_id]);

  const ubah = (k) => (e) => setForm(f => ({ ...f, [k]: k === 'jumlah' ? digitSaja(e.target.value) : e.target.value }));
  const jenis = JENIS_PEMASUKAN.find(j => j.id === form.jenis) || JENIS_PEMASUKAN[0];

  const kirim = async (e) => {
    e.preventDefault();
    if (sibuk) return;
    const v = validasiPenjualan(form, hariIni);
    setGalat(v.galat);
    if (!v.ok) return;
    setSibuk(true);                       // satu kiriman sekaligus: tombol terkunci sampai jawaban datang
    setPesan(null);
    const r = await api.pluginRute(PLUGIN_ID, '/penjualan', 'POST', v.body);
    setSibuk(false);
    if (!r.ok) {
      setPesan({ ...pesanUsahaGalat(r.status, r.data), galat: true });
      return;
    }
    const n = Array.isArray(r.data?.pembagian) ? r.data.pembagian.length : 0;
    onDone?.(`${jenis.label} ${rupiah(r.data?.jumlah)} dicatat${n > 1 ? ` dan dibagi ke ${n} amplop` : ''}.`);
  };

  return (
    <form onSubmit={kirim} aria-label="Catat pemasukan usaha" className="min-w-0">
      <fieldset>
        <legend className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Jenis pemasukan</legend>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-1">
          {JENIS_PEMASUKAN.map(j => (
            <label key={j.id} className="rounded-xl px-2 py-2 text-sm text-center cursor-pointer border"
              style={form.jenis === j.id
                ? { background: 'color-mix(in srgb, var(--brand-400) 18%, transparent)', borderColor: 'var(--brand-600)', color: 'var(--text)', fontWeight: 600 }
                : { borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
              <input type="radio" name="jenis" value={j.id} className="sr-only" checked={form.jenis === j.id} onChange={ubah('jenis')} />
              {j.label}
            </label>
          ))}
        </div>
        <p className="text-xs mt-1.5" style={{ color: 'var(--text-muted)' }}>{jenis.bantu}</p>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-2 mt-4">
        <label className="block">
          <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Jumlah</span>
          <div className="relative mt-1">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm" style={{ color: 'var(--text-muted)' }}>Rp</span>
            <input className="input !pl-9" inputMode="numeric" autoFocus value={ribuan(form.jumlah)} onChange={ubah('jumlah')}
              placeholder="0" aria-invalid={!!galat.jumlah} />
          </div>
          {galat.jumlah && <p className="text-xs mt-1" style={{ color: '#DC2626' }} role="alert">{galat.jumlah}</p>}
        </label>
        <label className="block">
          <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Tanggal</span>
          <input type="date" className="input mt-1" value={form.tanggal} max={hariIni} onChange={ubah('tanggal')} />
          {galat.tanggal && <p className="text-xs mt-1" style={{ color: '#DC2626' }} role="alert">{galat.tanggal}</p>}
        </label>
        {form.jenis === 'penjualan' ? (
          <label className="block">
            <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Pelanggan (opsional)</span>
            <select className="input mt-1" value={form.kontak_id} onChange={ubah('kontak_id')}>
              <option value="">Tanpa pelanggan</option>
              {pelanggan.map(k => <option key={k.id} value={k.id}>{k.nama}</option>)}
            </select>
            {pelanggan.length === 0 && (
              <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                Pelanggan tetap ditambahkan di <Link to={`/p/${PLUGIN_ID}`} onClick={onCancel} className="underline">Buku Usaha › Kontak</Link>.
              </p>
            )}
          </label>
        ) : (
          <label className="block">
            <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Masuk ke amplop</span>
            <select className="input mt-1" value={form.envelope_id} onChange={ubah('envelope_id')} aria-invalid={!!galat.envelope_id}>
              <option value="">Pilih amplop</option>
              {amplop.map(a => <option key={a.envelope_id} value={a.envelope_id}>{a.emoji ? `${a.emoji} ` : ''}{a.nama}</option>)}
            </select>
            {galat.envelope_id && <p className="text-xs mt-1" style={{ color: '#DC2626' }} role="alert">{galat.envelope_id}</p>}
          </label>
        )}
        <label className="block">
          <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Keterangan (opsional)</span>
          <input className="input mt-1" value={form.keterangan} onChange={ubah('keterangan')} maxLength={200}
            placeholder={form.jenis === 'penjualan' ? 'mis. nasi box 30 pax' : jenis.label} />
          {galat.keterangan && <p className="text-xs mt-1" style={{ color: '#DC2626' }} role="alert">{galat.keterangan}</p>}
        </label>
      </div>

      <section className="mt-4 rounded-2xl px-4 py-3" style={{ background: 'rgba(148,163,184,0.10)' }} aria-live="polite"
        aria-label="Pratinjau pembagian">
        <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
          {form.jenis === 'penjualan' ? 'Pembagian ke amplop' : 'Masuk ke'}
        </p>
        {!pratinjau ? (
          <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
            {form.jenis === 'penjualan' ? 'Isi jumlah untuk melihat pembagiannya.' : 'Isi jumlah dan pilih amplop.'}
          </p>
        ) : pratinjau.galat ? (
          <p className="text-sm mt-1" style={{ color: 'var(--text)' }}>
            {pratinjau.galat.teks} <TautanLanjut perlu={pratinjau.galat.perlu} onCancel={onCancel} />
          </p>
        ) : (
          <ul className="mt-1">
            {pratinjau.pembagian.map(b => (
              <li key={b.envelope_id} className="flex items-center gap-2 py-1 text-sm" style={{ color: 'var(--text)' }}>
                <span className="flex-1 min-w-0 truncate">{b.emoji ? `${b.emoji} ` : ''}{b.nama}
                  {b.persen != null && <span style={{ color: 'var(--text-muted)' }}> · {Number(b.persen).toLocaleString('id-ID')}%</span>}
                </span>
                <span className="font-semibold tabular-nums">{rupiah(b.jumlah)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {pesan && (
        <p role="alert" className="text-sm mt-3 rounded-xl px-3 py-2" style={{ color: '#B91C1C', background: 'rgba(220,38,38,0.08)' }}>
          {pesan.teks} <TautanLanjut perlu={pesan.perlu} onCancel={onCancel} />
        </p>
      )}
      <div className="flex flex-wrap gap-2 mt-4">
        <button type="submit" className="btn-primary inline-flex items-center gap-1.5 disabled:opacity-50" disabled={sibuk}>
          <Icon name="income" size={18} /> {sibuk ? 'Menyimpan…' : `Catat ${jenis.label.toLowerCase()}`}
        </button>
        <button type="button" className="btn-outline" disabled={sibuk} onClick={onCancel}>Batal</button>
      </div>
    </form>
  );
}
