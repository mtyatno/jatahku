// Halaman Fitur Tambahan (Plugin H3; 05-desain-buku-usaha.md artboard "Fitur Tambahan", A2 butir 7; ADR-P10, P11, P15).
//
// Katalog untuk ruang aktif (GET /plugins) + panel detail, bukan modal. Pemilik dan admin memasang lewat layar izin
// (daftar izin yang dilihat dikirim ke server: 409 `izin_berubah` bila manifest berubah di antaranya), menjeda,
// melanjutkan, mencopot (arsip 90 hari, tawaran ekspor), dan memulihkan. Sesudah memasang, kartu Beranda ditawarkan
// (yang `bawaan` sudah dicentang) dan ditambahkan lewat PUT /dashboard/layout. Semua aturan ditegakkan server.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useOutletContext, useSearchParams } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import { Icon } from '../components/Icon';
import { loadCache, saveCache } from '../lib/localCache';
import { cacheKeyLayout } from '../lib/dashboardRegistry';
import {
  STATUS_LABEL, aksiApi, bodyPasang, bodyTambahKartu, butuhBelumAktif, pesanGalat, tawaranKartu, tombolUntuk,
  urutkanKatalog,
} from '../lib/pluginHost';
import { EVENT_PLUGIN_BERUBAH } from '../plugins/useKontribusi';

const LABEL_TOMBOL = { pasang: 'Pasang', pulihkan: 'Pulihkan', lanjut: 'Lanjutkan', jeda: 'Jeda', copot: 'Copot' };

// Warna status per tema (kontras ≥ 4,5:1, desain A2 butir 10).
const NADA_STATUS = {
  aktif: [{ bg: '#DCFCE7', fg: '#166534' }, { bg: '#052e16', fg: '#86efac' }],
  terpasang: [{ bg: '#FEF3C7', fg: '#92400E' }, { bg: '#2d1f00', fg: '#fbbf24' }],
  dijeda: [{ bg: '#F1F5F9', fg: '#475569' }, { bg: '#1e293b', fg: '#cbd5e1' }],
  tersedia: [{ bg: '#E0E7FF', fg: '#3730A3' }, { bg: '#1e1b4b', fg: '#c7d2fe' }],
  arsip: [{ bg: '#F1F5F9', fg: '#475569' }, { bg: '#1e293b', fg: '#cbd5e1' }],
};

const tanggal = (iso) => {
  if (!iso) return '';
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('id-ID', { day: 'numeric', month: 'long', year: 'numeric' });
};

function Status({ status, gelap }) {
  const t = (NADA_STATUS[status] || NADA_STATUS.arsip)[gelap ? 1 : 0];
  return (
    <span className="shrink-0 text-[11px] font-semibold rounded-full px-2 py-0.5 whitespace-nowrap" style={{ background: t.bg, color: t.fg }}>
      {STATUS_LABEL[status] || status}
    </span>
  );
}

function Diperbaiki({ gelap }) {
  const t = NADA_STATUS.terpasang[gelap ? 1 : 0];
  return (
    <span className="shrink-0 text-[11px] font-semibold rounded-full px-2 py-0.5 whitespace-nowrap" style={{ background: t.bg, color: t.fg }}>
      Sedang diperbaiki
    </span>
  );
}

function IkonPlugin({ ikon, besar = false }) {
  return (
    <span className={`${besar ? 'w-12 h-12 rounded-2xl' : 'w-10 h-10 rounded-xl'} shrink-0 inline-flex items-center justify-center`}
      style={{ background: 'color-mix(in srgb, var(--brand-400) 16%, transparent)', color: 'var(--brand-600)' }} aria-hidden="true">
      <Icon name={ikon || 'puzzle'} size={besar ? 24 : 20} />
    </span>
  );
}

function Bagian({ judul, children }) {
  return (
    <div className="pt-4 mt-4" style={{ borderTop: '1px solid var(--border)' }}>
      <h3 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--text-muted)' }}>{judul}</h3>
      {children}
    </div>
  );
}

// Kotak pesan per tema (kontras ≥ 4,5:1 di terang dan gelap).
const KOTAK = {
  galat: [{ color: '#B91C1C', background: 'rgba(220,38,38,0.08)' }, { color: '#FCA5A5', background: 'rgba(248,113,113,0.12)' }],
  awas: [{ color: '#92400E', background: '#FEF3C7' }, { color: '#FBBF24', background: 'rgba(251,191,36,0.12)' }],
  info: [{ color: 'var(--text)', background: 'rgba(148,163,184,0.12)' }, { color: 'var(--text)', background: 'rgba(148,163,184,0.12)' }],
};
const kotak = (jenis, gelap) => KOTAK[jenis][gelap ? 1 : 0];

function Pesan({ pesan, gelap }) {
  if (!pesan) return null;
  return (
    <p role={pesan.galat ? 'alert' : 'status'} className="text-sm mt-3 rounded-xl px-3 py-2"
      style={kotak(pesan.galat ? 'galat' : 'info', gelap)}>
      {pesan.teks}
    </p>
  );
}

function Hak({ hak }) {
  if (!hak) return null;
  const teks = hak.status === 'aktif' ? `Langganan aktif${hak.sampai ? ` sampai ${tanggal(hak.sampai)}` : ''}`
    : hak.status === 'uji_coba' ? 'Gratis selama masa uji coba' : 'Gratis';
  return <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{teks}</span>;
}

// ── layar izin (pasang / pulihkan) ──────────────────────────────────────────
function LayarIzin({ p, ruangNama, butuh, pulihkan, sibuk, gelap, onSetuju, onBatal }) {
  return (
    <div>
      <h3 className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>
        {pulihkan ? `Pulihkan ${p.nama}?` : `Izinkan ${p.nama} di ${ruangNama}?`}
      </h3>
      <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
        {pulihkan ? 'Data yang diarsipkan kembali utuh. ' : ''}
        {p.izin.length ? `${p.nama} akan bisa:` : `${p.nama} tidak meminta akses ke data ruang ini.`}
      </p>
      {p.izin.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {p.izin.map(i => (
            <li key={i.kode} className="flex items-start gap-2 text-sm" style={{ color: 'var(--text)' }}>
              <Icon name="check" size={18} className="shrink-0 mt-0.5" color="var(--brand-600)" />
              <span>{i.teks}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs mt-3" style={{ color: 'var(--text-muted)' }}>
        Hanya data ruang {ruangNama}. Data ruang lain, termasuk ruang keluarga, tidak pernah terbaca, dan tidak ada data
        yang dikirim ke luar Jatahku. Kamu bisa menjeda atau mencopotnya kapan saja.
      </p>
      {butuh.length > 0 && (
        <p className="text-sm mt-3 rounded-xl px-3 py-2" style={kotak('awas', gelap)}>
          Aktifkan dulu {butuh.join(', ')} di ruang ini.
        </p>
      )}
      <div className="flex flex-wrap gap-2 mt-4">
        <button type="button" className="btn-primary disabled:opacity-50" disabled={sibuk} onClick={onSetuju}>
          {sibuk ? 'Memproses…' : pulihkan ? 'Izinkan dan pulihkan' : 'Izinkan dan pasang'}
        </button>
        <button type="button" className="btn-outline" disabled={sibuk} onClick={onBatal}>Batal</button>
      </div>
    </div>
  );
}

// ── tawaran kartu Beranda ───────────────────────────────────────────────────
function TawaranKartu({ p, sibuk, onTambah, onLewati }) {
  const [pilih, setPilih] = useState(() => tawaranKartu(p));
  const ubah = (key) => setPilih(ps => ps.map(x => (x.key === key ? { ...x, terpilih: !x.terpilih } : x)));
  const terpilih = pilih.filter(x => x.terpilih).map(x => x.key);
  return (
    <div>
      <h3 className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Tambahkan kartu ke Beranda?</h3>
      <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
        Kartu dari {p.nama} ditambahkan di bagian bawah Beranda ruang ini. Bisa diubah lagi kapan saja.
      </p>
      <ul className="mt-3 flex flex-col gap-1">
        {pilih.map(k => (
          <li key={k.key}>
            <label className="flex items-center gap-3 rounded-xl px-3 py-2 cursor-pointer hover:bg-black/5">
              <input type="checkbox" checked={k.terpilih} onChange={() => ubah(k.key)} className="w-4 h-4 accent-[var(--brand-600)]" />
              <span className="text-sm" style={{ color: 'var(--text)' }}>{k.judul}</span>
            </label>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2 mt-4">
        <button type="button" className="btn-primary disabled:opacity-50" disabled={sibuk || !terpilih.length}
          onClick={() => onTambah(terpilih)}>
          {sibuk ? 'Menyimpan…' : `Tambahkan ${terpilih.length || ''} kartu`}
        </button>
        <button type="button" className="btn-outline" disabled={sibuk} onClick={onLewati}>Lewati</button>
      </div>
    </div>
  );
}

// ── layar copot ─────────────────────────────────────────────────────────────
function LayarCopot({ p, sibuk, onCopot, onBatal }) {
  const ekspor = Array.isArray(p.ekspor) ? p.ekspor : [];
  return (
    <div>
      <h3 className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Copot {p.nama}?</h3>
      <ul className="mt-2 flex flex-col gap-1.5 text-sm" style={{ color: 'var(--text)' }}>
        <li>Menu, kartu Beranda, dan pengingatnya hilang dari ruang ini.</li>
        <li>Data {p.nama} diarsipkan 90 hari, lalu dihapus permanen. Pasang lagi sebelum itu untuk memulihkannya.</li>
        <li>Transaksi, pemasukan, dan amplop ruang ini tidak ikut terhapus.</li>
      </ul>
      <div className="mt-4 rounded-xl px-3 py-3" style={{ background: 'rgba(148,163,184,0.12)' }}>
        <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Simpan datanya dulu?</p>
        {ekspor.length ? (
          <div className="flex flex-wrap gap-2 mt-2">
            {ekspor.map(f => <a key={f.format} href={f.url} className="btn-outline text-sm">Unduh {f.format.toUpperCase()}</a>)}
          </div>
        ) : (
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            Unduhan data {p.nama} belum tersedia di versi ini. Datanya tetap tersimpan di arsip selama 90 hari.
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2 mt-4">
        <button type="button" className="btn-danger !px-5 !py-2.5 !rounded-xl disabled:opacity-50" disabled={sibuk} onClick={onCopot}>
          {sibuk ? 'Memproses…' : `Copot ${p.nama}`}
        </button>
        <button type="button" className="btn-outline" disabled={sibuk} onClick={onBatal}>Batal</button>
      </div>
    </div>
  );
}

// ── panel detail ────────────────────────────────────────────────────────────
function Panel({ p, katalog, ruangNama, rid, gelap, onBerubah }) {
  const { user } = useAuth();
  const [langkah, setLangkah] = useState(null);     // null | 'izin' | 'pulihkan' | 'kartu' | 'copot'
  const [sibuk, setSibuk] = useState(false);
  const [pesan, setPesan] = useState(null);

  useEffect(() => { setLangkah(null); setPesan(null); }, [p.id]);

  const jalankan = async (tombol, body) => {
    if (!rid) return null;
    setSibuk(true);
    setPesan(null);
    const r = await api.aksiPlugin(rid, p.id, aksiApi(tombol), body);
    setSibuk(false);
    if (!r.ok) {
      setPesan({ teks: pesanGalat(r.status, r.data), galat: true });
      if (r.data?.kode === 'izin_berubah') await onBerubah();     // tampilkan daftar izin terbaru
      return null;
    }
    await onBerubah();
    window.dispatchEvent(new CustomEvent(EVENT_PLUGIN_BERUBAH));
    return r.data;
  };

  const setuju = async () => {
    const pulih = langkah === 'pulihkan';
    const hasil = await jalankan(pulih ? 'pulihkan' : 'pasang', bodyPasang(p));
    if (!hasil) return;
    if (hasil.status === 'aktif' && tawaranKartu(p).length) {
      setLangkah('kartu');
      return;
    }
    setLangkah(null);
    setPesan({ teks: hasil.status === 'terpasang'
      ? `${p.nama} terpasang. Selesaikan pengaturannya untuk mulai memakai.`
      : `${p.nama} ${pulih ? 'dipulihkan' : 'terpasang'} di ${ruangNama}.` });
  };

  const tambahKartu = async (keys) => {
    setSibuk(true);
    let hasil = { ok: false };
    for (let coba = 0; coba < 2 && !hasil.ok; coba += 1) {
      const [layout, defs] = await Promise.all([api.getDashboardLayout(), api.kartuBeranda()]);
      if (!layout || !defs.ok) break;
      const body = bodyTambahKartu(layout, keys, defs.data);
      if (!body) { hasil = { ok: true }; break; }
      const r = await api.simpanTataLetak(body);
      if (r.ok) {
        if (user?.id && r.data?.layout) saveCache(cacheKeyLayout(user.id), { ...r.data.layout, enabled: layout.enabled });
        hasil = { ok: true };
      } else if (r.data?.kode !== 'versi_beda') {
        hasil = { ok: false, pesan: pesanGalat(r.status, r.data) };
        break;
      }
    }
    setSibuk(false);
    setLangkah(null);
    setPesan(hasil.ok
      ? { teks: `${p.nama} terpasang. Kartunya ada di bagian bawah Beranda.` }
      : { teks: hasil.pesan || 'Kartu belum bisa ditambahkan. Coba lagi dari Beranda nanti.', galat: true });
  };

  const tekan = async (tombol) => {
    if (tombol === 'pasang') { setLangkah('izin'); setPesan(null); return; }
    if (tombol === 'pulihkan') { setLangkah('pulihkan'); setPesan(null); return; }
    if (tombol === 'copot') { setLangkah('copot'); setPesan(null); return; }
    const hasil = await jalankan(tombol);
    if (!hasil) return;
    setPesan({ teks: tombol === 'jeda'
      ? `${p.nama} dijeda. Menu dan kartunya disembunyikan; datanya tetap tersimpan dan bisa dilanjutkan kapan saja.`
      : `${p.nama} aktif lagi di ${ruangNama}.` });
  };

  const copot = async () => {
    const hasil = await jalankan('copot');
    if (!hasil) return;
    setLangkah(null);
    setPesan({ teks: `${p.nama} dicopot. Datanya diarsipkan sampai ${tanggal(hasil.arsip_sampai)}; pasang lagi sebelum itu untuk memulihkannya.` });
  };

  const butuh = butuhBelumAktif(p, katalog);
  const tombol = tombolUntuk(p);

  return (
    <section className="card !px-5 md:!px-6 !py-5 min-w-0" aria-labelledby={`fitur-${p.id}`}>
      <div className="flex items-start gap-3">
        <IkonPlugin ikon={p.ikon} besar />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={`fitur-${p.id}`} className="font-display font-bold text-xl" style={{ color: 'var(--text)' }}>{p.nama}</h2>
            <Status status={p.status} gelap={gelap} />
            {p.diperbaiki && <Diperbaiki gelap={gelap} />}
          </div>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            Versi {p.versi} · <Hak hak={p.hak} />
          </p>
        </div>
      </div>
      <p className="text-sm mt-3" style={{ color: 'var(--text)' }}>{p.deskripsi}</p>

      {p.diperbaiki && (
        <p className="text-sm mt-3 rounded-xl px-3 py-2" style={kotak('awas', gelap)}>
          {p.nama} sedang diperbaiki tim Jatahku. Menu dan kartunya disembunyikan sementara; datamu aman.
        </p>
      )}
      {p.status === 'arsip' && p.arsip_sampai && (
        <p className="text-sm mt-3" style={{ color: 'var(--text-muted)' }}>
          Dicopot. Datanya diarsipkan sampai {tanggal(p.arsip_sampai)}, lalu dihapus permanen.
        </p>
      )}

      {langkah === 'izin' || langkah === 'pulihkan' ? (
        <Bagian judul="Izin">
          <LayarIzin p={p} ruangNama={ruangNama} butuh={butuh} pulihkan={langkah === 'pulihkan'} sibuk={sibuk} gelap={gelap}
            onSetuju={setuju} onBatal={() => setLangkah(null)} />
        </Bagian>
      ) : langkah === 'kartu' ? (
        <Bagian judul="Kartu Beranda">
          <TawaranKartu p={p} sibuk={sibuk} onTambah={tambahKartu}
            onLewati={() => { setLangkah(null); setPesan({ teks: `${p.nama} terpasang di ${ruangNama}.` }); }} />
        </Bagian>
      ) : langkah === 'copot' ? (
        <Bagian judul="Copot">
          <LayarCopot p={p} sibuk={sibuk} onCopot={copot} onBatal={() => setLangkah(null)} />
        </Bagian>
      ) : (
        <>
          {p.kartu.length > 0 && (
            <Bagian judul="Yang ditambahkan">
              <ul className="flex flex-col gap-1.5">
                {p.kartu.map(k => (
                  <li key={k.key} className="flex items-center gap-2 text-sm" style={{ color: 'var(--text)' }}>
                    <Icon name="grid" size={16} color="var(--text-muted)" /> Kartu Beranda “{k.judul}”
                  </li>
                ))}
              </ul>
            </Bagian>
          )}
          <Bagian judul={p.izin_diberikan.length ? 'Izin yang sudah diberikan' : 'Izin yang diminta'}>
            {p.izin.length === 0 ? (
              <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Tidak meminta akses ke data ruang.</p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {p.izin.map(i => (
                  <li key={i.kode} className="flex items-start gap-2 text-sm" style={{ color: 'var(--text)' }}>
                    <Icon name="lock" size={16} className="shrink-0 mt-0.5" color="var(--text-muted)" /> {i.teks}
                  </li>
                ))}
              </ul>
            )}
          </Bagian>
          {butuh.length > 0 && p.status === 'tersedia' && (
            <Bagian judul="Butuh">
              <p className="text-sm" style={{ color: 'var(--text)' }}>Aktifkan dulu {butuh.join(', ')} di ruang ini.</p>
            </Bagian>
          )}
          <Bagian judul="Data">
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
              Saat dijeda, data tetap tersimpan dan menu serta kartunya disembunyikan. Saat dicopot, data diarsipkan 90 hari
              lalu dihapus permanen; data inti ruang ini tidak pernah ikut terhapus.
            </p>
          </Bagian>
          {tombol.length > 0 ? (
            <div className="flex flex-wrap gap-2 mt-5">
              {tombol.map((t, i) => (
                <button key={t} type="button" disabled={sibuk || !rid} onClick={() => tekan(t)}
                  className={`${i === 0 && t !== 'copot' && t !== 'jeda' ? 'btn-primary' : 'btn-outline'} disabled:opacity-50`}>
                  {sibuk ? '…' : LABEL_TOMBOL[t]}
                </button>
              ))}
            </div>
          ) : !p.boleh_kelola && (
            <p className="text-sm mt-5" style={{ color: 'var(--text-muted)' }}>
              Hanya pemilik dan admin ruang ini yang bisa memasang, menjeda, atau mencopot Fitur Tambahan.
            </p>
          )}
        </>
      )}
      <Pesan pesan={pesan} gelap={gelap} />
    </section>
  );
}

export default function FiturTambahan() {
  const { ruang } = useOutletContext() || {};
  const [cari] = useSearchParams();
  const { mode } = useTheme();
  const gelap = mode === 'dark';
  const rid = ruang?.aktif?.id ?? null;
  const ruangNama = ruang?.aktif?.nama || 'ruang ini';
  const [katalog, setKatalog] = useState(() => loadCache('plugin_katalog'));
  const [galat, setGalat] = useState('');
  const [pilih, setPilih] = useState(() => cari.get('pilih'));
  const panelRef = useRef(null);

  const muat = useCallback(async () => {
    const r = await api.katalogPlugin();
    if (r.ok && Array.isArray(r.data)) {
      setKatalog(r.data);
      saveCache('plugin_katalog', r.data);
      setGalat('');
    } else if (r.status !== 0) {
      setGalat(pesanGalat(r.status, r.data));
    } else {
      setKatalog(k => k || []);
      setGalat('Koneksi terputus. Daftar ini mungkin belum terbaru.');
    }
  }, []);

  useEffect(() => { muat(); }, [muat]);

  const pilihPlugin = (id) => {
    setPilih(id);
    if (window.innerWidth < 1024) setTimeout(() => panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
  };

  const urut = urutkanKatalog(katalog);
  const dipilih = urut.find(p => p.id === pilih) || urut[0] || null;

  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          <Link to="/settings" className="hover:underline">Pengaturan</Link> › Fitur Tambahan
        </p>
        <h1 className="font-display font-bold text-2xl" style={{ color: 'var(--text)' }}>Fitur Tambahan</h1>
        <p className="text-sm mt-0.5" style={{ color: 'var(--text-muted)' }}>
          Untuk ruang {ruangNama}. Fitur Tambahan menambah menu, kartu Beranda, dan pencatatan khusus; amplop dan transaksi
          ruang ini tetap seperti biasa.
        </p>
      </div>

      {galat && <Pesan pesan={{ teks: galat, galat: true }} gelap={gelap} />}

      {katalog === null ? (
        <div className="text-center py-12 text-gray-400">Loading...</div>
      ) : urut.length === 0 ? (
        <div className="card !p-6 max-w-xl">
          <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Belum ada Fitur Tambahan untuk ruang ini.</p>
          <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
            Fitur Tambahan baru muncul di sini saat tersedia untuk jenis ruang ini.
          </p>
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)] items-start">
          <ul className="flex flex-col gap-2 min-w-0" aria-label="Katalog Fitur Tambahan">
            {urut.map(p => {
              const aktif = p.id === dipilih?.id;
              return (
                <li key={p.id}>
                  <button type="button" onClick={() => pilihPlugin(p.id)} aria-current={aktif ? 'true' : undefined}
                    className="card !p-4 w-full text-left flex items-start gap-3 transition-colors"
                    style={aktif ? { boxShadow: 'inset 0 0 0 1.5px var(--brand-400)' } : undefined}>
                    <IkonPlugin ikon={p.ikon} />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-sm" style={{ color: 'var(--text)' }}>{p.nama}</span>
                        <Status status={p.status} gelap={gelap} />
                        {p.diperbaiki && <Diperbaiki gelap={gelap} />}
                      </span>
                      <span className="block text-xs mt-1 line-clamp-2" style={{ color: 'var(--text-muted)' }}>{p.deskripsi}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <div ref={panelRef} className="min-w-0 scroll-mt-20">
            {dipilih && <Panel p={dipilih} katalog={urut} ruangNama={ruangNama} rid={rid} gelap={gelap} onBerubah={muat} />}
          </div>
        </div>
      )}
    </div>
  );
}
