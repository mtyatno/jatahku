// Format tampilan tanggal laporan (hanya tampilan; angka tidak dihitung di sini).
const BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

// "2026-10-05" atau ISO datetime → "5 Okt 2026"; tanggal tanpa zona dibaca sebagai tanggal lokal.
export function tanggalTeks(iso) {
  if (!iso) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso));
  if (!m) return '—';
  return `${Number(m[3])} ${BULAN[Number(m[2]) - 1]} ${m[1]}`;
}

export function periodeTeks(mulai, akhir) {
  return `${tanggalTeks(mulai)} – ${tanggalTeks(akhir)}`;
}

// Tanggal singkat untuk sumbu grafik: "2026-10-05" → "5"
export function hariTeks(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  return m ? String(Number(m[3])) : '';
}

// Tanggal terbit (datetime UTC dari server) menurut zona waktu perangkat.
export function terbitTeks(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getDate()} ${BULAN[d.getMonth()]} ${d.getFullYear()}`;
}

// "N hari" untuk angka sorotan; null/kosong → "—" saja (tanpa "— hari"), sama dengan PDF.
export function hariAngka(n) {
  return n === null || n === undefined || n === '' ? '—' : `${n} hari`;
}
