import { test } from 'node:test';
import assert from 'node:assert/strict';
import { unclassifiedEnvelopes } from './classificationBackfill.js';

const env = (over) => ({ id: '1', name: 'X', purpose: 'expense', classification: null, ...over });

test('includes expense with null classification', () => {
  const r = unclassifiedEnvelopes([env({ id: 'a' })]);
  assert.deepEqual(r.map(e => e.id), ['a']);
});

test('includes debt with null classification', () => {
  const r = unclassifiedEnvelopes([env({ id: 'b', purpose: 'debt' })]);
  assert.deepEqual(r.map(e => e.id), ['b']);
});

test('excludes already-classified', () => {
  const r = unclassifiedEnvelopes([env({ id: 'c', classification: 'needs' })]);
  assert.equal(r.length, 0);
});

test('excludes saving and sinking_fund regardless of classification', () => {
  const r = unclassifiedEnvelopes([
    env({ id: 'd', purpose: 'saving' }),
    env({ id: 'e', purpose: 'sinking_fund' }),
  ]);
  assert.equal(r.length, 0);
});

test('empty input -> empty', () => {
  assert.deepEqual(unclassifiedEnvelopes([]), []);
});
