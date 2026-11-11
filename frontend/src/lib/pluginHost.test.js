// Plugin H3: host Fitur Tambahan di web (pembantu murni). Jalankan: node --test src/lib/pluginHost.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  bodyIzinBaru, bodyTambahan, bolehTambahKartu, fieldUntuk, isianBolehUntuk, izinBaru, kontribusiDariKatalog,
  KONTRIBUSI_KOSONG, adaKartuPlugin, adaMenuPlugin, aksiApi, aksiCatatPlugin, aksiDariKunci, bodyPasang,
  bodyTambahKartu, butuhBelumAktif, formatEkspor, formatNilai, halamanUtama, idDariRute, kontribusiUntuk, menuPlugin,
  namaBerkasUnduhan, namaPlugin, pesanGalat, rapikanKontribusi, selTabel, tawaranKartu, tombolUntuk, urutkanKatalog,
} from './pluginHost.js';
import { safeRoute } from './advisorAction.js';

const SERVER = {
  plugins: [{ id: 'buku_usaha', nama: 'Buku Usaha', ikon: 'book' }],
  nav: [
    { plugin: 'buku_usaha', grup: 'usaha', label: 'Buku Usaha', route: '/p/buku_usaha', ikon: 'book' },
    { plugin: 'buku_usaha', grup: 'lainnya', label: 'Laporan', route: '/p/buku_usaha/laporan', ikon: 'book' },
  ],
  quick_actions: [
    { plugin: 'buku_usaha', key: 'buku_usaha.penjualan', label: 'Penjualan', ikon: 'book' },
    { plugin: 'buku_usaha', key: 'buku_usaha.prive', label: 'Prive', ikon: 'book' },
  ],
  pages: [
    { plugin: 'buku_usaha', route: '/p/buku_usaha/laporan', judul: 'Laporan' },
    { plugin: 'buku_usaha', route: '/p/buku_usaha', judul: 'Buku Usaha' },
  ],
  cards: [{ key: 'buku_usaha.omzet', plugin: 'buku_usaha', judul: 'Omzet', shape: 'kpi', sizes: ['S', 'M'],
    size_bawaan: 'S', bawaan: true }],
  form_fields: [{ plugin: 'buku_usaha', target: 'transaction', key: 'kontak_id', type: 'reference', label: 'Pemasok' }],
};

test('kontribusi server dirapikan apa adanya bila sah', () => {
  const k = rapikanKontribusi(SERVER);
  assert.deepEqual(k.plugins, SERVER.plugins);
  assert.equal(k.nav.length, 2);
  assert.equal(k.quick_actions.length, 2);
  assert.equal(k.cards[0].key, 'buku_usaha.omzet');
  assert.equal(k.form_fields.length, 1);
});

test('rapikan membuang entri rusak, rute ke luar halaman plugin, dan plugin yang tidak tercantum', () => {
  const k = rapikanKontribusi({
    ...SERVER,
    nav: [
      ...SERVER.nav,
      { plugin: 'buku_usaha', grup: 'usaha', label: 'Jahat', route: '/settings' },
      { plugin: 'buku_usaha', grup: 'usaha', label: 'Lain', route: '/p/plugin_lain' },
      { plugin: 'buku_usaha', grup: 'usaha', label: 'Luar', route: 'https://contoh.invalid/p/buku_usaha' },
      { plugin: 'buku_usaha', grup: 'atas', label: 'Grup asing', route: '/p/buku_usaha' },
      { plugin: 'siluman', grup: 'usaha', label: 'Siluman', route: '/p/siluman' },
    ],
    quick_actions: [...SERVER.quick_actions, { plugin: 'buku_usaha', key: 'buku_usaha.ketiga', label: 'Ketiga' },
      { plugin: 'buku_usaha', key: 'lain.aksi', label: 'Bukan miliknya' }],
    cards: [...SERVER.cards, { key: 'core.kpi.jatah', plugin: 'buku_usaha' }],
  });
  assert.deepEqual(k.nav.map(n => n.route), ['/p/buku_usaha', '/p/buku_usaha/laporan']);
  assert.deepEqual(k.quick_actions.map(a => a.key), ['buku_usaha.penjualan', 'buku_usaha.prive']);   // maks. 2
  assert.deepEqual(k.cards.map(c => c.key), ['buku_usaha.omzet']);
  assert.equal(rapikanKontribusi(null), KONTRIBUSI_KOSONG);
  assert.deepEqual(rapikanKontribusi({ nav: 'x' }).nav, []);
});

test('karyawan tidak pernah mendapat kontribusi plugin (keputusan H3 B)', () => {
  const k = rapikanKontribusi(SERVER);
  assert.equal(kontribusiUntuk(k, { karyawan: true }), KONTRIBUSI_KOSONG);
  assert.equal(kontribusiUntuk(k, { karyawan: false, pengelola: true }), k);
  assert.equal(kontribusiUntuk(undefined, {}), KONTRIBUSI_KOSONG);
});

test('menu per grup, aksi Catat per plugin, halaman utama', () => {
  const k = rapikanKontribusi(SERVER);
  const m = menuPlugin(k);
  assert.deepEqual(m.usaha, [{ to: '/p/buku_usaha', label: 'Buku Usaha', icon: 'book', plugin: 'buku_usaha', end: true }]);
  assert.equal(m.lainnya[0].end, false);
  assert.deepEqual(m.lainnya.map(i => i.to), ['/p/buku_usaha/laporan']);
  assert.ok(adaMenuPlugin(k));
  assert.ok(!adaMenuPlugin(KONTRIBUSI_KOSONG));
  const g = aksiCatatPlugin(k);
  assert.equal(g.length, 1);
  assert.equal(g[0].nama, 'Buku Usaha');
  assert.deepEqual(g[0].aksi.map(a => a.key), ['plugin:buku_usaha.penjualan', 'plugin:buku_usaha.prive']);
  assert.equal(aksiDariKunci('plugin:buku_usaha.penjualan'), 'buku_usaha.penjualan');
  assert.equal(aksiDariKunci('expense'), null);
  assert.equal(halamanUtama(k, 'buku_usaha'), '/p/buku_usaha');
  assert.equal(halamanUtama(k, 'lain'), null);
  assert.equal(namaPlugin(k, 'buku_usaha'), 'Buku Usaha');
});

test('rute plugin dikenali dan aman', () => {
  assert.equal(idDariRute('/p/buku_usaha'), 'buku_usaha');
  assert.equal(idDariRute('/p/buku_usaha/laba-rugi?bulan=10'), 'buku_usaha');
  assert.equal(idDariRute('/p/Buku'), null);
  assert.equal(idDariRute('/p/'), null);
  assert.equal(idDariRute('/envelopes'), null);
  // Aksi `route` dari kartu dan AI Advisor plugin: hanya halaman plugin yang sah.
  assert.equal(safeRoute('/p/buku_usaha/laba-rugi?bulan=10'), '/p/buku_usaha/laba-rugi?bulan=10');
  // Dinormalkan dulu, lalu dinilai: hasilnya tetap halaman plugin atau halaman inti yang diizinkan.
  assert.equal(safeRoute('/p/buku_usaha/../../settings'), '/settings');
  assert.equal(safeRoute('/p/buku_usaha/../../admin'), null);
  assert.equal(safeRoute('//evil.invalid/p/buku_usaha'), null);
  assert.equal(safeRoute('/p/BUKU'), null);
});

test('tombol katalog per status, peran, dan saklar darurat', () => {
  const p = (status, x = {}) => ({ status, boleh_kelola: true, diperbaiki: false, ...x });
  assert.deepEqual(tombolUntuk(p('tersedia')), ['pasang']);
  assert.deepEqual(tombolUntuk(p('terpasang')), ['lanjut', 'jeda', 'copot']);
  assert.deepEqual(tombolUntuk(p('aktif')), ['jeda', 'copot']);
  assert.deepEqual(tombolUntuk(p('dijeda')), ['lanjut', 'copot']);
  assert.deepEqual(tombolUntuk(p('arsip')), ['pulihkan']);
  assert.deepEqual(tombolUntuk(p('aktif', { boleh_kelola: false })), []);           // anggota biasa: lihat saja
  assert.deepEqual(tombolUntuk(p('dijeda', { diperbaiki: true })), ['copot']);       // saklar: hanya arah aman
  assert.deepEqual(tombolUntuk(p('tersedia', { diperbaiki: true })), []);
  assert.equal(aksiApi('pulihkan'), 'pasang');
  assert.equal(aksiApi('jeda'), 'jeda');
});

test('urutan katalog: yang dipakai dulu, lalu tersedia, lalu dicopot', () => {
  const daftar = [{ nama: 'Zeta', status: 'tersedia' }, { nama: 'Arsip', status: 'arsip' },
    { nama: 'Beta', status: 'dijeda' }, { nama: 'Alfa', status: 'aktif' }, { nama: 'Ana', status: 'tersedia' }];
  assert.deepEqual(urutkanKatalog(daftar).map(p => p.nama), ['Alfa', 'Beta', 'Ana', 'Zeta', 'Arsip']);
});

test('persetujuan izin mengirim daftar yang ditampilkan', () => {
  const p = { izin: [{ kode: 'incomes:read', teks: 'Melihat pemasukan' }, { kode: 'incomes:write', teks: 'Mencatat' }] };
  assert.deepEqual(bodyPasang(p), { izin: ['incomes:read', 'incomes:write'] });
  assert.deepEqual(bodyPasang({}), { izin: [] });
  assert.match(pesanGalat(409, { kode: 'izin_berubah', detail: 'Izin Uji berubah. Muat ulang.' }), /Muat ulang/);
  assert.equal(pesanGalat(0, null), 'Koneksi terputus. Coba lagi.');
  assert.equal(pesanGalat(500, {}), 'Belum berhasil. Coba lagi sebentar.');
});

test('butuh plugin lain yang belum aktif', () => {
  const katalog = [{ id: 'buku_usaha', nama: 'Buku Usaha', status: 'dijeda' }, { id: 'pajak', nama: 'Pajak', status: 'aktif' }];
  assert.deepEqual(butuhBelumAktif({ butuh: ['buku_usaha', 'pajak', 'hilang'] }, katalog), ['Buku Usaha', 'hilang']);
});

test('tawaran kartu: kartu bawaan dicentang', () => {
  assert.deepEqual(tawaranKartu({ kartu: [{ key: 'a.x', judul: 'X', bawaan: true }, { key: 'a.y', judul: 'Y' }] }),
    [{ key: 'a.x', judul: 'X', terpilih: true }, { key: 'a.y', judul: 'Y', terpilih: false }]);
});

test('menambah kartu ke Beranda mengirim balik semua instans dan tidak menggandakan', () => {
  const layout = {
    surface: 'beranda', version: 3,
    items: [
      { id: 'a1', card: 'core.kpi.jatah', size: 'S', hidden: false, devices: 'all', settings: {}, visible: true },
      { id: 'p1', card: 'core.transaksi_terbaru', size: 'M', hidden: true, devices: 'wide', settings: { limit: 5 } },
      { id: 'k1', card: 'core.karyawan.catat', size: 'M', hidden: false, devices: 'all', visible: false, alasan: 'khusus_karyawan' },
    ],
    parked: [{ id: 'z9', card: 'bu.parkir', size: 'S' }],
  };
  const defs = [{ key: 'bu.omzet', size_bawaan: 'M' }, { key: 'bu.parkir', size_bawaan: 'S' }, { key: 'core.kpi.jatah', size_bawaan: 'S' }];
  const body = bodyTambahKartu(layout, ['bu.omzet', 'bu.parkir', 'core.kpi.jatah', 'bu.omzet', 'bu.tanpa_def'], defs);
  assert.equal(body.if_version, 3);
  assert.deepEqual(body.removed, []);
  assert.deepEqual(body.items.map(i => i.id), ['a1', 'p1', 'k1', 'p2']);
  assert.deepEqual(body.items[3], { id: 'p2', card: 'bu.omzet', size: 'M', hidden: false, devices: 'all' });
  assert.deepEqual(body.items[1], { id: 'p1', card: 'core.transaksi_terbaru', size: 'M', hidden: true, devices: 'wide', settings: { limit: 5 } });
  assert.ok(!('visible' in body.items[2]));
  assert.equal(bodyTambahKartu(layout, ['core.kpi.jatah'], defs), null);
  assert.equal(bodyTambahKartu(null, ['bu.omzet'], defs), null);
  // Dokumen belum tersimpan (version 0): template dikirim sebagai dokumen pertama.
  assert.equal(bodyTambahKartu({ ...layout, version: 0 }, ['bu.omzet'], defs).if_version, 0);
});

test('format nilai kartu: rupiah, persen, hari, angka; sel tabel', () => {
  assert.equal(formatNilai('48650000', 'rp').replace(/\s/g, ' '), 'Rp 48.650.000');
  assert.equal(formatNilai('25.4', 'persen'), '25,4%');
  assert.equal(formatNilai(11, 'hari'), '11 hari');
  assert.equal(formatNilai('1234.5'), '1.234,5');
  assert.equal(formatNilai(null, 'rp'), '—');
  assert.equal(formatNilai('bukan', 'rp'), '—');
  assert.equal(selTabel('2026', 0), '2026');               // kolom label tidak pernah diformat
  assert.equal(selTabel('21400000', 1), '21.400.000');
  assert.equal(selTabel(9000000, 2), '9.000.000');
  assert.equal(selTabel('Okt 2026', 1), 'Okt 2026');
  assert.equal(selTabel(null, 1), '');
});

test('Beranda registry dipaksa bila tata letak memuat kartu plugin aktif', () => {
  const k = rapikanKontribusi(SERVER);
  assert.ok(adaKartuPlugin({ items: [{ card: 'buku_usaha.omzet' }] }, k));
  assert.ok(!adaKartuPlugin({ items: [{ card: 'buku_usaha.omzet', hidden: true }] }, k));
  assert.ok(!adaKartuPlugin({ items: [{ card: 'buku_usaha.omzet', visible: false }] }, k));
  assert.ok(!adaKartuPlugin({ items: [{ card: 'core.kpi.jatah' }] }, k));
  assert.ok(!adaKartuPlugin({ items: [{ card: 'buku_usaha.omzet' }] }, KONTRIBUSI_KOSONG));
});

test('U1: format ekspor dan nama berkas unduhan', () => {
  assert.deepEqual(formatEkspor({ status: 'aktif', ekspor: ['csv', 'json', 'xml'] }), ['csv', 'json']);
  assert.deepEqual(formatEkspor({ status: 'arsip', ekspor: ['json'] }), ['json']);
  assert.deepEqual(formatEkspor({ status: 'tersedia', ekspor: ['json'] }), []);
  assert.deepEqual(formatEkspor({ status: 'aktif' }), []);
  assert.deepEqual(formatEkspor(null), []);
  assert.equal(namaBerkasUnduhan('attachment; filename="jatahku-buku_usaha-20261105-0600.zip"', 'x.zip'),
    'jatahku-buku_usaha-20261105-0600.zip');
  assert.equal(namaBerkasUnduhan('attachment; filename="../etc/passwd"', 'x.zip'), 'x.zip');
  assert.equal(namaBerkasUnduhan(null, 'x.json'), 'x.json');
});

test('izin baru hanya untuk instalasi yang ada dan pengelola (U2)', () => {
  const p = { boleh_kelola: true, status: 'aktif', izin_baru: ['incomes:write'],
    izin: [{ kode: 'envelopes:read', teks: 'Membaca amplop' }, { kode: 'incomes:write', teks: 'Mencatat pemasukan' }] };
  assert.deepEqual(izinBaru(p), [{ kode: 'incomes:write', teks: 'Mencatat pemasukan' }]);
  assert.deepEqual(bodyIzinBaru(p), { izin: ['envelopes:read', 'incomes:write'] });   // semua yang dilihat
  assert.deepEqual(izinBaru({ ...p, boleh_kelola: false }), []);
  assert.deepEqual(izinBaru({ ...p, status: 'arsip' }), []);
  assert.deepEqual(izinBaru({ ...p, izin_baru: undefined }), []);
});

test('field form plugin per target dan body tambahan (U2)', () => {
  const k = { form_fields: [
    { plugin: 'bu', target: 'transaction', key: 'pemasok', type: 'reference', label: 'Pemasok' },
    { plugin: 'bu', target: 'transaction', key: 'akun', type: 'select', label: 'Akun', options: ['Sewa', 'Gaji'] },
    { plugin: 'bu', target: 'transaction', key: 'rusak', type: 'select', label: 'R' },
    { plugin: 'bu', target: 'income', key: 'x', type: 'text', label: 'X' },
    { plugin: 'bu', target: 'transaction', key: 'aneh', type: 'html', label: 'A' },
  ] };
  const f = fieldUntuk(k, 'transaction');
  assert.deepEqual(f.map(x => x.key), ['pemasok', 'akun']);
  assert.equal(bodyTambahan(f, {}), null);
  assert.equal(bodyTambahan(f, { 'bu.akun': '', 'bu.pemasok': null }), null);
  assert.deepEqual(bodyTambahan(f, { 'bu.akun': 'Sewa', 'bu.pemasok': 'id-1' }), { bu: { pemasok: 'id-1', akun: 'Sewa' } });
  assert.deepEqual(bodyTambahan(f, { 'bu.akun': 'Hiburan', 'bu.pemasok': 'id-1' }), { bu: { pemasok: 'id-1' } });
  assert.deepEqual(fieldUntuk(null, 'transaction'), []);
});

test('isian plugin tidak untuk pengeluaran pribadi (review #201 T3)', () => {
  assert.equal(isianBolehUntuk({ id: 'a', owner_id: null }, false), true);
  assert.equal(isianBolehUntuk(undefined, false), true);
  assert.equal(isianBolehUntuk({ id: 'a', owner_id: 'u1' }, false), false);
  assert.equal(isianBolehUntuk({ id: 'a', is_personal: true }, false), false);      // bentuk /envelopes/summary
  assert.equal(isianBolehUntuk({ id: 'a', is_personal: false }, false), true);
  assert.equal(isianBolehUntuk({ id: 'a', owner_id: null }, true), false);
});

// ── U4: kartu untuk instalasi yang sudah ada, dan kartu karyawan ──
test('U4: kartu bisa ditambahkan lagi dari panel hanya saat plugin aktif dan user pengelola', () => {
  const kartu = [{ key: 'a.x', judul: 'X', bawaan: true }];
  assert.equal(bolehTambahKartu({ status: 'aktif', boleh_kelola: true, kartu }), true);
  assert.equal(bolehTambahKartu({ status: 'aktif', boleh_kelola: false, kartu }), false);
  assert.equal(bolehTambahKartu({ status: 'aktif', boleh_kelola: true, kartu: [] }), false);
  assert.equal(bolehTambahKartu({ status: 'aktif', boleh_kelola: true, kartu, diperbaiki: true }), false);
  for (const status of ['tersedia', 'terpasang', 'dijeda', 'arsip']) {
    assert.equal(bolehTambahKartu({ status, boleh_kelola: true, kartu }), false, status);
  }
  assert.equal(bolehTambahKartu(null), false);
});

test('U4: katalog Beranda karyawan menjadi kontribusi kartu saja', () => {
  const katalog = [
    { key: 'core.karyawan.catat', judul: 'Catat', asal: 'inti', shape: 'inti', sizes: ['M'], size_bawaan: 'M' },
    { key: 'buku_usaha.penjualan_saya', judul: 'Penjualan saya bulan ini', asal: 'buku_usaha', sumber: 'Buku Usaha',
      shape: 'kpi', sizes: ['M', 'L'], size_bawaan: 'M' },
    { key: 'lain.kartu', judul: 'Tanpa nama sumber', asal: 'lain', shape: 'list', sizes: ['M'], size_bawaan: 'M' },
    { key: 'palsu.kartu', judul: 'Kunci tidak cocok asal', asal: 'buku_usaha', shape: 'kpi', sizes: ['S'], size_bawaan: 'S' },
    { key: 'x.y', judul: 'Asal tidak sah', asal: '../x', shape: 'kpi', sizes: ['S'], size_bawaan: 'S' },
  ];
  const k = kontribusiDariKatalog(katalog);
  assert.deepEqual(k.cards.map(c => [c.key, c.plugin, c.judul, c.shape]), [
    ['buku_usaha.penjualan_saya', 'buku_usaha', 'Penjualan saya bulan ini', 'kpi'],
    ['lain.kartu', 'lain', 'Tanpa nama sumber', 'list'],
  ]);
  assert.equal(namaPlugin(k, 'buku_usaha'), 'Buku Usaha');
  assert.equal(namaPlugin(k, 'lain'), 'lain');
  // Hanya kartu: karyawan tidak pernah mendapat menu, aksi, halaman, atau field dari katalog kartu.
  assert.deepEqual([k.nav, k.quick_actions, k.pages, k.form_fields], [[], [], [], []]);
  assert.deepEqual(kontribusiDariKatalog(null), KONTRIBUSI_KOSONG);
  assert.deepEqual(kontribusiDariKatalog([{ key: 'core.kpi.jatah', asal: 'inti' }]).cards, []);
});
