# Bagikan ke Jatahku: bukti bayar QRIS & transfer — desain

**Tanggal:** 26 Okt 2026
**Status:** desain disetujui pemilik produk di chat, bagian 1–7 (26 Okt 2026). **Bagian A (server + bot) tayang 28 Okt 2026 06:01 WIB:** PR #130 (squash `8074a57`), migrasi `a7c4e2b9d1f3`; kuota scan dihapus, bot membaca PDF. Saklar `features.receipt_inbox` (pembaca QRIS/transfer) masih **mati** sampai gerbang korpus A14 lulus (menunggu sampel bukti asli). Bagian B (PWA/web) dikerjakan di branch `feat/bagikan-ke-jatahku-web`. Perilaku yang benar-benar dibangun, termasuk keputusan selama implementasi, ada di `docs/kotak-struk.md` di repo.
**Klasifikasi:** arsitektural. Menambah subsistem baru (Kotak Struk, registri pembaca dokumen, peta merchant) dan antarmuka yang nanti dipakai aplikasi Android/iOS.
**Rencana mobile terkait:** `docs/mobile/` paket FS (ADR-M16). Spec ini mengubah urutan dan cakupannya (lihat "Dampak ke rencana mobile").

## Penyesuaian saat menyusun rencana implementasi (26 Okt 2026)

Membaca kode lebih dalam menghasilkan penyederhanaan berikut. Bagian di bawah sudah diperbarui sesuai daftar ini.

1. **Saklar fitur memakai yang sudah ada:** `features.receipt_inbox` di `/app/config` (AppSetting `app_config`, default mati), bukan AppSetting baru.
2. **Tanpa field `receipt_note`.** Server menurunkan teks yang boleh dipelajari dari keterangan transaksi dikurangi nama merchant (`learnable_text`). Bot dan web cukup mengirim `receipt_item_id`.
3. **Bukti bayar di form Catat tampil sebagai baris biasa** yang sudah terisi (keterangan, tanggal bayar, amplop disarankan), bukan kartu baru. `ProofCard` hanya dipakai di halaman `/bagikan`.
4. **Melanjutkan share setelah login lewat banner** "bukti menunggu dikirim", karena halaman login belum mendukung parameter `next`.
5. **Klaim item oleh worker** memakai `UPDATE … WHERE status='diterima'` + cek rowcount, yang aman di Postgres maupun SQLite.
6. **Gagal simpan di `ProofCard`** ditangani seperti antrean offline (ganti amplop, naikkan limit harian), tanpa geser dana.
7. **LLM tetap dipanggil dari pembaca struk belanja** seperti sekarang. Slot pembaca LLM umum ditambahkan bersama invoice umum (FS-2).
8. **Satu item struk belanja boleh terhubung ke banyak transaksi** (catat per barang). Bukti bayar hanya satu.
9. **`RECEIPT_SCAN_LIMIT_BASIC` tetap ada di `Settings`** (tidak dipakai), supaya `.env` lama tidak membuat startup gagal.

## Masalah

- Hampir semua toko di Indonesia, termasuk warung kecil di pinggir jalan, menerima QRIS. Toko kecil hampir tidak pernah memberi struk: total disebut lisan, pembeli membayar lewat QRIS, dan transaksi selesai tanpa daftar barang.
- Satu-satunya bukti yang dipegang user adalah bukti bayar dari aplikasi bank atau e-wallet (gambar, kadang PDF).
- Jatahku sekarang hanya bisa membaca foto struk belanja. Parsernya mencari pola TOTAL, TUNAI, dan KEMBALI, jadi bukti QRIS tidak terbaca. Bot menolak PDF ("File belum didukung"). PWA belum bisa menerima file dari menu Bagikan.
- Akibatnya, belanja harian yang paling sering terjadi justru yang paling merepotkan untuk dicatat.

## Tujuan

User sedang membuka bukti bayar di aplikasi bank atau e-wallet, mengetuk **Bagikan**, lalu memilih Jatahku (PWA di Android) atau bot Telegram Jatahku. Jatahku membaca bukti itu, menyarankan amplop dari pembelajaran yang sudah ada, dan user mencatat dengan satu ketukan.

Arsitekturnya harus siap untuk jenis dokumen lain di masa depan, termasuk invoice umum (sewa server, pajak kendaraan di Samsat, dan sebagainya), tanpa perubahan struktur besar di kode.

**Kriteria sukses**
1. Share bukti QRIS dari Android (PWA terpasang) sampai ke kartu konfirmasi dalam ≤5 detik saat online.
2. Kirim bukti QRIS/transfer ke bot Telegram menghasilkan pesan berisi tombol amplop. Ketukan pada amplop bertanda ⭐ langsung mencatat.
3. Share kedua dari merchant yang sama, oleh anggota rumah tangga mana pun, menghasilkan saran amplop yang yakin (sudah dipilihkan).
4. Bukti yang sama tidak pernah tercatat dua kali. Transfer gagal tidak bisa dicatat. Top-up disarankan "bukan pengeluaran".
5. Tidak ada file asli yang tersisa di server setelah diproses.

## Keputusan pemilik produk (brainstorming 26 Okt 2026)

| # | Keputusan |
|---|---|
| K1 | Kanal sekarang: bot Telegram (termasuk chat bot di web) dan Web Share Target di PWA. Aplikasi native menyusul dan memakai API yang sama |
| K2 | User selalu mengonfirmasi sebelum tercatat. Yang dibaca adalah data transaksi (merchant/penerima, nominal, waktu, referensi), karena bukti QRIS tidak memuat daftar barang. Sukses = share → amplop tertebak benar → satu ketukan |
| K3 | Rilis 1: bukti bayar QRIS dan bukti transfer (m-banking dan e-wallet). Tagihan, invoice marketplace, dan invoice umum menyusul. Arsitektur wajib siap untuk itu tanpa perombakan |
| K4 | Kuota scan (Basic 15/bulan) **dihapus untuk semua input**: foto struk, PDF, bukti bayar, dan teks. Satu-satunya batas bulanan adalah kuota transaksi (Basic 50/bulan). Alasannya, kebiasaan mencatat tidak boleh terganggu. (Suara sudah tanpa kuota bulanan; batas anti-spam 20/jam di `/transcribe` tetap) |
| K5 | Pembelajaran amplop per rumah tangga. Pembelajaran lintas user dibahas di brainstorming terpisah; tabel dirancang supaya bagian itu tinggal ditambah |
| K6 | Pendekatan C: kontrak Kotak Struk (data, API, status, registri pembaca) final sejak rilis 1; worker berjalan di dalam proses API dan bisa dipindah ke service terpisah tanpa mengubah kode |
| K7 | Item yang tidak dikonfirmasi menjadi `kedaluwarsa` setelah 7 hari |

## Di luar cakupan rilis 1 (FS-2)

- Pembaca tagihan (PLN, BPJS, pulsa), invoice marketplace, dan invoice umum.
- Worker OCR sebagai service systemd terpisah (kodenya sudah siap; hanya konfigurasi deploy).
- Terusan email ke alamat khusus per user.
- Pembelajaran lintas user (petunjuk dari semua user per NMID) dan konsep "kategori umum" untuk amplop.
- Drag-and-drop PDF di desktop.
- Mencatat uang masuk sebagai pemasukan dari bukti transfer masuk (rilis 1 hanya menyarankan "bukan pengeluaran").
- Pratinjau gambar bukti di daftar Kotak Struk.
- Share target di iPhone (Safari tidak mendukung; user iPhone memakai bot Telegram sampai aplikasi iOS rilis).

## Konstanta

| Nama | Nilai | Arti |
|---|---|---|
| `KOTAK_WAIT_BOT_S` | 10 | Bot dan PWA menunggu hasil sebelum menjawab "masih dibaca" |
| `KOTAK_WAIT_FORM_S` | 45 | Tombol Struk di form Catat (mode tunggu) sebelum membalas "sedang ramai" |
| `KOTAK_STALE_PROCESSING` | 5 menit | Item `diproses` lebih lama dari ini dikembalikan ke antrean |
| `KOTAK_MAX_ATTEMPTS` | 3 | Setelah itu item `gagal` |
| `KOTAK_ITEM_EXPIRY` | 7 hari | Item siap/gagal yang tidak dikonfirmasi → `kedaluwarsa` |
| `KOTAK_RATE_PER_HOUR` | 30 | Bukti per user per jam, gabungan semua kanal |
| `KOTAK_MAX_FILES_PER_SHARE` | 10 | File per satu share |
| `KOTAK_MAX_PENDING` | 20 | Item belum selesai per user |
| `KOTAK_IMAGE_MAX_BYTES` | 8 MB | Gambar (batas piksel 30 MP tetap) |
| `KOTAK_PDF_MAX_BYTES` / `_PAGES` | 10 MB / 5 | PDF |
| `KOTAK_PDF_TIMEOUT_S` | 15 | Batas waktu baca PDF di proses terpisah |
| `KOTAK_NOTE_TTL_S` | 300 | Bot menunggu teks catatan setelah tombol "Tambah catatan" |
| `SOFT_DUP_WINDOW` | ±3 jam | Kecocokan lunak dengan transaksi manual |
| `CONFIDENT_SHARE` | 2/3 | Porsi minimal amplop teratas di peta merchant agar saran dianggap yakin |
| `OLD_PROOF_DAYS` | 60 | Bukti lebih tua dari ini diberi peringatan |

## Desain

### 1. Arsitektur dan alur

```
Kanal ──► POST /kotak-struk ──► item `diterima` (DB) ──► worker ──► item `siap` ──► konfirmasi ──► catat + belajar
 bot Telegram / chat web          file sementara           ekstrak teks        Dokumen Bayar     (jalur catat
 PWA share target                 hash, idempotensi        kenali jenis        saran amplop       yang sudah ada)
 web (tombol Struk, mode tunggu)                           parse, cek silang   tanda duplikat
 app native (nanti)                                        duplikat, arah uang
```

- **Satu pintu masuk.** Semua kanal membuat item lewat layanan intake yang sama. Tombol Struk di form Catat tetap memanggil `POST /transactions/scan-receipt` dengan mode tunggu: endpoint itu membuat item, menunggu sampai siap (≤ `KOTAK_WAIT_FORM_S`), lalu mengembalikan bentuk respons lama ditambah field baru. Kontrak frontend yang ada tidak putus.
- **Worker** (`app/services/kotak_struk/worker.py`) punya satu titik masuk `run_worker()`. Di rilis 1, worker dijalankan sebagai tugas asyncio di `lifespan` API (di samping scheduler).
  - Mengambil id item `diterima` tertua, lalu mengklaimnya dengan `UPDATE … SET status='diproses' WHERE id=:id AND status='diterima'` dan pengecekan rowcount (aman di Postgres dan SQLite).
  - Saat menyala dan setiap menit, item `diproses` yang lebih lama dari `KOTAK_STALE_PROCESSING` dikembalikan ke `diterima` dengan `attempts += 1`. Kalau `attempts ≥ KOTAK_MAX_ATTEMPTS` → `gagal`.
  - Batas satu OCR bersamaan yang sudah ada tetap berlaku. OCR dan baca PDF tidak memblokir event loop: OCR di thread executor seperti sekarang, PDF di proses terpisah.
- **Kabar selesai** lewat Redis pub/sub, kanal `kotak:done:{item_id}`. Penunggu (`wait_for_item(id, timeout)`) mendengarkan kanal itu. Kalau Redis mati, penunggu memeriksa status di database tiap 0,5 detik. Karena lewat Redis, worker bisa dipindah ke proses lain tanpa mengubah kode.
- **Konfirmasi dan pencatatan memakai jalur yang sudah ada.** Aturan pengeluaran, kuota transaksi, dan idempotensi tidak diduplikasi:
  - **Bot:** callback amplop `t_{key}_{idx}` beserta alur geser dana dan limit harian. Karena Kotak Struk adalah tabel `receipt_scans`, id item = `scan_id` yang sudah dibawa alur-alur itu. Semuanya bermuara ke `_receipt_feedback_saved`, yang diperluas menjadi hook "item tercatat".
  - **Web/PWA:** `POST /transactions` dengan `client_ref`, ditambah field opsional `receipt_item_id` (lihat bagian 5d).
- **Chat bot di web** mendapat fitur yang sama otomatis karena memakai handler bot lewat `web_adapter`.

### 2. Model data

Semua perubahan aditif. Tabel baru dibuat oleh `create_all`; kolom baru lewat `ALTER TABLE … ADD COLUMN IF NOT EXISTS` di `lifespan` (`app/main.py`), plus berkas alembic sebagai catatan, sesuai pola repo.

**2a. Kotak Struk = `receipt_scans` yang diperluas.** Metrik akurasi Admin dan feedback belajar yang ada tetap jalan.

| Kolom | Tipe | Isi |
|---|---|---|
| `source` | `String(20)` null | `telegram`, `web_chat`, `web_form`, `pwa_share`; nanti `web_upload` (drag-and-drop), `android`, `ios`, `email` |
| `status` | `String(16)` null, index | `diterima` → `diproses` → `siap` / `gagal` → `tercatat` / `dilewati` / `kedaluwarsa`. Null = baris lama (riwayat) |
| `doc_type` | `String(30)` null | `struk_belanja`, `qris`, `transfer`, `tidak_dikenali`; nanti `tagihan`, `invoice`, `invoice_marketplace` |
| `household_id` | `UUID` null, index | Cakupan duplikat dan learning |
| `upload_id` | `String(64)` null | Id unggahan dari klien. Unik per user (indeks unik parsial `(user_id, upload_id) WHERE upload_id IS NOT NULL`) |
| `file_sha256` | `String(64)` null, index | Hash isi file (untuk teks: hash teks ternormalisasi) |
| `content_type`, `pages` | `String(60)`, `Integer` null | Info file |
| `file_path` | `String(255)` null | Lokasi file sementara; dikosongkan saat file dihapus |
| `ref_hash` | `String(64)` null, index | HMAC nomor referensi (RRN, nomor transaksi) |
| `counterparty_key` | `String(80)` null, index | Kunci pihak penerima (2c) |
| `paid_at` | `DateTime(tz)` null | Waktu bayar lengkap dengan jam |
| `document` | `JSON` (JSONB di Postgres) null | Dokumen Bayar (2b) |
| `parser` | `String(40)` null | Nama pembaca, mis. `qris.umum` |
| `attempts` | `Integer` default 0 | Percobaan proses |
| `error` | `String(200)` null | Alasan gagal yang aman ditampilkan |
| `channel_meta` | `JSON` null | Data untuk mengabari kanal: `chat_id`, `status_message_id` (Telegram) |
| `processed_at`, `expires_at` | `DateTime(tz)` null | Jejak waktu |
| `transaction_ids` | `JSON` null | Id transaksi hasil dokumen ini |

**2b. Dokumen Bayar** (`app/services/kotak_struk/document.py`): dataclass berversi yang diserialisasi ke kolom `document`. Jenis dokumen baru mengisi field yang relevan tanpa perubahan skema.

```json
{
  "schema": 1,
  "doc_type": "qris",
  "issuer": "bca_mobile",
  "status": "berhasil",
  "flow": "keluar",
  "method": "qris",
  "paid_at": "2026-10-26T08:12:00+07:00",
  "counterparty": {"name": "SITI AMINAH", "city": "BANDUNG", "id_kind": "nmid",
                   "id_masked": "ID10…6544", "bank": null},
  "amounts": {"subtotal": 25000, "fee": 0, "tax": 0, "discount": 0, "total": 25000},
  "lines": [],
  "refs": [{"kind": "rrn", "masked": "…8812"}],
  "note": null,
  "confidence": {"total": "tinggi", "counterparty": "tinggi", "paid_at": "tinggi"},
  "evidence": ["templat BCA mobile QRIS", "status Berhasil"]
}
```

- `status`: `berhasil` | `gagal` | `pending` | `tidak_diketahui`.
- `flow`: `keluar` | `masuk` | `top_up` | `antar_rekening_sendiri` | `tidak_diketahui`.
- `method`: `qris` | `transfer` | `va` | `tunai` | `kartu` | `lainnya`.
- `lines[]`: `{kind: item|fee|tax|discount|shipping, name, qty, unit_price, amount, flag, note, suggestion}`. Kosong untuk QRIS dan transfer. Struk belanja memetakan `items`/`adjustments` lama ke sini.
- `note` = berita transfer bila ada.
- Nomor rekening tidak pernah disimpan utuh: hanya 4 digit terakhir (`id_masked`) dan HMAC (`counterparty_key`). RRN disimpan sebagai HMAC (`ref_hash`) dan versi tersamar.
- HMAC memakai kunci `KOTAK_HMAC_KEY` dari `.env`.
- `document.py` juga berisi adaptor `to_scan_receipt_response(item)` yang membangun respons lama `scan-receipt` (`merchant`, `date`, `total`, `confidence`, `items`, `adjustments`, `reconciliation`, …) ditambah field baru `doc_type`, `item_id`, `counterparty`, `flags`, `suggestion`.

**2c. Peta merchant per rumah tangga**: dua tabel baru.

`household_merchants`

| Kolom | Tipe |
|---|---|
| `id` | UUID PK |
| `household_id` | FK `households`, `ondelete=CASCADE` |
| `counterparty_key` | `String(80)` |
| `raw_name` | `String(100)` (nama di bukti terakhir) |
| `display_name` | `String(60)` null (nama panggilan dari user) |
| `city` | `String(60)` null |
| `last_seen_at`, `created_at` | `DateTime(tz)` |

Unik `(household_id, counterparty_key)`.

`merchant_envelope_map`

| Kolom | Tipe |
|---|---|
| `id` | UUID PK |
| `merchant_id` | FK `household_merchants`, `ondelete=CASCADE` |
| `envelope_id` | FK `envelopes`, `ondelete=CASCADE` |
| `count` | `Integer` default 1 |
| `last_user_id` | FK `users`, `ondelete=SET NULL`, null |
| `last_used_at` | `DateTime(tz)` |

Unik `(merchant_id, envelope_id)`.

**Format `counterparty_key`** (berlaku nasional, supaya pembelajaran lintas user nanti bisa memakai kunci yang sama):
- `nmid:<NMID huruf besar>` bila NMID tercantum.
- `nama:<nama>|<kota>` bila tidak ada NMID. Nama dan kota dinormalisasi: huruf kecil, tanda baca dibuang, spasi dirapatkan. Kota boleh kosong. Dipotong 80 karakter.
- `rek:<hmac>` untuk penerima transfer (HMAC dari kode bank + nomor rekening yang terbaca utuh). Kalau nomor rekening hanya terbaca tersamar → `nama:<nama>|<bank>`.

**2d. Masa simpan**
- File asli dihapus begitu item selesai diproses (`siap` atau `gagal`), dan `file_path` dikosongkan. Job scheduler tiap jam menghapus file yatim di folder sementara yang lebih tua dari 1 jam.
- Item `siap`/`gagal` yang tidak dikonfirmasi dalam `KOTAK_ITEM_EXPIRY` → `kedaluwarsa`. Barisnya disimpan tanpa teks OCR, supaya bukti yang sama tetap terdeteksi duplikat.
- Teks OCR (`ocr_lines`) dihapus setelah feedback atau 24 jam, seperti sekarang.

### 3. Pembaca dokumen

**3a. Ekstraksi teks** (`extract.py`) → `TextDoc(lines: list[str], kind: image|pdf_text|pdf_ocr|text, pages: int)`.
- **Gambar:** `read_receipt_lines` (RapidOCR + penyusun baris yang ada).
- **PDF:** `pypdfium2` (paket baru). Teks diambil dari lapisan teks; halaman tanpa teks dirender (≈200 dpi) lalu di-OCR. Berjalan di proses terpisah dengan batas waktu `KOTAK_PDF_TIMEOUT_S` dan batas memori. PDF terenkripsi atau lebih dari `KOTAK_PDF_MAX_PAGES` halaman ditolak dengan pesan spesifik. Skrip di dalam PDF tidak dijalankan.
- **Teks:** dibelah per baris, tanpa OCR.

**3b. Registri pembaca** (`registry.py`, `readers/`)

```python
class DocReader(Protocol):
    doc_type: str            # "qris", "transfer", "struk_belanja", nanti "invoice"
    name: str                # mis. "qris.umum"
    def detect(self, doc: TextDoc) -> float: ...                 # skor 0–1
    def parse(self, doc: TextDoc, ctx: ParseContext) -> DokumenBayar: ...
    def checks(self, d: DokumenBayar) -> list[Check]: ...        # cek silang
```

- Registri menjalankan `detect` semua pembaca terdaftar dan memakai skor tertinggi di atas ambang 0,5. Tidak ada yang lolos → `doc_type = tidak_dikenali`: nominal terbesar yang tampak sebagai total diambil dengan keyakinan `rendah`, atau tanpa nominal.
- **`struk_belanja`** membungkus `parse_receipt` yang ada beserta data belajarnya (alias toko, label total). Logikanya tidak diubah.
- **`qris.umum` dan `transfer.umum`** adalah pembaca berbasis pasangan label–nilai (`readers/labels.py`). Pola yang ditangani:
  - Label dan nilai sebaris ("Nominal  Rp25.000").
  - Label di atas nilai.
  - Ciri QRIS: `QRIS`, `NMID`, `Merchant PAN`, `Terminal ID`, `Acquirer`/`Penerbit`.
  - Ciri transfer: `Rekening Tujuan`, `Bank Tujuan`, `BI-FAST`, `Berita`, `Penerima`.
  - Ciri top-up: `Top Up`, `Isi Saldo`.
  - Ciri uang masuk: `Dana Masuk`, `Terima`.
- **Profil aplikasi** (`readers/profiles.py`) adalah data, bukan kode. Isinya: kata pengenal aplikasi (penerbit), sinonim label per field ("Nominal", "Jumlah", "Total Bayar", "Total Pembayaran", "Amount", dan seterusnya), dan keanehan tata letak. Menambah aplikasi biasanya cukup menambah satu entri profil. Pembaca khusus aplikasi hanya dibuat bila tata letaknya benar-benar menyimpang.
- Daftar aplikasi rilis 1 ditetapkan dari korpus (7a): 8 bank dan 4 e-wallet teratas.
- Angka dibaca dengan `amounts_in` yang ada, termasuk format `Rp25.000`, `Rp 25.000,00`, dan `IDR 25,000.00`. Tanggal dan jam dalam format Indonesia dan Inggris (`26 Okt 2026 08:12:33 WIB`, `26/10/2026 08.12`, `Oct 26, 2026`).

**3c. Cek silang dan arah uang** (`checks.py`)
- **Nominal:** `subtotal + fee (− discount) = total`. Selisih → keyakinan total turun ke `sedang` dan muncul peringatan.
- **Status:** `gagal` → item diblokir (`flags.blocked = "transaksi_gagal"`), tidak bisa dicatat. `pending` → peringatan.
- **Tanggal:** di masa depan → keyakinan tanggal `rendah`. Lebih tua dari `OLD_PROOF_DAYS` → peringatan.
- **Arah uang:**
  - `top_up` dan `masuk` → `flags.skip_suggestion` berisi alasannya.
  - Penerima transfer "mirip user": nama penerima ternormalisasi sama dengan nama user, atau minimal 2 kata nama user muncul di nama penerima → `flow = antar_rekening_sendiri`. Ini hanya pertanyaan ke user, tidak pernah otomatis.
  - User selalu bisa memilih "Tetap catat", kecuali `blocked`.
- **Keyakinan per field:** `tinggi` | `sedang` | `rendah`, dengan daftar `evidence`.

**3d. Deteksi duplikat** (`dedup.py`), berurutan, dalam cakupan satu rumah tangga:
1. `upload_id` sama (per user) → item yang sudah ada dikembalikan; tidak ada item baru.
2. `file_sha256` sama dengan item milik user yang belum selesai (`diterima`, `diproses`, `siap`) → item itu dikembalikan; tidak ada item baru. Ini menangani share ganda sebelum dikonfirmasi. `file_sha256` sama dengan item `tercatat` di rumah tangga → item baru dibuat dengan `flags.duplicate_of = {kind: "file", item_id}`, dan pencatatan diblokir.
3. `ref_hash` sama dengan item `tercatat` di rumah tangga → `flags.duplicate_of = {kind: "ref", item_id}`, dan pencatatan diblokir. Sama dengan item rumah tangga yang belum tercatat (mis. anggota lain baru share) → hanya peringatan "Bukti ini juga dibagikan {nama anggota}"; item mana pun yang dicatat lebih dulu membuat item lainnya terblokir.
4. **Lunak:** ada transaksi rumah tangga dengan nominal sama, `transaction_date` sama dengan tanggal bayar, dan `created_at` dalam `SOFT_DUP_WINDOW` dari `paid_at` → `flags.duplicate_of = {kind: "soft", transaction: {id, description, amount, created_at, envelope_name}}`. Ini tidak memblokir; user memilih "Sama, lewati" atau "Beda, catat".

**3e. Slot LLM.** Fallback `receipt_llm` tetap dipanggil dari pembaca struk belanja seperti sekarang (mati secara default, dengan plafonnya). Rilis 1 tidak memakainya untuk QRIS dan transfer. Invoice umum (FS-2) menambah pembaca LLM umum sebagai pembaca terakhir di registri, dengan prompt sendiri.

**3f. Susunan modul**

```
app/services/kotak_struk/
  __init__.py
  config.py      konstanta (bagian Konstanta)
  intake.py      buat item: validasi isi file, batas, idempotensi, simpan file sementara
  worker.py      run_worker(), klaim item, pipeline, pemulihan item macet, kabar Redis
  waiter.py      wait_for_item(id, timeout) — Redis pub/sub, cadangan cek DB
  extract.py     gambar → OCR, PDF → teks/render (proses terpisah), teks
  document.py    DokumenBayar + serialisasi + adaptor respons scan-receipt
  registry.py    pendaftaran dan pemilihan pembaca
  readers/       base.py, labels.py, profiles.py, struk_belanja.py, qris.py, transfer.py
  checks.py      cek silang, arah uang
  dedup.py
  merchants.py   counterparty_key, household_merchants, merchant_envelope_map
  suggest.py     saran amplop (bagian 4)
  record.py      hook "item tercatat": tandai item, transaction_ids, learning
```

- `receipt_parser.py` tidak berubah.
- `receipt_scan.scan_receipt()` menjadi pembungkus tipis: intake (source `web_form`), tunggu, lalu adaptor.
- `apply_feedback` tetap dipakai untuk struk belanja.

### 4. Saran amplop dan learning

**4a. Urutan sinyal** (`suggest.py`). Hasilnya `{envelope_id, envelope_name, confident, source: note|merchant|keyword|none}`:
1. **Catatan user** (bila ada) → `find_best_envelope(note)` yang sudah ada.
2. **Peta merchant rumah tangga.**
   - Kandidat hanya amplop `expense` yang aktif dan boleh dilihat user (amplop bersama + amplop pribadinya sendiri). Aturan ini sama dengan `find_best_envelope`.
   - Amplop dengan `count` terbesar menang; kalau seri, `last_used_at` terbaru.
   - `confident = True` bila `count` amplop itu ≥ `CONFIDENT_SHARE` × total `count` merchant (untuk amplop yang boleh dilihat).
3. **Kata kunci nama merchant** (`display_name` bila ada, selain itu `raw_name`) → `find_best_envelope`. `CATEGORY_KEYWORDS` ditambah kata yang sering muncul di QRIS: apotek, klinik, spbu, pertamina, laundry, fotokopi, bengkel, dan sejenisnya. Kategori yang ditambah memetakan ke nama amplop yang sudah ada polanya.
4. Tidak ada sinyal → tanpa saran.

Saran yakin dipilihkan otomatis dan ditandai ⭐ / "disarankan". Saran tidak yakin hanya diurutkan teratas.

**4b. Keterangan transaksi** (`compose_description`)
- **Nama tampilan** = `display_name` bila ada. Kalau tidak, `raw_name` dirapikan: huruf besar semua → huruf awal kapital. Singkatan dalam daftar (PT, CV, UD, SPBU, BRI, BCA, BNI, BSI, dan sebagainya) tetap huruf besar.
- **Tanpa catatan:** QRIS → `Siti Aminah (QRIS)`; transfer → `Transfer ke Budi Santoso`.
- **Dengan catatan:** `bakso 2, es teh (Siti Aminah)`.
- Panjang mengikuti batas 500 karakter yang ada.

**4c. Nama panggilan merchant.** Opsional dan hanya atas inisiatif user (tautan "Ubah nama" di kartu web; tidak ada di bot pada rilis 1). Disimpan di `household_merchants.display_name` dan berlaku untuk seluruh rumah tangga. Jatahku tidak pernah meminta user mengisinya.

**4d. Aturan belajar** (`record.py`, dipanggil setelah transaksi tercatat)
- Hanya dari transaksi yang benar-benar tercatat. Melewati atau membatalkan item tidak mengajari apa pun.
- `merchant_envelope_map(merchant, amplop terpilih).count += 1` (buat bila belum ada), lalu isi `last_user_id` dan `last_used_at`. Item → `tercatat`, dan id transaksi ditambahkan ke `transaction_ids`.
- **Kata kunci:** untuk transaksi dari bukti bayar, `user_envelope_keywords` hanya belajar dari catatan user, yaitu keterangan transaksi setelah nama merchant (nama asli, nama panggilan) dan kata "QRIS"/"transfer ke" dibuang (`learnable_text`). Caranya, `after_expense_recorded(db, user, envelope_id, description, learn_text=None)` mendapat parameter opsional: bila `learn_text` diisi (termasuk string kosong), yang dipelajari adalah `learn_text`, bukan `description`. Server menghitungnya dari item (`learn_text_for_item`), jadi klien tidak mengirim catatan terpisah.
- Struk belanja tidak berubah: saran per barang tetap memakai kata kunci, dan feedback tetap lewat `apply_feedback`.
- Hapus akun: `last_user_id` → NULL (FK). Peta tetap milik rumah tangga. Jalur hapus rumah tangga di `account_deletion.py` ikut menghapus `household_merchants` (cascade ke peta).

### 5. Kanal dan layar konfirmasi

**5a. Bot Telegram dan chat bot web** (`app/bot/receipt_cmd.py`, `handlers.py`)
- **`handle_non_text`:** foto, dokumen gambar, dan dokumen PDF → `handle_receipt_document` (pengganti `handle_receipt_photo`) → intake (source `telegram` atau `web_chat` menurut kanal) → `wait_for_item(KOTAK_WAIT_BOT_S)`. Album: tiap foto satu item.
- **Teks bukti:** di `handle_message`, sebelum NLP, teks dianggap bukti bila semua syarat ini terpenuhi:
  - minimal 2 baris;
  - ada nominal Rp;
  - ada kata status (`berhasil`, `sukses`, `successful`);
  - ada minimal satu label (`referensi`, `ref`, `rrn`, `merchant`, `penerima`, `tujuan`, `nmid`).

  Teks lain tetap ke NLP.
- **Pesan menurut hasil:**
  - `struk_belanja` → pesan struk yang ada sekarang (rincian, cocok/selisih), tanpa baris sisa kuota.
  - `qris`/`transfer` → `"{QRIS|Transfer} · {nama} · {kota}\n{Rp} · {tgl jam} · {status}\n\nMasuk ke amplop mana?"` dengan tombol:
    - amplop (yang disarankan teratas, ⭐ bila yakin);
    - **✏️ Tambah catatan** (`kn_{key}`);
    - **🚫 Bukan pengeluaran** (`kx_{item_id}`);
    - **❌ Batal** (`struk_no_{item_id}`, yang sudah ada).
  - Payload Redis `txn:{key}` yang sudah ada ditambah `kind: "proof"` dan `note`. `desc` = hasil `compose_description`.
  - **Duplikat `ref`/`file` yang sudah tercatat:** "Bukti ini sudah tercatat {tgl} di {amplop}", tanpa tombol catat.
  - **Duplikat lunak:** "Mirip '{keterangan}' yang dicatat {jam}, sama?" dengan tombol **Sama, lewati** dan **Beda, catat**. **Beda, catat** menampilkan tombol amplop.
  - **Top-up / uang masuk / rekening sendiri:** penjelasan singkat, tombol **Oke, lewati** dan **Tetap catat**.
  - **Transaksi gagal:** pemberitahuan saja.
  - **`tidak_dikenali`:** total yang terbaca (bila ada) dengan tombol amplop, atau saran ketik manual seperti sekarang.
- **Tambah catatan:** bot membalas "Ketik isi belanjaannya (atau /batal)", lalu menyimpan `kotak:note:{tg_user_id} = {txn_key, item_id, message_id}` (TTL `KOTAK_NOTE_TTL_S`). Pesan teks berikutnya dari user itu menjadi catatan, sebelum NLP. Payload diperbarui, saran dihitung ulang dengan catatan, dan pesan tombol di-edit.
- **Lewat batas tunggu:** bot membalas "Masih dibaca, nanti kukabari" dan menyimpan `chat_id` serta `message_id` status di `channel_meta`. Worker yang menyelesaikan item ber-source `telegram` mengedit pesan itu menjadi pesan hasil. Untuk `web_chat`: "Masih dibaca, cek Bukti menunggu di beranda nanti."
- **Pencatatan:** `_receipt_feedback_saved(user_id, scan_id, …)` dipanggil oleh semua jalur catat bot (langsung, geser dana, limit harian). Hook ini diperluas: bila item ber-`doc_type` selain `struk_belanja` → `record.mark_recorded(item, txn, envelope, note)`; selain itu `apply_feedback` seperti sekarang. Baris "sisa scan" dihapus dari semua pesan.

**5b. Web Share Target di PWA (Android)**
- **`public/manifest.json`:**

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

- **`src/sw.js`:** penangan `fetch` untuk `POST /bagikan`. Ia membaca `formData()`, menyimpan tiap file (maksimal `KOTAK_MAX_FILES_PER_SHARE`) dan teks ke IndexedDB store `shares` (`{id, batchId, name, type, blob|text, createdAt}`), lalu `Response.redirect('/bagikan?s=<batchId>', 303)`. Logika penyimpanan berupa fungsi murni di `src/lib/shareInbox.js`, supaya bisa diuji dan dipakai halaman.
- **Nginx:** `POST /bagikan` yang lolos ke server (service worker belum aktif) dibalas `303` ke `/bagikan?err=sw`. Halaman lalu menampilkan "Buka Jatahku sekali, lalu bagikan lagi."
- **Halaman `/bagikan`** (route baru di `App.jsx`, di dalam `Layout`):
  - Belum login → login seperti biasa. Data di IndexedDB tetap aman, dan setelah login banner "N bukti menunggu dikirim · Kirim" membawa user kembali ke `/bagikan`.
  - Offline → banner "N bukti menunggu dikirim"; dikirim saat online (pemicu: app dibuka, event online).
  - Tiap entri diunggah lewat `api.uploadForm('/kotak-struk', fd)` dengan `source=pwa_share`, `upload_id = id entri`, dan `wait = KOTAK_WAIT_BOT_S`. Entri dihapus dari IndexedDB setelah server menerimanya.
  - Teks tahap memakai `receiptProgress.js` dengan kata benda "bukti" (lihat Koordinasi).
  - Hasilnya **`ProofCard`** per item. Beberapa item tampil bertumpuk. Item yang masih `diterima`/`diproses` dipantau dengan `GET /kotak-struk/{id}` tiap 1,5 detik sampai 30 detik.
- **`ProofCard`** (komponen baru, dipakai di `/bagikan`, form Catat, dan daftar "Bukti menunggu"):
  - Badge jenis dan penerbit, serta status.
  - Nominal besar.
  - Nama tampilan + "Ubah nama".
  - Tanggal, jam, dan kota.
  - Pilihan amplop (yang disarankan dipilihkan bila yakin, berlabel "disarankan").
  - Kolom catatan (placeholder `bakso 2, es teh (opsional)`). Saat catatan berubah (debounce 600 ms) → `POST /kotak-struk/{id}/saran`.
  - Peringatan duplikat dan arah uang.
  - Tombol **Simpan** dan **Bukan pengeluaran**.
- **Simpan:** `POST /transactions` dengan `client_ref`, `receipt_item_id`, dan `transaction_date` = tanggal bayar. Penolakan ditangani seperti antrean offline: limit harian → "Catat, naikkan limit hari ini"; dana kurang → pilih amplop lain. Geser dana tetap tersedia lewat form Catat.
- **Logout** mengosongkan store `shares`.
- **Tips di Settings:** "Di Android: pasang Jatahku dari browser, lalu pilih Jatahku di menu Bagikan. Di iPhone: bagikan bukti ke bot Telegram Jatahku." Ditampilkan ke semua orang, tanpa deteksi platform di komponen (aturan mobile #1).

**5c. Web (form Catat, desktop, dan dalam aplikasi)**
- `POST /transactions/scan-receipt` menerima gambar **atau PDF** (field `image` tetap). Respons lama ditambah `doc_type`, `item_id`, `counterparty`, `flags`, dan `suggestion`.
- **Form Catat:** bila `doc_type` ∈ {`qris`, `transfer`, `tidak_dikenali`}, hasil scan menjadi satu baris biasa yang sudah terisi (keterangan = `description_preview`, tanggal bayar, amplop disarankan bila yakin, `receipt_item_id`). Bukti yang terblokir menampilkan alasannya di baris dan tidak bisa disimpan. Peringatan (duplikat lunak, top-up) tampil di pesan hasil scan. Screenshot QRIS dari Galeri ikut dikenali.
- **Lapisan native:** antarmuka baru `native.files.pickDocument() → Promise<File|null>` (gambar atau PDF). Web memakai `<input type=file accept="image/*,application/pdf">`; Capacitor menyusul di paket B20–B22. Tombol kecil **PDF** di samping Foto/Galeri pada `ReceiptInput size="sm"`.
- **`useReceiptScan`** (dari rencana kamera) menerima `application/pdf`: tanpa kompresi, ditolak bila di atas `KOTAK_PDF_MAX_BYTES`.
- **Banner** "N bukti menunggu dicatat · Tinjau" di beranda dan Transaksi (pola sama dengan banner antrean offline), dari `GET /kotak-struk?status=siap`. **Tinjau** membuka lembar berisi `ProofCard` per item. Ini bentuk minimal UI Kotak Struk di rilis 1.

**5d. API**

| Endpoint | Isi |
|---|---|
| `POST /kotak-struk` | Multipart: `file` atau `text` (salah satu), `source`, `upload_id` (≤64), `wait` (0–45, default 0). 201 item baru / 200 item yang sudah ada (upload_id sama). Error: 413 terlalu besar, 415 bukan gambar/PDF/teks, 429 batas per jam atau `KOTAK_MAX_PENDING` |
| `GET /kotak-struk?status=siap` | Item milik user, terbaru dulu, maksimal 50 |
| `GET /kotak-struk/{id}` | Detail item (pemilik saja) |
| `POST /kotak-struk/{id}/saran` | `{note}` → `{suggestion, description_preview}` |
| `POST /kotak-struk/{id}/lewati` | `{reason: bukan_pengeluaran \| duplikat \| batal}` → `dilewati` |
| `PUT /kotak-struk/merchants/{merchant_id}` | `{display_name}` (≤60, dibersihkan); anggota rumah tangga merchant itu saja |
| `POST /transactions`, `/transactions/batch` | Field opsional baru `receipt_item_id` (UUID) |
| `GET /transactions/scan-receipt/quota` | Tetap ada untuk klien lama; `limit: null`, `remaining: null` |

**Detail item:**

```json
{
  "id": "…", "status": "siap", "doc_type": "qris", "source": "pwa_share",
  "created_at": "…", "paid_at": "…", "document": { },
  "merchant": {"id": "…", "name": "Siti Aminah", "display_name": null},
  "suggestion": {"envelope_id": "…", "envelope_name": "Makan", "confident": true, "source": "merchant"},
  "description_preview": "Siti Aminah (QRIS)",
  "flags": {"duplicate_of": null, "skip_suggestion": null, "blocked": null, "warnings": []},
  "error": null
}
```

**Aturan `receipt_item_id` di `POST /transactions`:**
- Item harus milik user dan berstatus `siap` (struk belanja: `siap` atau `tercatat`, karena dicatat per barang), serta tidak `blocked` dan tidak duplikat yang sudah tercatat. Kalau tidak → 409 dengan `detail` yang jelas.
- Idempotensi `client_ref` dicek lebih dulu, jadi kirim ulang tetap mengembalikan transaksi yang sama.
- Setelah commit → `learn_text_for_item` untuk `after_expense_recorded`, lalu `record.mark_recorded(…)` dalam request yang sama, best-effort: gagal di sini tidak membatalkan transaksi, hanya dicatat di log.
- **Batch:** item ditandai tercatat bila minimal satu transaksi dengan `receipt_item_id` itu tercatat.

### 6. Kegagalan, privasi, dan batas

**6a. Kegagalan**

| Kejadian | Perilaku |
|---|---|
| Isi file bukan gambar/PDF (cek magic bytes) | 415 saat intake, tidak masuk antrean |
| Antrean ramai | Item menunggu di DB. Bot/PWA menampilkan "masih dibaca". `scan-receipt` setelah `KOTAK_WAIT_FORM_S` → 503 "Scan struk sedang ramai" seperti sekarang; item tetap diproses dan muncul di banner |
| Worker mati atau API restart | Pemulihan item macet (bagian 1). Setelah `KOTAK_MAX_ATTEMPTS` → `gagal`, file dihapus |
| PDF terenkripsi / > 5 halaman / rusak / lewat batas waktu | `gagal` dengan pesan spesifik: "PDF terkunci kata sandi", "PDF lebih dari 5 halaman", "PDF tidak bisa dibaca" |
| Paket OCR atau `pypdfium2` belum terpasang | `gagal`: "Baca bukti sedang tidak bisa. Catat manual dulu." Fitur lain tidak terpengaruh |
| `tidak_dikenali` | Item siap dengan nominal keyakinan rendah atau tanpa nominal → isi manual |
| Saldo kurang / limit harian / kuota 50 transaksi habis | Item tetap `siap`. Alur geser dana, naikkan limit, dan pesan kuota yang ada berlaku |
| Redis mati | Penunggu memeriksa DB. Tombol bot butuh Redis seperti alur bot sekarang |
| Kanal Telegram tidak bisa dikabari (pesan status terhapus) | Worker mengirim pesan baru ke `chat_id` |

**6b. Privasi dan keamanan**
- **Folder file sementara** `/var/lib/jatahku/kotak/` (mode 0700, milik `jatahku`), di luar `backup.sh`. Nama file = id item; file tidak pernah disajikan ke browser.
- **Data tersimpan:** hanya field Dokumen Bayar. Nomor rekening: 4 digit + HMAC. RRN: HMAC + tersamar. Tanpa pratinjau gambar.
- **Data pribadi pihak ketiga:** nama penerima transfer disimpan karena menjadi keterangan transaksi milik user. Dicatat untuk DPIA ringkas (paket O05–O07).
- **PDF:** proses terpisah dengan `resource.setrlimit` (memori dan CPU) dan batas waktu. Terenkripsi ditolak. Tanpa eksekusi skrip.
- **Hak akses:** item Kotak Struk hanya terlihat oleh pemiliknya. Yang berlaku untuk rumah tangga: peta merchant, nama panggilan, dan cakupan deteksi duplikat.
- **IndexedDB `shares`:** entri dihapus setelah terunggah; seluruh store dikosongkan saat logout.
- **LLM** tetap mati untuk bukti bayar. Bila nanti dinyalakan (invoice umum), berlaku paket A21–A22 (izin eksplisit sebelum foto dikirim ke Groq).

**6c. Batas**
- **Kuota scan dihapus:**
  - `get_quota`/`ScanQuotaExceeded` tidak lagi memblokir.
  - `RECEIPT_SCAN_LIMIT_BASIC` dihapus dari konfigurasi dan dokumentasi.
  - Pesan dan UI "sisa scan" dihapus di bot dan web.
  - `GET …/quota` mengembalikan tanpa batas.
  - Plafon LLM global dan kuota LLM per user tetap.
- **Batas per jam:** satu batas gabungan semua kanal `KOTAK_RATE_PER_HOUR` (Redis `kotak:rate:{user_id}`), menggantikan `bot:scan:{tg_id}` (20/jam) dan batas web 30/jam yang terpisah. Fail open bila Redis mati, seperti sekarang.
- `KOTAK_MAX_FILES_PER_SHARE`, `KOTAK_MAX_PENDING`, dan batas ukuran sesuai tabel Konstanta.

### 7. Pengujian, gerbang rilis, dan peluncuran

**7a. Korpus uji (FS.5, prasyarat)**
- **Isi:** bukti QRIS dan transfer dari 8 aplikasi bank dan 4 e-wallet teratas, minimal 3 contoh per aplikasi per jenis. Contoh negatif: top-up, transfer gagal, uang masuk, transfer ke rekening sendiri. Plus 4 struk Indomaret yang sudah ada.
- **Sumber:** HP pemilik produk dan tim, serta user awal yang bersedia.
- **Yang masuk repo** (`app/tests/fixtures/kotak/`): hanya baris OCR atau teks PDF yang sudah disamarkan (nomor rekening, RRN, nama orang pribadi), bersama hasil yang diharapkan (`doc_type`, `issuer`, `total`, `paid_at`, `counterparty.name`, `status`, `flow`). Gambar asli tidak masuk repo.

**7b. Tes otomatis** (CI yang ada: `pytest`, `node --test src/lib/*.test.js src/native/*.test.js`, `npm run build`)
- **Pembaca dan registri:** tiap contoh korpus → hasil yang diharapkan. Struk belanja tidak berubah (tes `test_receipt_scan` lama lulus).
- **Cek silang:** nominal + biaya, status gagal/pending, aturan tanggal, arah uang (termasuk "mirip user").
- **Duplikat:** keempat lapis; cakupan rumah tangga; batas ±3 jam.
- **Saran dan learning:**
  - Aturan 2/3 dan seri `last_used_at`.
  - Amplop pribadi anggota lain tidak pernah disarankan.
  - `learn_text` (nama merchant tidak masuk kata kunci).
  - Learning hanya setelah tercatat.
- **Worker:** klaim (Postgres dan cadangan SQLite), pemulihan item macet, batas percobaan, file terhapus, kabar Redis dan cadangan DB.
- **Intake:** magic bytes, ukuran, PDF terenkripsi/halaman/batas waktu.
- **API:**
  - Unggah idempoten, `wait`, `saran`, `lewati`, nama panggilan.
  - `receipt_item_id` di `/transactions` (sukses, 409, kirim ulang).
  - Kuota tanpa batas, batas per jam.
- **Bot** (pola `test_web_chat`): foto, PDF, teks bukti, teks biasa tetap ke NLP, tombol catatan, duplikat, lewat batas tunggu.
- **Frontend:** `shareInbox.js` (simpan, ambil, hapus, kosongkan saat logout), alur halaman `/bagikan` sebagai fungsi murni (lanjut setelah login, offline), `compose`/format kartu, `native.files.pickDocument`.

**7c. Gerbang rilis**
- [ ] Korpus QRIS dan transfer: `total`, `paid_at` (tanggal), dan `status` benar ≥95%; `counterparty.name` benar ≥90%
- [ ] `doc_type` benar ≥98%, dan tidak ada struk belanja yang dikenali sebagai bukti bayar
- [ ] Bukti yang sama dibagikan dua kali tidak pernah tercatat dua kali
- [ ] Transfer gagal tidak bisa dicatat; top-up disarankan "bukan pengeluaran"
- [ ] Share Android → kartu konfirmasi ≤5 detik saat online
- [ ] Share kedua dari merchant yang sama dalam satu rumah tangga → saran yakin
- [ ] Folder file sementara kosong setelah semua item diproses

**Uji di HP sungguhan sebelum merge:**
- PWA terpasang di Android Chrome: share dari beberapa aplikasi bank dan e-wallet, saat belum login, dan saat offline.
- Bot Telegram di Android dan iPhone.
- Chat bot di web.
- PDF dari tombol PDF di desktop.
- Screenshot QRIS dari Galeri di form Catat.

**7d. Peluncuran**
1. **Server:** Kotak Struk, pembaca, perubahan bot, dan penghapusan kuota scan. Pembaca `qris` dan `transfer` aktif bila `features.receipt_inbox` (platform `web`) di `/app/config` menyala, lewat AppSetting `app_config` → `{"features": {"receipt_inbox": {"web": true}}}`, setelah gerbang lulus. Bila mati, registri hanya memakai `struk_belanja`. Klien memakai saklar yang sama untuk banner, halaman `/bagikan`, dan tombol PDF.
2. **Langkah manual sekali di server:**
   - `sudo -u jatahku /opt/jatahku/venv/bin/pip install pypdfium2==<versi yang sama dengan requirements.txt>`. Versinya dipin di `requirements.txt` pada tugas ekstraksi PDF.
   - `install -d -m 0700 -o jatahku /var/lib/jatahku/kotak`.
   - Tambah `KOTAK_HMAC_KEY` (acak 32 byte) ke `/opt/jatahku/.env`.
   - Aturan nginx `POST /bagikan` → 303.
3. **PWA:** manifest `share_target`, `sw.js`, halaman `/bagikan`, `ProofCard`, banner.
4. **Pemantauan:** Admin → Scan Struk diperluas dengan rincian per `doc_type` dan `issuer`, jumlah `tidak_dikenali`, dan tingkat koreksi. Data ini dipakai untuk menambah profil aplikasi.

## Koordinasi dengan rencana Foto Struk dari Kamera

Rencana `claude/foto-struk-kamera-rencana.md` (sesi lain, 26 Okt 2026) menyentuh `ReceiptInput.jsx`, `useReceiptScan`, `api.js` (`uploadForm`, `xhrUpload.js`), `receiptProgress.js`, `Layout.jsx`, dan `manifest.json`.

- **Urutan:** rencana kamera dikerjakan dan di-merge lebih dulu. Fitur ini memakai hasilnya: `api.uploadForm`, `receiptProgress`, `useReceiptScan`, `ReceiptInput size="sm"`. Kalau rencana kamera belum jalan saat implementasi dimulai, potongan itu dibuat persis sesuai spec kamera (nama, bentuk, perilaku), bukan versi kedua.
- **Tambahan kecil di atas hasil rencana kamera:**
  - `stageLabel` menerima `noun` opsional (`'struk'` default, `'bukti'` untuk share): "Membaca bukti…".
  - `failureMessage` tidak lagi memakai contoh kuota scan, karena kuota scan dihapus.
  - `useReceiptScan` menerima PDF (5c).
  - `ReceiptInput size="sm"` mendapat tombol PDF.
  - `manifest.json`: `share_target` ditambahkan di samping shortcut "Foto struk".
- Risiko yang dicatat spec kamera ("kirim ulang setelah jawaban hilang bisa menghitung satu scan lagi di kuota Basic") hilang dengan sendirinya karena kuota scan dihapus.

## File yang berubah (perkiraan)

**Backend**
- Baru: `app/services/kotak_struk/` (semua modul di 3f), `app/api/routes/kotak_struk.py`, `app/tests/test_kotak_*.py`, `app/tests/fixtures/kotak/`, berkas alembic baru.
- Ubah:
  - `app/models/models.py`: kolom `ReceiptScan`, dua model baru.
  - `app/main.py`: ALTER aditif, router, `run_worker` di `lifespan`.
  - `app/services/receipt_scan.py`: pembungkus, kuota dilepas.
  - `app/api/routes/transactions.py`: `scan-receipt` menerima PDF; field `receipt_item_id` di `TransactionCreate` dan item `BatchTransactionCreate` (model request ada di file ini); kuota.
  - `app/services/expense_rules.py`: `after_expense_recorded(learn_text=…)`.
  - `app/services/txn_nlp.py`: kata kategori.
  - `app/bot/receipt_cmd.py`, `app/bot/handlers.py`: dispatcher dokumen, teks bukti, tombol baru, `_receipt_feedback_saved`.
  - `app/services/scheduler.py`: kedaluwarsa dan file yatim.
  - `app/services/account_deletion.py`.
  - `app/api/routes/admin.py`: statistik.
  - `app/core/config.py`: `KOTAK_HMAC_KEY`, `RECEIPT_SCAN_LIMIT_BASIC` dihapus.
  - `requirements.txt`: `pypdfium2`.

**Frontend**
- Baru: `src/pages/Bagikan.jsx`, `src/components/ProofCard.jsx`, `src/components/PendingProofsBanner.jsx`, `src/lib/shareInbox.js` (+ tes), `src/lib/proofFormat.js` (+ tes).
- Ubah:
  - `public/manifest.json`, `src/sw.js`, `src/App.jsx` (route).
  - `src/lib/api.js`: endpoint Kotak Struk, field transaksi.
  - `src/native/index.js`, `src/native/web.js` (+ tes): `files.pickDocument`.
  - `src/lib/receiptScan.js`, `src/components/MultiAddTransaction.jsx` (baris bukti, `receipt_item_id`), `src/components/ReceiptInput.jsx`, `src/hooks/useReceiptScan.js`, `src/lib/receiptProgress.js`.
  - Halaman beranda dan Transaksi: banner.
  - `src/pages/Settings.jsx`: tips; hapus tampilan kuota scan.
  - `src/hooks/useAuth.jsx`: kosongkan `shares` saat logout.

**Server:** konfigurasi nginx (`POST /bagikan`).

**Dokumen**
- Baru: `docs/kotak-struk.md`.
- Ubah: `docs/scan-struk.md`, `docs/mobile/01-kajian.md`, `02-adr.md`, `03-workflow.md`, `PROGRESS.md`.
- Project doc `claude/scan-struk-keputusan.md`.

## Dampak ke rencana mobile (`docs/mobile/`)

- **Paket FS dipecah:**
  - **FS-1 (spec ini):** FS.1 tanpa service terpisah, FS.2, FS.3, FS.4a dan bagian QRIS/transfer dari FS.4b, FS.5, FS.6, FS.7, sebagian FS.8 (`ProofCard` + banner), FS.9 (Web Share Target kini wajib, PDF di bot), dan FS.11.
  - **FS-2:** tagihan (sisa FS.4b), FS.4c marketplace, invoice umum (baru), worker sebagai service terpisah, FS.10 notifikasi push, dan 6.7 email.
- **ADR-M16 tetap berlaku.** Tambah **ADR-M17**: semua jenis dokumen menghasilkan satu bentuk Dokumen Bayar berversi, dan dibaca lewat registri pembaca (deteksi + parse + cek silang) dengan profil aplikasi sebagai data. Jenis dokumen baru = modul baru, tanpa perubahan pipeline, skema, atau UI konfirmasi.
- **`01-kajian.md`:** bagian Paket Pro ("Kuota scan berlaku untuk share") diganti dengan K4. Tabel "Kondisi saat ini" baris Scan struk diperbarui setelah rilis.
- **Paket aplikasi tidak berubah:** B56–B58 (share Android) dan B62–B67 (Share Extension iOS) memakai `POST /kotak-struk`. B20–B22 menambah `files.pickDocument` di adapter Capacitor.

## Risiko

- **Tata letak aplikasi bank berubah** setelah update aplikasi → pembaca meleset. Mitigasi: profil sebagai data, pembaca umum berbasis label sebagai cadangan, dan statistik `issuer` + tingkat koreksi di Admin.
- **Worker di dalam proses API** menambah beban proses yang sama dengan API dan bot. Mitigasi: satu OCR bersamaan, PDF di proses terpisah, batas per jam; worker bisa dipindah (FS-2) hanya dengan konfigurasi.
- **Kuota scan dihapus** → beban OCR naik. Mitigasi: batas gabungan 30/jam, antrean DB, bukti bayar ringan dibaca (gambar digital rapi).
- **Kunci `nama:` bisa bertabrakan** (dua warung bernama sama di satu kota) dalam satu rumah tangga. Dampak kecil (saran amplop keliru, user mengoreksi). NMID didahulukan bila ada.
- **Salah tebak "rekening sendiri"** → hanya berupa pertanyaan, tidak pernah otomatis.
- **Share target tidak muncul** bila PWA belum terpasang atau service worker belum aktif → aturan nginx + pesan, dan jalur Telegram. User iPhone → Telegram.
- **Bentrok kode dengan rencana kamera** → urutan yang disepakati di bagian Koordinasi.
- **Data pribadi pihak ketiga** (nama penerima) → minimalisasi + DPIA.

## Perkiraan

Sekitar 15–18 hari kerja untuk satu pengembang, belum termasuk waktu mengumpulkan korpus. Perkiraan rinci per tugas dibuat di rencana implementasi.
