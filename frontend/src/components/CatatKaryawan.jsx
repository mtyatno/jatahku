// Catat untuk karyawan ruang usaha (Plugin R6; desain A2 butir 12, 15, 16). Satu pintu Catat: pengeluaran atau
// penjualan sesuai `jenis_catatan` dari admin, ke amplop yang diizinkan. Form lain (Catat pengeluaran biasa, Income)
// memanggil endpoint yang tertutup untuk karyawan (ringkasan saldo, alokasi, scan), jadi karyawan memakai form ini.
// Lembar Catat cepat dengan deteksi otomatis dan kamus ruang menggantikannya di R7.
//
// Server menegakkan semua batasan; di sini hanya menampilkan jawabannya. Di atas batas nominal server menjawab 202
// dan catatan menjadi draf "Menunggu persetujuan". `client_ref` dibuat sekali per form, jadi menekan Simpan lagi
// sesudah koneksi putus tidak mencatat dua kali.
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { parseAmount } from '../lib/parseAmount';
import { hasilCatat, payloadCatat } from '../lib/ruangPeran';
import { EnvelopeIcon } from './Icon';

const LABEL = { pengeluaran: 'Pengeluaran', penjualan: 'Penjualan' };

function buatRef() {
  try { return crypto.randomUUID(); } catch { return `k${Date.now()}${Math.random().toString(36).slice(2, 10)}`; }
}

export default function CatatKaryawan({ jenisAwal = 'pengeluaran', jenisBoleh = ['pengeluaran'], onDone, onCancel }) {
  const [jenis, setJenis] = useState(jenisBoleh.includes(jenisAwal) ? jenisAwal : jenisBoleh[0]);
  const [teksNominal, setTeksNominal] = useState('');
  const [keterangan, setKeterangan] = useState('');
  const [amplop, setAmplop] = useState(null);
  const [daftar, setDaftar] = useState(null);
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');
  const [clientRef] = useState(buatRef);

  useEffect(() => {
    let live = true;
    api.getEnvelopes().then(list => {
      if (!live) return;
      const rows = Array.isArray(list) ? list : [];
      setDaftar(rows);
      if (rows.length === 1) setAmplop(rows[0].id);
    });
    return () => { live = false; };
  }, []);

  const nominal = parseAmount(teksNominal || '')?.amount || 0;

  const simpan = async (e) => {
    e.preventDefault();
    if (saving) return;
    if (!nominal) { setGalat('Isi nominalnya dulu, mis. 125rb.'); return; }
    if (!amplop) { setGalat('Pilih amplopnya dulu.'); return; }
    setSaving(true);
    setGalat('');
    const { path, body } = payloadCatat({ jenis, nominal, keterangan, amplopId: amplop, clientRef });
    const { status, data } = await api.catatKaryawan(path, body);
    const hasil = hasilCatat(status, data);
    setSaving(false);
    if (hasil.hasil === 'galat') { setGalat(hasil.pesan); return; }
    window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
    if (hasil.hasil === 'menunggu') window.dispatchEvent(new CustomEvent('jatahku:draf-baru'));
    onDone?.(hasil);
  };

  if (daftar === null) return <div className="text-center py-8 text-gray-400">Loading...</div>;

  return (
    <form onSubmit={simpan} className="space-y-4">
      {jenisBoleh.length > 1 && (
        <div role="radiogroup" aria-label="Jenis catatan" className="grid grid-cols-2 gap-2">
          {jenisBoleh.map(j => (
            <button key={j} type="button" role="radio" aria-checked={jenis === j} onClick={() => setJenis(j)}
              className="rounded-xl py-2.5 text-sm font-semibold border transition-colors"
              style={jenis === j
                ? { background: 'var(--brand-50, rgba(29,158,117,0.12))', borderColor: 'var(--brand-400)', color: 'var(--brand-600)' }
                : { borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
              {LABEL[j]}
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor="catat-nominal">Nominal</label>
          <input id="catat-nominal" className="input font-mono" inputMode="text" autoComplete="off" autoFocus
            placeholder="125rb" value={teksNominal} onChange={e => setTeksNominal(e.target.value)} />
          {nominal > 0 && (
            <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Rp{nominal.toLocaleString('id-ID')}</p>
          )}
        </div>
        <div>
          <label className="label" htmlFor="catat-ket">Keterangan</label>
          <input id="catat-ket" className="input" maxLength={200} value={keterangan}
            placeholder={jenis === 'penjualan' ? 'nasi box 30 pax' : 'kardus 50 pcs'}
            onChange={e => setKeterangan(e.target.value)} />
        </div>
      </div>

      <fieldset>
        <legend className="label">Amplop</legend>
        {daftar.length === 0 ? (
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Admin belum mengizinkan amplop apa pun untukmu. Hubungi admin ruang ini.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto">
            {daftar.map(env => (
              <label key={env.id}
                className="flex items-center gap-2 rounded-xl border px-3 py-2 text-sm cursor-pointer"
                style={amplop === env.id
                  ? { borderColor: 'var(--brand-400)', color: 'var(--text)', background: 'rgba(29,158,117,0.08)' }
                  : { borderColor: 'var(--border)', color: 'var(--text)' }}>
                <input type="radio" name="amplop" className="sr-only" checked={amplop === env.id}
                  onChange={() => setAmplop(env.id)} />
                <EnvelopeIcon value={env.emoji} size={18} />
                <span className="truncate">{env.name}</span>
              </label>
            ))}
          </div>
        )}
        {jenis === 'penjualan' && daftar.length > 0 && (
          <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>Seluruh penjualan masuk ke amplop ini.</p>
        )}
      </fieldset>

      {galat && (
        <div role="alert" className="rounded-xl px-4 py-3 text-sm border" style={{ color: '#DC2626', borderColor: 'rgba(220,38,38,0.3)', background: 'rgba(220,38,38,0.06)' }}>
          {galat}
        </div>
      )}

      <div className="flex gap-2">
        <button type="button" onClick={onCancel} className="btn-outline flex-1">Batal</button>
        <button type="submit" disabled={saving || daftar.length === 0} className="btn-primary flex-1 disabled:opacity-50">
          {saving ? '...' : 'Simpan'}
        </button>
      </div>
      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
        Catatan di atas batas dari admin akan menunggu persetujuan dulu.
      </p>
    </form>
  );
}
