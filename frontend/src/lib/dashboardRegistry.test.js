import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  breakpointOf, deviceMatches, groupsOf, itemsForData, visibleItems, packRows, rowTemplate, rowGapAbove, rowKind,
  sumberPertama, cacheKeyData,
} from './dashboardRegistry.js';

// Template Beranda dari server (registry.TEMPLATE_BERANDA): 6 KPI, Cocokkan saldo, Pengeluaran harian,
// AI Advisor, Ke mana uangmu, Amplop pengeluaran, Target tabungan, Transaksi terbaru, Langganan.
const TEMPLATE = [
  ['a1', 'core.kpi.jatah', 'S'], ['a2', 'core.kpi.sisa_bebas', 'S'], ['a3', 'core.kpi.terpakai', 'S'],
  ['a4', 'core.kpi.income', 'S'], ['a5', 'core.kpi.tagihan', 'S'], ['a6', 'core.kpi.tabungan', 'S'],
  ['a7', 'core.cocokkan_saldo', 'S'], ['a8', 'core.pengeluaran_harian', 'L'], ['a9', 'core.advisor', 'S'],
  ['a10', 'core.ke_mana_uangmu', 'XL'], ['a11', 'core.amplop_pengeluaran', 'L'], ['a12', 'core.target_tabungan', 'S'],
  ['a13', 'core.transaksi_terbaru', 'L'], ['a14', 'core.langganan', 'S'],
].map(([id, card, size]) => ({ id, card, size, hidden: false, devices: 'all', settings: {}, visible: true }));

const OWN = { ownRow: (i) => i.card === 'core.cocokkan_saldo' };
const ids = (rows) => rows.map(r => r.cells.map(c => `${c.item.id}:${c.span}`).join(' '));

test('breakpoint mengikuti Tailwind md/lg/xl', () => {
  assert.deepEqual([375, 767, 768, 1023, 1024, 1279, 1280, 1920].map(breakpointOf),
    ['phone', 'phone', 'md', 'md', 'lg', 'lg', 'xl', 'xl']);
});

test('devices: wide ≥1024, narrow <1024', () => {
  assert.equal(deviceMatches('wide', 'lg'), true);
  assert.equal(deviceMatches('wide', 'md'), false);
  assert.equal(deviceMatches('narrow', 'phone'), true);
  assert.equal(deviceMatches('narrow', 'xl'), false);
  assert.equal(deviceMatches('all', 'phone'), true);
});

test('layar ≥1280: susunan sama dengan Beranda lama', () => {
  const rows = packRows(TEMPLATE, 'xl', OWN);
  assert.deepEqual(ids(rows), [
    'a1:4 a2:4 a3:4', 'a4:4 a5:4 a6:4', 'a7:12', 'a8:8 a9:4', 'a10:12', 'a11:8 a12:4', 'a13:8 a14:4',
  ]);
  assert.equal(rows[3].template, 'minmax(0,1.65fr) minmax(0,1fr)');
  assert.equal(rows[0].template, 'minmax(0,4fr) minmax(0,4fr) minmax(0,4fr)');
});

test('layar 1024–1279: KPI 3 kolom, kartu lain bertumpuk penuh (Beranda lama di bawah xl)', () => {
  assert.deepEqual(ids(packRows(TEMPLATE, 'lg', OWN)), [
    'a1:4 a2:4 a3:4', 'a4:4 a5:4 a6:4', 'a7:12', 'a8:12', 'a9:12', 'a10:12', 'a11:12', 'a12:12', 'a13:12', 'a14:12',
  ]);
});

test('tablet: KPI 2 kolom; HP: semua penuh', () => {
  assert.deepEqual(ids(packRows(TEMPLATE, 'md', OWN)).slice(0, 4), ['a1:6 a2:6', 'a3:6 a4:6', 'a5:6 a6:6', 'a7:12']);
  assert.ok(packRows(TEMPLATE, 'phone', OWN).every(r => r.cells.length === 1 && r.cells[0].span === 12));
});

test('kartu yang tidak tampil tidak menyisakan lubang: pasangannya melebar', () => {
  const tanpaAdvisor = TEMPLATE.filter(i => i.id !== 'a9');
  assert.deepEqual(ids(packRows(tanpaAdvisor, 'xl', OWN)).slice(3, 5), ['a8:12', 'a10:12']);
  const tanpaTarget = TEMPLATE.filter(i => i.id !== 'a12');
  assert.equal(ids(packRows(tanpaTarget, 'xl', OWN))[5], 'a11:12');
});

test('tanpa ownRow, S berikutnya mengisi sisa baris', () => {
  const items = [{ id: 'x', size: 'S' }, { id: 'y', size: 'L' }];
  assert.deepEqual(ids(packRows(items, 'xl')), ['x:4 y:8']);
});

test('baris campuran memakai fr sesuai span', () => {
  assert.equal(rowTemplate([6, 6], 'xl'), 'minmax(0,6fr) minmax(0,6fr)');
  assert.equal(rowTemplate([8, 4], 'lg'), 'minmax(0,8fr) minmax(0,4fr)');
  assert.equal(rowTemplate([12], 'xl'), 'minmax(0,1fr)');
});

test('jarak antarbaris meniru Beranda lama', () => {
  assert.equal(rowGapAbove(null, 'kpi'), 0);
  assert.equal(rowGapAbove('kpi', 'kpi'), 12);
  assert.equal(rowGapAbove('kpi', 'link'), 24);
  assert.equal(rowGapAbove('link', 'card'), 24);
  assert.equal(rowGapAbove('card', 'card'), 24);
  assert.equal(rowGapAbove('card', 'card', true), 16);
  const g = groupsOf(TEMPLATE, OWN);
  assert.equal(g.a8, g.a9, 'Pengeluaran harian + AI Advisor satu kelompok');
  assert.equal(g.a11, g.a12);
  assert.notEqual(g.a9, g.a10);
  assert.equal(rowKind(['kpi', 'kpi']), 'kpi');
  assert.equal(rowKind(['link']), 'link');
  assert.equal(rowKind(['kpi', 'card']), 'card');
});

test('instans tersembunyi, tidak dikenal, atau di perangkat lain tidak tampil', () => {
  const layout = { items: [
    { id: 'a', card: 'core.kpi.jatah', size: 'S' },
    { id: 'b', card: 'core.kpi.income', size: 'S', hidden: true },
    { id: 'c', card: 'plugin.x', size: 'S' },
    { id: 'd', card: 'core.langganan', size: 'S', devices: 'wide' },
    { id: 'e', card: 'core.advisor', size: 'S', visible: false },
  ] };
  const known = (k) => k.startsWith('core.');
  assert.deepEqual(visibleItems(layout, 'phone', known).map(i => i.id), ['a']);
  assert.deepEqual(visibleItems(layout, 'xl', known).map(i => i.id), ['a', 'd']);
  assert.deepEqual(itemsForData(layout, known), [
    { id: 'a', card: 'core.kpi.jatah', settings: {} }, { id: 'd', card: 'core.langganan', settings: {} },
  ]);
});

test('sumber pertama dari respons batch', () => {
  const data = { a1: { error: { kode: 'gagal_memuat' } }, a2: { sumber: { prediksi: null } },
    a3: { sumber: { prediksi: { safe_daily: 1 }, ringkasan_amplop: [] } } };
  assert.deepEqual(sumberPertama(data, 'prediksi'), { safe_daily: 1 });
  assert.deepEqual(sumberPertama(data, 'ringkasan_amplop'), []);
  assert.equal(sumberPertama(data, 'target'), undefined);
  assert.equal(sumberPertama(null, 'target'), undefined);
});

test('kunci cache per user', () => {
  assert.notEqual(cacheKeyData('u1'), cacheKeyData('u2'));
});
