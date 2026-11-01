import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { api } from '../lib/api';
import { jenisLabel, peranLabel, setRuangAktif } from '../lib/ruangAktif';

// Pemilih ruang (Plugin R4; desain 05-desain-buku-usaha.md A2 butir 1): di bawah logo sidebar,
// dan di HP menggantikan logo di header. Hanya tampil bila user punya lebih dari satu ruang atau
// boleh membuat ruang usaha (flag `ruang_usaha_users`); selain itu Layout menampilkan logo seperti biasa.
//
// Berpindah ruang memuat ulang aplikasi di Beranda: semua data (Beranda, menu, cache offline, chat)
// dimuat ulang untuk ruang baru, tanpa sisa state ruang sebelumnya.

function pindah(id, bawaan) {
  setRuangAktif(id, { bawaan });
  window.location.assign('/');
}

function RuangIcon({ jenis, size = 18 }) {
  return <Icon name={jenis === 'usaha' ? 'store' : 'home'} size={size} />;
}

function BuatRuang({ onBatal }) {
  const [nama, setNama] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    if (!nama.trim() || saving) return;
    setSaving(true);
    setError('');
    const { ok, data } = await api.buatRuang(nama.trim());
    if (ok && data?.id) { pindah(data.id, null); return; }
    setSaving(false);
    setError(typeof data?.detail === 'string' ? data.detail : 'Gagal membuat ruang. Coba lagi.');
  };
  return (
    <form onSubmit={submit} className="px-3 py-2 flex flex-col gap-2">
      <label className="text-[13px] font-semibold" style={{ color: 'var(--text)' }} htmlFor="ruang-baru-nama">
        Nama ruang usaha
      </label>
      <input id="ruang-baru-nama" autoFocus maxLength={60} value={nama} onChange={e => setNama(e.target.value)}
        placeholder="mis. Dapur Nusa" className="input text-sm" />
      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
        Uang usaha dicatat terpisah dari ruang keluargamu. Chat tetap untuk ruang keluarga.
      </p>
      {error && <p className="text-xs" style={{ color: '#DC2626' }}>{error}</p>}
      <div className="flex gap-2">
        <button type="button" onClick={onBatal} className="btn-outline flex-1 text-sm">Batal</button>
        <button type="submit" disabled={saving || !nama.trim()} className="btn-primary flex-1 text-sm disabled:opacity-50">
          {saving ? '...' : 'Buat'}
        </button>
      </div>
    </form>
  );
}

export default function RuangPicker({ pilihan, variant = 'sidebar' }) {
  const [open, setOpen] = useState(false);
  const [buat, setBuat] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) { setOpen(false); setBuat(false); } };
    const onKey = (e) => { if (e.key === 'Escape') { setOpen(false); setBuat(false); } };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [open]);

  const { items, aktif, bawaan, bolehBuat } = pilihan;
  if (!aktif) return null;
  const header = variant === 'header';

  return (
    <div className="relative min-w-0" ref={ref}>
      <button type="button" onClick={() => setOpen(o => !o)} aria-haspopup="menu" aria-expanded={open}
        aria-label={`Ruang aktif: ${aktif.nama}. Ganti ruang`}
        className={`w-full min-w-0 flex items-center gap-2 rounded-xl transition-colors hover:bg-black/5 ${header ? 'px-2 py-1.5' : 'px-3 py-2'}`}
        style={header ? { color: 'var(--text)' } : { color: 'var(--text)', background: 'var(--card-bg)', border: '1px solid var(--border)' }}>
        <span className="shrink-0 w-7 h-7 rounded-lg inline-flex items-center justify-center"
          style={{ background: aktif.jenis === 'usaha' ? 'rgba(245,184,74,0.18)' : 'rgba(29,158,117,0.12)' }}>
          <RuangIcon jenis={aktif.jenis} size={16} />
        </span>
        <span className="min-w-0 flex-1 text-left">
          <span className="block truncate text-[14px] font-bold leading-tight">{aktif.nama}</span>
          {!header && (
            <span className="block truncate text-[12px] leading-tight" style={{ color: 'var(--text-muted)' }}>
              {jenisLabel(aktif.jenis)}
            </span>
          )}
        </span>
        <Icon name="chevron" size={14} weight="bold" />
      </button>

      {open && (
        <div role="menu" aria-label="Pilih ruang"
          className={`absolute z-[60] mt-2 rounded-xl py-2 shadow-lg ${header ? 'left-0 w-72 max-w-[calc(100vw-2rem)]' : 'left-0 right-0'}`}
          style={{ background: 'var(--card-bg)', border: '1px solid var(--border)' }}>
          {!buat && items.map(r => (
            <button key={r.id} type="button" role="menuitemradio" aria-checked={r.id === aktif.id}
              onClick={() => { setOpen(false); if (r.id !== aktif.id) pindah(r.id, bawaan); }}
              className="w-full text-left px-3 py-2 flex items-center gap-3 hover:bg-black/5" style={{ color: 'var(--text)' }}>
              <RuangIcon jenis={r.jenis} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold">{r.nama}</span>
                <span className="block truncate text-xs" style={{ color: 'var(--text-muted)' }}>
                  {jenisLabel(r.jenis)}{r.jenis === 'usaha' && peranLabel(r.peran) ? ` · ${peranLabel(r.peran)}` : ''}
                </span>
              </span>
              {r.id === aktif.id && <Icon name="check" size={16} weight="bold" />}
            </button>
          ))}
          {!buat && bolehBuat && (
            <div className="border-t mt-1 pt-1" style={{ borderColor: 'var(--border)' }}>
              <button type="button" role="menuitem" onClick={() => setBuat(true)}
                className="w-full text-left px-3 py-2 flex items-center gap-3 text-sm font-semibold hover:bg-black/5"
                style={{ color: 'var(--brand-600)' }}>
                <Icon name="plus" size={18} weight="bold" /> Buat ruang usaha
              </button>
            </div>
          )}
          {buat && <BuatRuang onBatal={() => setBuat(false)} />}
        </div>
      )}
    </div>
  );
}
