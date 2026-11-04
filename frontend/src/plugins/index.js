// Kode web Fitur Tambahan per plugin (Plugin H3; 01-kajian.md "Frontend", 03-workflow.md baris H3).
//
// Ikut bundle aplikasi, tidak pernah diunduh per plugin (Apple 2.5.2, aturan mobile 8: perubahan plugin lewat rilis).
// Komponennya `React.lazy`, jadi hanya diunduh saat plugin aktif di ruang ini dan halamannya, kartunya, atau form
// aksinya dibuka. Plugin yang aktif tanpa entri di sini tetap jalan dari server: kartunya digambar dari bentuk
// deklaratif, dan halamannya menampilkan pesan "belum ada di versi aplikasi ini".
//
// Bentuk entri (`src/plugins/<id>/index.js`, mulai U1):
//
//   import { lazy } from 'react';
//   import kartu from './cards.js';            // { '<id>.<kartu>': lazy(() => import('./ArusKasCard.jsx')) }
//   export default {
//     halaman: lazy(() => import('./Halaman.jsx')),          // semua rute /p/<id>/*; props { subpath, plugin }
//     kartu,                                                 // kartu kustom; props { entri, item, ctx, kartu }
//     aksi: { '<id>.penjualan': lazy(() => import('./FormPenjualan.jsx')) },   // props { onDone, onCancel }
//   };
//
// lalu didaftarkan di PLUGIN_WEB di bawah: `import bukuUsaha from './buku_usaha'; … { buku_usaha: bukuUsaha }`.

export const PLUGIN_WEB = {};

export function webPlugin(id) {
  return Object.prototype.hasOwnProperty.call(PLUGIN_WEB, id) ? PLUGIN_WEB[id] : null;
}
