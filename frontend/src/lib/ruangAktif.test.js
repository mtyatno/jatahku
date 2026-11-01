import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  RUANG_HEADER, chatDiRuang, getRuangAktif, isRuangDitolak, pilihanRuang, ruangCacheSuffix, setRuangAktif,
  withRuangHeader,
} from './ruangAktif.js';
import { loadCache, saveCache } from './localCache.js';

function memStorage(init = {}) {
  const s = { ...init };
  return {
    getItem: k => (k in s ? s[k] : null),
    setItem: (k, v) => { s[k] = String(v); },
    removeItem: k => { delete s[k]; },
    key: i => Object.keys(s)[i] ?? null,
    get length() { return Object.keys(s).length; },
  };
}

const KELUARGA = '11111111-1111-4111-8111-111111111111';
const USAHA = '22222222-2222-4222-8222-222222222222';

test('tanpa pilihan: tanpa header, cache memakai kunci lama', () => {
  const st = memStorage();
  assert.equal(getRuangAktif(st), null);
  assert.deepEqual(withRuangHeader({ A: '1' }, st), { A: '1' });
  assert.equal(ruangCacheSuffix(st), '');
});

test('ruang usaha dipilih: header dikirim, ruang keluarga menghapus pilihan', () => {
  const st = memStorage();
  setRuangAktif(USAHA, { bawaan: KELUARGA, storage: st });
  assert.equal(getRuangAktif(st), USAHA);
  assert.deepEqual(withRuangHeader({}, st), { [RUANG_HEADER]: USAHA });
  setRuangAktif(KELUARGA, { bawaan: KELUARGA, storage: st });
  assert.equal(getRuangAktif(st), null);
  setRuangAktif(USAHA, { storage: st });
  setRuangAktif(null, { storage: st });
  assert.equal(getRuangAktif(st), null);
});

test('nilai tersimpan yang bukan UUID diabaikan dan tidak disimpan', () => {
  const st = memStorage({ jatahku_ruang_aktif: 'bukan-uuid' });
  assert.equal(getRuangAktif(st), null);
  assert.deepEqual(withRuangHeader({}, st), {});
  setRuangAktif('x\nX-Lain: 1', { storage: st });
  assert.equal(getRuangAktif(st), null);
});

test('storage melempar: tidak pernah galat', () => {
  const rusak = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); }, removeItem() { throw new Error('x'); } };
  assert.equal(getRuangAktif(rusak), null);
  assert.doesNotThrow(() => setRuangAktif(USAHA, { storage: rusak }));
});

test('cache offline terpisah per ruang', () => {
  const st = memStorage();
  saveCache('envelopes', ['keluarga'], st);
  setRuangAktif(USAHA, { storage: st });
  assert.equal(loadCache('envelopes', st), null);          // data ruang keluarga tidak tampil di ruang usaha
  saveCache('envelopes', ['usaha'], st);
  assert.deepEqual(loadCache('envelopes', st), ['usaha']);
  setRuangAktif(null, { storage: st });
  assert.deepEqual(loadCache('envelopes', st), ['keluarga']);
});

test('isRuangDitolak hanya untuk 403 ruang_tidak_diizinkan', () => {
  assert.equal(isRuangDitolak(403, { kode: 'ruang_tidak_diizinkan' }), true);
  assert.equal(isRuangDitolak(403, { kode: 'khusus_admin' }), false);
  assert.equal(isRuangDitolak(404, { kode: 'ruang_tidak_diizinkan' }), false);
  assert.equal(isRuangDitolak(403, null), false);
});

const DAFTAR = {
  bawaan: KELUARGA,
  items: [
    { id: KELUARGA, nama: 'Rumah Yatno', jenis: 'rumah_tangga', peran: 'owner', jumlah_anggota: 2 },
    { id: USAHA, nama: 'Dapur Nusa', jenis: 'usaha', peran: 'owner', jumlah_anggota: 1 },
  ],
  boleh_buat_usaha: true,
};

test('pilihanRuang: aktif dari pilihan, selain itu ruang keluarga', () => {
  assert.equal(pilihanRuang(DAFTAR, USAHA).aktif.id, USAHA);
  assert.equal(pilihanRuang(DAFTAR, null).aktif.id, KELUARGA);
  assert.equal(pilihanRuang(DAFTAR, '33333333-3333-4333-8333-333333333333').aktif.id, KELUARGA);
  assert.equal(pilihanRuang(DAFTAR, null).tampil, true);
});

test('pilihanRuang: user di luar flag tidak melihat pemilih', () => {
  const p = pilihanRuang({ bawaan: KELUARGA, items: [DAFTAR.items[0]], boleh_buat_usaha: false }, null);
  assert.equal(p.tampil, false);
  assert.equal(pilihanRuang(null, null).tampil, false);
  assert.equal(pilihanRuang(null, null).aktif, null);
  // Flag terbuka tapi belum punya ruang usaha: pemilih tampil untuk membuatnya.
  assert.equal(pilihanRuang({ ...DAFTAR, items: [DAFTAR.items[0]] }, null).tampil, true);
});

test('chatDiRuang: ADR-P16', () => {
  assert.deepEqual(chatDiRuang(DAFTAR.items[0]), { tampil: true, label: null });
  assert.deepEqual(chatDiRuang(DAFTAR.items[1]), { tampil: true, label: 'Ruang keluarga' });
  assert.deepEqual(chatDiRuang({ ...DAFTAR.items[1], peran: 'admin' }), { tampil: true, label: 'Ruang keluarga' });
  assert.deepEqual(chatDiRuang({ ...DAFTAR.items[1], peran: 'member' }), { tampil: false, label: null });
  assert.deepEqual(chatDiRuang(null), { tampil: true, label: null });
});
