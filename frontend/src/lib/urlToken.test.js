import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bacaToken, urlTanpaParam, hapusTokenDariUrl } from './urlToken.js';

// Jendela palsu: hanya location dan history yang dipakai.
function jendela(pathname, search = '', hash = '', state = { key: 'rr-1' }) {
  const panggilan = [];
  return {
    location: { pathname, search, hash },
    history: { state, replaceState: (...args) => panggilan.push(args) },
    panggilan,
  };
}

test('bacaToken mengambil nilai ?token=', () => {
  assert.equal(bacaToken('?token=abc.def'), 'abc.def');
  assert.equal(bacaToken('?a=1&token=x%2By&b=2'), 'x+y');
  assert.equal(bacaToken('?a=1'), null);
  assert.equal(bacaToken(''), null);
  assert.equal(bacaToken(undefined), null);
});

test('urlTanpaParam membuang hanya token; query lain dan hash tetap', () => {
  assert.equal(urlTanpaParam({ pathname: '/reset-password', search: '?token=abc', hash: '' }), '/reset-password');
  assert.equal(
    urlTanpaParam({ pathname: '/hapus-akun', search: '?a=1&token=abc&b=2', hash: '#bawah' }),
    '/hapus-akun?a=1&b=2#bawah',
  );
});

test('urlTanpaParam null bila tidak ada token (tidak ada yang perlu diubah)', () => {
  assert.equal(urlTanpaParam({ pathname: '/hapus-akun', search: '', hash: '' }), null);
  assert.equal(urlTanpaParam({ pathname: '/hapus-akun', search: '?a=1', hash: '#x' }), null);
});

test('hapusTokenDariUrl mengganti entri riwayat tanpa token dan mempertahankan state riwayat', () => {
  const w = jendela('/reset-password', '?token=rahasia&dari=email', '#atas');
  assert.equal(hapusTokenDariUrl(w), true);
  assert.equal(w.panggilan.length, 1);
  const [state, judul, url] = w.panggilan[0];
  assert.deepEqual(state, { key: 'rr-1' });   // state react-router tetap
  assert.equal(judul, '');
  assert.equal(url, '/reset-password?dari=email#atas');
  assert.ok(!url.includes('rahasia'));
});

test('hapusTokenDariUrl tidak menyentuh riwayat bila tidak ada token', () => {
  const w = jendela('/auth/tg', '?x=1');
  assert.equal(hapusTokenDariUrl(w), false);
  assert.equal(w.panggilan.length, 0);
});

test('hapusTokenDariUrl tidak melempar bila riwayat tidak bisa diubah', () => {
  const w = jendela('/auth/tg', '?token=abc');
  w.history.replaceState = () => { throw new Error('SecurityError'); };
  assert.equal(hapusTokenDariUrl(w), false);
  assert.equal(hapusTokenDariUrl({}), false);
});
