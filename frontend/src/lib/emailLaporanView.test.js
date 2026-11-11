import test from 'node:test';
import assert from 'node:assert/strict';
import { barisKartu, teksAlarm } from './emailLaporanView.js';

const dasar = {
  worker_hidup: true, worker_terakhir: '2026-11-12T05:30:00+00:00', menunggu: 0, tertua_menit: null, mengirim: 0,
  terkirim_24_jam: 12, gagal_7_hari: 0, penerima: 29, ambang_penerima: 300, smtp_lokal: true, laju_per_detik: 3,
};
const baris = (k, tz = 'UTC') => Object.fromEntries(barisKartu(k, tz).map((b) => [b.label, b]));

test('worker hidup: jam lokal HH.MM dari tanda terakhir', () => {
  assert.equal(baris(dasar).Worker.nilai, 'Hidup · terakhir 05.30');
  assert.equal(baris(dasar).Worker.nada, 'baik');
  assert.equal(baris(dasar, 'Asia/Jakarta').Worker.nilai, 'Hidup · terakhir 12.30');
});

test('worker mati', () => {
  const b = baris({ ...dasar, worker_hidup: false, worker_terakhir: null }).Worker;
  assert.equal(b.nilai, 'Tidak memberi tanda hidup');
  assert.equal(b.nada, 'bahaya');
});

test('worker hidup tanpa jam yang bisa dibaca tidak memuat teks aneh', () => {
  assert.equal(baris({ ...dasar, worker_terakhir: null }).Worker.nilai, 'Hidup');
});

test('menunggu: kosong dan berumur', () => {
  assert.equal(baris(dasar).Menunggu.nilai, '0');
  assert.equal(baris({ ...dasar, menunggu: 120, tertua_menit: 425 }).Menunggu.nilai, '120 · tertua 7 jam 5 menit');
  assert.equal(baris({ ...dasar, menunggu: 3, tertua_menit: 45 }).Menunggu.nilai, '3 · tertua 45 menit');
  assert.equal(baris({ ...dasar, menunggu: 3, tertua_menit: 120 }).Menunggu.nilai, '3 · tertua 2 jam 0 menit');
  assert.equal(baris({ ...dasar, menunggu: 2, tertua_menit: null }).Menunggu.nilai, '2');
});

test('baris lain dan nada', () => {
  const b = baris({ ...dasar, gagal_7_hari: 4, penerima: 312, laju_per_detik: 2.5 });
  assert.deepEqual(barisKartu(dasar, 'UTC').map((x) => x.label),
    ['Worker', 'Menunggu', 'Terkirim 24 jam', 'Gagal 7 hari', 'Penerima', 'Laju']);
  assert.equal(b['Terkirim 24 jam'].nilai, '12');
  assert.equal(b['Gagal 7 hari'].nilai, '4');
  assert.equal(b['Gagal 7 hari'].nada, 'bahaya');
  assert.equal(baris(dasar)['Gagal 7 hari'].nada, 'biasa');
  assert.equal(b.Penerima.nilai, '312 / 300');
  assert.equal(b.Penerima.nada, 'bahaya');
  assert.equal(baris(dasar).Penerima.nada, 'biasa');
  assert.equal(b.Laju.nilai, '2,5 email/detik');
  assert.equal(baris(dasar).Laju.nilai, '3 email/detik');
});

test('penerima bahaya mulai ambang (alarm pindah_penyedia berbunyi pada >= 300)', () => {
  assert.equal(baris({ ...dasar, penerima: 299 }).Penerima.nada, 'biasa');
  assert.equal(baris({ ...dasar, penerima: 300 }).Penerima.nada, 'bahaya');
});

test('teksAlarm', () => {
  assert.equal(teksAlarm('pindah_penyedia'), 'Saatnya pindah ke penyedia email transaksional (langkah di AGENTS.md).');
  assert.equal(teksAlarm('worker_mati'), 'Worker email tidak berjalan.');
  assert.equal(teksAlarm('antrean_tersendat'), 'Antrean tersendat lebih dari 6 jam.');
  assert.equal(teksAlarm('email_gagal'), 'Ada email laporan yang gagal dikirim.');
  assert.equal(teksAlarm('tidak_dikenal'), '');
  assert.equal(teksAlarm(undefined), '');
});
