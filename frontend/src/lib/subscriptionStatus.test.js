import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  unpaidMonthlyTotal, sortForPayment, statusMeta,
  monthlyEquivalentTotal, paidMonthlyTotal, nearestDue,
} from './subscriptionStatus.js';

const it = (over) => ({ id: 'x', amount: 100000, frequency: 'monthly', status: 'due', ...over });

test('unpaidMonthlyTotal sums monthly non-paid only', () => {
  const items = [
    it({ id: 'a', amount: 1600000, status: 'overdue' }),
    it({ id: 'b', amount: 110000, status: 'due' }),
    it({ id: 'c', amount: 380000, status: 'paid' }),           // excluded (paid)
    it({ id: 'd', amount: 500000, frequency: 'yearly', status: 'upcoming' }), // excluded (not monthly)
  ];
  assert.equal(unpaidMonthlyTotal(items), 1710000);
});

test('sortForPayment orders overdue, due, upcoming, paid', () => {
  const order = sortForPayment([
    it({ id: 'p', status: 'paid' }), it({ id: 'u', status: 'upcoming' }),
    it({ id: 'd', status: 'due' }), it({ id: 'o', status: 'overdue' }),
  ]).map(i => i.id);
  assert.deepEqual(order, ['o', 'd', 'u', 'p']);
});

test('statusMeta maps to label + tone', () => {
  assert.equal(statusMeta('overdue').tone, 'danger');
  assert.equal(statusMeta('due').tone, 'warning');
  assert.equal(statusMeta('paid').tone, 'safe');
  assert.equal(statusMeta('upcoming').tone, 'neutral');
});

test('monthlyEquivalentTotal: monthly full, yearly /12, weekly *52/12', () => {
  const items = [
    it({ id: 'a', amount: 100000, frequency: 'monthly' }),
    it({ id: 'b', amount: 1200000, frequency: 'yearly' }),   // 100000/bln
    it({ id: 'c', amount: 12000, frequency: 'weekly' }),     // 12000*52/12 = 52000/bln
  ];
  assert.equal(monthlyEquivalentTotal(items), 100000 + 100000 + 52000);
  assert.equal(monthlyEquivalentTotal([]), 0);
  assert.equal(monthlyEquivalentTotal(null), 0);
});

test('paidMonthlyTotal sums monthly paid only', () => {
  const items = [
    it({ id: 'a', amount: 380000, status: 'paid' }),
    it({ id: 'b', amount: 110000, status: 'due' }),              // excluded (not paid)
    it({ id: 'c', amount: 500000, frequency: 'yearly', status: 'paid' }), // excluded (not monthly)
  ];
  assert.equal(paidMonthlyTotal(items), 380000);
});

test('nearestDue returns unpaid item with earliest next_run', () => {
  const items = [
    it({ id: 'a', status: 'due', next_run: '2026-07-20' }),
    it({ id: 'b', status: 'overdue', next_run: '2026-07-05' }),
    it({ id: 'c', status: 'paid', next_run: '2026-07-01' }),     // excluded (paid)
    it({ id: 'd', status: 'upcoming', frequency: 'yearly', next_run: '2026-12-01' }),
  ];
  assert.equal(nearestDue(items).id, 'b');
  assert.equal(nearestDue([it({ id: 'p', status: 'paid', next_run: '2026-07-01' })]), null);
  assert.equal(nearestDue([]), null);
});
