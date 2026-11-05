// Modul web Buku Usaha (Plugin U1; bentuk entri di `src/plugins/index.js`). Ikut bundle; komponen lazy.
import { lazy } from 'react';

export default {
  halaman: lazy(() => import('./Halaman.jsx')),      // /p/buku_usaha/* — U1: tab Kontak
  kartu: {},                                           // kartu kustom: U4
  aksi: {},                                            // form aksi cepat (Penjualan, Prive): U2
  wizard: lazy(() => import('./Wizard.jsx')),         // pasang → terpasang → 5 amplop bawaan → lanjut
};
