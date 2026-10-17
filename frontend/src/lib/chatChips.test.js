import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pageChips, quickChips } from './chatChips.js';

test('chip per halaman', () => {
  assert.equal(pageChips('/langganan')[0].text, 'tagihan bulan ini');
  assert.equal(pageChips('/transactions')[0].text, 'pengeluaran hari ini');
  assert.ok(pageChips('/envelopes').some(c => c.text === 'target'));
  assert.ok(pageChips('/').some(c => c.text === 'kenapa boros?'));
  assert.deepEqual(pageChips('/langganan/'), pageChips('/langganan'));
});

test('halaman lain memakai chip bawaan', () => {
  assert.deepEqual(pageChips('/settings'), pageChips('/admin'));
  assert.deepEqual(pageChips(undefined), pageChips('/'));
  assert.ok(pageChips('/settings').length >= 4);
});

test('chip insight didahulukan, tanpa duplikat', () => {
  const draft = [{ label: 'Kenapa lewat ±Rp525 rb?', text: 'Kenapa dana belanja kurang?' },
    { label: 'Tagihan', text: 'Tagihan bulan ini' }];
  const chips = quickChips('/langganan', draft);
  assert.equal(chips[0].text, 'Kenapa dana belanja kurang?');
  assert.equal(chips[0].draft, true);
  assert.equal(chips.filter(c => c.text.toLowerCase() === 'tagihan bulan ini').length, 1);
  assert.ok(chips.some(c => c.text === '/help' && c.draft === false));
});

test('aman beli hanya mengisi kotak ketik', () => {
  const c = pageChips('/').find(x => x.label.startsWith('Aman beli'));
  assert.equal(c.fill, true);
  assert.ok(c.text.endsWith(' '));
});

test('tanpa angka di chip halaman', () => {
  for (const p of ['/', '/envelopes', '/transactions', '/allocate', '/langganan', '/analytics', '/x']) {
    for (const c of pageChips(p)) assert.doesNotMatch(c.label + c.text, /\d|Rp/);
  }
});
