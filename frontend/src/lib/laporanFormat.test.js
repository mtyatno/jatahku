import test from 'node:test';
import assert from 'node:assert/strict';
import { tanggalTeks, periodeTeks, hariTeks, terbitTeks, hariAngka } from './laporanFormat.js';

test('tanggalTeks: ISO tanggal dan datetime, tanpa geser zona', () => {
  assert.equal(tanggalTeks('2026-10-05'), '5 Okt 2026');
  assert.equal(tanggalTeks('2026-12-31T23:59:00Z'), '31 Des 2026');
  assert.equal(tanggalTeks(null), '—');
  assert.equal(tanggalTeks('bukan'), '—');
});
test('periodeTeks', () => {
  assert.equal(periodeTeks('2026-10-01', '2026-10-31'), '1 Okt 2026 – 31 Okt 2026');
});
test('hariTeks: hanya tanggal tanpa nol di depan', () => {
  assert.equal(hariTeks('2026-10-05'), '5');
  assert.equal(hariTeks('2026-10-31'), '31');
  assert.equal(hariTeks(undefined), '');
});
test('terbitTeks: datetime valid dan tidak valid', () => {
  assert.match(terbitTeks('2026-11-01T12:00:00Z'), /^\d{1,2} (Okt|Nov) 2026$/);
  assert.equal(terbitTeks('x'), '—');
});
test('hariAngka: null tidak pernah jadi "— hari"', () => {
  assert.equal(hariAngka(28), '28 hari');
  assert.equal(hariAngka(0), '0 hari');
  assert.equal(hariAngka(null), '—');
  assert.equal(hariAngka(undefined), '—');
});
