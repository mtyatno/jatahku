# Plugin dan ruang usaha — kontrak API (v0, draf 31 Okt 2026)

Bentuk header dan endpoint baru supaya frontend dan backend bisa dikerjakan paralel. Versi v0 ditulis sesi F0 dari `01-kajian.md` (bagian "API", "Manifest dan titik ekstensi", "Lampiran teknis") dan `05-desain-buku-usaha.md`. Setiap bagian menyebut sesi yang membangunnya; sesi itu menetapkan bentuk akhirnya di PR-nya sendiri dengan mengubah file ini, lalu memberi tahu pemilik sesi frontend yang memakainya. Bagian yang sudah ditetapkan ditandai **v1 (sesi, PR)**.

## Aturan untuk semua endpoint di file ini

1. **API hanya bertambah** (`AGENTS.md`, "Aplikasi mobile" aturan 2; dicek workflow "Cek API"). Field lama tidak dihapus atau diubah artinya. Endpoint lama yang mendapat perilaku ruang tetap mengembalikan bentuk yang sama.
2. **Ruang untuk membaca** dari header `X-Jatahku-Ruang`. **Ruang untuk menulis** dari objek yang ditulis (amplop, transaksi, pemasukan, kontak, atau ruang itu sendiri di path), lalu server memeriksa keanggotaan, peran, dan batasan. `ruang_id` di body atau query tidak pernah dipercaya (`AGENTS.md`, "Plugin dan ruang" aturan 1).
3. Nama di API adalah `ruang_id`; kolom database tetap `household_id`.
4. Nominal dalam rupiah bulat (integer). Tanggal `YYYY-MM-DD`; waktu ISO 8601 dengan zona waktu user, seperti endpoint yang ada.
5. Teks yang tampil ke user (judul kartu, footer, pesan galat) dirakit server dari templat (aturan 7).
6. **Galat.** Klien sekarang menampilkan `detail` sebagai teks, jadi `detail` tetap teks siap tampil. Galat baru menambah field `kode` untuk mesin: `{"detail": "Batas catatanmu Rp1.000.000. Catatan ini perlu disetujui admin.", "kode": "perlu_persetujuan"}`. Daftar kode di bagian 7.
7. Data karyawan dibatasi di server: endpoint laporan (laba, kas, omzet, arus kas, saldo yang tidak diizinkan) menjawab 403 `khusus_admin` untuk peran `member`, termasuk lewat `/dashboard/data` dan ekspor. **Sejak R5 berupa tolak-bawaan:** karyawan (peran `member` di ruang **usaha**) hanya bisa memakai route di daftar `KARYAWAN_BOLEH` (`app/services/ruang.py`, lihat §2 "Karyawan"); semua route lain, termasuk route baru, menjawab 403 `khusus_admin`. Peran `member` di ruang keluarga tidak dibatasi.

## 0. Field baru di endpoint inti (R1) — **v1 (R1, PR plugin/r1-model-ruang)**

Hanya bertambah; field lama tidak berubah arti. Belum ada perilaku ruang: semua household lama dan baru bertipe `rumah_tangga`, dan endpoint lama tetap memakai satu keanggotaan per user sampai R2.

| Endpoint | Field baru | Nilai |
| --- | --- | --- |
| `GET /household/` | `type` | `rumah_tangga` atau `usaha` (`households.type`; di `GET /ruang` bagian 2 field yang sama bernama `jenis`) |
| `POST /incomes/` body | `kind` (opsional) | `pemasukan` (bawaan) atau `top-up`; nilai lain 422. `transfer` dan `penyesuaian` hanya ditulis server lewat geser dana, hapus amplop, dan cocokkan saldo |
| `POST /incomes/` respons, `GET /incomes/` item | `kind` | `pemasukan`, `transfer`, `top-up`, atau `penyesuaian` (`incomes.kind`). Field lama `type` (`income`/`transfer`) dan `is_adjustment` tetap ada |

**H2 (titik `checks`):** `POST /transactions/` respons (201) mendapat field `peringatan`: `null`, atau daftar teks siap tampil (maks. 3) dari Fitur Tambahan yang aktif di ruang amplop itu, mis. `["Melewati anggaran Bahan Baku"]`. Hanya informasi: pencatatan tidak pernah ditolak karenanya, dan karyawan tidak pernah menerimanya. Sumbernya `expense_rules.peringatan_plugin`, sama dengan bot. `POST /transactions/batch` dan pemasukan belum (menyusul bersama pemakainya).

Pemasukan lama diberi `kind` oleh migrasi `1c7e5a9d3b20`: `balance_check_id` terisi → `penyesuaian`; nominal 0 → `transfer`; keterangan `Top-up` atau diawali `Top-up ` → `top-up`; selain itu `pemasukan`. Jenis usaha (penjualan, modal pemilik, pinjaman, lain-lain) disimpan Buku Usaha di tabelnya sendiri (U1–U2), bukan di kolom ini.

## 1. Header `X-Jatahku-Ruang` (R2; penulisan R3) — **v1 (R2 #166, penulisan R3)**

Web dan aplikasi mengirim header ini di setiap permintaan sejak R4 (`frontend/src/lib/api.js`, `lib/ruangAktif.js`), hanya bila user memilih ruang selain ruang keluarga. Ruang kedua hanya bisa dibuat user di flag `ruang_usaha_users` (§2). Header tercantum di OpenAPI sebagai header opsional pada setiap endpoint ber-ruang.

Implementasi: `app/services/ruang.py`. Route menerima ruang sebagai parameter keyword-only `hid: RuangAktif` (membaca) atau `hid: RuangTulis` (menulis) dan meneruskannya ke services sebagai `household_id`; tidak ada service yang mencari household dari keanggotaan sendiri.

| Kasus | Perilaku server |
| --- | --- |
| Header tidak dikirim, atau kosong | Ruang keluarga user: household `rumah_tangga` tempat user menjadi anggota (bila lebih dari satu, keanggotaan tertua). User dengan satu ruang dan aplikasi lama tidak berubah perilakunya |
| UUID ruang tempat user menjadi anggota | Ruang itu dipakai untuk membaca (semua `GET`, plus `POST` yang hanya membaca: `/dashboard/data`, `/balance-check/preview`, `/advisor/allocation-recommendation`) |
| UUID ruang yang bukan milik user, ruang terhapus, atau bukan UUID | 403 `{"detail": "<teks>", "kode": "ruang_tidak_diizinkan"}`. Tidak pernah jatuh diam-diam ke ruang lain |
| Ruang usaha di luar jam kerja anggota itu (ADR-P17) | 403 `{"detail", "kode": "di_luar_jam_kerja", "buka_lagi": "2026-11-02T07:00:00+07:00"}` (R5). Berlaku lewat header dan untuk tulis dari objek (catat, hapus, pemasukan); di antrean offline per baris (`kode` di hasil baris) |
| Endpoint tulis untuk objek yang sudah ada atau yang punya induk (R3) | Header tidak menentukan ruang. Ruang diambil dari objeknya: amplop (`PUT`/`DELETE /envelopes/{id}`, `POST /transactions/`, `POST /goals/`, `POST /recurring/`), transaksi, target, langganan (termasuk bayar/lewati/tandai), grup, cek saldo (`/balance-check/{id}/undo`), merchant Kotak Struk. Objek di ruang yang bukan milik user → 404 dengan pesan "tidak ditemukan" biasa (tidak membocorkan keberadaan objek). Mengubah langganan ke amplop ruang lain → 404 |
| Satu permintaan tulis yang menyentuh dua ruang milik user (R3) | 400 `{"detail": "<teks>", "kode": "lintas_ruang"}`: `POST /envelopes/transfer` antar-ruang, `POST /incomes/` dengan alokasi ke dua ruang. Satu-satunya pengecualian: `POST /prive` (R8), yang menentukan kedua ruangnya sendiri di server |
| Antrean offline `POST /transactions/batch` (R3) | Ruang per baris = ruang amplopnya (antrean tidak menyimpan ruang). Baris ke amplop di ruang yang bukan milik user ditolak per baris (`ok: false`, "Envelope not found"); baris lain tetap dicatat. Kirim ulang dengan `client_ref` yang sama mengembalikan transaksi user sendiri |
| Objek baru tanpa induk (R3, keputusan pemilik produk 1 Nov) | Ruang dari header yang sah (`ruang_aktif`), tanpa header = ruang keluarga: `POST /envelopes/`, `POST /envelopes/groups`, `POST /incomes/` tanpa alokasi, `POST /user/reset`, `POST /snapshots/recompute`, `POST /balance-check/apply` (cocokkan saldo seluruh ruang; baris harus amplop ruang itu), `POST /advisor/plan` + `/execute`, saran amplop `POST /transactions/suggest-envelope(s)`. Header ruang orang lain → 403 |
| Undangan anggota (`POST /household/invite`) | Tetap ruang keluarga (`ruang_tulis`); header ruang lain → 403. Undangan ruang usaha: `POST /ruang/{id}/undangan` + `POST /ruang/gabung` (R5, §2) |

Tata letak Beranda (`GET`/`PUT /dashboard/layout`) adalah dokumen milik user per ruang, jadi keduanya memakai ruang aktif. Dismiss AI Advisor (`POST`/`DELETE /advisor/dismiss`) juga memakai ruang aktif (status per viewer, tidak mengubah data keuangan). Rencana dana dan eksekusinya sama-sama memakai ruang aktif. Daftar lengkap route non-GET yang memakai ruang aktif dijaga `app/tests/test_ruang_pagar.py`.

**Kuota per ruang (R3, ADR-P13).** Kuota Basic (50 transaksi per bulan, 6 amplop, 5 langganan) hanya berlaku di ruang keluarga: transaksi dihitung dari semua catatan user di luar ruang usaha, amplop dan langganan dari ruang tujuan. Ruang usaha tidak memakai kuota Basic; haknya diatur Paket Usaha (tabel hak di H1, kode `butuh_paket_usaha` dipasang di H1/V1, uji coba gratis selama beta). `usage` di `GET /user/profile` mengikuti aturan yang sama.

Bot (Telegram dan chat web), job terjadwal (ringkasan, pengingat gajian, peringatan proaktif), dan Kotak Struk (bukti baru dan saran amplopnya dicatat ke ruang keluarga sampai R7; mencatat bukti ke amplop ruang usaha tetap masuk ruang amplop itu) tidak membaca header ini dan selalu memakai `ruang_keluarga(user)` (ADR-P2).

Dua endpoint lama yang menerima id household dari klien dibatasi ke ruang keluarga (review keamanan PR #166): `POST /auth/link/merge` hanya menerima `keep_household_id` yang merupakan ruang keluarga salah satu dari kedua akun (selain itu 400, tanpa perubahan data); `POST /household/join` (dan `/join` di bot) menolak kode undangan yang menunjuk household selain `rumah_tangga` (400 "Kode invite tidak valid"). Undangan ruang usaha terpisah (R5, §2).

## 2. Ruang (R4, R5, R6, R7, R8) — **`GET`/`POST /ruang` v1 (R4)**

```jsonc
// GET /ruang — semua ruang user, untuk pemilih ruang. Tidak membaca header ruang.
{
  "bawaan": "<uuid ruang keluarga>",          // null bila user belum punya household
  "items": [                                  // ruang keluarga dulu, lalu ruang lain urut bergabung
    {"id": "…", "nama": "Keluarga yatno", "jenis": "rumah_tangga", "peran": "owner", "jumlah_anggota": 2,
     "paket": null, "jam_kerja": null},
    {"id": "…", "nama": "Dapur Nusa", "jenis": "usaha", "peran": "owner", "jumlah_anggota": 3,
     "paket": null,       // ADR-P12, P13: {"status": "uji_coba", "sampai": "2026-12-31"} mulai H1/V1; null sampai saat itu
     "jam_kerja": null,   // R5: untuk member, jadwalnya sendiri bila diatur admin
     "jenis_catatan": null}   // R6 (aditif): untuk member, jenis yang boleh dicatat (menu Catat); null untuk peran lain
  ],
  "boleh_buat_usaha": true                    // flag terbuka untuk user ini dan belum mencapai batas (R4)
}
// jenis: rumah_tangga | usaha. peran: owner | admin | member (UI: Pemilik, Admin, Karyawan).
// Ruang usaha hanya muncul untuk user di flag ruang_usaha_users (AppSetting) sampai rilis.

// POST /ruang {"nama": "Dapur Nusa"} → 201 {ruang}   (item seperti di atas, jumlah_anggota 1)
// Selalu membuat ruang berjenis usaha; pembuat menjadi owner. Nama 1–60 huruf (spasi dirapikan), selain itu 422.
// 403 `ruang_usaha_belum_dibuka` di luar flag; 409 `batas_ruang_usaha` bila user sudah memiliki 3 ruang usaha.
// Ruang baru: siklus bulan kalender (payday_day 1, desain A2 butir 9), tanpa kode undangan (undangan ruang usaha di R5).
```

**Flag `ruang_usaha_users` sebagai saklar (R4).** Di luar flag, ruang usaha milik user tidak tampil di `GET /ruang`,
tidak bisa dibuka lewat header (403 `ruang_tidak_diizinkan`, §1), dan objeknya tidak bisa ditulis (404 seperti objek
asing). Ruang keluarga tidak pernah terpengaruh. Klien (`frontend/src/lib/ruangAktif.js`) menyimpan id ruang terpilih di
perangkat (hanya ruang selain ruang keluarga; dihapus saat logout), mengirimnya di setiap permintaan, memisah cache offline
per ruang, dan bila server menjawab 403 `ruang_tidak_diizinkan` untuk header itu, kembali ke ruang keluarga dan memuat
ulang Beranda. Permintaan yang ditolak tidak diulang tanpa header, supaya catatan tidak masuk ruang yang salah. Berpindah
ruang memuat ulang aplikasi di Beranda. Chat tetap ruang keluarga: di ruang usaha tombolnya berlabel "Ruang keluarga"
untuk pemilik dan admin, dan disembunyikan untuk karyawan (ADR-P16).

Anggota, undangan, batasan, persetujuan, audit — **v1 (R5, PR plugin/r5-peran-batasan)**. Implementasi: `app/api/routes/ruang_kelola.py`, `app/services/peran.py`. Ikut flag `ruang_usaha_users` (R4): di luar flag route ini 404, dan `/ruang/gabung` 403 `ruang_usaha_belum_dibuka`.

Semua `/ruang/{id}/…` hanya untuk ruang **usaha** (ruang keluarga tetap lewat `/household`) dan hanya owner dan admin ruang itu: bukan anggota atau ruang keluarga → 404 "Ruang tidak ditemukan"; karyawan → 403 `khusus_admin`. Admin tidak bisa mengubah atau mengeluarkan owner (403 `khusus_admin`). Setiap perubahan tercatat di log audit ruang.

```jsonc
// GET    /ruang/{id}/anggota → [{"user_id", "nama", "peran", "jabatan", "bergabung", "batasan": {…} | null}]
//        batasan hanya untuk peran member (bawaan bila belum pernah diatur); owner dan admin → null
// POST   /ruang/{id}/undangan {"peran": "member" | "admin"} → 201 {"kode": "RU…", "peran", "kedaluwarsa"}
//        sekali pakai, berlaku 7 hari (tabel ruang_undangan; bukan households.invite_code)
// GET    /ruang/{id}/undangan → [{"id", "kode", "peran", "dibuat_oleh": "<nama>" | null, "kedaluwarsa", "dibuat"}]
//        (R6) hanya yang masih bisa dipakai: belum dipakai, belum dicabut, belum kedaluwarsa; terbaru dulu
// DELETE /ruang/{id}/undangan/{undangan_id} → 204   (R6) mencabut kode; `/ruang/gabung` lalu menolaknya (400);
//        sudah dipakai → 409; sudah dicabut → 204 tanpa perubahan; undangan ruang lain → 404; log `undangan_dicabut`
// PATCH  /ruang/{id} {"nama"} → {"id", "nama"}   (R6) owner dan admin; nama 1–60 huruf (spasi dirapikan), selain itu
//        422; log `ruang_diubah`. Tutup atau hapus ruang usaha belum ada.
// POST   /ruang/gabung {"kode"} → {"id", "nama", "jenis": "usaha", "peran"}
//        tidak mengubah ruang keluarga user; kode dipakai/kedaluwarsa/salah → 400; sudah anggota → 400; 10/menit per IP;
//        kode hanya berlaku selama pembuatnya masih owner/admin ruang itu, selain itu 400 (R6, review #185): pembuat
//        yang dikeluarkan, keluar, atau diturunkan ke karyawan juga membuat kodenya dicabut (log `undangan_dicabut`)
// PATCH  /ruang/{id}/anggota/{user_id} {"peran"?: "member" | "admin", "jabatan"?} → {"user_id", "peran"}
//        admin boleh mengubah, menaikkan, menurunkan, dan mengeluarkan admin lain; hanya owner yang terlindung (ADR-P4).
//        R6: ganti peran membuang tata letak Beranda anggota itu di ruang ini (Beranda berikutnya = template peran baru)
// DELETE /ruang/{id}/anggota/{user_id} → 204   // owner/admin mengeluarkan, atau anggota keluar sendiri (bukan owner);
//        akses hilang seketika; catatan lama tetap milik ruang; draf yang menunggu → dibatalkan; batasannya dan tata
//        letak Berandanya di ruang ini dihapus (R6)
// PUT    /ruang/{id}/anggota/{user_id}/batasan → batasan tersimpan (isi di bawah); hanya peran member, selain itu 422;
//        amplop bukan milik ruang itu → 422; jam_kerja tidak sah → 422
// GET    /ruang/{id}/audit?limit=50 → [{"aksi", "oleh", "anggota", "rincian", "waktu", "oleh_nama", "anggota_nama"}]
//        (nama: R6, aditif; akun terhapus → null)
//        aksi: undangan_dibuat, anggota_bergabung, anggota_diubah, anggota_keluar, anggota_dikeluarkan,
//        batasan_diubah, draf_disetujui, draf_ditolak, catatan_dihapus, reset_ruang (jumlah catatan per pencatat, tanpa nominal),
//        undangan_dicabut, ruang_diubah (R6)

// batasan per anggota (hanya untuk peran member; owner dan admin tanpa batasan)
// Bawaan bila admin belum mengatur: dua jenis, semua amplop, tanpa batas nominal dan foto, hari_sama, lihat_saldo false,
// tanpa jam kerja.
{
  "jenis_catatan": ["pengeluaran", "penjualan"],  // pengeluaran = POST /transactions, penjualan = POST /incomes
  "amplop_ids": ["…", "…"],                       // null = semua amplop ruang; juga amplop alokasi pemasukan
  "batas_nominal": 1000000,                       // null = tanpa batas; di atas batas → draf menunggu persetujuan
  "foto_nota_di_atas": 300000,                    // null = tidak wajib; foto = receipt_item_id (Kotak Struk)
  "jendela_ubah": "hari_sama",                    // hari_sama | tidak_boleh (menghapus catatan sendiri)
  "lihat_saldo": false,                           // false: /envelopes/summary 403, budget_amount di /envelopes = 0
  "jam_kerja": null                               // atau {"mulai": "07:00", "selesai": "15:00", "hari": [1, 2, 3, 4, 5, 6], "zona": "Asia/Jakarta"}
}
// hari ISO (1 = Senin); selesai ≤ mulai = sif lewat tengah malam; zona bawaan = zona admin yang menyimpan.
```

**Karyawan** (peran `member` di ruang usaha). Route yang boleh, dengan penyaringannya:

| Route | Perilaku untuk karyawan |
| --- | --- |
| `GET /envelopes/` | Hanya amplop di `amplop_ids`; `budget_amount` = 0 bila `lihat_saldo` false |
| `GET /envelopes/summary` | 403 `khusus_admin` bila `lihat_saldo` false; selain itu hanya amplop yang diizinkan |
| `GET /transactions/` | Hanya catatan miliknya |
| `POST /transactions/suggest-envelope(s)` | Amplop yang tidak diizinkan tidak disarankan |
| `POST /transactions/`, `/transactions/batch` | Batasan per catatan (urutan: jenis → amplop → foto → nominal); di atas batas → 202 draf. `raise_daily_limit` diabaikan (limit harian dari admin tidak bisa dinaikkan karyawan). Tanpa `lihat_saldo`, pesan dana tidak cukup, amplop belum diisi, dan limit harian tanpa angka |
| `DELETE /transactions/{id}` | Hanya catatan miliknya, dalam `jendela_ubah`; selain itu 403 `jendela_ubah_lewat`. Tercatat di log audit (`catatan_dihapus`) |
| `POST /incomes/` | Jenis `penjualan`, amplop alokasi, lalu alokasi harus sama dengan nominal (sisa tidak boleh jatuh ke Tabungan: 422 `alokasi_tidak_penuh`), batas nominal; di atas batas → 202 draf. Field baru `client_ref` (aditif): kiriman ulang → 202 dengan status draf terbaru. Notifikasi target dari penjualan karyawan dikirim ke owner |
| `GET /persetujuan/saya` | Draf miliknya |
| `GET`/`PUT /dashboard/layout`, `GET /dashboard/cards`, `POST /dashboard/data`, `GET /dashboard/data/{id}` | R6: hanya kartu karyawan (§4, "Beranda karyawan"); kartu umum → `khusus_admin` per kartu, tanpa memuat datanya |

Semua route lain (amplop, grup, transfer, target, langganan, cocokkan saldo, analitik, ekspor, AI Advisor, reset, …) → 403 `khusus_admin`.

Antrean persetujuan — **v1 (R5)**, ADR-P18. Draf disimpan terpisah (`ruang_draf`) dan tidak mengubah saldo; saat disetujui, draf dicatat lewat jalur pencatatan yang sama (`catat_transaksi` / `catat_pemasukan`) atas nama pencatat asli, jadi aturan amplop, dana, limit harian, kunci, dan struk tetap berlaku; hanya batasan karyawan yang tidak dicek lagi.

```jsonc
// POST /transactions (dan /incomes) dari karyawan di atas batas_nominal
// → 202 {"draf_id", "kode": "perlu_persetujuan", "status": "menunggu", "detail": "Batas catatanmu Rp1.000.000. …"}
//   bukan 201; klien menampilkan "Menunggu persetujuan". Kirim ulang client_ref yang sama → 202 draf yang sama;
//   sesudah disetujui → 201 transaksi hasil persetujuan (client_ref yang sama dipakai saat dicatat).
//   Satu client_ref = satu catatan (R7, review keamanan #191): kiriman ulang hanya menjawab transaksi/draf lama bila
//   ruang, jenis, dan amplopnya sama; ref yang sudah dipakai catatan lain → 409 `client_ref_bentrok` (di batch: per
//   baris), tidak pernah jawaban catatan ruang lain.
// POST /transactions/batch: baris di atas batas → {"ok": false, "kode": "perlu_persetujuan", "draf_id", "error": "…"};
//   baris yang ditolak batasan → {"ok": false, "kode": "<kode §7>", "error": "…"} (field kode, draf_id baru, aditif)
// GET  /ruang/{id}/persetujuan → [{"id", "pencatat", "pencatat_id", "jenis", "jumlah", "keterangan", "amplop_id",
//                                 "ada_foto", "status", "alasan", "hasil_id", "dibuat"}]   (status menunggu)
// GET  /persetujuan/saya → draf milik user di ruang aktif: menunggu + yang diputus 14 hari terakhir (bentuk sama)
// POST /ruang/{id}/persetujuan/{draf_id}/setujui → {"transaction_id" | "income_id", "draf_id", "status": "disetujui"}
//      aturan pencatatan gagal (mis. dana tidak cukup, limit harian amplop terlewati — persetujuan tidak menaikkan
//      limit) → 403 dengan pesan lengkap untuk admin, draf kembali "menunggu";
//      sudah diputus → 409; pencatat sudah keluar → 409
// POST /ruang/{id}/persetujuan/{draf_id}/tolak {"alasan"?} → {"draf_id", "status": "ditolak"}
// status draf: menunggu | diproses | disetujui | ditolak | dibatalkan
```

Kamus ruang — **v1 (R7)**, ADR-P5. Kata → amplop yang diajarkan anggota mana pun dari catatan yang tersimpan, dipakai
semua anggota ruang itu (sesudah kata user sendiri, §3). Hanya ruang usaha; aturan sama dengan `/ruang/{id}/…` lain
(owner/admin, bukan anggota atau bukan ruang usaha atau di luar flag → 404, karyawan → 403 `khusus_admin`).

```jsonc
// GET /ruang/{id}/kamus?q=&limit=200 → {"total": 37, "items": [
//   {"id", "kata": "kardus", "envelope_id", "amplop": "Operasional", "emoji": "🧾", "kali": 4,
//    "diajarkan_oleh": "Bagas" | null,   // pengajar terakhir; null = akun terhapus atau baris lama
//    "diubah": "2026-11-04T03:10:00+00:00"}]}
// Urut: paling sering dulu, lalu kata. `q` = kata memuat teks itu (tanpa wildcard); limit 1–500 (bawaan 200);
// `total` = semua kata di ruang ini sebelum q dan limit. Kata frasa ("kardus besar") ikut sebagai baris sendiri.
// DELETE /ruang/{id}/kamus/{kamus_id} → 204. Kata ruang lain → 404. Ikut menghapus kata user (`user_envelope_keywords`)
//   yang sama untuk amplop itu milik semua anggota, supaya pengajarnya juga tidak mendapat tebakan itu lagi.
//   Termasuk frasa user yang sama sesudah nominal/satuan dibuang ("kardus besar pcs" untuk kata "kardus besar").
//   Log ruang: `kata_dihapus` {"kata", "envelope_id", "amplop"}.
```

Yang mengajari kamus ruang: catatan pengeluaran **bukan-privat** lewat web/aplikasi (`POST /transactions`,
`/transactions/batch`, dan draf yang disetujui, atas nama pencatatnya) ke amplop **bersama** (tanpa `owner_id`), aktif,
bertujuan pengeluaran, di ruang usaha. Kata = kata dari keterangan tanpa nominal, angka, dan satuan (`pcs`, `kg`, `pax`,
…), maksimal 12 kata + satu frasa. Tidak mengajari: catatan privat (kamus terlihat admin), amplop pribadi, ruang
keluarga, bot (ADR-P2), Kotak Struk, pemasukan. Reset ruang menghapus kamusnya; hapus akun mengosongkan
`diajarkan_oleh`.

Prive (R8):

```jsonc

// POST /prive {"dari_amplop_id", "jumlah", "tanggal"?, "catatan"?, "client_ref"}     (v1, R8; client_ref wajib)
// Hanya owner ruang usaha asal (ruang dari amplop). Tujuan selalu ruang keluarga pemanggil, ditentukan server;
// header X-Jatahku-Ruang tidak dipakai. Sisa amplop dihitung dengan siklus ruang usaha (bulan kalender).
// tanggal bawaan hari ini (server), hanya di irisan periode berjalan ruang usaha dan ruang keluarga pemilik;
// catatan maks. 200 karakter; client_ref 1–64 karakter, wajib (kirim ulang → jawaban yang sama tanpa catatan
// ganda, juga bila tanggalnya sudah di luar periode; fail-closed: Redis tidak terjangkau dalam 2 detik → 503).
// → 201 {
//   "keluar": {"income_id", "ruang_id", "amplop"},   // ruang usaha: pemasukan bernilai 0 + alokasi -jumlah di amplop asal
//   "masuk":  {"income_id", "ruang_id", "amplop": "Tabungan"},  // ruang keluarga: pemasukan sungguhan ke Tabungan
//   "jumlah": "250000", "tanggal": "2026-11-01"
// }   — dua sisi dalam satu transaksi database
// Galat: 404 amplop tidak ada / ruang orang lain / pribadi anggota lain / nonaktif · 400 `bukan_ruang_usaha`
// · 403 `prive_hanya_pemilik` · 400 `tanpa_ruang_keluarga` · 400 melebihi sisa amplop ("Maksimal prive dari …")
// · 400 tanggal masa depan / sebelum awal periode berjalan · 409 client_ref masih diproses · 422 jumlah ≤ 0 atau tanpa client_ref
// · 503 client_ref dikirim tetapi pengaman kiriman ulang tidak terjangkau (coba lagi)
```

Kedua sisi tersimpan di `incomes` dengan `kind = "prive"` (v0 menulis `keluar.transaction_id`; diubah di R8 supaya prive tidak pernah menjadi transaksi pengeluaran). Akibatnya: prive tidak dihitung sebagai beban dan tidak mengurangi laba (U3 menghitung beban dari transaksi); `GET /incomes/` di ruang usaha menampilkan sisi keluar sebagai `type: "transfer"`, `transfer: null`, `kind: "prive"` (riwayat web sekarang melewatinya), dan di ruang keluarga sisi masuk sebagai `type: "income"`, `kind: "prive"`. Hapus atau batalkan prive belum ada.

## 3. Catat cepat (R7, U5) — **v1 untuk saran amplop, sumber, dan aturan (R7)**; `jenis_catatan` dan `kontak` masih v0 (U5)

Endpoint yang ada tetap; field baru hanya bertambah. Ruang dari header (membaca), karena saran tidak menulis apa pun.
Nominal diurai di perangkat (`parseAmount.js`, kasusnya sama dengan bot) dan dikirim terpisah dari keterangan.

```jsonc
// POST /transactions/suggest-envelope {"description": "kardus 50 pcs", "amount": 125000}   // amount opsional (R7)
{
  "envelope_id": "…", "envelope_name": "Operasional", "confident": true,          // field lama, tetap
  "sumber": {"jenis": "kamus_ruang", "kali": 4, "diajarkan_oleh": "Bagas", "oleh_saya": false} | null,
  //   jenis: kata_saya | kamus_ruang | kamus_plugin (titik `nlp_kamus`, H2) | kamus_kategori | nama_amplop (U5 menambah kontak)
  //   kali: kata_saya dan kamus_ruang = hitungan kata yang cocok yang paling sering diajarkan (≈ jumlah catatan);
  //   diajarkan_oleh/oleh_saya: hanya kamus_ruang (nama null bila pengajarnya pemanggil sendiri atau akunnya terhapus).
  //   Karyawan: kamus_ruang hanya {"jenis": "kamus_ruang"} tanpa kali, diajarkan_oleh, oleh_saya (review keamanan
  //   #191 temuan 2, keputusan pemilik produk 5 Nov), supaya saran tidak bisa dipakai menebak catatan anggota lain.
  "aturan": [{"kode": "foto_nota", "teks": "Wajib foto nota di atas Rp300.000."},
             {"kode": "persetujuan", "teks": "Di atas batasmu Rp1.000.000: menunggu persetujuan admin."}]
  //   batasan karyawan untuk `amount` (kosong untuk owner/admin, ruang keluarga, atau tanpa amount); juga dijawab
  //   bila description kosong. Hanya tampilan: penegakan tetap di jalur catat (§2, kode §7).
  // U5 (v0): "jenis_catatan": "pengeluaran" | "penjualan" | …, "kontak": {"id", "nama", "peran"} | null
}
// POST /transactions/suggest-envelopes {"descriptions": [...]} → results[] dengan field lama + "sumber": {"jenis"} | null
// Batas (R7, review keamanan #191): description ≤ 500 huruf, descriptions ≤ 100 item (lebih → 422); per user
// suggest-envelope 60/menit dan suggest-envelopes 20/menit (lebih → 429), termasuk permintaan tanpa header.
```

Urutan cocok (`txn_nlp.cari_amplop`): kata yang dipelajari user sendiri (amplop di ruang ini) → kamus ruang (hanya bila
ruang di header bertipe usaha; gerbangnya di kueri) → kamus Fitur Tambahan yang aktif di ruang itu (H2, `nlp_kamus`) →
kamus kategori bawaan → nama amplop di keterangan. Karyawan:
hanya amplop yang diizinkan menjadi kandidat, jadi amplop terkunci tidak menutupi tebakan berikutnya; amplop terkunci
tidak dikirim (daftar amplop karyawan dari `GET /envelopes/` sudah hanya yang diizinkan).

**Tawaran "pengeluaran pribadi"** (v0 `tawaran_pribadi` dihapus; keputusan R7 B): tidak dihitung server, supaya tidak ada
kueri lintas ruang selain Prive (`AGENTS.md` aturan 8). Bila tebakan di ruang usaha tidak berasal dari `kata_saya` atau
`kamus_ruang`, klien memanggil endpoint yang sama **tanpa header** (= ruang keluarga user sendiri); tawaran muncul hanya
bila `sumber.jenis` jawabannya `kata_saya` dan `confident`. "Catat di ruang keluarga" = `POST /transactions` tanpa header
ke amplop dari jawaban itu (ruang tulis dari amplop, R3). Tidak tersimpan, tidak terlihat admin.

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
| `progress` | `items`: `[{"label", "value", "target", "tone"}]` — web menggambar `value`/`target` sebagai rupiah (H3) |
| `list` | `items` (maks. 8): `[{"judul", "subjudul", "nominal", "status", "aksi"}]` |
| `table` | `columns`, `rows` (maks. 10) — web: kolom pertama label apa adanya; kolom lain yang berisi angka diberi pemisah ribuan (H3), jadi label seperti tahun ditaruh di kolom pertama atau ditulis sebagai teks berhuruf |
| `series` | `x` (label), `series` (1–3: `[{"nama", "values"}]`), `acuan` (opsional) |
| `alert` | `tone`, `judul`, `isi`, `aksi` |
| `inti` | `sumber` saja |

`aksi` hanya menunjuk aksi terdaftar: `{"kind": "route", "payload": {"to": "/p/buku_usaha/laba-rugi"}}`, `{"kind": "form", …}`, atau alur `/advisor/plan` untuk pemindahan dana. Kartu plugin (H2, U4) wajib mengisi field bentuknya sendiri; kartu inti boleh hanya membawa `sumber` sampai teksnya dipindah ke templat server.

**Beranda karyawan (R6).** Setiap kartu menyatakan `untuk`: `umum` (semua kartu inti) atau `karyawan`. Karyawan = peran
`member` di ruang usaha (`peran.batasan_karyawan`); semua peran lain, termasuk anggota ruang keluarga, memakai kartu umum.
Server menyaring di setiap route `/dashboard/*`:

```jsonc
// GET /dashboard/layout (dan "layout" di jawaban PUT) → + "untuk": "karyawan" | "umum" (aditif). Karyawan: "enabled" selalu true (Beranda lama
// memanggil endpoint yang tertutup untuknya) dan template "Karyawan" (registry.TEMPLATE_KARYAWAN, a1–a6, ukuran M).
// Instans tersimpan yang kartunya bukan untuk peran ini → "visible": false, "alasan": "khusus_admin" (karyawan)
// atau "khusus_karyawan" (peran lain); datanya ditolak. Saat menyimpan, instans itu boleh dikirim balik dan disimpan
// dari salinan server (ukuran, pengaturan, dan sembunyikan dari klien diabaikan).
// GET /dashboard/cards → karyawan: hanya kartu karyawan; peran lain: hanya kartu umum (katalog ruang keluarga tetap).
// PUT /dashboard/layout → kartu yang bukan untuk peran ini: 422 kartu_tidak_dikenal.
// POST /dashboard/data → kartu umum untuk karyawan: {"error": {"kode": "khusus_admin"}} per kartu, penyedianya tidak
// dipanggil; kartu karyawan untuk peran lain: {"error": {"kode": "kartu_tidak_dikenal"}}. `periode` diabaikan
// kartu karyawan (selalu hari ini, zona user). "Catatan hari ini" = dibuat hari ini menurut jam dibuat (`created_at`)
// di zona user, sama dengan jendela ubah; bukan `transaction_date`/`income_date` (bertanggal jam server UTC).
```

| Kartu (`untuk: karyawan`) | `shape` | Isi |
| --- | --- | --- |
| `core.karyawan.catat` | inti | `jenis_catatan`, `amplop` (`[{id, nama, emoji}]` yang diizinkan, tanpa anggaran) |
| `core.karyawan.hari_ini` | inti | `tanggal`, `pengeluaran` dan `penjualan` `{jumlah, total}` miliknya hari ini, `jenis_catatan` |
| `core.karyawan.menunggu` | list | `items` drafnya (menunggu + diputus 14 hari): `{id, jenis, judul, nominal, status, subjudul: alasan, dibuat}`; `menunggu`, `total_item` |
| `core.karyawan.catatan_hari_ini` | list | `items` catatannya hari ini: `{id, jenis, judul, subjudul: nama amplop, emoji, nominal, waktu, boleh_hapus}` (hapus hanya transaksi, dalam `jendela_ubah`); `total_item`, `jendela_ubah` |
| `core.karyawan.batasan` | inti | `batasan` (bentuk §2 tanpa `amplop_ids`), `amplop` (`null` = semua amplop) |
| `core.karyawan.ruang_terpisah` | alert | `tone`, `judul`, `isi`: catatan pribadi tetap di ruang keluarganya (ADR-P2, P4) |

Catatan dan draf hanya milik karyawan itu sendiri di ruang itu; tidak ada saldo, total ruang, atau catatan anggota lain.
Kartu `refresh_on` memakai event `jatahku:txn-added` dan `jatahku:draf-baru`.

Menyusul bersama Mode Atur (setelah beta): `POST /dashboard/layout/reset`, `dashboard_defaults` (keputusan kajian no. 7).

## 5. Fitur Tambahan / plugin (H1, H2, H3, U1, U2) — **v1 untuk katalog dan siklus (H1, PR plugin/h1-host-inti), titik ekstensi server (H2), `contributions` + persetujuan izin (H3, PR plugin/h3-fitur-tambahan), endpoint plugin + ekspor data (U1, PR plugin/u1-kerangka-buku-usaha), dan tulis pemasukan + field form + izin baru (U2, PR plugin/u2-penjualan-alokasi)**

Pasang, lanjut, jeda, dan copot hanya untuk owner dan admin ruang (ADR-P11). Urutan pemeriksaan: ruang dari **path** → keanggotaan (bukan anggota, ruang tidak ada, id bukan UUID, atau ruang usaha di luar flag `ruang_usaha_users` (R4) → 404 `ruang_tidak_ada`, supaya keberadaan ruang lain tidak bocor) → peran (member → 403 `khusus_admin`) → plugin (`plugin_id` tidak dikenal → 404 `plugin_tidak_ada`). Header `X-Jatahku-Ruang` tidak menentukan ruang tulis. Aturan: `app/plugins/host/siklus.py`.

```jsonc
// GET /plugins → katalog untuk ruang aktif (header). Anggota ruang keluarga boleh melihat; di ruang usaha karyawan
// (peran member) mendapat 403 `khusus_admin` dari gerbang R5 (route di luar `KARYAWAN_BOLEH`).
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
  "ekspor": ["csv", "json"],         // U1: format unduhan data plugin (manifest data_lifecycle.export); [] bila tanpa data
  "butuh": [],                       // id plugin yang harus aktif lebih dulu
  "diperbaiki": false,               // saklar darurat menyala: tampilkan "Sedang diperbaiki"
  "boleh_kelola": true}]             // owner/admin; tombol pasang/jeda/copot hanya tampilan, server tetap memeriksa

// POST /ruang/{ruang_id}/plugins/{plugin_id}/pasang   body opsional {"pengaturan": {}, "izin": ["incomes:read", …]}
// `izin` (H3, aditif): kode izin yang ditampilkan di layar izin saat user menekan Pasang/Pulihkan (urutan bebas,
// maks. 40). Beda dengan izin manifest sekarang → 409 `izin_berubah` dan tidak ada yang tersimpan; tanpa field = klien
// lama, izin manifest dicatat seperti H1. Diperiksa hanya saat pasang baru atau pulihkan, sesudah flag, saklar darurat,
// jenis ruang, `butuh`, dan bentrok; pasang ulang plugin yang sudah terpasang tetap idempoten. Web selalu mengirimnya.
// POST /ruang/{ruang_id}/plugins/{plugin_id}/lanjut | /jeda
// → {"plugin": "buku_usaha", "status": "aktif", "arsip_sampai": null, "izin_diberikan": ["incomes:read", …]}
// POST /ruang/{ruang_id}/plugins/{plugin_id}/copot
// → {"plugin": "buku_usaha", "status": "arsip", "arsip_sampai": "2027-01-30", "izin_diberikan": [],
//    "ekspor": {"csv": "/ruang/<id>/plugins/buku_usaha/ekspor?format=csv", "json": "…?format=json"}}   // null bila tanpa data

// GET /ruang/{ruang_id}/plugins/{plugin_id}/ekspor?format=json|csv   (U1; ruang dari path, owner/admin)
//   Semua baris hidup tabel plugin (`entities`) di ruang itu, boleh saat aktif, terpasang, dijeda, atau arsip (ADR-P15:
//   layar copot selalu menawarkan ekspor). Belum pernah terpasang di ruang ini → 404 `plugin_tidak_aktif`; format di luar
//   manifest → 404 `format_tidak_tersedia`. Setiap unduhan dicatat di `plugin_audit_log` (aksi `ekspor`, jumlah baris).
//   json → attachment {"plugin", "versi", "ruang_id", "dibuat", "data": {"<entitas>": [baris…]}}; nominal Decimal sebagai
//   string, UUID dan waktu sebagai teks; tanpa `household_id` dan `deleted_at`.
//   csv  → ZIP satu berkas `<entitas>.csv` per tabel (BOM UTF-8); sel teks berawalan = + - @ diberi kutip
//   (anti formula-injection PR #136). Nama berkas: jatahku-<plugin>-<YYYYMMDD-HHMM>.json|zip.
```

| Aksi | Dari | Ke | Catatan |
| --- | --- | --- | --- |
| `pasang` | tersedia | aktif, atau terpasang bila manifest punya wizard (`contributes.setup`) | Izin manifest saat itu dicatat sebagai `izin_diberikan` |
| `pasang` | arsip | aktif / terpasang (**pulihkan**) | Baris dan data arsip yang sama kembali; izin disetujui ulang |
| `lanjut` | terpasang, dijeda | aktif | Wizard selesai/dilewati, atau melanjutkan |
| `jeda` | terpasang, aktif | dijeda | Data tetap, kontribusi hilang |
| `copot` | terpasang, aktif, dijeda | arsip (+90 hari) | Data inti tidak pernah ikut terhapus (ADR-P15) |

- **Idempoten:** aksi yang diulang pada status tujuannya menjawab 200 dengan status sekarang dan tidak menambah audit. Perpindahan lain yang tidak sah → 404 `plugin_tidak_aktif` (lanjut/jeda pada plugin yang belum terpasang atau arsip).
- Pasang/pulihkan/lanjut ditolak bila: saklar darurat menyala (503 `plugin_diperbaiki`), jenis ruang tidak didukung (422 `jenis_ruang_tidak_cocok`), plugin di `butuh` belum aktif (409 `butuh_plugin`), atau bentrok dengan plugin terpasang (409 `bentrok_plugin`, dua arah). Pasang dan lanjut juga butuh flag rollout user (selain itu 404 `plugin_tidak_ada`); jeda dan copot tidak, supaya plugin selalu bisa dimatikan. Lanjut/jeda/copot tanpa instalasi menjawab `plugin_tidak_ada` (bukan `plugin_tidak_aktif`) bila plugin di luar flag user, supaya nama plugin yang belum dirilis tidak bisa ditebak.
- Perubahan plugin di satu ruang diserialkan (kunci baris `households` sampai commit), jadi `requires`, `conflicts`, dan `dibutuhkan_plugin_lain` tetap benar walau dua permintaan datang bersamaan.
- Jeda/copot ditolak bila plugin lain di ruang ini masih membutuhkannya (409 `dibutuhkan_plugin_lain`): jeda bila pemakainya terpasang/aktif, copot bila pemakainya belum dicopot.
- `pengaturan` yang tidak kosong → 422 `pengaturan_tidak_sah` sampai titik `settings` (form dari JSON Schema + validasi server) ada di H2/U1. Pilihan kartu Beranda saat pasang (`kartu` di v0) dihapus dari body: klien menambah kartu lewat `PUT /dashboard/layout` (H3).
- `ekspor` (U1): tautan unduhan per format manifest; `null` untuk plugin tanpa `entities`. Web memakai tombol unduh lewat `api` (header Authorization dan ruang), bukan `<a href>`.
- Saklar darurat: `AppSetting plugin_saklar_darurat` = id plugin dipisah koma (tidak peka huruf besar-kecil) (`PUT /admin/settings/plugin_saklar_darurat?value=buku_usaha`). Dibaca setiap permintaan, jadi berlaku seketika; status per ruang tidak berubah.

```jsonc
// GET /plugins/contributions → kontribusi plugin aktif untuk ruang aktif (header) dan user ini (H3, v1)
{
  "plugins": [{"id": "buku_usaha", "nama": "Buku Usaha", "ikon": "book"}],      // plugin aktif: label sumber kartu/menu
  "nav": [{"plugin": "buku_usaha", "grup": "usaha", "label": "Buku Usaha", "route": "/p/buku_usaha", "ikon": "book"}],
  "quick_actions": [{"plugin": "buku_usaha", "key": "buku_usaha.penjualan", "label": "Penjualan", "ikon": "book"}],
  "pages": [{"plugin": "buku_usaha", "route": "/p/buku_usaha", "judul": "Buku Usaha"}],
  "cards": [{"key": "buku_usaha.omzet", "plugin": "buku_usaha", "judul": "Omzet", "shape": "kpi",
             "sizes": ["S", "M"], "size_bawaan": "S", "bawaan": true}],
  "form_fields": [{"plugin": "buku_usaha", "target": "transaction", "key": "kontak_id", "type": "reference", "label": "Pemasok"}]
}
// Tanpa household → semua daftar kosong.
```

- **Sumber.** `siklus.aktif_di_ruang()` (H1): hanya plugin berstatus `active`, tanpa saklar darurat, dengan flag user
  aktif. Plugin dijeda, terpasang tanpa wizard selesai, dicopot, atau dimatikan server → tidak ada kontribusinya sama
  sekali. Isi dari manifest: `nav` hanya halaman yang menyatakan `nav` (`usaha` | `lainnya`), `pages` semua halaman,
  `quick_actions` maks. 2 per plugin, ikon = ikon plugin. `cards` hanya kartu yang punya fungsi kartu di kode server
  (`titik.kartu_ruang`, sumber yang sama dengan tata letak dan data Beranda), jadi kartu yang tercantum selalu bisa
  dimuat. Perubahan bentuk dari v0: `plugins` baru, `cards` berisi objek (bukan kunci saja), `quick_actions` tanpa
  `form` (web membuka form dari `src/plugins/<id>` per `key`).
- **Peran.** Karyawan ruang usaha: 403 `khusus_admin` (route di luar `KARYAWAN_BOLEH`); selama H3 karyawan tidak mendapat
  kontribusi plugin apa pun (keputusan pembukaan sesi H3). Anggota ruang keluarga mendapat kontribusi plugin aktif ruang
  itu. Header ruang lain → 403 `ruang_tidak_diizinkan` (resolver R2).
- **Kartu di katalog Beranda.** `GET /dashboard/cards` kini ikut memuat kartu plugin yang aktif di ruang header (asal =
  id plugin, `refresh_on` kosong; web memuat ulang kartu plugin pada `jatahku:txn-added` dan
  `jatahku:envelope-updated`), tidak pernah untuk karyawan.
- **Web (H3).** Menu grup "Usaha"/"Lainnya" di sidebar dan lembar "Lainnya" (item ke-6 bottom nav HP, hanya bila ada
  `nav`); aksi cepat di menu Catat ▾ (grup per plugin) dan FAB; rute `/p/<id>/*` lazy (pesan bila plugin tidak aktif atau
  halamannya belum ada di bundle); kartu plugin dari `src/plugins/<id>/cards.js` atau renderer bentuk deklaratif;
  halaman Fitur Tambahan `/fitur-tambahan` (katalog, layar izin, pasang, lanjut, jeda, copot, pulihkan, tawaran kartu
  lewat `PUT /dashboard/layout`). Aksi `route` kartu dan saran AI Advisor plugin (`payload.to`) membuka `/p/<id>…`.

### Titik ekstensi server — **v1 (H2, PR plugin/h2-plugin-context)**

Plugin menyumbang lewat kode di `app/plugins/<id>/__init__.py` (`plugin = Plugin("<id>")` dari `app.plugins.sdk`), dicocokkan dengan manifest saat start dan di CI. Izin per jenis fungsi: kartu, cek, aturan advisor, perintah bot, dan field form hanya izin baca; `notifications:send` hanya untuk job. Data yang dibaca plugin mengikuti kontrak visibilitas: amplop pribadi anggota lain tidak terbaca, deskripsi transaksi privat tersamar, dan di ruang keluarga plugin hanya membaca pemasukan milik viewer (seperti `GET /incomes/`; job tanpa user tidak membaca pemasukan ruang keluarga). Tidak ada endpoint baru; endpoint inti yang berubah perilaku:

- **Kartu (`cards`) di `/dashboard/*`.** `GET`/`PUT /dashboard/layout`, `POST /dashboard/data`, dan `GET /dashboard/data/{id}` mengenal kartu plugin (`<id>.<nama>`) yang **aktif di ruang header untuk user itu** (`siklus.aktif_di_ruang`). Kartu plugin yang tidak aktif (dijeda, dicopot, saklar darurat, flag dicabut) diperlakukan seperti kartu yang definisinya hilang: diparkir di `GET /dashboard/layout`, `kartu_tidak_dikenal` di `PUT` dan di galat per kartu. Data kartu plugin berbentuk deklaratif (§4: `kpi`, `progress`, `list`, `table`, `series`, `alert`, tidak pernah `inti`) dan diperiksa server sebelum dikirim: field asing, nominal float, daftar lebih panjang dari batas, atau aksi selain `route` ke `/p/<id>…` → galat kartu `gagal_memuat`. Nominal `Decimal` dikirim sebagai string desimal. Sejak H3 `GET /dashboard/cards` juga memuat kartu plugin aktif (§5).
- **AI Advisor (`advisor_rules`).** Saran plugin masuk kartu AI Advisor (`GET /advisor/dashboard`, `advisor.items`/`sisa`) dengan bentuk item yang sama, `aturan` berupa kode plugin (mis. `BU-01`), aksi hanya `{"kind": "route", "label", "payload": {"to": "/p/<id>…"}}`. Maksimal 1 saran per plugin di `items` (`daftar_per_plugin`), tidak pernah chip KPI inti, tidak untuk karyawan. Dismiss memakai `kunci` yang sama seperti saran inti.
- **Perintah bot (`bot_commands`).** Telegram dan chat web: perintah baca plugin dijawab satu pesan per ruang yang memasang plugin itu, berawalan `[Nama ruang]`. `audience: admin` hanya owner/admin (karyawan: "Laporan <ruang> hanya untuk admin ruang."); tanpa ruang yang aktif: "Perintah ini belum tersedia di ruangmu." Teks polos, tanpa tombol.
- **Notifikasi (`notifications`).** Lewat `ctx.notify`, **hanya dari job** (konteks tanpa user; review keamanan #186): lonceng (`type` = `system`) dan Telegram, judul berawalan `[Nama ruang]`, `link` hanya `/p/<id>…`; hanya owner/admin ruang yang plugin-nya aktif untuk mereka; tidak pada jam tenang 21.00–07.00 waktu penerima; maksimal 2 per plugin per penerima per hari dan 1 per `kunci`. Tidak ada preferensi per jenis notifikasi sampai U6.
- **Kamus Catat cepat (`nlp_kamus`).** Saran amplop (`POST /transactions/suggest-envelope(s)`, Kotak Struk) di ruang yang memasang plugin mencoba kamus plugin sesudah kata user dan kamus ruang (R7), sebelum kamus kategori inti (`sumber.jenis = kamus_plugin`, §3). Tidak dipakai di ruang lain.
- **Field form (`form_fields`).** Validasi server `titik.periksa_field` untuk body `{"<plugin_id>": {"<key>": nilai}}`; field di luar plugin aktif atau manifest → 422 `field_tidak_sah`. Belum disambungkan ke body transaksi/pemasukan (U2).
- **Job (`jobs`)** dan **cek (`checks`)**: tanpa permukaan API selain `peringatan` di §0.

### Endpoint plugin `/p/<plugin_id>/…` — **v1 (U1, PR plugin/u1-kerangka-buku-usaha)**

Plugin yang punya halaman butuh data: manifest `contributes.routes` (`[{"method": "GET", "path": "/kontak/{id}"}]`,
maks. 30) dan fungsi `@plugin.rute("GET", "/kontak/{id}")` → `async (ctx, Permintaan) -> data JSON | Jawaban(data, status)`.
Host melayani semuanya lewat satu route `/{plugin_id}/{path}` di awalan `/p` (`app/api/routes/plugins.py` →
`titik.jalankan_rute`):

- **Ruang dari header** (`ruang_aktif`), seperti baca; tanpa household → 404 `ruang_tidak_ada`. Karyawan ruang usaha
  → 403 `khusus_admin` (gerbang R5, route di luar `KARYAWAN_BOLEH`); anggota ruang keluarga boleh (bila plugin
  rumah tangga ada). `ruang_id` di body/query diabaikan: plugin hanya mendapat `ctx.ruang_id` dari host.
- **Urutan:** plugin dikenal (404 `plugin_tidak_ada`) → aktif di ruang ini untuk user ini (404 `plugin_tidak_aktif`:
  dijeda, dicopot, saklar darurat, atau flag, tidak dibedakan; status `terpasang` membuka rute **GET saja**, supaya
  wizard pasang bisa membaca pengaturannya) → rute cocok (404 `rute_tidak_ada`) → fungsi plugin.
- **Body** JSON ≤ 64 KB (413 `body_terlalu_besar`, 422 `body_bukan_json`); query ≤ 20 parameter, nilai pertama ≤ 200
  huruf (422 `query_terlalu_banyak`). `Permintaan`: `metode`, `path` (parameter pola), `query`, `body`.
- **Jawaban:** status 200 (bawaan) atau `Jawaban(data, 201|202|204)`; nilai dirapikan host: `Decimal` → string
  desimal, UUID/tanggal → teks, float ditolak (500 `plugin_gagal`).
- **Galat plugin:** `GalatRute(status 4xx, kode, detail)` apa adanya (`kode` huruf kecil ≤ 40, `detail` ≤ 300);
  `NilaiTidakSah("…")` → 422 `nilai_tidak_sah`; izin ditolak → 403 `khusus_admin` / `tanpa_izin`; galat lain → 500
  `plugin_gagal` (jejak di log, tidak pernah detail internal).
- **Data plugin** hanya lewat `ctx.data("<entitas>")` (tabel `entities` manifest, `app/plugins/host/data.py`): `cari`,
  `ambil`, `hitung`, `tambah`, `ubah`, `hapus` (lunak). Selalu disaring ruang konteks dan `deleted_at IS NULL`; baris
  ruang lain = tidak ada. Tulis hanya dari rute non-GET; kartu, cek, saran, bot, field form, dan job hanya membaca
  (`hanya_baca`). Setiap tulis dicatat di `plugin_audit_log` (`data:tambah|ubah|hapus`, tabel + id + nama kolom,
  tanpa nilai) dalam transaksi yang sama. Kolom `id`, `household_id`, `created_by`, waktu, `deleted_at` milik host.
- Izin data inti di rute hanya baca (`IZIN_PER_JENIS["rute"]`), kecuali **`incomes:write` (U2)**: `ctx.catat_pemasukan(
  jumlah=, keterangan=, tanggal=, pembagian=[(envelope_id, jumlah)])` (`app/plugins/host/inti.py`) hanya dari rute
  non-GET, oleh owner/admin (karyawan `khusus_admin`), dengan user pemicu. Amplop harus amplop aktif ruang konteks yang
  terlihat viewer; pembagian harus persis sama dengan jumlah (tanpa sisa ke Tabungan); tanggal ≤ hari ini dan ≥ setahun
  ke belakang (zona waktu user); salah → `NilaiTidakSah` (422 `nilai_tidak_sah`). Lewat jalur pemasukan inti
  (`catat_pemasukan(commit=False)`, `kind = pemasukan`), jadi pemasukan, pembagian, tulisan `ctx.data()`, dan audit
  `inti:pemasukan` (id + jumlah amplop, tanpa nominal) masuk dalam **satu commit** route `/p`; galat di tengah = tidak
  ada apa pun. Notifikasi goal dijalankan sesudah commit (`app/services/setelah_commit.py`). Tidak ada metode tulis
  inti lain.

### Field form Fitur Tambahan di form inti — **v1 (U2, PR plugin/u2-penjualan-alokasi)**

- Manifest `form_fields` (Plugin API 1.3): `{target: transaction|income|envelope, key, type: text|number|select|reference,
  label, entity?, options?}`; `select` wajib `options` (≤ 30, unik, 1–40 huruf; jenis lain dilarang), `reference` wajib
  `entity`. `GET /plugins/contributions` `form_fields[]` mendapat `options` untuk `select` (aditif).
- `POST /transactions/` (aditif) `tambahan: {"<plugin_id>": {"<key>": nilai}}`: diperiksa sebelum apa pun disimpan
  (`titik.periksa_field`: plugin aktif di ruang amplop untuk user itu, field ada di manifest untuk `transaction`, tipe
  bawaan, `options`, lalu `field_form` plugin). Salah, karyawan, atau ruang tanpa plugin itu → 422 `field_tidak_sah`
  tanpa transaksi. Nilai bersih disimpan plugin pemiliknya (`@plugin.simpan_field("transaction")`, `async (ctx,
  target_id, nilai)`, hanya `ctx.data()` tabel sendiri) sesudah transaksi di-flush dan sebelum commit: gagal → 422
  `field_tidak_sah` (`NilaiTidakSah`) atau 500 `plugin_gagal`, transaksi batal dan kunci `client_ref` dilepas. Isian yang
  semuanya `null` tidak memanggil plugin. Belum di `/transactions/batch` (antrean offline mengirim tanpa `tambahan`),
  persetujuan draf, Catat cepat, atau ubah transaksi.

### Izin baru untuk instalasi yang sudah ada — **v1 (U2)**

- Katalog (`GET /plugins`) dan semua jawaban siklus (`ke_api`) mendapat `izin_baru: ["incomes:write"]` (aditif): izin
  manifest versi sekarang yang belum ada di `granted_permissions` instalasi itu (kosong untuk yang belum/sudah tidak
  terpasang). Izin baru **tidak pernah diberikan diam-diam**: fungsi yang memakainya ditolak 403 `tanpa_izin`.
- `POST /ruang/{id}/plugins/{plugin_id}/izin {"izin": [semua kode izin yang dilihat]}` (owner/admin, flag rollout user,
  instalasi terpasang/aktif/dijeda; status tidak berubah) → jawaban siklus. Daftar beda dengan manifest → 409
  `izin_berubah`; tanpa `izin` → 422; belum terpasang atau arsip → 404 `plugin_tidak_aktif`. Diaudit `izin` (dari, ke,
  versi). Izin yang dibuang manifest ikut hilang.

## 6. Buku Usaha (U1–U4) — **v1 untuk pengaturan dan Kontak (U1, PR plugin/u1-kerangka-buku-usaha)**

Semua di bawah `/p/buku_usaha/` (endpoint plugin §5: ruang dari header, owner/admin); 404 `plugin_tidak_aktif` bila
Buku Usaha tidak aktif di ruang itu. Alokasi, penjualan, dan field pengeluaran v1 sejak U2; U3–U4 masih v0. Manifest
0.2.0: izin `envelopes:read`, `incomes:write` (instalasi U1 menyetujuinya lewat `POST …/izin`).

```jsonc
// Pengaturan (U1) — dipakai wizard pasang (boleh saat `terpasang`) dan kepala halaman
// GET /p/buku_usaha/pengaturan → {"ruang": "Dapur Nusa",
//   "amplop_bawaan": [{"nama": "Bahan", "emoji": "🥬", "tujuan": "expense", "keterangan": "…", "ada": true, "envelope_id": "…"},
//                     … Operasional (expense), Prive, Laba ditahan, Pajak (saving)],   // `ada` = amplop bersama bernama sama sudah ada
//   "jumlah_kontak": {"pelanggan": 3, "pemasok": 2}}
//   Amplop bawaan dibuat KLIEN lewat `POST /envelopes/` inti atas nama user (plugin tidak menulis data inti di U1):
//   expense dengan `budget_amount` yang diisi user (aturan inti: > 0), saving tanpa anggaran. Lalu `lanjut` → aktif.

// Kontak (U1)
// GET    /p/buku_usaha/kontak?peran=pelanggan|pemasok&q=   → [{"id", "nama", "peran", "telepon", "catatan", "dibuat", "diubah"}]
//        urut nama; `q` dicari di nama dan telepon (tanpa peka huruf); maks. 200; `peran` lain → 422 `peran_tidak_dikenal`
// POST   /p/buku_usaha/kontak {"nama", "peran", "telepon"?, "catatan"?} → 201 {kontak}
//        nama 1–120 (spasi dirapikan), peran pelanggan|pemasok, telepon 5–29 angka/spasi/./- (boleh +), catatan ≤ 500;
//        salah → 422 `nilai_tidak_sah`; nama+peran sudah ada (tanpa peka huruf) → 409 `kontak_ganda`
// PATCH  /p/buku_usaha/kontak/{id} {kolom yang berubah} → {kontak}; DELETE /p/buku_usaha/kontak/{id} → 204 (hapus lunak;
//        dibuang permanen sesudah 30 hari oleh job `plugin_jobs`)
//        kontak ruang lain atau sudah dihapus → 404 `kontak_tidak_ada`
// `total_bulan_ini` (v0) menyusul bersama `income_meta` dan `metrics.py` (U2–U3), aditif.

// Alokasi omzet (U2) — owner, admin — v1
// GET /p/buku_usaha/alokasi → {"aturan": [{"envelope_id", "nama", "emoji", "persen": "45.00"}],   // urut persen turun
//   "siap": true,          // ada aturan, semua amplopnya masih aktif dan bersama, total 100 (syarat mencatat penjualan)
//   "tersimpan": true, "saran": [],   // belum tersimpan: saran 45/30/15/9/1 bila kelima amplop bawaan ada, selain itu []
//   "amplop": [{"envelope_id", "nama", "emoji", "tujuan"}]}   // amplop bersama aktif ruang ini (pilihan editor)
// PUT /p/buku_usaha/alokasi {"aturan": [{"envelope_id", "persen"}]} → bentuk GET (tanpa `amplop`)
//   1–10 baris, persen 0 < p ≤ 100 maks. 2 desimal (angka atau teks), amplop tidak ganda → selain itu 422 nilai_tidak_sah;
//   total ≠ 100 → 422 alokasi_bukan_100; amplop pribadi / ruang lain / tidak aktif → 422 amplop_tidak_ada.
//   Mengganti seluruh aturan (yang tidak dikirim dihapus lunak).

// Penjualan dan jenis pemasukan (U2) — v1. Jenis: penjualan (dibagi menurut alokasi; hanya ini omzet, U3) | modal |
// pinjaman | lain (satu amplop: `envelope_id`, bawaan amplop bernama "Laba ditahan").
// POST /p/buku_usaha/penjualan/pratinjau {"jumlah", "jenis"?, "envelope_id"?} → {"jenis", "jumlah",
//   "pembagian": [{"envelope_id", "nama", "emoji", "persen": "45.00" | null, "jumlah": "450001.00"}]}   // tidak menulis
// POST /p/buku_usaha/penjualan {"jumlah", "jenis"?, "envelope_id"?, "tanggal"? (YYYY-MM-DD), "kontak_id"?, "keterangan"?}
//   → 201 {"income_id", "jenis", "jumlah", "tanggal", "keterangan", "kontak": {"id", "nama"} | null, "pembagian": [...]}
//   Pemasukan inti (`kind = pemasukan`) lewat `ctx.catat_pemasukan` + `income_meta` (jenis, pelanggan) dalam satu commit.
//   Pembagian: tiap bagian dibulatkan ke bawah per rupiah, sisa (termasuk sen) ke persen terbesar; total selalu persis.
//   Galat: jumlah ≤ 0 / bukan angka, tanggal sesudah hari ini atau > 1 tahun lalu, kolom asing, pelanggan untuk jenis
//   selain penjualan, `envelope_id` untuk penjualan → 422 nilai_tidak_sah; jenis lain → 422 jenis_tidak_dikenal;
//   aturan belum siap → 422 alokasi_belum_diatur; amplop jenis lain tidak ada → 422 amplop_tidak_ada / amplop_wajib;
//   kontak bukan pelanggan ruang ini → 422 kontak_tidak_ada; izin `incomes:write` belum disetujui → 403 tanpa_izin.
//   Keterangan kosong → label jenis (+ " · <pelanggan>"). Tanpa `client_ref` (U2: tombol dikunci selama mengirim, sama
//   dengan /incomes owner/admin); penjualan karyawan tetap lewat /incomes inti (tanpa meta sampai U3/U5).

// Field pengeluaran (U2) — v1, `tambahan` di `POST /transactions/` (§5 "Field form"):
//   {"buku_usaha": {"pemasok": "<id kontak pemasok ruang ini>", "akun": "Bahan baku" | "Gaji" | "Sewa" |
//    "Listrik & air" | "Transport" | "Pemasaran" | "Peralatan" | "Lain-lain"}} → baris `txn_meta` (kontak_id, akun)

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
| `lintas_ruang` | 400 | Satu permintaan tulis menyentuh dua ruang (R3); prive (R8) adalah satu-satunya pengecualian |
| `bukan_ruang_usaha` | 400 | Prive dari amplop yang bukan ruang usaha (R8) |
| `prive_hanya_pemilik` | 403 | Admin atau karyawan mencatat prive (R8) |
| `tanpa_ruang_keluarga` | 400 | Pemilik usaha belum punya ruang keluarga sebagai tujuan prive (R8) |
| `ruang_usaha_belum_dibuka` | 403 | `POST /ruang` oleh user di luar flag `ruang_usaha_users` (R4) |
| `batas_ruang_usaha` | 409 | `POST /ruang` saat user sudah memiliki 3 ruang usaha (R4) |
| `di_luar_jam_kerja` | 403 | Ruang usaha dibuka di luar jam kerja anggota; body juga berisi `buka_lagi` (R5) |
| `khusus_admin` | 403 / per kartu | Karyawan di ruang usaha memakai route di luar `KARYAWAN_BOLEH`, atau aksi admin lain (mengubah owner) (R5); member mengatur Fitur Tambahan (H1); kartu umum di `POST /dashboard/data` untuk karyawan (R6) |
| `nominal_tidak_sah` | per baris | Baris antrean offline bernominal nol atau negatif (R5; jalur tunggal dan pemasukan: 422 validasi) |
| `amplop_tidak_diizinkan` | 403 | Amplop tidak termasuk batasan anggota |
| `jenis_tidak_diizinkan` | 403 | Jenis catatan tidak termasuk batasan anggota |
| `perlu_foto_nota` | 422 | Nominal di atas `foto_nota_di_atas` tanpa foto |
| `perlu_persetujuan` | 202 | Di atas `batas_nominal`; draf dibuat, belum menjadi transaksi |
| `client_ref_bentrok` | 409 / per baris | `client_ref` sudah dipakai catatan lain (ruang, jenis, atau amplop berbeda); tidak ada yang dicatat (R7, review keamanan #191) |
| `jendela_ubah_lewat` | 403 | Mengubah atau menghapus catatan di luar jendela |
| `butuh_paket_usaha` | 402 | Ruang usaha tanpa hak Paket Usaha (ADR-P13) |
| `plugin_tidak_aktif` | 404 | Plugin tidak terpasang atau dijeda di ruang ini |
| `plugin_tidak_ada` | 404 | `plugin_id` tidak dikenal, atau flag rollout user belum aktif saat memasang (H1) |
| `plugin_diperbaiki` | 503 | Saklar darurat menyala: pasang dan lanjut ditolak, jeda dan copot tetap boleh (H1) |
| `jenis_ruang_tidak_cocok` | 422 | Plugin tidak mendukung jenis ruang ini (H1) |
| `butuh_plugin` | 409 | Plugin yang dibutuhkan belum aktif di ruang ini (H1) |
| `bentrok_plugin` | 409 | Bentrok dengan plugin yang terpasang (H1) |
| `dibutuhkan_plugin_lain` | 409 | Plugin lain di ruang ini masih membutuhkannya (H1) |
| `izin_berubah` | 409 | Daftar izin yang disetujui di layar izin (`pasang` body `izin`) beda dengan manifest sekarang; muat ulang lalu setujui lagi (H3) |
| `rute_tidak_ada` | 404 | Endpoint plugin tidak ada di manifest `routes` atau tidak punya fungsi (U1) |
| `nilai_tidak_sah` | 422 | Isian endpoint plugin ditolak plugin atau host (`NilaiTidakSah`; U1) |
| `tanpa_izin` | 403 | Fungsi plugin memakai izin yang tidak diberikan, termasuk izin baru yang belum disetujui (`POST …/izin`, U2) (U1; karyawan tetap `khusus_admin`) |
| `plugin_gagal` | 500 | Fungsi plugin melempar galat atau mengembalikan nilai yang tidak sah; jejak di log (U1) |
| `body_terlalu_besar`, `body_bukan_json`, `query_terlalu_banyak` | 413 / 422 / 422 | Batas permintaan endpoint plugin (U1) |
| `format_tidak_tersedia` | 404 | Format ekspor data plugin di luar manifest (U1) |
| `kontak_ganda`, `kontak_tidak_ada`, `peran_tidak_dikenal` | 409 / 404 / 422 | Kontak Buku Usaha (U1, §6) |
| `alokasi_belum_diatur`, `amplop_tidak_ada`, `amplop_wajib`, `jenis_tidak_dikenal` | 422 | Penjualan dan alokasi omzet Buku Usaha (U2, §6) |
| `izin_wajib` | 422 | `POST …/izin` tanpa daftar izin (U2, §5) |
| `versi_beda` | 409 | `if_version` tata letak sudah usang |
| `instans_hilang` | 422 | `PUT /dashboard/layout` kehilangan instans tanpa `removed` |
| `ruang_tidak_ada` | 404 | User belum punya household (`/dashboard/*`), atau ruang di path bukan ruang user (`/ruang/{id}/plugins/*`, H1) |
| `kartu_tidak_dikenal` | 422 / per kartu | Kartu tidak terdaftar (`PUT /dashboard/layout`; di `POST /dashboard/data` sebagai galat kartu) |
| `ukuran_tidak_sah`, `kartu_ganda`, `instans_tidak_sah`, `terlalu_banyak` | 422 | Validasi tata letak atau permintaan data (§4) |
| `field_tidak_sah` | 422 | `tambahan` di `POST /transactions/`: field tidak dikenal, di luar plugin aktif, karyawan, pilihan di luar `options`, atau ditolak/gagal disimpan plugin (H2; dipakai sejak U2) |
| `pengaturan_tidak_sah` | 422 / per kartu | Pengaturan instans tidak cocok dengan skema kartu; pengaturan plugin saat pasang (H1, sampai titik `settings`) |
| `periode_tidak_dikenal` | 422 | `periode` bukan `period_start` dari `GET /analytics/periods` |
| `instans_tidak_ada` | 404 | `GET /dashboard/data/{id}` untuk instans yang tidak ada di tata letak user |
| `gagal_memuat` | per kartu | Sumber data kartu gagal dimuat; kartu lain tetap terisi |
| `alokasi_bukan_100` | 422 | Total persen alokasi omzet ≠ 100 (U2, `PUT /p/buku_usaha/alokasi`) |
| `alokasi_tidak_penuh` | 422 | Penjualan karyawan yang alokasinya tidak sama dengan nominal (sisa akan jatuh ke amplop di luar izinnya) (R5) |

Batasan member juga berlaku di `POST /transactions/batch` (antrean offline) dan untuk kiriman ulang dengan `client_ref` yang sama: item yang ditolak kembali dengan `kode` di hasil per item, dan tetap disimpan klien (`AGENTS.md`, "Service Worker", antrean offline).
