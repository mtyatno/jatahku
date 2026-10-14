---
title: "Cara Menggunakan Bot Telegram Jatahku: Catat Pengeluaran Semudah Kirim Chat"
description: "Panduan lengkap pakai @JatahkuBot untuk mencatat pengeluaran tanpa buka aplikasi. Format NLP, foto struk, cara koreksi, cek saldo amplop — semua lewat chat."
pubDate: 2026-03-30
updatedDate: 2026-10-15
category: tutorial
author: Tim Jatahku
cover: /covers/cara-pakai-bot-telegram.svg
featured: true
---

**Diperbarui 15 Oktober 2026:** bot sekarang bisa membaca foto struk, mengisi dana amplop yang kurang, dan mencatat beberapa pengeluaran tanpa koma. Tidak memakai Telegram? Bot yang sama kini ada di dalam webapp. Baca [Chat Jatahku Kini Ada di Webapp](/insight/chat-jatahku-di-webapp/).

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

Bot membaca nominalnya, lalu memilih amplop yang cocok. Kalau belum yakin, bot menampilkan tombol pilihan amplop. Ketuk salah satunya, dan transaksi langsung tercatat.

**Bagaimana bot memilih amplop?** Pertama dari kebiasaanmu: kata yang pernah kamu catat ke suatu amplop akan diingat, jadi lain kali tidak ditanyakan lagi. Lalu dari kata kunci umum, misalnya kopi dan nasi ke amplop bernama Makan, atau gojek dan parkir ke amplop bernama Transport. Kalau kata kuncinya belum dikenali, nama amplop yang kamu tulis di pesan juga dipakai.

**Format nominal yang didukung:**

| Yang kamu tulis | Dibaca sebagai |
|---|---|
| `35k` | Rp 35.000 |
| `52rb` | Rp 52.000 |
| `1.5jt` | Rp 1.500.000 |
| `285.000` | Rp 285.000 |
| `rp250ribu` | Rp 250.000 |

---

## Beberapa Pengeluaran Sekaligus

Habis jalan seharian? Kirim semuanya dalam satu pesan. Pisahkan dengan koma, baris baru, atau kata "dan":

```
makan 30k, parkir 5k, kopi 20k
```

Koma juga boleh dilewati, selama tiap nominal punya satuan atau format ribuan:

```
kopi 35 ribu gojek 20 ribu
35k kopi 20k parkir
```

Angka tanpa satuan tidak memecah pengeluaran. Jadi `beli 2 kopi 25 ribu` tetap terbaca sebagai satu pengeluaran sebesar Rp 25.000, dan angka 2 dianggap jumlah barang.

Setiap item dicek seperti kalau dicatat satu per satu. Item yang amplopnya langsung dikenali dan dananya cukup langsung tercatat. Item yang perlu pilihan amplop atau tambahan dana ditanyakan satu per satu di pesan yang sama.

---

## Catat dari Foto Struk

Kirim foto struk ke bot. Bot membaca nama toko, tanggal, total, dan rincian barangnya, lalu menanyakan amplopnya. Amplop yang disarankan muncul paling atas dengan tanda ⭐.

Struk dicatat sebagai satu transaksi dengan tanggal yang tertulis di struk. Kalau totalnya salah terbaca, ketuk **✏️ Nominal salah**, lalu ketik nominal yang benar seperti biasa. Catatan yang diketik ulang ini memakai tanggal hari ini.

Mau memecah struk per barang ke amplop yang berbeda? Pakai tombol **Struk** di webapp. Panduannya ada di artikel [Catat Belanja dari Foto Struk](/insight/catat-belanja-dari-foto-struk/).

---

## Kalau Dana Amplop Kurang

Kalau sisa amplop tidak cukup untuk pengeluaran yang kamu kirim, bot menampilkan **💸 Dana amplop kurang** beserta kekurangannya, lalu menawarkan dua cara menutupnya:

- **Geser dari amplop lain.** Setiap amplop yang sisanya cukup muncul sebagai tombol 🔁 tersendiri, maksimal empat, mulai dari yang sisanya paling besar.
- **Top-up pemasukan.** Tombol **💰 Top-up pemasukan** mencatat pemasukan sebesar kekurangannya ke amplop itu.

Setelah kamu memilih, transaksinya langsung tercatat. Kalau tidak jadi, ketuk **❌ Batalkan** dan tidak ada dana yang berubah.

---

## Kalau Melewati Limit Harian

Kalau amplop punya limit harian dan pengeluaranmu melewatinya, bot menampilkan rinciannya dan menawarkan **✅ Catat, naikkan limit hari ini**. Limit amplop itu dinaikkan sampai tengah malam, lalu besok kembali normal.

---

## Cara Koreksi Kalau Salah Ketik

Salah nominal atau salah catat? Ada dua cara memperbaikinya.

**Salah nominal:** kirim misalnya

```
harusnya 25k
```

Bot mengganti nominal transaksi terakhir yang kamu catat.

**Salah catat:** kirim `/batal`, atau tulis `batalin yang tadi`. Bot menghapus transaksi terakhir yang kamu catat.

Untuk transaksi yang lebih lama, buka halaman **Transaksi** di webapp, lalu hapus lewat menu di baris transaksinya.

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

Bot menampilkan sisa dana tiap amplop, persentase yang sudah terpakai, dan berapa hari lagi sampai periode gajianmu berakhir.

Mau beli sesuatu tapi ragu? Tanya dulu, misalnya `aman gak beli sepatu 450rb?`. Bot menjawab ✅ Aman, ⚠️ Pas-pasan, atau ❌ Tidak cukup, tanpa mencatat apa pun. Kalau amplopnya belum jelas, bot menampilkan semua amplop dengan tanda yang sama.

---

## Transaksi Langganan (Bulanan/Tahunan)

Punya pengeluaran yang rutin tiap bulan? Daftarkan sekali, berikutnya tinggal konfirmasi:

```
sewa server 250k tiap bulan
Netflix 75rb setiap bulan
asuransi jiwa 350rb per bulan
```

Bot mencatat pembayaran pertama dan menyimpan langganannya. Setiap jatuh tempo, bot mengirim pengingat dengan tombol **✅ Bayar & catat**, **⏭️ Skip bulan ini**, atau **❌ Berhenti langganan**. Pembayaran baru tercatat setelah kamu mengetuk Bayar & catat.

---

## Perintah Berguna Lainnya

| Perintah | Fungsi |
|---|---|
| `/start` | Mulai / cek status akun |
| `/status` | Ringkasan budget bulan ini |
| `/amplop` | Daftar amplop dan sisa dananya |
| `/batal` | Batalkan transaksi terakhir |
| `/langganan` | Daftar langganan aktif |
| `/help` | Daftar semua perintah |
| `/webapp` | Buka Jatahku langsung dari Telegram |

---

## Tips agar Konsisten

**Catat saat itu juga.** Jangan tunggu malam atau akhir minggu. Begitu transaksi terjadi, langsung buka Telegram dan ketik. Dengan bot, prosesnya cuma 5 detik.

**Pin chat @JatahkuBot** di Telegram kamu supaya selalu ada di bagian atas dan mudah dijangkau.

**Aktifkan notifikasi bot** supaya kamu tahu kalau ada pesan dari Jatahku — misalnya ringkasan harian, pengingat tagihan langganan, atau pengingat untuk mencatat.

---

Selamat mencoba! Kalau ada pertanyaan, kirim langsung ke [@JatahkuBot](https://t.me/JatahkuBot) dengan perintah `/help`.
