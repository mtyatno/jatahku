import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldShowPrivateToggle } from './privateToggle.js';

const shared = { owner_id: null };            // shared == no owner
const personal = { owner_id: 'user-123' };    // personal == owned

test('shown when household >1 and envelope shared', () => {
  assert.equal(shouldShowPrivateToggle(2, shared), true);
});

test('hidden when solo household', () => {
  assert.equal(shouldShowPrivateToggle(1, shared), false);
});

test('hidden when envelope is personal (owned)', () => {
  assert.equal(shouldShowPrivateToggle(3, personal), false);
});

test('hidden when no envelope selected', () => {
  assert.equal(shouldShowPrivateToggle(3, null), false);
});

test('hidden in a business room for every role (decision 11 Nov 2026)', () => {
  assert.equal(shouldShowPrivateToggle(5, shared, { ruangUsaha: true }), false);
  assert.equal(shouldShowPrivateToggle(5, shared, { ruangUsaha: false }), true);
  assert.equal(shouldShowPrivateToggle(5, shared, {}), true);
});
