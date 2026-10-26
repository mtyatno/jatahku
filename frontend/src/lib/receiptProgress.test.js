import test from 'node:test';
import assert from 'node:assert/strict';
import { STAGE, stageLabel, stageSteps, failureMessage } from './receiptProgress.js';

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

test('stageSteps: tahap sebelum aktif selesai, sesudahnya belum', () => {
  assert.deepEqual(stageSteps(STAGE.UPLOADING).map(s => [s.key, s.state]),
    [['preparing', 'done'], ['uploading', 'active'], ['reading', 'todo']]);
  assert.deepEqual(stageSteps(STAGE.READING).map(s => s.label), ['Menyiapkan foto', 'Mengunggah', 'Membaca struk']);
});

test('failureMessage: foto tidak bisa dibuka → hanya Foto ulang', () => {
  assert.deepEqual(failureMessage({ stage: STAGE.PREPARING }),
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

test('failureMessage: penolakan server memakai detail; 429 tanpa Coba lagi/Foto ulang; 5xx bisa Coba lagi', () => {
  const quota = failureMessage({ stage: STAGE.READING, status: 429, detail: 'Kuota scan struk bulan ini (15x) sudah habis.' });
  assert.deepEqual(quota, { text: 'Kuota scan struk bulan ini (15x) sudah habis.', canRetry: false, canRetake: false });
  assert.equal(failureMessage({ stage: STAGE.READING, status: 413, detail: 'Foto terlalu besar' }).canRetry, false);
  assert.equal(failureMessage({ stage: STAGE.READING, status: 502 }).canRetry, true);
  assert.equal(failureMessage({ stage: STAGE.READING, status: 502 }).text, 'Scan struk gagal, coba lagi');
});
