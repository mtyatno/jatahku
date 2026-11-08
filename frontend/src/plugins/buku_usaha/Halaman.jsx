// Halaman Buku Usaha `/p/buku_usaha/*` (Plugin U1; 05-desain-buku-usaha.md artboard "Halaman Buku Usaha").
//
// Tab Kontak (U1, pelanggan dan pemasok) dan Alokasi omzet (U2, `TabAlokasi.jsx`). Laba rugi (U3) menyusul.
// Semua data dari `/p/buku_usaha/*` (ruang dari header, server memeriksa peran dan status plugin); di sini tampilan,
// saringan lokal, dan validasi yang sama dengan server sebelum mengirim (`bukuUsaha.js`).
import { useCallback, useEffect, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { api } from '../../lib/api';
import { Icon } from '../../components/Icon';
import TabAlokasi from './TabAlokasi';
import {
  MAKS_CATATAN, MAKS_NAMA, PERAN_KONTAK, PLUGIN_ID, bodyUbahKontak, hitungKontak, pesanKontakGalat, rapikanKontak,
  saringKontak, urutkanKontak, validasiKontak,
} from './bukuUsaha';

const TAB = [
  { id: 'kontak', label: 'Kontak' },
  { id: 'alokasi', label: 'Alokasi omzet' },
  { id: 'laba-rugi', label: 'Laba rugi', nanti: 'U3' },
];
const KOSONG = { nama: '', peran: 'pelanggan', telepon: '', catatan: '' };

function Pesan({ pesan }) {
  if (!pesan) return null;
  return (
    <p role={pesan.galat ? 'alert' : 'status'} className="text-sm mt-3 rounded-xl px-3 py-2"
      style={pesan.galat ? { color: '#B91C1C', background: 'rgba(220,38,38,0.08)' } : { color: 'var(--text-muted)', background: 'rgba(148,163,184,0.12)' }}>
      {pesan.teks}
    </p>
  );
}

function Galat({ teks }) {
  return teks ? <p className="text-xs mt-1" style={{ color: '#DC2626' }} role="alert">{teks}</p> : null;
}

// ── form kontak (tambah dan ubah) ─────────────────────────────────────────
function FormKontak({ awal = KOSONG, judul, tombol, sibuk, onSimpan, onBatal }) {
  const [form, setForm] = useState(awal);
  const [galat, setGalat] = useState({});
  const ubah = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));
  const kirim = (e) => {
    e.preventDefault();
    const v = validasiKontak(form);
    setGalat(v.galat);
    if (v.ok) onSimpan(v.body);
  };
  return (
    <form onSubmit={kirim} className="rounded-2xl px-4 py-4" style={{ background: 'rgba(148,163,184,0.10)' }} aria-label={judul}>
      <h3 className="font-semibold text-sm mb-3" style={{ color: 'var(--text)' }}>{judul}</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block sm:col-span-2">
          <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Nama</span>
          <input className="input mt-1" value={form.nama} onChange={ubah('nama')} maxLength={MAKS_NAMA} autoFocus
            placeholder="mis. Bu Sari atau UD Sumber Unggas" />
          <Galat teks={galat.nama} />
        </label>
        <fieldset>
          <legend className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Peran</legend>
          <div className="flex gap-2 mt-1">
            {PERAN_KONTAK.map(p => (
              <label key={p.id} className="flex-1 rounded-xl px-3 py-2 text-sm text-center cursor-pointer border"
                style={form.peran === p.id
                  ? { background: 'color-mix(in srgb, var(--brand-400) 18%, transparent)', borderColor: 'var(--brand-600)', color: 'var(--text)' }
                  : { borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
                <input type="radio" name="peran" value={p.id} className="sr-only" checked={form.peran === p.id} onChange={ubah('peran')} />
                {p.label}
              </label>
            ))}
          </div>
          <Galat teks={galat.peran} />
        </fieldset>
        <label className="block">
          <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Telepon (opsional)</span>
          <input className="input mt-1" value={form.telepon} onChange={ubah('telepon')} maxLength={30} inputMode="tel"
            placeholder="0812…" />
          <Galat teks={galat.telepon} />
        </label>
        <label className="block sm:col-span-2">
          <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Catatan (opsional)</span>
          <input className="input mt-1" value={form.catatan} onChange={ubah('catatan')} maxLength={MAKS_CATATAN}
            placeholder="mis. langganan nasi box tiap Jumat" />
          <Galat teks={galat.catatan} />
        </label>
      </div>
      <div className="flex flex-wrap gap-2 mt-4">
        <button type="submit" className="btn-primary disabled:opacity-50" disabled={sibuk}>{sibuk ? 'Menyimpan…' : tombol}</button>
        <button type="button" className="btn-outline" disabled={sibuk} onClick={onBatal}>Batal</button>
      </div>
    </form>
  );
}

function BarisKontak({ k, onUbah, onHapus, sibuk }) {
  const peran = PERAN_KONTAK.find(p => p.id === k.peran);
  return (
    <li className="flex items-center gap-3 py-3" style={{ borderTop: '1px solid var(--border)' }}>
      <span className="shrink-0 w-9 h-9 rounded-full inline-flex items-center justify-center text-sm font-bold"
        style={{ background: 'rgba(29,158,117,0.12)', color: 'var(--brand-600)' }} aria-hidden="true">
        {k.nama.charAt(0).toUpperCase()}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold truncate" style={{ color: 'var(--text)' }}>{k.nama}</p>
        <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
          {peran?.label}{k.telepon ? ` · ${k.telepon}` : ''}{k.catatan ? ` · ${k.catatan}` : ''}
        </p>
      </div>
      <button type="button" onClick={onUbah} disabled={sibuk} aria-label={`Ubah ${k.nama}`}
        className="shrink-0 w-8 h-8 rounded-lg inline-flex items-center justify-center hover:bg-black/5 disabled:opacity-50" style={{ color: 'var(--text-muted)' }}>
        <Icon name="edit" size={16} />
      </button>
      <button type="button" onClick={onHapus} disabled={sibuk} aria-label={`Hapus ${k.nama}`}
        className="shrink-0 w-8 h-8 rounded-lg inline-flex items-center justify-center hover:bg-black/5 disabled:opacity-50" style={{ color: 'var(--text-muted)' }}>
        <Icon name="trash" size={16} />
      </button>
    </li>
  );
}

// ── tab Kontak ────────────────────────────────────────────────────────────
function TabKontak({ ruangNama }) {
  const [semua, setSemua] = useState(null);           // null = belum dimuat
  const [peran, setPeran] = useState('');
  const [q, setQ] = useState('');
  const [mode, setMode] = useState(null);             // null | 'tambah' | { ubah: kontak } | { hapus: kontak }
  const [sibuk, setSibuk] = useState(false);
  const [pesan, setPesan] = useState(null);

  const muat = useCallback(async () => {
    const r = await api.pluginRute(PLUGIN_ID, '/kontak');
    if (r.ok) {
      setSemua(urutkanKontak(rapikanKontak(r.data)));
      setPesan(p => (p?.galat ? null : p));       // pesan sukses aksi barusan tetap tampil
    } else {
      setSemua(s => s || []);
      setPesan({ teks: pesanKontakGalat(r.status, r.data), galat: true });
    }
  }, []);
  useEffect(() => { muat(); }, [muat]);

  const jalankan = async (fn, sukses) => {
    setSibuk(true);
    setPesan(null);
    const r = await fn();
    setSibuk(false);
    if (!r.ok) {
      setPesan({ teks: pesanKontakGalat(r.status, r.data), galat: true });
      if (r.data?.kode === 'kontak_tidak_ada') await muat();
      return false;
    }
    setMode(null);
    setPesan({ teks: sukses });
    await muat();
    return true;
  };

  const tambah = (body) => jalankan(() => api.pluginRute(PLUGIN_ID, '/kontak', 'POST', body), `${body.nama} ditambahkan ke ${ruangNama}.`);
  const ubah = (lama, body) => {
    const beda = bodyUbahKontak(lama, body);
    if (!Object.keys(beda).length) { setMode(null); return Promise.resolve(true); }
    return jalankan(() => api.pluginRute(PLUGIN_ID, `/kontak/${lama.id}`, 'PATCH', beda), `${body.nama} diperbarui.`);
  };
  const hapus = (k) => jalankan(() => api.pluginRute(PLUGIN_ID, `/kontak/${k.id}`, 'DELETE'), `${k.nama} dihapus.`);

  const hitung = hitungKontak(semua);
  const tampil = saringKontak(semua, { peran, q });

  return (
    <section className="card !px-4 md:!px-6 !py-5 min-w-0" aria-labelledby="bu-kontak">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="bu-kontak" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Kontak</h2>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {hitung.pelanggan} pelanggan · {hitung.pemasok} pemasok. Pelanggan dipilih di form penjualan, pemasok di form pengeluaran.
          </p>
        </div>
        {mode !== 'tambah' && (
          <button type="button" className="btn-primary !px-4 !py-2 inline-flex items-center gap-1.5" onClick={() => { setMode('tambah'); setPesan(null); }}>
            <Icon name="plus" size={16} /> Kontak baru
          </button>
        )}
      </div>
      {mode === 'tambah' && (
        <div className="mt-4"><FormKontak judul="Kontak baru" tombol="Simpan" sibuk={sibuk} onSimpan={tambah} onBatal={() => setMode(null)} /></div>
      )}
      <div className="flex flex-wrap gap-2 mt-4">
        <div className="flex gap-1 rounded-xl p-1" style={{ background: 'rgba(148,163,184,0.12)' }} role="tablist" aria-label="Saring peran">
          {[{ id: '', label: `Semua (${hitung.semua})` }, ...PERAN_KONTAK.map(p => ({ id: p.id, label: `${p.label} (${hitung[p.id]})` }))].map(t => (
            <button key={t.id} type="button" role="tab" aria-selected={peran === t.id} onClick={() => setPeran(t.id)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold"
              style={peran === t.id ? { background: 'var(--surface)', color: 'var(--text)' } : { color: 'var(--text-muted)' }}>
              {t.label}
            </button>
          ))}
        </div>
        <label className="flex-1 min-w-[10rem] relative">
          <span className="sr-only">Cari kontak</span>
          <Icon name="search" size={16} className="absolute left-3 top-1/2 -translate-y-1/2" color="var(--text-muted)" />
          <input className="input !pl-9 text-sm" value={q} onChange={e => setQ(e.target.value)} placeholder="Cari nama atau telepon" maxLength={100} />
        </label>
      </div>
      <Pesan pesan={pesan} />
      {semua === null ? (
        <p className="text-sm mt-4" style={{ color: 'var(--text-muted)' }}>Memuat kontak…</p>
      ) : tampil.length === 0 ? (
        <p className="text-sm mt-4 rounded-xl px-4 py-6 text-center" style={{ color: 'var(--text-muted)', background: 'rgba(148,163,184,0.08)' }}>
          {semua.length === 0
            ? 'Belum ada kontak. Tambahkan pelanggan tetap dan pemasok supaya bisa dipilih saat mencatat.'
            : 'Tidak ada kontak yang cocok.'}
        </p>
      ) : (
        <ul className="mt-3">
          {tampil.map(k => (mode?.ubah?.id === k.id ? (
            <li key={k.id} className="py-3" style={{ borderTop: '1px solid var(--border)' }}>
              <FormKontak awal={{ nama: k.nama, peran: k.peran, telepon: k.telepon, catatan: k.catatan }} judul={`Ubah ${k.nama}`}
                tombol="Simpan perubahan" sibuk={sibuk} onSimpan={(body) => ubah(k, body)} onBatal={() => setMode(null)} />
            </li>
          ) : mode?.hapus?.id === k.id ? (
            <li key={k.id} className="py-3 flex flex-wrap items-center gap-2" style={{ borderTop: '1px solid var(--border)' }}>
              <span className="text-sm flex-1 min-w-[12rem]" style={{ color: 'var(--text)' }}>
                Hapus {k.nama}? Catatan penjualan dan pengeluaran yang pernah memakainya tidak berubah.
              </span>
              <button type="button" className="btn-danger !px-4 !py-2 !rounded-xl disabled:opacity-50" disabled={sibuk} onClick={() => hapus(k)}>
                {sibuk ? 'Menghapus…' : 'Hapus'}
              </button>
              <button type="button" className="btn-outline" disabled={sibuk} onClick={() => setMode(null)}>Batal</button>
            </li>
          ) : (
            <BarisKontak key={k.id} k={k} sibuk={sibuk} onUbah={() => { setMode({ ubah: k }); setPesan(null); }}
              onHapus={() => { setMode({ hapus: k }); setPesan(null); }} />
          )))}
        </ul>
      )}
    </section>
  );
}

function TabNanti({ tab }) {
  return (
    <section className="card !px-5 !py-8 text-center" role="status">
      <span className="inline-flex w-12 h-12 rounded-2xl items-center justify-center mb-3"
        style={{ background: 'rgba(148,163,184,0.14)', color: 'var(--text-muted)' }}>
        <Icon name="book" size={24} />
      </span>
      <h2 className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>{tab.label} menyusul</h2>
      <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>Bagian ini datang di pembaruan Buku Usaha berikutnya.</p>
    </section>
  );
}

export default function Halaman({ subpath = '', plugin }) {
  const { ruang } = useOutletContext() || {};
  const ruangNama = ruang?.aktif?.nama || 'ruang ini';
  const aktif = TAB.find(t => t.id === subpath.split('/')[0]) || TAB[0];
  return (
    <div className="max-w-3xl mx-auto min-w-0">
      <div className="flex items-center gap-3 mb-4">
        <span className="w-12 h-12 rounded-2xl shrink-0 inline-flex items-center justify-center"
          style={{ background: 'color-mix(in srgb, var(--brand-400) 16%, transparent)', color: 'var(--brand-600)' }} aria-hidden="true">
          <Icon name={plugin?.ikon || 'book'} size={24} />
        </span>
        <div className="min-w-0">
          <h1 className="font-display font-bold text-2xl truncate" style={{ color: 'var(--text)' }}>{plugin?.nama || 'Buku Usaha'}</h1>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{ruangNama} · Fitur Tambahan</p>
        </div>
      </div>
      <nav className="flex gap-1 mb-4 overflow-x-auto" aria-label="Bagian Buku Usaha">
        {TAB.map(t => (
          <Link key={t.id} to={`/p/${PLUGIN_ID}${t.id === 'kontak' ? '' : `/${t.id}`}`}
            aria-current={aktif.id === t.id ? 'page' : undefined}
            className="px-3 py-2 rounded-xl text-sm font-semibold whitespace-nowrap"
            style={aktif.id === t.id
              ? { background: 'color-mix(in srgb, var(--brand-400) 18%, transparent)', color: 'var(--text)' }
              : { color: 'var(--text-muted)' }}>
            {t.label}{t.nanti ? ' ·' : ''}
          </Link>
        ))}
      </nav>
      {aktif.id === 'kontak' ? <TabKontak ruangNama={ruangNama} />
        : aktif.id === 'alokasi' ? <TabAlokasi ruangNama={ruangNama} /> : <TabNanti tab={aktif} />}
    </div>
  );
}
