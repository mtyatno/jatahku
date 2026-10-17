import { test } from 'node:test';
import assert from 'node:assert/strict';
import { advisorQuery, pageEnabled, rowMarkers, pageBanner, markerActions } from './transaksiAdvisor.js';

const dobel = {
  id: 'DAT-03:t1', aturan: 'DAT-03', tone: 'warn', chip: 'Dobel?', judul: 'belanja pasar Rp150 rb tercatat 2×',
  aksi: [
    { kind: 'delete_txn', label: 'Hapus salah satu', payload: { txn_id: 't2', txn_ids: ['t2'] } },
    { kind: 'not_duplicate', label: 'Bukan dobel', payload: { kunci: 'DAT-03:t1' } },
  ],
  dismiss: { kunci: 'DAT-03:t1', pilihan: ['nanti', 'periode', 'tidak_relevan'] },
};
const besar = {
  id: 'HAR-03:t9', aturan: 'HAR-03', tone: 'info', chip: 'Belanja besar Rp2 jt',
  aksi: [{ kind: 'route', label: 'Lihat transaksi hari ini', payload: { path: '/transactions?date=2026-10-15' } }],
  dismiss: { kunci: 'HAR-03:t9', pilihan: ['nanti'] },
};
const PAGE = { enabled: true, hari_ini: '2026-10-15', banner: besar, penanda: { t1: [dobel], t2: [dobel], t9: [besar] } };

test('advisorQuery: filter tanggal, tab Hari Ini, dan amplop', () => {
  const today = '2026-10-15';
  assert.deepEqual(advisorQuery({ envelope: 'all', date: null, timeTab: 'all', today }), { tanggal: null, amplop: null });
  assert.deepEqual(advisorQuery({ envelope: 'all', date: null, timeTab: 'today', today }), { tanggal: today, amplop: null });
  assert.deepEqual(advisorQuery({ envelope: 'e1', date: '2026-10-12', timeTab: 'today', today }),
    { tanggal: '2026-10-12', amplop: 'e1' });
  assert.deepEqual(advisorQuery({ envelope: 'e1', date: null, timeTab: 'week', today }), { tanggal: null, amplop: 'e1' });
});

test('pageEnabled: di luar flag atau gagal → tidak tampil', () => {
  assert.equal(pageEnabled(null), false);
  assert.equal(pageEnabled({ enabled: false }), false);
  assert.equal(pageEnabled({ enabled: true }), false);
  assert.equal(pageEnabled(PAGE), true);
});

test('rowMarkers: per transaksi, yang baru disembunyikan tidak tampil', () => {
  assert.deepEqual(rowMarkers(PAGE, 't1'), [dobel]);
  assert.deepEqual(rowMarkers(PAGE, 'tx-lain'), []);
  assert.deepEqual(rowMarkers(PAGE, 't2', ['DAT-03:t1']), []);
  assert.deepEqual(rowMarkers({ enabled: false }, 't1'), []);
});

test('pageBanner: null bila tidak ada atau disembunyikan', () => {
  assert.equal(pageBanner(PAGE), besar);
  assert.equal(pageBanner(PAGE, ['HAR-03:t9']), null);
  assert.equal(pageBanner({ ...PAGE, banner: null }), null);
});

test('markerActions: rute ke halaman ini dengan filter yang sama dibuang, maks 2', () => {
  assert.deepEqual(markerActions(besar, '?date=2026-10-15'), []);
  assert.deepEqual(markerActions(besar, ''), besar.aksi);                // belum difilter: tetap berguna
  assert.deepEqual(markerActions({ aksi: [{ kind: 'route', payload: { path: '/transactions' } }] }, ''), []);
  assert.deepEqual(markerActions(dobel).map(a => a.kind), ['delete_txn', 'not_duplicate']);
  assert.deepEqual(markerActions(null), []);
});
