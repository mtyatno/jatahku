// Tab "Laba rugi" Buku Usaha (Plugin U3; 05-desain-buku-usaha.md artboard "Halaman Buku Usaha": vs bulan lalu, bagian
// "Di luar laba rugi"; A2 no. 9: per bulan kalender). Semua angka dan rasio dari `GET /p/buku_usaha/laba-rugi`
// (`metrics.py`, aturan 6); di sini hanya format. Laporan PDF/CSV dibuat server (`GET /p/buku_usaha/laporan`) dan
// disimpan lewat `api.unduhPluginRute`, tidak pernah dibuka di tab aplikasi.
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/api';
import { Icon } from '../../components/Icon';
import {
  BELUM_BERAKUN, PLUGIN_ID, labelPeriode, pathLaporan, persenRasio, pesanLabaRugiGalat, pilihanPeriode,
  rapikanLabaRugi, rupiah, tanggalPendek,
} from './bukuUsaha';

function hariIniLokal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Warna yang terbaca di tema terang dan gelap: merah dicampur warna teks tema (lebih gelap di terang, lebih
// terang di gelap); hijau memakai --brand-600 milik tema.
const MERAH = 'color-mix(in srgb, #DC2626 60%, var(--text))';
const HIJAU = 'var(--brand-600)';
const negatif = (v) => Number(v) < 0;

// Perubahan dari bulan lalu. `naikBaik` false untuk beban (beban naik = kabar buruk).
function Perubahan({ p, naikBaik = true, bulanLalu }) {
  if (!p) return <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{bulanLalu ? `${bulanLalu}: belum ada` : ''}</span>;
  const baik = p.arah === 'tetap' ? null : (p.arah === 'naik') === naikBaik;
  const gaya = baik === null
    ? { color: 'var(--text-muted)', background: 'rgba(148,163,184,0.14)' }
    : baik
      ? { color: HIJAU, background: 'color-mix(in srgb, var(--brand-400) 14%, transparent)' }
      : { color: MERAH, background: 'rgba(220,38,38,0.10)' };
  return (
    <span className="inline-flex items-center gap-1 text-xs font-semibold rounded-full px-2 py-0.5 tabular-nums" style={gaya}>
      {p.arah !== 'tetap' && <Icon name="trendup" size={12} style={p.arah === 'turun' ? { transform: 'scaleY(-1)' } : undefined} />}
      {p.teks}{bulanLalu ? <span className="font-normal">dari {bulanLalu}</span> : null}
    </span>
  );
}

function Kpi({ label, nilai, sub, perubahan, naikBaik, bulanLalu, utama = false }) {
  return (
    <div className="rounded-2xl px-4 py-3 min-w-0"
      style={utama ? { background: 'color-mix(in srgb, var(--brand-400) 14%, transparent)' } : { background: 'rgba(148,163,184,0.10)' }}>
      <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>{label}</p>
      <p className="font-display font-bold text-xl tabular-nums truncate mt-0.5" style={{ color: negatif(nilai) ? MERAH : 'var(--text)' }}>
        {rupiah(nilai)}
      </p>
      {sub && <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{sub}</p>}
      <div className="mt-2"><Perubahan p={perubahan} naikBaik={naikBaik} bulanLalu={bulanLalu} /></div>
    </div>
  );
}

export default function TabLabaRugi({ ruangNama }) {
  const hariIni = useMemo(hariIniLokal, []);
  const pilihan = useMemo(() => pilihanPeriode(hariIni, 12), [hariIni]);
  const [periode, setPeriode] = useState(pilihan[0] || '');
  const [data, setData] = useState(undefined);       // undefined = memuat; null = gagal
  const [galat, setGalat] = useState(null);
  const [unduh, setUnduh] = useState('');            // format yang sedang diunduh
  const [pesanUnduh, setPesanUnduh] = useState(null);

  useEffect(() => {
    let batal = false;
    setData(undefined);
    setGalat(null);
    api.pluginRute(PLUGIN_ID, `/laba-rugi?periode=${encodeURIComponent(periode)}`).then(r => {
      if (batal) return;
      const d = r.ok ? rapikanLabaRugi(r.data) : null;
      setData(d);
      if (!r.ok) setGalat(pesanLabaRugiGalat(r.status, r.data));
      else if (!d) setGalat({ teks: 'Laba rugi tidak terbaca. Coba muat ulang.' });
    });
    return () => { batal = true; };
  }, [periode]);

  const unduhLaporan = async (format) => {
    setUnduh(format);
    setPesanUnduh(null);
    const r = await api.unduhPluginRute(PLUGIN_ID, pathLaporan(periode, format),
      `jatahku-buku-usaha-laba-rugi-${periode}.${format}`);
    setUnduh('');
    setPesanUnduh(r.ok
      ? { teks: `Laporan ${labelPeriode(periode)} (${format.toUpperCase()}) diunduh.` }
      : { ...pesanLabaRugiGalat(r.status, r.data), galat: true });
  };

  const bulanLalu = data ? labelPeriode(data.banding.periode).split(' ')[0] : '';
  const kosong = data && Number(data.omzet) === 0 && data.beban.length === 0 && data.diLuar.every(x => Number(x.jumlah) === 0);

  return (
    <section className="card !px-4 md:!px-6 !py-5 min-w-0" aria-labelledby="bu-laba-rugi" aria-busy={data === undefined}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="bu-laba-rugi" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Laba rugi</h2>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {data ? `${tanggalPendek(data.mulai)} – ${tanggalPendek(data.akhir)} · dibanding ${labelPeriode(data.banding.periode)}`
              : `Omzet, beban, dan laba ${ruangNama} per bulan kalender.`}
          </p>
        </div>
        <label className="shrink-0">
          <span className="sr-only">Periode</span>
          <select className="input text-sm !py-2" value={periode} onChange={e => { setPeriode(e.target.value); setPesanUnduh(null); }}>
            {pilihan.map(p => <option key={p} value={p}>{labelPeriode(p)}{p === pilihan[0] ? ' (berjalan)' : ''}</option>)}
          </select>
        </label>
      </div>

      {data === undefined && <p className="text-sm mt-4" style={{ color: 'var(--text-muted)' }}>Memuat laba rugi…</p>}

      {galat && (
        <p role="alert" className="text-sm mt-4 rounded-xl px-3 py-2" style={{ color: '#B91C1C', background: 'rgba(220,38,38,0.08)' }}>
          {galat.teks}{' '}
          {galat.perlu === 'izin' || galat.perlu === 'fitur'
            ? <Link to="/fitur-tambahan" className="underline font-semibold">Buka Fitur Tambahan</Link> : null}
        </p>
      )}

      {data && (
        <>
          {data.berjalan && (
            <p className="text-xs mt-3 rounded-xl px-3 py-2" style={{ color: 'var(--text-muted)', background: 'rgba(148,163,184,0.12)' }}>
              Bulan berjalan: angka masih bisa berubah sampai akhir bulan.
            </p>
          )}

          <div className="grid gap-3 sm:grid-cols-3 mt-4">
            <Kpi label="Omzet" nilai={data.omzet} perubahan={data.perubahan.omzet} bulanLalu={bulanLalu}
              sub={`${data.jumlahPenjualan.toLocaleString('id-ID')} penjualan`} />
            <Kpi label="Beban" nilai={data.bebanTotal} perubahan={data.perubahan.bebanTotal} naikBaik={false} bulanLalu={bulanLalu}
              sub={`${data.beban.reduce((t, b) => t + b.banyak, 0).toLocaleString('id-ID')} pengeluaran`} />
            <Kpi label="Laba bersih" nilai={data.laba} perubahan={data.perubahan.laba} bulanLalu={bulanLalu} utama
              sub={`Margin ${persenRasio(data.margin)}`} />
          </div>

          {kosong && (
            <p className="text-sm mt-4 rounded-xl px-4 py-6 text-center" style={{ color: 'var(--text-muted)', background: 'rgba(148,163,184,0.08)' }}>
              Belum ada penjualan atau pengeluaran di {labelPeriode(data.periode)}.
            </p>
          )}

          {data.tanpaJenis.banyak > 0 && (
            <p className="text-sm mt-4 rounded-xl px-3 py-2" role="note"
              style={{ color: 'color-mix(in srgb, #B45309 60%, var(--text))', background: 'rgba(245,158,11,0.14)' }}>
              {data.tanpaJenis.banyak.toLocaleString('id-ID')} pemasukan tanpa jenis ({rupiah(data.tanpaJenis.jumlah)}) ikut dihitung
              sebagai omzet. Catat penjualan lewat Catat › Penjualan supaya jenisnya tercatat.
            </p>
          )}

          {data.beban.length > 0 && (
            <div className="mt-5">
              <h3 className="font-semibold text-sm" style={{ color: 'var(--text)' }}>Beban per akun</h3>
              <ul className="mt-1">
                {data.beban.map(b => (
                  <li key={b.akun} className="py-2.5" style={{ borderTop: '1px solid var(--border)' }}>
                    <div className="flex items-baseline gap-3">
                      <span className="flex-1 min-w-0 text-sm truncate"
                        style={{ color: b.akun === BELUM_BERAKUN ? 'var(--text-muted)' : 'var(--text)', fontWeight: b.akun === BELUM_BERAKUN ? 400 : 600 }}>
                        {b.akun}
                        <span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}> · {b.banyak.toLocaleString('id-ID')} catatan</span>
                      </span>
                      <span className="text-sm font-semibold tabular-nums" style={{ color: 'var(--text)' }}>{rupiah(b.jumlah)}</span>
                      <span className="text-xs tabular-nums w-11 text-right" style={{ color: 'var(--text-muted)' }}>{persenRasio(b.porsi)}</span>
                    </div>
                    <div className="mt-1.5 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(148,163,184,0.18)' }} aria-hidden="true">
                      <div className="h-full rounded-full" style={{ width: `${Math.round(b.porsi * 100)}%`, background: b.akun === BELUM_BERAKUN ? 'rgba(148,163,184,0.7)' : 'var(--brand-500, #1D9E75)' }} />
                    </div>
                  </li>
                ))}
              </ul>
              {data.beban.some(b => b.akun === BELUM_BERAKUN) && (
                <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                  "Belum berakun" = pengeluaran tanpa Akun beban (isi di form pengeluaran), termasuk pengeluaran privat anggota.
                </p>
              )}
            </div>
          )}

          <div className="mt-5">
            <h3 className="font-semibold text-sm" style={{ color: 'var(--text)' }}>Di luar laba rugi</h3>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Uang yang masuk atau keluar tetapi bukan omzet atau beban.</p>
            <ul className="mt-1">
              {data.diLuar.map(x => (
                <li key={x.id} className="flex items-baseline gap-3 py-2" style={{ borderTop: '1px solid var(--border)' }}>
                  <span className="flex-1 min-w-0">
                    <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{x.label}</span>
                    <span className="block text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                      {x.id === 'prive' && data.priveDariLaba !== null && Number(x.jumlah) > 0
                        ? `${persenRasio(data.priveDariLaba)} dari laba bersih` : x.bantu}
                    </span>
                  </span>
                  <span className="text-sm font-semibold tabular-nums" style={{ color: Number(x.jumlah) ? 'var(--text)' : 'var(--text-muted)' }}>
                    {rupiah(x.jumlah)}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-wrap items-center gap-2 mt-5 pt-4" style={{ borderTop: '1px solid var(--border)' }}>
            <span className="text-sm mr-auto basis-full sm:basis-auto" style={{ color: 'var(--text-muted)' }}>Laporan {labelPeriode(data.periode)}</span>
            {['pdf', 'csv'].map(f => (
              <button key={f} type="button" className="btn-outline !px-4 !py-2 inline-flex items-center gap-1.5 disabled:opacity-50"
                disabled={!!unduh} onClick={() => unduhLaporan(f)} aria-label={`Unduh laporan ${f.toUpperCase()}`}>
                <Icon name={unduh === f ? 'spinner' : 'download'} size={16} /> {f.toUpperCase()}
              </button>
            ))}
          </div>
        </>
      )}

      {pesanUnduh && (
        <p role={pesanUnduh.galat ? 'alert' : 'status'} className="text-sm mt-3 rounded-xl px-3 py-2"
          style={pesanUnduh.galat ? { color: '#B91C1C', background: 'rgba(220,38,38,0.08)' } : { color: 'var(--text-muted)', background: 'rgba(148,163,184,0.12)' }}>
          {pesanUnduh.teks}
        </p>
      )}
    </section>
  );
}
