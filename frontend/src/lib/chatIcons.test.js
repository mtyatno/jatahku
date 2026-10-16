import { test } from 'node:test';
import assert from 'node:assert/strict';
import { barLevel, barRatio, chatSegments } from './chatIcons.js';

const kinds = (text) => chatSegments(text).map(s => (s.t === 'text' ? s.v : `[${s.t}${s.icon ? ':' + s.icon : ''}${s.level ? ':' + s.level : ''}]`));

test('baris /status: titik status, ikon amplop, bar, persen', () => {
  assert.deepEqual(kinds('🔴 🚗 Transport · habis ▰▰▰▰▰▰ 115%'),
    ['[dot:bad]', ' ', '[emoji]', ' Transport · habis ', '[bar]', ' 115%']);
  assert.deepEqual(kinds('⚪ 📁 Tabungan · Rp1.5jt'), ['[dot:none]', ' ', '[emoji]', ' Tabungan · Rp1.5jt']);
});

test('tone insight AI Advisor: 🔵 info jadi titik', () => {
  assert.deepEqual(kinds('🔵 Klasifikasikan 1 amplop'), ['[dot:info]', ' Klasifikasikan 1 amplop']);
});

test('emoji dekoratif jadi ikon aplikasi, dengan atau tanpa variation selector', () => {
  assert.deepEqual(kinds('📊 Budget'), ['[icon:dashboard]', ' Budget']);
  assert.deepEqual(kinds('⚠️ Hati-hati'), ['[icon:warning]', ' Hati-hati']);
  assert.deepEqual(kinds('✏️ Nominal salah'), ['[icon:edit]', ' Nominal salah']);
  assert.deepEqual(kinds('💡 Per hari'), ['[icon:bulb]', ' Per hari']);
});

test('emoji wajah & keluarga tetap utuh sebagai emoji', () => {
  const segs = chatSegments('😬 boncos 👨‍👩‍👧');
  assert.deepEqual(segs.map(s => s.t), ['emoji', 'text', 'emoji']);
  assert.equal(segs[2].v, '👨‍👩‍👧');
});

test('bar teks lama & baru dikenali; teks biasa tidak', () => {
  assert.equal(barRatio('▓▓▓░░░'), 0.5);
  assert.equal(barRatio('▰▰▱▱▱▱▱▱▱▱'), 0.2);
  assert.equal(barRatio('░░░░░░'), 0);
  assert.deepEqual(kinds('Rp1.590.000 · 3 hari'), ['Rp1.590.000 · 3 hari']);
  assert.deepEqual(kinds('▰▱'), ['▰▱']); // terlalu pendek untuk disebut bar
  assert.equal(barLevel(0.95), 'bad');
  assert.equal(barLevel(0.75), 'warn');
  assert.equal(barLevel(0.2), 'ok');
});

test('garis pemisah', () => {
  assert.deepEqual(kinds('\n─────────────────\n'), ['\n', '[rule]', '\n']);
});

test('teks tanpa simbol tidak berubah', () => {
  assert.deepEqual(chatSegments('halo'), [{ t: 'text', v: 'halo' }]);
  assert.deepEqual(chatSegments(''), []);
});
