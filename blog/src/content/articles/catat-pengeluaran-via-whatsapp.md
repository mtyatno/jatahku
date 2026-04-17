---
title: "Catat Pengeluaran Lewat WhatsApp: Jatahku Kini Hadir di WA"
description: "Jatahku sekarang bisa diakses via WhatsApp. Catat pengeluaran, cek saldo amplop, dan terima ringkasan harian — semua tanpa buka aplikasi."
pubDate: 2026-04-18
category: update-fitur
author: Tim Jatahku
cover: /covers/bot-whatsapp.svg
featured: true
---

Selama ini Jatahku bisa diakses lewat Telegram dan webapp. Mulai sekarang, ada satu cara baru yang lebih dekat dengan keseharian banyak orang Indonesia: **WhatsApp**.

Kamu bisa catat pengeluaran, cek saldo amplop, dan terima ringkasan harian — cukup lewat chat WA, tanpa perlu buka aplikasi lain.

---

## Cara Menghubungkan Akun

Sebelum bisa pakai, akun Jatahku kamu perlu dihubungkan ke nomor WhatsApp.

**Langkah 1:** Kirim pesan `/link` ke nomor WhatsApp Jatahku.

Bot akan membalas dengan sebuah link, contoh:

```
Tap link berikut untuk menghubungkan akun WhatsApp:

https://jatahku.com/settings?wa=482910

Berlaku 5 menit.
```

**Langkah 2:** Tap link tersebut. Kamu akan diarahkan ke halaman Settings Jatahku, dan akun langsung terhubung otomatis — tanpa perlu copy-paste kode.

Setelah terhubung, semua fitur bot langsung bisa dipakai.

---

## Catat Pengeluaran dengan Bahasa Natural

Sama seperti bot Telegram, kamu cukup ketik pengeluaran dalam bahasa sehari-hari:

```
kopi 18k
```

Bot akan langsung mencatat ke amplop yang paling sesuai berdasarkan riwayat kamu.

Kalau ada lebih dari satu amplop yang cocok, bot akan menampilkan pilihan bernomor:

```
Pilih amplop untuk "kopi 18k":

1. ☕ Makan & Minum  (sisa Rp 234.000)
2. 🎉 Hiburan        (sisa Rp 87.000)

Balas dengan angka.
```

Balas `1` atau `2` — transaksi langsung tercatat.

---

## Multi-Input: Catat Beberapa Sekaligus

Kalau ada beberapa pengeluaran sekaligus, ketik dalam satu pesan dipisah koma atau baris baru:

```
kopi 18k, makan siang 35k, bensin 50k
```

Bot akan memproses semuanya sekaligus. Transaksi yang langsung dikenali akan **dicatat otomatis**. Yang belum pasti amplop-nya akan ditanyakan satu per satu.

---

## Perintah yang Tersedia

| Perintah | Fungsi |
|----------|--------|
| `/status` | Ringkasan budget periode ini |
| `/amplop` | Daftar semua amplop dan sisa saldo |
| `/webapp` | Link login ke WebApp tanpa password |
| `/link` | Hubungkan atau ganti akun |

---

## Ringkasan Harian & Mingguan

Sama seperti Telegram, bot WhatsApp juga mengirim:

- **Ringkasan harian** setiap jam 8 malam — pengeluaran hari ini, status setiap amplop, dan apakah kamu masih on track
- **Ringkasan mingguan** setiap Senin pagi — total minggu lalu, burn rate, dan prediksi akhir periode

Kamu tidak perlu melakukan apa-apa. Selama akun terhubung, ringkasan akan terkirim otomatis.

---

## Nomor WhatsApp Jatahku

Untuk mulai, kirim pesan `/link` ke nomor WhatsApp Jatahku. Nomor bisa ditemukan di halaman **Settings → WhatsApp** di [jatahku.com](https://jatahku.com).

Kalau kamu sudah pakai bot Telegram dan mau coba WA juga, keduanya bisa aktif bersamaan — transaksi yang dicatat dari salah satu channel akan langsung terlihat di dashboard dan channel lainnya.
