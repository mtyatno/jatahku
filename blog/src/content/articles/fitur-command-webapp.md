---
title: "Perintah /webapp: Buka Dashboard Jatahku Langsung dari Telegram Tanpa Password"
description: "Fitur /webapp menghasilkan link login sekali pakai yang membuka webapp Jatahku secara otomatis — tanpa ketik email, tanpa ketik password, langsung masuk."
pubDate: 2026-04-03
category: update-fitur
author: Tim Jatahku
cover: /covers/fitur-command-webapp.svg
featured: false
---

Ada satu skenario yang sering terjadi: kamu sedang pakai Telegram untuk catat pengeluaran, lalu tiba-tiba perlu cek detail budget, lihat grafik analitik, atau atur ulang alokasi amplop. Tapi untuk itu kamu harus buka browser, buka jatahku.com, dan login dulu.

Langkah kecil — tapi cukup untuk membuatmu malas melakukannya.

Perintah `/webapp` menghilangkan hambatan itu.

---

## Apa Itu `/webapp`?

`/webapp` adalah perintah bot Telegram yang menghasilkan **link login sekali pakai** ke Jatahku Webapp. Satu klik pada link itu, dan kamu langsung masuk ke dashboard — tanpa ketik email, tanpa ketik password.

Link ini:
- **Berlaku 5 menit** sejak dibuat
- **Hanya bisa digunakan sekali** — setelah diklik, link langsung kedaluwarsa
- **Otomatis login** ke akun yang terhubung dengan Telegram kamu

---

## Cara Pakai

Sangat sederhana. Buka chat [@JatahkuBot](https://t.me/JatahkuBot) dan ketik:

```
/webapp
```

Bot akan membalas dengan link seperti ini:

> 🔐 **Login ke Jatahku Webapp**
>
> Klik link berikut untuk masuk:
> https://jatahku.com/auth/tg?token=...
>
> ⏱ Link berlaku **5 menit** dan hanya bisa digunakan sekali.

Klik link tersebut — browser terbuka dan kamu langsung masuk ke dashboard Jatahku.

---

## Kapan Ini Berguna?

### Setelah Catat Banyak Pengeluaran

Kamu baru saja mencatat beberapa transaksi via bot. Mau lihat progress bar tiap amplop secara visual? Ketik `/webapp`, klik link, langsung ke halaman Amplop.

### Saat Perlu Atur Ulang Alokasi

Di tengah bulan, kamu sadar alokasi Makan terlalu kecil dan Hiburan terlalu besar. Daripada buka browser dari nol dan login manual — ketik `/webapp` dari Telegram, selesai dalam 10 detik.

### Akses Analytics dan Laporan

Mau lihat grafik tren pengeluaran bulan ini? Atau cetak laporan PDF bulan lalu? Fitur-fitur ini ada di webapp, bukan di bot. `/webapp` adalah jembatan tercepat untuk ke sana.

### Kelola Langganan & Sinking Fund

Tambah langganan baru, ubah nominal, atau nonaktifkan sementara — semua bisa dilakukan di webapp. Akses langsung lewat `/webapp` tanpa login ulang.

### Saat Buka Jatahku di HP Baru atau Browser Berbeda

Belum login di browser HP kamu? Atau pakai laptop kantor yang tidak tersimpan session? Ketik `/webapp` dari Telegram, link langsung bisa dipakai tanpa perlu ingat password.

---

## Kenapa Tidak Perlu Password?

`/webapp` menggunakan sistem **magic link** — metode autentikasi yang banyak dipakai aplikasi modern.

Cara kerjanya:
1. Kamu ketik `/webapp` di Telegram
2. Bot memverifikasi bahwa akun Telegram kamu memang terhubung ke Jatahku
3. Sistem membuat token unik yang disimpan sementara (5 menit)
4. Token itu dikirim sebagai bagian dari link
5. Saat kamu klik link, sistem mencocokkan token dan langsung login

Karena Telegram sudah memverifikasi identitasmu, tidak perlu login ulang dengan email dan password. Token sekali pakai memastikan link tidak bisa disalahgunakan jika tersebar.

---

## Yang Perlu Diperhatikan

**Jangan bagikan link ke orang lain.** Link ini langsung login ke akunmu. Jika ada yang mengkliknya sebelum kamu, mereka akan masuk ke akunmu. Perlakukan seperti password sementara.

**Link kadaluwarsa dalam 5 menit.** Jika tidak sempat diklik, cukup ketik `/webapp` lagi untuk generate link baru.

**Perlu terhubung ke Telegram dulu.** Jika akunmu belum dihubungkan ke Telegram, `/webapp` tidak akan berfungsi. Hubungkan dulu lewat Settings → Generate Link Telegram di webapp.

---

## Ringkasan

| | Tanpa `/webapp` | Dengan `/webapp` |
|--|-----------------|-----------------|
| Buka webapp | Buka browser → ketik URL → login | Ketik `/webapp` → klik link |
| Langkah | 4–5 langkah | 2 langkah |
| Perlu ingat password | Ya | Tidak |
| Waktu | ~30 detik | ~5 detik |

Untuk pengguna yang sudah terbiasa catat pengeluaran via Telegram, `/webapp` membuat transisi ke webapp jadi mulus — tanpa hambatan, tanpa interupsi.
