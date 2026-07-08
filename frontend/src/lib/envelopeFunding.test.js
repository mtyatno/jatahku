import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fundingState } from './envelopeFunding.js';

// remaining = allocated + rollover - spent ; free = remaining - reserved
const env = (o) => ({ allocated: 0, rollover: 0, spent: 0, reserved: 0, free: 0, ...o });

test('overspent when remaining < 0', () => {
  assert.equal(fundingState(env({ allocated: 100, spent: 150, free: -50 })), 'overspent');
});

test('reserve_short when remaining >= 0 but free < 0', () => {
  // allocated 5374000, spent 284000 -> remaining 5090000; reserved 5190000 -> free -100000
  assert.equal(fundingState(env({ allocated: 5374000, spent: 284000, reserved: 5190000, free: -100000 })), 'reserve_short');
});

test('ok when free >= 0', () => {
  assert.equal(fundingState(env({ allocated: 1000, spent: 200, reserved: 100, free: 700 })), 'ok');
});

test('remaining exactly 0 with free negative is reserve_short', () => {
  assert.equal(fundingState(env({ allocated: 100, spent: 100, reserved: 50, free: -50 })), 'reserve_short');
});
