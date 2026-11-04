// Lembar Catat cepat di ruang usaha (Plugin R7; artboard "Karyawan: Catat cepat dengan deteksi otomatis", desain
// B3.2 butir 2, A2 butir 12–17). Satu kotak teks seperti chat → kartu Terdeteksi (jenis, nominal, keterangan, amplop
// dan sumber tebakannya) → koreksi bila perlu → simpan. Menggantikan form Catat karyawan R6; untuk pemilik dan admin
// ruang usaha juga pintu Catat utama, dengan tautan ke form lengkap.
//
// Server menegakkan semua batasan (aturan admin di kartu hanya tampilan). Koreksi amplop mengajari kamus ruang ini
// (server, hanya catatan bukan-privat). Tawaran "pengeluaran pribadi" bertanya ke ruang keluarga user sendiri lewat
// permintaan terpisah tanpa header ruang; tidak tersimpan dan tidak terlihat admin (lib/catatCepat.js).
// `client_ref` dibuat sekali per lembar: menekan Simpan lagi sesudah koneksi putus tidak mencatat dua kali.
import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import {
  JEDA_SARAN_MS, amplopDipakai, amplopPilihan, aturanCatatan, galatCatat, labelSumber, perluCekPribadi, pesanAjari,
  tawaranPribadi, uraiCatatan,
} from '../lib/catatCepat';
import { hasilCatat, payloadCatat } from '../lib/ruangPeran';
import { EnvelopeIcon, Icon } from './Icon';
import VoiceInput from './VoiceInput';

const LABEL = { pengeluaran: 'Pengeluaran', penjualan: 'Penjualan' };
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
}) {
  const namaRuang = ruang?.nama || 'ruang ini';
  const [jenis, setJenis] = useState(jenisBoleh.includes(jenisAwal) ? jenisAwal : jenisBoleh[0]);
  const [teks, setTeks] = useState('');
  const [daftar, setDaftar] = useState(null);
  const [pilihan, setPilihan] = useState(null);         // amplop dipilih user (null = pakai tebakan)
  const [saran, setSaran] = useState(null);
  const [keluarga, setKeluarga] = useState(null);       // jawaban ruang keluarga (tawaran pribadi)
  const [abaikanPribadi, setAbaikanPribadi] = useState(false);
  const [saving, setSaving] = useState(false);
  const [suaraSibuk, setSuaraSibuk] = useState(false);
  const [galat, setGalat] = useState('');
  const [clientRef] = useState(buatRef);
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
      const desc = jenis === 'pengeluaran' ? keterangan : '';
      const s = await api.saranCatat({ description: desc, amount: nominal || undefined });
      if (id !== urut.current) return;
      setSaran(s);
      let k = null;
      if (perluCekPribadi({ jenis, keterangan, saran: s })) {
        k = await api.saranCatat({ description: keterangan }, { ruangKeluarga: true });
        if (id !== urut.current) return;
      }
      setKeluarga(k);
    }, JEDA_SARAN_MS);
    return () => clearTimeout(t);
  }, [keterangan, nominal, jenis]);

  useEffect(() => { setAbaikanPribadi(false); }, [keterangan]);
  useEffect(() => { if (!teks.trim()) setPilihan(null); }, [teks]);   // kotak dikosongkan = mulai lagi dari tebakan

  const amplopId = amplopDipakai(pilihan, jenis === 'pengeluaran' ? saran : null);
  const pilihanAmplop = amplopPilihan(daftar, jenis, jenis === 'pengeluaran' ? saran?.envelope_id : null);
  const amplop = pilihanAmplop.find(e => e.id === amplopId) || null;
  const aturan = aturanCatatan(saran?.aturan);
  const ajari = pesanAjari({ jenis, keterangan, saran, amplopId, namaRuang });
  const pribadi = !abaikanPribadi && jenis === 'pengeluaran' && tawaranPribadi(keluarga);
  const dariTebakan = amplopId && !pilihan && saran?.envelope_id === amplopId;

  const kirim = async (fn, sesudah) => {
    if (saving || suaraSibuk) return;
    setSaving(true);
    setGalat('');
    const r = await fn();
    const hasil = hasilCatat(r.status, r.data);
    setSaving(false);
    if (hasil.hasil === 'galat') { setGalat(hasil.pesan); return; }
    window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
    if (hasil.hasil === 'menunggu') window.dispatchEvent(new CustomEvent('jatahku:draf-baru'));
    onDone?.(sesudah ? sesudah(hasil) : hasil);
  };

  const simpan = (e) => {
    e.preventDefault();
    const salah = galatCatat({ nominal, amplopId: amplop ? amplopId : null, tahan: aturan.tahan });
    if (salah) { setGalat(salah); return; }
    const { path, body } = payloadCatat({ jenis, nominal, keterangan, amplopId, clientRef });
    kirim(() => api.catatKaryawan(path, body));
  };

  const catatPribadi = () => {
    if (!nominal) { setGalat('Tulis nominalnya dulu, mis. "pulsa 50rb".'); return; }
    kirim(() => api.catatDiRuangKeluarga({ envelope_id: keluarga.envelope_id, amount: Math.round(nominal),
      description: keterangan || 'Pengeluaran', client_ref: clientRef }),
    () => ({ hasil: 'tercatat', pesan: `Tercatat di ruang keluargamu (${keluarga.envelope_name})` }));
  };

  if (daftar === null) return <div className="text-center py-8 text-gray-400">Loading...</div>;

  return (
    <form onSubmit={simpan} className="space-y-4">
      {jenisBoleh.length > 1 && (
        <div role="radiogroup" aria-label="Jenis catatan" className="grid grid-cols-2 gap-2">
          {jenisBoleh.map(j => (
            <button key={j} type="button" role="radio" aria-checked={jenis === j}
              onClick={() => { setJenis(j); setPilihan(null); }}
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
            value={teks} onChange={e => setTeks(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} />
          <VoiceInput disabled={saving} onBusyChange={setSuaraSibuk} onError={setGalat}
            onTranscript={(t) => setTeks(v => (v.trim() ? `${v.trim()} ${t}` : t))} />
        </div>
      </div>

      {(nominal > 0 || keterangan) && (
        <div className="rounded-xl px-4 py-2" style={{ background: 'var(--page)', border: '1px solid var(--border)' }}
          aria-live="polite">
          <p className="text-xs font-semibold uppercase tracking-wide pt-1" style={{ color: 'var(--text-muted)' }}>Terdeteksi</p>
          <Baris label="Jenis">{LABEL[jenis]}</Baris>
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
        </div>
      )}

      {pribadi && (
        <div role="status" className="rounded-xl px-4 py-3 text-sm border"
          style={{ borderColor: 'rgba(217,119,6,0.35)', background: 'rgba(217,119,6,0.08)', color: 'var(--text)' }}>
          <p>
            Sepertinya pengeluaran pribadi: biasanya kamu mencatat "{keterangan}" di <b>{keluarga.envelope_name}</b>.
            Catat di ruang keluargamu?
          </p>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Hanya kamu yang melihat tawaran ini.</p>
          <div className="flex flex-wrap gap-2 mt-2">
            <button type="button" onClick={catatPribadi} disabled={saving} className="btn-primary text-sm disabled:opacity-50">
              Catat di ruang keluarga
            </button>
            <button type="button" onClick={() => setAbaikanPribadi(true)} className="btn-outline text-sm">Tetap di {namaRuang}</button>
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
                  <input type="radio" name="amplop" className="sr-only" checked={aktif} onChange={() => setPilihan(env.id)} />
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
        </div>
      )}

      <div className="flex gap-2">
        <button type="button" onClick={onCancel} className="btn-outline flex-1">Batal</button>
        <button type="submit" disabled={saving || suaraSibuk || pilihanAmplop.length === 0 || !!aturan.tahan}
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
