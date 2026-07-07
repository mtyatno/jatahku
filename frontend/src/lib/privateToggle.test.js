import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldShowPrivateToggle } from './privateToggle.js';

const shared = { is_personal: false };
const personal = { is_personal: true };

test('shown when household >1 and envelope shared', () => {
  assert.equal(shouldShowPrivateToggle(2, shared), true);
});

test('hidden when solo household', () => {
  assert.equal(shouldShowPrivateToggle(1, shared), false);
});

test('hidden when envelope is personal', () => {
  assert.equal(shouldShowPrivateToggle(3, personal), false);
});

test('hidden when no envelope selected', () => {
  assert.equal(shouldShowPrivateToggle(3, null), false);
});
