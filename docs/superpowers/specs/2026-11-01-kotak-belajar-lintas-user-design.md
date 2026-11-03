# Kotak Struk: belajar lintas user dan menyalakan saklar `receipt_inbox` — desain

**Status:** disetujui pemilik produk 1 Nov 2026 (keputusan tambahan di §12). Melanjutkan `claude/bagikan-ke-jatahku-desain.md`
(Bagian A tayang 28 Okt, Bagian B tayang 29 Okt, kalibrasi A14 putaran 1–3 tayang 31 Okt, PR #135).
Setelah disetujui: rencana tugas → implementasi per tugas dengan review (alur yang sama seperti Bagian A/B).

## Keputusan pemilik produk (1 Nov 2026)
1. **Peluncuran:** saklar `receipt_inbox` dinyalakan untuk **semua user**, tanpa beta.
2. **Profil aplikasi baru:** aturan yang dipelajari **menunggu persetujuan pemilik di Admin** sebelum dipakai.
3. **"Dibatalkan" / "Ditolak"** diblokir seperti "Gagal".
4. (Latar) Sampel bukti dari banyak bank sulit didapat; gerbang korpus §7c (≥95% pada 12 aplikasi) **diganti**
   dengan: kalibrasi yang ada + belajar dari koreksi user + pemantauan di Admin. Korpus tetap dipelihara dari donasi
   contoh (tahap 2).

## Ringkasan
Jatahku sudah menjamin **tidak ada yang tercatat tanpa konfirmasi user** (kartu bukti, tombol amplop di bot,
nominal kurang yakin ditanya dulu, status gagal/pending diblokir/diperingatkan). Karena itu saklar aman dinyalakan
sebelum semua aplikasi bank punya sampel: bukti dari aplikasi yang belum dikenal jatuh ke `tidak_dikenali` dengan
nominal tebakan yang dikonfirmasi user. Yang ditambahkan desain ini:

- **Belajar lintas user dari koreksi.** Saat user mengoreksi hasil baca (nominal, nama pihak, tanggal, "bukan
  pengeluaran"), sistem mencatat **struktur**-nya (label baris mana yang memuat nilai yang benar untuk aplikasi itu),
  bukan isinya. Setelah cukup banyak user berbeda mengoreksi dengan pola yang sama, aturannya muncul di Admin;
  pemilik menyetujui; pembaca memakainya untuk semua user.
- **Kosakata status:** "dibatalkan", "ditolak", "batal", "rejected", "cancelled" → `gagal`.
- **Menutup titik yang wajib sebelum saklar** (review akhir Bagian A: N2, N4, C2, C3, sisa N1), paragraf privasi
  (`privacy.html`, sisa A68), lalu urutan menyalakan saklar yang sudah ada di `docs/kotak-struk.md`.

Mekanisme belajar lintas user **sudah ada** untuk struk belanja (`receipt_total_labels`, `receipt_merchant_aliases`,
`receipt_learn_votes`: satu suara per user, dipakai setelah ≥ 2 user berbeda). Desain ini memakai pola yang sama
untuk bukti bayar, dengan satu pengetat tambahan: **persetujuan pemilik** (ambang tetap **2 user berbeda**).

## 1. Prinsip
1. Koreksi user tidak pernah mengubah hasil user lain secara langsung; hanya lewat aturan yang disetujui.
2. Yang dibagikan lintas user hanya **struktur**: teks label (digit disamarkan), jenis nilai, kata logo aplikasi.
   Nama orang, nomor rekening/HP/referensi, dan nominal tidak pernah masuk tabel belajar.
3. Aturan belajar hanya mengubah **dari mana** nilai dibaca (label → nominal/nama/tanggal) dan penanda aplikasi.
   Aturan **tidak pernah** melonggarkan blokir status gagal/pending, cek arah uang, atau cek duplikat.
4. Setiap aturan punya jejak: jumlah user dan rumah tangga pendukung, kapan, siapa yang menyetujui; bisa dicabut.
5. Semua yang dipelajari tetap melewati jalur yang ada: `check_recordable`, klaim atomik, `after_recorded`.

## 2. Apa yang dipelajari (jenis aturan)
| Jenis (`kind`) | Kunci | Nilai | Dipelajari dari |
|---|---|---|---|
| `label_total` | `issuer` | teks label baris (mis. "Total Bayar", "Jumlah Pembayaran") | user mengubah nominal di kartu/bot dan nominal itu ada di baris berlabel lain |
| `label_pihak` | `issuer` | teks label (mis. "Ditransfer ke", "Nama Merchant") | user mengganti nama pihak dan nama itu (HMAC) ada di baris berlabel lain |
| `label_tanggal` | `issuer` | teks label (mis. "Waktu Selesai") | user memilih tanggal lain yang tercetak di baris berlabel |
| `logo` | `issuer` | kata logo (mis. "BYOND", "wondr") | bukti `tidak_dikenali` yang user beri nama aplikasinya (tahap 2, lihat §10) |
| `arah` | `issuer` + label | `top_up` / `masuk` / `antar_rekening_sendiri` | user menekan "Bukan pengeluaran" dan memilih alasannya; label judul bukti itu (mis. "Top Up GoPay") dicatat |

`issuer` = profil aplikasi yang dikenali; bukti `tidak_dikenali` memakai kata logo baris pertama sebagai kunci
sementara (`logo:<kata>`), supaya aplikasi baru pun bisa belajar sebelum punya profil.

Yang **tidak** dipelajari lintas user: kata status baru (ditambah manual lewat kalibrasi, karena salah belajar di sini
berarti bukti gagal bisa tercatat), nomor/ID apa pun, nama merchant (itu urusan peta merchant per rumah tangga yang
sudah ada).

## 3. Data
### 3a. Kerangka tata letak per item (`document.layout`)
Teks OCR bukti bayar **tidak** disimpan (privasi). Supaya koreksi yang datang belakangan bisa dipetakan ke baris
asalnya, worker menyimpan kerangka yang aman di `document.layout` (JSON, maksimal 60 baris):

```
{ "i": 7, "label": "Jumlah Kirim Uang", "kind": "nominal", "amount": 10000 }
{ "i": 4, "label": "Ditransfer ke",     "kind": "nama",    "h": "<HMAC nama ternormalisasi>" }
{ "i": 9, "label": "Tanggal",           "kind": "tanggal", "date": "2026-10-31" }
{ "i": 2, "label": null,                "kind": "judul",   "words": ["top","up"] }
```
- `label`: teks sebelum nilai, maksimal 40 karakter, **semua digit diganti `#`**; `kind` ∈ nominal | nama | tanggal |
  judul | lain. Nominal dan tanggal disimpan apa adanya (bukan data pribadi; totalnya memang sudah disimpan).
  Nama hanya sebagai HMAC (`KOTAK_HMAC_KEY`, sama seperti `ref_hash`), jadi bisa dicocokkan dengan nama yang
  diketik user tanpa menyimpan namanya. Baris nomor rekening/HP/referensi **tidak** masuk kerangka sama sekali.
- `judul`: kata-kata baris judul (≤ 6 kata, tanpa digit) untuk aturan `arah`.
- Umur: dihapus (`layout = null`) oleh job pemeliharaan untuk item yang sudah selesai (`tercatat`/`dilewati`) lebih
  dari 24 jam, dan bersama `kedaluwarsa` — sama seperti `ocr_lines` struk belanja hari ini.

### 3b. Tabel baru (migrasi)
- `proof_rule_votes(kind, rule_key, value, user_id, household_id, created_at)`, PK (kind, rule_key, value, user_id):
  satu suara per user per aturan.
- `proof_rules(id, kind, rule_key, value, users, households, status, created_at, decided_at, decided_by, note)`,
  `status` ∈ `menunggu` | `disetujui` | `ditolak` | `dicabut`; unik (kind, rule_key, value).
  `users`/`households` = jumlah pendukung berbeda, diperbarui tiap suara.

Ambang: aturan masuk `menunggu` (tampil di Admin) setelah **≥ 2 user berbeda** (keputusan pemilik; sama dengan
struk belanja). Di bawah itu hanya suara. Jumlah rumah tangga tetap dicatat dan ditampilkan di Admin. Aturan dengan 1 user pun tetap terlihat di Admin di tab "Suara" (angka saja), supaya pemilik bisa melihat
aplikasi mana yang sering dikoreksi.

## 4. Alur: koreksi → suara → aturan → persetujuan
1. User menyimpan bukti (web: kartu `/bagikan` atau baris form Catat; bot: tombol amplop / "Nominal salah" /
   "Bukan pengeluaran"). Server sudah tahu item dan nilai akhirnya (`after_recorded`, `skip_item`).
2. `learn_from_correction(db, item, final)` membandingkan hasil baca dengan nilai akhir:
   - nominal berbeda → cari di `layout` baris `nominal` dengan `amount == final.amount` → suara `label_total`
     (`issuer`, label baris itu). Tidak ada baris yang cocok → tidak ada suara (user mengetik nominal yang tidak
     tercetak; tidak bisa dipelajari).
   - nama pihak diganti → HMAC(nama baru ternormalisasi) cocok dengan baris `nama` → suara `label_pihak`.
   - tanggal dipilih berbeda dari tanggal bukti → cocok dengan baris `tanggal` → suara `label_tanggal`.
   - "Bukan pengeluaran" dengan alasan top-up / uang masuk / rekening sendiri → suara `arah` dengan kata judul.
   Satu simpanan menghasilkan paling banyak satu suara per jenis; satu user satu suara per aturan (PK).
3. Setelah tiap suara, `proof_rules` diperbarui (users, households). Mencapai ambang → `status = menunggu`, dan
   pemilik mendapat notifikasi Admin (lencana jumlah aturan menunggu; tanpa email/Telegram di tahap 1).
4. Pemilik membuka Admin → Scan Struk → "Aturan belajar": tiap aturan menampilkan jenis, aplikasi, label, jumlah
   user/rumah tangga, contoh **sintetis** (label + "Rp##.###"), tombol **Setujui** / **Tolak** (+ catatan).
5. `disetujui` → pembaca memakainya (§5) mulai permintaan berikutnya (cache aturan 5 menit di proses API).
   `ditolak` → suara tetap tersimpan, aturan tidak muncul lagi kecuali pemilik membukanya. `dicabut` → seperti ditolak,
   untuk aturan yang pernah disetujui.

## 5. Pembaca memakai aturan
- `labels_for(issuer)` (profil aplikasi) ditambah sinonim dari `proof_rules` yang disetujui: `label_total` →
  daftar label total, `label_pihak` → label penerima/merchant, `label_tanggal` → label tanggal. Aturan belajar
  **didahulukan** dari label umum untuk aplikasi itu (itulah gunanya), tetapi label bawaan profil tetap dipakai bila
  aturan tidak menemukan nilai.
- `logo` (tahap 2) menambah kata pengenal aplikasi ke profil.
- `arah`: bila judul bukti memuat kata aturan → `flow` sesuai aturan, sebelum cek "mirip user". Tetap hanya
  menghasilkan peringatan "bukan pengeluaran?", tidak pernah mencatat otomatis.
- Keyakinan nilai dari aturan yang disetujui = `tinggi` (kalau `sedang`, bot akan bertanya setiap kali dan tujuan
  belajarnya hilang). Nilai yang tidak lolos cek silang (nominal + biaya ≠ total, dll.) tetap mendapat peringatan.
- Pembaca memuat aturan sekali per permintaan baca (`ParseContext.rules`), dari cache; tanpa aturan = perilaku hari ini.
  Tes pembaca dan alat korpus berjalan **tanpa** aturan (deterministik); ada tes terpisah yang menyuntik aturan.

## 6. Admin
- Scan Struk card: bagian "Aturan belajar" — ringkasan (menunggu / disetujui / ditolak) + daftar aturan menunggu
  dengan tombol; tab "Semua" untuk mencabut yang disetujui; tab "Suara" (angka per aplikasi dan jenis).
- Metrik yang sudah ada (`by_issuer` tercatat/dikoreksi, `% dikoreksi`) menjadi alat pantau: aplikasi dengan
  `% dikoreksi` tinggi dan belum ada aturan = kandidat kalibrasi manual.
- API: `GET /admin/kotak/rules?status=`, `POST /admin/kotak/rules/{id}/setujui|tolak|cabut` (admin saja, additive).

## 7. Kosakata status
"dibatalkan", "ditolak", "batal" (sebagai kata status, bukan tombol "Batal"), "rejected", "cancelled"/"canceled",
"void" (hanya pada judul status / nilai label status, bukan di baris barang) → `gagal`. Mengikuti aturan yang sudah
ada untuk kata gagal (judul status, label status pembayaran, 4 baris pertama); kaki bersyarat ("Jika transaksi
dibatalkan…") tidak dihitung. Sapuan: tidak ada struk belanja yang jadi terblokir.

## 8. Privasi
- Kerangka `layout` tidak memuat nama (hanya HMAC), nomor, atau teks bebas; label disamarkan digitnya; dihapus
  24 jam setelah item selesai. Tabel aturan hanya memuat label dan kata logo/judul.
- Data belajar dihapus bersama akun (`proof_rule_votes.user_id` ON DELETE CASCADE; hitungan aturan dihitung ulang).
- Paragraf untuk `privacy.html` (sisa A68; file ada di server, bukan repo):
  > **Belajar dari koreksi.** Saat Anda mengoreksi hasil pembacaan bukti bayar (nominal, nama penerima, tanggal, atau
  > menandai "bukan pengeluaran"), Jatahku mencatat *struktur* bukti dari aplikasi tersebut — misalnya baris berlabel
  > "Total Bayar" yang memuat nominal — agar pembacaan bukti dari aplikasi yang sama menjadi lebih tepat untuk semua
  > pengguna. Yang dibagikan hanya struktur itu: nama orang, nomor rekening, nomor referensi, dan nominal transaksi
  > Anda tidak pernah dibagikan. Aturan baru ditinjau pengelola sebelum dipakai. Gambar bukti dihapus setelah dibaca,
  > dan teks hasil bacanya tidak disimpan.
- DPIA ringkas: ditambah satu baris untuk tabel aturan (data: label, hitungan; dasar: kepentingan sah; retensi: selama
  aturan dipakai).

## 9. Gerbang rilis baru dan urutan menyalakan saklar
Gerbang §7c (korpus ≥ 95% pada 12 aplikasi) **diganti** oleh keputusan pemilik (butir 4). Syarat yang tetap:
1. Titik wajib review akhir Bagian A ditutup: **N2** (QRIS dengan nama toko berkata sukses menutupi "Pembayaran Gagal"
   saat saklar menyala), **N4** (blokir palsu oleh kaki bantuan berbentuk judul), **C2** (judul tanpa kata benda
   transaksi, "Kirim Uang Berhasil"), **C3** (struk 1–2 barang dibayar QRIS kehilangan rincian saat saklar mati), sisa
   N1. Masing-masing dengan sapuan: tidak ada struk belanja berubah, tidak ada blokir hilang.
2. Kosakata §7 tayang.
3. Belajar lintas user tayang (§2–6) beserta migrasinya — supaya koreksi hari pertama langsung terkumpul.
4. `privacy.html` diperbarui (§8) oleh pemilik di server; DPIA ringkas diperbarui.
5. Urutan yang sudah ada di `docs/kotak-struk.md` "Menyalakan saklar": keputusan hari pertama (banner langsung
   menghitung item `siap` 7 hari terakhir) → saklar ON → uji HP tanpa share → PR `share_target` → uji share.
   Catatan: `eval --real-only` tetap dijalankan dan dilaporkan, bukan sebagai gerbang.
6. Pemantauan 2 minggu pertama: `% dikoreksi` per aplikasi di Admin, aturan menunggu, laporan user. Saklar bisa
   dimatikan lagi kapan saja (`/app/config`; klien membaca ulang ≤ 1 jam).

## 10. Tahap dan paket tugas (perkiraan)
**Tahap 1 (satu PR berlabel `migrasi`, cabang `feat/kotak-belajar`):**
- L1 kerangka `layout` di worker + purge (server, tanpa API baru).
- L2 tabel `proof_rule_votes`/`proof_rules` + migrasi + `learn_from_correction` di `after_recorded`/`skip_item`
  (web + bot), ambang, hapus akun.
- L3 pembaca memakai aturan yang disetujui (`ParseContext.rules`, cache 5 menit).
- L4 API Admin + UI "Aturan belajar".
- L5 kosakata §7.
- L6 penutupan N2, N4, C2, C3, sisa N1 (masing-masing kalibrasi kecil dengan sapuan).
- L7 dokumen: `docs/kotak-struk.md` (bagian "Belajar lintas user", gerbang baru, batasan), `AGENTS.md` checklist
  deploy (migrasi), PROGRESS/03-workflow, paragraf privasi.
- Lalu: review akhir branch, PR, merge dengan izin, migrasi sesudah deploy, langkah §9.5.

**Tahap 2 (PR terpisah, setelah saklar menyala):**
- Donasi contoh (opt-in di Settings): saat user mengoreksi, baris OCR yang sudah disamarkan (`mask_line`) masuk antrean
  tinjauan Admin; pemilik meninjau, mengganti nama, menyetujui → sampel korpus `reviewed: true`. Ini jalan untuk
  menambah korpus tanpa pemilik punya rekening di banyak bank.
- Aturan `logo` untuk aplikasi yang belum berprofil (user memberi nama aplikasi pada bukti `tidak_dikenali`).
- Top-up e-wallet sendiri (`top_up`) dari aturan `arah` yang terkumpul.

## 11. Risiko dan mitigasi
| Risiko | Mitigasi |
|---|---|
| Aturan salah membuat nominal salah terbaca `tinggi` untuk semua user | ambang 2 user + persetujuan pemilik + cek silang nominal tetap jalan + cabut di Admin |
| Pengguna jahil memberi suara palsu | satu suara per user; butuh 2 akun; pemilik melihat contoh sintetis dan jumlah rumah tangga sebelum setuju |
| Kebocoran lewat label | digit disamarkan, panjang ≤ 40, baris nomor tidak masuk kerangka; tes privasi memindai `layout` dan tabel aturan untuk pola nomor/nama sampel nyata |
| Hari pertama ramai koreksi, pemilik kewalahan | ambang membuat hanya pola berulang yang muncul; tab "Suara" hanya angka |
| Aplikasi tanpa sampel terbaca `tidak_dikenali` | nominal tebakan + konfirmasi; belajar `label_total` lewat kunci `logo:<kata>` |

## 12. Keputusan pemilik (1 Nov 2026, 18:08 dan 19:57)
1. Ambang aturan: **2 user berbeda** (seperti struk belanja).
2. Gerbang korpus §7c **diganti** seperti §9.
3. Hari pertama: **B** — perintah sekali jalan menandai item `siap` lama dari form Catat (`source = web_form`)
   sebagai `dilewati` (alasan `batal`) tepat sebelum saklar dinyalakan; item bot/chat web tidak disentuh.
4. Tahap 2 (donasi contoh) **langsung dikerjakan** setelah tahap 1 tayang.
