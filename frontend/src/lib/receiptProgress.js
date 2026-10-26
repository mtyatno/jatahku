// Teks tahap proses scan struk & pesan gagal (logika murni, tanpa DOM).
// Dipakai hook progres, kartu status, dan panel chat — semua teks UI ada di sini.

export const STAGE = {
  IDLE: 'idle',
  PREPARING: 'preparing',
  UPLOADING: 'uploading',
  READING: 'reading',
  FAILED: 'failed',
};

// Membaca lebih lama dari ini → tampilkan hint "struk panjang".
export const SLOW_READING_MS = 8000;
// Unggah tanpa laporan progres selama ini → anggap unggah & baca berjalan bersamaan.
export const NO_PROGRESS_MS = 1500;

const GENERIC_FAILURE = 'Scan struk gagal, coba lagi';
// Pembatas laju (slowapi, 30/jam) menjawab 429 dengan {"error": …} tanpa `detail`.
const RATE_LIMITED = 'Terlalu banyak scan. Tunggu sebentar, ya.';

function clampPercent(percent) {
  const n = Math.round(Number(percent) || 0);
  return Math.min(100, Math.max(0, n));
}

// Judul + hint untuk satu tahap. `elapsedMs` = ms sejak tahap ini mulai.
export function stageLabel({ stage, percent = null, progressSeen = false, elapsedMs = 0 }) {
  switch (stage) {
    case STAGE.PREPARING:
      return { title: 'Menyiapkan foto…', hint: null };
    case STAGE.UPLOADING:
      if (progressSeen) return { title: `Mengunggah foto… ${clampPercent(percent)}%`, hint: null };
      // Perangkat/jaringan tidak melaporkan progres: jangan pura-pura persen.
      if (elapsedMs >= NO_PROGRESS_MS) return { title: 'Mengirim dan membaca struk…', hint: null };
      return { title: 'Mengunggah foto…', hint: null };
    case STAGE.READING:
      return {
        title: 'Membaca struk…',
        hint: elapsedMs >= SLOW_READING_MS ? 'Struk panjang butuh waktu lebih lama.' : null,
      };
    default:
      return { title: '', hint: null };
  }
}

const STEPS = [
  { key: 'preparing', label: 'Menyiapkan foto' },
  { key: 'uploading', label: 'Mengunggah' },
  { key: 'reading', label: 'Membaca struk' },
];

// Daftar langkah dengan status: sebelum tahap aktif = done, sesudahnya = todo.
// Tahap di luar tiga langkah (idle/failed) → semua todo.
export function stageSteps(stage) {
  const active = STEPS.findIndex(s => s.key === stage);
  return STEPS.map((s, i) => ({
    ...s,
    state: active < 0 || i > active ? 'todo' : i === active ? 'active' : 'done',
  }));
}

// Pesan gagal per tahap. `stage` = tahap saat gagal.
export function failureMessage({ stage, status = 0, detail = null, timedOut = false }) {
  // Foto tidak bisa disiapkan (format/dekode): mengulang pengiriman tidak membantu.
  if (stage === STAGE.PREPARING) {
    return {
      text: 'Foto tidak bisa dibuka. Coba foto ulang atau pilih format JPG.',
      canRetry: false,
      canRetake: true,
    };
  }

  const code = Number(status) || 0;
  const canRetry = code === 0 || timedOut || code >= 500;
  const canRetake = code !== 429;

  // Server menjawab dengan penolakan: pakai pesannya bila ada.
  if (code >= 400) {
    const hasDetail = typeof detail === 'string' && detail.trim();
    const text = hasDetail ? detail : code === 429 ? RATE_LIMITED : GENERIC_FAILURE;
    return { text, canRetry, canRetake };
  }

  // Tanpa jawaban server: koneksi putus / lewat batas waktu.
  if (stage === STAGE.UPLOADING) {
    const text = timedOut
      ? 'Koneksi lambat, foto belum terkirim. Coba lagi.'
      : 'Foto belum terkirim. Cek koneksi lalu coba lagi.';
    return { text, canRetry, canRetake };
  }
  // Foto sudah sampai; jawabannya yang tak kunjung datang (batas 60 dtk) vs. koneksi putus.
  const text = timedOut
    ? 'Server lama menjawab. Coba lagi.'
    : 'Koneksi terputus saat membaca struk. Coba lagi.';
  return { text, canRetry, canRetake };
}
