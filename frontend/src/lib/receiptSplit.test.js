import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  reconcileItems, splitByItem, itemDescription, summarizePlan, toReceiptItems, itemNet, buildPlan,
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

test('splitByItem: satu bagian per barang, Σ = total, voucher mengurangi barangnya', () => {
  const items = S1.map((it, i) => ({ ...it, id: `r${i}` }));
  const parts = splitByItem(items, 140500, 'env-belanja');
  assert.equal(parts.length, 8);
  assert.equal(parts.reduce((s, x) => s + x.amount, 0), 140500);
  // Rincian cocok → tiap barang = nilai bersihnya, tanpa pembagian.
  assert.deepEqual(parts.map(x => x.amount), [300, 6700, 6700, 37900, 15900, 5000, 60000, 8000]);
  assert.ok(parts.every(x => x.envelopeId === 'env-belanja'));
  assert.deepEqual(parts.map(x => x.itemId), items.map(it => it.id));
});

test('splitByItem: amplop per barang dipakai, sisanya ikut amplop struk', () => {
  const items = [{ id: 'a', name: 'SABUN', amount: 5000, envelopeId: 'e-rumah' }, { id: 'b', name: 'ROTI', amount: 8000 }];
  assert.deepEqual(splitByItem(items, 13000, 'e-makan').map(x => [x.name, x.envelopeId, x.amount]),
    [['SABUN', 'e-rumah', 5000], ['ROTI', 'e-makan', 8000]]);
});

test('splitByItem: diskon global & pajak dibagi proporsional, pembulatan tetap pas', () => {
  const items = [
    { id: 'a', name: 'A', amount: 37800 },
    { id: 'b', name: 'B', amount: 21700 },
    { id: 'c', name: 'C', amount: 17000 },
    { id: 'd', name: 'D', amount: 22900 },
  ];
  const parts = splitByItem(items, 70600, 'e1');
  assert.equal(parts.reduce((s, x) => s + x.amount, 0), 70600);
  for (const x of parts) assert.ok(Number.isInteger(x.amount));
  assert.equal(parts[0].amount, Math.round(70600 * 37800 / 99400));
});

test('splitByItem: barang dihapus tidak dicatat; barang gratis (bagian 0) dilewati', () => {
  const items = [
    { id: 'a', name: 'A', amount: 10000 },
    { id: 'x', name: 'DOBEL', amount: 10000, removed: true },
    { id: 'g', name: 'GRATIS', amount: 3000, discount: 3000 },
  ];
  assert.deepEqual(splitByItem(items, 10000, 'e1').map(x => [x.itemId, x.amount]), [['a', 10000]]);
});

test('splitByItem: tanpa barang / tanpa nilai → seluruh total satu bagian di amplop struk', () => {
  assert.deepEqual(splitByItem([], 9200, 'e1'), [{ itemId: null, name: null, envelopeId: 'e1', amount: 9200 }]);
  assert.deepEqual(splitByItem([{ id: 'a', name: 'A', amount: 0 }], 9200, 'e1').map(x => [x.itemId, x.amount]), [[null, 9200]]);
  const zero = splitByItem([{ id: 'a', name: 'A', amount: 1000 }], 0, 'e1');
  assert.equal(zero.length, 1);
  assert.equal(zero[0].amount, 0);
});

test('splitByItem: acak — Σ selalu = total, semua bagian bulat & positif', () => {
  let seed = 7;
  const rnd = n => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  for (let run = 0; run < 3000; run++) {
    const n = 1 + rnd(25);
    const items = Array.from({ length: n }, (_, i) => {
      const amount = rnd(4) === 0 ? rnd(500) : rnd(200000);
      return { id: `r${i}`, name: `B${i}`, amount, discount: rnd(5) === 0 ? rnd(amount + 1) : 0, envelopeId: rnd(3) ? '' : `e${rnd(4)}`, removed: rnd(10) === 0 };
    });
    const total = rnd(3000000);
    const parts = splitByItem(items, total, 'e-def');
    assert.equal(parts.reduce((s, x) => s + x.amount, 0), total);
    for (const x of parts) assert.ok(Number.isInteger(x.amount) && (x.amount > 0 || parts.length === 1));
  }
});

test('itemDescription: nama barang + nama toko', () => {
  assert.equal(itemDescription('Indomaret', 'ROTI TAWAR'), 'ROTI TAWAR (Indomaret)');
  assert.equal(itemDescription('', ' Sabun '), 'Sabun');
  assert.equal(itemDescription('Indomaret', ''), 'Barang (Indomaret)');
  assert.ok(itemDescription('T'.repeat(300), 'B'.repeat(450)).length <= 500);
});

test('buildPlan: 1 transaksi per barang dengan keterangan barang (toko), id stabil', () => {
  const plan = buildPlan({
    description: 'Indomaret', amount: 140500, envelopeId: 'e1',
    receiptItems: S1.map((it, i) => ({ ...it, id: `r${i}`, envelopeId: i === 3 ? 'e2' : '' })),
  });
  assert.deepEqual(plan.map(g => g.id), ['g0', 'g1', 'g2', 'g3', 'g4', 'g5', 'g6', 'g7']);
  assert.equal(plan.reduce((s, g) => s + g.amount, 0), 140500);
  assert.equal(plan[3].description, 'SCORA GENTLE CLEAN75 (Indomaret)');
  assert.equal(plan[3].envelopeId, 'e2');
  assert.ok(plan.every(g => g.saved === false && g.error === null && g.raiseLimit === false));
});

test('buildPlan: tanpa rincian bernilai → satu transaksi bernama toko', () => {
  const plan = buildPlan({ description: 'Apotek', amount: 61000, envelopeId: 'e1', receiptItems: [] });
  assert.deepEqual(plan.map(g => [g.envelopeId, g.amount, g.description, g.itemId]), [['e1', 61000, 'Apotek', null]]);
});

test('summarizePlan: ringkas per amplop, status simpan & barang gagal', () => {
  const plan = [
    { id: 'g0', envelopeId: 'e1', amount: 5000, saved: true, error: null },
    { id: 'g1', envelopeId: 'e2', amount: 7000, saved: false, error: 'Dana tidak cukup' },
    { id: 'g2', envelopeId: 'e1', amount: 3000, saved: false, error: null, raiseLimit: true },
    { id: 'g3', envelopeId: 'e2', amount: 1000, saved: false, error: 'Dana tidak cukup' },
  ];
  const rows = summarizePlan(plan);
  assert.deepEqual(rows.map(r => [r.envelopeId, r.amount, r.count, r.savedCount, r.allSaved]),
    [['e1', 8000, 2, 1, false], ['e2', 8000, 2, 0, false]]);
  assert.equal(rows[1].failedAmount, 8000);
  assert.equal(rows[1].error, 'Dana tidak cukup');
  assert.equal(rows[0].raiseLimit, true);
  assert.equal(rows[0].error, null);
});

test('toReceiptItems & itemNet', () => {
  const [it] = toReceiptItems([{ name: 'SOKLN', amount: 18900, discount: 3000, unit_price: 18900, qty: 1, flag: 'ok' }]);
  assert.equal(it.unitPrice, 18900);
  assert.equal(it.envelopeId, '');
  assert.equal(itemNet(it), 15900);
});
