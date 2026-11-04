// Bagian "Donasi contoh" di kartu Admin "Scan Struk" (tahap 2 M1e; API app/api/routes/admin_kotak.py
// `/admin/kotak/samples…`): logika murni, diuji dengan node --test; JSX (components/ProofSamplesSection.jsx) hanya
// merender hasilnya.
//
// Daftar dimuat sekali dengan `GET /admin/kotak/samples?status=semua` lalu dikelompokkan per tab di sini; sesudah setiap
// keputusan daftar dimuat ulang. Sampel `ditolak` tidak pernah ada (ruling M1d: Tolak menghapus barisnya), jadi hanya
// dua tab dan `from_status` selalu "menunggu". Baris sampel sudah disamarkan server; baris bertanda `periksa`
// (`samaran.needs_review`) perlu dicek pemilik. Server tetap penentu: menyamarkan lagi saat Setujui, 422 bila masih ada
// nomor panjang atau nama yang bukan nama samaran, 409 bila sampel sudah diputuskan.
import { ISSUER_LABEL } from './proofFormat.js';
import { wibDate, shortDate } from './receiptScan.js';

export const SAMPLE_TABS = [
  { key: 'menunggu', label: 'Menunggu' },
  { key: 'disetujui', label: 'Disetujui' },
];
const STATUSES = SAMPLE_TABS.map(t => t.key);

export const SAMPLE_MAX_LINES = 80;   // = server config.SAMPLE_MAX_LINES
export const SAMPLE_LINE_MAX = 200;   // = server config.SAMPLE_LINE_MAX
const NOTE_MAX = 200;                 // = server admin_kotak.NOTE_MAX
const ID_MAX = 100;

// = server samaran.PSEUDONYMS (user, pihak, pengirim, merchant): `user_name` hanya boleh kata nama samaran (ruling M1d).
const PSEUDONYMS = ['ANDI PRATAMA', 'BUDI SANTOSO', 'SITI AMINAH', 'TOKO CONTOH'];
export const PSEUDONYM_CHOICES = [
  ...PSEUDONYMS.map(name => ({ value: name, label: name })),
  { value: '', label: 'Tanpa nama' },
];

// `expect` entri korpus memakai nilai koreksi user (ruling M1d), bukan hasil pembaca sekarang.
export const EXPECT_LABEL = 'Koreksi user (sudah diterapkan)';
export const READING_LABEL = 'Hasil baca';
export const TRUTH_LABEL = 'Koreksi user';
export const STEP_TEXT = 'Simpan berkas, lalu jalankan `python -m app.scripts.kotak_corpus add --dari-donasi <berkas>` '
  + 'di checkout lokal dan buka PR. Bila pembaca berbeda dari koreksi user, perintah berhenti (exit 3); pakai '
  + '`--tahan` untuk menulis `reviewed: false`.';

// = server donasi.TRIGGERS.
const TRIGGER_LABEL = {
  nominal: 'Nominal dikoreksi',
  tanggal: 'Tanggal dikoreksi',
  tidak_dikenali: 'Bukti tidak dikenali dipastikan',
  arah: 'Bukan pengeluaran',
  aplikasi: 'Aplikasi dipilih',
  nominal_bot: 'Nominal dikoreksi di bot',
};
const FIELD_LABEL = { total: 'Nominal', date: 'Tanggal', status: 'Status', flow: 'Arah uang', app: 'Aplikasi' };
const FLOW_LABEL = { keluar: 'Pengeluaran', top_up: 'Top-up', masuk: 'Uang masuk', antar_rekening_sendiri: 'Rekening sendiri' };
const STATUS_LABEL = { berhasil: 'Berhasil', pending: 'Pending', gagal: 'Gagal' };
const DONE_TEXT = { setujui: 'Sampel disetujui.', tolak: 'Sampel ditolak dan dihapus.', hapus: 'Sampel dihapus.' };
const CONFIRM_TEXT = {
  tolak: 'Tolak sampel ini? Barisnya dihapus dan tidak bisa dikembalikan.',
  hapus: 'Hapus sampel ini? Pastikan entri korpus sudah diunduh dan disalin ke korpus.',
};
const EMPTY_TEXT = { menunggu: 'Tidak ada sampel yang menunggu.', disetujui: 'Belum ada sampel yang disetujui.' };
const NONE = '–';

const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const isText = v => typeof v === 'string' && v.length > 0;
const own = (map, key) => typeof key === 'string' && Object.hasOwn(map, key);
const count = v => (Number.isSafeInteger(v) && v > 0 ? v : 0);
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
// Karakter kontrol yang ditolak server di baris (kategori Cc kecuali tab) dan di nama/catatan (Cc, Cf).
const BAD_LINE_CHARS = /[\p{Cc}]/gu;
const BAD_NOTE_CHARS = /[\p{Cc}\p{Cf}]/gu;
const cut = (text, max) => [...text].slice(0, max).join('');

function rupiah(n) {
  if (!Number.isSafeInteger(n)) return null;
  const digits = String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return `${n < 0 ? '-' : ''}Rp ${digits}`;
}
const dayText = iso => (typeof iso === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? shortDate(iso) : null);
const appText = v => (v === 'baru' ? 'Lainnya' : own(ISSUER_LABEL, v) ? ISSUER_LABEL[v] : null);

// Nilai yang dibaca manusia per field; tidak ada / tidak dikenal → null.
function fieldText(field, value) {
  if (value === null || value === undefined) return null;
  if (field === 'total') return rupiah(value);
  if (field === 'date') return dayText(value);
  if (field === 'flow') return own(FLOW_LABEL, value) ? FLOW_LABEL[value] : null;
  if (field === 'status') return own(STATUS_LABEL, value) ? STATUS_LABEL[value] : null;
  if (field === 'app') return appText(value);
  return null;
}

// Nilai pembaca (`reading`/`expect`, bentuk korpus) untuk satu field koreksi.
function readingValue(field, reading) {
  if (!isObj(reading)) return null;
  if (field === 'date') return wibDate(reading.paid_at);
  if (field === 'app') return reading.issuer ?? null;
  return reading[field] ?? null;
}

const validLines = lines => Array.isArray(lines) && lines.length > 0 && lines.every(l => isObj(l) && typeof l.text === 'string');
const validSample = s => isObj(s) && isText(s.id) && STATUSES.includes(s.status) && validLines(s.lines);

// {menunggu, disetujui} dari `counts` server (seluruh tabel; `ditolak` diabaikan); rusak → 0.
export function sampleCounts(resp) {
  const counts = isObj(resp?.counts) ? resp.counts : {};
  return Object.fromEntries(STATUSES.map(s => [s, count(counts[s])]));
}

// Jumlah baris bertanda PERIKSA (sampel server atau baris hasil sampleRows); data rusak → null.
export function periksaCount(row) {
  if (!validLines(row?.lines)) return null;
  return row.lines.filter(l => l.periksa === true).length;
}

// Teks baris untuk <textarea> (satu baris per baris bukti); data rusak → null.
export function editableLines(row) {
  if (!validLines(row?.lines)) return null;
  return row.lines.map(l => l.text).join('\n');
}

function dateLine(s) {
  if (s.status === 'menunggu') {
    const d = wibDate(s.created_at);
    return d ? `Masuk ${shortDate(d)}` : null;
  }
  const d = wibDate(s.decided_at);
  if (!d) return null;
  return `Disetujui ${shortDate(d)}${isText(s.decided_by_name) ? ` oleh ${s.decided_by_name}` : ''}`;
}

// "Hasil baca" (pembaca sekarang) vs "Koreksi user" (`truth`) per field: [{field, label, read, fixed, differs}].
// `differs` hanya bila user mengoreksi field itu dan nilainya berbeda dari pembaca.
function compareRows(reading, truth) {
  const t = isObj(truth) ? truth : {};
  return ['total', 'date', 'flow', 'app'].map((field) => {
    const got = readingValue(field, reading);
    const want = t[field] ?? null;
    return {
      field,
      label: FIELD_LABEL[field],
      read: fieldText(field, got) ?? NONE,
      fixed: fieldText(field, want) ?? NONE,
      differs: want !== null && want !== got,
    };
  });
}

// Baris satu tab → [{id, status, app, trigger, lines: [{n, text, periksa}], periksa, periksaText, userName, compare,
// readingMissing, date, note}]; tab tidak dikenal → []; respons tanpa daftar → null. Sampel rusak dilewati; hanya
// field yang disebut di atas yang disalin (tidak pernah id user/item). Tidak pernah melempar.
export function sampleRows(resp, tab) {
  if (!isObj(resp) || !Array.isArray(resp.samples)) return null;
  if (!STATUSES.includes(tab)) return [];
  return resp.samples.filter(s => validSample(s) && s.status === tab).map((s) => {
    const lines = s.lines.map((l, i) => ({ n: i + 1, text: l.text, periksa: l.periksa === true }));
    const flagged = lines.filter(l => l.periksa).map(l => l.n);
    const name = typeof s.user_name === 'string' ? s.user_name : null;
    return {
      id: s.id,
      status: s.status,
      app: isText(s.app_label) ? s.app_label : 'Aplikasi tidak dikenal',
      trigger: own(TRIGGER_LABEL, s.trigger) ? TRIGGER_LABEL[s.trigger] : (isText(s.trigger) ? s.trigger : NONE),
      lines,
      periksa: flagged.length,
      periksaText: flagged.length ? `PERIKSA baris ${flagged.join(', ')}` : null,
      userName: name,
      compare: compareRows(s.reading, s.truth),
      readingMissing: !isObj(s.reading),
      date: dateLine(s),
      note: typeof s.note === 'string' && s.note.trim() ? s.note.trim() : null,
    };
  });
}

// Baris dari isian (teks <textarea> atau daftar) → daftar baris yang dikirim: karakter kontrol (kecuali tab) dibuang,
// baris kosong dibuang, tiap baris <= SAMPLE_LINE_MAX, paling banyak SAMPLE_MAX_LINES. Isian bukan teks/daftar → null.
function cleanLines(input) {
  const raw = typeof input === 'string' ? input.split(/\r\n|\r|\n/) : Array.isArray(input) ? input : null;
  if (!raw || !raw.every(l => typeof l === 'string')) return null;
  return raw.map(l => l.replace(BAD_LINE_CHARS, ch => (ch === '\t' ? ch : '')))
    .filter(l => l.trim().length > 0);
}

// Peringatan sebelum Setujui (isian akan dipotong / kosong), atau null.
export function linesNotice(input) {
  const lines = cleanLines(input);
  if (!lines) return null;
  if (lines.length === 0) return 'Baris kosong semua; isi minimal satu baris.';
  const long = lines.findIndex(l => [...l].length > SAMPLE_LINE_MAX);
  if (long >= 0) return `Baris ${long + 1} lebih dari ${SAMPLE_LINE_MAX} karakter; sisanya dipotong.`;
  if (lines.length > SAMPLE_MAX_LINES) return `Lebih dari ${SAMPLE_MAX_LINES} baris; sisanya tidak dikirim.`;
  return null;
}

// Nama samaran dari pilihan: hanya salah satu PSEUDONYMS (huruf besar/kecil tidak dibedakan), selain itu null.
function pseudonym(name) {
  if (typeof name !== 'string') return null;
  const t = name.trim().replace(/\s+/g, ' ').toUpperCase();
  return PSEUDONYMS.includes(t) ? t : null;
}

function noteValue(note) {
  if (typeof note !== 'string') return null;
  const t = cut(note.replace(BAD_NOTE_CHARS, '').trim(), NOTE_MAX).trim();
  return t || null;
}

// Body Setujui: HANYA {lines, user_name, note, from_status} (server menolak field lain dengan 422), dipotong ke batas
// server. Null bila baris bukan `menunggu`, isian rusak, atau tidak ada baris berisi.
export function approveBody(row, lines, userName, note) {
  if (!isObj(row) || row.status !== 'menunggu') return null;
  const clean = cleanLines(lines);
  if (!clean || clean.length === 0) return null;
  return {
    lines: clean.slice(0, SAMPLE_MAX_LINES).map(l => cut(l, SAMPLE_LINE_MAX)),
    user_name: pseudonym(userName),
    note: noteValue(note),
    from_status: 'menunggu',
  };
}

// Body Tolak: {note, from_status}; null bila baris bukan `menunggu`.
export function rejectBody(row, note) {
  if (!isObj(row) || row.status !== 'menunggu') return null;
  return { note: noteValue(note), from_status: 'menunggu' };
}

// "<entry.id>.json" (dari entri atau dari respons {entry, …}); id yang bukan nama berkas aman → null.
export function entryFileName(entry) {
  const e = isObj(entry?.entry) ? entry.entry : entry;
  const id = e?.id;
  if (typeof id !== 'string' || id.length > ID_MAX || !SAFE_ID.test(id)) return null;
  return `${id}.json`;
}

// Respons `GET …/{id}/korpus` → {fileName, text, expect, diffText} atau null. `text` = SELURUH {entry, truth,
// gated_diff} (ruling M1d: `add --dari-donasi` membaca bentuk utuh ini), field lain dibuang. `expect` = nilai entri per
// field (berlabel EXPECT_LABEL); `diffText` = field yang pembacanya masih berbeda dari koreksi user, atau null.
export function entryDownload(resp) {
  if (!isObj(resp) || !isObj(resp.entry) || !Array.isArray(resp.gated_diff)) return null;
  const { entry, gated_diff: diff } = resp;
  const fileName = entryFileName(entry);
  if (!fileName || !Array.isArray(entry.lines) || !isObj(entry.expect)) return null;
  if (!diff.every(f => typeof f === 'string')) return null;
  const truth = isObj(resp.truth) ? resp.truth : null;
  const text = JSON.stringify({ entry, truth, gated_diff: diff }, null, 2);
  const expect = ['total', 'date', 'status', 'flow', 'app'].map(field => ({
    field, label: FIELD_LABEL[field], value: fieldText(field, readingValue(field, entry.expect)) ?? NONE,
  }));
  const names = diff.map(f => (own(FIELD_LABEL, f) ? FIELD_LABEL[f] : f));
  return {
    fileName,
    text,
    expect,
    diffText: names.length ? `Pembaca masih berbeda dari koreksi user di: ${names.join(', ')}` : null,
  };
}

// `detail` server sebagai kalimat pendek: teks biasa, atau `msg` galat validasi pydantic pertama; selain itu null.
function serverText(data) {
  let d = data?.detail;
  if (Array.isArray(d)) d = isObj(d[0]) ? d[0].msg : null;
  if (typeof d !== 'string') return null;
  const t = d.replace(/^Value error,\s*/, '').trim();
  if (!t || t.length > 200 || /^[[{]/.test(t)) return null;
  return `${t.replace(/[.!]+$/, '')}.`;
}

// Hasil aksi ({ok, status, data} dari api) → {kind: ok|conflict|invalid|error, text, reload}. 409/404: daftar sudah
// berubah (muat ulang); 422: teks server (mis. "Masih ada nomor panjang di baris 3"). Tidak pernah melempar.
export function actionOutcome(action, res) {
  if (isObj(res) && res.ok) return { kind: 'ok', text: DONE_TEXT[action] || 'Tersimpan.', reload: true };
  const status = Number.isSafeInteger(res?.status) ? res.status : 0;
  const data = isObj(res) ? res.data : null;
  if (status === 409) {
    const t = serverText(data);
    return { kind: 'conflict', text: `${t || 'Sampel ini sudah berubah.'} Daftar dimuat ulang.`, reload: true };
  }
  if (status === 404) return { kind: 'conflict', text: 'Sampel tidak ditemukan lagi. Daftar dimuat ulang.', reload: true };
  if (status === 422) return { kind: 'invalid', text: serverText(data) || 'Isian tidak diterima.', reload: false };
  if (status === 403) return { kind: 'error', text: 'Hanya admin yang bisa meninjau sampel.', reload: false };
  if (status === 0) return { kind: 'error', text: 'Koneksi gagal, coba lagi.', reload: false };
  return { kind: 'error', text: `Belum tersimpan (kode ${status}). Coba lagi.`, reload: false };
}

// Pertanyaan konfirmasi sebelum aksi yang menghapus, atau null.
export function confirmText(action) {
  return own(CONFIRM_TEXT, action) ? CONFIRM_TEXT[action] : null;
}

// Tab berikutnya untuk panah/Home/End (pola tab WAI-ARIA, melingkar), atau null.
export function nextSampleTab(current, key) {
  const i = STATUSES.indexOf(current);
  if (i < 0) return null;
  if (key === 'ArrowRight') return STATUSES[(i + 1) % STATUSES.length];
  if (key === 'ArrowLeft') return STATUSES[(i - 1 + STATUSES.length) % STATUSES.length];
  if (key === 'Home') return STATUSES[0];
  if (key === 'End') return STATUSES[STATUSES.length - 1];
  return null;
}

export function emptyText(tab) {
  return own(EMPTY_TEXT, tab) ? EMPTY_TEXT[tab] : '';
}
