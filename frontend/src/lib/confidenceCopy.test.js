import { test } from 'node:test';
import assert from 'node:assert/strict';
import { confidenceLabel, confidenceTone } from './confidenceCopy.js';

test('labels map to Indonesian', () => {
  assert.equal(confidenceLabel('high'), 'Tinggi');
  assert.equal(confidenceLabel('medium'), 'Sedang');
  assert.equal(confidenceLabel('low'), 'Rendah');
});

test('unknown label passes through', () => {
  assert.equal(confidenceLabel('weird'), 'weird');
  assert.equal(confidenceLabel(undefined), '');
});

test('tone maps by level', () => {
  assert.equal(confidenceTone('high'), 'green');
  assert.equal(confidenceTone('medium'), 'amber');
  assert.equal(confidenceTone('low'), 'gray');
  assert.equal(confidenceTone('weird'), 'gray');
});
