import test from 'node:test';
import assert from 'node:assert/strict';
import { analitikAktif, ringkasanPoin, harianKeDaily, sinkingButtons } from './analyticsAdvice.js';

const page = {
  enabled: true, period_start: '2026-10-01',
  ringkasan: [
    { id: 'PER-03:2026-10-01', tone: 'warn', judul: 'Belanja lebih cepat dari waktu', isi: 'x', aksi: [],
      dismiss: { kunci: 'PER-03:2026-10-01' } },
    { id: null, tone: 'ok', judul: 'Semua hari dalam jatah periode ini', isi: 'y',
      aksi: [{ kind: 'route', label: 'Lihat 4 Okt', payload: { path: '/transactions?date=2026-10-04' } }], dismiss: null },
  ],
};

test('analitikAktif: flag, bentuk, dan periode yang sama', () => {
  assert.equal(analitikAktif(page, '2026-10-01'), true);
  assert.equal(analitikAktif(page, '2026-09-01'), false);
  assert.equal(analitikAktif({ enabled: false }, '2026-10-01'), false);
  assert.equal(analitikAktif(null), false);
  assert.equal(analitikAktif({ enabled: true }), false);
});

test('ringkasanPoin: memetakan bentuk, kunci dismiss, dan tombol', () => {
  const [a, b] = ringkasanPoin(page);
  assert.deepEqual(a, { key: 'PER-03:2026-10-01', tone: 'warn', judul: 'Belanja lebih cepat dari waktu', isi: 'x',
    actions: [], dismissKey: 'PER-03:2026-10-01' });
  assert.equal(b.key, 'poin-1');
  assert.equal(b.dismissKey, null);
  assert.equal(b.actions[0].kind, 'route');
});

test('ringkasanPoin: maksimal 3 poin, tone tak dikenal jadi info', () => {
  const many = { ringkasan: Array.from({ length: 5 }, (_, i) => ({ id: `x${i}`, tone: 'aneh', judul: 'j' })) };
  const out = ringkasanPoin(many);
  assert.equal(out.length, 3);
  assert.equal(out[0].tone, 'info');
  assert.deepEqual(ringkasanPoin(null), []);
});

test('harianKeDaily: total = belanja variabel, hari kosong dibuang', () => {
  assert.deepEqual(harianKeDaily([
    { tanggal: '2026-10-01', variabel: 50000, tagihan: 300000 },
    { tanggal: '2026-10-02', variabel: 0, tagihan: 0 },
  ]), [{ date: '2026-10-01', total: 50000 }]);
  assert.deepEqual(harianKeDaily(undefined), []);
});

test('sinkingButtons: hanya kind pipa CTA yang dikenal', () => {
  const item = { actions: [
    { kind: 'make_recurring', label: 'Jadikan langganan', payload: { deskripsi: 'Netflix' } },
    { kind: 'create_recurring', label: 'Lama' },
    { kind: 'dismiss', label: 'Abaikan', payload: { kunci: 'SNK:1', pilihan: 'tidak_relevan' } },
  ] };
  assert.deepEqual(sinkingButtons(item).map(a => a.kind), ['make_recurring', 'dismiss']);
  assert.deepEqual(sinkingButtons({}), []);
});
