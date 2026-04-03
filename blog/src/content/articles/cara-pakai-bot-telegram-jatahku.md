---
title: "Cara Menggunakan Bot Telegram Jatahku: Catat Pengeluaran Semudah Kirim Chat"
description: "Panduan lengkap pakai @JatahkuBot untuk mencatat pengeluaran tanpa buka aplikasi. Format NLP, cara koreksi, cek saldo amplop — semua bisa lewat chat."
pubDate: 2026-03-30
category: tutorial
author: Tim Jatahku
cover: /covers/cara-pakai-bot-telegram.svg
featured: true
---

Salah satu keluhan terbesar soal aplikasi keuangan adalah ini: **terlalu ribet untuk dipakai setiap hari**.

Buka app, login, pilih menu, pilih amplop, ketik nominal, simpan. Untuk satu kopi 15 ribu pun harus melewati 6 langkah.

Jatahku menyelesaikan masalah ini dengan cara yang berbeda — kamu cukup kirim pesan ke bot Telegram, persis seperti chat biasa. Tidak perlu buka app, tidak perlu login berulang.

---

## Cara Menghubungkan Akun ke Bot

Sebelum mulai, kamu perlu menghubungkan akun Jatahku ke Telegram sekali saja:

1. Login ke [jatahku.com](https://jatahku.com)
2. Buka **Settings** → klik **Generate Link Telegram**
3. Klik link yang muncul — Telegram akan terbuka otomatis
4. Kirim `/start` ke [@JatahkuBot](https://t.me/JatahkuBot)

Selesai. Sekarang bot sudah mengenal kamu.

---

## Format Dasar: Nulis Bebas, Bot yang Ngerti

Kamu tidak perlu hafal format khusus. Tulis saja seperti ngobrol:

```
kopi 15k
makan siang 52rb
bensin 100ribu
bayar listrik 285.000
```

Bot akan otomatis baca nominal dan tanya amplop mana. Ketuk pilihan amplop, transaksi langsung tercatat.

**Mau langsung tentukan amplopnya?** Tambahkan di akhir kalimat:

```
kopi 15k ngopi
makan siang 52rb makan
bensin 100k transport
```

Kalau nama amplop cocok, bot langsung catat tanpa tanya lagi.

**Format nominal yang didukung:**

| Yang kamu tulis | Dibaca sebagai |
|---|---|
| `35k` | Rp 35.000 |
| `52rb` | Rp 52.000 |
| `1.5jt` | Rp 1.500.000 |
| `285.000` | Rp 285.000 |
| `rp250ribu` | Rp 250.000 |

---

## Cara Koreksi Kalau Salah Ketik

Salah nominal atau salah amplop? Tenang, ada dua cara memperbaikinya.

**Cara 1 — Batalkan transaksi terakhir:**

Setelah bot konfirmasi transaksi, langsung ketik:

```
batal
```

Bot akan hapus transaksi yang baru saja dicatat.

**Cara 2 — Hapus dari riwayat:**

Kirim perintah:

```
/riwayat
```

Bot akan tampilkan 5 transaksi terakhir lengkap dengan tombol **Hapus** di setiap transaksinya.

---

## Cek Sisa Saldo Amplop

Mau tahu masih ada berapa di amplop Makan sebelum pesan restoran? Ketik saja:

```
sisa
```

atau

```
saldo
```

Bot akan tampilkan semua amplop beserta sisa dana masing-masing, terurut dari yang paling menipis.

---

## Transaksi Langganan (Bulanan/Tahunan)

Punya pengeluaran yang rutin tiap bulan? Catat sekali, otomatis jalan terus:

```
sewa server 250k tiap bulan
Netflix 75rb setiap bulan
asuransi jiwa 350rb per bulan
```

Bot akan buat transaksi berulang dan otomatis mencatat di tanggal yang sama setiap bulannya.

---

## Perintah Berguna Lainnya

| Perintah | Fungsi |
|---|---|
| `/start` | Mulai / cek status akun |
| `/sisa` | Lihat saldo semua amplop |
| `/riwayat` | 5 transaksi terakhir |
| `/help` | Daftar semua perintah |
| `/webapp` | Buka Jatahku langsung dari Telegram |

---

## Tips agar Konsisten

**Catat saat itu juga.** Jangan tunggu malam atau akhir minggu. Begitu transaksi terjadi, langsung buka Telegram dan ketik. Dengan bot, prosesnya cuma 5 detik.

**Pin chat @JatahkuBot** di Telegram kamu supaya selalu ada di bagian atas dan mudah dijangkau.

**Aktifkan notifikasi bot** supaya kamu tahu kalau ada pengingat dari Jatahku — misalnya kalau saldo amplop mulai menipis.

---

Selamat mencoba! Kalau ada pertanyaan, kirim langsung ke [@JatahkuBot](https://t.me/JatahkuBot) dengan perintah `/help`.
