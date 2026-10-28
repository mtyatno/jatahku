# Kotak Struk ("Bagikan ke Jatahku")

Satu pintu masuk untuk struk dan bukti bayar (QRIS, transfer) dari semua kanal: bot Telegram, chat bot di
webapp, dan tombol Struk di form Catat; nanti PWA (menu Bagikan di Android) dan aplikasi native. Setiap unggahan
menjadi satu baris `receipt_scans` berstatus `diterima`, dibaca worker di dalam proses API, lalu dicatat **hanya
setelah user mengonfirmasi**. Desain: `docs/superpowers/specs/2026-10-26-bagikan-ke-jatahku-design.md`;
keputusan: ADR-M16 dan ADR-M17 (`docs/mobile/02-adr.md`). Cara struk belanja dibaca dan dicatat per barang:
[`docs/scan-struk.md`](scan-struk.md).

**Status (28 Okt 2026).** Bagian A (server, bot, API, alat korpus) tayang 28 Okt 2026 06:01 WIB: PR #130 (squash
`8074a57`), migrasi `a7c4e2b9d1f3`, verifikasi versi yang tayang lulus. Saklar `features.receipt_inbox` mati.
Bagian B (PWA: share target, halaman `/bagikan`, `ProofCard`, banner "Bukti menunggu", tombol PDF, tips Settings,
rincian di UI Admin) belum dimulai; dikerjakan di branch `feat/bagikan-ke-jatahku-web`. Kalibrasi pembaca dengan
sampel nyata (A14) menunggu sampel dari pemilik produk. Perbarui bagian ini saat status berubah.

## Alur

```
bot Telegram / chat web ─┐
form Catat (scan-receipt) ┼─► intake ──► item `diterima` ──► worker ──► `siap` ──► user konfirmasi ──► `tercatat`
POST /kotak-struk ────────┘  (isi, batas,   (file sementara,   (teks, pembaca,  (saran amplop,    (jalur catat yang ada
 (PWA/app: Bagian B)          idempotensi)    hash)             cek silang)      tanda duplikat)   + belajar)
```

- **Intake** (`services/kotak_struk/intake.py`) adalah satu-satunya pintu. Urutan: tepat satu file atau satu teks;
  sumber dikenal; `upload_id` sama → item lama; jenis file dari **isi**-nya (JPEG/PNG/WebP/PDF, bukan nama atau
  header klien); ukuran; file sama dengan item user yang belum selesai → item lama; batas per jam; batas item
  menunggu; lalu item dan file sementara (mode 0600, nama = id item) disimpan.
- **Worker** (`worker.py`, `run_worker()`) berjalan sebagai tugas asyncio di `lifespan` (`main.py`), di samping
  scheduler. Mengklaim item `diterima` tertua dengan `UPDATE … WHERE status='diterima'` + cek rowcount
  (`attempts + 1`), lalu: baca file → ekstrak teks → pembaca → simpan hasil → **hapus file** → kabari. Koneksi DB
  tidak dipegang selama OCR/PDF/LLM; satu OCR berjalan bersamaan. Saat menyala dan tiap menit, item `diproses`
  yang lebih dari 5 menit (API restart) dikembalikan ke `diterima`, atau `gagal` bila sudah 3 percobaan. Galat tak
  terduga mengulang sampai 3 kali, lalu `gagal` ("Bukti tidak bisa dibaca. Coba kirim ulang.").
- **Kabar selesai**: Redis pub/sub `kotak:done:{item_id}`; `wait_for_item(id, timeout)` mendengarkannya dan
  tetap memeriksa DB (tiap 0,5 dtk bila Redis mati, tiap 5 dtk bila sehat), jadi Redis mati tidak membuat
  penunggu macet.
- **Ekstraksi teks** (`extract.py`): gambar → RapidOCR; teks → dibelah per baris; PDF → `pypdfium2` di **proses
  anak** (spawn, batas waktu 15 dtk, batas memori 768 MB dan CPU, tanpa menjalankan skrip PDF): lapisan teks
  dibaca langsung, halaman tanpa teks dirender (200 dpi) lalu di-OCR. PDF yang butuh kata sandi untuk dibuka
  ditolak; PDF yang hanya dibatasi sandi pemilik tetap dibaca.
- **Konfirmasi memakai jalur catat yang sudah ada**, tidak menduplikasi aturan pengeluaran, kuota transaksi, dan
  idempotensi: bot lewat callback amplop `t_{key}_{idx}` (termasuk geser dana dan limit harian); web lewat
  `POST /transactions` dan `/transactions/batch` dengan `receipt_item_id` (lihat [`scan-struk.md`](scan-struk.md)).

## Status item

| Status | Arti | Berikutnya |
|---|---|---|
| `diterima` | Di antrean, file ada di `KOTAK_DIR` | `diproses` |
| `diproses` | Worker sedang membaca | `siap`, `gagal`, atau kembali `diterima` (ulang/pemulihan) |
| `siap` | Terbaca, menunggu konfirmasi (`expires_at` = selesai + 7 hari) | `tercatat`, `dilewati`, `kedaluwarsa` |
| `gagal` | Tidak terbaca; alasan di `error` (`expires_at` sama) | `dilewati`, `kedaluwarsa` |
| `tercatat` | Sudah menjadi transaksi (`transaction_ids`) | akhir |
| `dilewati` | User melewati; alasan di `channel_meta.skip_reason`: `bukan_pengeluaran`, `duplikat`, `batal` | akhir |
| `kedaluwarsa` | `siap`/`gagal` lebih dari 7 hari tanpa konfirmasi | akhir; struk belanja dan tidak dikenali yang sudah terbaca masih boleh dicatat (simpan terlambat dari antrean offline) → `tercatat` |

`status` NULL = baris riwayat scan lama, bukan item Kotak Struk (API menjawab 404 untuknya). Struk belanja boleh
dicatat berkali-kali (satu transaksi per barang): statusnya `tercatat` sejak yang pertama dan idnya
ditambahkan ke `transaction_ids`. Jenis lain (QRIS, transfer, tidak dikenali) hanya sekali.

Pesan `error` untuk item `gagal` (aman ditampilkan): "PDF terkunci kata sandi", "PDF lebih dari 5 halaman", "PDF
tidak bisa dibaca" (rusak, lewat batas waktu, atau melewati batas memori/CPU proses anak; langsung `gagal`, tidak
diulang), "Gambar tidak bisa dibaca. Coba kirim ulang.", "Baca bukti
sedang tidak bisa. Catat manual dulu." (paket OCR atau `pypdfium2` belum terpasang; fitur lain tidak
terpengaruh), "Bukti tidak bisa dibaca. Coba kirim ulang." (galat tak terduga setelah 3 percobaan, atau file
hilang). `source`: `telegram`, `web_chat`, `web_form`, `pwa_share` (nanti `web_upload`, `android`, `ios`, `email`).

## Jenis dokumen dan pembaca

`doc_type`: `struk_belanja`, `qris`, `transfer`, `tidak_dikenali` (nanti `tagihan`, `invoice`, …). Registri
(`registry.py`) menjalankan `detect` tiap pembaca terdaftar dan memakai skor tertinggi **≥ 0,5**; seri dimenangkan
yang terdaftar lebih dulu (QRIS, transfer, struk belanja). Tidak ada yang lolos → pembaca cadangan.

| Pembaca | Jenis | Dasar |
|---|---|---|
| `qris.umum` | `qris` | ≥ 2 penanda (`QRIS`, `NMID`, `Merchant PAN`, `Terminal ID`, `Acquirer`, `Penerbit`) → skor 0,95; hanya kata `QRIS` plus label merchant atau nominal → 0,7 (0,9 bila ada kata status) |
| `transfer.umum` | `transfer` | ≥ 2 penanda (`transfer`, `rekening tujuan`, `bank tujuan`, `BI-FAST`, `berita`, `penerima`) → 0,9; top-up atau uang masuk yang ada nominalnya → 0,85 (0,9 bila ada penanda lain atau kata status) |
| `struk_belanja` | `struk_belanja` | Membungkus `parse_receipt` beserta data belajarnya (logika tidak diubah); fallback LLM tetap seperti dulu |
| cadangan | `tidak_dikenali` | Nominal Rp terbesar (keyakinan `rendah`), atau tebakan scan lama untuk teks tanpa baris Rp; boleh tanpa nominal |

Kedua pembaca bukti bayar memberi skor 0 pada pola struk belanja (KEMBALI/TUNAI, ≥ 3 barang). Struk belanja yang mencantumkan kata "QRIS" (mis. "Non Tunai (QRIS)") tetap `struk_belanja`. LLM tidak dipanggil
untuk QRIS/transfer yang dikenali; hanya jalur struk belanja/tidak dikenali yang memakainya (seperti scan lama),
dan itu mati kecuali `RECEIPT_LLM_ENABLED`.

**Profil aplikasi** (`readers/profiles.py`) adalah data, bukan kode: kata pengenal aplikasi (`issuer`) dan sinonim
label. Saat ini 8 bank (BCA mobile, Livin' by Mandiri, BRImo, BNI/wondr, BSI, Jago, SeaBank, blu) dan 4 e-wallet
(GoPay, OVO, DANA, ShopeePay); label khusus per aplikasi masih kosong sampai kalibrasi A14. Menambah aplikasi
biasanya cukup satu entri `AppProfile`.

**Dokumen Bayar** (kolom `document`, JSON berversi `schema: 1`, `services/kotak_struk/document.py`): `doc_type`,
`issuer`, `status` (`berhasil` | `gagal` | `pending` | `tidak_diketahui`), `flow` (`keluar` | `masuk` | `top_up` |
`antar_rekening_sendiri` | `tidak_diketahui`), `method` (`qris` | `transfer` | `va` | `tunai` | `kartu` | `lainnya`), `paid_at`, `counterparty` (nama, kota, `bank`,
`id_kind`, `id_masked`),
`amounts` (subtotal, fee, tax, discount, total), `lines` (struk belanja), `refs` (hanya versi tersamar), `note` (berita transfer),
`confidence` per field (`tinggi` | `sedang` | `rendah`), `evidence`, dan `checks`. Jenis baru mengisi field yang
relevan tanpa perubahan skema (ADR-M17). Untuk struk belanja, worker menambahkan kunci `receipt` (diskon per barang,
penyesuaian, rekonsiliasi, sumber keyakinan, label total) supaya respons `scan-receipt` lama bisa dibangun ulang.

**Cek silang** (`checks.py`; hasilnya di `document.checks`, level `warn` atau `block`):

| Kode | Level | Berlaku untuk | Efek |
|---|---|---|---|
| `status_gagal` | block | semua jenis | Item diblokir (`flags.blocked = "transaksi_gagal"`), tidak bisa dicatat |
| `status_pending` | warn | semua jenis | Peringatan "Transaksi masih diproses bank" |
| `selisih_nominal` | warn | QRIS, transfer | subtotal + biaya + pajak − diskon ≠ total; keyakinan total turun ke `sedang` |
| `tanggal_depan` | warn | QRIS, transfer | Keyakinan tanggal `rendah` |
| `bukti_lama` | warn | QRIS, transfer | Bukti lebih dari 60 hari lalu |

Cek status sengaja berlaku untuk semua jenis supaya transfer gagal tidak bisa tercatat walau salah dirutekan ke
pembaca lain. Pembaca struk belanja dan pembaca tidak dikenali (yang membaca bukti bayar saat saklar mati, atau bukti yang
tidak dikenali pembaca bukti) mengambil status dari judul (4 baris pertama) **dan dari judul status gagal/pending di
mana pun di badan** (`apply_header_status` → `read_body_failure_title`: kata benda transaksi + kata status, mis.
"Transaksi Gagal" di bawah rincian, "Transaction failed", "Transfer Diproses"), jadi bukti seperti itu diblokir atau
diperingatkan sama seperti di jalur bukti. Hanya judul: kalimat biasa ("Cetak ulang gagal"), kalimat bantuan/ajakan/tanya
("Info untuk transaksi gagal: 14017", "Jika transaksi gagal hubungi …", "Transaksi gagal? Hubungi kami"), dan judul
sukses dari baris nama tidak dihitung; judul status yang **pertama** menentukan, seperti `read_status`: judul sukses di
atasnya ("Transfer Berhasil", atau "Transaksi Berhasil" di badan) membuat kalimat gagal sesudahnya dianggap kaki bukti.
Pada struk belanja, kaki "Transaksi gagal - struk ini tidak sah" (struk batal) ikut memblokir dan "Pembayaran pending
akan diproses otomatis" hanya memperingatkan. Arah uang: `top_up`, `masuk`, dan `antar_rekening_sendiri` mengisi `flags.skip_suggestion`; bot dan web
menawarkan "bukan pengeluaran", **tidak pernah otomatis**, dan user tetap bisa memilih "Tetap catat" (kecuali
`blocked`). `antar_rekening_sendiri` hanya untuk transfer keluar yang nama penerimanya sama dengan nama akun, atau
yang minimal 2 katanya ada di nama akun (`apply_flow`).

## Duplikat: tidak pernah tercatat dua kali

| Lapis | Pemicu | Hasil |
|---|---|---|
| 1. `upload_id` | Sama, per user (ketuk Bagikan dua kali, kirim ulang). Indeks unik parsial `(user_id, upload_id)` | Item yang ada dikembalikan (200), tidak ada item baru |
| 2. Hash file | `file_sha256` sama dengan item user yang masih terbuka (`diterima`, `diproses`, `siap`) | Item itu dikembalikan |
| 2b. Hash file tercatat | Sama dengan item `tercatat` di rumah tangga | Item baru tetap dibuat; `flags` (dihitung saat item ditampilkan) berisi `duplicate_of = {kind: "file", item_id, recorded: true}` dan `blocked = "sudah_tercatat"` |
| 3. `ref_hash` | HMAC nomor referensi sama dengan item `tercatat` di rumah tangga | `duplicate_of = {kind: "ref", item_id, recorded: true}` dan `blocked = "sudah_tercatat"` |
| 3b. Referensi anggota lain | Sama dengan item `siap` milik anggota rumah tangga lain | `duplicate_of = {kind: "ref", item_id, recorded: false, by}` plus peringatan "Bukti ini juga dibagikan {nama}"; **tidak memblokir**. Begitu salah satunya tercatat, yang lain terkena lapis 3 |
| 4. Lunak | Item `siap` bernominal sama dengan transaksi rumah tangga yang belum dihapus, tanggal transaksi = tanggal bayar (WIB), dan dicatat dalam ±3 jam dari `paid_at`; hanya amplop yang boleh dilihat user | `duplicate_of = {kind: "soft", transaction}`; tidak memblokir: "Sama, lewati" atau "Beda, catat" |
| Klaim atomik | `claim_for_recording` | Lihat di bawah |

**Klaim atomik** (`record.py`): semua jenis selain struk belanja diklaim dengan satu `UPDATE … siap → tercatat`
(tidak dikenali yang sudah terbaca juga dari `kedaluwarsa`) **di commit yang sama dengan transaksinya**; hanya satu pemanggil yang menang (bot dan web bersamaan, dua ketukan),
yang lain mendapat 409 (web) atau "Bukti ini sudah tercatat" (bot) dan tidak ada transaksi. Urutan di web dan bot:
`check_recordable` (pesan ramah) → `claim_for_recording` → insert transaksi → satu commit → `after_recorded`
(streak, kata kunci, `mark_recorded`, peta merchant; best-effort dan idempoten per transaksi). `client_ref` yang
dikirim ulang menyembuhkan penandaan yang hilang (`heal_recorded`). Item yang dibagikan ulang setelah `kedaluwarsa`
membuka item baru (lapis 2 dan 3 hanya mencocokkan item terbuka dan `tercatat`). Item `tercatat` yang semua
transaksinya sudah dihapus (atau tidak ada lagi) tidak lagi memblokir file/referensi yang sama, jadi bukti itu bisa
dibagikan dan dicatat lagi; item tanpa id transaksi tercatat yang bisa dipastikan (`transaction_ids` kosong/NULL,
bukan daftar, atau berisi id yang tidak valid) tetap memblokir (`dedup._recorded_by`).

## Saran amplop dan belajar

Urutan sinyal (`suggest.py`), hasil `{envelope_id, envelope_name, confident, source: note|merchant|keyword|none}`:

1. **Catatan user** → `find_best_envelope(catatan)`.
2. **Peta merchant rumah tangga**: amplop dengan `count` terbesar (seri: `last_used_at` terbaru); `confident`
   bila `count`-nya ≥ 2/3 dari total `count` merchant itu di amplop yang boleh disarankan ke user (aktif, `expense`, bersama
   atau pribadi user; amplop lain tidak ikut dihitung).
3. **Kata kunci nama merchant** (nama panggilan bila ada) → `find_best_envelope`.
4. Tidak ada sinyal → tanpa saran.

Kandidat hanya amplop `purpose == "expense"`, aktif, dan `owner_id IS NULL OR owner_id == user.id` (kontrak
visibilitas rumah tangga): amplop yang dihapus, nonaktif, atau pribadi anggota lain tidak pernah disarankan, dan
sinyal jatuh ke berikutnya. Saran `confident` dipilihkan dan ditandai ⭐ ("disarankan"); yang tidak yakin hanya
diurutkan teratas.

Keterangan transaksi (`compose_description`, maks 500 karakter): `Siti Aminah (QRIS)`, `Transfer ke Budi Santoso`,
dengan catatan `bakso 2, es teh (Siti Aminah)`. **Belajar hanya dari transaksi yang benar-benar tercatat**
(`record.mark_recorded`): untuk QRIS dan transfer, `merchant_envelope_map.count + 1`; kata kunci hanya dari **catatan
user**, tanpa nama merchant, "(QRIS)", dan "transfer ke" (`learn_text_for_item`). Melewati item tidak mengajari apa
pun. Struk belanja dan `tidak_dikenali` hanya mendapat baris `household_merchants` (nama dan kota dari worker; nama
panggilan hanya dari user lewat `PUT /kotak-struk/merchants/{id}`),
kecuali teks yang tampak seperti bukti bayar (lihat "Privasi"); `merchant_envelope_map` tidak pernah belajar darinya
(saran per barang tetap kata kunci; umpan balik struk lewat `apply_feedback`).

Peta ada di dua tabel per rumah tangga: `household_merchants` (`counterparty_key`, `raw_name`, `display_name`
= nama panggilan opsional dari user, `city`) dan `merchant_envelope_map` (`merchant_id`, `envelope_id`, `count`,
`last_user_id`, `last_used_at`). `counterparty_key`: `nmid:<NMID>` bila ada; `rek:<hmac>` untuk rekening yang
terbaca utuh (≥ 8 digit); selain itu `nama:<nama>|<kota atau bank>` (huruf kecil, tanda baca dibuang, maks 80 karakter).

## Kanal

**Bot Telegram dan chat bot web** (`app/bot/receipt_cmd.py`, `handlers.py`; chat web otomatis ikut lewat
`web_adapter`):

- Foto, dokumen gambar, dan PDF → item (source `telegram` atau `web_chat`) → menunggu hasil maks **10 dtk** →
  pesan hasil. Tiap foto atau file satu item. Dokumen selain gambar/PDF tetap "📄 File belum didukung."
- **Teks bukti** yang ditempel dianggap bukti **hanya bila** semua syarat terpenuhi: minimal 2 baris, ada nominal
  `Rp`/`IDR`, ada kata status (`berhasil`, `sukses`, `successful`), dan ada satu label (`referensi`, `ref`, `rrn`,
  `merchant`, `penerima`, `tujuan`, `nmid`); panjang ≤ 4.000 karakter. Ketikan biasa ("kopi 35k", daftar "kopi 20k"
  + "roti 15k") tetap ke NLP.
- **Struk belanja** (dan `tidak_dikenali`): pesan struk lama (rincian, cocok/selisih), **tanpa baris sisa kuota**.
- **QRIS/transfer**: `{QRIS|Transfer} · {nama} · {kota}`, `{Rp} · {tgl jam} · {status}`, "Masuk ke amplop mana?",
  dengan tombol amplop (saran teratas, ⭐ bila yakin), **✏️ Tambah catatan** (`kn_`), **🚫 Bukan pengeluaran**
  (`kx_`), **❌ Batal** (`struk_no_`). Transfer gagal: "⚠️ Transaksi ini gagal di bank, jadi tidak dicatat." tanpa
  tombol. Sudah tercatat: "✅ Bukti ini sudah tercatat {tgl} di {amplop}." (nama amplop disembunyikan bila amplop
  pribadi anggota lain). Duplikat lunak: "Mirip "…" yang dicatat {jam}. Sama?" dengan **Sama, lewati** (`kd_`) dan
  **Beda, catat** (`ko_`). Top-up, uang masuk, rekening sendiri: **Oke, lewati** dan **Tetap catat**.
- **Tambah catatan**: bot membalas "Ketik isi belanjaannya (atau /batal)" dan menyimpan `kotak:note:{tg_user_id}`
  (TTL 300 dtk). Pesan teks berikutnya menjadi catatan sebelum NLP; saran dan pesan tombol dihitung ulang. `/batal`
  selama menunggu catatan hanya membatalkan catatan (bukan transaksi terakhir). Catatan yang masuk saat tombol pesan
  yang sama sedang diproses menunggu sebentar (≤ 2 dtk); masih sibuk → "⏳ Sedang diproses, kirim ulang catatannya.";
  bila tombol itu sudah memakai sesinya (mis. mencatat) → "⚠️ Bukti ini sudah diproses, catatannya tidak
  ditambahkan." Catatan yang sempat menunggu tidak pernah diproses NLP.
- **Lewat batas tunggu**: Telegram membalas "⏳ Masih dibaca, nanti kukabari." lalu worker mengedit pesan itu
  menjadi hasil (atau gagal) lewat `send_ready_message`; pesan terhapus → pesan baru. Chat web membalas "⏳ Masih
  dibaca. Cek Bukti menunggu di beranda nanti." (banner itu datang di Bagian B). Bukti yang sama dikirim lagi
  selagi dibaca tidak merebut janji pesan pertama.
- **Tanggal di luar periode berjalan** (struk dan bukti; `period.document_date_kind`): tanggal struk/bayar sebelum
  awal periode anggaran user → sebelum tombol amplop bot bertanya "📅 Tanggal di {struk|bukti}: {tgl} — di luar
  periode sekarang ({periode}). Catat untuk tanggal berapa?" dengan **📅 Hari ini** dan **📅 {tgl}** (`kt_{key}_h` /
  `kt_{key}_d`; juga sesudah "Tetap catat"/"Beda, catat" dan catatan). Hari ini → cek dana, geser dana, dan limit
  harian seperti biasa. Tanggal dokumen → dicatat di periode lalu **tanpa geser dana**: blok dana dan limit harian
  dilewati, kunci amplop, kuota, dan amplop tabungan tetap memblokir ("Tercatat di periode …; sisa periode sekarang
  tidak berubah."). Tanggal yang belum lewat dianggap salah baca: dicatat hari ini dengan satu baris keterangan.
  Pesan sukses yang tanggalnya bukan hari ini menyebut tanggal itu (`· 📅 26 Okt`).
- Payload Redis `txn:{key}` yang sudah ada diperluas dengan `kind: "proof"`, `item_id`, `note`, dan untuk jawaban
  tanggal `date_answered` dan `past_period` (selama menunggu jawaban juga teks bacaan dan label tombol amplopnya).
- Route foto chat web (`/bot/chat/photo`) hanya menerima gambar (415 untuk PDF); PDF dari web masuk lewat form
  Catat dan share target (Bagian B).

**Form Catat** (`POST /transactions/scan-receipt`): membuat item (source `web_form`), menunggu maks 45 dtk, lalu
membalas bentuk respons lama ditambah `item_id`, `doc_type`, `counterparty`, `paid_at`, `flags`, `suggestion`,
`description_preview`. Menerima gambar atau PDF. Kontrak frontend lama tidak putus.

Baris hasil scan di form Catat (B1, tidak bergantung saklar; `frontend/src/lib/receiptScan.js`, `multiAddRows.js`):
- Setiap simpan membawa `receipt_item_id`: batch, antrean offline (app dan service worker), dan setiap bagian struk
  per barang.
- Satu item = satu baris/kartu: foto yang sama di-scan lagi tidak menambah baris ("Struk ini sudah ada di daftar." /
  "Bukti ini sudah ada di daftar.").
- `flags.blocked`, dan penolakan 409 saat simpan, tampil sebagai alasan di baris; baris itu tidak dikirim lagi.
- Tanggal dokumen di luar periode ditanya dulu ("Hari ini" atau tanggal dokumen); tanggal yang belum lewat menjadi
  hari ini (lihat `receipt_item_id` di bawah).
- × dan "Lewati yang gagal" melewati item (`lewati`, alasan `batal`), kecuali baris lain masih memakai item itu.
- Umpan balik belajar struk (`scan-receipt/{id}/feedback`) hanya untuk struk belanja.
- QRIS/transfer: keterangan `description_preview` dan saran amplop server yang yakin. Struk belanja dan tidak
  dikenali seperti dulu, sama dengan bot: nama toko atau "Belanja", saran kata kunci.

**Tombol PDF** di form Catat (B2), hanya saat saklar menyala: `native.files.pickDocument` (gambar atau PDF, tanpa
penanda kamera). PDF dikirim apa adanya dengan nama aslinya ke `scan-receipt`; di atas 10 MB ditolak sebelum diunggah
(`receiptProgress.checkScanFile`). Teks tahapnya memakai kata "bukti", tanpa gambar kecil, dan "Pilih file lain"
menggantikan "Foto ulang". Saklar mati: tidak ada tombol PDF, dan PDF yang terpilih lewat Galeri tetap ditolak seperti
dulu.

**PWA share target, halaman `/bagikan`, `ProofCard`, banner**: Bagian B (belum ada).

## API

Semua butuh login; item hanya terlihat pemiliknya (item orang lain = 404 "Bukti tidak ditemukan"). Rute memakai
garis miring penutup (`/kotak-struk/`); tanpa itu dijawab 307.

| Endpoint | Isi |
|---|---|
| `POST /kotak-struk/` | Multipart: `file` **atau** `text`, `source`, `upload_id` (≤ 64), `wait` (0–45 dtk, bawaan 0; koneksi DB dilepas selama menunggu). 201 item baru, 200 item yang sudah ada. Menjawab detail item |
| `GET /kotak-struk/?status=siap` | Item milik user dengan status itu (bawaan `siap`), terbaru dulu, maks 50 |
| `GET /kotak-struk/{id}` | Detail item |
| `POST /kotak-struk/{id}/saran` | `{note}` (≤ 200) → `{suggestion, description_preview}` |
| `POST /kotak-struk/{id}/lewati` | `{reason: bukan_pengeluaran \| duplikat \| batal}` → `dilewati`. Hanya item `siap`/`gagal`; selain itu 409 "Bukti ini tidak bisa dilewati" |
| `PUT /kotak-struk/merchants/{merchant_id}` | `{display_name}` (≤ 60; tag `<…>` dan karakter selain A–Z, a–z, 0–9, spasi, `&'.-` dibuang; kosong menghapus). Hanya anggota rumah tangga merchant itu, selain itu 404 |
| `POST /transactions`, `/transactions/batch` | Field opsional `receipt_item_id` (UUID); 409 bila item tidak boleh dicatat |
| `POST /transactions/scan-receipt` | Gambar atau PDF; respons lama + field baru |
| `GET /transactions/scan-receipt/quota` | Tetap ada untuk klien lama: `{limit: null, used, remaining: null}` |

Galat `POST /kotak-struk/`: **413** teks lebih dari 4.000 karakter ("Teks terlalu panjang"), foto lebih dari 8 MB,
PDF lebih dari 10 MB; **415** isi bukan JPEG/PNG/WebP/PDF ("Kirim foto (JPG/PNG/WebP), PDF, atau teks"); **422**
file dan teks sekaligus atau keduanya kosong ("Kirim satu file atau teks"), sumber tidak dikenal, atau `wait`
di luar 0–45; **429** lebih dari 30 bukti/jam ("Terlalu banyak bukti. Coba lagi sebentar.") atau 20 item belum
selesai ("Masih ada bukti yang sedang dibaca. Tunggu sebentar.").

**Detail item**: `id`, `status`, `doc_type`, `source`, `created_at`, `paid_at`, `document`, `merchant`
(`{id, name, display_name}`), `suggestion`, `description_preview`, `flags`, `error`. `flags` =
`{duplicate_of, skip_suggestion, blocked, warnings[]}`: `duplicate_of.kind` = `file` | `ref` | `soft`;
`skip_suggestion` = `top_up` | `masuk` | `antar_rekening_sendiri`; `blocked` = `transaksi_gagal` | `sudah_tercatat`. `duplicate_of` terisi
dengan `recorded` (true untuk file/ref yang sudah tercatat, false untuk referensi anggota lain yang masih `siap`; lunak tidak memuat
`recorded`). **Yang memblokir hanya `blocked`** (di antara `flags`; yang bisa dicatat tetap hanya item `siap`, lihat `receipt_item_id` di bawah), bukan `duplicate_of.kind`: klien tidak boleh menolak bukti hanya karena `kind: "ref"`.
Item `diterima`/`diproses`/`gagal` hanya memuat kolom dasar (tanpa `document`, `merchant`, saran).

**`receipt_item_id` di `POST /transactions` dan `/batch`**: dicek setelah `client_ref` (kirim ulang tetap
mengembalikan transaksi yang sama). Item harus milik user, `siap` (struk belanja: `siap` atau `tercatat`), tidak
diblokir, dan bukan duplikat yang sudah tercatat. Struk belanja dan tidak dikenali yang sudah terbaca (punya
`document`) tetap boleh dicatat sesudah `kedaluwarsa`, seperti `siap` dengan cek yang sama: simpan dari antrean offline
form Catat yang baru sampai sesudah 7 hari adalah konfirmasi yang terlambat (`record._late_ok`). QRIS/transfer yang
kedaluwarsa dan item yang tidak pernah terbaca tetap mendapat teks kedaluwarsa. Selain itu 409 (di batch: `error`
baris itu, `ok: false`) dengan
salah satu teks: "Bukti ini sudah tercatat", "Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya", "Bukti
ini belum siap dicatat", "Bukti tidak ditemukan", "Transaksi gagal, tidak bisa dicatat". Kuota transaksi Basic
(50/bulan) tetap berlaku. Tanggal (aturan bot yang sama, `period.document_date_kind` terhadap gajian user):
`transaction_date` sesudah hari ini dicatat hari ini, dan sebelum awal periode berjalan dicatat di tanggal itu tanpa
blok dana dan limit harian (limit juga tidak dinaikkan walau `raise_daily_limit`), sedangkan kunci amplop, amplop
tabungan, dan kuota tetap menolak; form Catat dan kartu bukti di web menanyakan "Hari ini" atau tanggal dokumen
lebih dulu (form Catat: B1, periode dari `GET /analytics/periods`, tanggal yang belum lewat diganti hari ini oleh
form sebelum disimpan; kartu bukti: B4, belum ada), dan baris tanpa `receipt_item_id` tidak berubah.

## Saklar fitur

`features.receipt_inbox` di `/app/config` (AppSetting `app_config`, bawaan **mati**). Server membacanya lewat
`feature_enabled(db, "receipt_inbox", "web")` per item, untuk semua kanal termasuk bot; galat membaca → mati.

| | Saklar mati (bawaan produksi) | Saklar menyala |
|---|---|---|
| Pembaca | Hanya `struk_belanja`; bukti QRIS biasanya jatuh ke `tidak_dikenali`, transfer kadang terbaca `struk_belanja` | `qris.umum` dan `transfer.umum` didahulukan |
| Pesan bot untuk QRIS | Pesan struk lama berkeyakinan rendah ("⚠️ kurang yakin, mohon dicek") | Pesan bukti dengan tombol catatan dan "Bukan pengeluaran" |
| Teks OCR dan peta merchant | Teks yang terbaca seperti bukti bayar **tidak** disimpan dan tidak masuk peta merchant (nomor rekening/RRN tidak boleh tersimpan) | Bukti yang dibaca pembaca QRIS/transfer tidak pernah menyimpan teks OCR; penerimanya masuk peta |
| Klien (Bagian B) | Banner, `/bagikan`, tombol PDF tersembunyi | Tampil |

**Tidak bergantung pada saklar**: penghapusan kuota scan, PDF/gambar lewat intake, transfer gagal tetap diblokir,
pencegahan ganda. Menyalakan (setelah gerbang korpus lulus; `PUT` mengganti **seluruh** nilai, jadi gabungkan dengan
isi `GET /admin/settings/app_config` bila sudah ada):

```
PUT /admin/settings/app_config?value={"features": {"receipt_inbox": {"web": true}}}
```

Nilai di query harus di-URL-encode. Berlaku untuk item berikutnya; item yang sudah `siap` tidak dibaca ulang.

## Konstanta

`app/services/kotak_struk/config.py`.

| Nama | Nilai | Arti |
|---|---|---|
| `WAIT_BOT_S` | 10 | Bot (dan PWA) menunggu hasil sebelum menjawab "masih dibaca" |
| `WAIT_FORM_S` | 45 | Tombol Struk di form Catat menunggu sebelum 503 "sedang ramai"; batas atas `wait` di API |
| `STALE_PROCESSING` | 5 menit | Item `diproses` lebih lama dari ini dikembalikan ke antrean |
| `MAX_ATTEMPTS` | 3 | Percobaan baca sebelum `gagal` |
| `ITEM_EXPIRY` | 7 hari | `siap`/`gagal` tanpa konfirmasi → `kedaluwarsa` (dihitung dari selesai dibaca) |
| `RATE_PER_HOUR` | 30 | Bukti per user per jam, gabungan semua kanal (Redis `kotak:rate:{user_id}`; Redis mati → tidak dibatasi); menggantikan batas slowapi 30/jam di `scan-receipt` dan `/bot/chat/photo` |
| `MAX_FILES_PER_SHARE` | 10 | File per satu share. Dipakai klien (Bagian B); server belum memakainya |
| `MAX_PENDING` | 20 | Item `diterima`/`diproses` per user |
| `IMAGE_MAX_BYTES` | 8 MB | Gambar (batas 30 MP di OCR tetap) |
| `PDF_MAX_BYTES` / `PDF_MAX_PAGES` | 10 MB / 5 | PDF |
| `PDF_TIMEOUT_S` | 15 | Batas waktu baca PDF di proses anak |
| `NOTE_TTL_S` | 300 | Bot menunggu teks catatan setelah "✏️ Tambah catatan" |
| `SOFT_DUP_WINDOW` | ±3 jam | Kecocokan lunak dengan transaksi rumah tangga |
| `CONFIDENT_SHARE` | 2/3 | Porsi minimal amplop teratas di peta merchant agar saran yakin |
| `OLD_PROOF_DAYS` | 60 | Bukti lebih tua diberi peringatan |
| `TEXT_MAX_CHARS` | 4000 | Panjang teks bukti |
| `ORPHAN_FILE_AGE` | 1 jam | File yatim lebih tua dari ini dihapus |
| `READER_THRESHOLD` | 0,5 | Skor minimum pembaca QRIS/transfer |

## Privasi dan masa simpan

- **Nomor rekening tidak pernah disimpan utuh.** Dokumen Bayar hanya memuat versi tersamar (`id_masked`, 4 digit
  terakhir); kunci `rek:` adalah HMAC. **RRN/nomor referensi** hanya sebagai HMAC (`ref_hash`) dan versi tersamar.
  HMAC memakai `KOTAK_HMAC_KEY`. NMID QRIS (publik) boleh disimpan.
- **Teks OCR bukti bayar tidak pernah disimpan.** `receipt_scans.ocr_lines` hanya diisi untuk struk belanja
  sungguhan (bahan `apply_feedback`) dan dihapus setelah feedback atau **24 jam** (`purge_stale_ocr_text`, job
  scheduler tiap jam); item `kedaluwarsa` juga dikosongkan. Teks yang tampak seperti bukti bayar (dikenali pembaca
  bukti, berjudul status seperti "Transfer Berhasil" di 4 baris pertama, atau memuat judul status di baris mana pun
  tanpa pola struk belanja; pola struk dibaca dari baris yang dinormalkan seperti pembaca struk, jadi struk belanja
  yang mencetak "Pembayaran QRIS berhasil" di kakinya tetap struk) tapi dibaca pembaca struk (saklar mati, atau bukti
  yang tidak dikenali pembaca bukti) diperlakukan sebagai bukti: tanpa `ocr_lines`, tanpa rincian baris
  (`document.lines`, juga tanpa `receipt`), tanpa nama merchant (dan tanpa kunci pihak dari nama itu), tanpa kutipan
  baris di `evidence`, tanpa peta merchant; yang tersimpan hanya nominal, waktu, status, keyakinan, dan cek. Pembaca
  struk memecah nomor berkelompok menjadi "barang" (`Rekening Tujuan 0123 0100`, 1234, 567), jadi rincian itu tidak
  boleh tersimpan.
- **File asli dihapus begitu item selesai dibaca** (`siap` atau `gagal`), `file_path` dikosongkan. Folder
  `KOTAK_DIR` (mode 0700, milik `jatahku`, di luar `backup.sh`); nama file = id item; file tidak pernah disajikan
  ke browser; tanpa pratinjau gambar. Teks bukti juga ditulis sebagai file sementara dengan aturan yang sama.
- **Yang tersimpan**: field Dokumen Bayar. Nama penerima/merchant disimpan karena menjadi keterangan transaksi
  milik user (data pihak ketiga; masuk DPIA, paket O05–O07). Hash file dan `ref_hash` tetap tersimpan setelah file
  dihapus supaya bukti yang sama dikenali.
- **Hak akses**: item hanya terlihat pemiliknya. Yang berlaku untuk rumah tangga: peta merchant, nama panggilan, dan
  cakupan deteksi duplikat. Transaksi di amplop pribadi anggota lain tidak ikut tampil di tanda duplikat lunak.
- **Hapus akun** (`account_deletion.py`): baris `receipt_scans` user ikut terhapus. Saat satu anggota keluar,
  peta merchant di amplop bersama tetap milik rumah tangga (`last_user_id` → NULL) dan baris peta ke amplop
  pribadinya dihapus; saat rumah tangga dihapus, `household_merchants` dan peta ikut terhapus. File sementara
  item yang belum selesai tidak dihapus di sana: barisnya hilang, penyapu file yatim yang menghapusnya (paling lama
  ±2 jam).

## Pemeliharaan

Job scheduler `kotak_maintenance` (`services/scheduler.py`): **cron tiap jam di menit 17** (bukan interval, supaya
tetap jalan walau API sering restart saat deploy; menghindari job menit 00). Dua langkah, masing-masing dengan
sesi dan penanganan galat sendiri:

1. `expire_items`: satu `UPDATE` bersyarat `siap`/`gagal` dengan `expires_at < sekarang` → `kedaluwarsa`, `ocr_lines`
   dikosongkan. Baris tetap disimpan (hash, `ref_hash`, `transaction_ids` tidak disentuh).
2. `delete_orphan_files`: berkas biasa di `KOTAK_DIR` (tanpa rekursi, tanpa symlink) yang namanya UUID kanonik,
   lebih tua dari 1 jam, dan bukan milik item `diterima`/`diproses`. Nama lain dibiarkan (jaga-jaga bila
   `KOTAK_DIR` salah menunjuk folder bersama). Folder tidak ada → tidak dibuat.

`purge_receipt_ocr_text` (interval 1 jam) tetap menghapus teks OCR scan lama yang tidak pernah diberi feedback.

## Statistik Admin

`GET /admin/receipt-scans/stats` (kartu Scan Struk) mempertahankan kunci lama dan menambah, dari item bulan ini
(baris riwayat tanpa status tidak ikut): `by_doc_type` (`{doc_type: n}`), `unrecognized` (jumlah `tidak_dikenali`),
dan `by_issuer` (`{issuer: {total, recorded, corrected}}`, hanya aplikasi yang profilnya dikenali). `corrected`
untuk QRIS/transfer **diturunkan**: item `tercatat` yang nominal transaksinya beda dari hasil baca, nominalnya
tidak terbaca, atau tanggal transaksinya bukan tanggal bayar (WIB), karena bukti bayar tidak pernah memakai
`outcome`. Data ini dipakai untuk menambah profil aplikasi. Tampilan di `Admin.jsx` belum ada (Bagian B).

## Konfigurasi (`/opt/jatahku/.env`)

| Env | Bawaan | Arti |
|---|---|---|
| `KOTAK_HMAC_KEY` | kosong | Kunci HMAC nomor referensi/rekening. **Isi** (`openssl rand -hex 32`). Kosong → diturunkan dari `JWT_SECRET` dengan peringatan di log; jangan diganti setelah dipakai (`ref_hash` dan kunci `rek:` lama tidak cocok lagi, deteksi duplikat dan peta merchant terputus) |
| `KOTAK_DIR` | `/var/lib/jatahku/kotak` | Folder berkas sementara; harus ada dan bisa ditulis user service. Mode 0700 hanya diterapkan pada folder yang dibuat aplikasi sendiri, jadi buat lewat langkah deploy |
| `RECEIPT_SCAN_LIMIT_BASIC` | 15 | Tidak dipakai lagi; tetap ada di `Settings` supaya `.env` lama tidak membuat startup gagal |
| `RECEIPT_LLM_*` | — | Fallback LLM struk belanja (mati bawaan); lihat [`scan-struk.md`](scan-struk.md) |

## Deploy manual (sekali)

Deploy otomatis tidak memasang paket Python dan tidak menjalankan alembic, jadi ada langkah manual. Daftar yang
sama, format checklist: `AGENTS.md` "Deploy Checklist — Kotak Struk / Bagikan ke Jatahku, Bagian A (a7c4e2b9d1f3)". PR Bagian A berlabel `migrasi`.

1. **Sebelum merge** (aman untuk kode lama):
   `sudo -u jatahku /opt/jatahku/venv/bin/pip install pypdfium2==5.13.0` (versi sama dengan `requirements.txt`);
   `sudo install -d -m 0700 -o jatahku -g jatahku /var/lib/jatahku/kotak`;
   tambahkan `KOTAK_HMAC_KEY=<openssl rand -hex 32>` ke `/opt/jatahku/.env`.
2. **Merge**, tunggu deploy (`api.jatahku.com/health` → `commit` baru). Kolom baru `receipt_scans` dan dua tabel
   baru dibuat `lifespan` saat API restart (`KOTAK_DDL` + `create_all`), jadi tidak ada jendela 500 seperti
   migrasi sebelumnya.
3. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head`; `alembic current` harus
   `a7c4e2b9d1f3` (sebelumnya `a7c3e9d1f5b2`). Migrasi ini idempoten dan hanya mencatat revisi; tanpa itu
   `deploy.sh` mengakhiri deploy dengan exit 2. Lalu `sudo systemctl restart jatahku`.
4. **Uji** (saklar masih mati): kirim foto struk Indomaret ke bot → pesan struk lama **tanpa** baris sisa scan;
   kirim PDF → bot membalas hasil, bukan "📄 File belum didukung" (jawaban "Baca bukti sedang tidak bisa" berarti
   `pypdfium2` belum terpasang); kirim bukti QRIS → pesan struk berkeyakinan rendah, dan `GET /admin/receipt-scans/stats` (admin)
   → `unrecognized` bertambah (UI Admin belum menampilkannya). Bot menjawab "Bukti tidak bisa dibaca" untuk semua file → cek `journalctl -u jatahku`
   (biasanya `KOTAK_DIR` tidak ada atau tidak bisa ditulis).
5. **Saklar tetap mati sampai gerbang korpus lulus** (bagian berikut). Setelah itu nyalakan seperti di "Saklar
   fitur", lalu kirim dua bukti QRIS dari merchant yang sama (catat yang pertama): yang kedua datang dengan ⭐.

## Alat korpus dan gerbang rilis

Korpus `app/tests/fixtures/kotak/corpus.json` berisi **baris teks tersamar**, bukan gambar atau PDF, dengan hasil
yang diharapkan. **Berkas bukti asli tidak pernah di-commit** (alatnya tidak menyalinnya).

```
python -m app.scripts.kotak_corpus add <berkas> --id <id> [--real] [--user-name NAMA] [--corpus PATH]
python -m app.scripts.kotak_corpus eval [--real-only] [--corpus PATH]
```

Di VPS: `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.kotak_corpus eval --real-only`.

- **`add`** menerima `.txt`, `.pdf`, atau gambar; mengekstrak teks (OCR/lapisan teks), menyamarkan tiap baris
  (`mask_line`: deret ≥ 6 digit menjadi `…dddd`; nominal, tanggal, jam, dan NMID dibiarkan), menjalankan pembaca pada
  baris tersamar, lalu menambahkan sampel dengan `expect` = hasil pembaca saat ini. `--real` menandainya bukti nyata
  dengan `"reviewed": false`; `--user-name` untuk cek "rekening sendiri" (pakai nama samaran); `--corpus` memilih
  berkas lain. Id berawalan `indomaret-` dicadangkan; id yang sudah ada ditolak (exit 2).
- **Tinjauan manusia wajib** untuk sampel nyata: bandingkan baris dan `expect` dengan bukti aslinya, samarkan nama
  orang pribadi (juga `user_name`; selain penerima/merchant yang dibutuhkan), lalu ubah ke `"reviewed": true`. Baris
  bertanda **`PERIKSA baris N`** masih memuat ≥ 6 digit atau huruf mirip angka di luar bentuk yang dibiarkan
  (kemungkinan nomor rekening/referensi/HP). Tanda itu **hanya jaring pengaman**: tidak memblokir dan tidak
  menggantikan tinjauan (lihat "Batasan yang diketahui").
- **`eval`** mencetak hasil per sampel dan ringkasan. Bawaan: sampel sintetis + sampel nyata yang sudah ditinjau + 4
  struk Indomaret asli (`receipt_ocr_lines.json`, harus tetap `struk_belanja`); sampel nyata yang belum ditinjau
  dilewati dan dihitung. **`--real-only`**: hanya sampel nyata yang sudah ditinjau ditambah 4 struk Indomaret; tanpa
  satu pun sampel nyata yang ditinjau, mencetak "korpus nyata belum ada" dan keluar 1 (tanpa evaluasi). Kode keluar:
  0 gerbang lulus, 1 tidak lulus atau tanpa sampel, 2 berkas korpus tidak ada atau rusak.
- **Gerbang** (spec §7c; persen satu desimal, dibulatkan ke bawah): pada sampel QRIS/transfer, **total, tanggal
  (WIB), dan status sekaligus benar** ≥ 95% dan nama pihak benar ≥ 90%; `doc_type` benar ≥ 98% pada semua
  sampel; tidak ada struk belanja yang terbaca sebagai bukti bayar. Tanpa sampel QRIS/transfer, gerbang tidak
  lulus. `flow` dan `issuer` dilaporkan, tidak digerbang.

**Hanya `eval --real-only` yang boleh dipakai sebagai syarat menyalakan saklar**: `eval` polos sudah lulus hari
ini karena memakai 6 sampel sintetis. Spec §7a menetapkan isi korpus nyata (8 bank dan 4 e-wallet, minimal 3 contoh
per aplikasi per jenis, plus contoh negatif: top-up, transfer gagal, uang masuk, rekening sendiri); alatnya tidak
memeriksa cakupan itu, jadi peninjau yang memastikannya sebelum menganggap gerbang lulus. Tes
`test_real_corpus_meets_release_gate` dilewati ("korpus nyata belum ada") sampai ada sampel nyata yang sudah
ditinjau, dan baru benar-benar berjalan setelah itu. Butir spec §7c yang bergantung pada klien (share Android
≤ 5 dtk, saran yakin di share kedua, folder sementara kosong setelah semua item diproses) diuji manual di HP
sungguhan bersama Bagian B; butir server lain (tidak pernah tercatat dua kali, transfer gagal tidak bisa dicatat)
dicakup tes otomatis.

**Kalibrasi A14 menunggu sampel nyata** dari pemilik produk (bukti QRIS dan transfer dari 8 bank dan 4 e-wallet).
Di sana juga diselesaikan titik yang diparkir di "Batasan yang diketahui" dan label per aplikasi di `profiles.py`.

## Batasan yang diketahui

- **Status gagal yang belum terbaca.** Judul dari baris nama ("Tujuan Transfer CV SUKSES JAYA") tidak lagi menutupi
  kegagalan di bawahnya, di jalur bukti maupun jalur struk/tidak dikenali (lihat "Cek silang"). Yang belum: di jalur
  struk/tidak dikenali, kata status tunggal di badan ("Gagal") dan status berlabel ("Status: Gagal") tidak dibaca
  (hanya judul status, paling banyak 8 kata); di jalur bukti, kata status di nama tanpa label di empat baris pertama
  ("TOKO SUKSES MAKMUR") masih terbaca berhasil dan menutupi "Pembayaran Gagal" di bawahnya; kaki bantuan berbentuk
  judul pada bukti tanpa status sendiri ("Info transaksi pending/gagal: 14017") memblokir di kedua jalur. Dikalibrasi di
  A14 dengan sampel nyata.
- **Alat korpus tidak mendeteksi semua nomor panjang.** `PERIKSA` tidak menandai nomor rekening/RRN yang terbaca
  OCR sebagai dua nominal bertitik ("614.534 681.544") atau terpotong tanda lain di tengahnya ("703.123|…6700"),
  nomor yang terpotong ke dua baris, dan referensi campuran huruf dan angka pendek. Tinjauan manusia sebelum
  `reviewed: true` satu-satunya penjaga di sana. Dikerjakan di A14.
- **Profil aplikasi belum dikalibrasi.** Label khusus per aplikasi kosong; pembaca memakai label umum. Sampai A14,
  bukti dari aplikasi dengan tata letak tidak biasa bisa terbaca `tidak_dikenali` atau dengan keyakinan `rendah`
  (user tetap mengonfirmasi dan mengoreksi nominal). Contohnya, transfer yang hanya punya satu penanda
  (DANA "Kirim Uang") bisa terbaca `struk_belanja`, dan struk berisi 1–2 barang dengan harga polos plus satu baris
  QRIS dan NMID bisa terbaca `qris` tanpa status. Teks seperti itu tetap diperlakukan sebagai bukti (tanpa teks OCR,
  rincian, dan nama; lihat "Privasi") bila memuat judul status berkata benda transaksi ("Transfer Berhasil",
  "Pembayaran Gagal") di 4 baris pertama, atau di baris mana pun bila teksnya tidak berpola struk belanja. Belum
  dikenali: judul tanpa kata itu ("Kirim Uang Berhasil"), status berlabel atau kata status saja ("Status: Berhasil",
  "BERHASIL"), dan bukti tanpa status sama sekali; untuk teks seperti itu pembaca struk masih bisa menyimpan nomor
  berkelompok sebagai rincian ("Ke BUDI 1234", 5678, 9012). Bukti satu penanda yang sama sekali tidak memuat judul
  status tetap disimpan sebagai struk belanja sampai A14. Sebaliknya, struk 1–2 barang tanpa pola struk (tanpa baris
  tunai dan tanpa kolom jumlah barang) yang mencetak judul status disimpan sebagai bukti, tanpa rincian (nominal tetap
  terbaca).
- **Bagian B belum ada**: chat web menyebut "Bukti menunggu di beranda" tetapi banner itu belum ada; item yang
  `siap` bisa dilihat lewat API tetapi belum lewat UI web.

## Tes

`python -m unittest discover -s app/tests -t .` (perintah CI). Yang khusus Kotak Struk: `app/tests/test_kotak_*.py`
(intake, ekstraksi, pembaca, registri, worker, API, bot, pemeliharaan, saran, transaksi, korpus, skema, dokumen),
`test_receipt_scan.py`, `test_account_deletion.py`, `test_web_chat.py`. Cek API hanya bertambah:
`python -m app.scripts.openapi_cek`.
