import { test } from 'node:test';
import assert from 'node:assert/strict';
import { advisorStrip, emergencyField, guessEmergency } from './envelopeStrip.js';

const page = {
  enabled: true,
  amplop: {
    makan: {
      id: 'AMP-03:makan', tone: 'warn', chip: 'Habis ±24 Okt', judul: 'Makan: maksimal Rp153 rb/hari', isi: 'Kalau tetap…',
      aksi: [{ kind: 'plan', label: 'Geser Rp525 rb', payload: {} }, { kind: 'route', label: 'Lihat', payload: {} },
        { kind: 'chat', label: 'Tanya', payload: {} }, { kind: 'x' }],
      dismiss: { kunci: 'AMP-03:makan', pilihan: ['nanti'] },
    },
    tabungan: { id: null, tone: 'ok', judul: 'Liburan: saldo Rp750 rb', isi: '', aksi: [], dismiss: null },
    rahasia: null,
  },
};

test('v2: tone server dipetakan, maksimal 2 tombol berlabel', () => {
  const s = advisorStrip(page, 'makan');
  assert.equal(s.mode, 'v2');
  assert.equal(s.tone, 'warning');
  assert.equal(s.text, 'Makan: maksimal Rp153 rb/hari');
  assert.deepEqual(s.actions.map(a => a.label), ['Geser Rp525 rb', 'Lihat']);
  assert.equal(s.dismissKey, 'AMP-03:makan');
});

test('baris dasar: ok → safe, tanpa dismiss', () => {
  const s = advisorStrip(page, 'tabungan');
  assert.equal(s.tone, 'safe');
  assert.equal(s.dismissKey, null);
  assert.deepEqual(s.actions, []);
});

test('null = semua disembunyikan → tanpa strip', () => {
  assert.deepEqual(advisorStrip(page, 'rahasia'), { mode: 'hidden' });
});

test('legacy: flag mati, gagal muat, atau amplop belum ada di respons', () => {
  assert.equal(advisorStrip({ enabled: false }, 'makan').mode, 'legacy');
  assert.equal(advisorStrip(null, 'makan').mode, 'legacy');
  assert.equal(advisorStrip(page, 'baru').mode, 'legacy');
  assert.equal(advisorStrip(page, 'toString').mode, 'legacy');
});

test('tone tak dikenal → neutral', () => {
  assert.equal(advisorStrip({ enabled: true, amplop: { a: { tone: '??', judul: 'x' } } }, 'a').tone, 'neutral');
});

test('dana darurat: tebakan nama sama dengan backend', () => {
  assert.equal(guessEmergency('Dana Darurat'), true);
  assert.equal(guessEmergency('Emergency fund'), true);
  assert.equal(guessEmergency('Liburan'), false);
  assert.equal(guessEmergency(null), false);
});

test('dana darurat: field body hanya untuk tabungan', () => {
  assert.equal(emergencyField('expense', true), false);
  assert.equal(emergencyField('saving', true), true);
  assert.equal(emergencyField('sinking_fund', false), false);
  assert.equal(emergencyField('saving', null), null);
});
