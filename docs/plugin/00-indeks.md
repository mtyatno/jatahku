# Plugin dan ruang usaha Jatahku — indeks

Sistem **Fitur Tambahan** (plugin) untuk Jatahku, dengan **Buku Usaha** sebagai plugin pertama (ADR-P7). Uang usaha dipisah dari uang keluarga lewat **ruang**: ruang usaha adalah household kedua bertipe `usaha`, dengan banyak anggota, peran, dan batasan dari admin (ADR-P1, P4). Kartu Beranda menjadi registry dengan data batch, supaya plugin bisa menyumbang kartu. Chat (Telegram dan chat web) tetap hanya untuk ruang keluarga (ADR-P2).

**Fase sekarang:** Fase 1 (Beranda registry) selesai 1 Nov 2026: B1 #162, B2 #165, B3 #167/#168 (Gerbang B lulus, paritas produksi 105 user, p95 231 ms; flag `beranda_registry_users` dinyalakan bertahap oleh pemilik). Fase 2 (ruang usaha) berjalan: R1 #161, R2 #166, dan R3 #171 tayang; R4 menambah `GET`/`POST /ruang` dan pemilih ruang di balik flag `ruang_usaha_users`. Ruang ditentukan `app/services/ruang.py`: membaca dari `ruang_aktif` (header `X-Jatahku-Ruang`, tanpa header = ruang keluarga); sejak R3 (#143) menulis dari objek yang ditulis, objek baru tanpa induk dari header, dan kuota Basic hanya di ruang keluarga; bot dan job selalu ruang keluarga. Berikutnya R4 (membuat dan berpindah ruang, flag `ruang_usaha_users`), R5, R8, dan H1. Status per sesi: `PROGRESS.md`.

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
| Registry kartu dan data batch | `app/services/dashboard/` (`registry.py` definisi + template, `providers.py` penyedia kartu inti, `sources.py` endpoint lama sekali per permintaan, `batch.py`, `layout.py`), `app/api/routes/dashboard.py`, model `DashboardLayout` (migrasi `b1d4a7c2e9f0`), tes `app/tests/test_dashboard_registry.py`; frontend: `src/pages/Dashboard.jsx` (pemilih lewat `enabled`), `BerandaRegistry.jsx`, `BerandaLama.jsx`, `src/cards/` (`CardRegistry.js`, `DashboardGrid.jsx`, `CardFrame.jsx`, `core/index.jsx`), bersama: `lib/berandaModel.js`, `lib/dashboardRegistry.js`, `components/BerandaKpi.jsx`, `components/BerandaHeader.jsx`, `hooks/useBerandaShell.js` | B1 (backend), B2 (frontend) |
| Resolver ruang | `app/services/ruang.py`: `ruang_aktif` (dependency route, parameter `hid: RuangAktif`), ruang dari objek `ruang_amplop` / `ruang_amplop_satu` / `ruang_objek` (R3), `ruang_tulis` (undangan, ruang keluarga), `ruang_keluarga(user, db)` (bot, job), `keanggotaan`; kuota per ruang di `plan_limits.py`; skrip `app/scripts/ruang_paritas.py`; pagar `app/tests/test_ruang_pagar.py` | R2, R3 |
| Daftar dan pemilih ruang | `app/api/routes/ruang.py` (`GET`/`POST /ruang`), saklar flag `ruang_usaha_users` di `ruang.ruang_usaha_dibuka`; frontend: `src/lib/ruangAktif.js` (pilihan, header, cache per ruang, ADR-P16), `src/components/RuangPicker.jsx` (sidebar dan header HP), `lib/api.js` (header + kembali ke ruang keluarga saat 403); tes `app/tests/test_ruang_r4.py`, `src/lib/ruangAktif.test.js` | R4 |
| Host plugin dan SDK | `app/plugins/host/`, `app/plugins/sdk/` (`PluginContext`) | H1, H2 |
| Buku Usaha | `app/plugins/buku_usaha/` (manifest, `metrics.py`, kartu, aturan BU-*), `frontend/src/plugins/buku_usaha/` | U1–U6 |
| Cek migrasi | `.github/workflows/migrasi.yml`, `.github/scripts/cek-migrasi.sh` | F0 |
| Verifikasi Beranda registry (Gerbang B) | `app/scripts/beranda_paritas.py` (paritas angka semua user, di VPS), `scripts/banding_beranda.py` (banding tampilan di laptop), `?beranda=lama\|registry` di `Dashboard.jsx`; langkah rilis di `AGENTS.md` "Rilis Beranda registry" | B3 |

## Sumber di luar repo

- Dokumen "Kajian Dashboard Kustomisasi & Sistem Plugin Jatahku" di claude.ai (https://claude.ai/artifact/GBThMvGCNTzqHMJPpspu2Q), versi dengan diagram dari `01-kajian.md`.
- Dokumen "Rencana Development Plugin Buku Usaha" di claude.ai (https://claude.ai/artifact/VuQVnfRG5fmUcdqCKBLs7s), versi dengan diagram dari `03-workflow.md`.
- Kanvas desain Buku Usaha (https://claude.ai/artifact/NFHnjALwuskpZz8pxB3Z8k), 10 artboard; ringkasannya di `05-desain-buku-usaha.md` bagian A.
- Artifact "Tracker Plugin Jatahku" di claude.ai: status, PR, dan tanggal per sesi untuk manusia.

Perubahan rencana dan keputusan dibuat di repo lewat PR, lalu disalin ke dokumen claude.ai dan project "jatahku".
