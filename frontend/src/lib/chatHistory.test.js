import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  applyOps, clearAllHistory, loadHistory, saveHistory, historyKey, looksLikeChange, userMessage, userPhotoMessage, MAX_MESSAGES,
} from './chatHistory.js';

function memStorage(init = {}) {
  const s = { ...init };
  return {
    getItem: k => (k in s ? s[k] : null),
    setItem: (k, v) => { s[k] = String(v); },
    removeItem: k => { delete s[k]; },
    dump: () => s,
  };
}

const btn = [[{ text: 'Makan', data: 't_ab_0' }]];

test('pesan baru, edit, ganti tombol, toast', () => {
  let { messages, toasts } = applyOps([], [
    { type: 'message', id: 'a1', text: 'Masuk ke amplop mana?', format: 'plain', buttons: btn },
  ], 1);
  assert.equal(messages.length, 1);
  assert.deepEqual(messages[0].buttons, btn);
  ({ messages, toasts } = applyOps(messages, [
    { type: 'toast', text: 'Sip' },
    { type: 'edit', id: 'a1', text: '✅ <b>Tercatat</b>', format: 'html', buttons: [] },
  ]));
  assert.deepEqual(toasts, ['Sip']);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].text, '✅ <b>Tercatat</b>');
  assert.equal(messages[0].format, 'html');
  assert.deepEqual(messages[0].buttons, []);
  ({ messages } = applyOps(messages, [{ type: 'buttons', id: 'a1', buttons: btn }]));
  assert.deepEqual(messages[0].buttons, btn);
});

test('edit untuk pesan yang sudah terpangkas ditambahkan sebagai pesan baru', () => {
  const { messages } = applyOps([], [{ type: 'edit', id: 'zz', text: 'hai', format: 'plain', buttons: [] }]);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].role, 'bot');
});

test('riwayat dibatasi dan pesan "sending" saat dibuka ulang jadi gagal', () => {
  const store = memStorage();
  const many = Array.from({ length: MAX_MESSAGES + 20 }, (_, i) => ({ ...userMessage(`m${i}`), status: undefined }));
  many[many.length - 1].status = 'sending';
  saveHistory('u1', many, store);
  const back = loadHistory('u1', store);
  assert.equal(back.length, MAX_MESSAGES);
  assert.equal(back[back.length - 1].status, 'failed');
  assert.ok(historyKey('u1') in store.dump());
});

test('storage rusak atau tidak tersedia tidak membuat crash', () => {
  assert.deepEqual(loadHistory('u1', memStorage({ [historyKey('u1')]: '{oops' })), []);
  const throwing = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.deepEqual(loadHistory('u1', throwing), []);
  assert.doesNotThrow(() => saveHistory('u1', [], throwing));
});

test('deteksi balasan yang mengubah data', () => {
  assert.equal(looksLikeChange([{ type: 'message', text: '✅ Rp35rb — kopi\nMasuk ke Makan' }]), true);
  assert.equal(looksLikeChange([{ type: 'edit', text: '↩️ Dibatalkan: Rp35rb — kopi' }]), true);
  assert.equal(looksLikeChange([{ type: 'message', text: '💰 Sisa amplop kamu' }]), false);
  assert.equal(looksLikeChange([{ type: 'toast', text: '✅ Dipelajari!' }]), false);
});

test('logout menghapus riwayat chat semua akun, data lain tetap', () => {
  const s = {};
  const store = {
    get length() { return Object.keys(s).length; },
    key: i => Object.keys(s)[i] ?? null,
    getItem: k => s[k] ?? null,
    setItem: (k, v) => { s[k] = String(v); },
    removeItem: k => { delete s[k]; },
  };
  store.setItem(historyKey('a'), '[]');
  store.setItem(historyKey('b'), '[]');
  store.setItem('jatahku_theme', '{}');
  clearAllHistory(store);
  assert.deepEqual(Object.keys(s), ['jatahku_theme']);
});

test('pesan "Membaca struk..." yang dihapus bot hilang dari riwayat', () => {
  const ops = [
    { type: 'message', id: 'b1', text: '🧾 Membaca struk...', format: 'plain', buttons: [] },
    { type: 'delete', id: 'b1' },
    { type: 'message', id: 'b2', text: '👋 Budget kamu belum disiapkan.', format: 'plain', buttons: [] },
  ];
  let { messages } = applyOps([], ops);
  assert.deepEqual(messages.map(m => m.id), ['b2']);
  // kirim ulang (ops sama dari server) tidak menggandakan
  ({ messages } = applyOps(messages, ops));
  assert.deepEqual(messages.map(m => m.id), ['b2']);
});

test('pesan foto struk dari user', () => {
  const m = userPhotoMessage('data:image/jpeg;base64,xx', 5);
  assert.equal(m.kind, 'photo');
  assert.equal(m.role, 'user');
  assert.equal(m.status, 'sending');
  assert.equal(typeof m.text, 'string'); // tetap lolos filter riwayat lokal
});

test('gelembung bukti menyimpan id item dan status menunggu, lalu hasilnya menggantikannya', () => {
  const ITEM = '11111111-2222-4333-8444-555555555555';
  let { messages } = applyOps([], [
    { type: 'message', id: 'b1', text: '🧾 Membaca bukti...', format: 'plain', buttons: [] },
    { type: 'edit', id: 'b1', text: '⏳ Masih dibaca, nanti kukabari di sini.', format: 'plain', buttons: [], item: ITEM, pending: true },
  ], 10);
  assert.equal(messages[0].item, ITEM);
  assert.equal(messages[0].pending, true);
  assert.equal(messages[0].renderedAt, undefined); // belum ada tombol yang bisa basi
  // Hasil dari /bot/chat/bukti: item tetap, tidak lagi menunggu, waktu render dicatat (sesi tombol bot 10 menit).
  ({ messages } = applyOps(messages, [
    { type: 'edit', id: 'b1', text: 'QRIS · Siti\n\nMasuk ke amplop mana?', format: 'plain', buttons: btn, item: ITEM },
  ], 20));
  assert.equal(messages[0].item, ITEM);
  assert.equal(messages[0].pending, false);
  assert.equal(messages[0].renderedAt, 20);
  // Tombol ditekan: edit biasa (tanpa `item`) tetap mengingat itemnya dan memperbarui waktu render.
  ({ messages } = applyOps(messages, [
    { type: 'edit', id: 'b1', text: '✅ Tercatat', format: 'plain', buttons: [] },
  ], 30));
  assert.equal(messages[0].item, ITEM);
  assert.equal(messages[0].pending, false);
  assert.equal(messages[0].renderedAt, 30);
  // Pesan tanpa item tidak membawa field itu sama sekali.
  ({ messages } = applyOps(messages, [{ type: 'message', id: 'b2', text: 'hai', format: 'plain', buttons: [] }], 40));
  assert.equal('item' in messages[1], false);
  assert.equal('pending' in messages[1], false);
});

test('gelembung menunggu dan id item bertahan di riwayat lokal', () => {
  const store = memStorage();
  const ITEM = '11111111-2222-4333-8444-555555555555';
  const { messages } = applyOps([], [
    { type: 'message', id: 'b1', text: '⏳ Masih dibaca', format: 'plain', buttons: [], item: ITEM, pending: true },
  ]);
  saveHistory('u1', messages, store);
  const [back] = loadHistory('u1', store);
  assert.equal(back.item, ITEM);
  assert.equal(back.pending, true);
});
