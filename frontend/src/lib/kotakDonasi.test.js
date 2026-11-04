import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CONSENT_TEXT, consentView, toggleOutcome } from './kotakDonasi.js';

// Bentuk GET/PUT /user/kotak-donasi (app/api/routes/user_settings.py KotakDonasiOut). Data karangan.
const resp = over => ({ available: true, consented: false, consented_at: null, ...over });

test('CONSENT_TEXT: teks pemilik apa adanya (judul + isi, tanpa tambahan)', () => {
  assert.equal(CONSENT_TEXT.title, 'Bantu Jatahku membaca bukti bayar');
  assert.equal(CONSENT_TEXT.body,
    'Bantu Jatahku menjadi lebih tepat dalam membaca berbagai model dan bentuk bukti bayar (struk) dari berbagai bank '
    + 'dan layanan keuangan di seluruh Indonesia. Teks bukti yang sudah disamarkan dikirim ke pengelola untuk ditinjau; '
    + 'bisa dimatikan kapan saja.');
  assert.deepEqual(Object.keys(CONSENT_TEXT).sort(), ['body', 'title']);
});

test('consentView: kartu tidak tampil bila saklar mati dan belum setuju', () => {
  const v = consentView(resp({ available: false }));
  assert.equal(v.show, false);
  assert.equal(v.on, false);
});

test('consentView: tampil saat tersedia (mati), dan saat sudah setuju walau saklar mati (untuk menarik)', () => {
  const off = consentView(resp());
  assert.deepEqual([off.show, off.on, off.since], [true, false, null]);
  assert.equal(off.label, 'Mati');
  assert.equal(off.closed, null);

  const on = consentView(resp({ consented: true, consented_at: '2026-11-04T18:30:00Z' }));
  assert.deepEqual([on.show, on.on], [true, true]);
  assert.equal(on.since, '5 Nov 2026');   // hari WIB
  assert.equal(on.label, 'Aktif sejak 5 Nov 2026');

  const closed = consentView(resp({ available: false, consented: true, consented_at: '2026-10-01T03:00:00Z' }));
  assert.deepEqual([closed.show, closed.on], [true, true]);
  assert.match(closed.closed, /bisa mematikannya/);
});

test('consentView: tanggal rusak → tanpa "sejak"; data rusak → null, tidak melempar', () => {
  const v = consentView(resp({ consented: true, consented_at: 'kemarin' }));
  assert.equal(v.since, null);
  assert.equal(v.label, 'Aktif');
  for (const bad of [null, undefined, 'x', [], {}, { available: 'ya', consented: false }, { available: true }]) {
    assert.equal(consentView(bad), null);
  }
});

test('toggleOutcome: berhasil menyalakan / mematikan → teks dan tampilan baru', () => {
  const on = toggleOutcome({ ok: true, status: 200, data: resp({ consented: true, consented_at: '2026-11-05T01:00:00Z' }) });
  assert.equal(on.kind, 'ok');
  assert.equal(on.view.on, true);
  assert.match(on.text, /aktif/i);
  const off = toggleOutcome({ ok: true, status: 200, data: resp() });
  assert.equal(off.kind, 'ok');
  assert.equal(off.view.on, false);
  assert.match(off.text, /dimatikan/i);
  // 2xx dengan isi rusak: tetap berhasil, tampilan dimuat ulang
  assert.deepEqual(toggleOutcome({ ok: true, status: 200, data: {} }).view, null);
});

test('toggleOutcome: 409 → teks server; galat lain → teks aman; tidak pernah melempar', () => {
  const c = toggleOutcome({ ok: false, status: 409, data: { detail: 'Donasi contoh belum dibuka' } });
  assert.deepEqual([c.kind, c.text, c.view], ['conflict', 'Donasi contoh belum dibuka.', null]);
  assert.equal(toggleOutcome({ ok: false, status: 409, data: {} }).text, 'Donasi contoh belum dibuka.');
  assert.equal(toggleOutcome({ ok: false, status: 409, data: { detail: '{"x":1}' } }).text, 'Donasi contoh belum dibuka.');
  assert.equal(toggleOutcome({ ok: false, status: 0, data: {} }).text, 'Koneksi gagal, coba lagi.');
  assert.equal(toggleOutcome({ ok: false, status: 500, data: {} }).kind, 'error');
  for (const bad of [null, undefined, 'x', {}]) assert.equal(toggleOutcome(bad).kind, 'error');
});
