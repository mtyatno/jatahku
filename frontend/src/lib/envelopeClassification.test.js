import { test } from 'node:test';
import assert from 'node:assert/strict';
import { needsClassification, suggestClassification, PURPOSE_OPTIONS } from './envelopeClassification.js';

test('needsClassification true for expense and debt', () => {
  assert.equal(needsClassification('expense'), true);
  assert.equal(needsClassification('debt'), true);
});

test('needsClassification false for saving and sinking_fund', () => {
  assert.equal(needsClassification('saving'), false);
  assert.equal(needsClassification('sinking_fund'), false);
});

test('suggestClassification maps needs keywords', () => {
  assert.equal(suggestClassification('Listrik PLN'), 'needs');
  assert.equal(suggestClassification('Belanja sembako'), 'needs');
  assert.equal(suggestClassification('Cicilan motor'), 'needs');
});

test('suggestClassification maps wants keywords', () => {
  assert.equal(suggestClassification('Kopi kekinian'), 'wants');
  assert.equal(suggestClassification('Langganan Netflix'), 'wants');
  assert.equal(suggestClassification('Jajan game'), 'wants');
});

test('suggestClassification returns null when no keyword matches', () => {
  assert.equal(suggestClassification('Amplop XYZ'), null);
  assert.equal(suggestClassification(''), null);
});

test('PURPOSE_OPTIONS has the four purposes in order', () => {
  assert.deepEqual(PURPOSE_OPTIONS.map(p => p.key), ['expense', 'debt', 'saving', 'sinking_fund']);
});
