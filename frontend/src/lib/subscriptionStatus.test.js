import { test } from 'node:test';
import assert from 'node:assert/strict';
import { unpaidMonthlyTotal, sortForPayment, statusMeta } from './subscriptionStatus.js';

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
