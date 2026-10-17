// Lapisan native (ADR-M6, aturan mobile #1 di AGENTS.md): SATU-SATUNYA tempat
// perbedaan web / Android / iOS. Komponen memakai `native` dari sini dan tidak
// pernah memeriksa Capacitor, user agent, display-mode, atau hostname.
//
// Antarmuka (sama untuk web.js dan capacitor.js nanti):
//   init()                         → Promise; dipanggil sekali sebelum render (main.jsx)
//   platform                       → {name, isNative, apiUrl}
//   tokens.getAccess/setAccess/getRefresh/setRefresh   (sinkron; null = hapus)
//   queue.store()                  → {all, add, put, del} penyimpanan antrean offline
//   queue.withAuth(item)           → item siap disimpan (web: + token untuk service worker)
//   queue.requestBackgroundSync()  → minta sistem mengirim antrean walau app tertutup
//   queue.onBackgroundSynced(cb)   → cb(summary) setelah sinkron di latar; → pelepas
//   files.save(blob, filename)     → simpan ke perangkat
//   files.share(blob, filename, {title}) → 'shared' | 'cancelled' | 'saved'
//   print.pdf({frame, url})        → cetak PDF yang tampil di iframe
//   openExternal(url, event?)      → buka tautan di luar app
//   externalLinkProps(url, onClick?, {appUrl}) → props <a> untuk tautan luar
//   onInstallPrompt(cb)            → prompt instal PWA (aplikasi: tidak pernah); → pelepas
//
// Implementasi Capacitor (paket 3.2) dipilih di sini berdasarkan platform build
// (CLIENT.platform dari clientInfo.js), bukan tebakan saat runtime.
import { createWebNative } from './web.js';

export const native = createWebNative({ prod: import.meta.env.PROD });
