# Aplikasi mobile Jatahku — indeks

Aplikasi Android (Google Play) dan iOS (App Store) dengan **Capacitor 8** di atas bundle React yang sama dengan web, termasuk fitur **Bagikan ke Jatahku** (bukti transfer, e-wallet, tagihan, invoice marketplace → Kotak Struk → konfirmasi amplop). Dirancang supaya tidak mengulang migrasi shell Alurik (Tauri → Capacitor).

**Fase sekarang:** F0 — keputusan, akun, legal. O01 selesai (#100). Fondasi F1 dimulai: 1.3 `/app/config` dan header `X-Jatahku-Client` tayang (#109). Belum ada proyek `mobile/`. Status per paket: `PROGRESS.md`.

## Dokumen
| File | Isi | Kapan dibaca |
|---|---|---|
| `01-kajian.md` | Kajian lengkap: pelajaran Alurik, kondisi repo, kebutuhan, opsi teknologi, kesiapan toko & regulasi, Paket Pro, Bagikan ke Jatahku, roadmap, WBS, risiko, biaya | Bagian yang disebut paket; seluruhnya sekali di awal |
| `02-adr.md` | ADR-M1 sampai M16 | Setiap sesi; dirujuk di PR |
| `03-workflow.md` | Cara kerja: satu sesi = satu PR, `/sesi` & `/tutup-sesi`, template PR, koordinasi dengan AI Advisor, daftar paket & jadwal sesi | Awal setiap sesi |
| `PROGRESS.md` | Status tiap paket | Awal dan akhir setiap sesi |
| `SESI-LOG.md` | Catatan serah-terima | Entri terakhir di awal sesi; entri baru di akhir |

## Aturan singkat
Sebelas aturan ada di `AGENTS.md` bagian "Aplikasi mobile". Yang paling penting: **API hanya bertambah** (aplikasi terpasang menjalankan kode lama berminggu-minggu) dan **perbedaan platform hanya di `frontend/src/native/`**.

## Sumber di luar repo
- Dokumen "Kajian & Rencana Aplikasi Mobile Jatahku" di claude.ai (versi dengan diagram). Perubahan rencana dibuat di repo lewat PR.
- Artifact "Tracker Mobile Jatahku" di claude.ai: status, PR, catatan per paket, gerbang.
