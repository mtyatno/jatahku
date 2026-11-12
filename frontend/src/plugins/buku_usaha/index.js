// Modul web Buku Usaha (Plugin U1; bentuk entri di `src/plugins/index.js`). Ikut bundle; komponen lazy.
import { lazy } from 'react';

export default {
  halaman: lazy(() => import('./Halaman.jsx')),      // /p/buku_usaha/* — tab Kontak (U1), Alokasi omzet (U2), Laba rugi (U3)
  kartu: {},                                           // kartu kustom: U4
  // Form aksi cepat (U2): menu Catat ▾ dan FAB. Prive tetap inti (R8, `POST /prive`), bukan aksi plugin.
  aksi: { 'buku_usaha.penjualan': lazy(() => import('./FormPenjualan.jsx')) },
  // Catat cepat (U5): jenis terdeteksi yang dicatat lewat form di atas, dengan isian awal dari yang sudah diketik
  // (props `isiAwal`: { jenis, jumlah, keterangan, kontak_id }).
  catatCepat: { aksi: 'buku_usaha.penjualan', jenis: ['penjualan', 'modal', 'pinjaman'] },
  // Isian field `reference` di form inti (U2): props { field, nilai, onChange }. Field lain digambar host.
  isian: { 'transaction.pemasok': lazy(() => import('./PilihPemasok.jsx')) },
  wizard: lazy(() => import('./Wizard.jsx')),         // pasang → terpasang → 5 amplop bawaan → lanjut
};
