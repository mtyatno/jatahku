// Teks tahap proses scan struk & pesan gagal (logika murni, tanpa DOM).
// Dipakai hook progres, kartu status, tombol pilih file, dan panel chat — semua teks UI ada di sini.
//
// Kata benda (`noun`): 'struk' (bawaan: foto struk, teks lama tidak berubah) atau 'bukti' (PDF bukti bayar dari
// tombol PDF di form Catat, hanya saat saklar `receipt_inbox` menyala). Nilai lain dibaca 'struk'.
import { UPLOAD_TIMEOUT_MS } from './xhrUpload.js';

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

export const PDF_TYPE = 'application/pdf';
// Sama dengan server (app/services/kotak_struk/config.py PDF_MAX_BYTES): PDF lebih besar ditolak sebelum diunggah.
export const PDF_MAX_BYTES = 10 * 1024 * 1024;

const STRUK = {
  preparing: 'Menyiapkan foto…',
  uploading: 'Mengunggah foto…',
  sendingAndReading: 'Mengirim dan membaca struk…',
  reading: 'Membaca struk…',
  slowHint: 'Struk panjang butuh waktu lebih lama.',
  stepPreparing: 'Menyiapkan foto',
  stepReading: 'Membaca struk',
  cannotOpen: 'Foto tidak bisa dibuka. Coba foto ulang atau pilih format JPG.',
  failed: 'Scan struk gagal, coba lagi',
  notSent: 'Foto belum terkirim. Cek koneksi lalu coba lagi.',
  notSentSlow: 'Koneksi lambat, foto belum terkirim. Coba lagi.',
  cutWhileReading: 'Koneksi terputus saat membaca struk. Coba lagi.',
  offline: 'Butuh koneksi internet untuk scan struk',
  pickFailed: 'Foto tidak bisa diambil, coba lagi',
  retake: { label: 'Foto ulang', icon: 'camera', source: 'camera' },
  waiting: 'Menunggu struk...',
};

const BUKTI = {
  preparing: 'Menyiapkan bukti…',
  uploading: 'Mengunggah bukti…',
  sendingAndReading: 'Mengirim dan membaca bukti…',
  reading: 'Membaca bukti…',
  slowHint: 'Dokumen panjang butuh waktu lebih lama.',
  stepPreparing: 'Menyiapkan bukti',
  stepReading: 'Membaca bukti',
  cannotOpen: 'Bukti tidak bisa dibuka. Coba pilih file lain.',
  failed: 'Scan bukti gagal, coba lagi',
  notSent: 'Bukti belum terkirim. Cek koneksi lalu coba lagi.',
  notSentSlow: 'Koneksi lambat, bukti belum terkirim. Coba lagi.',
  cutWhileReading: 'Koneksi terputus saat membaca bukti. Coba lagi.',
  offline: 'Butuh koneksi internet untuk membaca bukti',
  pickFailed: 'File tidak bisa dibuka, coba lagi',
  // Bukan foto: ganti file lewat pemilih dokumen, bukan kamera.
  retake: { label: 'Pilih file lain', icon: 'file', source: 'document' },
  waiting: 'Menunggu bukti...',
};

const words = (noun) => (noun === 'bukti' ? BUKTI : STRUK);

const SERVER_SLOW = 'Server lama menjawab. Coba lagi.';
// Pembatas laju (slowapi, 30/jam) menjawab 429 dengan {"error": …} tanpa `detail`.
const RATE_LIMITED = 'Terlalu banyak scan. Tunggu sebentar, ya.';

const NOT_IMAGE = 'Pilih file foto (JPG/PNG)';
const NOT_IMAGE_OR_PDF = 'Pilih file foto (JPG/PNG) atau PDF';
const PDF_TOO_BIG = 'PDF terlalu besar (maks 10 MB)';

function clampPercent(percent) {
  const n = Math.round(Number(percent) || 0);
  return Math.min(100, Math.max(0, n));
}

// Judul + hint untuk satu tahap. `elapsedMs` = ms sejak tahap ini mulai.
export function stageLabel({ stage, percent = null, progressSeen = false, elapsedMs = 0, noun = 'struk' }) {
  const w = words(noun);
  switch (stage) {
    case STAGE.PREPARING:
      return { title: w.preparing, hint: null };
    case STAGE.UPLOADING:
      if (progressSeen) return { title: `${w.uploading} ${clampPercent(percent)}%`, hint: null };
      // Perangkat/jaringan tidak melaporkan progres: jangan pura-pura persen.
      if (elapsedMs >= NO_PROGRESS_MS) return { title: w.sendingAndReading, hint: null };
      return { title: w.uploading, hint: null };
    case STAGE.READING:
      return {
        title: w.reading,
        hint: elapsedMs >= SLOW_READING_MS ? w.slowHint : null,
      };
    default:
      return { title: '', hint: null };
  }
}

// Daftar langkah dengan status: sebelum tahap aktif = done, sesudahnya = todo.
// Tahap di luar tiga langkah (idle/failed) → semua todo.
export function stageSteps(stage, noun = 'struk') {
  const w = words(noun);
  const steps = [
    { key: 'preparing', label: w.stepPreparing },
    { key: 'uploading', label: 'Mengunggah' },
    { key: 'reading', label: w.stepReading },
  ];
  const active = steps.findIndex(s => s.key === stage);
  return steps.map((s, i) => ({
    ...s,
    state: active < 0 || i > active ? 'todo' : i === active ? 'active' : 'done',
  }));
}

// Pesan gagal per tahap. `stage` = tahap saat gagal.
export function failureMessage({ stage, status = 0, detail = null, timedOut = false, noun = 'struk' }) {
  const w = words(noun);
  // File tidak bisa disiapkan (format/dekode): mengulang pengiriman tidak membantu.
  if (stage === STAGE.PREPARING) {
    return { text: w.cannotOpen, canRetry: false, canRetake: true };
  }

  const code = Number(status) || 0;
  const canRetry = code === 0 || timedOut || code >= 500;
  const canRetake = code !== 429;

  // Server menjawab dengan penolakan: pakai pesannya bila ada.
  if (code >= 400) {
    const hasDetail = typeof detail === 'string' && detail.trim();
    const text = hasDetail ? detail : code === 429 ? RATE_LIMITED : w.failed;
    return { text, canRetry, canRetake };
  }

  // Tanpa jawaban server: koneksi putus / lewat batas waktu.
  if (stage === STAGE.UPLOADING) {
    return { text: timedOut ? w.notSentSlow : w.notSent, canRetry, canRetake };
  }
  // File sudah sampai; jawabannya yang tak kunjung datang (batas 60 dtk) vs. koneksi putus.
  return { text: timedOut ? SERVER_SLOW : w.cutWhileReading, canRetry, canRetake };
}

// Tanpa koneksi saat file sudah dipilih: Coba lagi memulai dari awal dengan file yang sama.
export function offlineFailure(noun = 'struk') {
  return { text: words(noun).offline, canRetry: true, canRetake: false };
}

// Pesan tombol pilih file (ReceiptInput). source: 'camera' | 'gallery' | 'document' (tombol PDF).
export function pickMessages(source) {
  const w = words(source === 'document' ? 'bukti' : 'struk');
  return { offline: w.offline, failed: w.pickFailed };
}

// Tombol ganti file di kartu gagal (canRetake): label, ikon, dan `source` untuk pickReceiptPhoto.
export function retakeAction(noun = 'struk') {
  return { ...words(noun).retake };
}

// Tombol simpan form Catat selama struk/bukti masih dibaca.
export function waitingLabel(noun = 'struk') {
  return words(noun).waiting;
}

// Batas waktu satu kiriman scan (unggah + server membaca, xhrUpload). Foto sudah dikompres (±300 KB): batas lama
// UPLOAD_TIMEOUT_MS persis. PDF dikirim apa adanya (maks 10 MB): ditambah 1 dtk per 25 KB (±200 kbit/s), maks 5 menit;
// server tetap menjawab paling lama ±45 dtk setelah file sampai, jadi tambahannya hanya untuk unggahnya.
const PDF_BYTES_PER_EXTRA_S = 25000;
const PDF_UPLOAD_MAX_MS = 300000;
export function uploadTimeoutMs(blob) {
  if (blob?.type !== PDF_TYPE) return UPLOAD_TIMEOUT_MS;
  const size = Math.max(0, Number(blob.size) || 0);
  return Math.min(PDF_UPLOAD_MAX_MS, UPLOAD_TIMEOUT_MS + Math.ceil(size / PDF_BYTES_PER_EXTRA_S) * 1000);
}

// PDF tanpa tipe yang berguna (sebagian penyedia file Android memberi '' atau application/octet-stream; server menolak
// keduanya): hanya saat saklar menyala, isinya yang menentukan. Hook membaca PDF_HEAD_BYTES byte awal (I/O tipis), lalu
// isPdfHead → asPdfFile. Saklar mati: isi tidak pernah dibaca, file ditolak seperti dulu. Nama file tidak dipakai.
const UNTYPED = new Set(['', 'application/octet-stream']);
const PDF_MAGIC = [0x25, 0x50, 0x44, 0x46, 0x2d]; // "%PDF-", sama dengan server (kotak_struk/extract.py sniff_type)
export const PDF_HEAD_BYTES = PDF_MAGIC.length;

export function needsPdfSniff(file, { allowPdf = false } = {}) {
  if (!file || !allowPdf) return false;
  return UNTYPED.has(String(file.type ?? ''));
}

// Byte awal file (Uint8Array, ArrayBuffer, atau array) diawali "%PDF-"?
export function isPdfHead(bytes) {
  if (!bytes) return false;
  const b = bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : bytes;
  if (!(b.length >= PDF_MAGIC.length)) return false;
  return PDF_MAGIC.every((v, i) => b[i] === v);
}

// PDF yang dikenali dari isinya → File bertipe application/pdf (server memilih jenis dari tipe bagian unggahan),
// isi dan nama aslinya tetap; tanpa nama → 'bukti.pdf'.
export function asPdfFile(file, FileCtor = globalThis.File) {
  return new FileCtor([file], file.name || 'bukti.pdf', { type: PDF_TYPE });
}

// File yang dipilih → { kind: 'image' | 'pdf' | null, noun, failure } (failure null = boleh dibaca).
// PDF hanya bila allowPdf (saklar `receipt_inbox`): tanpa itu PDF ditolak seperti sebelum ada tombol PDF.
// Foto dikompres dulu, jadi ukurannya tidak diperiksa di sini; PDF dikirim apa adanya, maks PDF_MAX_BYTES.
export function checkScanFile(file, { allowPdf = false } = {}) {
  const type = String(file?.type || '');
  if (type.startsWith('image/')) return { kind: 'image', noun: 'struk', failure: null };
  if (allowPdf && type === PDF_TYPE) {
    const tooBig = Number(file.size) > PDF_MAX_BYTES;
    return { kind: 'pdf', noun: 'bukti', failure: tooBig ? { text: PDF_TOO_BIG, canRetry: false, canRetake: true } : null };
  }
  return { kind: null, noun: 'struk', failure: { text: allowPdf ? NOT_IMAGE_OR_PDF : NOT_IMAGE, canRetry: false, canRetake: true } };
}
