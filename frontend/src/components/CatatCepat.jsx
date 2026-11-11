// Lembar Catat cepat di ruang usaha (Plugin R7; artboard "Karyawan: Catat cepat dengan deteksi otomatis", desain
// B3.2 butir 2, A2 butir 12–17). Satu kotak teks seperti chat → kartu Terdeteksi (jenis, nominal, keterangan, amplop
// dan sumber tebakannya) → koreksi bila perlu → simpan. Menggantikan form Catat karyawan R6; untuk pemilik dan admin
// ruang usaha juga pintu Catat utama, dengan tautan ke form lengkap.
//
// Server menegakkan semua batasan (aturan admin di kartu hanya tampilan). Koreksi amplop mengajari kamus ruang ini
// (server, hanya catatan bukan-privat). Tawaran "pengeluaran pribadi" bertanya ke ruang keluarga user sendiri lewat
// permintaan terpisah tanpa header ruang; tidak tersimpan dan tidak terlihat admin (lib/catatCepat.js).
// Dua jalur, dua `client_ref` (review keamanan PR #191 temuan 1): Simpan ke ruang usaha dan "Catat di ruang keluarga"
// masing-masing punya ref sendiri. Bila hasil satu jalur belum pasti (koneksi putus, sedang diproses, 5xx), isian dan
// jalur lain dikunci, dan kirim ulang memakai permintaan yang sama persis, jadi tidak tercatat dua kali dan tidak
// pernah berpindah ruang diam-diam.
//
// Plugin U5: saran juga membawa jenis catatan dan kontak dari Fitur Tambahan yang aktif di ruang ini. Kata seperti
// "jual" memindahkan jenis ke Penjualan (selama user belum memilih sendiri); pemasok terdeteksi ikut tersimpan lewat
// field form plugin (`tambahan`); penjualan atas nama pelanggan, modal, dan pinjaman dilanjutkan di form Fitur
// Tambahan (`onFormPlugin`) dengan isian awal dari yang sudah diketik. Karyawan tidak menerima kontak dan tidak
// punya form plugin.
import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import {
  JEDA_SARAN_MS, amplopDipakai, amplopPilihan, aturanCatatan, galatCatat, hasilPribadi, hasilTidakPasti, isiFormPlugin,
  jenisLain, jenisTerdeteksi, kontakCatatan, labelSumber, perluCekPribadi, pesanAjari, pesanTerkunci, tambahanKontak,
  tawaranPribadi, uraiCatatan,
} from '../lib/catatCepat';
import { hasilCatat, payloadCatat } from '../lib/ruangPeran';
import { EnvelopeIcon, Icon } from './Icon';
import VoiceInput from './VoiceInput';

const LABEL = { pengeluaran: 'Pengeluaran', penjualan: 'Penjualan' };
const LABEL_KONTAK = { pemasok: 'Pemasok', pelanggan: 'Pelanggan' };
const rp = (n) => `Rp${Math.round(Number(n) || 0).toLocaleString('id-ID')}`;

function buatRef() {
  try { return crypto.randomUUID(); } catch { return `c${Date.now()}${Math.random().toString(36).slice(2, 10)}`; }
}

function Baris({ label, children }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <span className="text-xs shrink-0" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="text-sm text-right min-w-0 break-words" style={{ color: 'var(--text)' }}>{children}</span>
    </div>
  );
}

export default function CatatCepat({
  ruang, jenisBoleh = ['pengeluaran'], jenisAwal = 'pengeluaran', onDone, onCancel, onFormLengkap,
  isianPlugin = [], formPlugin, onFormPlugin,
}) {
  const namaRuang = ruang?.nama || 'ruang ini';
  const jenisMula = jenisBoleh.includes(jenisAwal) ? jenisAwal : jenisBoleh[0];
  const [jenis, setJenis] = useState(jenisMula);
  const [jenisManual, setJenisManual] = useState(false);   // user memilih sendiri: deteksi tidak memindahkannya lagi
  const manual = useRef(false);                            // cermin `jenisManual` untuk jawaban saran yang datang belakangan
  const [tanpaKontak, setTanpaKontak] = useState(false);   // user melepas kontak terdeteksi untuk catatan ini
  const [teks, setTeks] = useState('');
  const [daftar, setDaftar] = useState(null);
  const [pilihan, setPilihan] = useState(null);         // amplop dipilih user (null = pakai tebakan)
  const [saran, setSaran] = useState(null);
  const [keluarga, setKeluarga] = useState(null);       // jawaban ruang keluarga (tawaran pribadi)
  const [abaikanPribadi, setAbaikanPribadi] = useState(false);
  const [saving, setSaving] = useState(false);
  const [suaraSibuk, setSuaraSibuk] = useState(false);
  const [galat, setGalat] = useState('');
  const [refUsaha] = useState(buatRef);
  const [refPribadi] = useState(buatRef);
  const [terkunci, setTerkunci] = useState(null);        // 'usaha' | 'pribadi': hasil jalur itu belum pasti
  const kiriman = useRef(null);                           // permintaan terakhir per jalur, dikirim ulang apa adanya
  const urut = useRef(0);

  const { nominal, keterangan } = uraiCatatan(teks);

  useEffect(() => {
    let live = true;
    api.getEnvelopes().then(list => { if (live) setDaftar(Array.isArray(list) ? list : []); });
    return () => { live = false; };
  }, []);

  // Tebakan amplop + aturan admin untuk nominal ini (ditunda sebentar sesudah mengetik). Penjualan: hanya aturan.
  useEffect(() => {
    const id = ++urut.current;
    if (!keterangan && !nominal) { setSaran(null); setKeluarga(null); return undefined; }
    const t = setTimeout(async () => {
      // U5: keterangan dikirim untuk semua jenis (jenis catatan dan kontak terdeteksi dari sana); tebakan amplop
      // tetap hanya dipakai untuk pengeluaran.
      const s = await api.saranCatat({ description: keterangan, amount: nominal || undefined, jenis });
      if (id !== urut.current) return;
      setSaran(s);
      const terdeteksi = jenisTerdeteksi(s, jenisBoleh);
      if (terdeteksi && !manual.current && terdeteksi !== jenis) { setJenis(terdeteksi); setPilihan(null); }
      let k = null;
      if (perluCekPribadi({ jenis, keterangan, saran: s })) {
        k = await api.saranCatat({ description: keterangan }, { ruangKeluarga: true });
        if (id !== urut.current) return;
      }
      setKeluarga(k);
    }, JEDA_SARAN_MS);
    return () => clearTimeout(t);
  }, [keterangan, nominal, jenis]);

  useEffect(() => { setAbaikanPribadi(false); setTanpaKontak(false); }, [keterangan]);
  // Kotak dikosongkan = mulai lagi dari tebakan. Jenis yang dipindahkan deteksi ikut kembali; pilihan user sendiri tetap.
  useEffect(() => {
    if (teks.trim()) return;
    setPilihan(null);
    if (!manual.current && !terkunci) setJenis(jenisMula);
  }, [teks]);

  const amplopId = amplopDipakai(pilihan, jenis === 'pengeluaran' ? saran : null);
  const pilihanAmplop = amplopPilihan(daftar, jenis, jenis === 'pengeluaran' ? saran?.envelope_id : null);
  const amplop = pilihanAmplop.find(e => e.id === amplopId) || null;
  const aturan = aturanCatatan(saran?.aturan);
  const ajari = pesanAjari({ jenis, keterangan, saran, amplopId, namaRuang });
  // Tawaran tidak muncul selama hasil Simpan ke ruang usaha belum pasti; tetap tampil (untuk kirim ulang) bila jalur
  // pribadi yang belum pasti.
  const pribadi = terkunci === 'pribadi'
    || (!terkunci && !abaikanPribadi && jenis === 'pengeluaran' && tawaranPribadi(keluarga));
  const dariTebakan = amplopId && !pilihan && saran?.envelope_id === amplopId;
  // U5: kontak terdeteksi untuk jenis ini; form Fitur Tambahan untuk penjualan atas nama pelanggan, modal, pinjaman.
  const kontak = tanpaKontak ? null : kontakCatatan(jenis, saran);
  const lain = jenisLain(saran);
  const labelFormLain = lain && formPlugin ? formPlugin(lain.id) : null;
  const labelFormPelanggan = jenis === 'penjualan' && kontak && formPlugin ? formPlugin('penjualan') : null;
  const bukaFormPlugin = (j) => onFormPlugin?.(j, isiFormPlugin({ jenis: j, nominal, keterangan, kontak }));

  // Kirim satu jalur. Selama hasil jalur ini belum pasti, kirim ulang memakai permintaan yang sama persis.
  const kirim = async (jalur, buat) => {
    if (saving || suaraSibuk || (terkunci && terkunci !== jalur)) return;
    const k = terkunci === jalur && kiriman.current?.jalur === jalur ? kiriman.current : { jalur, ...buat() };
    kiriman.current = k;
    setSaving(true);
    setGalat('');
    const r = jalur === 'pribadi' ? await api.catatDiRuangKeluarga(k.body) : await api.catatKaryawan(k.path, k.body);
    let hasil = hasilCatat(r.status, r.data);
    setSaving(false);
    if (hasil.hasil === 'galat') {
      setTerkunci(hasilTidakPasti(r.status, r.data) ? jalur : null);
      setGalat(hasil.pesan);
      return;
    }
    setTerkunci(null);
    if (jalur === 'pribadi') hasil = hasilPribadi(hasil, r.data, k.keluarga);
    window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
    if (hasil.hasil === 'menunggu') window.dispatchEvent(new CustomEvent('jatahku:draf-baru'));
    onDone?.(hasil);
  };

  const simpan = (e) => {
    e.preventDefault();
    if (terkunci !== 'usaha') {
      const salah = galatCatat({ nominal, amplopId: amplop ? amplopId : null, tahan: aturan.tahan });
      if (salah) { setGalat(salah); return; }
    }
    kirim('usaha', () => {
      const p = payloadCatat({ jenis, nominal, keterangan, amplopId, clientRef: refUsaha });
      const tambahan = jenis === 'pengeluaran' ? tambahanKontak(isianPlugin, kontak, amplop) : null;
      return tambahan ? { ...p, body: { ...p.body, tambahan } } : p;
    });
  };

  const catatPribadi = () => {
    if (!nominal && terkunci !== 'pribadi') { setGalat('Tulis nominalnya dulu, mis. "pulsa 50rb".'); return; }
    kirim('pribadi', () => ({
      keluarga,
      body: { envelope_id: keluarga.envelope_id, amount: Math.round(nominal), description: keterangan || 'Pengeluaran',
        client_ref: refPribadi },
    }));
  };

  if (daftar === null) return <div className="text-center py-8 text-gray-400">Loading...</div>;

  return (
    <form onSubmit={simpan} className="space-y-4">
      {jenisBoleh.length > 1 && (
        <div role="radiogroup" aria-label="Jenis catatan" className="grid grid-cols-2 gap-2">
          {jenisBoleh.map(j => (
            <button key={j} type="button" role="radio" aria-checked={jenis === j}
              onClick={() => { manual.current = true; setJenisManual(true); setJenis(j); setPilihan(null); }} disabled={!!terkunci}
              className="rounded-xl py-2.5 text-sm font-semibold border transition-colors"
              style={jenis === j
                ? { background: 'var(--brand-50, rgba(29,158,117,0.12))', borderColor: 'var(--brand-400)', color: 'var(--brand-600)' }
                : { borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
              {LABEL[j]}
            </button>
          ))}
        </div>
      )}

      <div>
        <label className="label" htmlFor="catat-cepat">Tulis seperti chat</label>
        <div className="flex items-start gap-2">
          <textarea id="catat-cepat" rows={2} maxLength={200} autoFocus autoComplete="off"
            className="input flex-1 resize-none"
            placeholder={jenis === 'penjualan' ? 'nasi box 30 pax 900rb' : 'kardus 50 pcs 125rb'}
            value={teks} onChange={e => setTeks(e.target.value)} readOnly={!!terkunci}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} />
          <VoiceInput disabled={saving || !!terkunci} onBusyChange={setSuaraSibuk} onError={setGalat}
            onTranscript={(t) => setTeks(v => (v.trim() ? `${v.trim()} ${t}` : t))} />
        </div>
      </div>

      {(nominal > 0 || keterangan) && (
        <div className="rounded-xl px-4 py-2" style={{ background: 'var(--page)', border: '1px solid var(--border)' }}
          aria-live="polite">
          <p className="text-xs font-semibold uppercase tracking-wide pt-1" style={{ color: 'var(--text-muted)' }}>Terdeteksi</p>
          <Baris label="Jenis">
            {LABEL[jenis]}
            {!jenisManual && jenis !== jenisMula && (
              <span className="block text-xs" style={{ color: 'var(--text-muted)' }}>dari kata di catatanmu</span>
            )}
          </Baris>
          <Baris label="Nominal">{nominal > 0 ? <b className="font-mono">{rp(nominal)}</b> : <span style={{ color: '#DC2626' }}>belum ada</span>}</Baris>
          <Baris label="Keterangan">{keterangan || '—'}</Baris>
          <Baris label="Amplop">
            {amplop ? (
              <span className="inline-flex flex-col items-end">
                <span className="inline-flex items-center gap-1.5 font-semibold"><EnvelopeIcon value={amplop.emoji} size={16} /> {amplop.name}</span>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {dariTebakan ? labelSumber(saran?.sumber, namaRuang) : 'Dipilih sendiri'}
                </span>
              </span>
            ) : <span style={{ color: 'var(--text-muted)' }}>pilih di bawah</span>}
          </Baris>
          {kontak && (
            <Baris label={LABEL_KONTAK[kontak.peran]}>
              <span className="inline-flex flex-col items-end">
                <span className="font-semibold">{kontak.nama}</span>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  dari Kontak ·{' '}
                  <button type="button" className="underline" disabled={!!terkunci} onClick={() => setTanpaKontak(true)}>
                    bukan {LABEL_KONTAK[kontak.peran].toLowerCase()} ini
                  </button>
                </span>
              </span>
            </Baris>
          )}
        </div>
      )}

      {!terkunci && (labelFormLain || labelFormPelanggan) && (
        <div role="status" className="rounded-xl px-4 py-3 text-sm border"
          style={{ borderColor: 'var(--border)', background: 'var(--page)', color: 'var(--text)' }}>
          {labelFormLain ? (
            <p>Sepertinya ini <b>{lain.label}</b>, bukan penjualan atau pengeluaran. Catat lewat form {labelFormLain} supaya tidak dihitung sebagai omzet.</p>
          ) : (
            <p>Supaya tercatat atas nama <b>{kontak.nama}</b> dan dibagi menurut alokasi omzet, lanjutkan di form {labelFormPelanggan}.</p>
          )}
          <button type="button" onClick={() => bukaFormPlugin(labelFormLain ? lain.id : 'penjualan')}
            className="btn-outline text-sm mt-2">
            Lanjut di form {labelFormLain || labelFormPelanggan}
          </button>
        </div>
      )}

      {pribadi && (
        <div role="status" className="rounded-xl px-4 py-3 text-sm border"
          style={{ borderColor: 'rgba(217,119,6,0.35)', background: 'rgba(217,119,6,0.08)', color: 'var(--text)' }}>
          <p>
            Sepertinya pengeluaran pribadi: biasanya kamu mencatat "{keterangan}" di <b>{(kiriman.current?.keluarga || keluarga)?.envelope_name}</b>.
            Catat di ruang keluargamu?
          </p>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Hanya kamu yang melihat tawaran ini.</p>
          <div className="flex flex-wrap gap-2 mt-2">
            <button type="button" onClick={catatPribadi} disabled={saving} className="btn-primary text-sm disabled:opacity-50">
              Catat di ruang keluarga
            </button>
            {!terkunci && (
              <button type="button" onClick={() => setAbaikanPribadi(true)} className="btn-outline text-sm">Tetap di {namaRuang}</button>
            )}
          </div>
        </div>
      )}

      <fieldset>
        <legend className="label">Amplop</legend>
        {pilihanAmplop.length === 0 ? (
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Belum ada amplop yang bisa dipakai untukmu di ruang ini. Hubungi admin ruang.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto">
            {pilihanAmplop.map(env => {
              const aktif = amplopId === env.id;
              return (
                <label key={env.id}
                  className="flex items-center gap-2 rounded-xl border px-3 py-2 text-sm cursor-pointer min-w-0"
                  style={aktif
                    ? { borderColor: 'var(--brand-400)', color: 'var(--text)', background: 'rgba(29,158,117,0.08)' }
                    : { borderColor: 'var(--border)', color: 'var(--text)' }}>
                  <input type="radio" name="amplop" className="sr-only" checked={aktif} disabled={!!terkunci}
                    onChange={() => setPilihan(env.id)} />
                  <EnvelopeIcon value={env.emoji} size={18} />
                  <span className="truncate flex-1">{env.name}</span>
                  {jenis === 'pengeluaran' && saran?.envelope_id === env.id && (
                    <span className="shrink-0 inline-flex" style={{ color: 'var(--brand-600)' }} title="Tebakan">
                      <Icon name="bulb" size={14} />
                      <span className="sr-only">tebakan</span>
                    </span>
                  )}
                </label>
              );
            })}
          </div>
        )}
        {jenis === 'penjualan' && pilihanAmplop.length > 0 && (
          <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>Seluruh penjualan masuk ke amplop ini.</p>
        )}
        {ajari && <p className="text-xs mt-2 flex gap-1.5" style={{ color: 'var(--text-muted)' }}><Icon name="info" size={14} /> {ajari}</p>}
      </fieldset>

      {aturan.daftar.length > 0 && (
        <div className="rounded-xl px-4 py-3 text-sm border" style={{ borderColor: 'var(--border)' }}>
          <p className="text-xs font-semibold mb-1" style={{ color: 'var(--text-muted)' }}>Aturan admin untuk catatan ini</p>
          <ul className="list-disc pl-5 space-y-0.5" style={{ color: 'var(--text)' }}>
            {aturan.daftar.map(t => <li key={t}>{t}</li>)}
          </ul>
          {aturan.tahan && <p className="text-xs mt-2" style={{ color: '#DC2626' }}>{aturan.tahan}</p>}
        </div>
      )}

      {galat && (
        <div role="alert" className="rounded-xl px-4 py-3 text-sm border" style={{ color: '#DC2626', borderColor: 'rgba(220,38,38,0.3)', background: 'rgba(220,38,38,0.06)' }}>
          {galat}
          {terkunci && <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{pesanTerkunci(terkunci, namaRuang)}</p>}
        </div>
      )}

      <div className="flex gap-2">
        <button type="button" onClick={onCancel} className="btn-outline flex-1">Batal</button>
        <button type="submit"
          disabled={saving || suaraSibuk || terkunci === 'pribadi'
            || (terkunci !== 'usaha' && (pilihanAmplop.length === 0 || !!aturan.tahan))}
          className="btn-primary flex-1 disabled:opacity-50">
          {saving ? '...' : aturan.persetujuan ? 'Kirim untuk persetujuan' : `Simpan ke ${namaRuang}`}
        </button>
      </div>
      {onFormLengkap && (
        <button type="button" onClick={() => onFormLengkap(jenis)} className="text-sm font-semibold"
          style={{ color: 'var(--brand-600)' }}>
          Form lengkap (tanggal, foto struk, beberapa item)
        </button>
      )}
    </form>
  );
}
