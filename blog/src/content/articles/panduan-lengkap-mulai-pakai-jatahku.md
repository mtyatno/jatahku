---
title: "Panduan Lengkap Mulai Pakai Jatahku: Dari Daftar sampai Catat Pengeluaran Pertama"
description: "Panduan step-by-step menggunakan Jatahku dari awal — daftar akun, onboarding wizard, hubungkan Telegram, catat pengeluaran dengan NLP, sampai baca laporan bulanan."
pubDate: 2026-04-02
category: tutorial
author: Tim Jatahku
cover: /covers/panduan-lengkap.svg
featured: false
---

Kamu baru dengar soal Jatahku dan penasaran cara pakainya? Artikel ini akan membawa kamu dari nol — mulai daftar akun sampai kamu bisa mencatat pengeluaran pertama, semuanya kurang dari 15 menit.

---

## Apa Itu Jatahku?

Jatahku adalah aplikasi *envelope budgeting* berbasis web yang terintegrasi dengan Telegram Bot. Idenya sederhana: **setiap rupiah yang masuk langsung dibagi ke amplop-amplop pengeluaran** sebelum kamu mulai belanja.

Bedanya dengan aplikasi keuangan lain: pencatatan pengeluaran bisa dilakukan lewat chat Telegram — semudah kirim pesan ke teman. Tidak perlu buka app, tidak perlu klik banyak tombol.

---

## Langkah 1: Daftar Akun

1. Buka [jatahku.com](https://jatahku.com)
2. Klik **Mulai Gratis** atau **Daftar**
3. Isi nama, email, dan password
4. Akun langsung aktif — tidak perlu verifikasi email

Setelah login pertama kali, **Onboarding Wizard** akan otomatis muncul untuk memandu setup awal kamu.

---

## Langkah 2: Onboarding Wizard (3 Langkah)

Saat pertama login, Jatahku menjalankan wizard setup singkat 3 langkah. Ini cara tercepat untuk langsung siap pakai.

### Step 1 — Income & Tanggal Gajian

Masukkan total pemasukan bulanan kamu (gaji, freelance, dll) dan tanggal gajian.

Tanggal gajian penting karena Jatahku menghitung **periode budget berdasarkan hari gajianmu**, bukan bulan kalender. Misalnya jika gajian tanggal 25, periode budgetmu adalah 25 Maret – 24 April, bukan 1–31 April.

### Step 2 — Pilih Template Amplop

Pilih salah satu dari empat template yang sudah disiapkan:

| Template | Cocok untuk | Amplop bawaan |
|----------|-------------|---------------|
| 💼 Karyawan | Pekerja kantoran | Makan 20%, Transport 7%, Hiburan 5%, Tagihan 8% |
| 🎓 Mahasiswa | Pelajar/mahasiswa | Makan 30%, Transport 10%, Hiburan 10%, Kuliah 15% |
| 👨‍👩‍👧 Keluarga | Rumah tangga | Makan 25%, Transport 10%, Rumah 20%, Tagihan 8%, Hiburan 5% |
| ✏️ Custom | Semua profil | Buat amplop sendiri dari nol |

### Step 3 — Sesuaikan Alokasi

Setelah pilih template, kamu bisa atur ulang alokasi tiap amplop — baik dalam persen maupun nominal Rp. Bar progress akan menunjukkan berapa yang sudah teralokasi dari total income.

Sisa income yang belum dialokasikan otomatis masuk sebagai **Tabungan**.

Klik **Mulai Budgeting** — semua amplop dan alokasi langsung tersimpan sekaligus.

---

## Langkah 3: Hubungkan Telegram Bot

Ini langkah yang akan membuat pencatatan pengeluaran jadi sangat mudah.

1. Buka **Settings** (ikon roda gigi di sidebar)
2. Klik **Generate Link Telegram**
3. Klik link yang muncul — Telegram akan terbuka otomatis
4. Kirim `/start` ke [@JatahkuBot](https://t.me/JatahkuBot)

Bot sudah mengenal kamu. Sekarang kamu bisa catat pengeluaran hanya dengan kirim pesan.

---

## Langkah 4: Catat Pengeluaran dengan NLP

Ini fitur utama Jatahku. Kamu **tidak perlu pilih menu atau klik tombol** — cukup ketik kalimat natural seperti chat biasa, dan bot akan mengerti.

### Format Dasar

Ketik deskripsi pengeluaran diikuti nominal:

```
kopi 18k
makan siang 35000
grab ke kantor 22rb
bayar listrik 250.000
nonton bioskop 75.000
```

### Format Angka yang Didukung

Bot memahami semua format angka Indonesia:

| Yang kamu ketik | Dibaca sebagai |
|-----------------|----------------|
| `18k` | Rp 18.000 |
| `18rb` | Rp 18.000 |
| `18ribu` | Rp 18.000 |
| `18000` | Rp 18.000 |
| `18.000` | Rp 18.000 |
| `250k` | Rp 250.000 |
| `1.5jt` | Rp 1.500.000 |
| `rp17.000` | Rp 17.000 |

### Deteksi Amplop Otomatis

Bot belajar mengenali kata-kata yang kamu sering pakai dan mencocokkannya ke amplop yang tepat. Semakin sering dipakai, semakin akurat deteksinya.

- `kopi`, `makan siang`, `warteg` → otomatis ke amplop Makan
- `grab`, `gojek`, `bensin` → otomatis ke amplop Transport
- `netflix`, `spotify` → otomatis ke amplop Hiburan atau Tagihan

Jika bot belum yakin, ia akan menampilkan tombol pilihan amplop. Pilihanmu akan **diingat** untuk transaksi berikutnya.

### Cek Saldo Amplop

Ketik `/status` untuk lihat semua amplop beserta sisa saldo:

```
/status
```

Bot akan membalas dengan daftar lengkap amplop, berapa yang sudah dipakai, dan berapa sisa yang tersedia.

### Perintah Bot Lainnya

| Perintah | Fungsi |
|----------|--------|
| `/status` | Cek saldo semua amplop |
| `/sisa` | Ringkasan sisa budget |
| `/help` | Daftar semua perintah |

---

## Pantau Budget di Webapp

Selain Telegram, kamu juga bisa pantau budget lewat webapp di [jatahku.com](https://jatahku.com):

- **Dashboard** — ringkasan budget, peringatan amplop hampir habis, dan kabar baik jika hemat
- **Halaman Amplop** — progress bar visual tiap amplop
- **Analytics** — grafik tren pengeluaran bulanan

---

## Baca Laporan Bulanan

Di akhir bulan (atau kapan saja), kamu bisa lihat laporan lengkap:

1. Buka halaman **Dashboard**
2. Klik tombol **Laporan** di sudut kanan atas
3. Laporan PDF bulan berjalan akan terbuka
4. Gunakan tombol **‹ ›** di toolbar untuk navigasi ke bulan-bulan sebelumnya
5. Klik **Simpan PDF** untuk mengunduh, atau **Print** untuk cetak

---

## Tips Agar Konsisten

**Catat langsung, jangan tunda.** Saat bayar kopi, langsung kirim ke bot. Kalau ditunda, sering lupa.

**Cek `/status` tiap hari.** Kebiasaan ini membantu kamu sadar sebelum amplop kosong, bukan sesudah.

**Mulai sederhana.** Tidak perlu langsung sempurna. 4 amplop yang rutin dicatat lebih baik dari 15 amplop yang sering terlewat.

**Manfaatkan sisa bulan.** Jatahku menampilkan sisa saldo amplop setelah dikurangi pengeluaran. Kalau tersisa banyak di akhir bulan — kamu bisa pindahkan ke tabungan atau tambahkan ke amplop lain.

---

Selamat mencoba! Kalau ada pertanyaan atau butuh bantuan, hubungi kami di [hi@jatahku.com](mailto:hi@jatahku.com).
