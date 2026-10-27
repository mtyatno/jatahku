# Scan Struk (foto → pengeluaran)

Catat pengeluaran dari foto struk, di webapp (tombol **Foto** / **Galeri** di form catat)
dan bot Telegram (kirim foto). Tanpa LLM: OCR **RapidOCR** (model PaddleOCR via
ONNX Runtime, CPU) + parser aturan. Fallback LLM Groq tersedia tapi **mati
secara default** dan dikunci plafon biaya.

Selain total, parser membaca **rincian barang** dan mencocokkannya dengan total
struk (Σ barang − diskon + pajak = total). Di webapp, **tiap barang dicatat sebagai
satu transaksi** di amplopnya sendiri, mis. `ROTI TAWAR (Indomaret)`; Σ selalu =
total struk.

## Alur

Sejak **Kotak Struk** ("Bagikan ke Jatahku"), `POST /transactions/scan-receipt` tidak lagi membaca
fotonya sendiri: ia memasukkannya ke Kotak Struk (`app/services/kotak_struk/intake.py`, sumber
`web_form`), menunggu worker membacanya (maks `WAIT_FORM_S` = 45 dtk), lalu membalas dalam
**bentuk respons lama** ditambah field baru. Rincian pintu masuk, worker, jenis dokumen, dan
status item ada di [`docs/kotak-struk.md`](kotak-struk.md). Yang tetap di dokumen ini: cara
struk belanja dibaca (parser, rincian barang) dan dicatat per barang.

```
foto/PDF ─► kompres di HP (≤1600px JPEG) ─► POST /transactions/scan-receipt
            └─ bot: foto Telegram ────────────────┘
                 │
                 ├─ intake Kotak Struk (item `diterima`) ─► worker: RapidOCR → baris teks
                 │     (susun kiri→kanan, tahan struk melengkung) → pembaca struk belanja:
                 ├─ parser: toko, tanggal, total + cek silang tunai−kembali / non-tunai
                 │    keyakinan: tinggi | sedang | rendah | gagal
                 ├─ rincian barang → rekonsiliasi dengan total (cocok | selisih | kosong)
                 ├─ (opsional) keyakinan rendah/gagal → fallback LLM ber-plafon
                 ├─ item `siap` ─► respons scan-receipt (+ item_id, doc_type, saran amplop, …)
                 │     (belum selesai dalam 45 dtk → 503 "sedang ramai"; item tetap diproses)
                 └─ user cek rincian, pilih amplop (per barang boleh beda), simpan →
                    1 transaksi per barang (client_ref per transaksi, `receipt_item_id` = item
                    Kotak Struk; item ditandai `tercatat`)
                                        │
              POST /scan-receipt/{id}/feedback (nilai akhir) ─► belajar
```

Tidak ada kuota scan (dihapus untuk semua paket, tidak bergantung pada saklar `receipt_inbox`).
`scan_id` pada respons = `item_id` Kotak Struk, jadi umpan balik lama (`/scan-receipt/{id}/feedback`)
tetap jalan; field `quota` di respons dipertahankan dengan isi `{limit: null, used: 0, remaining: null}`.
File PDF diterima oleh endpoint (maks 10 MB); foto tetap maks 8 MB.

**Di webapp: dari foto sampai hasil.** Empat pintu masuk, semuanya berakhir di form
Catat yang sama dan langsung membaca fotonya (`MultiAddTransaction` + `useReceiptScan`):

- **Foto struk** di FAB (HP) dan menu **Catat ▾** (desktop): kamera dibuka dulu,
  form Catat terbuka begitu fotonya sampai (`openReceiptCamera` di `Layout.jsx`).
- Tombol **Foto** / **Galeri** di dalam form Catat.
- Shortcut PWA **Foto struk** (`/transactions?struk=1`): form Catat terbuka dalam mode
  siap difoto, dengan tombol besar **Ambil foto struk**. Kamera tidak bisa dibuka tanpa
  ketukan, jadi shortcut hanya menyiapkan layar; parameternya dihapus dari URL.
- Pemulihan: kalau OS mematikan app saat kamera terbuka, app berikutnya menampilkan
  toast "Foto struk tadi tidak sempat diterima, coba lagi." dengan tombol **Foto ulang**.

Kamera dan galeri lewat `native.camera` (`takePhoto` / `pickPhoto` / `recover`; di web
berupa `<input type=file>`), dan harus dipanggil sinkron di dalam handler ketukan
karena iPhone Safari menolak membukanya dari tempat lain. Foto dikompres, diunggah lewat
XHR supaya persennya nyata (`lib/xhrUpload.js`, batas 60 detik, token di-refresh bila kedaluwarsa),
lalu dibaca server. Tahap yang terlihat user: menyiapkan → mengunggah (dengan persen) →
membaca; gagal di tahap mana pun memberi pesan sesuai tahap (`lib/receiptProgress.js`).
Penanda `jatahku_camera_open` (localStorage) ditulis sebelum kamera dibuka dan dihapus
begitu fotonya sampai atau dibatalkan; `recover()` yang dipanggil sekali saat app dibuka
menganggap foto hilang kalau penandanya masih baru (< 3 menit). Web tidak bisa
mengembalikan file yang hilang, hanya memberi tahu.

## Rincian barang

**Membaca.** Daerah barang: dari baris tanggal sampai baris ringkasan/pembayaran
pertama (SUBTOTAL, TOTAL, TUNAI, …). Tiap baris dibaca dari kanan:
`NAMA [QTY] [HARGA SATUAN] JUMLAH`. Ditangani juga: barang dua baris (nama di
atas, angka di bawah), qty yang menempel ke harga, format qty di depan, voucher
yang melekat ke barang di atasnya, serta diskon global dan pajak/servis di antara
SUBTOTAL dan TOTAL. Baris "diskon" bernilai positif yang ambigu diputuskan lewat
rekonsiliasi.

**Mencocokkan.** Σ barang − diskon + pajak/servis dibanding total struk →
`cocok` / `selisih` / `kosong`. Barang diperbaiki otomatis (`flag: auto`, dengan
keterangan) **hanya kalau terbukti**: qty × harga satuan, atau satu digit salah
baca yang dikonfirmasi harga satuan. Selain itu barang ditandai `cek` dengan saran
nilai (`suggestion`; `0` = kemungkinan terbaca dobel) — tidak diubah diam-diam.

**Keyakinan.** `tinggi` dari pembayaran (tunai − kembali / non-tunai), atau dari
rincian yang cocok asalkan tidak dibantah pembayaran, baris totalnya berlabel
kuat (TOTAL, GRAND TOTAL, TOTAL BAYAR, …; bukan SUBTOTAL atau label lemah seperti
JUMLAH), dan tidak ada pajak/servis setelah TOTAL.
Tanpa baris TOTAL: total = Σ barang, keyakinan `rendah`.
`confidence_source`: `payment` | `items` | `items_sum`.

**Respons API** (tambahan): `items[]` (name, qty, unit_price, amount, discount,
flag `ok|auto|cek`, note, suggestion), `adjustments[]` (label, amount, kind
`discount|charge`), `reconciliation` (items_total, discounts, charges, expected,
diff, status, note), `confidence_source`.

**Webapp (kartu struk).** Bilah cocok/selisih, keterangan per barang, nama barang
bisa diedit, tombol pakai saran, hapus barang, dan **Tambah "Lainnya"** untuk menutup
selisih. Tiap barang bisa memilih amplop sendiri (default: amplop struk).
- **1 transaksi per barang**, keterangan `NAMA BARANG (Toko)` — nama barang di depan
  supaya daftar transaksi mudah dipindai (permintaan pemilik produk, Okt 2026;
  versi awal menggabung per amplop jadi `Indomaret (3 barang)`). Seperti transaksi
  lain, keterangan di amplop bersama terlihat oleh anggota rumah tangga.
- Nominal: voucher barang mengurangi barang itu; diskon global, pajak, dan selisih
  yang belum terjelaskan dibagi proporsional menurut nilai bersih barang. Pembulatan
  sisa terbesar → Σ nominal **selalu = total struk** (`frontend/src/lib/receiptSplit.js`).
  Barang yang bagiannya 0 (gratis karena voucher) tidak dicatat.
- Rencana simpan ditampilkan ringkas per amplop ("Belanja · 2 barang · Rp…") dan
  dibekukan saat pertama disimpan. Kalau sebagian gagal (saldo/limit), yang sudah
  tercatat tidak dikirim ulang; perbaikan (geser dana sebesar Σ barang yang gagal,
  naikkan limit, pindah amplop) berlaku untuk semua barang yang gagal di amplop
  itu, atau sisanya dilewati. "Ubah rincian" hanya tersedia selama belum ada yang
  tercatat.
- Kata kunci → amplop dipelajari dari keterangan tiap barang (hook yang sama dengan
  transaksi biasa). Setelah scan, nama barang dikirim ke `POST /transactions/suggest-envelopes`;
  saran yang yakin mengisi amplop barang yang belum dipilih user (ditandai
  "disarankan"), jadi "SABUN MANDI" yang pernah dicatat ke Kebutuhan Rumah otomatis
  terpilih untuk "SABUN CAIR" di struk berikutnya. Pilihan manual tidak pernah ditimpa,
  dan saran yang datang setelah struk disimpan diabaikan.
- Paket Basic (50 transaksi/bulan): tiap barang dihitung satu transaksi. Kuota dicek
  sekali di awal simpan: struk yang mulai disimpan saat kuota masih ada selalu selesai
  utuh (juga kirim ulang bagian yang gagal), lalu user diberi tahu kuota habis sampai
  tanggal 1 bulan depan (`app/services/quota_pass.py`).

**Bot.** Ringkas: daftar barang (maks 12 baris + 5 penyesuaian, ≤ 2.500 karakter)
dan status cocok/selisih. Kalau selisih, bot menyarankan koreksi & pecah amplop di
webapp; bot tetap mencatat total sebagai satu transaksi.

## Kirim ulang aman (idempotensi)

Respons simpan bisa hilang (sinyal putus, 5xx) padahal transaksi sudah tercatat.
Supaya "Simpan" lagi tidak mencatat dua kali:

- Web mengirim `client_ref` (UUID) per transaksi di `POST /transactions` dan
  `POST /transactions/batch`; antrean offline & service worker ikut meneruskannya.
- Server (`app/services/idempotency.py`, Redis `txnref:{user_id}:{ref}`): `pending`
  (SET NX, 120 dtk) selama dibuat → ID transaksi (2 hari) setelah commit. Ref yang
  sama dikirim lagi → transaksi yang sudah ada dikembalikan, tidak dibuat baru.
  Masih `pending` → 409 (batch: `pending: true`). Gagal sebelum commit → reservasi
  dilepas. Redis mati → fail open (perilaku lama, tanpa dedup).
- Klien: respons hilang / 409 / 5xx → baris ditandai "belum pasti" dan dikunci
  (nominal & amplop tidak bisa diubah) dengan kunci yang sama; tekan Simpan lagi
  (quick-add mengirim ulang permintaan yang sama persis). Penolakan pasti (mis.
  saldo kurang, 4xx selain 409) → tidak tercatat; baris bisa diedit lagi.
- Simpan ditahan selama suara direkam/ditranskripsi atau struk sedang dibaca, dan
  selama teks yang baru diketik belum selesai dibaca — supaya hasilnya tidak masuk
  di tengah penyimpanan atau hilang saat panel ditutup.
- Keterangan lebih dari 500 karakter (panjang kolom) dipotong di server; dulu gagal
  500 dan kirim ulang tidak pernah berhasil.
- Tidak ada tabel atau paket baru.
- **`receipt_item_id`** (opsional) di `POST /transactions` dan `/transactions/batch` mencatat
  transaksi atas satu item Kotak Struk: dicek (`check_recordable`) tepat setelah cek `client_ref`;
  semua jenis selain struk belanja (QRIS, transfer, tidak dikenali) diklaim secara atomik bersama commit
  transaksinya (`claim_for_recording`), jadi tidak pernah tercatat dua kali walau disimpan bersamaan dari
  dua tempat (409 "Bukti ini sudah tercatat"); struk belanja boleh dicatat per barang (id semua transaksi
  ditambahkan ke item). Teks 409 untuk klaim yang gagal (di batch: `error` baris itu dengan `ok: false`)
  mengikuti status item saat itu (`record.claim_failure_detail`): "Bukti ini sudah tercatat", "Bukti ini sudah
  kedaluwarsa, bagikan lagi untuk mencatatnya", "Bukti ini belum siap dicatat", atau "Bukti tidak ditemukan".
  Item yang sudah kedaluwarsa sebelum disimpan mendapat teks kedaluwarsa yang sama dari `check_recordable`.
  Sesudah commit `record.after_recorded` (dipakai web dan bot) menjalankan streak,
  kata kunci, dan menandai item `tercatat` (`mark_recorded`), semuanya best-effort: galat database yang
  ditelan di sana tidak merusak sisa permintaan (sesi di-rollback dan `user` dimuat ulang, jadi baris batch
  berikutnya dan pemberitahuan kuota tetap jalan). `client_ref` yang dikirim ulang dengan `receipt_item_id`
  yang sama menyembuhkan penandaan yang hilang (`record.heal_recorded`; hanya item yang diklaim transaksi
  itu tapi belum ditandai). Peta merchant hanya belajar dari QRIS/transfer.
- Foto yang tidak dikenali pembaca mana pun dan tanpa baris "Rp" (dan tanpa penyelamatan LLM): pembaca
  cadangan menebak seperti scan struk lama (`parse_receipt`: total, tanggal, nama merchant) dengan keyakinan
  `rendah`, jenisnya tetap `tidak_dikenali` (spec 6a): sekali dicatat (klaim eksklusif), tanpa rincian barang,
  tanpa teks OCR, tanpa data belajar struk. Rincian, kutipan baris, dan nama yang memuat deret digit sepanjang
  nomor rekening (>= 8 digit) tidak dibawa; teks yang terbaca sebagai bukti bayar tetap tanpa peta merchant.

## Belajar dari koreksi (tanpa LLM)

| Data | Tabel | Dipakai parser setelah |
|---|---|---|
| Label baris total per toko ("JML BYR") | `receipt_total_labels` | ≥ 2 user berbeda |
| Nama toko salah-baca → benar | `receipt_merchant_aliases` | ≥ 2 user berbeda |
| Toko → amplop per user | `user_envelope_keywords` (sudah ada) | langsung |

Pengaman agar data bersama tidak "teracuni":
- Suara dihitung per user (`receipt_learn_votes`), bukan per scan.
- Koreksi total hanya dipelajari jika nilainya terbukti oleh pembayaran di
  struk itu sendiri (tunai − kembali / non-tunai). Mencatat sebagian item saja
  tidak mengajari apa pun.
- Label hasil belajar tidak bisa mengalahkan total yang cocok dengan pembayaran.
- Nama toko dari user dibersihkan (huruf/angka/&'.-, maks 40) sebelum jadi alias.

Koreksi rincian barang belum dipelajari — feedback hanya membawa total, tanggal,
dan nama toko.

Teks OCR (`receipt_scans.ocr_lines`) dihapus begitu feedback diproses; scan yang
tidak pernah diberi feedback dibersihkan scheduler setelah 24 jam (outcome `expired`).
Bukti bayar yang dibaca jalur struk ini (saklar `receipt_inbox` mati) tidak menyimpan teks OCR sama sekali, juga
tanpa rincian barang, nama toko, dan kutipan baris (lihat [`docs/kotak-struk.md`](kotak-struk.md) "Privasi").
Statusnya dibaca dari judul dan dari judul status gagal/pending di badan ("Transaksi Gagal" di bawah rincian), jadi
transfer gagal tetap diblokir di jalur ini; struk dengan kaki "Transaksi gagal - struk ini tidak sah" juga diblokir,
dan "Pembayaran pending …" hanya memperingatkan (lihat `docs/kotak-struk.md` "Cek silang").
Salah-baca kata kunci umum (`T0TAL`, `TUNAL`, `KEHBALI`) ditangani kamus +
pencocokan jarak-edit 1 di `receipt_parser.py`.

Akurasi bulanan (diterima tanpa koreksi vs dikoreksi) & toko yang paling sering
dikoreksi: **Admin → Dashboard → Scan Struk** (`GET /admin/receipt-scans/stats`). Sejak Kotak Struk
respons itu juga memuat `by_doc_type`, `unrecognized`, dan `by_issuer` (lihat [`docs/kotak-struk.md`](kotak-struk.md)).

## Fallback LLM — pengaman biaya

Mati kecuali `RECEIPT_LLM_ENABLED=true` di `/opt/jatahku/.env` (pakai `GROQ_API_KEY` yang sama dengan voice).

- **Plafon bulanan global** `RECEIPT_LLM_MONTHLY_BUDGET_IDR` (default Rp100.000).
  Sebelum tiap panggilan, biaya terburuk direservasi atomik di Redis
  (`receipt_llm:cost:YYYY-MM`); kalau melewati plafon, LLM tidak dipanggil.
- **Kuota per user** `RECEIPT_LLM_USER_MONTHLY_BASIC` (3) / `_PRO` (10).
- Estimasi biaya memakai harga per token di config dan kurs konservatif
  `RECEIPT_LLM_USD_IDR=17500`. Satu panggilan ± Rp40–70.
- Request yang ditolak (4xx) atau tidak terkirim tidak memotong plafon maupun
  kuota user. Timeout / 5xx tetap dihitung (mungkin sudah ditagih Groq).

## Deploy (manual, sekali)

Rincian barang & idempotensi tidak menambah paket maupun tabel — cukup merge
(deploy otomatis). Langkah di bawah hanya untuk pemasangan awal scan struk.
Kotak Struk menambah `pypdfium2` (PDF), folder berkas sementara, `KOTAK_HMAC_KEY`, dan satu revisi alembic:
langkahnya di [`docs/kotak-struk.md`](kotak-struk.md) bagian "Deploy manual" dan `AGENTS.md`
"Deploy Checklist — Kotak Struk / Bagikan ke Jatahku, Bagian A (a7c4e2b9d1f3)".

Deploy otomatis **tidak** meng-install paket Python, jadi sebelum/sesudah merge:

1. `sudo -u jatahku /opt/jatahku/venv/bin/pip install rapidocr==3.10.0 onnxruntime==1.31.0`
   (sesuaikan path venv; model ±31 MB ikut paket, tidak perlu unduh).
2. Tabel baru (`receipt_scans`, `receipt_total_labels`, `receipt_merchant_aliases`,
   `receipt_learn_votes`) dibuat otomatis oleh `create_all` saat startup — tidak
   ada ALTER tabel lama. (Kolom Kotak Struk di `receipt_scans` ditambah `lifespan`; lihat `docs/kotak-struk.md`.)
3. `sudo systemctl restart jatahku` (API + bot).
4. Uji: kirim foto struk ke bot, dan tombol **Foto** / **Galeri** di form catat webapp.
5. Pantau RAM: proses API naik ±340 MB setelah scan pertama (model dimuat sekali).
   Pastikan `jatahku.service` menjalankan uvicorn dengan **1 worker**: tiap worker
   memuat model sendiri, dan batas "1 OCR bersamaan" berlaku per proses.

## Batas & perlindungan

- Foto > 30 MP ditolak dari header sebelum didekode (cegah bom dekompresi).
- 1 OCR berjalan bersamaan (worker Kotak Struk di proses API). `scan-receipt` menunggu hasilnya
  maks 45 dtk; lewat itu 503 "sedang ramai" dan itemnya tetap diproses (muncul di Kotak Struk).
  Koneksi DB dilepas selama menunggu.
- Rate limit: tidak ada batas slowapi terpisah lagi di `POST /transactions/scan-receipt`; batas intake Kotak
  Struk berlaku untuk semua kanal: 30 bukti/jam per user (Redis; Redis mati → tidak dibatasi) dan maks 20 item
  belum selesai per user; terlewati → 429 ("Terlalu banyak bukti. Coba lagi sebentar." / "Masih ada
  bukti yang sedang dibaca. Tunggu sebentar."), di bot pesan itu menggantikan "Membaca bukti…". Bot tidak
  punya batas scan sendiri lagi (batas 30 pesan/menit untuk pesan teks tetap).
- **Kuota scan dihapus** (semua paket). `GET /transactions/scan-receipt/quota` tetap ada untuk klien
  lama: `{limit: null, used, remaining: null}` (`used` = scan bulan ini yang totalnya terbaca, di
  zona waktu user).

Kalau paket OCR (`rapidocr`) atau `pypdfium2` (PDF) belum terpasang, worker menandai item `gagal` dengan
pesan "Baca bukti sedang tidak bisa. Catat manual dulu.": `scan-receipt` membalas **422** dengan pesan itu
(bukan lagi 503 "Scan struk sedang tidak tersedia") dan bot membalas "😕 Baca bukti sedang tidak bisa.
Catat manual dulu." — fitur lain tidak terpengaruh. Kalau belum selesai dalam 45 dtk, tetap 503 "Scan
struk sedang ramai. Coba lagi beberapa detik lagi.", dan itemnya tetap diproses.

## Konfigurasi

| Env | Default | Arti |
|---|---|---|
| `RECEIPT_SCAN_LIMIT_BASIC` | 15 | Tidak dipakai lagi sejak Kotak Struk: kuota scan tidak ada. Tetap ada di `Settings` supaya `.env` lama tidak membuat startup gagal |
| `RECEIPT_LLM_ENABLED` | false | Nyalakan fallback LLM |
| `RECEIPT_LLM_MONTHLY_BUDGET_IDR` | 100000 | Plafon biaya LLM per bulan (Rp) |
| `RECEIPT_LLM_USER_MONTHLY_BASIC` / `_PRO` | 3 / 10 | Kuota fallback per user |
| `RECEIPT_LLM_MODEL` | qwen/qwen3.8-27b | Model vision Groq |

## Test

`python -m unittest app.tests.test_receipt_scan -v` — termasuk 4 struk Indomaret
asli (fixture baris OCR di `app/tests/fixtures/receipt_ocr_lines.json`, nomor
kartu disamarkan; keempatnya rincian `cocok`), kasus rincian (dua baris, voucher,
pajak, salah baca digit, dobel), gerbang belajar, idempotensi, ringkasan bot, dan
`scan_receipt` lewat Kotak Struk (SQLite, hasil OCR palsu).
`python -m unittest app.tests.test_kotak_transactions -v` — bentuk respons scan-receipt,
kuota tanpa batas, dan `receipt_item_id` (klaim atomik, kirim ulang, batch).
Frontend: `node --test src/lib/receiptScan.test.js src/lib/receiptSplit.test.js`
dari folder `frontend` (catat per barang: Σ selalu = total, diuji acak).
