import { test } from 'node:test';
import assert from 'node:assert/strict';
import { askItems, pendingItems, pollDelay, staleItems, POLL_DELAYS_MS, STALE_MS } from './chatPending.js';

const A = '11111111-2222-4333-8444-555555555555';
const B = '22222222-2222-4333-8444-555555555555';
const btn = [[{ text: 'Makan', data: 't_ab_0' }]];
const bot = (id, over = {}) => ({ id, role: 'bot', text: 'x', format: 'plain', buttons: [], ts: 1, ...over });

test('gelembung yang masih dibaca: pasangan item dan pesan, hanya pesan bot yang menunggu', () => {
  const messages = [
    { id: 'u1', role: 'user', text: 'foto', buttons: [], ts: 1 },
    bot('b1', { item: A, pending: true }),
    bot('b2', { item: B, pending: false, buttons: btn, renderedAt: 5 }),
    bot('b3'),
  ];
  assert.deepEqual(pendingItems(messages), [{ item_id: A, message_id: 'b1' }]);
});

test('tombol yang hampir kedaluwarsa (sesi bot 10 menit) disegarkan; tanpa tombol atau masih baru tidak', () => {
  const now = 1_000_000;
  const messages = [
    bot('b1', { item: A, buttons: btn, renderedAt: now - STALE_MS }),        // basi
    bot('b2', { item: B, buttons: btn, renderedAt: now - STALE_MS + 1000 }), // masih segar
    bot('b3', { item: B, buttons: [], renderedAt: now - 2 * STALE_MS }),     // tanpa tombol: tidak ada yang basi
    bot('b4', { buttons: btn, renderedAt: now - 2 * STALE_MS }),             // bukan gelembung bukti
    bot('b5', { item: A, pending: true, buttons: [] }),                      // masih dibaca: bukan basi
  ];
  assert.deepEqual(staleItems(messages, now), [{ item_id: A, message_id: 'b1' }]);
  assert.ok(STALE_MS < 10 * 60 * 1000);
});

test('askItems: menunggu selalu, yang basi hanya saat refresh, tanpa duplikat pasangan', () => {
  const now = 1_000_000;
  const messages = [
    bot('b1', { item: A, pending: true }),
    bot('b2', { item: B, buttons: btn, renderedAt: now - STALE_MS }),
  ];
  assert.deepEqual(askItems(messages, now, { refresh: false }), [{ item_id: A, message_id: 'b1' }]);
  assert.deepEqual(askItems(messages, now, { refresh: true }),
    [{ item_id: A, message_id: 'b1' }, { item_id: B, message_id: 'b2' }]);
  assert.deepEqual(askItems([], now, { refresh: true }), []);
});

test('jeda tanya ulang membesar lalu menetap', () => {
  assert.deepEqual(POLL_DELAYS_MS.map((_, i) => pollDelay(i)), POLL_DELAYS_MS);
  assert.equal(pollDelay(POLL_DELAYS_MS.length + 5), POLL_DELAYS_MS[POLL_DELAYS_MS.length - 1]);
  assert.equal(pollDelay(0) >= 2000, true);
  assert.equal(pollDelay(99) <= 30_000, true);
});
