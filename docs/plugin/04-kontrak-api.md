# Plugin dan ruang usaha — kontrak API (v0, draf 31 Okt 2026)

Bentuk header dan endpoint baru supaya frontend dan backend bisa dikerjakan paralel. Versi v0 ditulis sesi F0 dari `01-kajian.md` (bagian "API", "Manifest dan titik ekstensi", "Lampiran teknis") dan `05-desain-buku-usaha.md`. Setiap bagian menyebut sesi yang membangunnya; sesi itu menetapkan bentuk akhirnya di PR-nya sendiri dengan mengubah file ini, lalu memberi tahu pemilik sesi frontend yang memakainya. Bagian yang sudah ditetapkan ditandai **v1 (sesi, PR)**.

## Aturan untuk semua endpoint di file ini

1. **API hanya bertambah** (`AGENTS.md`, "Aplikasi mobile" aturan 2; dicek workflow "Cek API"). Field lama tidak dihapus atau diubah artinya. Endpoint lama yang mendapat perilaku ruang tetap mengembalikan bentuk yang sama.
2. **Ruang untuk membaca** dari header `X-Jatahku-Ruang`. **Ruang untuk menulis** dari objek yang ditulis (amplop, transaksi, pemasukan, kontak, atau ruang itu sendiri di path), lalu server memeriksa keanggotaan, peran, dan batasan. `ruang_id` di body atau query tidak pernah dipercaya (`AGENTS.md`, "Plugin dan ruang" aturan 1).
3. Nama di API adalah `ruang_id`; kolom database tetap `household_id`.
4. Nominal dalam rupiah bulat (integer). Tanggal `YYYY-MM-DD`; waktu ISO 8601 dengan zona waktu user, seperti endpoint yang ada.
5. Teks yang tampil ke user (judul kartu, footer, pesan galat) dirakit server dari templat (aturan 7).
6. **Galat.** Klien sekarang menampilkan `detail` sebagai teks, jadi `detail` tetap teks siap tampil. Galat baru menambah field `kode` untuk mesin: `{"detail": "Batas catatanmu Rp1.000.000. Catatan ini perlu disetujui admin.", "kode": "perlu_persetujuan"}`. Daftar kode di bagian 7.
7. Data karyawan dibatasi di server: endpoint laporan (laba, kas, omzet, arus kas, saldo yang tidak diizinkan) menjawab 403 `khusus_admin` untuk peran `member`, termasuk lewat `/dashboard/data` dan ekspor.

## 0. Field baru di endpoint inti (R1) — **v1 (R1, PR plugin/r1-model-ruang)**

Hanya bertambah; field lama tidak berubah arti. Belum ada perilaku ruang: semua household lama dan baru bertipe `rumah_tangga`, dan endpoint lama tetap memakai satu keanggotaan per user sampai R2.

| Endpoint | Field baru | Nilai |
| --- | --- | --- |
| `GET /household/` | `type` | `rumah_tangga` atau `usaha` (`households.type`; di `GET /ruang` bagian 2 field yang sama bernama `jenis`) |
| `POST /incomes/` body | `kind` (opsional) | `pemasukan` (bawaan) atau `top-up`; nilai lain 422. `transfer` dan `penyesuaian` hanya ditulis server lewat geser dana, hapus amplop, dan cocokkan saldo |
| `POST /incomes/` respons, `GET /incomes/` item | `kind` | `pemasukan`, `transfer`, `top-up`, atau `penyesuaian` (`incomes.kind`). Field lama `type` (`income`/`transfer`) dan `is_adjustment` tetap ada |

Pemasukan lama diberi `kind` oleh migrasi `1c7e5a9d3b20`: `balance_check_id` terisi → `penyesuaian`; nominal 0 → `transfer`; keterangan `Top-up` atau diawali `Top-up ` → `top-up`; selain itu `pemasukan`. Jenis usaha (penjualan, modal pemilik, pinjaman, lain-lain) disimpan Buku Usaha di tabelnya sendiri (U1–U2), bukan di kolom ini.

## 1. Header `X-Jatahku-Ruang` (R2; penulisan R3) — **v1 (R2 #166, penulisan R3)**

Web dan aplikasi mengirim header ini di setiap permintaan sejak R4 (`frontend/src/lib/api.js`). Sampai R4 belum ada klien yang mengirimnya, dan belum ada user yang punya ruang kedua. Header tercantum di OpenAPI sebagai header opsional pada setiap endpoint ber-ruang.

Implementasi: `app/services/ruang.py`. Route menerima ruang sebagai parameter keyword-only `hid: RuangAktif` (membaca) atau `hid: RuangTulis` (menulis) dan meneruskannya ke services sebagai `household_id`; tidak ada service yang mencari household dari keanggotaan sendiri.

| Kasus | Perilaku server |
| --- | --- |
| Header tidak dikirim, atau kosong | Ruang keluarga user: household `rumah_tangga` tempat user menjadi anggota (bila lebih dari satu, keanggotaan tertua). User dengan satu ruang dan aplikasi lama tidak berubah perilakunya |
| UUID ruang tempat user menjadi anggota | Ruang itu dipakai untuk membaca (semua `GET`, plus `POST` yang hanya membaca: `/dashboard/data`, `/balance-check/preview`, `/advisor/allocation-recommendation`) |
| UUID ruang yang bukan milik user, ruang terhapus, atau bukan UUID | 403 `{"detail": "<teks>", "kode": "ruang_tidak_diizinkan"}`. Tidak pernah jatuh diam-diam ke ruang lain |
| Ruang usaha di luar jam kerja anggota itu (ADR-P17) | 403 `di_luar_jam_kerja`, dengan `buka_lagi` (waktu) di body (R5) |
| Endpoint tulis untuk objek yang sudah ada atau yang punya induk (R3) | Header tidak menentukan ruang. Ruang diambil dari objeknya: amplop (`PUT`/`DELETE /envelopes/{id}`, `POST /transactions/`, `POST /goals/`, `POST /recurring/`), transaksi, target, langganan (termasuk bayar/lewati/tandai), grup, cek saldo (`/balance-check/{id}/undo`), merchant Kotak Struk. Objek di ruang yang bukan milik user → 404 dengan pesan "tidak ditemukan" biasa (tidak membocorkan keberadaan objek). Mengubah langganan ke amplop ruang lain → 404 |
| Satu permintaan tulis yang menyentuh dua ruang milik user (R3) | 400 `{"detail": "<teks>", "kode": "lintas_ruang"}`: `POST /envelopes/transfer` antar-ruang, `POST /incomes/` dengan alokasi ke dua ruang. Prive dua sisi menyusul di R8 |
| Antrean offline `POST /transactions/batch` (R3) | Ruang per baris = ruang amplopnya (antrean tidak menyimpan ruang). Baris ke amplop di ruang yang bukan milik user ditolak per baris (`ok: false`, "Envelope not found"); baris lain tetap dicatat. Kirim ulang dengan `client_ref` yang sama mengembalikan transaksi user sendiri |
| Objek baru tanpa induk (R3, keputusan pemilik produk 1 Nov) | Ruang dari header yang sah (`ruang_aktif`), tanpa header = ruang keluarga: `POST /envelopes/`, `POST /envelopes/groups`, `POST /incomes/` tanpa alokasi, `POST /user/reset`, `POST /snapshots/recompute`, `POST /balance-check/apply` (cocokkan saldo seluruh ruang; baris harus amplop ruang itu), `POST /advisor/plan` + `/execute`, saran amplop `POST /transactions/suggest-envelope(s)`. Header ruang orang lain → 403 |
| Undangan anggota (`POST /household/invite`) | Tetap ruang keluarga (`ruang_tulis`); header ruang lain → 403. Undangan ruang usaha dibuat di R5 |

Tata letak Beranda (`GET`/`PUT /dashboard/layout`) adalah dokumen milik user per ruang, jadi keduanya memakai ruang aktif. Dismiss AI Advisor (`POST`/`DELETE /advisor/dismiss`) juga memakai ruang aktif (status per viewer, tidak mengubah data keuangan). Rencana dana dan eksekusinya sama-sama memakai ruang aktif. Daftar lengkap route non-GET yang memakai ruang aktif dijaga `app/tests/test_ruang_pagar.py`.

**Kuota per ruang (R3, ADR-P13).** Kuota Basic (50 transaksi per bulan, 6 amplop, 5 langganan) hanya berlaku di ruang keluarga: transaksi dihitung dari semua catatan user di luar ruang usaha, amplop dan langganan dari ruang tujuan. Ruang usaha tidak memakai kuota Basic; haknya diatur Paket Usaha (tabel hak di H1, kode `butuh_paket_usaha` dipasang di H1/V1, uji coba gratis selama beta). `usage` di `GET /user/profile` mengikuti aturan yang sama.

Bot (Telegram dan chat web), job terjadwal (ringkasan, pengingat gajian, peringatan proaktif), dan Kotak Struk (bukti baru dan saran amplopnya dicatat ke ruang keluarga sampai R7; mencatat bukti ke amplop ruang usaha tetap masuk ruang amplop itu) tidak membaca header ini dan selalu memakai `ruang_keluarga(user)` (ADR-P2).

Dua endpoint lama yang menerima id household dari klien dibatasi ke ruang keluarga (review keamanan PR #166): `POST /auth/link/merge` hanya menerima `keep_household_id` yang merupakan ruang keluarga salah satu dari kedua akun (selain itu 400, tanpa perubahan data); `POST /household/join` (dan `/join` di bot) menolak kode undangan yang menunjuk household selain `rumah_tangga` (400 "Kode invite tidak valid"). Undangan ruang usaha dibuat terpisah di R5.

## 2. Ruang (R4, R5, R6, R7, R8)

```jsonc
// GET /ruang — semua ruang user, untuk pemilih ruang
{
  "bawaan": "<uuid ruang keluarga>",
  "items": [
    {"id": "…", "nama": "Keluarga yatno", "jenis": "rumah_tangga", "peran": "owner", "jumlah_anggota": 2},
    {"id": "…", "nama": "Dapur Nusa", "jenis": "usaha", "peran": "owner", "jumlah_anggota": 3,
     "paket": {"status": "uji_coba", "sampai": "2026-12-31"},   // ADR-P12, P13; null di ruang keluarga
     "jam_kerja": null}                                          // untuk member: jadwalnya sendiri bila diatur admin
  ]
}
// jenis: rumah_tangga | usaha. peran: owner | admin | member (UI: Pemilik, Admin, Karyawan).
// Ruang usaha hanya muncul untuk user di flag ruang_usaha_users (AppSetting) sampai rilis.

// POST /ruang {"nama": "Dapur Nusa"} → 201 {ruang}
// Selalu membuat ruang berjenis usaha; pembuat menjadi owner. 403 di luar flag.
```

Anggota, undangan, dan batasan (R5, R6). Hanya owner dan admin; admin tidak bisa mengubah atau mengeluarkan owner.

```jsonc
// GET    /ruang/{id}/anggota → [{"user_id", "nama", "peran", "jabatan", "bergabung", "batasan": {…} | null}]
// POST   /ruang/{id}/undangan {"peran": "member" | "admin"} → {"kode", "kedaluwarsa"}
//        Bergabung lewat kode memakai pola alur household yang ada (routes/household.py: /household/invite, /household/join).
// PATCH  /ruang/{id}/anggota/{user_id} {"peran"?, "jabatan"?}
// DELETE /ruang/{id}/anggota/{user_id}          // akses hilang seketika; catatan lama tetap milik ruang
// PUT    /ruang/{id}/anggota/{user_id}/batasan  // isi di bawah; tersimpan di log audit ruang

// batasan per anggota (hanya untuk peran member; owner dan admin tanpa batasan)
{
  "jenis_catatan": ["pengeluaran", "penjualan"],  // jenis lain ditambahkan plugin lewat manifest
  "amplop_ids": ["…", "…"],                       // null = semua amplop ruang
  "batas_nominal": 1000000,                       // null = tanpa batas; di atas batas → draf menunggu persetujuan
  "foto_nota_di_atas": 300000,                    // null = tidak wajib
  "jendela_ubah": "hari_sama",                    // hari_sama | tidak_boleh
  "lihat_saldo": false,
  "jam_kerja": null                               // atau {"mulai": "07:00", "selesai": "15:00", "hari": [1, 2, 3, 4, 5, 6]}
}
```

Antrean persetujuan (R5, ADR-P18). Draf disimpan terpisah dan tidak mengubah saldo; saat disetujui, draf dicatat lewat jalur pencatatan yang sama (`expense_rules`) dengan pencatat asli.

```jsonc
// POST /transactions (dan /incomes) dari member di atas batas_nominal
// → 202 {"draf_id", "kode": "perlu_persetujuan", "detail": "…"}   — bukan 201; klien menampilkan "Menunggu persetujuan"
// GET  /ruang/{id}/persetujuan → [{"id", "pencatat", "jenis", "jumlah", "keterangan", "amplop_id", "ada_foto", "dibuat"}]
// GET  /persetujuan/saya → draf milik user di ruang aktif (Beranda karyawan)
// POST /ruang/{id}/persetujuan/{draf_id}/setujui → {"transaction_id"}
// POST /ruang/{id}/persetujuan/{draf_id}/tolak {"alasan"?}
```

Kamus ruang (R7) dan Prive (R8):

```jsonc
// GET    /ruang/{id}/kamus → [{"kata", "amplop_id", "diajarkan_oleh", "dipakai"}]   (owner, admin)
// DELETE /ruang/{id}/kamus/{kata}

// POST /prive {"dari_amplop_id", "jumlah", "tanggal", "catatan"?, "client_ref"}
// Hanya owner ruang usaha asal (ruang dari amplop). Tujuan selalu ruang keluarga owner itu, ditentukan server.
// → 201 {"keluar": {"transaction_id"}, "masuk": {"income_id"}}   — dua sisi dalam satu transaksi database
```

## 3. Catat cepat (R7, U5)

Endpoint yang ada tetap; field baru hanya bertambah. Ruang dari header (membaca), karena saran tidak menulis apa pun.

```jsonc
// POST /transactions/suggest-envelope {"description": "kardus 50 pcs 125rb"}
{
  "envelope_id": "…", "envelope_name": "Operasional", "confident": true,          // field lama, tetap
  "sumber": {"jenis": "kamus_ruang", "diajarkan_oleh": "Bagas", "kali": 4},        // kata_saya | kamus_ruang | kontak | kamus_kategori
  "jumlah": 125000,
  "jenis_catatan": "pengeluaran",                                                  // dari kamus plugin (nlp_kamus, U5): penjualan, modal, …
  "kontak": {"id": "…", "nama": "Toko Plastik Jaya", "peran": "pemasok"} | null,  // U5, bila Buku Usaha aktif
  "aturan": [{"kode": "foto_nota", "teks": "Wajib foto nota di atas Rp300.000"}],  // batasan yang berlaku untuk catatan ini
  "amplop_terkunci": [{"envelope_id": "…", "alasan": "Dikunci admin untukmu"}],
  "tawaran_pribadi": false   // true bila mirip kata pribadi user sendiri; hanya untuk user itu, tidak dicatat (ADR-P5)
}
```

## 4. Beranda (B1, B2) — **v1 (B1 #162; `enabled` B2)**

Implementasi: `app/api/routes/dashboard.py`, `app/services/dashboard/`. Ruang = household user, ditentukan server dari keanggotaan (R2 menggantinya dengan `ruang_aktif`); body yang membawa `ruang_id` atau `household_id` diabaikan. User tanpa household → 404 `ruang_tidak_ada` di semua endpoint di bawah.

```jsonc
// GET /dashboard/layout?surface=beranda → tata letak efektif (01-kajian, "Tata letak efektif dihitung server")
{
  "surface": "beranda", "schema_version": 1, "version": 0,
  "items": [
    {"id": "a1", "card": "core.kpi.jatah", "size": "S", "hidden": false, "devices": "all", "settings": {}, "visible": true}
  ],
  "parked": [],
  "enabled": false
}
// enabled (B2, aditif): user ada di AppSetting `beranda_registry_users` (daftar user_id atau `*`). true → web
// menggambar Beranda dari registry (`BerandaRegistry.jsx`); false → Beranda lama. Hanya di GET, bukan di PUT.
// Belum tersimpan → template bawaan dengan version 0 (GET tidak menyimpan apa pun). Template ruang keluarga =
// Beranda sekarang, 14 kartu a1–a14 (registry.TEMPLATE_BERANDA); Papan disiplin hanya di katalog.
// size: S | M | L | XL (ADR-P8). devices: all | wide (≥1024 px) | narrow (<1024 px).
// Instans yang definisinya tidak ada lagi (mis. kartu plugin yang dicopot) pindah ke parked dan tidak perlu
// dikirim balik; posisinya kembali bila kartunya ada lagi. Instans visible:false (H1 ke atas) tetap dikirim
// dan wajib dikirim balik. "alasan" hanya ada bila visible:false.

// PUT /dashboard/layout {"surface": "beranda", "if_version": 0, "items": [...], "removed": ["a9"]}
// → 200 {"layout": <tata letak efektif>, "version": 1}
// if_version 0 = membuat dokumen pertama dari template. Item: id ^[A-Za-z0-9_-]{1,40}$, card terdaftar,
// size dari sizes kartu, devices, hidden (bool), settings sesuai skema kartu. Maks. 40 item.
// 409 versi_beda (muat ulang, terapkan ulang) · 422 instans_hilang (instans hilang tanpa disebut di removed)
// · 422 kartu_tidak_dikenal · ukuran_tidak_sah · kartu_ganda (kartu multi_instance:false dua kali)
// · pengaturan_tidak_sah · instans_tidak_sah (id/devices/hidden tidak sah, id ganda) · terlalu_banyak

// GET /dashboard/cards → katalog kartu untuk user, ruang, peran, dan platform ini
[{"key": "core.kpi.jatah", "judul": "Jatah hari ini", "deskripsi": "…", "asal": "inti", "sizes": ["S", "M"],
  "size_bawaan": "S", "shape": "kpi", "supports_period": true, "multi_instance": false,
  "refresh_on": ["jatahku:txn-added", "…"], "hak": "ok", "baru": false}]
// asal: inti | <plugin_id>. hak: ok | butuh_plugin | butuh_paket (H1). Kartu laporan usaha tidak tercantum
// untuk peran member (U4). refresh_on: event window yang membuat kartu dimuat ulang (B2).

// POST /dashboard/data {"periode": "2026-10-01" | null, "items": [{"id": "a1", "card": "core.kpi.jatah", "settings": {}}]}
{
  "generated_at": "2026-11-01T08:05:00+07:00",
  "periode": {"start": "2026-11-01", "end": "2026-11-30", "berjalan": true},
  "data": {
    "a1": {"shape": "kpi", "value": 35000, "unit": "rp", "sumber": {"advisor": {…}, "harian": […], "prediksi": {…}}},
    "a4": {"error": {"kode": "kartu_tidak_dikenal", "detail": "Kartu ini tidak tersedia."}}
  }
}
// periode = period_start salah satu periode dari GET /analytics/periods (24 terakhir), atau null = periode
// berjalan. Rentang bebas tidak diterima: 422 periode_tidak_dikenal. 1–40 item, id unik (422 instans_tidak_sah).
// Satu snapshot per permintaan; galat satu penyedia hanya mengisi kartunya:
//   kartu_tidak_dikenal · pengaturan_tidak_sah · gagal_memuat (sumber datanya gagal; coba lagi).
// Anggaran: p95 ≤ 500 ms, penyedia ≤ 150 ms; yang lewat dicatat log "jatahku.dashboard".

// GET /dashboard/data/{instance_id}?surface=beranda&periode= → satu instans dari tata letak user sendiri
// (kartu dan settings dibaca dari dokumen tersimpan, bukan dari klien). Bentuk = satu entri "data".
// 404 instans_tidak_ada.
```

**Kartu inti dan `sumber` (B1).** Penyedia kartu inti tidak menghitung apa pun: `sumber` berisi respons endpoint lama yang dipanggil `Dashboard.jsx` sekarang, persis sama (dikunci tes paritas di `app/tests/test_dashboard_registry.py`), dimuat sekali per permintaan dan dipakai bersama antar kartu. B2 menggambar komponen yang sama dari `sumber`, jadi tampilan tidak berubah. Field deklaratif kartu inti hanya `shape`, dan untuk KPI `value` + `unit` bila angkanya sudah utuh di respons server (total Tabungan masih dijumlah frontend, jadi `value: null`). Teks KPI (footer, sufiks) tetap dirakit frontend sampai dipindah ke templat server.

| Nama di `sumber` | Endpoint lama | Ikut periode | Periode lalu |
| --- | --- | --- | --- |
| `ringkasan_amplop` | `GET /envelopes/summary` | ya | ada |
| `harian` | `GET /analytics/daily-spending` | ya | ada |
| `rincian` | `GET /analytics/envelope-breakdown` | ya | ada |
| `transaksi` | `GET /transactions/?limit=&start_date=&end_date=` (rentang periode) | ya | ada |
| `prediksi` | `GET /analytics/prediction` | berjalan | `null` |
| `tagihan` | `GET /recurring/summary/period` | berjalan | `null` |
| `advisor` | `GET /advisor/dashboard` (KPI: potongan `{enabled, generated_at, metrics tanpa harian, kpi: <chip kartu itu>, redam_chip}`; Pengeluaran harian: `{enabled, generated_at, metrics: {harian}, grafik}`; kartu AI Advisor: utuh) | berjalan | `null` |
| `insights`, `pemasukan` | `GET /advisor/insights`, `GET /incomes/` (hanya kartu AI Advisor saat flag advisor mati: UI Perlu perhatian) | berjalan | `null` |
| `target` | `GET /goals/` | — | ada |
| `langganan` | `GET /recurring/` | — | ada |
| `saldo_cek` | `GET /balance-check/status` | — | ada |
| `papan` | `GET /household/leaderboard` | — | ada |

| Kartu | `shape` | `value` | `sumber` | Pengaturan |
| --- | --- | --- | --- | --- |
| `core.kpi.jatah` | kpi | `metrics.belanja_hari_ini` | advisor, harian, prediksi | — |
| `core.kpi.sisa_bebas` | kpi | `metrics.sisa_bebas_harian` (atau `sisa_bebas`) | advisor, ringkasan_amplop, prediksi | — |
| `core.kpi.terpakai` | kpi | `metrics.terpakai` | advisor, ringkasan_amplop, prediksi | — |
| `core.kpi.income` | kpi | `metrics.pemasukan_rumah_tangga` (advisor mati: `prediksi.total_income`) | advisor, prediksi | — |
| `core.kpi.tagihan` | kpi | `tagihan.amount_due` | advisor, tagihan | — |
| `core.kpi.tabungan` | kpi | `null` | advisor, ringkasan_amplop, target | — |
| `core.cocokkan_saldo` | inti | — | saldo_cek | — |
| `core.pengeluaran_harian` | series | — | advisor, harian, prediksi | — |
| `core.advisor` | inti | — | advisor (+ insights, ringkasan_amplop, langganan, pemasukan, prediksi bila flag mati) | — |
| `core.ke_mana_uangmu` | inti | — | rincian | — |
| `core.amplop_pengeluaran` | inti | — | ringkasan_amplop | — |
| `core.target_tabungan` | progress | — | ringkasan_amplop, target | — |
| `core.transaksi_terbaru` | list | — | transaksi, ringkasan_amplop | `{"limit": 1–50}`, bawaan 10 |
| `core.langganan` | list | — | langganan | — |
| `core.papan_disiplin` | list | — | papan | — |

Bentuk deklaratif (`shape`), digambar komponen inti (`01-kajian.md`, "Bentuk data deklaratif untuk kartu"). `inti` = kartu inti dengan komponen sendiri yang membaca `sumber` (tidak dipakai plugin):

| `shape` | Field |
| --- | --- |
| `kpi` | `value`, `unit` (`rp`, `persen`, `hari`, `angka`), `suffix`, `bar` (0–1, opsional), `footer`, `tone` (`ok`, `info`, `warn`, `danger`), `chip` |
| `progress` | `items`: `[{"label", "value", "target", "tone"}]` |
| `list` | `items` (maks. 8): `[{"judul", "subjudul", "nominal", "status", "aksi"}]` |
| `table` | `columns`, `rows` (maks. 10) |
| `series` | `x` (label), `series` (1–3: `[{"nama", "values"}]`), `acuan` (opsional) |
| `alert` | `tone`, `judul`, `isi`, `aksi` |
| `inti` | `sumber` saja |

`aksi` hanya menunjuk aksi terdaftar: `{"kind": "route", "payload": {"to": "/p/buku_usaha/laba-rugi"}}`, `{"kind": "form", …}`, atau alur `/advisor/plan` untuk pemindahan dana. Kartu plugin (H2, U4) wajib mengisi field bentuknya sendiri; kartu inti boleh hanya membawa `sumber` sampai teksnya dipindah ke templat server.

Menyusul bersama Mode Atur (setelah beta): `POST /dashboard/layout/reset`, `dashboard_defaults` (keputusan kajian no. 7).

## 5. Fitur Tambahan / plugin (H1, H3) — **v1 untuk katalog dan siklus (H1, PR plugin/h1-host-inti)**; `contributions` masih v0 (H3)

Pasang, lanjut, jeda, dan copot hanya untuk owner dan admin ruang (ADR-P11). Urutan pemeriksaan: ruang dari **path** → keanggotaan (bukan anggota, ruang tidak ada, atau id bukan UUID → 404 `ruang_tidak_ada`, supaya keberadaan ruang lain tidak bocor) → peran (member → 403 `khusus_admin`) → plugin (`plugin_id` tidak dikenal → 404 `plugin_tidak_ada`). Header `X-Jatahku-Ruang` tidak menentukan ruang tulis. Aturan: `app/plugins/host/siklus.py`.

```jsonc
// GET /plugins → katalog untuk ruang aktif (header). Semua anggota boleh melihat.
// Berisi plugin yang cocok dengan jenis ruang dan flag rollout user (`plugin_<id>_users`), ditambah plugin yang
// sudah punya baris instalasi di ruang ini (supaya tetap bisa dijeda/dicopot walau flag dicabut).
[{"id": "buku_usaha", "nama": "Buku Usaha", "versi": "1.0.0", "deskripsi": "…", "ikon": "book", "kategori": "usaha",
  "jenis_ruang": ["usaha"],
  "status": "tersedia",              // tersedia | terpasang | aktif | dijeda | arsip
  "arsip_sampai": null,              // "YYYY-MM-DD" bila arsip (dicopot, dihapus permanen setelah tanggal ini)
  "izin_diberikan": [],              // izin yang disetujui saat pasang/pulihkan; [] bila tersedia atau arsip
  "izin": [{"kode": "incomes:write", "teks": "Mencatat pemasukan"}],   // dari manifest versi sekarang
  "kartu": [{"key": "buku_usaha.omzet", "judul": "Omzet", "bawaan": true}],
  "hak": {"status": "uji_coba", "sampai": null},   // gratis | uji_coba | aktif; belum menolak apa pun selama beta (ADR-P13)
  "butuh": [],                       // id plugin yang harus aktif lebih dulu
  "diperbaiki": false,               // saklar darurat menyala: tampilkan "Sedang diperbaiki"
  "boleh_kelola": true}]             // owner/admin; tombol pasang/jeda/copot hanya tampilan, server tetap memeriksa

// POST /ruang/{ruang_id}/plugins/{plugin_id}/pasang   body opsional {"pengaturan": {}}
// POST /ruang/{ruang_id}/plugins/{plugin_id}/lanjut | /jeda
// → {"plugin": "buku_usaha", "status": "aktif", "arsip_sampai": null, "izin_diberikan": ["incomes:read", …]}
// POST /ruang/{ruang_id}/plugins/{plugin_id}/copot
// → {"plugin": "buku_usaha", "status": "arsip", "arsip_sampai": "2027-01-30", "izin_diberikan": [], "ekspor": null}
```

| Aksi | Dari | Ke | Catatan |
| --- | --- | --- | --- |
| `pasang` | tersedia | aktif, atau terpasang bila manifest punya wizard (`contributes.setup`) | Izin manifest saat itu dicatat sebagai `izin_diberikan` |
| `pasang` | arsip | aktif / terpasang (**pulihkan**) | Baris dan data arsip yang sama kembali; izin disetujui ulang |
| `lanjut` | terpasang, dijeda | aktif | Wizard selesai/dilewati, atau melanjutkan |
| `jeda` | terpasang, aktif | dijeda | Data tetap, kontribusi hilang |
| `copot` | terpasang, aktif, dijeda | arsip (+90 hari) | Data inti tidak pernah ikut terhapus (ADR-P15) |

- **Idempoten:** aksi yang diulang pada status tujuannya menjawab 200 dengan status sekarang dan tidak menambah audit. Perpindahan lain yang tidak sah → 404 `plugin_tidak_aktif` (lanjut/jeda pada plugin yang belum terpasang atau arsip).
- Pasang/pulihkan/lanjut ditolak bila: saklar darurat menyala (503 `plugin_diperbaiki`), jenis ruang tidak didukung (422 `jenis_ruang_tidak_cocok`), plugin di `butuh` belum aktif (409 `butuh_plugin`), atau bentrok dengan plugin terpasang (409 `bentrok_plugin`, dua arah). Pasang juga butuh flag rollout user (selain itu 404 `plugin_tidak_ada`); jeda dan copot tidak, supaya plugin selalu bisa dimatikan.
- Jeda/copot ditolak bila plugin lain di ruang ini masih membutuhkannya (409 `dibutuhkan_plugin_lain`): jeda bila pemakainya terpasang/aktif, copot bila pemakainya belum dicopot.
- `pengaturan` yang tidak kosong → 422 `pengaturan_tidak_sah` sampai titik `settings` (form dari JSON Schema + validasi server) ada di H2/U1. Pilihan kartu Beranda saat pasang (`kartu` di v0) dihapus dari body: klien menambah kartu lewat `PUT /dashboard/layout` (H3).
- `ekspor` bernilai `null` sampai endpoint `GET /ruang/{id}/plugins/{plugin_id}/ekspor?format=csv|json` ada (U1, bersama data plugin pertama; escape dan anti formula-injection dari PR #136).
- Saklar darurat: `AppSetting plugin_saklar_darurat` = id plugin dipisah koma (`PUT /admin/settings/plugin_saklar_darurat?value=buku_usaha`). Dibaca setiap permintaan, jadi berlaku seketika; status per ruang tidak berubah.

```jsonc
// GET /plugins/contributions → kontribusi aktif untuk ruang aktif dan peran user (H3, masih v0)
{
  "nav": [{"plugin": "buku_usaha", "grup": "usaha", "label": "Buku Usaha", "route": "/p/buku_usaha", "ikon": "book"}],
  "quick_actions": [{"plugin": "buku_usaha", "key": "buku_usaha.penjualan", "label": "Penjualan", "form": "penjualan"}],
  "pages": [{"plugin": "buku_usaha", "route": "/p/buku_usaha"}],
  "cards": ["buku_usaha.omzet", "…"],
  "form_fields": [{"plugin": "buku_usaha", "target": "transaction", "key": "kontak_id", "type": "reference", "label": "Pemasok"}]
}
// Sumbernya `siklus.aktif_di_ruang()` (H1): hanya plugin berstatus aktif, tanpa saklar darurat, dengan flag user aktif.
// Plugin dijeda, dicopot, atau dimatikan server → tidak ada kontribusinya sama sekali.
```

## 6. Buku Usaha (U1–U4)

Semua di bawah `/p/buku_usaha/`; 404 `plugin_tidak_aktif` bila Buku Usaha tidak terpasang atau dijeda di ruang itu. Bentuk di bagian ini paling mungkin berubah saat sesi U menetapkannya.

```jsonc
// Kontak (U1)
// GET    /p/buku_usaha/kontak?peran=pelanggan|pemasok&q= → [{"id", "nama", "peran", "telepon", "catatan", "total_bulan_ini"}]
// POST   /p/buku_usaha/kontak {"nama", "peran", "telepon"?, "catatan"?} → 201 {kontak}
// PATCH  /p/buku_usaha/kontak/{id} · DELETE /p/buku_usaha/kontak/{id}   — hapus lunak (deleted_at)

// Alokasi omzet (U2) — owner, admin
// GET /p/buku_usaha/alokasi → {"aturan": [{"envelope_id", "nama", "persen": 45}]}
// PUT /p/buku_usaha/alokasi {"aturan": [...]} → 422 alokasi_bukan_100 bila total ≠ 100

// Penjualan (U2) — lewat PluginContext ke jalur pemasukan inti; pembagian ke amplop di transaksi database yang sama
// POST /p/buku_usaha/penjualan/pratinjau {"jumlah"} → {"pembagian": [{"envelope_id", "nama", "jumlah"}]}
// POST /p/buku_usaha/penjualan {"jumlah", "tanggal", "kontak_id"?, "keterangan", "jenis": "penjualan" | "modal" | "pinjaman" | "lain",
//                               "client_ref"} → 201 {"income_id", "pembagian": [...]}
//   Ruang dari amplop tujuan aturan alokasi; batasan member (jenis_catatan, batas_nominal) berlaku seperti /incomes.

// Laba rugi (U3) — owner, admin; member → 403 khusus_admin
// GET /p/buku_usaha/laba-rugi?periode=2026-10
{
  "periode": "2026-10", "omzet": 48650000, "jumlah_penjualan": 112,
  "beban": [{"akun": "…", "jumlah": 0}], "beban_total": 36300000,
  "laba": 12350000, "margin": 0.254,
  "banding": {"periode": "2026-09", "omzet": 44600000, "laba": 9650000},
  "di_luar_laba_rugi": {"prive": 6000000, "modal": 0, "pinjaman": 0}
}
// Satu sumber angka: app/plugins/buku_usaha/metrics.py (aturan 6). Omzet hanya dari jenis penjualan.

// Laporan (U3) — dibuat di worker, bukan di proses API
// POST /p/buku_usaha/laporan {"periode", "format": "pdf" | "csv"} → 202 {"job_id"}
// GET  /p/buku_usaha/laporan/{job_id} → {"status": "antre" | "jalan" | "siap" | "gagal", "url"?}
```

Kunci kartu Beranda (U4): `buku_usaha.omzet`, `buku_usaha.laba`, `buku_usaha.kas`, `buku_usaha.arus_kas_13`, `buku_usaha.alokasi_omzet`, `buku_usaha.beban_akun`, `buku_usaha.pelanggan_teratas` (owner, admin) dan `buku_usaha.penjualan_saya` (member).

## 7. Kode galat

| `kode` | HTTP | Arti |
| --- | --- | --- |
| `ruang_tidak_diizinkan` | 403 | Header ruang bukan ruang user |
| `lintas_ruang` | 400 | Satu permintaan tulis menyentuh dua ruang (R3); prive menyusul di R8 |
| `di_luar_jam_kerja` | 403 | Ruang usaha dibuka di luar jam kerja anggota |
| `khusus_admin` | 403 | Peran member meminta data laporan atau aksi admin (termasuk mengatur Fitur Tambahan, H1) |
| `amplop_tidak_diizinkan` | 403 | Amplop tidak termasuk batasan anggota |
| `jenis_tidak_diizinkan` | 403 | Jenis catatan tidak termasuk batasan anggota |
| `perlu_foto_nota` | 422 | Nominal di atas `foto_nota_di_atas` tanpa foto |
| `perlu_persetujuan` | 202 | Di atas `batas_nominal`; draf dibuat, belum menjadi transaksi |
| `jendela_ubah_lewat` | 403 | Mengubah atau menghapus catatan di luar jendela |
| `butuh_paket_usaha` | 402 | Ruang usaha tanpa hak Paket Usaha (ADR-P13) |
| `plugin_tidak_aktif` | 404 | Plugin tidak terpasang atau dijeda di ruang ini |
| `plugin_tidak_ada` | 404 | `plugin_id` tidak dikenal, atau flag rollout user belum aktif saat memasang (H1) |
| `plugin_diperbaiki` | 503 | Saklar darurat menyala: pasang dan lanjut ditolak, jeda dan copot tetap boleh (H1) |
| `jenis_ruang_tidak_cocok` | 422 | Plugin tidak mendukung jenis ruang ini (H1) |
| `butuh_plugin` | 409 | Plugin yang dibutuhkan belum aktif di ruang ini (H1) |
| `bentrok_plugin` | 409 | Bentrok dengan plugin yang terpasang (H1) |
| `dibutuhkan_plugin_lain` | 409 | Plugin lain di ruang ini masih membutuhkannya (H1) |
| `versi_beda` | 409 | `if_version` tata letak sudah usang |
| `instans_hilang` | 422 | `PUT /dashboard/layout` kehilangan instans tanpa `removed` |
| `ruang_tidak_ada` | 404 | User belum punya household (`/dashboard/*`), atau ruang di path bukan ruang user (`/ruang/{id}/plugins/*`, H1) |
| `kartu_tidak_dikenal` | 422 / per kartu | Kartu tidak terdaftar (`PUT /dashboard/layout`; di `POST /dashboard/data` sebagai galat kartu) |
| `ukuran_tidak_sah`, `kartu_ganda`, `instans_tidak_sah`, `terlalu_banyak` | 422 | Validasi tata letak atau permintaan data (§4) |
| `pengaturan_tidak_sah` | 422 / per kartu | Pengaturan instans tidak cocok dengan skema kartu; pengaturan plugin saat pasang (H1, sampai titik `settings`) |
| `periode_tidak_dikenal` | 422 | `periode` bukan `period_start` dari `GET /analytics/periods` |
| `instans_tidak_ada` | 404 | `GET /dashboard/data/{id}` untuk instans yang tidak ada di tata letak user |
| `gagal_memuat` | per kartu | Sumber data kartu gagal dimuat; kartu lain tetap terisi |
| `alokasi_bukan_100` | 422 | Total persen alokasi omzet ≠ 100 |

Batasan member juga berlaku di `POST /transactions/batch` (antrean offline) dan untuk kiriman ulang dengan `client_ref` yang sama: item yang ditolak kembali dengan `kode` di hasil per item, dan tetap disimpan klien (`AGENTS.md`, "Service Worker", antrean offline).
