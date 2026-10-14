import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatBotText, parseHtml, parseMarkdown, linkify, inAppPath, safeHref } from './chatFormat.js';

test('html: tebal, miring, kode, entitas', () => {
  assert.deepEqual(formatBotText('✅ <b>Rp35rb</b> — kopi &amp; roti\n<i>catatan</i> <code>35k</code>', 'html'), [
    { t: 'text', v: '✅ ' },
    { t: 'text', v: 'Rp35rb', b: true },
    { t: 'text', v: ' — kopi & roti\n' },
    { t: 'text', v: 'catatan', i: true },
    { t: 'text', v: ' ' },
    { t: 'code', v: '35k' },
  ]);
});

test('html: tidak pernah meloloskan tag/skrip sebagai HTML', () => {
  const nodes = parseHtml('<script>alert(1)</script><img src=x onerror=alert(1)>hai');
  assert.ok(nodes.every(n => n.t === 'text'));
  assert.equal(nodes.map(n => n.v).join(''), '<script>alert(1)</script><img src=x onerror=alert(1)>hai');
});

test('html: tautan hanya http(s)', () => {
  assert.deepEqual(parseHtml('<a href="https://jatahku.com/upgrade">Upgrade</a>'), [
    { t: 'link', v: 'Upgrade', href: 'https://jatahku.com/upgrade' },
  ]);
  assert.deepEqual(parseHtml('<a href="javascript:alert(1)">klik</a>'), [{ t: 'text', v: 'klik' }]);
});

test('html: tag yang tidak ditutup tidak merusak teks', () => {
  assert.equal(parseHtml('<b>tebal').map(n => n.v).join(''), 'tebal');
  assert.equal(parseHtml('a </b> b').map(n => n.v).join(''), 'a  b');
});

test('markdown lama Telegram: *tebal*, _miring_, `kode`, escape', () => {
  assert.deepEqual(formatBotText('📖 *Panduan Jatahku*\n- `kopi 35k`\n/amplop\\_baru \\[nama\\]', 'markdown'), [
    { t: 'text', v: '📖 ' },
    { t: 'text', v: 'Panduan Jatahku', b: true },
    { t: 'text', v: '\n- ' },
    { t: 'code', v: 'kopi 35k' },
    { t: 'text', v: '\n' },
    { t: 'cmd', v: '/amplop_baru' },
    { t: 'text', v: ' [nama]' },
  ]);
});

test('markdown: penanda tanpa pasangan tampil apa adanya', () => {
  assert.deepEqual(parseMarkdown('harga 5*3 = 15'), [{ t: 'text', v: 'harga 5*3 = 15' }]);
  assert.deepEqual(parseMarkdown('[teks](javascript:x)'), [{ t: 'text', v: '[teks](javascript:x)' }]);
  assert.deepEqual(parseMarkdown('[Buka](https://jatahku.com)'), [{ t: 'link', v: 'Buka', href: 'https://jatahku.com' }]);
});

test('perintah bot bisa diketuk, tapi bukan "/bulan" atau perintah Telegram', () => {
  const nodes = linkify('Ketik /status atau /help. Rp50rb/bulan, /link KODE, (/batal)');
  const cmds = nodes.filter(n => n.t === 'cmd').map(n => n.v);
  assert.deepEqual(cmds, ['/status', '/help', '/batal']);
  assert.equal(nodes.map(n => n.v).join(''), 'Ketik /status atau /help. Rp50rb/bulan, /link KODE, (/batal)');
});

test('tautan polos & domain jatahku jadi link, tanda baca akhir tidak ikut', () => {
  const nodes = linkify('Upgrade di jatahku.com/settings. Info: https://blog.jatahku.com/a, api.jatahku.com');
  const links = nodes.filter(n => n.t === 'link').map(n => [n.v, n.href]);
  assert.deepEqual(links, [
    ['jatahku.com/settings', 'https://jatahku.com/settings'],
    ['https://blog.jatahku.com/a', 'https://blog.jatahku.com/a'],
  ]);
  assert.equal(nodes.map(n => n.v).join(''), 'Upgrade di jatahku.com/settings. Info: https://blog.jatahku.com/a, api.jatahku.com');
});

test('teks di dalam kode tidak di-linkify', () => {
  const nodes = formatBotText('<code>/status</code>', 'html');
  assert.deepEqual(nodes, [{ t: 'code', v: '/status' }]);
});

test('tautan ke halaman webapp dibuka di dalam aplikasi', () => {
  assert.equal(inAppPath('https://jatahku.com/settings'), '/settings');
  assert.equal(inAppPath('https://www.jatahku.com/upgrade/'), '/upgrade');
  assert.equal(inAppPath('https://jatahku.com'), null); // landing
  assert.equal(inAppPath('https://contoh.com/settings'), null);
  assert.equal(inAppPath('bukan url'), null);
});

test('safeHref', () => {
  assert.equal(safeHref('jatahku.com/upgrade'), 'https://jatahku.com/upgrade');
  assert.equal(safeHref('data:text/html,x'), null);
});
