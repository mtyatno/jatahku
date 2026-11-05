// Tampilan per peran di ruang usaha (Plugin R6; 05-desain-buku-usaha.md B4.1, B4.3, A2 butir 12, 16, 18).
//
// Server yang menegakkan semua batasan (AGENTS.md "Plugin dan ruang" aturan 3). Di sini hanya keputusan tampilan:
// menu yang disembunyikan, menu Catat karyawan, teks ringkas batasan, dan label log ruang. Pembantu murni supaya
// bisa diuji tanpa browser.

const PERAN_PENGELOLA = new Set(['owner', 'admin']);

/** Peran user di ruang aktif (`GET /ruang` item). Karyawan = peran `member` di ruang usaha. */
export function aksesRuang(aktif) {
  const usaha = aktif?.jenis === 'usaha';
  const karyawan = usaha && aktif?.peran === 'member';
  const jenis = Array.isArray(aktif?.jenis_catatan) ? aktif.jenis_catatan : ['pengeluaran', 'penjualan'];
  return {
    usaha,
    karyawan,
    pengelola: usaha && PERAN_PENGELOLA.has(aktif?.peran),
    ruangId: aktif?.id ?? null,
    jenisCatatan: karyawan ? jenis.filter(j => j === 'pengeluaran' || j === 'penjualan') : [],
  };
}

// Halaman yang dibuka karyawan. Halaman lain memanggil endpoint yang tertutup untuknya (403 `khusus_admin`).
export const RUTE_KARYAWAN = ['/', '/transactions', '/settings'];
export const RUTE_KELOLA = '/ruang';
// Halaman milik pribadi user yang endpoint-nya tidak membaca ruang aktif (laporan berkala: `/laporan`,
// `/laporan/:id`). Tetap terbuka di ruang mana pun supaya tautan notifikasi laporan tidak dialihkan ke Beranda,
// tetapi tidak ikut menu karyawan (menu memakai RUTE_KARYAWAN).
const RUTE_PRIBADI = ['/laporan'];

/** Boleh membuka `path` di ruang aktif ini? Selain itu Layout mengarahkan ke Beranda. */
export function ruteBoleh(path, akses) {
  const p = (path || '/').replace(/\/+$/, '') || '/';
  if (p === RUTE_KELOLA) return !!akses?.pengelola;
  if (!akses?.karyawan) return true;
  return RUTE_KARYAWAN.includes(p) || RUTE_PRIBADI.some(r => p === r || p.startsWith(`${r}/`));
}

/** Menu (bottom nav dan sidebar) untuk peran ini. Pengelola ruang usaha mendapat "Anggota" dengan angka antrean
 *  (`kelola: false` untuk bottom nav HP yang sudah penuh; di HP halaman Anggota dibuka dari pemilih ruang). */
export function menuUntuk(items, akses, { menunggu = 0, kelola = true } = {}) {
  const dasar = akses?.karyawan ? items.filter(i => RUTE_KARYAWAN.includes(i.to)) : [...items];
  if (akses?.pengelola && kelola) {
    dasar.push({ to: RUTE_KELOLA, label: 'Anggota', icon: 'users', badge: menunggu, badgeLabel: 'menunggu persetujuan' });
  }
  return dasar;
}

const CATAT = {
  pengeluaran: { key: 'karyawan-pengeluaran', icon: 'expense', label: 'Pengeluaran' },
  penjualan: { key: 'karyawan-penjualan', icon: 'income', label: 'Penjualan' },
};

/** Pilihan Catat karyawan sesuai `jenis_catatan` dari admin (satu pintu Catat, A2 butir 12). */
export function catatKaryawan(akses) {
  return (akses?.jenisCatatan || []).map(j => CATAT[j]).filter(Boolean);
}

export const jenisDariAksi = (key) => (key === 'karyawan-penjualan' ? 'penjualan' : 'pengeluaran');

/** Body permintaan Catat karyawan. Penjualan dialokasikan penuh ke satu amplop (server menolak sisa, 422). */
export function payloadCatat({ jenis, nominal, keterangan, amplopId, clientRef }) {
  const amount = Math.round(Number(nominal) || 0);
  const desc = (keterangan || '').trim();
  if (jenis === 'penjualan') {
    return {
      path: '/incomes/',
      body: { amount, source: desc || 'Penjualan', client_ref: clientRef,
        allocations: [{ envelope_id: amplopId, amount }] },
    };
  }
  return {
    path: '/transactions/',
    body: { envelope_id: amplopId, amount, description: desc || 'Pengeluaran', client_ref: clientRef },
  };
}

/** Jawaban server → hasil untuk ditampilkan. 202 `perlu_persetujuan` = draf menunggu admin (ADR-P18). */
export function hasilCatat(status, body) {
  const detail = typeof body?.detail === 'string' ? body.detail : '';
  if (status === 202 || body?.kode === 'perlu_persetujuan') {
    return { hasil: 'menunggu', pesan: detail || 'Catatan ini menunggu persetujuan admin.' };
  }
  if (status >= 200 && status < 300) return { hasil: 'tercatat', pesan: 'Tercatat.' };
  if (body?.kode === 'di_luar_jam_kerja') return { hasil: 'galat', pesan: detail || 'Ruang ini sedang tutup.' };
  if (status === 0) return { hasil: 'galat', pesan: 'Koneksi terputus. Coba lagi — tidak akan tercatat dua kali.' };
  return { hasil: 'galat', pesan: detail || 'Gagal menyimpan. Periksa isian lalu coba lagi.' };
}

const rp = (n) => `Rp${Math.round(Number(n) || 0).toLocaleString('id-ID')}`;
const HARI = ['', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'];

export function ringkasHari(hari) {
  const h = [...new Set(hari || [])].sort((a, b) => a - b);
  if (h.length === 7) return 'setiap hari';
  if (h.length > 2 && h.every((x, i) => i === 0 || x === h[i - 1] + 1)) return `${HARI[h[0]]}–${HARI[h[h.length - 1]]}`;
  return h.map(x => HARI[x]).join(', ');
}

/**
 * Batasan karyawan dalam kalimat pendek (kartu "Batasan dari admin" dan ringkasan di halaman Anggota).
 * `amplop` = daftar nama amplop yang diizinkan, atau null = semua amplop ruang.
 */
export function ringkasBatasan(b, amplop = null) {
  if (!b) return [];
  const jenis = b.jenis_catatan || [];
  const baris = [];
  baris.push(jenis.length === 0 ? 'Belum boleh mencatat apa pun'
    : jenis.length === 2 ? 'Boleh mencatat pengeluaran dan penjualan'
      : `Boleh mencatat ${jenis[0]} saja`);
  baris.push(amplop == null ? 'Semua amplop ruang ini'
    : amplop.length === 0 ? 'Belum ada amplop yang diizinkan' : `Amplop: ${amplop.join(', ')}`);
  baris.push(b.batas_nominal == null ? 'Tanpa batas nominal'
    : `Di atas ${rp(b.batas_nominal)} per catatan menunggu persetujuan admin`);
  if (b.foto_nota_di_atas != null) baris.push(`Wajib foto nota di atas ${rp(b.foto_nota_di_atas)}`);
  baris.push(b.jendela_ubah === 'tidak_boleh' ? 'Catatan tidak bisa dihapus sendiri'
    : 'Catatan sendiri bisa dihapus di hari yang sama');
  baris.push(b.lihat_saldo ? 'Boleh melihat saldo amplop yang diizinkan' : 'Saldo amplop tidak ditampilkan');
  if (b.jam_kerja) {
    baris.push(`Jam kerja ${b.jam_kerja.mulai}–${b.jam_kerja.selesai}, ${ringkasHari(b.jam_kerja.hari)}`);
  }
  return baris;
}

/** Peran user di ruang `aktifId` berubah antara daftar ruang tersimpan dan yang baru (mis. admin diturunkan): cache
 *  Beranda ruang itu dibuang supaya angka dari peran lama tidak tersisa di perangkat (review PR #185 no. 4). */
export function peranBerubah(lama, baru, aktifId) {
  if (!lama || !baru || !aktifId) return false;
  const cari = (d) => (Array.isArray(d.items) ? d.items.find(r => r.id === aktifId) : null);
  const a = cari(lama);
  const b = cari(baru);
  return !!a && (!b || a.peran !== b.peran);
}

// ── Form batasan di halaman Anggota ────────────────────────────────────────
/** Batasan API → isian form (angka sebagai teks, jam kerja punya saklar sendiri). */
export function formDariBatasan(b) {
  const jk = b?.jam_kerja;
  return {
    jenis_catatan: [...(b?.jenis_catatan || ['pengeluaran', 'penjualan'])],
    semua_amplop: b?.amplop_ids == null,
    amplop_ids: [...(b?.amplop_ids || [])],
    batas_nominal: b?.batas_nominal == null ? '' : String(b.batas_nominal),
    foto_nota_di_atas: b?.foto_nota_di_atas == null ? '' : String(b.foto_nota_di_atas),
    jendela_ubah: b?.jendela_ubah || 'hari_sama',
    lihat_saldo: !!b?.lihat_saldo,
    pakai_jam_kerja: !!jk,
    jam_mulai: jk?.mulai || '08:00',
    jam_selesai: jk?.selesai || '17:00',
    hari: jk?.hari ? [...jk.hari] : [1, 2, 3, 4, 5, 6],
    zona: jk?.zona || null,
  };
}

const angkaAtauNull = (t) => {
  const s = String(t ?? '').replace(/[^\d]/g, '');
  return s ? Number(s) : null;
};

/** Isian form → body `PUT /ruang/{id}/anggota/{user}/batasan`. */
export function batasanDariForm(f) {
  return {
    jenis_catatan: f.jenis_catatan,
    amplop_ids: f.semua_amplop ? null : f.amplop_ids,
    batas_nominal: angkaAtauNull(f.batas_nominal),
    foto_nota_di_atas: angkaAtauNull(f.foto_nota_di_atas),
    jendela_ubah: f.jendela_ubah,
    lihat_saldo: f.lihat_saldo,
    jam_kerja: f.pakai_jam_kerja
      ? { mulai: f.jam_mulai, selesai: f.jam_selesai, hari: f.hari, ...(f.zona ? { zona: f.zona } : {}) }
      : null,
  };
}

/** Isian yang bisa dikirim: jam kerja butuh hari dan jam yang berbeda; amplop pilihan tidak boleh kosong. */
export function galatForm(f) {
  if (f.pakai_jam_kerja && (!f.hari.length || f.jam_mulai === f.jam_selesai)) {
    return 'Pilih hari kerja, dan jam mulai harus berbeda dari jam selesai.';
  }
  if (!f.semua_amplop && f.amplop_ids.length === 0) return 'Pilih minimal satu amplop, atau izinkan semua amplop.';
  return null;
}

// ── Antrean dan log ────────────────────────────────────────────────────────
export const STATUS_DRAF = {
  menunggu: 'Menunggu persetujuan',
  diproses: 'Sedang diproses',
  disetujui: 'Disetujui',
  ditolak: 'Ditolak',
  dibatalkan: 'Dibatalkan',
};

export const labelStatusDraf = (s) => STATUS_DRAF[s] || s;

const PERAN = { owner: 'Pemilik', admin: 'Admin', member: 'Karyawan' };

/** Satu baris log ruang (`GET /ruang/{id}/audit`) dalam kalimat. Akun terhapus → "Mantan anggota". */
export function labelAudit(a) {
  const oleh = a?.oleh_nama || 'Mantan anggota';
  const siapa = a?.anggota_nama || 'Mantan anggota';
  const r = a?.rincian || {};
  switch (a?.aksi) {
    case 'undangan_dibuat': return `${oleh} membuat undangan ${PERAN[r.peran] || ''}`.trim();
    case 'undangan_dicabut': return `${oleh} mencabut undangan ${PERAN[r.peran] || ''}`.trim();
    case 'anggota_bergabung': return `${siapa} bergabung sebagai ${PERAN[r.peran] || r.peran}`;
    case 'anggota_diubah':
      if (r.peran) return `${oleh} mengubah peran ${siapa} menjadi ${PERAN[r.peran.ke] || r.peran.ke}`;
      return `${oleh} mengubah jabatan ${siapa}${r.jabatan ? ` menjadi ${r.jabatan}` : ''}`;
    case 'anggota_keluar': return `${siapa} keluar dari ruang`;
    case 'anggota_dikeluarkan': return `${oleh} mengeluarkan ${siapa}`;
    case 'batasan_diubah': return `${oleh} mengubah batasan ${siapa}`;
    case 'draf_disetujui': return `${oleh} menyetujui catatan ${siapa}`;
    case 'draf_ditolak': return `${oleh} menolak catatan ${siapa}`;
    case 'catatan_dihapus': return `${oleh} menghapus catatannya`;
    case 'reset_ruang': return `${oleh} mereset data ruang`;
    case 'ruang_diubah': return `${oleh} mengganti nama ruang menjadi ${r.nama?.ke || ''}`.trim();
    case 'kata_dihapus': return `${oleh} menghapus kata "${r.kata || ''}"${r.amplop ? ` (${r.amplop})` : ''} dari kamus ruang`;
    default: return `${oleh}: ${a?.aksi || 'perubahan'}`;
  }
}
