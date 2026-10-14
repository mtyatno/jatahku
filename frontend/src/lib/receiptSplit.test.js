import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  reconcileItems, splitByEnvelope, isSplit, groupDescription, toReceiptItems, itemNet, buildPlan,
} from './receiptSplit.js';

// Struk Indomaret asli (#1): 8 barang 149.500, voucher melekat 9.000, total 140.500.
const S1 = [
  { name: 'IDM KTG PLSTK 1W BSR', amount: 300, discount: 0 },
  { name: 'NBATI SIIP COKLAT 57', amount: 6700, discount: 0 },
  { name: 'NBATI SIIP JG.BKR 62', amount: 6700, discount: 0 },
  { name: 'SCORA GENTLE CLEAN75', amount: 37900, discount: 0 },
  { name: 'SOKLN SOFTR ROSY 720', amount: 18900, discount: 3000 },
  { name: 'CHOCOLITO RC.CHO 38G', amount: 6000, discount: 1000 },
  { name: 'HOLISTICARE VIT.C 30', amount: 60000, discount: 0 },
  { name: 'YC SS BKR SAPI KEJU', amount: 13000, discount: 5000 },
];

test('reconcileItems: rincian cocok dengan total (voucher melekat)', () => {
  const r = reconcileItems(S1, [], 140500);
  assert.equal(r.itemsTotal, 149500);
  assert.equal(r.discounts, 9000);
  assert.equal(r.diff, 0);
  assert.equal(r.status, 'cocok');
});

test('reconcileItems: diskon global & pajak ikut dihitung; barang dihapus tidak dihitung', () => {
  const items = [{ name: 'A', amount: 99400 }, { name: 'X', amount: 5000, removed: true }];
  const adj = [{ kind: 'discount', amount: 5900 }, { kind: 'discount', amount: 22900 }];
  assert.equal(reconcileItems(items, adj, 70600).status, 'cocok');
  const resto = reconcileItems([{ name: 'Nasi', amount: 40000 }], [{ kind: 'charge', amount: 4000 }], 44000);
  assert.equal(resto.status, 'cocok');
  const kurang = reconcileItems([{ name: 'Nasi', amount: 40000 }], [], 44000);
  assert.deepEqual([kurang.status, kurang.diff], ['selisih', 4000]);
});

test('splitByEnvelope: satu amplop → seluruh total', () => {
  const g = splitByEnvelope(S1, 140500, 'env-belanja');
  assert.deepEqual(g.map(x => [x.envelopeId, x.amount]), [['env-belanja', 140500]]);
  assert.equal(isSplit(S1, 'env-belanja'), false);
});

test('splitByEnvelope: dipecah dua amplop, Σ = total, voucher mengurangi barangnya', () => {
  const items = S1.map(it => (it.name.startsWith('HOLISTICARE') || it.name.startsWith('SCORA')
    ? { ...it, envelopeId: 'env-sehat' } : it));
  assert.equal(isSplit(items, 'env-belanja'), true);
  const g = splitByEnvelope(items, 140500, 'env-belanja');
  assert.equal(g.reduce((s, x) => s + x.amount, 0), 140500);
  assert.equal(g[0].envelopeId, 'env-belanja'); // amplop struk di urutan pertama
  // Rincian cocok → tiap amplop = Σ bersih barangnya, tanpa pembagian.
  assert.deepEqual(g.map(x => x.amount), [42600, 97900]);
});

test('splitByEnvelope: diskon global dibagi proporsional, pembulatan tetap pas', () => {
  const items = [
    { name: 'A', amount: 37800, envelopeId: 'e1' },
    { name: 'B', amount: 21700, envelopeId: 'e2' },
    { name: 'C', amount: 17000, envelopeId: 'e2' },
    { name: 'D', amount: 22900, envelopeId: 'e3' },
  ];
  const g = splitByEnvelope(items, 70600, 'e1');
  assert.equal(g.reduce((s, x) => s + x.amount, 0), 70600);
  for (const x of g) assert.ok(Number.isInteger(x.amount));
  // e1 memegang 37.800 / 99.400 dari total
  assert.equal(g.find(x => x.envelopeId === 'e1').amount, Math.round(70600 * 37800 / 99400));
});

test('splitByEnvelope: tanpa barang → total ke amplop struk', () => {
  assert.deepEqual(splitByEnvelope([], 9200, 'e1').map(x => [x.envelopeId, x.amount]), [['e1', 9200]]);
});

test('groupDescription: nama toko (+ jumlah barang bila dipecah), tanpa nama barang', () => {
  assert.equal(groupDescription('Indomaret', 2, { split: false }), 'Indomaret');
  assert.equal(groupDescription('Indomaret', 3, { split: true }), 'Indomaret (3 barang)');
});

test('splitByEnvelope: total 0 dengan beberapa amplop tetap menghasilkan satu bagian', () => {
  const g = splitByEnvelope([{ name: 'A', amount: 1000, envelopeId: 'e2' }, { name: 'B', amount: 0 }], 0, 'e1');
  assert.equal(g.length, 1);
  assert.equal(g[0].amount, 0);
});

test('buildPlan: semua barang ke amplop lain → satu bagian ke amplop itu (bukan amplop struk)', () => {
  const plan = buildPlan({
    description: 'Apotek', amount: 61000, envelopeId: 'e-belanja',
    receiptItems: [{ name: 'VITAMIN', amount: 61000, envelopeId: 'e-sehat' }],
  });
  assert.deepEqual(plan.map(g => [g.envelopeId, g.amount, g.description]), [['e-sehat', 61000, 'Apotek']]);
});

test('buildPlan: dipecah → id stabil, deskripsi berjumlah barang, Σ = total', () => {
  const plan = buildPlan({
    description: 'Indomaret', amount: 140500, envelopeId: 'e1',
    receiptItems: S1.map((it, i) => (i === 3 ? { ...it, envelopeId: 'e2' } : it)),
  });
  assert.deepEqual(plan.map(g => g.id), ['g0', 'g1']);
  assert.equal(plan.reduce((s, g) => s + g.amount, 0), 140500);
  assert.equal(plan[1].description, 'Indomaret (1 barang)');
  assert.ok(plan.every(g => g.saved === false && g.error === null));
});

test('toReceiptItems & itemNet', () => {
  const [it] = toReceiptItems([{ name: 'SOKLN', amount: 18900, discount: 3000, unit_price: 18900, qty: 1, flag: 'ok' }]);
  assert.equal(it.unitPrice, 18900);
  assert.equal(it.envelopeId, '');
  assert.equal(itemNet(it), 15900);
});
