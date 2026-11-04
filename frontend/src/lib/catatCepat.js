// Catat cepat di ruang usaha (Plugin R7; 05-desain-buku-usaha.md B3.2 butir 2, 5, 7; A2 butir 12–17).
//
// Satu kotak teks seperti chat ("kardus 50 pcs 125rb"): nominal dan keterangan diurai di perangkat (parseAmount.js,
// kasusnya sama dengan bot), amplop ditebak server (`POST /transactions/suggest-envelope`, ruang dari header) dengan
// urutan kata user → kamus ruang → kamus kategori. Server menegakkan semua batasan; di sini hanya tampilan.
//
// Tawaran "pengeluaran pribadi" (keputusan R7 B): bila tebakan di ruang usaha tidak berasal dari kata user atau kamus
// ruang, klien bertanya ke ruang keluarga user sendiri (permintaan TANPA header ruang = ruang keluarga). Tawaran
// muncul hanya bila jawabannya kata yang diajarkan user itu sendiri. Server tidak pernah menggabungkan dua ruang dalam
// satu kueri (AGENTS.md aturan 8), dan tawaran ini tidak tersimpan di mana pun.
import { parseAmount } from './parseAmount.js';

export const SUMBER_DIKENAL = new Set(['kata_saya', 'kamus_ruang']);
export const JEDA_SARAN_MS = 350;

/** Teks Catat cepat → { nominal, keterangan }. Tanpa nominal: seluruh teks menjadi keterangan. */
export function uraiCatatan(teks) {
  const t = (teks || '').trim();
  if (!t) return { nominal: 0, keterangan: '' };
  const p = parseAmount(t);
  if (!p || !p.amount) return { nominal: 0, keterangan: t };
  const ket = (p.description || '').trim();
  return { nominal: p.amount, keterangan: ket === 'Pengeluaran' ? '' : ket };
}

/** Asal tebakan amplop dalam kalimat pendek (desain A2 butir 13: kartu Terdeteksi selalu menyebut sumbernya). */
export function labelSumber(sumber, namaRuang = 'ruang ini') {
  if (!sumber?.jenis) return '';
  const kali = sumber.kali ? ` · ${sumber.kali}×` : '';
  switch (sumber.jenis) {
    case 'kata_saya': return `Kata yang kamu ajarkan${kali}`;
    case 'kamus_ruang': {
      // Karyawan menerima kamus ruang tanpa pengajar dan hitungan (review keamanan PR #191 temuan 2).
      if (!('oleh_saya' in sumber) && !('diajarkan_oleh' in sumber)) return `Kamus ${namaRuang}`;
      const oleh = sumber.oleh_saya ? 'kamu' : (sumber.diajarkan_oleh || 'anggota');
      return `Kamus ${namaRuang} · diajarkan ${oleh}${kali}`;
    }
    case 'kamus_plugin': return 'Kamus Fitur Tambahan';
    case 'kamus_kategori': return 'Kamus kategori bawaan';
    case 'nama_amplop': return 'Nama amplop di catatanmu';
    default: return '';
  }
}

/** Perlu bertanya ke ruang keluarga? Hanya untuk pengeluaran berketerangan yang tebakannya tidak dari kata user atau
 *  kamus ruang (kata yang sudah dikenal ruang ini tidak pernah memicu tawaran). */
export function perluCekPribadi({ jenis, keterangan, saran }) {
  if (jenis !== 'pengeluaran' || !(keterangan || '').trim()) return false;
  return !SUMBER_DIKENAL.has(saran?.sumber?.jenis);
}

/** Tawaran "pengeluaran pribadi": jawaban ruang keluarga berasal dari kata user sendiri dan yakin. */
export function tawaranPribadi(saranKeluarga) {
  return !!(saranKeluarga?.envelope_id && saranKeluarga.confident && saranKeluarga.sumber?.jenis === 'kata_saya');
}

/** Catatan ini akan mengajari kamus ruang? (desain A2 butir 14). Hanya pengeluaran berketerangan ke amplop yang
 *  berbeda dari tebakan kamus/kata yang sudah dikenal (koreksi atau kata baru). */
export function pesanAjari({ jenis, keterangan, saran, amplopId, namaRuang = 'ruang ini' }) {
  if (jenis !== 'pengeluaran' || !(keterangan || '').trim() || !amplopId) return '';
  if (saran?.envelope_id === amplopId && SUMBER_DIKENAL.has(saran?.sumber?.jenis)) return '';
  return `Kata ini masuk kamus ${namaRuang} untuk semua anggota. Admin bisa menghapusnya; tidak dipakai di ruang keluarga.`;
}

/** Aturan admin untuk catatan ini (dari server) + apa artinya di Catat cepat. Foto nota belum bisa dilampirkan di
 *  sini (keputusan R7 D), jadi catatan di atas batas foto akan ditolak server: Simpan ditahan dengan alasannya. */
export function aturanCatatan(aturan) {
  const daftar = Array.isArray(aturan) ? aturan : [];
  const foto = daftar.some(a => a?.kode === 'foto_nota');
  return {
    daftar: daftar.map(a => a.teks).filter(Boolean),
    tahan: foto ? 'Foto nota belum bisa dilampirkan dari Catat cepat. Minta admin mencatatnya, atau kecilkan nominalnya.' : '',
    persetujuan: daftar.some(a => a?.kode === 'persetujuan'),
  };
}

/** Amplop yang dipakai: pilihan user, atau tebakan server bila user belum memilih. */
export const amplopDipakai = (pilihan, saran) => pilihan || saran?.envelope_id || null;

/** Galat sebelum kirim (null = boleh kirim). */
export function galatCatat({ nominal, amplopId, tahan }) {
  if (!nominal) return 'Tulis nominalnya, mis. "kardus 50 pcs 125rb".';
  if (!amplopId) return 'Pilih amplopnya dulu.';
  if (tahan) return tahan;
  return null;
}

// Amplop tabungan dan dana berkala bukan tujuan pengeluaran langsung (server: `expense_rules.is_spendable`).
const BUKAN_PENGELUARAN = new Set(['saving', 'sinking_fund']);

/** Amplop yang bisa dipilih untuk jenis catatan ini, tebakan server di depan. */
export function amplopPilihan(daftar, jenis, saranId = null) {
  const rows = (Array.isArray(daftar) ? daftar : []).filter(e => jenis !== 'pengeluaran' || !BUKAN_PENGELUARAN.has(e?.purpose));
  if (!saranId) return rows;
  return [...rows.filter(e => e.id === saranId), ...rows.filter(e => e.id !== saranId)];
}

// ── Kiriman dan jawabannya (review keamanan PR #191 temuan 1) ───────────────
// Simpan ke ruang usaha dan "Catat di ruang keluarga" adalah dua catatan berbeda: masing-masing memakai `client_ref`
// sendiri, dan selama hasil satu jalur belum pasti, jalur lain ditutup dan isian dikunci (kirim ulang = permintaan
// yang sama persis, server menjawab catatan yang sudah ada; ref yang dipakai catatan lain → 409 `client_ref_bentrok`).

/** Hasil kiriman belum pasti (mungkin sudah tercatat): koneksi putus, sedang diproses, atau galat server. */
export function hasilTidakPasti(status, data) {
  return status === 0 || status >= 500 || (status === 409 && data?.kode !== 'client_ref_bentrok');
}

/** Jawaban "Catat di ruang keluarga" → hasil yang ditampilkan. Kalimat "di ruang keluargamu" hanya bila server
 *  menjawab transaksi di amplop ruang keluarga itu; jawaban lain (mis. draf 202) ditampilkan apa adanya. */
export function hasilPribadi(hasil, data, keluarga) {
  if (hasil?.hasil === 'tercatat' && keluarga?.envelope_id && data?.envelope_id === keluarga.envelope_id) {
    return { hasil: 'tercatat', pesan: `Tercatat di ruang keluargamu (${keluarga.envelope_name})` };
  }
  return hasil;
}

/** Keterangan saat isian dikunci karena hasil jalur ini belum pasti. */
export function pesanTerkunci(jalur, namaRuang = 'ruang ini') {
  if (jalur === 'usaha') return `Isian dikunci sampai hasilnya pasti. Tekan "Simpan ke ${namaRuang}" lagi; tidak akan tercatat dua kali.`;
  if (jalur === 'pribadi') return 'Isian dikunci sampai hasilnya pasti. Tekan "Catat di ruang keluarga" lagi; tidak akan tercatat dua kali.';
  return '';
}
