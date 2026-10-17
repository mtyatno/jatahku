// Strip AI per kartu di halaman Amplop (S11, 02-aturan.md §7 "Halaman lain: Amplop").
// Isi dari GET /advisor/page/amplop: satu insight terpilih per amplop (atau baris dasar
// "Aman, ±Rp…/hari") — pilihan & teks dari server (select/render), di sini hanya memetakan
// tone ke gaya strip dan memilih tombol. User di luar flag / gagal muat → `legacy`
// (envelopeInsight.js lama, dihapus di S10b).

// Tone server → kunci gaya strip di Envelopes.jsx.
export const STRIP_TONE = { danger: 'danger', warn: 'warning', info: 'info', ok: 'safe' };

// `page`: respons endpoint, null bila gagal. Hasil:
// - { mode: 'legacy' }  — pakai envelopeInsight (flag mati, gagal muat, amplop belum ada di respons);
// - { mode: 'hidden' }  — semua saran amplop ini disembunyikan viewer: tanpa strip;
// - { mode: 'v2', tone, text, detail, actions, dismissKey }.
export function advisorStrip(page, envId, maxActions = 2) {
  const map = page && page.enabled === true ? page.amplop : null;
  if (!map || typeof map !== 'object' || !Object.prototype.hasOwnProperty.call(map, envId)) {
    return { mode: 'legacy' };
  }
  const item = map[envId];
  if (!item) return { mode: 'hidden' };
  return {
    mode: 'v2',
    tone: STRIP_TONE[item.tone] || 'neutral',
    text: item.judul || item.chip || '',
    detail: item.isi || '',
    actions: (Array.isArray(item.aksi) ? item.aksi : []).filter(a => a && a.kind && a.label).slice(0, maxActions),
    dismissKey: item.dismiss?.kunci || null,
  };
}

// Toggle "Dana darurat" di form amplop: hanya untuk tabungan; nilai awal = pilihan tersimpan,
// amplop baru = tebakan nama yang sama dengan backend (metrics.is_emergency_name).
const EMERGENCY_KW = ['darurat', 'emergency'];
export const guessEmergency = (name) => EMERGENCY_KW.some(k => String(name || '').toLowerCase().includes(k));

// Nilai `is_emergency` untuk body PUT/POST /envelopes: null = biarkan server memutuskan
// (amplop baru → tebak nama, ubah → nilai lama); non-tabungan selalu false.
export function emergencyField(purpose, choice) {
  if (purpose !== 'saving' && purpose !== 'sinking_fund') return false;
  return typeof choice === 'boolean' ? choice : null;
}
