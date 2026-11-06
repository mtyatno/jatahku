// Host Fitur Tambahan di web (Plugin H3; docs/plugin/04-kontrak-api.md §5, 05-desain-buku-usaha.md A2 butir 2–4, 7, 8).
//
// Server yang memutuskan plugin mana yang aktif untuk ruang dan user ini (`GET /plugins/contributions`, status, saklar
// darurat, flag, peran) dan menegakkan izin di setiap panggilan plugin. Di sini hanya tampilan: menu, aksi cepat, rute
// `/p/<id>`, kartu, dan tombol katalog. Pembantu murni supaya bisa diuji tanpa browser (node --test).
//
// Istilah di UI selalu "Fitur Tambahan" (ADR-P10); "plugin" hanya di kode.

import { formatCurrency } from './utils.js';

export const KONTRIBUSI_KOSONG = Object.freeze({
  plugins: [], nav: [], quick_actions: [], pages: [], cards: [], form_fields: [],
});

const ID_RE = /^[a-z][a-z0-9_]{1,29}$/;
// Rute halaman plugin, sama dengan pola manifest dan `titik.rute_plugin` di server.
export const RUTE_PLUGIN_RE = /^\/p\/([a-z][a-z0-9_]{1,29})((?:\/[a-z0-9_-]+)*)\/?$/;
export const RUTE_FITUR = '/fitur-tambahan';
const MAKS_AKSI_PER_PLUGIN = 2;   // manifest juga membatasi (A2 butir 4)

const arr = (v) => (Array.isArray(v) ? v : []);
const teks = (v, maks = 60) => (typeof v === 'string' ? v.slice(0, maks) : '');

/** Id plugin dari path `/p/<id>/…`, atau null. */
export function idDariRute(path) {
  const m = RUTE_PLUGIN_RE.exec(String(path || '').split(/[?#]/)[0]);
  return m ? m[1] : null;
}

/** Rute milik plugin itu sendiri? (kontribusi menunjuk halaman plugin lain = dibuang) */
export function rutePunya(route, pluginId) {
  return idDariRute(route) === pluginId;
}

/**
 * Jawaban `GET /plugins/contributions` → bentuk yang aman dipakai UI. Entri yang rusak dibuang, rute harus di bawah
 * `/p/<plugin itu>`, dan hanya entri milik plugin yang tercantum di `plugins` yang dipakai. Server sudah memeriksa
 * semua ini; pemeriksaan di sini hanya supaya UI tidak pernah menautkan ke luar halaman plugin.
 */
export function rapikanKontribusi(data) {
  if (!data || typeof data !== 'object') return KONTRIBUSI_KOSONG;
  const plugins = arr(data.plugins)
    .filter(p => p && ID_RE.test(p.id))
    .map(p => ({ id: p.id, nama: teks(p.nama, 40) || p.id, ikon: teks(p.ikon, 30) || 'puzzle' }));
  const ada = new Set(plugins.map(p => p.id));
  const milik = (x) => x && ada.has(x.plugin);
  const aksiPer = {};
  return {
    plugins,
    nav: arr(data.nav).filter(n => milik(n) && rutePunya(n.route, n.plugin) && (n.grup === 'usaha' || n.grup === 'lainnya'))
      .map(n => ({ plugin: n.plugin, grup: n.grup, label: teks(n.label, 40), route: n.route, ikon: teks(n.ikon, 30) || 'puzzle' })),
    quick_actions: arr(data.quick_actions).filter(a => milik(a) && typeof a.key === 'string' && a.key.startsWith(`${a.plugin}.`))
      .filter(a => { aksiPer[a.plugin] = (aksiPer[a.plugin] || 0) + 1; return aksiPer[a.plugin] <= MAKS_AKSI_PER_PLUGIN; })
      .map(a => ({ plugin: a.plugin, key: a.key, label: teks(a.label, 30), ikon: teks(a.ikon, 30) || 'puzzle' })),
    pages: arr(data.pages).filter(p => milik(p) && rutePunya(p.route, p.plugin))
      .map(p => ({ plugin: p.plugin, route: p.route, judul: teks(p.judul, 40) })),
    cards: arr(data.cards).filter(c => milik(c) && typeof c.key === 'string' && c.key.startsWith(`${c.plugin}.`))
      .map(c => ({
        key: c.key, plugin: c.plugin, judul: teks(c.judul, 40), shape: c.shape,
        sizes: arr(c.sizes).filter(s => ['S', 'M', 'L', 'XL'].includes(s)),
        size_bawaan: c.size_bawaan, bawaan: !!c.bawaan,
      })),
    form_fields: arr(data.form_fields).filter(milik),
  };
}

/** Kontribusi untuk peran ini: karyawan tidak pernah mendapat apa pun (keputusan H3 B; server juga menolak, 403). */
export function kontribusiUntuk(kontribusi, akses) {
  return akses?.karyawan ? KONTRIBUSI_KOSONG : (kontribusi || KONTRIBUSI_KOSONG);
}

export const pluginAktif = (kontribusi, id) => arr(kontribusi?.plugins).find(p => p.id === id) || null;
export const namaPlugin = (kontribusi, id) => pluginAktif(kontribusi, id)?.nama || id;

/** Menu plugin per grup (A2 butir 2): grup "Usaha" dan "Lainnya" di sidebar; di HP keduanya di lembar Lainnya. */
export function menuPlugin(kontribusi) {
  const nav = arr(kontribusi?.nav);
  // `end`: halaman utama tidak ikut menyala saat subhalaman yang juga ada di menu sedang dibuka.
  const ke = (n) => ({ to: n.route, label: n.label, icon: n.ikon, plugin: n.plugin,
    end: nav.some(o => o.route.startsWith(`${n.route}/`)) });
  return {
    usaha: nav.filter(n => n.grup === 'usaha').map(ke),
    lainnya: nav.filter(n => n.grup === 'lainnya').map(ke),
  };
}

export const adaMenuPlugin = (kontribusi) => arr(kontribusi?.nav).length > 0;

// Aksi cepat plugin di menu Catat ▾ dan FAB: kunci UI berawalan `plugin:` supaya tidak bertabrakan dengan aksi inti.
const AWALAN_AKSI = 'plugin:';
export const kunciAksi = (key) => `${AWALAN_AKSI}${key}`;
export const aksiDariKunci = (k) => (typeof k === 'string' && k.startsWith(AWALAN_AKSI) ? k.slice(AWALAN_AKSI.length) : null);

/** Grup aksi Catat per plugin (A2 butir 4): [{plugin, nama, aksi: [{key, icon, label}]}]. */
export function aksiCatatPlugin(kontribusi) {
  const grup = [];
  for (const a of arr(kontribusi?.quick_actions)) {
    let g = grup.find(x => x.plugin === a.plugin);
    if (!g) {
      g = { plugin: a.plugin, nama: namaPlugin(kontribusi, a.plugin), aksi: [] };
      grup.push(g);
    }
    g.aksi.push({ key: kunciAksi(a.key), icon: a.ikon, label: a.label, aksi: a.key, plugin: a.plugin });
  }
  return grup;
}

/** Halaman utama plugin (rute terpendek): tujuan aksi cepat yang belum punya form sendiri. */
export function halamanUtama(kontribusi, pluginId) {
  const rute = arr(kontribusi?.pages).filter(p => p.plugin === pluginId).map(p => p.route)
    .sort((a, b) => a.length - b.length);
  return rute[0] || null;
}

// ── katalog Fitur Tambahan (GET /plugins) ───────────────────────────────

export const STATUS_LABEL = {
  tersedia: 'Tersedia', terpasang: 'Belum selesai diatur', aktif: 'Aktif', dijeda: 'Dijeda', arsip: 'Dicopot',
};

const URUT_STATUS = { aktif: 0, terpasang: 1, dijeda: 2, tersedia: 3, arsip: 4 };

export function urutkanKatalog(daftar) {
  return [...arr(daftar)].sort((a, b) => (URUT_STATUS[a.status] ?? 9) - (URUT_STATUS[b.status] ?? 9)
    || String(a.nama).localeCompare(String(b.nama), 'id'));
}

/**
 * Tombol yang tampil untuk satu plugin di katalog. Hanya tampilan: server tetap memeriksa peran, status, saklar,
 * requires, dan conflicts. Pemilik/admin saja (ADR-P11); saat saklar darurat menyala hanya arah yang mematikan.
 */
export function tombolUntuk(p) {
  if (!p?.boleh_kelola) return [];
  const per = {
    tersedia: ['pasang'],
    terpasang: ['lanjut', 'jeda', 'copot'],
    aktif: ['jeda', 'copot'],
    dijeda: ['lanjut', 'copot'],
    arsip: ['pulihkan'],
  }[p.status] || [];
  return p.diperbaiki ? per.filter(t => t === 'jeda' || t === 'copot') : per;
}

/** Aksi API untuk tombol (pulihkan = pasang pada arsip, 04-kontrak-api.md §5). */
export const aksiApi = (tombol) => (tombol === 'pulihkan' ? 'pasang' : tombol);

/** Body pasang/pulihkan: izin yang ditampilkan di layar izin (server 409 `izin_berubah` bila manifest berubah). */
export function bodyPasang(p) {
  return { izin: arr(p?.izin).map(i => i.kode) };
}

/** Plugin di `butuh` yang belum aktif di ruang ini (untuk teks layar pasang). */
export function butuhBelumAktif(p, katalog) {
  const status = Object.fromEntries(arr(katalog).map(x => [x.id, x]));
  return arr(p?.butuh).filter(id => status[id]?.status !== 'aktif').map(id => status[id]?.nama || id);
}

/** Format unduhan data plugin dari katalog (U1): tombol unduh tampil bila ada data dan plugin pernah terpasang. */
export function formatEkspor(p) {
  if (!p || !['aktif', 'terpasang', 'dijeda', 'arsip'].includes(p.status)) return [];
  return arr(p.ekspor).filter(f => f === 'csv' || f === 'json');
}

/** Nama berkas dari header Content-Disposition server, atau cadangan (nama aneh ditolak). */
export function namaBerkasUnduhan(contentDisposition, cadangan) {
  const m = /filename="([^"]+)"/.exec(String(contentDisposition || ''));
  const nama = m ? m[1] : '';
  return /^[\w.-]+$/.test(nama) ? nama : cadangan;
}

/** Jawaban server → pesan untuk user. */
export function pesanGalat(status, body) {
  const detail = typeof body?.detail === 'string' ? body.detail : '';
  if (status === 0) return 'Koneksi terputus. Coba lagi.';
  if (body?.kode === 'izin_berubah') return detail || 'Izin Fitur Tambahan ini berubah. Muat ulang, lalu periksa lagi.';
  return detail || 'Belum berhasil. Coba lagi sebentar.';
}

// ── tawaran kartu Beranda saat memasang ──────────────────────────────────

/** Kartu yang ditawarkan sesudah memasang: [{key, judul, terpilih}] (kartu `bawaan` sudah dicentang). */
export function tawaranKartu(p) {
  return arr(p?.kartu).map(k => ({ key: k.key, judul: k.judul, terpilih: !!k.bawaan }));
}

const ID_INSTANS_RE = /^[A-Za-z0-9_-]{1,40}$/;

function idBaru(dipakai) {
  for (let n = 1; n < 1000; n += 1) {
    const id = `p${n}`;
    if (!dipakai.has(id)) { dipakai.add(id); return id; }
  }
  return null;
}

/**
 * Body PUT /dashboard/layout yang menambahkan kartu plugin di akhir Beranda. Semua instans yang ada (termasuk
 * `visible: false` dan yang tersembunyi) dikirim balik apa adanya; kartu yang sudah ada atau sedang diparkir tidak
 * ditambah lagi (yang diparkir kembali sendiri saat plugin aktif). `defs` = katalog GET /dashboard/cards (ukuran).
 * Mengembalikan null bila tidak ada yang perlu ditambah.
 */
export function bodyTambahKartu(layout, keys, defs = []) {
  if (!layout || !Array.isArray(layout.items)) return null;
  const items = layout.items.map(i => {
    const it = { id: i.id, card: i.card, size: i.size, hidden: !!i.hidden, devices: i.devices || 'all' };
    if (i.settings && Object.keys(i.settings).length) it.settings = i.settings;
    return it;
  });
  const sudah = new Set([...items, ...arr(layout.parked)].map(i => i.card));
  const dipakai = new Set([...items, ...arr(layout.parked)].map(i => i.id).filter(Boolean));
  const ukuran = Object.fromEntries(arr(defs).map(d => [d.key, d.size_bawaan]));
  let tambah = 0;
  for (const key of [...new Set(arr(keys))]) {
    if (sudah.has(key) || !ukuran[key]) continue;
    const id = idBaru(dipakai);
    if (!id || !ID_INSTANS_RE.test(id)) break;
    items.push({ id, card: key, size: ukuran[key], hidden: false, devices: 'all' });
    tambah += 1;
  }
  if (!tambah) return null;
  return { surface: layout.surface || 'beranda', if_version: layout.version ?? 0, items, removed: [] };
}

// ── format nilai kartu deklaratif ────────────────────────────────────────
// Nominal dari server: int, atau Decimal sebagai string desimal (`titik.rapikan_kartu`); float tidak pernah dikirim.

const angka = (v) => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** Nilai KPI per `unit` (`rp`, `persen`, `hari`, `angka`); kosong atau bukan angka → "—". */
export function formatNilai(v, unit) {
  const n = angka(v);
  if (n === null) return '—';
  if (unit === 'rp') return formatCurrency(n);
  if (unit === 'persen') return `${n.toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`;
  if (unit === 'hari') return `${n.toLocaleString('id-ID', { maximumFractionDigits: 0 })} hari`;
  return n.toLocaleString('id-ID', { maximumFractionDigits: 2 });
}

const ANGKA_RE = /^-?\d+(\.\d+)?$/;

/** Sel tabel: kolom pertama selalu label apa adanya; kolom lain yang berisi angka diberi pemisah ribuan. */
export function selTabel(c, kolom) {
  if (c === null || c === undefined) return '';
  if (kolom > 0 && (typeof c === 'number' || (typeof c === 'string' && ANGKA_RE.test(c)))) return formatNilai(c);
  return String(c);
}

/** Beranda harus digambar dari registry bila tata letaknya memuat kartu plugin (Beranda lama tidak mengenalnya). */
export function adaKartuPlugin(layout, kontribusi) {
  const keys = new Set(arr(kontribusi?.cards).map(c => c.key));
  return arr(layout?.items).some(i => !i.hidden && i.visible !== false && keys.has(i.card));
}
