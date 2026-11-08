// Isian "Pemasok" di form pengeluaran inti (Plugin U2; manifest `form_fields` transaction.pemasok, `reference` ke
// Kontak). Daftar dari `GET /p/buku_usaha/kontak?peran=pemasok` (ruang dari header); server memeriksa lagi bahwa
// kontaknya pemasok ruang ini (`field_form`), dan menyimpannya di `txn_meta` bersama transaksinya.
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { PLUGIN_ID, rapikanKontak, urutkanKontak } from './bukuUsaha';

export default function PilihPemasok({ field, nilai, onChange, id }) {
  const [daftar, setDaftar] = useState(null);
  useEffect(() => {
    let live = true;
    api.pluginRute(PLUGIN_ID, '/kontak?peran=pemasok').then(r => {
      if (live) setDaftar(r.ok ? urutkanKontak(rapikanKontak(r.data)) : []);
    });
    return () => { live = false; };
  }, []);
  return (
    <select id={id} className="input" value={nilai || ''} onChange={e => onChange(e.target.value || null)}
      disabled={daftar === null} aria-label={field?.label || 'Pemasok'}>
      <option value="">{daftar === null ? 'Memuat…' : daftar.length ? 'Tanpa pemasok' : 'Belum ada pemasok di Kontak'}</option>
      {(daftar || []).map(k => <option key={k.id} value={k.id}>{k.nama}</option>)}
    </select>
  );
}
