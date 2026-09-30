import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  toNumber, unassigned, allToOne, canSubmit, toApplyLines, formatLastChecked, errorText,
} from './balanceCheck.js';

const L = (id, amount, extra = {}) => ({ envelope_id: id, name: id, emoji: '', remaining: 100000, amount, ...extra });

test('toNumber handles strings, blanks, junk', () => {
  assert.equal(toNumber('12000'), 12000);
  assert.equal(toNumber(''), 0);
  assert.equal(toNumber('abc'), 0);
  assert.equal(toNumber(undefined), 0);
});

test('unassigned = total - sum(lines), tolerant of strings and float noise', () => {
  assert.equal(unassigned(340000, [L('a', '227000'), L('b', 113000)]), 0);
  assert.equal(unassigned(340000, [L('a', 200000)]), 140000);
  assert.equal(unassigned(0.3, [L('a', 0.1), L('b', 0.2)]), 0);
  assert.equal(unassigned(100, [L('a', 150)]), -50);
});

test('allToOne puts everything on an existing line and zeroes the rest', () => {
  const out = allToOne([L('a', 200000), L('b', 140000)], { envelope_id: 'b', name: 'b', emoji: '', remaining: 50000 }, 340000);
  assert.deepEqual(out.map(l => [l.envelope_id, l.amount]), [['a', 0], ['b', 340000]]);
});

test('allToOne appends a target that is not in the list', () => {
  const out = allToOne([L('a', 340000)], { envelope_id: 'debt', name: 'Cicilan', emoji: '', remaining: 300000 }, 340000);
  assert.deepEqual(out.map(l => [l.envelope_id, l.amount]), [['a', 0], ['debt', 340000]]);
  assert.equal(out[1].name, 'Cicilan');
});

test('canSubmit rules per direction', () => {
  assert.equal(canSubmit('match', 0, [], ''), true);
  assert.equal(canSubmit('surplus', 200000, [], ''), false);
  assert.equal(canSubmit('surplus', 200000, [], 'tab'), true);
  assert.equal(canSubmit('unrecorded_expense', 340000, [L('a', 340000)], ''), true);
  assert.equal(canSubmit('unrecorded_expense', 340000, [L('a', 300000)], ''), false);
  assert.equal(canSubmit('unrecorded_expense', 340000, [L('a', 350000), L('b', -10000)], ''), false);
  assert.equal(canSubmit('unrecorded_expense', 0, [L('a', 0)], ''), false);
  assert.equal(canSubmit(undefined, 0, [], ''), false);
});

test('toApplyLines drops zero lines and shapes payload', () => {
  assert.deepEqual(
    toApplyLines('unrecorded_expense', [L('a', '227000'), L('b', 0), L('c', 113000)], '', 340000),
    [{ envelope_id: 'a', amount: 227000 }, { envelope_id: 'c', amount: 113000 }],
  );
  assert.deepEqual(toApplyLines('surplus', [], 'tab', 200000), [{ envelope_id: 'tab', amount: 200000 }]);
  assert.deepEqual(toApplyLines('match', [L('a', 1)], '', 0), []);
});

test('formatLastChecked', () => {
  const now = new Date(2026, 8, 30, 20, 0);
  assert.equal(formatLastChecked(null, now), 'belum pernah');
  assert.equal(formatLastChecked(new Date(2026, 8, 30, 1, 0).toISOString(), now), 'hari ini');
  assert.equal(formatLastChecked(new Date(2026, 8, 29, 23, 0).toISOString(), now), 'kemarin');
  assert.equal(formatLastChecked(new Date(2026, 8, 18, 12, 0).toISOString(), now), '12 hari lalu');
});

test('errorText only trusts string detail', () => {
  assert.equal(errorText({ detail: 'Data berubah' }, 'x'), 'Data berubah');
  assert.equal(errorText({ detail: [{ msg: 'bad' }] }, 'Gagal menyimpan'), 'Gagal menyimpan');
  assert.equal(errorText({}, 'Gagal'), 'Gagal');
  assert.equal(errorText(null, 'Gagal'), 'Gagal');
  assert.equal(errorText({ detail: '' }, 'Gagal'), 'Gagal');
});
