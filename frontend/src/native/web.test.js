import test from 'node:test';
import assert from 'node:assert/strict';
import { createWebNative, TOKEN_KEY, REFRESH_KEY, PROD_API_URL, DEV_API_URL, CAMERA_MARK_KEY, CAMERA_MARK_MAX_MS } from './web.js';

function memStorage(init = {}) {
  const data = { ...init };
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    removeItem: (k) => { delete data[k]; },
  };
}

function eventTarget() {
  const handlers = {};
  return {
    handlers,
    addEventListener: (type, fn) => { (handlers[type] ||= []).push(fn); },
    removeEventListener: (type, fn) => { handlers[type] = (handlers[type] || []).filter(h => h !== fn); },
    emit: (type, e) => (handlers[type] || []).forEach(h => h(e)),
  };
}

function fakeDom() {
  const clicks = [];
  const body = { children: [], appendChild(el) { this.children.push(el); }, removeChild(el) { this.children = this.children.filter(c => c !== el); } };
  const doc = {
    ...eventTarget(),
    body,
    createElement: (tag) => (tag === 'input'
      ? {
        type: '', accept: '', attrs: {}, files: [], style: {}, l: {}, clicked: 0,
        setAttribute(k, v) { this.attrs[k] = v; },
        addEventListener(t, f) { this.l[t] = f; },
        click() { this.clicked++; },
      }
      : { click() { clicks.push({ href: this.href, download: this.download }); } }),
  };
  const revoked = [];
  const timers = [];
  const opened = [];
  const win = {
    ...eventTarget(),
    URL: { createObjectURL: () => 'blob:1', revokeObjectURL: (u) => revoked.push(u) },
    setTimeout: (fn) => timers.push(fn),
    open: (...args) => opened.push(args),
  };
  return { doc, win, clicks, revoked, timers, opened };
}

test('tokens: kunci localStorage sama dengan sebelum 1.5 (user tetap login)', () => {
  assert.equal(TOKEN_KEY, 'jatahku_token');
  assert.equal(REFRESH_KEY, 'jatahku_refresh');
  const storage = memStorage({ jatahku_token: 'a1', jatahku_refresh: 'r1' });
  const n = createWebNative({ storage, window: {}, document: {}, navigator: {} });
  assert.equal(n.tokens.getAccess(), 'a1');
  assert.equal(n.tokens.getRefresh(), 'r1');
  n.tokens.setAccess('a2');
  n.tokens.setRefresh('r2');
  assert.deepEqual(storage.data, { jatahku_token: 'a2', jatahku_refresh: 'r2' });
  n.tokens.setAccess(null);
  n.tokens.setRefresh(null);
  assert.deepEqual(storage.data, {});
  assert.equal(n.tokens.getAccess(), null);
});

test('tokens: storage yang diblokir tidak melempar', () => {
  const boom = () => { throw new Error('SecurityError'); };
  const n = createWebNative({ storage: { getItem: boom, setItem: boom, removeItem: boom } });
  assert.equal(n.tokens.getAccess(), null);
  assert.doesNotThrow(() => n.tokens.setAccess('x'));
  assert.doesNotThrow(() => n.tokens.setRefresh(null));
  // tetap login selama halaman terbuka
  assert.equal(n.tokens.getAccess(), 'x');
});

test('platform: alamat API dari build, bukan dari hostname', () => {
  assert.equal(createWebNative({ prod: true }).platform.apiUrl, PROD_API_URL);
  assert.equal(createWebNative({ prod: false }).platform.apiUrl, DEV_API_URL);
  const p = createWebNative({ prod: true }).platform;
  assert.equal(p.isNative, false);
  assert.equal(p.name, 'web');
});

test('queue.withAuth menyertakan token untuk service worker', () => {
  const n = createWebNative({ storage: memStorage({ jatahku_token: 'tok' }) });
  assert.deepEqual(n.queue.withAuth({ amount: 5 }), { amount: 5, token: 'tok' });
});

test('queue.store memakai store yang diberikan', () => {
  const store = { all: async () => [] };
  assert.equal(createWebNative({ queueStore: store }).queue.store(), store);
});

test('queue.requestBackgroundSync mendaftarkan sync bila didukung', async () => {
  const tags = [];
  const nav = { serviceWorker: { ready: Promise.resolve({ sync: { register: async (t) => tags.push(t) } }) } };
  await createWebNative({ navigator: nav, window: { SyncManager: function () {} } }).queue.requestBackgroundSync();
  assert.deepEqual(tags, ['sync-transactions']);
});

test('queue.requestBackgroundSync diam bila tidak didukung atau ditolak', async () => {
  await createWebNative({ navigator: {}, window: {} }).queue.requestBackgroundSync();
  const nav = { serviceWorker: { ready: Promise.resolve({ sync: { register: async () => { throw new Error('no'); } } }) } };
  await createWebNative({ navigator: nav, window: { SyncManager: function () {} } }).queue.requestBackgroundSync();
});

test('queue.onBackgroundSynced hanya meneruskan pesan sinkron dan bisa dilepas', () => {
  const sw = eventTarget();
  const got = [];
  const off = createWebNative({ navigator: { serviceWorker: sw } }).queue.onBackgroundSynced(s => got.push(s));
  sw.emit('message', { data: { type: 'lain' } });
  sw.emit('message', { data: { type: 'jatahku:offline-synced', summary: { saved: 2 } } });
  off();
  sw.emit('message', { data: { type: 'jatahku:offline-synced', summary: { saved: 9 } } });
  assert.deepEqual(got, [{ saved: 2 }]);
  // tanpa service worker: pelepas tetap fungsi
  assert.equal(typeof createWebNative({ navigator: {} }).queue.onBackgroundSynced(() => {}), 'function');
});

test('files.save mengunduh lewat <a download> lalu mencabut URL', async () => {
  const { doc, win, clicks, revoked, timers } = fakeDom();
  const n = createWebNative({ window: win, document: doc });
  await n.files.save({ type: 'text/csv' }, 'laporan.csv');
  assert.deepEqual(clicks, [{ href: 'blob:1', download: 'laporan.csv' }]);
  assert.equal(doc.body.children.length, 0);
  assert.deepEqual(revoked, []);
  timers.forEach(fn => fn());
  assert.deepEqual(revoked, ['blob:1']);
});

test('files.share memakai lembar bagikan bila bisa, selain itu menyimpan', async () => {
  const { doc, win, clicks } = fakeDom();
  win.File = class { constructor(parts, name) { this.name = name; } };
  const shared = [];
  const nav = { canShare: () => true, share: async (d) => shared.push(d.files[0].name) };
  assert.equal(await createWebNative({ window: win, document: doc, navigator: nav }).files.share({ type: 'application/pdf' }, 'a.pdf'), 'shared');
  assert.deepEqual(shared, ['a.pdf']);
  assert.equal(clicks.length, 0);

  const cancel = { canShare: () => true, share: async () => { const e = new Error(); e.name = 'AbortError'; throw e; } };
  assert.equal(await createWebNative({ window: win, document: doc, navigator: cancel }).files.share({}, 'a.pdf'), 'cancelled');

  assert.equal(await createWebNative({ window: win, document: doc, navigator: {} }).files.share({}, 'b.pdf'), 'saved');
  assert.deepEqual(clicks.map(c => c.download), ['b.pdf']);
});

test('print.pdf mencetak isi iframe; tanpa iframe tidak apa-apa', () => {
  const calls = [];
  const frame = { contentWindow: { focus: () => calls.push('focus'), print: () => calls.push('print') } };
  const n = createWebNative();
  n.print.pdf({ frame });
  assert.deepEqual(calls, ['focus', 'print']);
  assert.doesNotThrow(() => n.print.pdf({}));
});

test('openExternal: dari kode membuka tab baru; dari klik link dibiarkan ke browser', () => {
  const { win, opened } = fakeDom();
  const n = createWebNative({ window: win });
  n.openExternal('https://t.me/JatahkuBot');
  assert.deepEqual(opened, [['https://t.me/JatahkuBot', '_blank', 'noopener,noreferrer']]);
  let prevented = false;
  n.openExternal('https://t.me/x', { preventDefault: () => { prevented = true; } });
  assert.equal(opened.length, 1);
  assert.equal(prevented, false);
});

test('externalLinkProps: target _blank dan onClick pemanggil tetap jalan', () => {
  const { win, opened } = fakeDom();
  const seen = [];
  const p = createWebNative({ window: win }).externalLinkProps('https://t.me/a', () => seen.push('mine'));
  assert.equal(p.href, 'https://t.me/a');
  assert.equal(p.target, '_blank');
  assert.equal(p.rel, 'noopener noreferrer');
  p.onClick({ preventDefault() {} });
  assert.deepEqual(seen, ['mine']);
  assert.equal(opened.length, 0);
});

test('externalLinkProps: appUrl dicoba lewat anchor tersembunyi, kecuali klik dibatalkan', () => {
  const { doc, win, clicks } = fakeDom();
  const n = createWebNative({ window: win, document: doc });
  n.externalLinkProps('https://t.me/a', null, { appUrl: 'tg://resolve?domain=a' }).onClick({});
  assert.deepEqual(clicks.map(c => c.href), ['tg://resolve?domain=a']);
  assert.equal(doc.body.children.length, 0);
  n.externalLinkProps('https://t.me/a', (e) => { e.defaultPrevented = true; }, { appUrl: 'tg://x' }).onClick({});
  assert.equal(clicks.length, 1);
});

test('onInstallPrompt menahan prompt bawaan dan bisa dilepas', () => {
  const win = eventTarget();
  const got = [];
  const off = createWebNative({ window: win }).onInstallPrompt(e => got.push(e.id));
  let prevented = 0;
  win.emit('beforeinstallprompt', { id: 1, preventDefault: () => prevented++ });
  off();
  win.emit('beforeinstallprompt', { id: 2, preventDefault: () => prevented++ });
  assert.deepEqual(got, [1]);
  assert.equal(prevented, 1);
});

test('init mendaftarkan service worker setelah load bila didukung', async () => {
  const win = eventTarget();
  const doc = eventTarget();
  const registered = [];
  const sw = { ...eventTarget(), register: (url, opts) => { registered.push([url, opts]); return Promise.resolve({ update() {} }); } };
  await createWebNative({ window: win, document: doc, navigator: { serviceWorker: sw } }).init();
  assert.equal(registered.length, 0);
  win.emit('load');
  assert.deepEqual(registered, [['/sw.js', { scope: '/', updateViaCache: 'none' }]]);
  assert.equal(sw.handlers.controllerchange.length, 1);
  // tanpa service worker: tidak melempar
  await createWebNative({ window: eventTarget(), navigator: {} }).init();
});

test('camera.takePhoto: input foto dengan capture=environment, diklik sinkron, penanda ditulis', () => {
  const { doc, win } = fakeDom(); const storage = memStorage();
  const n = createWebNative({ storage, window: win, document: doc, navigator: {}, now: () => 1000 });
  n.camera.takePhoto();
  const input = doc.body.children.at(-1);
  assert.equal(input.type, 'file'); assert.equal(input.accept, 'image/*');
  assert.equal(input.attrs.capture, 'environment'); assert.equal(input.clicked, 1);
  assert.equal(storage.data[CAMERA_MARK_KEY], '1000');
});

test('camera.pickPhoto: tanpa capture', () => {
  const { doc, win } = fakeDom();
  const n = createWebNative({ storage: memStorage(), window: win, document: doc, navigator: {} });
  n.camera.pickPhoto();
  assert.equal(doc.body.children.at(-1).attrs.capture, undefined);
});

test('camera: change → File, input dilepas, penanda dihapus; cancel → null', async () => {
  const { doc, win } = fakeDom(); const storage = memStorage();
  const n = createWebNative({ storage, window: win, document: doc, navigator: {} });
  const p = n.camera.takePhoto(); const input = doc.body.children.at(-1);
  input.files = ['FOTO']; input.l.change();
  assert.equal(await p, 'FOTO');
  assert.equal(doc.body.children.includes(input), false);
  assert.equal(CAMERA_MARK_KEY in storage.data, false);
  const q = n.camera.pickPhoto(); doc.body.children.at(-1).l.cancel();
  assert.equal(await q, null);
});

test('camera: panggilan baru melepas input lama yang belum selesai dan menyelesaikannya dengan null', async () => {
  const { doc, win } = fakeDom();
  const n = createWebNative({ storage: memStorage(), window: win, document: doc, navigator: {} });
  const first = n.camera.takePhoto(); const oldInput = doc.body.children.at(-1);
  n.camera.takePhoto();
  assert.equal(await first, null);
  assert.equal(doc.body.children.includes(oldInput), false);
  assert.equal(doc.body.children.filter(c => c.type === 'file').length, 1);
});

test('files.pickDocument: input menerima gambar dan PDF, tanpa capture, tanpa penanda kamera', () => {
  const { doc, win } = fakeDom(); const storage = memStorage();
  const n = createWebNative({ storage, window: win, document: doc, navigator: {} });
  n.files.pickDocument();
  const input = doc.body.children.at(-1);
  assert.equal(input.accept, 'image/*,application/pdf');
  assert.equal(input.attrs.capture, undefined);
  assert.equal(CAMERA_MARK_KEY in storage.data, false);
});

test('files.pickDocument: diklik sinkron; change → File, cancel → null; penanda kamera yang ada tidak disentuh', async () => {
  const { doc, win } = fakeDom(); const storage = memStorage({ [CAMERA_MARK_KEY]: '5' });
  const n = createWebNative({ storage, window: win, document: doc, navigator: {}, now: () => 9000 });
  const p = n.files.pickDocument(); const input = doc.body.children.at(-1);
  assert.equal(input.type, 'file'); assert.equal(input.clicked, 1);
  assert.equal(storage.data[CAMERA_MARK_KEY], '5');
  input.files = ['BUKTI.pdf']; input.l.change();
  assert.equal(await p, 'BUKTI.pdf');
  assert.equal(doc.body.children.includes(input), false);
  assert.equal(storage.data[CAMERA_MARK_KEY], '5');
  const q = n.files.pickDocument(); doc.body.children.at(-1).l.cancel();
  assert.equal(await q, null);
  assert.equal(storage.data[CAMERA_MARK_KEY], '5');
});

test('camera.pickPhoto tetap image/* dan tetap menulis penanda (tidak berubah karena pickDocument)', () => {
  const { doc, win } = fakeDom(); const storage = memStorage();
  const n = createWebNative({ storage, window: win, document: doc, navigator: {}, now: () => 7 });
  n.camera.pickPhoto();
  const input = doc.body.children.at(-1);
  assert.equal(input.accept, 'image/*'); assert.equal(input.attrs.capture, undefined); assert.equal(input.clicked, 1);
  assert.equal(storage.data[CAMERA_MARK_KEY], '7');
});

test('files.pickDocument dan kamera berbagi satu input: yang belum selesai dijawab null', async () => {
  const { doc, win } = fakeDom(); const storage = memStorage();
  const n = createWebNative({ storage, window: win, document: doc, navigator: {}, now: () => 3 });
  const inputs = () => doc.body.children.filter(c => c.type === 'file').map(c => c.accept);
  const photo = n.camera.takePhoto();
  const pdf = n.files.pickDocument();
  assert.equal(await photo, null);
  // Kamera sudah dijawab → penandanya dihapus; dokumen tidak menulis penanda baru.
  assert.equal(CAMERA_MARK_KEY in storage.data, false);
  assert.deepEqual(inputs(), ['image/*,application/pdf']);
  n.camera.takePhoto();
  assert.equal(await pdf, null);
  assert.equal(storage.data[CAMERA_MARK_KEY], '3');
  assert.deepEqual(inputs(), ['image/*']);
});

test('camera.recover: lost bila penanda < 3 menit, lalu dihapus; file selalu null di web', async () => {
  const mk = (mark, t) => createWebNative({ storage: memStorage(mark == null ? {} : { [CAMERA_MARK_KEY]: String(mark) }), window: {}, document: {}, navigator: {}, now: () => t });
  assert.deepEqual(await mk(1000, 1000 + CAMERA_MARK_MAX_MS - 1).camera.recover(), { file: null, lost: true });
  assert.deepEqual(await mk(1000, 1000 + CAMERA_MARK_MAX_MS).camera.recover(), { file: null, lost: false });
  assert.deepEqual(await mk(null, 5000).camera.recover(), { file: null, lost: false });
  const storage = memStorage({ [CAMERA_MARK_KEY]: '1' });
  await createWebNative({ storage, window: {}, document: {}, navigator: {}, now: () => 2 }).camera.recover();
  assert.equal(CAMERA_MARK_KEY in storage.data, false);
});
