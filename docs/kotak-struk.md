# Kotak Struk ("Bagikan ke Jatahku")

Satu pintu masuk untuk struk dan bukti bayar (QRIS, transfer) dari semua kanal: bot Telegram, chat bot di
webapp, form Catat (Foto/Galeri, dan tombol PDF saat saklar menyala), dan PWA (menu Bagikan di Android → halaman
`/bagikan`, lihat "Web dan PWA"); nanti aplikasi native. Setiap unggahan menjadi satu baris `receipt_scans` berstatus
`diterima`, dibaca worker di dalam proses API, lalu dicatat **hanya setelah user mengonfirmasi**. Desain:
`docs/superpowers/specs/2026-10-26-bagikan-ke-jatahku-design.md`; keputusan: ADR-M16 dan ADR-M17
(`docs/mobile/02-adr.md`). Cara struk belanja dibaca dan dicatat per barang: [`docs/scan-struk.md`](scan-struk.md).

**Status (29 Okt 2026).** Bagian A (server, bot, API, alat korpus) tayang 28 Okt 2026 06:01 WIB: PR #130 (squash
`8074a57`), migrasi `a7c4e2b9d1f3`, verifikasi versi yang tayang lulus. Bagian B (web dan PWA: baris bukti dan
tombol PDF di form Catat, halaman `/bagikan`, `ProofCard`, banner "Bukti menunggu", tips Settings, rincian Scan Struk
di Admin) selesai di kode di branch `feat/bagikan-ke-jatahku-web` dan menunggu merge; tanpa migrasi dan tanpa paket
baru. Saklar `features.receipt_inbox` tetap mati. Dengan saklar mati, yang terlihat baru hanya baris hasil scan di form
Catat (satu baris per item, alasan blokir, pertanyaan tanggal) dan rincian Scan Struk di Admin. Tombol PDF, banner,
tips Settings, dan isi halaman `/bagikan` baru aktif saat saklar menyala (tabel di "Saklar fitur"). Menu Bagikan Android
butuh `share_target` di manifest, yang sengaja belum ada di branch ini: PR kecil terpisah saat saklar dinyalakan
(keputusan pemilik produk 28 Okt 2026; urutannya di "Menyalakan saklar"). Kalibrasi pembaca dengan sampel nyata (A14)
masih menunggu sampel dari pemilik produk. Perbarui bagian ini saat status berubah.

## Alur

```
bot Telegram / chat web ─┐
form Catat (scan-receipt) ┼─► intake ──► item `diterima` ──► worker ──► `siap` ──► user konfirmasi ──► `tercatat`
POST /kotak-struk ────────┘  (isi, batas,   (file sementara,   (teks, pembaca,  (saran amplop,    (jalur catat yang ada
 (PWA: /bagikan)              idempotensi)    hash)             cek silang)      tanda duplikat)   + belajar)
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
  dibaca. Cek Bukti menunggu di beranda nanti." (banner itu hanya tampil saat saklar menyala, lihat "Batasan yang
  diketahui"). Bukti yang sama dikirim lagi selagi dibaca tidak merebut janji pesan pertama.
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
- Route foto chat web (`/bot/chat/photo`) hanya menerima gambar (415 untuk PDF); PDF dari web masuk lewat tombol PDF
  di form Catat dan share target PWA, keduanya hanya saat saklar menyala (lihat "Web dan PWA").

**Form Catat** (`POST /transactions/scan-receipt`): membuat item (source `web_form`), menunggu maks 45 dtk, lalu
membalas bentuk respons lama ditambah `item_id`, `doc_type`, `counterparty`, `paid_at`, `flags`, `suggestion`,
`description_preview`. Menerima gambar atau PDF. Kontrak frontend lama tidak putus. Tampilannya di web (baris hasil
scan, tombol PDF): bagian berikut.

## Web dan PWA (Bagian B)

Aturannya ada di modul murni `frontend/src/lib/` yang diuji `node --test` (`receiptScan.js`, `multiAddRows.js`,
`receiptProgress.js`, `shareInbox.js`, `proofFormat.js`, `pendingProofs.js`, `scanStats.js`); komponen JSX hanya
merender. Saklar `features.receipt_inbox` dibaca dari `/app/config`; hanya nilai `true` yang berarti menyala.

**Form Catat: baris hasil scan** (tidak bergantung saklar; `receiptScan.js`, `multiAddRows.js`):
- QRIS dan transfer menjadi satu baris biasa tanpa rincian barang: keterangan dari `description_preview`, tanggal bayar
  (WIB), dan amplop dari saran server bila saran itu yakin (ditandai "disarankan"). Saran kata kunci tidak menimpanya.
  Pesan hasil scan menyebut satu peringatan bila ada (peringatan server, duplikat lunak, atau arah uang: top-up, uang
  masuk, rekening sendiri).
- Struk belanja dan `tidak_dikenali` seperti dulu, sama dengan bot: keterangan nama toko atau "Belanja", amplop dari
  saran kata kunci. Keduanya tetap membawa `receipt_item_id`, alasan blokir, dan aturan tanggal di bawah.
- Satu item = satu baris/kartu. Item yang sudah ada di daftar (mis. foto yang sama di-scan lagi) tidak menambah baris:
  "Struk ini sudah ada di daftar." atau "Bukti ini sudah ada di daftar.".
- `flags.blocked` tampil sebagai alasan di baris sejak scan, untuk semua jenis dokumen (saat saklar mati bukti bayar
  terbaca sebagai struk belanja atau tidak dikenali): "Transaksi ini gagal di bank, jadi tidak bisa dicatat." atau
  "Bukti ini sudah tercatat.". Penolakan bukti saat simpan (teks 409 di `receipt_item_id` di bawah) juga menjadi alasan
  di baris. Baris itu tidak bisa disimpan: pilihan amplopnya dikunci (kartu struk: semua isiannya), Simpan Semua
  melewatinya, dan bila semua baris diblokir, Simpan Semua menampilkan alasannya.
- Setiap jalur simpan membawa `receipt_item_id`: batch, setiap bagian struk per barang, dan antrean offline (payload
  antrean menyimpannya, `offlineSync.toBatchItem` meneruskannya saat sinkron dari app maupun dari service worker).
- × dan "Lewati yang gagal" melewati item di server (`POST /kotak-struk/{id}/lewati`, alasan `batal`) supaya tidak
  menunggu dicatat, kecuali baris lain masih memakai item itu. Jawaban 2xx memicu event `jatahku:kotak-changed`, jadi
  banner langsung menghitung ulang.
- Umpan balik belajar struk (`scan-receipt/{id}/feedback`) hanya untuk struk belanja (dan scan lama tanpa jenis); bukti
  bayar belajar di server saat tercatat.

**Tombol PDF** (hanya saat saklar menyala; `ReceiptInput.jsx`, `useReceiptScan.js`, `receiptProgress.js`):
- Tombol **PDF** di samping Foto/Galeri membuka `native.files.pickDocument` (gambar atau PDF, tanpa penanda kamera).
- PDF dikirim apa adanya ke `scan-receipt` dengan nama aslinya: tanpa kompres dan tanpa gambar kecil. PDF di atas 10 MB
  (`PDF_MAX_BYTES` = 10 × 1024 × 1024 byte) ditolak sebelum diunggah: "PDF terlalu besar (maks 10 MB)".
- File bertipe kosong atau `application/octet-stream` (sebagian penyedia file Android) dikenali dari isinya: 5 byte
  awal `%PDF-` → dikirim sebagai `application/pdf`. Saklar mati: isi file tidak pernah dibaca.
- Batas waktu unggah PDF: 60 dtk ditambah 1 dtk per 25 kB, maks 300 dtk (`uploadTimeoutMs`). Foto (sudah dikompres)
  tetap 60 dtk.
- Teks tahap memakai kata "bukti" ("Mengunggah bukti…", "Membaca bukti…", tombol simpan "Menunggu bukti..."), ikon
  dokumen menggantikan gambar kecil, dan "Pilih file lain" menggantikan "Foto ulang".
- Saklar mati: tidak ada tombol PDF, dan PDF yang terpilih lewat Galeri tetap ditolak seperti dulu ("Pilih file foto
  (JPG/PNG)").

**Tanggal dokumen** (keputusan pemilik produk 28 Okt 2026; server: `_check_row` di `routes/transactions.py`): aturan
yang sama dengan bot ("Tanggal di luar periode berjalan" di bagian "Kanal"), untuk baris form Catat dengan item Kotak
Struk dan untuk `ProofCard`. Tanggal dokumen = tanggal struk, atau tanggal WIB dari `paid_at`.
- Sebelum awal periode anggaran berjalan → "Tanggal di {struk|bukti}: {tgl} — di luar periode sekarang ({periode}).
  Catat untuk tanggal berapa?" dengan pilihan **Hari ini** dan **{tgl}**. Tanggalnya kosong sampai dipilih ("Pilih
  tanggal catat").
- Hari ini → cek dana dan limit harian seperti biasa. Tanggal dokumen → server mencatat di tanggal itu tanpa blok dana
  dan limit harian (`PAST_PERIOD_IGNORED` di `expense_rules.py`; limit juga tidak dinaikkan). Kunci amplop, amplop
  tabungan/sinking fund, dan kuota paket tetap menolak. Form tidak menawarkan Geser atau "limit ↑" dari dugaannya
  sendiri untuk baris itu; galat dana/limit yang tetap dijawab server (gajian berubah, sinkron offline sesudah gajian)
  tampil seperti biasa.
- Tanggal yang belum lewat dianggap salah baca → hari ini, dengan keterangan "Tanggal di {struk|bukti} ({tgl}) belum
  lewat — dicatat hari ini." Form dan kartu menggantinya sebelum menyimpan (juga untuk antrean offline dan umpan balik
  struk); server memakai aturan yang sama.
- Periode dari `GET /analytics/periods`: form memintanya sekali saat struk pertama mulai dibaca, kartu memakai satu
  permintaan bersama (disimpan 1 menit). Selama periode belum terbaca tidak ada pertanyaan, dan server tetap menerapkan
  aturannya. Bukti yang diblokir tidak ditanya; baris tanpa `receipt_item_id` tidak berubah.

**Share target dan service worker** (`sw.js`, `shareInbox.js`):
- Service worker menangani `POST /bagikan` di origin aplikasi (`isShareTarget`; POST lain tidak dicegat), sebelum cek
  GET. Share disimpan ke IndexedDB `jatahku-share`, store `shares` (terpisah dari antrean offline `jatahku-offline`),
  lalu dijawab 303 ke `/bagikan?s=<batch>`. Form yang tidak bisa dibaca atau disimpan (termasuk memori penuh) → 303 ke
  `/bagikan?err=baca`, dan entri batch itu yang sempat tersimpan dihapus lagi.
- Satu share = satu batch. Maks 10 file (`MAX_FILES`, sama dengan `MAX_FILES_PER_SHARE`; file berikutnya diabaikan);
  nilai bukan file dan file 0 byte diabaikan. Entri file `{id, batchId, seq, name, type, blob, createdAt}` berisi file
  asli. Teks menjadi satu entri `{id, batchId, seq, text, type: 'text/plain', createdAt}`: `title` lalu `text`, digabung
  baris baru (yang sama tidak diulang); `url` hanya bila tidak ada teks lain. Share tanpa file dan teks tidak menyimpan
  apa pun.
- Entri berisi bukti asli yang belum disamarkan dan tidak pernah di-log. Entri dihapus begitu server menerimanya, saat
  ditolak permanen, atau saat halaman membaca saklar mati (batch `?s=` itu). Logout oleh user sendiri mengosongkan
  store, dan pindah ke `/login` menunggu penghapusan itu maks 2 dtk. Sesi yang kedaluwarsa (refresh token ditolak) tidak
  menghapusnya: bukti tetap ada sampai user login lagi.
- Navigasi tetap NetworkFirst, tetapi hanya jawaban 2xx ber-`Content-Type` `text/html` yang disimpan sebagai app shell
  offline: 404, 5xx, redirect, atau berkas bukan HTML tidak lagi menimpa `/index.html`.
- `share_target` di `frontend/public/manifest.json` belum ada di branch ini (keputusan pemilik produk 28 Okt 2026), jadi
  menu Bagikan Android belum menampilkan Jatahku. PR kecil saat saklar dinyalakan menambah blok ini sebagai kunci
  tingkat atas di samping `"shortcuts"` (tambahkan koma sesudah larik `shortcuts`):

  ```json
    "share_target": {
      "action": "/bagikan",
      "method": "POST",
      "enctype": "multipart/form-data",
      "params": {
        "title": "title", "text": "text", "url": "url",
        "files": [{ "name": "files", "accept": ["image/*", "application/pdf"] }]
      }
    }
  ```

  Nama harus sama dengan kode: `action` = `POST /bagikan` (`isShareTarget`), `files` = `formData.getAll('files')`,
  `title`/`text`/`url` = kolom teks share.

**Halaman `/bagikan`** (`Bagikan.jsx`, `shareInbox.js`): route di dalam `Layout`, judul "Bagikan ke Jatahku". Belum
login → `/login`; entri lokal tetap, dan setelah login banner "Bukti menunggu" membawa user kembali ke sini.
- Saklar dibaca dari `/app/config` setiap putaran, bukan dari cache lokal, karena saklar mati menghapus share. Jawaban
  server boleh disimpan browser sampai 5 menit (`Cache-Control: public, max-age=300`), jadi perubahan saklar bisa sampai
  ke sini 5 menit kemudian. Gagal mengambil → nilai cache terakhir; belum pernah terbaca → ditahan seperti offline.
- Saklar mati → hanya "Fitur ini segera hadir.". Entri batch `?s=` itu dihapus dari HP, dan tidak ada permintaan Kotak
  Struk (juga tanpa kartu, teks `?err=`, dan permintaan amplop).
- Offline (atau saklar belum diketahui) → entri tetap, dengan "{n} bukti menunggu dikirim. Akan dikirim saat online."
  dan tombol "Kirim lagi". Event `online` selama halaman terbuka memulai putaran baru.
- Kirim: entri diunggah satu per satu ke `POST /kotak-struk/` (`source=pwa_share`, `upload_id` = id entri, `wait=10`,
  tepat satu `file` atau `text`), dengan teks tahap "bukti". Urutannya: entri yang belum pernah dicoba dulu, lalu yang
  paling lama tidak dicoba; sesamanya, share tertua dulu lalu urutan dalam share. File dikirim apa adanya (tidak
  dikompres), jadi semua file memakai batas waktu PDF (60 dtk + 1 dtk per 25 kB, maks 300 dtk); teks 60 dtk.
- Hasil tiap entri (`uploadOutcome`):
  - diterima (2xx berisi item) → entri dihapus, kartunya tampil;
  - dibuang (413, 415, 422 dari API) → entri dihapus, dengan baris "{nama file}: {pesan server}", atau "Bukti tidak bisa
    dikirim." bila pesannya bukan teks. 413 dari nginx sendiri tidak terbaca browser dan berakhir sebagai "disimpan"
    (lihat "Batas unggah `api.jatahku.com`");
  - disimpan (tanpa jawaban, lewat batas waktu, 5xx, 401, 429, 4xx lain, atau 2xx tanpa item) → entri tetap: "Bukti
    belum terkirim. Akan dikirim lagi saat online." (429: pesan server, atau "Terlalu banyak bukti. Coba lagi
    sebentar."). Putaran berhenti, entri itu pindah ke belakang antrean, dan "Kirim lagi" mengirim ulang dengan
    `upload_id` yang sama (tidak membuat item ganda).
- File di atas 10 MB dibuang di HP tanpa diunggah, dengan teks server untuk isinya: "PDF terlalu besar (maks 10 MB)",
  "Foto terlalu besar (maks 8 MB)", atau "Kirim foto (JPG/PNG/WebP), PDF, atau teks". Foto 8–10 MB tetap diputuskan
  server (413).
- Sesudah putaran unggah, halaman menampilkan kartu untuk semua bukti `siap` milik user
  (`GET /kotak-struk/?status=siap`, maks 50), jadi halaman ini juga tujuan "Tinjau" di banner. Item hasil unggahan yang
  masih `diterima`/`diproses` dipantau dengan `GET /kotak-struk/{id}` tiap 1,5 dtk, paling lama 30 dtk sejak diterima
  halaman.
- Satu `ProofCard` per id item: detail baru menggantikan yang lama di tempat yang sama, dan status yang lebih awal tidak
  menimpa yang lebih baru. Amplop dimuat sekali saat kartu pertama muncul. Kartu yang dicatat, dilewati, atau ditolak
  server menyegarkan daftar bukti menunggu.
- "Ke Transaksi" tampil bila tidak ada unggahan atau pantauan yang berjalan dan setiap kartu `siap` sudah ditangani.
  Tanpa kartu dan tanpa pesan: "Tidak ada bukti yang menunggu.".
- `?err=sw` → "Buka Jatahku sekali, lalu bagikan lagi." (share sampai ke server, lihat aturan nginx di "Menyalakan
  saklar"). `?err=baca` → "File yang dibagikan tidak bisa dibaca. Coba bagikan lagi." dan "Kalau memori HP penuh,
  kosongkan sedikit lalu bagikan lagi.". Kotak share yang tidak bisa dibaca halaman → kalimat pertama saja.
- Meninggalkan halaman menghentikan unggahan berikutnya; unggahan yang sedang berjalan tetap selesai.

**`ProofCard`** (`ProofCard.jsx`, `proofFormat.js`): satu kartu = satu transaksi untuk total dokumen, untuk semua jenis
(rincian per barang tetap di form Catat). Tanpa geser dana dan tanpa antrean offline.
- Badge jenis "QRIS", "Transfer", "Struk belanja", atau "Bukti bayar" (`tidak_dikenali`); QRIS/transfer dari aplikasi
  yang profilnya dikenali ditambah penerbit ("QRIS · GoPay"). Status bayar: "Berhasil", "Pending", atau "Gagal".
- Nominal: QRIS/transfer dengan total terbaca yang keyakinannya bukan `rendah`/`gagal` hanya ditampilkan (besar). Selain
  itu (tanpa total, keyakinan `rendah`/`gagal`, struk belanja, tidak dikenali) kolom "Nominal" bisa diubah: terisi total
  dokumen, juga bila item baru selesai dibaca sesudah kartu tampil, dengan label keyakinan ("total tidak terbaca",
  "kurang yakin, mohon dicek", "cek lagi nominalnya"). Nominal pecahan ditolak.
- Nama tampilan (nama panggilan rumah tangga, lalu nama dari bukti) dan "Ubah nama" (`PUT /kotak-struk/merchants/{id}`,
  bila item punya merchant). Tanggal dan jam bayar WIB ("26 Okt 2026, 08.12"; struk belanja dan tidak dikenali tanpa
  jam) dan kota. Tanggal sebelum periode berjalan: pilihan Hari ini/{tgl} (lihat "Tanggal dokumen" di atas).
- Amplop: daftar yang sama dengan form Catat (aktif, bukan tabungan/sinking fund), saran server paling depan. Saran yang
  yakin dipilihkan dan diberi label "· disarankan"; saran yang tidak yakin hanya ada di urutan pertama.
- "Catatan" (contoh "bakso 2, es teh (opsional)", maks 200 karakter): 600 ms sesudah berhenti mengetik →
  `POST /kotak-struk/{id}/saran`, lalu saran amplop dan "Keterangan: …" diperbarui (jawaban lama diabaikan).
- Peringatan, berurutan: alasan blokir; arah uang ("Ini top-up saldo, biasanya bukan pengeluaran.", "Ini uang masuk,
  biasanya bukan pengeluaran.", "Sepertinya transfer ke rekeningmu sendiri."); duplikat lunak ("Mirip "{keterangan}"
  yang dicatat {jam}. Sudah dicatat?"); lalu peringatan server apa adanya. Tidak ada langkah konfirmasi tambahan:
  menekan Simpan dengan peringatan yang terlihat sama dengan "Tetap catat" di bot.
- Tombol: **Simpan**; **Sama, lewati** (duplikat lunak, dan satu-satunya tombol lewati untuk bukti yang sudah
  tercatat); **Bukan pengeluaran** (selain bukti yang sudah tercatat). Simpan mati sampai kartu siap; alasan pertama
  yang menghalangi tampil di bawahnya ("Nominal tidak terbaca", "Pilih tanggal catat", "Pilih amplop dulu", atau "Butuh
  koneksi internet"), sedangkan alasan blokir tampil di peringatan.
- Simpan → `POST /transactions/` dengan `receipt_item_id`, `client_ref` (satu per kartu), dan tanggal catat:
  - 409 → teks server menjadi alasan blokir kartu: Simpan mati dan tombol lewati hilang (sama untuk 409/404 saat
    melewati);
  - koneksi putus, 5xx, atau 409 "sedang diproses" → hasil belum pasti: isian dikunci dan Simpan mengirim ulang
    permintaan yang sama ("… tidak akan tercatat dua kali.");
  - limit harian → tombol "Catat, naikkan limit hari ini"; dana kurang → "Pilih amplop lain lalu Simpan lagi.";
  - tercatat → "Tercatat di {amplop}." (ditambah pemberitahuan kuota bila ada) dan event `jatahku:txn-added`; dilewati
    → "Dilewati.".
- Offline: Simpan dan tombol lewati mati. Item yang belum `siap` hanya menampilkan badge dan alasannya (gagal: pesan
  `error` item).

**Banner "Bukti menunggu"** (`PendingProofsBanner.jsx`, `pendingProofs.js`):
- Hanya saat saklar menyala. Saklar mati (juga sebelum config terbaca): tanpa permintaan, tanpa IndexedDB, tanpa
  listener.
- Dipasang di `Layout` tepat sesudah banner antrean offline, jadi tampil di semua halaman kecuali `/bagikan` sendiri
  (juga `/bagikan/`; besar-kecil huruf diabaikan). Spec 5c menyebut "beranda dan Transaksi"; banner ini mengikuti pola
  banner antrean offline, yang tampil di semua halaman.
- Dua angka: share yang belum terkirim (jumlah entri IndexedDB `jatahku-share`) dan item `siap` milik user di server
  (`GET /kotak-struk/count?status=siap`). Server menghitung semua item `siap`, juga dari Telegram, chat web, dan scan
  form Catat yang ditinggalkan tanpa disimpan atau dihapus.
- Teks: "{u} bukti menunggu dikirim, {r} menunggu dicatat · Tinjau", "{u} bukti menunggu dikirim · Kirim", atau "{r}
  bukti menunggu dicatat · Tinjau"; keduanya 0 → banner tidak tampil. Ketuk → `/bagikan`.
- Dihitung ulang saat dipasang atau saklar menyala, setiap pindah halaman, pada event `online`, `jatahku:txn-added`,
  `jatahku:kotak-changed`, dan saat tab terlihat lagi. Tiap angka tampil begitu bacaannya sendiri selesai, dan jawaban
  lama tidak menimpa yang lebih baru. COUNT gagal → angka terakhir; IndexedDB gagal → 0.
- Banner tidak mengunggah apa pun. Share lokal dikirim halaman `/bagikan` (saat dibuka, pada event `online` selama
  halaman terbuka, atau lewat "Kirim lagi"), jadi share yang belum terkirim menunggu satu ketukan.

**Tips Settings dan rincian Admin**:
- Settings, tepat sesudah kartu Telegram, hanya saat saklar menyala: "Bagikan bukti bayar ke Jatahku: di Android,
  pasang Jatahku dari browser lalu pilih Jatahku di menu Bagikan. Di iPhone, bagikan bukti ke bot Telegram Jatahku."
  Teks ini menganggap menu Bagikan sudah ada (PR `share_target`).
- Admin → Dashboard → kartu "Scan Struk (bulan ini)" (`scanStats.js`, tidak bergantung saklar) menambah baris "Jenis
  dokumen: Struk belanja {n} · QRIS {n} · Transfer {n} · Tidak dikenali {n}" (jenis lain menyusul dengan kuncinya) dan
  tabel "Per penerbit": Penerbit, Total, Tercatat, Dikoreksi, dan "% dikoreksi" (dikoreksi / tercatat, dibulatkan; "–"
  bila belum ada yang tercatat), urut total terbanyak. Hanya pembaca QRIS dan transfer yang mengisi `issuer`, jadi
  selama saklar mati tabel itu tidak tampil. Server lama tanpa rincian → bagian itu tidak tampil. Angkanya dari
  `GET /admin/receipt-scans/stats` (lihat "Statistik Admin").

## API

Semua butuh login; item hanya terlihat pemiliknya (item orang lain = 404 "Bukti tidak ditemukan"). Rute memakai
garis miring penutup (`/kotak-struk/`); tanpa itu dijawab 307.

| Endpoint | Isi |
|---|---|
| `POST /kotak-struk/` | Multipart: `file` **atau** `text`, `source`, `upload_id` (≤ 64), `wait` (0–45 dtk, bawaan 0; koneksi DB dilepas selama menunggu). 201 item baru, 200 item yang sudah ada. Menjawab detail item |
| `GET /kotak-struk/?status=siap` | Item milik user dengan status itu (bawaan `siap`), terbaru dulu, maks 50 |
| `GET /kotak-struk/count?status=siap` | `{count}`: jumlah item milik user dengan status itu (bawaan `siap`), saringan sama dengan daftar tanpa batas 50; satu COUNT tanpa detail item (banner bukti menunggu di web) |
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
tabungan, dan kuota tetap menolak; form Catat dan kartu bukti (`ProofCard`) di web menanyakan "Hari ini" atau tanggal
dokumen lebih dulu (periode dari `GET /analytics/periods`; tanggal yang belum lewat diganti hari ini oleh form atau
kartu sebelum disimpan; lihat "Tanggal dokumen" di "Web dan PWA"), dan baris tanpa `receipt_item_id` tidak berubah.

## Saklar fitur

`features.receipt_inbox` di `/app/config` (AppSetting `app_config`, bawaan **mati**). Server membacanya lewat
`feature_enabled(db, "receipt_inbox", "web")` per item, untuk semua kanal termasuk bot; galat membaca → mati.

| | Saklar mati (bawaan produksi) | Saklar menyala |
|---|---|---|
| Pembaca | Hanya `struk_belanja`; bukti QRIS biasanya jatuh ke `tidak_dikenali`, transfer kadang terbaca `struk_belanja` | `qris.umum` dan `transfer.umum` didahulukan |
| Pesan bot untuk QRIS | Pesan struk lama berkeyakinan rendah ("⚠️ kurang yakin, mohon dicek") | Pesan bukti dengan tombol catatan dan "Bukan pengeluaran" |
| Teks OCR dan peta merchant | Teks yang terbaca seperti bukti bayar **tidak** disimpan dan tidak masuk peta merchant (nomor rekening/RRN tidak boleh tersimpan) | Bukti yang dibaca pembaca QRIS/transfer tidak pernah menyimpan teks OCR; penerimanya masuk peta |
| Form Catat (web) | Tanpa tombol PDF; PDF lewat Galeri ditolak seperti dulu | Tombol PDF |
| Banner "Bukti menunggu", tips Settings | Tidak tampil; banner tidak meminta apa pun ke server | Tampil |
| Halaman `/bagikan` | Hanya "Fitur ini segera hadir."; entri batch `?s=` itu dihapus dari HP, tanpa permintaan Kotak Struk | Mengunggah share, lalu `ProofCard` untuk tiap bukti `siap` |

**Tidak bergantung pada saklar**: penghapusan kuota scan, PDF/gambar lewat intake, transfer gagal tetap diblokir,
pencegahan ganda, baris hasil scan di form Catat (satu baris per item, `receipt_item_id`, alasan blokir, pertanyaan
tanggal, × melewati item), penangan `POST /bagikan` di service worker, dan rincian Scan Struk di Admin (lihat "Web dan
PWA"). Menu Bagikan Android juga tidak diatur saklar: Jatahku muncul di sana setelah `share_target` ada di manifest dan
PWA memperbarui manifestnya. Klien web membaca saklar dari cache `/app/config` (lihat "Menyalakan saklar"); halaman
`/bagikan` memintanya lagi setiap putaran (jawaban yang disimpan browser berumur paling lama 5 menit).

Menyalakan: ikuti urutan di "Menyalakan saklar" (gerbang korpus, nginx, batas unggah, saklar, uji HP tanpa share, PR
`share_target`, uji share).
Perintahnya (`PUT` mengganti **seluruh** nilai, jadi gabungkan dengan isi `GET /admin/settings/app_config` bila sudah
ada):

```
PUT /admin/settings/app_config?value={"features": {"receipt_inbox": {"web": true}}}
```

Nilai di query harus di-URL-encode. Berlaku untuk item berikutnya; item yang sudah `siap` tidak dibaca ulang.

## Konstanta

`app/services/kotak_struk/config.py`.

| Nama | Nilai | Arti |
|---|---|---|
| `WAIT_BOT_S` | 10 | Bot menunggu hasil sebelum menjawab "masih dibaca"; halaman `/bagikan` mengirim `wait` yang sama (`UPLOAD_WAIT_S`) |
| `WAIT_FORM_S` | 45 | Tombol Struk di form Catat menunggu sebelum 503 "sedang ramai"; batas atas `wait` di API |
| `STALE_PROCESSING` | 5 menit | Item `diproses` lebih lama dari ini dikembalikan ke antrean |
| `MAX_ATTEMPTS` | 3 | Percobaan baca sebelum `gagal` |
| `ITEM_EXPIRY` | 7 hari | `siap`/`gagal` tanpa konfirmasi → `kedaluwarsa` (dihitung dari selesai dibaca) |
| `RATE_PER_HOUR` | 30 | Bukti per user per jam, gabungan semua kanal (Redis `kotak:rate:{user_id}`; Redis mati → tidak dibatasi); menggantikan batas slowapi 30/jam di `scan-receipt` dan `/bot/chat/photo` |
| `MAX_FILES_PER_SHARE` | 10 | File per satu share. Klien memakai nilai yang sama (`shareInbox.js` `MAX_FILES`): service worker menyimpan 10 file pertama, sisanya diabaikan. Server sendiri tidak memakainya (tiap unggahan satu file) |
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
`outcome`. Data ini dipakai untuk menambah profil aplikasi. Tampilannya di Admin → Dashboard → kartu "Scan Struk (bulan
ini)" (`Admin.jsx`, `scanStats.js`): lihat "Tips Settings dan rincian Admin" di "Web dan PWA".

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
Bagian B tidak menambah paket maupun migrasi. Langkah manualnya di server hanya aturan nginx `/bagikan` dan, bila
perlu, batas unggah nginx api.jatahku.com (keduanya di bagian "Menyalakan saklar"); checklist-nya `AGENTS.md` "Deploy
Checklist — Bagikan ke Jatahku, Bagian B (web)".

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
   → `unrecognized` bertambah (sejak Bagian B juga di Admin → Scan Struk, baris "Jenis dokumen"). Bot menjawab "Bukti tidak bisa dibaca" untuk semua file → cek `journalctl -u jatahku`
   (biasanya `KOTAK_DIR` tidak ada atau tidak bisa ditulis).
5. **Saklar tetap mati sampai gerbang korpus lulus** (bagian berikut). Setelah itu nyalakan dengan urutan di
   "Menyalakan saklar", lalu kirim dua bukti QRIS dari merchant yang sama (catat yang pertama): yang kedua datang
   dengan ⭐.

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
sungguhan saat saklar dinyalakan (langkah terakhir "Menyalakan saklar"); butir server lain (tidak pernah tercatat dua
kali, transfer gagal tidak bisa dicatat) dicakup tes otomatis.

**Kalibrasi A14 menunggu sampel nyata** dari pemilik produk (bukti QRIS dan transfer dari 8 bank dan 4 e-wallet).
Di sana juga diselesaikan titik yang diparkir di "Batasan yang diketahui" dan label per aplikasi di `profiles.py`.

## Menyalakan saklar

Semua langkah saat `features.receipt_inbox` dinyalakan, berurutan. Aturan nginx boleh dipasang lebih dulu, langsung
sesudah Bagian B di-merge; ia harus sudah aktif sebelum PR `share_target` di-merge.

**Aturan nginx `/bagikan`** (di luar repo: konfigurasi nginx domain jatahku.com di HestiaCP). Share yang sampai ke
server karena service worker belum aktif dijawab 303 ke `/bagikan?err=sw` ("Buka Jatahku sekali, lalu bagikan
lagi."), dan `GET /bagikan` disajikan `app.html` seperti route SPA lain. Bila nginx tidak menyajikan `app.html` untuk
`/bagikan`, service worker hanya meneruskan jawaban server (mis. 404), jadi halaman itu tidak terbuka, juga sesudah
303 dari service worker.
1. Cek dulu cara route SPA disajikan sekarang:
   ```bash
   curl -sI https://jatahku.com/bagikan
   curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' -X POST https://jatahku.com/bagikan
   ```
2. Tambahkan blok ini ke konfigurasi nginx domain jatahku.com, di tempat yang sama dengan aturan route SPA yang ada
   (`app.html` disalin `deploy.sh` ke `/home/jatahku/web/jatahku.com/public_html/`):
   ```nginx
   location = /bagikan {
       if ($request_method = POST) { return 303 /bagikan?err=sw; }
       try_files /app.html =404;
   }
   ```
3. `sudo nginx -t && sudo systemctl reload nginx`.
4. Ulangi dua perintah di langkah 1. Hasil yang benar: GET → `200` dengan `Content-Type: text/html`; POST → `303` ke
   `…/bagikan?err=sw`.
   POST yang lebih besar dari `client_max_body_size` domain jatahku.com dijawab 413 oleh nginx sebelum `return` jalan,
   jadi share besar saat service worker belum aktif berakhir di halaman galat nginx, bukan teks `?err=sw` (POST di
   langkah 1 tanpa isi, jadi tidak menguji ini). Cek nilainya dengan `sudo nginx -T | grep client_max_body_size`; bila
   kecil (bawaan nginx 1m), tambahkan mis. `client_max_body_size 110m;` di dalam blok `location = /bagikan` (cukup
   untuk 10 file × 10 MB ditambah bungkus multipart; `100m` kurang sedikit).

**Batas unggah `api.jatahku.com`.** Foto yang dibagikan tidak dikompres (server menerima sampai 8 MB) dan PDF sampai
10 MB, padahal unggahan web selama ini foto terkompres ±300 KB. `client_max_body_size` nginx untuk api.jatahku.com harus
menerima file 10 MB ditambah bungkus multipart-nya (`10m` tidak cukup). Kalau terlalu kecil, nginx menjawab 413 sebelum
API, dan halaman galat nginx itu tanpa header CORS: browser tidak bisa membacanya dan menganggapnya koneksi gagal. Form
Catat lalu menampilkan galat koneksi dengan "Coba lagi", dan di `/bagikan` entrinya tidak dibuang: tetap "Bukti belum
terkirim", dicoba lagi di setiap putaran, dan terus dihitung banner (lihat "Batasan yang diketahui"). Karena itu cek
ini wajib sebelum saklar menyala. Cek tanpa token (tidak ada item yang dibuat):
```bash
head -c 10485760 /dev/urandom > /tmp/bukti-10mb.bin
curl -s -o /dev/null -w '%{http_code}\n' -X POST -F source=pwa_share -F file=@/tmp/bukti-10mb.bin https://api.jatahku.com/kotak-struk/
rm /tmp/bukti-10mb.bin
```
`413` = batas nginx terlalu kecil: naikkan `client_max_body_size` di konfigurasi nginx api.jatahku.com (mis. `12m`),
`sudo nginx -t && sudo systemctl reload nginx`, lalu ulangi cek. `401` = cukup (permintaan sampai ke API dan ditolak
karena tanpa login).

**Urutan:**
1. Gerbang korpus A14 lulus (`eval --real-only` keluar 0, bagian "Alat korpus dan gerbang rilis"), sisa privasi A68
   selesai (`privacy.html`, DPIA, formulir toko; `docs/mobile/PROGRESS.md`), dan pemilik produk memutuskan menyalakan.
2. Aturan nginx `/bagikan` aktif (di atas).
3. Batas unggah `api.jatahku.com` sudah dicek (di atas).
4. Nyalakan saklar (`PUT /admin/settings/app_config`, bagian "Saklar fitur").
5. Uji di HP sungguhan tanpa menu Bagikan (spec 7c), sebelum PR `share_target` di-merge: bot Telegram di Android dan
   iPhone, chat bot web, PDF dari tombol PDF di desktop, dan screenshot QRIS dari Galeri di form Catat.
6. Merge PR `share_target` (blok di "Share target dan service worker") segera sesudah langkah 5, lalu cek versi yang
   tayang (`https://jatahku.com/version.json`). Saklar harus menyala lebih dulu, paling sedikit 5 menit sebelumnya:
   share yang tiba di `/bagikan` saat saklar terbaca mati (juga dari cache, bila `/app/config` gagal diambil, atau dari
   cache browser yang berumur sampai 5 menit) dihapus. Jarak langkah 4 dan 6 dibuat pendek karena tips Settings sudah
   menyuruh user Android memilih Jatahku di menu Bagikan.
7. Langsung sesudah deploy `share_target`, uji alur share di HP sungguhan (spec 7c): PWA terpasang di Android Chrome
   (buka app sekali supaya manifest baru terbaca; bila Jatahku belum muncul di menu Bagikan, pasang ulang PWA-nya),
   share dari beberapa aplikasi bank dan e-wallet, saat belum login, dan saat offline; share Android → kartu
   konfirmasi ≤ 5 dtk saat online; share kedua dari merchant yang sama → saran yakin. Terakhir: folder file sementara
   (`KOTAK_DIR`) kosong setelah semua item diproses.

Catatan:
- Klien web membaca saklar dari cache `/app/config`, yang diambil ulang saat app dibuka atau tab terlihat lagi, paling
  cepat sejam sekali (`CONFIG_TTL_MS`). Perubahan saklar (nyala atau mati) baru sampai ke klien yang sudah terbuka pada
  kesempatan itu, jadi bisa butuh sejam atau lebih. Halaman `/bagikan` memintanya lagi setiap putaran, tetapi browser
  boleh memakai jawaban yang berumur sampai 5 menit (`Cache-Control: public, max-age=300`).
- PWA yang sudah terpasang memakai penangan service worker baru setelah app dibuka sekali sesudah deploy Bagian B
  (service worker baru langsung aktif: `skipWaiting` + `clients.claim`). Jatahku muncul di menu Bagikan setelah Chrome
  memperbarui manifest PWA itu, saat app dibuka dan tidak langsung.
- Penyimpanan permanen (`navigator.storage.persist()`) tidak diminta: saat memori HP sangat penuh, browser bisa
  menghapus data situs, termasuk share yang belum terkirim (seperti antrean offline). Share yang gagal disimpan karena
  memori penuh berakhir di teks `?err=baca` dengan petunjuk memori.
- Saklar dimatikan lagi sesudah PR `share_target` tayang: menu Bagikan tetap menampilkan Jatahku, dan `/bagikan`
  menjawab "Fitur ini segera hadir." lalu menghapus share itu.

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
- **Saklar mati: janji chat web tanpa banner.** Bukti yang belum selesai dibaca dalam 10 dtk di chat web dijawab "⏳
  Masih dibaca. Cek Bukti menunggu di beranda nanti.", tetapi banner "Bukti menunggu" hanya tampil saat saklar
  menyala. Diterima (jarang).
- **Form lintas situs ke `/bagikan`.** Situs mana pun bisa mengirim form `POST` ke `/bagikan` lewat navigasi lintas
  situs, dan service worker menyimpannya seperti share. Saat saklar menyala, halaman `/bagikan` mengunggahnya ke kotak
  user yang sedang login sebagai item sampah. Dibatasi batas intake (30 bukti/jam, 20 item belum selesai), file di
  atas 10 MB dibuang di HP, dan tidak ada yang tercatat tanpa Simpan. Cek asal/referer tidak dipasang: cek itu tidak
  bisa membedakan share asli dari form lintas situs tanpa referer, dan cek yang salah memblokir share asli. Diterima.
- **Ganti akun di HP yang sama** (ditinjau di review akhir Bagian B). Share disimpan tanpa id user, dan sesi yang
  kedaluwarsa tidak menghapusnya. Bila akun lain lalu login di HP itu, banner menghitung share akun sebelumnya dan
  `/bagikan` mengunggahnya ke kotak akun baru: detail bukti terlihat oleh akun itu, tetapi tidak ada yang tercatat tanpa
  Simpan.
- **Tanpa batas waktu permintaan** (ditinjau di review akhir Bagian B). Permintaan biasa ke API (`fetch`, termasuk
  `/app/config`) tidak punya batas waktu; hanya unggahan XHR yang punya. Koneksi yang menggantung membuat `/bagikan`
  tetap "Memuat…" (saat membaca `/app/config`) atau tanpa daftar bukti menunggu, dan angka server di banner tidak
  diperbarui (angka share lokal tetap tampil). Memuat ulang halaman memulihkannya.
- **Share yang tidak pernah bisa terkirim** (ditinjau di review akhir Bagian B). Entri yang setiap kali berakhir
  "disimpan" (lihat "Hasil tiap entri"; mis. 413 dari nginx tanpa header CORS, yang terbaca browser sebagai koneksi
  gagal) tidak pernah dibuang: `/bagikan` hanya punya "Kirim lagi", tanpa tombol buang, dan banner terus menampilkan
  "{n} bukti menunggu dikirim". Entri itu pindah ke belakang antrean, jadi entri lain terkirim lebih dulu di putaran
  berikutnya. Selama saklar menyala, yang menghapusnya hanya logout oleh user sendiri.

## Tes

`python -m unittest discover -s app/tests -t .` (perintah CI). Yang khusus Kotak Struk: `app/tests/test_kotak_*.py`
(intake, ekstraksi, pembaca, registri, worker, API, bot, pemeliharaan, saran, transaksi, korpus, skema, dokumen),
`test_receipt_scan.py`, `test_account_deletion.py`, `test_web_chat.py`. Cek API hanya bertambah:
`python -m app.scripts.openapi_cek`.

Web (Bagian B): `cd frontend && node --test src/lib/*.test.js src/native/*.test.js`, antara lain `shareInbox`,
`swShareTarget` (memuat `sw.js` asli dengan `self`, `caches`, dan `fetch` tiruan), `proofFormat`, `pendingProofs`,
`scanStats`, `multiAddRows`, `receiptScan`, `receiptProgress`, `offlineSync`, dan `native/web`. Komponen JSX
(`Bagikan.jsx`, `ProofCard.jsx`, banner, form Catat) tidak diuji otomatis; aturannya ada di modul-modul itu.
