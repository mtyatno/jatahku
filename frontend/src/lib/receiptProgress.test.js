import test from 'node:test';
import assert from 'node:assert/strict';
import {
  STAGE, PDF_MAX_BYTES, stageLabel, stageSteps, failureMessage, checkScanFile, offlineFailure, pickMessages, retakeAction,
  waitingLabel, uploadTimeoutMs, needsPdfSniff, isPdfHead, asPdfFile, PDF_HEAD_BYTES,
} from './receiptProgress.js';

const ELL = '…'; // elipsis satu karakter, seperti teks lama

test('stageLabel: menyiapkan, mengunggah dengan persen, membaca', () => {
  assert.deepEqual(stageLabel({ stage: STAGE.PREPARING }), { title: 'Menyiapkan foto…', hint: null });
  assert.equal(stageLabel({ stage: STAGE.UPLOADING, percent: 40, progressSeen: true }).title, 'Mengunggah foto… 40%');
  assert.equal(stageLabel({ stage: STAGE.READING, elapsedMs: 1000 }).title, 'Membaca struk…');
  assert.equal(stageLabel({ stage: STAGE.READING, elapsedMs: 1000 }).hint, null);
});

test('stageLabel: membaca lewat 8 detik menambah hint struk panjang', () => {
  assert.equal(stageLabel({ stage: STAGE.READING, elapsedMs: 8000 }).hint, 'Struk panjang butuh waktu lebih lama.');
});

test('stageLabel: tanpa laporan progres → label gabungan setelah 1,5 detik', () => {
  assert.equal(stageLabel({ stage: STAGE.UPLOADING, progressSeen: false, elapsedMs: 1499 }).title, 'Mengunggah foto…');
  assert.equal(stageLabel({ stage: STAGE.UPLOADING, progressSeen: false, elapsedMs: 1500 }).title, 'Mengirim dan membaca struk…');
});

test('stageLabel: persen dibulatkan dan dibatasi 0–100', () => {
  assert.equal(stageLabel({ stage: STAGE.UPLOADING, percent: 99.6, progressSeen: true }).title, 'Mengunggah foto… 100%');
  assert.equal(stageLabel({ stage: STAGE.UPLOADING, percent: -5, progressSeen: true }).title, 'Mengunggah foto… 0%');
});

test('stageLabel: kata benda bukti', () => {
  assert.equal(stageLabel({ stage: STAGE.READING, elapsedMs: 0, noun: 'bukti' }).title, 'Membaca bukti…');
  assert.equal(stageLabel({ stage: STAGE.UPLOADING, percent: 40, progressSeen: true, noun: 'bukti' }).title, 'Mengunggah bukti… 40%');
  assert.equal(stageLabel({ stage: STAGE.READING, elapsedMs: 8000, noun: 'bukti' }).hint, 'Dokumen panjang butuh waktu lebih lama.');
  assert.equal(stageLabel({ stage: STAGE.READING, elapsedMs: 0 }).title, 'Membaca struk…');
});

test('stageSteps: tahap sebelum aktif selesai, sesudahnya belum', () => {
  assert.deepEqual(stageSteps(STAGE.UPLOADING).map(s => [s.key, s.state]),
    [['preparing', 'done'], ['uploading', 'active'], ['reading', 'todo']]);
  assert.deepEqual(stageSteps(STAGE.READING).map(s => s.label), ['Menyiapkan foto', 'Mengunggah', 'Membaca struk']);
});

test('failureMessage: foto tidak bisa dibuka → hanya Foto ulang', () => {
  assert.deepEqual(failureMessage({ stage: STAGE.PREPARING }),
    { text: 'Foto tidak bisa dibuka. Coba foto ulang atau pilih format JPG.', canRetry: false, canRetake: true });
});

test('failureMessage: tahap menyiapkan tetap pesan dekode walau ada status server (R1)', () => {
  assert.deepEqual(failureMessage({ stage: STAGE.PREPARING, status: 502 }),
    { text: 'Foto tidak bisa dibuka. Coba foto ulang atau pilih format JPG.', canRetry: false, canRetake: true });
});

test('failureMessage: unggahan gagal / lewat batas waktu → Coba lagi', () => {
  assert.deepEqual(failureMessage({ stage: STAGE.UPLOADING, status: 0 }),
    { text: 'Foto belum terkirim. Cek koneksi lalu coba lagi.', canRetry: true, canRetake: true });
  assert.equal(failureMessage({ stage: STAGE.UPLOADING, timedOut: true }).text, 'Koneksi lambat, foto belum terkirim. Coba lagi.');
});

test('failureMessage: koneksi putus saat membaca → pesan tahap membaca', () => {
  assert.deepEqual(failureMessage({ stage: STAGE.READING, status: 0 }),
    { text: 'Koneksi terputus saat membaca struk. Coba lagi.', canRetry: true, canRetake: true });
});

test('failureMessage: server lama menjawab saat membaca (timeout) → teks sendiri, bisa Coba lagi & Foto ulang', () => {
  assert.deepEqual(failureMessage({ stage: STAGE.READING, timedOut: true }),
    { text: 'Server lama menjawab. Coba lagi.', canRetry: true, canRetake: true });
  // Putus jaringan (bukan timeout) tetap pesan koneksi terputus.
  assert.equal(failureMessage({ stage: STAGE.READING, status: 0, timedOut: false }).text,
    'Koneksi terputus saat membaca struk. Coba lagi.');
});

test('failureMessage: penolakan server memakai detail; 429 tanpa Coba lagi/Foto ulang; 5xx bisa Coba lagi', () => {
  const quota = failureMessage({ stage: STAGE.READING, status: 429, detail: 'Kuota scan struk bulan ini (15x) sudah habis.' });
  assert.deepEqual(quota, { text: 'Kuota scan struk bulan ini (15x) sudah habis.', canRetry: false, canRetake: false });
  assert.equal(failureMessage({ stage: STAGE.READING, status: 413, detail: 'Foto terlalu besar' }).canRetry, false);
  assert.equal(failureMessage({ stage: STAGE.READING, status: 502 }).canRetry, true);
  assert.equal(failureMessage({ stage: STAGE.READING, status: 502 }).text, 'Scan struk gagal, coba lagi');
});

test('failureMessage: 429 tanpa detail (pembatas laju slowapi) → teks tunggu, tanpa tombol', () => {
  const expected = { text: 'Terlalu banyak scan. Tunggu sebentar, ya.', canRetry: false, canRetake: false };
  assert.deepEqual(failureMessage({ stage: STAGE.READING, status: 429 }), expected);
  assert.deepEqual(failureMessage({ stage: STAGE.UPLOADING, status: 429, detail: null }), expected);
  assert.deepEqual(failureMessage({ stage: STAGE.READING, status: 429, detail: '   ' }), expected);
  // Detail dari server (kuota bulanan) tetap dipakai.
  assert.equal(failureMessage({ stage: STAGE.READING, status: 429, detail: 'Kuota habis.' }).text, 'Kuota habis.');
});

// ── Kata benda tahap: 'struk' (bawaan, foto) dan 'bukti' (PDF dari tombol PDF form Catat) ──

test('noun bawaan / struk / tak dikenal: semua teks lama persis sama', () => {
  for (const noun of [undefined, 'struk', null, 'lain', 'constructor', '__proto__']) {
    const n = noun === undefined ? {} : { noun };
    assert.deepEqual(stageLabel({ stage: STAGE.PREPARING, ...n }), { title: `Menyiapkan foto${ELL}`, hint: null });
    assert.deepEqual(stageLabel({ stage: STAGE.UPLOADING, elapsedMs: 0, ...n }), { title: `Mengunggah foto${ELL}`, hint: null });
    assert.deepEqual(stageLabel({ stage: STAGE.UPLOADING, percent: 40, progressSeen: true, ...n }), { title: `Mengunggah foto${ELL} 40%`, hint: null });
    assert.deepEqual(stageLabel({ stage: STAGE.UPLOADING, elapsedMs: 1500, ...n }), { title: `Mengirim dan membaca struk${ELL}`, hint: null });
    assert.deepEqual(stageLabel({ stage: STAGE.READING, elapsedMs: 7999, ...n }), { title: `Membaca struk${ELL}`, hint: null });
    assert.deepEqual(stageLabel({ stage: STAGE.READING, elapsedMs: 8000, ...n }), { title: `Membaca struk${ELL}`, hint: 'Struk panjang butuh waktu lebih lama.' });
    assert.deepEqual(stageLabel({ stage: STAGE.IDLE, ...n }), { title: '', hint: null });
    assert.deepEqual(stageSteps(STAGE.UPLOADING, noun).map(s => s.label), ['Menyiapkan foto', 'Mengunggah', 'Membaca struk']);
    assert.deepEqual(failureMessage({ stage: STAGE.PREPARING, ...n }),
      { text: 'Foto tidak bisa dibuka. Coba foto ulang atau pilih format JPG.', canRetry: false, canRetake: true });
    assert.deepEqual(failureMessage({ stage: STAGE.UPLOADING, status: 0, ...n }),
      { text: 'Foto belum terkirim. Cek koneksi lalu coba lagi.', canRetry: true, canRetake: true });
    assert.deepEqual(failureMessage({ stage: STAGE.UPLOADING, timedOut: true, ...n }),
      { text: 'Koneksi lambat, foto belum terkirim. Coba lagi.', canRetry: true, canRetake: true });
    assert.deepEqual(failureMessage({ stage: STAGE.READING, status: 0, ...n }),
      { text: 'Koneksi terputus saat membaca struk. Coba lagi.', canRetry: true, canRetake: true });
    assert.deepEqual(failureMessage({ stage: STAGE.READING, timedOut: true, ...n }),
      { text: 'Server lama menjawab. Coba lagi.', canRetry: true, canRetake: true });
    assert.deepEqual(failureMessage({ stage: STAGE.READING, status: 502, ...n }),
      { text: 'Scan struk gagal, coba lagi', canRetry: true, canRetake: true });
    assert.deepEqual(failureMessage({ stage: STAGE.READING, status: 429, ...n }),
      { text: 'Terlalu banyak scan. Tunggu sebentar, ya.', canRetry: false, canRetake: false });
    assert.deepEqual(offlineFailure(noun), { text: 'Butuh koneksi internet untuk scan struk', canRetry: true, canRetake: false });
    assert.deepEqual(retakeAction(noun), { label: 'Foto ulang', icon: 'camera', source: 'camera' });
    assert.equal(waitingLabel(noun), 'Menunggu struk...');
  }
});

test('waitingLabel: tombol simpan selama membaca — struk persis seperti dulu, bukti untuk PDF', () => {
  assert.equal(waitingLabel(), 'Menunggu struk...');
  assert.equal(waitingLabel('struk'), 'Menunggu struk...');
  assert.equal(waitingLabel('bukti'), 'Menunggu bukti...');
});

test('stageLabel: bukti — menyiapkan, unggah tanpa laporan progres, gabungan, persen, hint lambat', () => {
  const b = (o) => stageLabel({ ...o, noun: 'bukti' });
  assert.deepEqual(b({ stage: STAGE.PREPARING }), { title: `Menyiapkan bukti${ELL}`, hint: null });
  assert.deepEqual(b({ stage: STAGE.UPLOADING, elapsedMs: 1499 }), { title: `Mengunggah bukti${ELL}`, hint: null });
  assert.deepEqual(b({ stage: STAGE.UPLOADING, elapsedMs: 1500 }), { title: `Mengirim dan membaca bukti${ELL}`, hint: null });
  assert.deepEqual(b({ stage: STAGE.UPLOADING, percent: 99.6, progressSeen: true }), { title: `Mengunggah bukti${ELL} 100%`, hint: null });
  assert.deepEqual(b({ stage: STAGE.READING, elapsedMs: 7999 }), { title: `Membaca bukti${ELL}`, hint: null });
  assert.deepEqual(b({ stage: STAGE.READING, elapsedMs: 8000 }), { title: `Membaca bukti${ELL}`, hint: 'Dokumen panjang butuh waktu lebih lama.' });
  assert.deepEqual(b({ stage: STAGE.FAILED }), { title: '', hint: null });
});

test('stageSteps: bukti — label langkah tanpa foto/struk, status langkah sama', () => {
  assert.deepEqual(stageSteps(STAGE.READING, 'bukti').map(s => [s.key, s.label, s.state]),
    [['preparing', 'Menyiapkan bukti', 'done'], ['uploading', 'Mengunggah', 'done'], ['reading', 'Membaca bukti', 'active']]);
  assert.deepEqual(stageSteps(STAGE.FAILED, 'bukti').map(s => s.state), ['todo', 'todo', 'todo']);
});

test('failureMessage: bukti — teks tanpa foto/struk; tombol Coba lagi/ganti file sama dengan struk', () => {
  const b = (o) => failureMessage({ ...o, noun: 'bukti' });
  assert.deepEqual(b({ stage: STAGE.PREPARING }), { text: 'Bukti tidak bisa dibuka. Coba pilih file lain.', canRetry: false, canRetake: true });
  assert.deepEqual(b({ stage: STAGE.UPLOADING, status: 0 }), { text: 'Bukti belum terkirim. Cek koneksi lalu coba lagi.', canRetry: true, canRetake: true });
  assert.deepEqual(b({ stage: STAGE.UPLOADING, timedOut: true }), { text: 'Koneksi lambat, bukti belum terkirim. Coba lagi.', canRetry: true, canRetake: true });
  assert.deepEqual(b({ stage: STAGE.READING, status: 0 }), { text: 'Koneksi terputus saat membaca bukti. Coba lagi.', canRetry: true, canRetake: true });
  assert.deepEqual(b({ stage: STAGE.READING, timedOut: true }), { text: 'Server lama menjawab. Coba lagi.', canRetry: true, canRetake: true });
  assert.deepEqual(b({ stage: STAGE.READING, status: 502 }), { text: 'Scan bukti gagal, coba lagi', canRetry: true, canRetake: true });
  assert.deepEqual(b({ stage: STAGE.READING, status: 429 }), { text: 'Terlalu banyak scan. Tunggu sebentar, ya.', canRetry: false, canRetake: false });
  // Penolakan server (PDF terkunci, terlalu banyak halaman, terlalu besar) tetap memakai pesan server.
  assert.deepEqual(b({ stage: STAGE.READING, status: 422, detail: 'PDF terkunci kata sandi' }), { text: 'PDF terkunci kata sandi', canRetry: false, canRetake: true });
  assert.deepEqual(b({ stage: STAGE.UPLOADING, status: 413, detail: 'PDF terlalu besar (maks 10 MB)' }),
    { text: 'PDF terlalu besar (maks 10 MB)', canRetry: false, canRetake: true });
  for (const o of [{ stage: STAGE.PREPARING }, { stage: STAGE.UPLOADING, status: 0 }, { stage: STAGE.UPLOADING, timedOut: true },
    { stage: STAGE.READING, status: 0 }, { stage: STAGE.READING, status: 502 }]) {
    assert.doesNotMatch(b(o).text, /foto|struk/i);
  }
});

test('offlineFailure dan retakeAction: bukti — teks bukti, ganti file lewat pemilih dokumen (bukan kamera)', () => {
  assert.deepEqual(offlineFailure('bukti'), { text: 'Butuh koneksi internet untuk membaca bukti', canRetry: true, canRetake: false });
  assert.deepEqual(retakeAction('bukti'), { label: 'Pilih file lain', icon: 'file', source: 'document' });
});

test('pickMessages: tombol Foto/Galeri memakai teks lama; tombol PDF memakai kata bukti', () => {
  for (const source of ['camera', 'gallery', undefined]) {
    assert.deepEqual(pickMessages(source), { offline: 'Butuh koneksi internet untuk scan struk', failed: 'Foto tidak bisa diambil, coba lagi' });
  }
  assert.deepEqual(pickMessages('document'), { offline: 'Butuh koneksi internet untuk membaca bukti', failed: 'File tidak bisa dibuka, coba lagi' });
});

const pick = (type, size = 1000) => ({ type, size, name: 'berkas' });
const REJECT_OLD = { kind: null, noun: 'struk', failure: { text: 'Pilih file foto (JPG/PNG)', canRetry: false, canRetake: true } };

test('checkScanFile: foto selalu diterima; PDF hanya bila allowPdf (saklar receipt_inbox)', () => {
  for (const allowPdf of [false, true]) {
    assert.deepEqual(checkScanFile(pick('image/jpeg'), { allowPdf }), { kind: 'image', noun: 'struk', failure: null });
    assert.deepEqual(checkScanFile(pick('image/webp'), { allowPdf }), { kind: 'image', noun: 'struk', failure: null });
  }
  // Saklar mati (dan bawaan): PDF ditolak dengan teks lama, persis seperti sebelum ada tombol PDF.
  assert.deepEqual(checkScanFile(pick('application/pdf')), REJECT_OLD);
  assert.deepEqual(checkScanFile(pick('application/pdf'), { allowPdf: false }), REJECT_OLD);
  assert.deepEqual(checkScanFile(pick('text/plain'), { allowPdf: false }), REJECT_OLD);
  assert.deepEqual(checkScanFile(pick(''), {}), REJECT_OLD);
  // Saklar menyala: PDF diterima dengan kata benda bukti; jenis lain ditolak dengan teks yang menyebut PDF.
  assert.deepEqual(checkScanFile(pick('application/pdf'), { allowPdf: true }), { kind: 'pdf', noun: 'bukti', failure: null });
  assert.deepEqual(checkScanFile(pick('text/plain'), { allowPdf: true }),
    { kind: null, noun: 'struk', failure: { text: 'Pilih file foto (JPG/PNG) atau PDF', canRetry: false, canRetake: true } });
  assert.deepEqual(checkScanFile(pick(''), { allowPdf: true }).kind, null);
});

test('checkScanFile: PDF di atas 10 MB ditolak sebelum diunggah (batas sama dengan server)', () => {
  assert.equal(PDF_MAX_BYTES, 10 * 1024 * 1024);
  const tooBig = { kind: 'pdf', noun: 'bukti', failure: { text: 'PDF terlalu besar (maks 10 MB)', canRetry: false, canRetake: true } };
  assert.deepEqual(checkScanFile(pick('application/pdf', 10 * 1024 * 1024), { allowPdf: true }), { kind: 'pdf', noun: 'bukti', failure: null });
  assert.deepEqual(checkScanFile(pick('application/pdf', 10 * 1024 * 1024 + 1), { allowPdf: true }), tooBig);
  assert.deepEqual(checkScanFile(pick('application/pdf', 50 * 1024 * 1024), { allowPdf: true }), tooBig);
  // Foto tidak memakai batas PDF: dikompres dulu sebelum diunggah.
  assert.equal(checkScanFile(pick('image/jpeg', 50 * 1024 * 1024), { allowPdf: true }).failure, null);
});

// ── Batas waktu unggah (fix m2) ──

test('uploadTimeoutMs: foto dan jenis lain tetap 60 dtk persis, berapa pun ukurannya', () => {
  for (const blob of [pick('image/jpeg', 0), pick('image/jpeg', 300 * 1024), pick('image/png', 50 * 1024 * 1024),
    pick('', 10), pick('application/octet-stream', 5 * 1024 * 1024), {}, undefined, null]) {
    assert.equal(uploadTimeoutMs(blob), 60000);
  }
});

test('uploadTimeoutMs: PDF 60 dtk + 1 dtk per 25 KB (dibulatkan ke atas), maks 5 menit', () => {
  const pdfMs = (size) => uploadTimeoutMs(pick('application/pdf', size));
  assert.equal(pdfMs(0), 60000);
  assert.equal(pdfMs(1), 61000);
  assert.equal(pdfMs(77), 61000);
  assert.equal(pdfMs(25000), 61000);
  assert.equal(pdfMs(25001), 62000);
  assert.equal(pdfMs(500 * 1000), 80000);
  assert.equal(pdfMs(5975000), 299000);
  assert.equal(pdfMs(5975001), 300000);
  assert.equal(pdfMs(10 * 1024 * 1024), 300000); // PDF terbesar yang boleh (10 MB)
  assert.equal(pdfMs(50 * 1024 * 1024), 300000);
});

// ── PDF tanpa tipe yang berguna (fix m3) ──

const bytesOf = (s) => Uint8Array.from(s, (c) => c.charCodeAt(0));
const PDF_CONTENT = bytesOf('%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n');

test('needsPdfSniff: hanya saat saklar menyala dan tipe file kosong atau application/octet-stream', () => {
  for (const type of ['', 'application/octet-stream']) {
    const f = { type, name: 'x.pdf', size: 10 };
    assert.equal(needsPdfSniff(f, { allowPdf: true }), true, type);
    // Saklar mati (dan bawaan): isi file tidak pernah dibaca — perilaku lama.
    assert.equal(needsPdfSniff(f, { allowPdf: false }), false, type);
    assert.equal(needsPdfSniff(f), false, type);
  }
  for (const type of ['application/pdf', 'image/jpeg', 'text/plain', 'application/zip']) {
    assert.equal(needsPdfSniff({ type, name: 'x.pdf', size: 10 }, { allowPdf: true }), false, type);
  }
  assert.equal(needsPdfSniff({ name: 'tanpa-tipe', size: 10 }, { allowPdf: true }), true);
  assert.equal(needsPdfSniff(null, { allowPdf: true }), false);
});

test('isPdfHead: "%PDF-" di byte pertama, sama dengan server (extract.sniff_type)', () => {
  assert.equal(PDF_HEAD_BYTES, 5);
  assert.equal(isPdfHead(bytesOf('%PDF-')), true);
  assert.equal(isPdfHead(PDF_CONTENT), true);
  assert.equal(isPdfHead(bytesOf('%PDF-').buffer), true); // ArrayBuffer juga
  assert.equal(isPdfHead([0x25, 0x50, 0x44, 0x46, 0x2d]), true);
  for (const s of ['%PDF', '%pdf-', ' %PDF-', 'PDF-1', '%PDX-', '', '\xff\xd8\xff\xe0\x00']) {
    assert.equal(isPdfHead(bytesOf(s)), false, JSON.stringify(s));
  }
  assert.equal(isPdfHead(Uint8Array.from([0xef, 0xbb, 0xbf, 0x25, 0x50, 0x44, 0x46, 0x2d])), false); // BOM di depan
  assert.equal(isPdfHead(null), false);
  assert.equal(isPdfHead(undefined), false);
});

test('asPdfFile: dibungkus ulang bertipe application/pdf, nama asli (atau bukti.pdf), isi sama', async () => {
  const src = new File([PDF_CONTENT], 'Bukti Transfer', { type: '' });
  const out = asPdfFile(src);
  assert.equal(out.type, 'application/pdf');
  assert.equal(out.name, 'Bukti Transfer');
  assert.equal(out.size, src.size);
  assert.deepEqual(new Uint8Array(await out.arrayBuffer()), PDF_CONTENT);
  assert.equal(asPdfFile(new File([PDF_CONTENT], '', { type: 'application/octet-stream' })).name, 'bukti.pdf');
  // Setelah diberi tipe, batas waktu unggahnya batas PDF.
  assert.equal(uploadTimeoutMs(asPdfFile(new File([new Uint8Array(30000)], 'x', { type: '' }))), 62000);
});

test('checkScanFile: nama .pdf tanpa tipe tidak cukup — saklar mati menolak dengan teks lama', () => {
  const untyped = { type: '', size: 1000, name: 'x.pdf' };
  const octet = { type: 'application/octet-stream', size: 1000, name: 'bukti.pdf' };
  assert.deepEqual(checkScanFile(untyped, { allowPdf: false }), REJECT_OLD);
  assert.deepEqual(checkScanFile(untyped), REJECT_OLD);
  assert.deepEqual(checkScanFile(octet, { allowPdf: false }), REJECT_OLD);
  // Saklar menyala: tidak menebak dari nama. Isi yang menentukan (needsPdfSniff → isPdfHead → asPdfFile, di hook).
  assert.equal(checkScanFile(untyped, { allowPdf: true }).kind, null);
  assert.equal(checkScanFile(octet, { allowPdf: true }).kind, null);
});

// Alur yang dijalankan useReceiptScan sebelum checkScanFile (pembacaan 5 byte = I/O tipis di hook).
async function pickedForScan(file, allowPdf) {
  let f = file;
  if (needsPdfSniff(f, { allowPdf })) {
    const head = new Uint8Array(await f.slice(0, PDF_HEAD_BYTES).arrayBuffer());
    if (isPdfHead(head)) f = asPdfFile(f);
  }
  return { file: f, ...checkScanFile(f, { allowPdf }) };
}

test('PDF tanpa tipe: saklar menyala → dikenali dari isinya; saklar mati → ditolak seperti dulu, tidak diubah', async () => {
  const untypedPdf = new File([PDF_CONTENT], 'bukti', { type: '' });
  const octetPdf = new File([PDF_CONTENT], 'bukti.pdf', { type: 'application/octet-stream' });
  for (const f of [untypedPdf, octetPdf]) {
    const on = await pickedForScan(f, true);
    assert.deepEqual([on.kind, on.noun, on.failure, on.file.type, on.file.name], ['pdf', 'bukti', null, 'application/pdf', f.name]);
    const off = await pickedForScan(f, false);
    assert.deepEqual({ kind: off.kind, noun: off.noun, failure: off.failure }, REJECT_OLD);
    assert.equal(off.file, f);
  }
  // Isi bukan PDF: tetap teks "tidak didukung" (saklar menyala menyebut PDF).
  const txt = await pickedForScan(new File([bytesOf('halo')], 'catatan', { type: '' }), true);
  assert.equal(txt.failure.text, 'Pilih file foto (JPG/PNG) atau PDF');
  // Aturan 10 MB tetap berlaku setelah diberi tipe.
  const big = await pickedForScan(new File([PDF_CONTENT, new Uint8Array(PDF_MAX_BYTES)], 'besar', { type: '' }), true);
  assert.equal(big.failure.text, 'PDF terlalu besar (maks 10 MB)');
});
