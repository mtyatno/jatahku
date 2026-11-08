// Isian field Fitur Tambahan di form inti (Plugin U2; manifest `form_fields`, `GET /plugins/contributions`).
//
// Host menggambar `text`, `number`, dan `select` (pilihan dari manifest). Field `reference` butuh data plugin, jadi
// digambar komponen modul web plugin itu (`isian['<target>.<key>']` di `src/plugins/<id>`); tanpa komponen, field itu
// tidak tampil. Nilai dikirim sebagai `tambahan` (`pluginHost.bodyTambahan`); server yang memeriksa dan menyimpan
// (`titik.periksa_field` + `simpan_field`). Karyawan tidak pernah mendapat field plugin (kontribusi kosong).
import { Suspense } from 'react';
import { webPlugin } from './index';

export default function IsianPlugin({ fields, nilai, onChange, disabled = false }) {
  const tampil = (fields || []).filter(f => f.type !== 'reference' || webPlugin(f.plugin)?.isian?.[`${f.target}.${f.key}`]);
  if (!tampil.length) return null;
  const ubah = (f) => (v) => onChange({ ...nilai, [`${f.plugin}.${f.key}`]: v });
  return (
    <div className="grid gap-3 sm:grid-cols-2" aria-label="Isian Fitur Tambahan">
      {tampil.map(f => {
        const kunci = `${f.plugin}.${f.key}`;
        const id = `isian-${f.plugin}-${f.key}`;
        const v = nilai?.[kunci] ?? '';
        let isi;
        if (f.type === 'reference') {
          const Komponen = webPlugin(f.plugin).isian[`${f.target}.${f.key}`];
          isi = (
            <Suspense fallback={<select className="input" disabled><option>Memuat…</option></select>}>
              <Komponen id={id} field={f} nilai={v} onChange={ubah(f)} />
            </Suspense>
          );
        } else if (f.type === 'select') {
          isi = (
            <select id={id} className="input" value={v} disabled={disabled} onChange={e => ubah(f)(e.target.value || null)}>
              <option value="">Tidak diisi</option>
              {f.options.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          );
        } else {
          isi = (
            <input id={id} className="input" value={v} disabled={disabled} maxLength={200}
              inputMode={f.type === 'number' ? 'decimal' : undefined} onChange={e => ubah(f)(e.target.value)} />
          );
        }
        return (
          <div key={kunci}>
            <label htmlFor={id} className="label">{f.label} <span className="font-normal text-gray-400">(opsional)</span></label>
            {isi}
          </div>
        );
      })}
    </div>
  );
}
