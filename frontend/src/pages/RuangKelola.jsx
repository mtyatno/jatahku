// Halaman Anggota ruang usaha (Plugin R6; artboard "Admin: anggota, batasan, persetujuan", desain A2 butir 18, B4).
// Untuk pemilik dan admin ruang usaha yang sedang dibuka: antrean persetujuan, daftar anggota di kiri, panel batasan
// di kanan (tersimpan otomatis dan tercatat di log ruang), undangan, nama ruang, dan log.
//
// Server memeriksa semua hak (04-kontrak-api.md §2): admin tidak bisa mengubah pemilik; batasan hanya untuk karyawan.
// Kata yang dipelajari (kamus ruang, R7): daftar dan hapus; menghapus juga membuang kata yang sama milik anggota untuk
// amplop itu, dan tercatat di log ruang.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { Icon, EnvelopeIcon } from '../components/Icon';
import { formatCurrency } from '../lib/utils';
import { peranLabel, setRuangAktif } from '../lib/ruangAktif';
import { batasanDariForm, formDariBatasan, galatForm, labelAudit } from '../lib/ruangPeran';

const HARI = [[1, 'Sen'], [2, 'Sel'], [3, 'Rab'], [4, 'Kam'], [5, 'Jum'], [6, 'Sab'], [7, 'Min']];
const SIMPAN_TUNDA_MS = 700;
const ribuan = (t) => (t ? Number(t).toLocaleString('id-ID') : '');   // isian nominal tampil "1.000.000"
const digit = (t) => t.replace(/[^\d]/g, '');

const tanggal = (iso) => (iso ? new Date(iso).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' }) : '');
const waktu = (iso) => (iso ? new Date(iso).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '');
const pesan = (r, cadangan) => (typeof r?.data?.detail === 'string' ? r.data.detail : cadangan);

function Bagian({ judul, aksi, children, className = '' }) {
  return (
    <section className={`card !px-4 md:!px-6 !py-5 min-w-0 ${className}`}>
      <div className="flex items-center justify-between gap-3 mb-3">
        <h2 className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>{judul}</h2>
        {aksi}
      </div>
      {children}
    </section>
  );
}

function Pesan({ teks, galat = false }) {
  if (!teks) return null;
  return (
    <p role={galat ? 'alert' : 'status'} className="text-sm mt-2" style={{ color: galat ? '#DC2626' : 'var(--text-muted)' }}>
      {teks}
    </p>
  );
}

function Avatar({ nama }) {
  return (
    <span className="shrink-0 w-9 h-9 rounded-full inline-flex items-center justify-center text-sm font-bold"
      style={{ background: 'rgba(29,158,117,0.12)', color: 'var(--brand-600)' }}>
      {(nama || '?').charAt(0).toUpperCase()}
    </span>
  );
}

// ── Nama ruang ──────────────────────────────────────────────────────────────
function NamaRuang({ rid, nama, onBerubah }) {
  const [edit, setEdit] = useState(false);
  const [isi, setIsi] = useState(nama);
  const [galat, setGalat] = useState('');
  const simpan = async (e) => {
    e.preventDefault();
    const r = await api.ubahRuang(rid, isi);
    if (!r.ok) { setGalat(pesan(r, 'Nama ruang 1–60 huruf.')); return; }
    setEdit(false);
    setGalat('');
    onBerubah(r.data.nama);
  };
  if (!edit) {
    return (
      <div className="flex items-center gap-2 min-w-0">
        <h1 className="font-display font-bold text-2xl truncate" style={{ color: 'var(--text)' }}>{nama}</h1>
        <button type="button" onClick={() => { setIsi(nama); setEdit(true); }} aria-label="Ganti nama ruang"
          className="shrink-0 w-8 h-8 rounded-lg inline-flex items-center justify-center hover:bg-black/5" style={{ color: 'var(--text-muted)' }}>
          <Icon name="edit" size={16} />
        </button>
      </div>
    );
  }
  return (
    <form onSubmit={simpan} className="flex flex-wrap items-center gap-2">
      <input className="input text-lg font-bold" maxLength={60} autoFocus value={isi} onChange={e => setIsi(e.target.value)}
        aria-label="Nama ruang" />
      <button type="submit" className="btn-primary text-sm">Simpan</button>
      <button type="button" onClick={() => setEdit(false)} className="btn-outline text-sm">Batal</button>
      <Pesan teks={galat} galat />
    </form>
  );
}

// ── Antrean persetujuan ─────────────────────────────────────────────────────
function Antrean({ rid, draf, amplop, onBerubah }) {
  const [tolak, setTolak] = useState(null);   // { id, alasan }
  const [sibuk, setSibuk] = useState(null);
  const [hasil, setHasil] = useState({});     // id → { teks, galat }

  const putus = async (d, aksi) => {
    setSibuk(d.id);
    const r = aksi === 'setujui' ? await api.setujuiDraf(rid, d.id) : await api.tolakDraf(rid, d.id, tolak?.alasan);
    setSibuk(null);
    if (!r.ok) {
      setHasil(h => ({ ...h, [d.id]: { teks: pesan(r, 'Gagal. Coba lagi.'), galat: true } }));
      if (r.status === 409) onBerubah();
      return;
    }
    setTolak(null);
    window.dispatchEvent(new CustomEvent('jatahku:draf-diputus'));
    if (aksi === 'setujui') window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
    onBerubah();
  };

  return (
    <Bagian judul="Menunggu persetujuan"
      aksi={draf.length > 0 ? <span className="text-xs font-bold rounded-full px-2 py-0.5" style={{ background: '#DC2626', color: '#fff' }}>{draf.length}</span> : null}>
      {draf.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          Tidak ada catatan yang menunggu. Catatan karyawan di atas batas nominalnya akan muncul di sini.
        </p>
      ) : (
        <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
          {draf.map(d => {
            const env = amplop[d.amplop_id];
            return (
              <li key={d.id} className="py-3">
                <div className="flex flex-wrap items-start gap-3">
                  <Avatar nama={d.pencatat} />
                  <div className="min-w-0 flex-1 basis-[calc(100%-3rem)] sm:basis-0">
                    <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                      {d.keterangan} <span className="font-mono">· {formatCurrency(d.jumlah)}</span>
                    </p>
                    <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                      {d.pencatat || 'Mantan anggota'} · {d.jenis === 'penjualan' ? 'Penjualan' : 'Pengeluaran'}
                      {env ? ` · ${env.name}` : ''}{d.ada_foto ? ' · ada foto nota' : ''} · {waktu(d.dibuat)}
                    </p>
                  </div>
                  <div className="flex gap-2 shrink-0 w-full sm:w-auto pl-12 sm:pl-0">
                    <button type="button" disabled={sibuk === d.id} onClick={() => setTolak(t => (t?.id === d.id ? null : { id: d.id, alasan: '' }))}
                      className="btn-outline text-sm disabled:opacity-50">Tolak</button>
                    <button type="button" disabled={sibuk === d.id} onClick={() => putus(d, 'setujui')}
                      className="btn-primary text-sm disabled:opacity-50">{sibuk === d.id ? '...' : 'Setujui'}</button>
                  </div>
                </div>
                {tolak?.id === d.id && (
                  <form className="flex flex-wrap gap-2 mt-2 sm:pl-12" onSubmit={(e) => { e.preventDefault(); putus(d, 'tolak'); }}>
                    <input className="input text-sm flex-1 min-w-[12rem]" maxLength={300} placeholder="Alasan (opsional), terlihat oleh karyawan"
                      value={tolak.alasan} onChange={e => setTolak({ id: d.id, alasan: e.target.value })} autoFocus />
                    <button type="submit" className="btn-outline text-sm" style={{ color: '#DC2626' }}>Tolak catatan</button>
                  </form>
                )}
                {hasil[d.id] && <div className="sm:pl-12"><Pesan teks={hasil[d.id].teks} galat={hasil[d.id].galat} /></div>}
              </li>
            );
          })}
        </ul>
      )}
    </Bagian>
  );
}

// ── Panel anggota ───────────────────────────────────────────────────────────
function FormBatasan({ rid, anggota, amplopDaftar, onTersimpan }) {
  const [form, setForm] = useState(() => formDariBatasan(anggota.batasan));
  const [status, setStatus] = useState({ teks: '', galat: false });
  const timer = useRef(null);
  const tertunda = useRef(null);

  const kirim = useCallback(async (f) => {
    tertunda.current = null;
    const salah = galatForm(f);
    if (salah) { setStatus({ teks: salah, galat: true }); return; }
    setStatus({ teks: 'Menyimpan...', galat: false });
    const r = await api.aturBatasan(rid, anggota.user_id, batasanDariForm(f));
    if (!r.ok) { setStatus({ teks: pesan(r, 'Gagal menyimpan batasan.'), galat: true }); return; }
    setStatus({ teks: `Tersimpan · ${new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}`, galat: false });
    onTersimpan(anggota.user_id, r.data);
  }, [rid, anggota.user_id, onTersimpan]);

  // Simpan yang masih tertunda saat panel ditutup atau anggota lain dipilih.
  useEffect(() => () => {
    clearTimeout(timer.current);
    if (tertunda.current) kirim(tertunda.current);
  }, [kirim]);

  const ubah = (perubahan) => {
    setForm(f => {
      const baru = { ...f, ...perubahan };
      tertunda.current = baru;
      clearTimeout(timer.current);
      timer.current = setTimeout(() => kirim(baru), SIMPAN_TUNDA_MS);
      return baru;
    });
  };
  const toggle = (daftar, nilai) => (daftar.includes(nilai) ? daftar.filter(x => x !== nilai) : [...daftar, nilai]);

  return (
    <div className="space-y-5">
      <fieldset>
        <legend className="label">Boleh mencatat</legend>
        <div className="flex flex-wrap gap-2">
          {[['pengeluaran', 'Pengeluaran'], ['penjualan', 'Penjualan']].map(([j, label]) => (
            <label key={j} className="inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm cursor-pointer" style={{ borderColor: 'var(--border)', color: 'var(--text)' }}>
              <input type="checkbox" checked={form.jenis_catatan.includes(j)} onChange={() => ubah({ jenis_catatan: toggle(form.jenis_catatan, j) })} />
              {label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="label">Amplop yang boleh dipakai</legend>
        <label className="inline-flex items-center gap-2 text-sm mb-2" style={{ color: 'var(--text)' }}>
          <input type="checkbox" checked={form.semua_amplop}
            onChange={() => ubah({ semua_amplop: !form.semua_amplop, amplop_ids: form.semua_amplop ? [] : form.amplop_ids })} />
          Semua amplop ruang ini
        </label>
        {!form.semua_amplop && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {amplopDaftar.map(env => (
              <label key={env.id} className="flex items-center gap-2 rounded-xl border px-3 py-2 text-sm cursor-pointer" style={{ borderColor: 'var(--border)', color: 'var(--text)' }}>
                <input type="checkbox" checked={form.amplop_ids.includes(env.id)} onChange={() => ubah({ amplop_ids: toggle(form.amplop_ids, env.id) })} />
                <EnvelopeIcon value={env.emoji} size={16} />
                <span className="truncate">{env.name}</span>
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor="batas-nominal">Batas per catatan (Rp)</label>
          <input id="batas-nominal" className="input font-mono" inputMode="numeric" placeholder="Tanpa batas"
            value={ribuan(form.batas_nominal)} onChange={e => ubah({ batas_nominal: digit(e.target.value) })} />
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Di atasnya catatan menunggu persetujuanmu.</p>
        </div>
        <div>
          <label className="label" htmlFor="foto-nota">Wajib foto nota di atas (Rp)</label>
          <input id="foto-nota" className="input font-mono" inputMode="numeric" placeholder="Tidak wajib"
            value={ribuan(form.foto_nota_di_atas)} onChange={e => ubah({ foto_nota_di_atas: digit(e.target.value) })} />
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Lampiran foto nota untuk karyawan belum tersedia: catatannya di atas nominal ini ditolak, jadi admin yang mencatat.</p>
        </div>
      </div>

      <fieldset>
        <legend className="label">Menghapus catatan sendiri</legend>
        <div className="flex flex-wrap gap-2">
          {[['hari_sama', 'Di hari yang sama'], ['tidak_boleh', 'Tidak boleh']].map(([v, label]) => (
            <label key={v} className="inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm cursor-pointer" style={{ borderColor: 'var(--border)', color: 'var(--text)' }}>
              <input type="radio" name={`jendela-${anggota.user_id}`} checked={form.jendela_ubah === v} onChange={() => ubah({ jendela_ubah: v })} />
              {label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="label">Yang bisa dilihat</legend>
        <label className="inline-flex items-center gap-2 text-sm" style={{ color: 'var(--text)' }}>
          <input type="checkbox" checked={form.lihat_saldo} onChange={() => ubah({ lihat_saldo: !form.lihat_saldo })} />
          Saldo amplop yang diizinkan
        </label>
        <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Laporan, laba, dan kas tidak pernah terlihat oleh karyawan.</p>
      </fieldset>

      <fieldset>
        <legend className="label">Jam kerja</legend>
        <label className="inline-flex items-center gap-2 text-sm mb-2" style={{ color: 'var(--text)' }}>
          <input type="checkbox" checked={form.pakai_jam_kerja} onChange={() => ubah({ pakai_jam_kerja: !form.pakai_jam_kerja })} />
          Ruang ini hanya bisa dibuka di jam kerja
        </label>
        {form.pakai_jam_kerja && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: 'var(--text)' }}>
              <input type="time" className="input w-32" aria-label="Jam mulai" value={form.jam_mulai} onChange={e => ubah({ jam_mulai: e.target.value })} />
              <span>sampai</span>
              <input type="time" className="input w-32" aria-label="Jam selesai" value={form.jam_selesai} onChange={e => ubah({ jam_selesai: e.target.value })} />
            </div>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Hari kerja">
              {HARI.map(([h, label]) => (
                <button key={h} type="button" aria-pressed={form.hari.includes(h)} onClick={() => ubah({ hari: toggle(form.hari, h).sort((a, b) => a - b) })}
                  className="w-11 h-9 rounded-lg text-sm font-semibold border"
                  style={form.hari.includes(h)
                    ? { background: 'rgba(29,158,117,0.12)', borderColor: 'var(--brand-400)', color: 'var(--brand-600)' }
                    : { borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
                  {label}
                </button>
              ))}
            </div>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Jam selesai sebelum jam mulai = sif lewat tengah malam.</p>
          </div>
        )}
      </fieldset>

      <Pesan teks={status.teks} galat={status.galat} />
    </div>
  );
}

function PanelAnggota({ rid, anggota, peranSaya, saya, amplopDaftar, onBerubah, onTersimpan }) {
  const [jabatan, setJabatan] = useState(anggota.jabatan || '');
  const [info, setInfo] = useState({ teks: '', galat: false });
  const owner = anggota.peran === 'owner';
  const diriSendiri = anggota.user_id === saya;
  const bolehUbah = !owner && !(diriSendiri && peranSaya === 'admin');

  const ubahPeran = async (peran) => {
    if (peran === anggota.peran) return;
    if (peran === 'admin' && !window.confirm(`Jadikan ${anggota.nama} admin? Admin bisa mengatur anggota, menyetujui catatan, dan melihat laporan ruang ini.`)) return;
    const r = await api.ubahAnggota(rid, anggota.user_id, { peran });
    if (!r.ok) { setInfo({ teks: pesan(r, 'Gagal mengubah peran.'), galat: true }); return; }
    setInfo({ teks: `Peran diubah menjadi ${peranLabel(peran)}.`, galat: false });
    onBerubah();
  };
  const simpanJabatan = async () => {
    if ((anggota.jabatan || '') === jabatan.trim()) return;
    const r = await api.ubahAnggota(rid, anggota.user_id, { jabatan: jabatan.trim() || null });
    setInfo(r.ok ? { teks: 'Jabatan tersimpan.', galat: false } : { teks: pesan(r, 'Gagal menyimpan jabatan.'), galat: true });
    if (r.ok) onTersimpan(anggota.user_id, null, jabatan.trim() || null);
  };
  const keluarkan = async () => {
    const tanya = diriSendiri ? 'Keluar dari ruang ini? Aksesmu langsung hilang; catatanmu tetap milik ruang.'
      : `Keluarkan ${anggota.nama}? Aksesnya langsung hilang, catatannya tetap milik ruang, dan draf yang menunggu dibatalkan.`;
    if (!window.confirm(tanya)) return;
    const r = await api.keluarkanAnggota(rid, anggota.user_id);
    if (!r.ok) { setInfo({ teks: pesan(r, 'Gagal.'), galat: true }); return; }
    if (diriSendiri) { setRuangAktif(null); window.location.assign('/'); return; }
    onBerubah(true);
  };

  return (
    <Bagian judul={anggota.nama}>
      <p className="text-sm -mt-2 mb-4" style={{ color: 'var(--text-muted)' }}>
        {peranLabel(anggota.peran)}{anggota.jabatan ? ` · ${anggota.jabatan}` : ''} · bergabung {tanggal(anggota.bergabung)}
      </p>
      {owner ? (
        <p className="text-sm" style={{ color: 'var(--text)' }}>Pemilik ruang tidak dibatasi dan tidak bisa diubah atau dikeluarkan.</p>
      ) : (
        <div className="space-y-5">
          {bolehUbah && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <fieldset>
                <legend className="label">Peran</legend>
                <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Peran">
                  {['member', 'admin'].map(p => (
                    <button key={p} type="button" role="radio" aria-checked={anggota.peran === p} onClick={() => ubahPeran(p)}
                      className="rounded-xl py-2 text-sm font-semibold border"
                      style={anggota.peran === p
                        ? { background: 'rgba(29,158,117,0.12)', borderColor: 'var(--brand-400)', color: 'var(--brand-600)' }
                        : { borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
                      {peranLabel(p)}
                    </button>
                  ))}
                </div>
              </fieldset>
              <div>
                <label className="label" htmlFor="jabatan">Jabatan</label>
                <input id="jabatan" className="input" maxLength={50} placeholder="mis. Kasir" value={jabatan}
                  onChange={e => setJabatan(e.target.value)} onBlur={simpanJabatan} />
              </div>
            </div>
          )}
          <Pesan teks={info.teks} galat={info.galat} />
          {anggota.peran === 'member' ? (
            <FormBatasan key={anggota.user_id} rid={rid} anggota={anggota} amplopDaftar={amplopDaftar} onTersimpan={onTersimpan} />
          ) : (
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Admin tidak dibatasi: bisa mencatat, menyetujui, dan mengatur anggota.</p>
          )}
          {(bolehUbah || (diriSendiri && !owner)) && (
            <div className="pt-4" style={{ borderTop: '1px solid var(--border)' }}>
              <button type="button" onClick={keluarkan} className="text-sm font-semibold" style={{ color: '#DC2626' }}>
                {diriSendiri ? 'Keluar dari ruang ini' : `Keluarkan ${anggota.nama} dari ruang`}
              </button>
            </div>
          )}
        </div>
      )}
    </Bagian>
  );
}

// ── Undangan ────────────────────────────────────────────────────────────────
function Undangan({ rid, undangan, onBerubah }) {
  const [baru, setBaru] = useState(null);
  const [galat, setGalat] = useState('');
  const [salin, setSalin] = useState(false);
  const buat = async (peran) => {
    setGalat('');
    const r = await api.buatUndangan(rid, peran);
    if (!r.ok) { setGalat(pesan(r, 'Gagal membuat undangan.')); return; }
    setBaru(r.data);
    setSalin(false);
    onBerubah();
  };
  const cabut = async (u) => {
    if (!window.confirm(`Cabut kode ${u.kode}? Kode ini tidak bisa dipakai lagi.`)) return;
    const r = await api.cabutUndangan(rid, u.id);
    if (!r.ok) setGalat(pesan(r, 'Gagal mencabut undangan.'));
    if (baru?.kode === u.kode) setBaru(null);
    onBerubah();
  };
  const salinKode = async () => {
    try { await navigator.clipboard.writeText(baru.kode); setSalin(true); } catch { setSalin(false); }
  };
  return (
    <Bagian judul="Undang anggota">
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => buat('member')} className="btn-primary text-sm">Undang karyawan</button>
        <button type="button" onClick={() => buat('admin')} className="btn-outline text-sm">Undang admin</button>
      </div>
      {baru && (
        <div className="mt-3 rounded-xl px-4 py-3" style={{ background: 'var(--page)', border: '1px solid var(--border)' }}>
          <div className="flex items-center gap-3">
            <span className="font-mono text-lg font-bold tracking-wider" style={{ color: 'var(--text)' }}>{baru.kode}</span>
            <button type="button" onClick={salinKode} className="text-sm font-semibold" style={{ color: 'var(--brand-600)' }}>
              {salin ? 'Tersalin' : 'Salin'}
            </button>
          </div>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            Untuk {peranLabel(baru.peran)}, sekali pakai, berlaku sampai {tanggal(baru.kedaluwarsa)}. Minta dia membuka
            Jatahku, ketuk pemilih ruang, lalu "Gabung dengan kode". Ruang keluarganya tidak ikut terhubung.
          </p>
        </div>
      )}
      <Pesan teks={galat} galat />
      {undangan.length > 0 && (
        <ul className="mt-3 divide-y" style={{ borderColor: 'var(--border)' }}>
          {undangan.map(u => (
            <li key={u.id} className="py-2 flex items-center gap-3 text-sm">
              <span className="font-mono font-semibold" style={{ color: 'var(--text)' }}>{u.kode}</span>
              <span className="flex-1 min-w-0 truncate text-xs" style={{ color: 'var(--text-muted)' }}>
                {peranLabel(u.peran)} · sampai {tanggal(u.kedaluwarsa)}{u.dibuat_oleh ? ` · dari ${u.dibuat_oleh}` : ''}
              </span>
              <button type="button" onClick={() => cabut(u)} className="text-xs font-semibold" style={{ color: '#DC2626' }}>Cabut</button>
            </li>
          ))}
        </ul>
      )}
    </Bagian>
  );
}

// ── Kata yang dipelajari (kamus ruang, R7) ─────────────────────────────────
const KAMUS_RINGKAS = 12;

function KamusRuang({ rid, namaRuang, onBerubah }) {
  const [data, setData] = useState(null);
  const [q, setQ] = useState('');
  const [semua, setSemua] = useState(false);
  const [galat, setGalat] = useState('');

  const muat = useCallback(async (cari) => {
    const r = await api.kamusRuang(rid, cari);
    if (!r.ok) { setGalat(pesan(r, 'Kata yang dipelajari belum bisa dimuat.')); return; }
    setGalat('');
    setData(r.data);
  }, [rid]);

  useEffect(() => {
    const t = setTimeout(() => muat(q.trim()), q ? 300 : 0);
    return () => clearTimeout(t);
  }, [muat, q]);

  const hapus = async (k) => {
    if (!window.confirm(`Hapus "${k.kata}" → ${k.amplop}? Anggota tidak lagi mendapat tebakan ini.`)) return;
    const r = await api.hapusKamus(rid, k.id);
    if (!r.ok && r.status !== 404) { setGalat(pesan(r, 'Gagal menghapus kata.')); return; }
    await muat(q.trim());
    onBerubah?.();
  };

  const items = data?.items || [];
  const tampil = semua ? items : items.slice(0, KAMUS_RINGKAS);
  return (
    <Bagian judul="Kata yang dipelajari"
      aksi={data ? <span className="text-sm" style={{ color: 'var(--text-muted)' }}>{data.total} kata</span> : null}>
      <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
        Dari catatan anggota di {namaRuang}. Dipakai semua anggota untuk menebak amplop, sesudah kata masing-masing;
        tidak pernah dipakai di ruang keluarga.
      </p>
      {(data?.total || 0) > KAMUS_RINGKAS && (
        <input type="search" className="input mt-3" placeholder="Cari kata" aria-label="Cari kata yang dipelajari"
          value={q} onChange={e => setQ(e.target.value)} maxLength={100} />
      )}
      <Pesan teks={galat} galat />
      {data && items.length === 0 && (
        <p className="text-sm mt-3" style={{ color: 'var(--text-muted)' }}>
          {q ? 'Tidak ada kata yang cocok.' : 'Belum ada. Kata bertambah saat anggota mencatat pengeluaran di ruang ini.'}
        </p>
      )}
      {items.length > 0 && (
        <ul className="mt-3 divide-y" style={{ borderColor: 'var(--border)' }}>
          {tampil.map(k => (
            <li key={k.id} className="py-2 flex items-center gap-3 text-sm min-w-0">
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 min-w-0" style={{ color: 'var(--text)' }}>
                  <b className="truncate">{k.kata}</b>
                  <span aria-hidden="true" style={{ color: 'var(--text-muted)' }}>→</span>
                  <EnvelopeIcon value={k.emoji} size={16} />
                  <span className="truncate">{k.amplop}</span>
                </span>
                <span className="block truncate text-xs" style={{ color: 'var(--text-muted)' }}>
                  {k.kali}× · diajarkan {k.diajarkan_oleh || 'mantan anggota'}
                </span>
              </span>
              <button type="button" onClick={() => hapus(k)} className="text-xs font-semibold shrink-0" style={{ color: '#DC2626' }}
                aria-label={`Hapus kata ${k.kata} untuk ${k.amplop}`}>Hapus</button>
            </li>
          ))}
        </ul>
      )}
      {items.length > KAMUS_RINGKAS && (
        <button type="button" onClick={() => setSemua(v => !v)} className="text-sm font-semibold mt-2" style={{ color: 'var(--brand-600)' }}>
          {semua ? 'Ringkas' : `Lihat semua (${items.length})`}
        </button>
      )}
    </Bagian>
  );
}

// ── Halaman ─────────────────────────────────────────────────────────────────
export default function RuangKelola() {
  const { user } = useAuth();
  const { ruang, akses } = useOutletContext() || {};
  const rid = akses?.ruangId;
  const aktif = ruang?.aktif;
  const [nama, setNama] = useState(aktif?.nama || '');
  const [anggota, setAnggota] = useState(null);
  const [pilih, setPilih] = useState(null);
  const [undangan, setUndangan] = useState([]);
  const [draf, setDraf] = useState([]);
  const [log, setLog] = useState([]);
  const [amplop, setAmplop] = useState([]);
  const [galat, setGalat] = useState('');
  const [lihatLog, setLihatLog] = useState(false);
  const panelRef = useRef(null);

  useEffect(() => { if (aktif?.nama) setNama(aktif.nama); }, [aktif?.nama]);

  const muat = useCallback(async () => {
    if (!rid) return;
    const [a, u, p, l] = await Promise.all([api.ruangAnggota(rid), api.daftarUndangan(rid), api.daftarPersetujuan(rid), api.logRuang(rid)]);
    if (!a.ok) { setGalat(pesan(a, 'Halaman ini belum bisa dimuat.')); return; }
    setGalat('');
    setAnggota(a.data);
    setUndangan(u.ok ? u.data : []);
    setDraf(p.ok ? p.data : []);
    setLog(l.ok ? l.data : []);
  }, [rid]);

  useEffect(() => { muat(); }, [muat]);
  useEffect(() => { if (rid) api.getEnvelopes().then(list => setAmplop(Array.isArray(list) ? list : [])); }, [rid]);

  const onTersimpan = useCallback((uid, batasan, jabatan) => {
    setAnggota(list => (list || []).map(m => (m.user_id !== uid ? m
      : { ...m, ...(batasan ? { batasan } : {}), ...(jabatan !== undefined ? { jabatan } : {}) })));
    api.logRuang(rid).then(l => { if (l.ok) setLog(l.data); });
  }, [rid]);

  if (!akses?.pengelola || !rid) {
    return (
      <div className="card !p-6 max-w-xl">
        <p className="text-sm" style={{ color: 'var(--text)' }}>Halaman ini untuk pemilik dan admin ruang usaha. Buka ruang usahamu dari pemilih ruang.</p>
        <Link to="/" className="text-sm font-semibold" style={{ color: 'var(--brand-600)' }}>Kembali ke Beranda</Link>
      </div>
    );
  }
  if (galat) return <div className="card !p-6 max-w-xl"><Pesan teks={galat} galat /></div>;
  if (!anggota) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  const amplopMap = Object.fromEntries(amplop.map(e => [e.id, e]));
  const dipilih = anggota.find(m => m.user_id === pilih) || anggota.find(m => m.peran === 'member') || anggota[0];
  const pilihAnggota = (uid) => {
    setPilih(uid);
    if (window.innerWidth < 1024) setTimeout(() => panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
  };

  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          <Link to="/settings" className="hover:underline">Pengaturan</Link> › Ruang usaha
        </p>
        <NamaRuang rid={rid} nama={nama} onBerubah={(n) => { setNama(n); window.dispatchEvent(new CustomEvent('jatahku:ruang-berubah')); muat(); }} />
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          {anggota.length} anggota · peranmu {peranLabel(aktif?.peran)}
        </p>
      </div>

      <Antrean rid={rid} draf={draf} amplop={amplopMap} onBerubah={muat} />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)] items-start">
        <div className="space-y-5 min-w-0">
          <Bagian judul="Anggota">
            <ul className="space-y-1" role="listbox" aria-label="Anggota ruang">
              {anggota.map(m => {
                const aktifPilih = m.user_id === dipilih?.user_id;
                const ringkas = m.peran === 'member' && m.batasan?.batas_nominal != null ? `batas ${formatCurrency(m.batasan.batas_nominal)}` : null;
                return (
                  <li key={m.user_id}>
                    <button type="button" role="option" aria-selected={aktifPilih} onClick={() => pilihAnggota(m.user_id)}
                      className="w-full text-left flex items-center gap-3 rounded-xl px-3 py-2.5 transition-colors"
                      style={{ background: aktifPilih ? 'var(--sidebar-active, rgba(148,163,184,0.12))' : 'transparent' }}>
                      <Avatar nama={m.nama} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold" style={{ color: 'var(--text)' }}>
                          {m.nama}{m.user_id === user?.id ? ' (kamu)' : ''}
                        </span>
                        <span className="block truncate text-xs" style={{ color: 'var(--text-muted)' }}>
                          {peranLabel(m.peran)}{m.jabatan ? ` · ${m.jabatan}` : ''}{ringkas ? ` · ${ringkas}` : ''}
                        </span>
                      </span>
                      <Icon name="chevron" size={14} className="-rotate-90" />
                    </button>
                  </li>
                );
              })}
            </ul>
          </Bagian>
          <Undangan rid={rid} undangan={undangan} onBerubah={muat} />
        </div>
        <div ref={panelRef} className="min-w-0 scroll-mt-20">
          {dipilih && (
            <PanelAnggota key={dipilih.user_id} rid={rid} anggota={dipilih} peranSaya={aktif?.peran} saya={user?.id}
              amplopDaftar={amplop} onBerubah={(keluar) => { if (keluar) setPilih(null); muat(); }} onTersimpan={onTersimpan} />
          )}
        </div>
      </div>

      <KamusRuang rid={rid} namaRuang={nama || 'ruang ini'}
        onBerubah={() => api.logRuang(rid).then(l => { if (l.ok) setLog(l.data); })} />

      <Bagian judul="Log ruang"
        aksi={<button type="button" onClick={() => setLihatLog(v => !v)} className="text-sm font-semibold" style={{ color: 'var(--brand-600)' }}>
          {lihatLog ? 'Sembunyikan' : `Lihat (${log.length})`}
        </button>}>
        {lihatLog ? (
          <ul className="divide-y text-sm" style={{ borderColor: 'var(--border)' }}>
            {log.map((a, i) => (
              <li key={`${a.waktu}-${i}`} className="py-2 flex gap-3">
                <span className="shrink-0 w-28 text-xs" style={{ color: 'var(--text-muted)' }}>{waktu(a.waktu)}</span>
                <span style={{ color: 'var(--text)' }}>{labelAudit(a)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Setiap perubahan anggota, batasan, undangan, persetujuan, dan kata yang dihapus tercatat di sini.</p>
        )}
      </Bagian>
    </div>
  );
}
