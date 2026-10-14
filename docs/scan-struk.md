# Scan Struk (foto → pengeluaran)

Catat pengeluaran dari foto struk, di webapp (tombol **Struk** di form catat)
dan bot Telegram (kirim foto). Tanpa LLM: OCR **RapidOCR** (model PaddleOCR via
ONNX Runtime, CPU) + parser aturan. Fallback LLM Groq tersedia tapi **mati
secara default** dan dikunci plafon biaya.

## Alur

```
foto ─► kompres di HP (≤1600px JPEG) ─► POST /transactions/scan-receipt
        └─ bot: foto Telegram ────────────────┘
             │
             ├─ kuota: Basic 15 scan/bulan (RECEIPT_SCAN_LIMIT_BASIC), Pro tanpa batas
             ├─ RapidOCR → baris teks (susun kiri→kanan, tahan struk melengkung)
             ├─ parser: toko, tanggal, total + cek silang tunai−kembali / non-tunai
             │    keyakinan: tinggi | sedang | rendah | gagal
             ├─ (opsional) keyakinan rendah/gagal → fallback LLM ber-plafon
             └─ simpan ReceiptScan → user cek, pilih amplop, simpan
                                        │
              POST /scan-receipt/{id}/feedback (nilai akhir) ─► belajar
```

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

Teks OCR (`receipt_scans.ocr_lines`) dihapus begitu feedback diproses; scan yang
tidak pernah diberi feedback dibersihkan scheduler setelah 24 jam (outcome `expired`).
Salah-baca kata kunci umum (`T0TAL`, `TUNAL`, `KEHBALI`) ditangani kamus +
pencocokan jarak-edit 1 di `receipt_parser.py`.

Akurasi bulanan (diterima tanpa koreksi vs dikoreksi) & toko yang paling sering
dikoreksi: **Admin → Dashboard → Scan Struk** (`GET /admin/receipt-scans/stats`).

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

Deploy otomatis **tidak** meng-install paket Python, jadi sebelum/sesudah merge:

1. `sudo -u jatahku /opt/jatahku/venv/bin/pip install rapidocr==3.10.0 onnxruntime==1.31.0`
   (sesuaikan path venv; model ±31 MB ikut paket, tidak perlu unduh).
2. Tabel baru (`receipt_scans`, `receipt_total_labels`, `receipt_merchant_aliases`,
   `receipt_learn_votes`) dibuat otomatis oleh `create_all` saat startup — tidak
   ada ALTER tabel lama.
3. `sudo systemctl restart jatahku` (API + bot).
4. Uji: kirim foto struk ke bot, dan tombol **Struk** di form catat webapp.
5. Pantau RAM: proses API naik ±340 MB setelah scan pertama (model dimuat sekali).
   Pastikan `jatahku.service` menjalankan uvicorn dengan **1 worker**: tiap worker
   memuat model sendiri, dan batas "1 OCR bersamaan" berlaku per proses.

## Batas & perlindungan

- Foto > 30 MP ditolak dari header sebelum didekode (cegah bom dekompresi).
- 1 OCR berjalan bersamaan; maks 4 antre (selebihnya 503 "sedang ramai");
  1 scan berjalan per user. Koneksi DB dilepas selama OCR.
- Rate limit: web 30 scan/jam per user, bot 20 scan/jam per user.
- Scan yang totalnya tidak terbaca sama sekali tidak memotong kuota.
- Kuota bulanan dihitung di zona waktu user.

Kalau paket belum terpasang, endpoint membalas 503 "Scan struk sedang tidak
tersedia" dan bot menyarankan catat manual — fitur lain tidak terpengaruh.

## Konfigurasi

| Env | Default | Arti |
|---|---|---|
| `RECEIPT_SCAN_LIMIT_BASIC` | 15 | Scan/bulan untuk user Basic |
| `RECEIPT_LLM_ENABLED` | false | Nyalakan fallback LLM |
| `RECEIPT_LLM_MONTHLY_BUDGET_IDR` | 100000 | Plafon biaya LLM per bulan (Rp) |
| `RECEIPT_LLM_USER_MONTHLY_BASIC` / `_PRO` | 3 / 10 | Kuota fallback per user |
| `RECEIPT_LLM_MODEL` | qwen/qwen3.8-27b | Model vision Groq |

## Test

`python -m unittest app.tests.test_receipt_scan -v` — termasuk 4 struk Indomaret
asli (fixture baris OCR di `app/tests/fixtures/receipt_ocr_lines.json`, nomor
kartu disamarkan). Frontend: `node --test frontend/src/lib/receiptScan.test.js`.
