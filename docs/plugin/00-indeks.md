# Plugin dan ruang usaha Jatahku — indeks

Sistem **Fitur Tambahan** (plugin) untuk Jatahku, dengan **Buku Usaha** sebagai plugin pertama (ADR-P7). Uang usaha dipisah dari uang keluarga lewat **ruang**: ruang usaha adalah household kedua bertipe `usaha`, dengan banyak anggota, peran, dan batasan dari admin (ADR-P1, P4). Kartu Beranda menjadi registry dengan data batch, supaya plugin bisa menyumbang kartu. Chat (Telegram dan chat web) tetap hanya untuk ruang keluarga (ADR-P2).

**Fase sekarang:** Fase 0 — Persiapan. O1 selesai 31 Okt 2026 (dua belas rekomendasi disetujui menjadi ADR-P8–P19). F0 (#137) membuka folder ini, aturan di `AGENTS.md`, perintah `/sesi-plugin` dan `/tutup-sesi-plugin`, workflow "Migrasi", serta issue #137–#158. Belum ada kode plugin. Berikutnya B1 (#138) dan R1 (#141), dua jalur yang bisa paralel; bila dikerjakan sendiri, B1 dulu. Status per sesi: `PROGRESS.md`.

## Dokumen

| File | Isi | Kapan dibaca |
|---|---|---|
| `01-kajian.md` | Kajian lengkap: kondisi repo, Beranda kustomisasi, pilihan arsitektur plugin, manifest dan titik ekstensi, ruang usaha, tabel plugin, keamanan dan UU PDP, monetisasi, katalog plugin, lampiran teknis | Bagian yang disebut sesi; seluruhnya sekali di awal |
| `02-adr.md` | ADR-P1 sampai P19, plus keputusan kajian yang belum diambil | Setiap sesi; dirujuk di PR |
| `03-workflow.md` | Urutan fase dan gerbang, cakupan Buku Usaha v1, daftar sesi (hasil, file, dependensi), keamanan, cara kerja, template PR | Awal setiap sesi |
| `04-kontrak-api.md` | Header `X-Jatahku-Ruang` dan bentuk endpoint baru: `/ruang`, Catat cepat, `/dashboard/*`, `/plugins/*`, Buku Usaha, kode galat (v0, ditetapkan sesi pembuatnya) | Sesi yang menambah atau memakai endpoint itu; diubah di PR yang sama |
| `05-desain-buku-usaha.md` | A: mockup per artboard, keputusan desain, data contoh. B: keputusan ruang usaha (chat, pencatatan cerdas, peran, batasan, persetujuan) | Sesi R4–R8, H3, U1–U6 |
| `PROGRESS.md` | Status tiap sesi dan gerbang | Awal dan akhir setiap sesi |
| `SESI-LOG.md` | Catatan serah-terima | Entri terakhir di awal sesi; entri baru di akhir |

## Aturan singkat

Sembilan aturan ada di `AGENTS.md` bagian "Plugin dan ruang". Yang paling penting: **ruang ditentukan server, tidak pernah oleh klien** (membaca lewat `ruang_aktif`, menulis dari objek yang ditulis) dan **chat selalu ruang keluarga**. Aturan "Aplikasi mobile" tetap berlaku, terutama **API hanya bertambah**, karena aplikasi Android dan iOS memakai bundle yang sama. Temuan keamanan dikerjakan sebelum fitur dilanjutkan.

## Peta kode

Diisi sesi yang membuatnya. Rencana dari `01-kajian.md`, "Lampiran teknis":

| Bagian | Lokasi | Sesi |
|---|---|---|
| Registry kartu dan data batch | `app/services/dashboard/` (`registry.py` definisi + template, `providers.py` penyedia kartu inti, `sources.py` endpoint lama sekali per permintaan, `batch.py`, `layout.py`), `app/api/routes/dashboard.py`, model `DashboardLayout` (migrasi `b1d4a7c2e9f0`), tes `app/tests/test_dashboard_registry.py`; frontend `frontend/src/cards/core/` (B2) | B1 (backend), B2 |
| Resolver ruang | `ruang_aktif(user, request)`, `ruang_keluarga(user)` (menggantikan dua `get_household_id`) | R2 |
| Host plugin dan SDK | `app/plugins/host/`, `app/plugins/sdk/` (`PluginContext`) | H1, H2 |
| Buku Usaha | `app/plugins/buku_usaha/` (manifest, `metrics.py`, kartu, aturan BU-*), `frontend/src/plugins/buku_usaha/` | U1–U6 |
| Cek migrasi | `.github/workflows/migrasi.yml`, `.github/scripts/cek-migrasi.sh` | F0 |

## Sumber di luar repo

- Dokumen "Kajian Dashboard Kustomisasi & Sistem Plugin Jatahku" di claude.ai (https://claude.ai/artifact/GBThMvGCNTzqHMJPpspu2Q), versi dengan diagram dari `01-kajian.md`.
- Dokumen "Rencana Development Plugin Buku Usaha" di claude.ai (https://claude.ai/artifact/VuQVnfRG5fmUcdqCKBLs7s), versi dengan diagram dari `03-workflow.md`.
- Kanvas desain Buku Usaha (https://claude.ai/artifact/NFHnjALwuskpZz8pxB3Z8k), 10 artboard; ringkasannya di `05-desain-buku-usaha.md` bagian A.
- Artifact "Tracker Plugin Jatahku" di claude.ai: status, PR, dan tanggal per sesi untuk manusia.

Perubahan rencana dan keputusan dibuat di repo lewat PR, lalu disalin ke dokumen claude.ai dan project "jatahku".
