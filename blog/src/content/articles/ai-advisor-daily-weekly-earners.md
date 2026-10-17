---
title: "AI Advisor Kini Ikut Ritme Pendapatanmu: Harian, Mingguan, atau Bulanan"
description: "Batas aman belanja di AI Advisor sekarang dihitung dari jenis pendapatanmu. Yang dapat uang setiap hari tidak lagi diminta berhemat seolah gajian masih sebulan lagi."
pubDate: 2026-10-05
updatedDate: 2026-10-17
category: update-fitur
author: Tim Jatahku
cover: /covers/ai-advisor-ritme-pendapatan.svg
featured: true
---

**Diperbarui 17 Oktober 2026:** ada dua angka harian sekarang. **Jatah hari ini** tetap sepanjang hari, dan **aman per hari ke depan** sudah memperhitungkan belanja hari ini. Keduanya tetap mengikuti jenis pendapatanmu. Bagian "Cara Hitungnya" dan "Di Mana Terlihat?" di bawah sudah disesuaikan. Gambaran besarnya ada di [AI Advisor Baru: Analisa dan Tombol Aksi di Setiap Halaman](/insight/ai-advisor-di-setiap-halaman/).

Sebelumnya, AI Advisor menghitung batas aman belanja dengan cara yang sama untuk semua orang: **sisa bebas dibagi sisa hari sampai periode budget selesai**.

Cara itu pas untuk yang gajian bulanan. Tapi bayangkan driver ojol yang punya sisa bebas Rp180.000 dan periodenya masih 20 hari. Dengan cara lama, batas amannya hanya Rp9.000 per hari, padahal besok dia sudah dapat pemasukan lagi.

Sekarang AI Advisor memperhitungkan **jenis pendapatan** kamu.

## Atur Jenis Pendapatan

Buka **Settings → 💼 Jenis Pendapatan** dan pilih salah satu:

- **📅 Bulanan**: gaji tetap setiap bulan
- **📆 Mingguan**: pendapatan setiap minggu
- **📈 Harian**: pendapatan setiap hari
- **❓ Tidak Tentu**: pendapatan tidak teratur

Akun baru sudah ditanya soal ini saat onboarding. Akun yang dibuat sebelumnya dihitung sebagai **Bulanan** sampai kamu mengubahnya di Settings.

## Cara Hitungnya

Ada dua angka. Keduanya dibulatkan ke bawah ke kelipatan Rp100.

- **Jatah hari ini** = sisa bebas **di awal hari** ÷ jumlah hari yang harus ditutup, **termasuk hari ini**. Angka ini tetap sepanjang hari, berapa pun yang kamu catat. Inilah pembanding di kartu Jatah hari ini.
- **Aman per hari ke depan** = sisa bebas **sekarang** ÷ jumlah hari yang harus ditutup **setelah hari ini**. Angka ini turun kalau hari ini kamu belanja melebihi jatah.

| Jenis pendapatan | Jatah hari ini dibagi | Aman ke depan dibagi |
|---|---|---|
| Harian | 1 hari | 1 hari, karena pemasukan berikutnya datang besok |
| Mingguan | 7 hari | 7 hari |
| Bulanan dan Tidak Tentu | sisa hari + hari ini | sisa hari sampai periode budget selesai |

Sisa bebas di sini dihitung dari amplop belanja, yaitu **Pengeluaran rutin dan Cicilan/Utang**, dikurangi yang sudah terpakai dan tagihan yang belum dibayar. Amplop tabungan tidak ikut. Penjelasan lengkapnya ada di artikel [Sisa Bebas di Dashboard](/insight/sisa-bebas-dengan-bill-reserve/).

**Contoh hitungan (pendapatan bulanan, 11 hari tersisa setelah hari ini):**

- Sisa bebas awal hari Rp1.982.300 ÷ 12 hari = jatah hari ini **Rp165.100**.
- Hari ini belanja Rp297.100, jadi lewat Rp132.000. Sisa bebas sekarang Rp1.685.200.
- Rp1.685.200 ÷ 11 hari = aman ke depan **Rp153.200/hari**.

| Jenis | Sisa bebas | Dibagi | Aman ke depan |
|---|---|---|---|
| Harian | Rp180.000 | 1 hari | Rp180.000 |
| Mingguan | Rp420.000 | 7 hari | Rp60.000 |
| Bulanan | Rp751.000 | 20 hari tersisa | Rp37.500 (dari Rp37.550, dibulatkan ke bawah) |

Untuk pendapatan **Harian**, seluruh sisa bebas boleh dipakai hari ini karena besok ada pemasukan baru.

## Di Mana Terlihat?

**1. Kartu Jatah hari ini.** Belanja hari ini dibandingkan dengan jatah sejak pagi, misalnya "Rp297.100 / Rp165.100". Chip ✦ di pojoknya merangkum hasilnya, misalnya "1,8× jatah" atau "Sisa Rp40 rb hari ini". Ketuk chip itu untuk melihat hitungannya: "Jatah hari ini sejak pagi", "Belanja hari ini", "Aman 11 hari ke depan", dan penyumbang terbesar.

**2. Kartu Sisa bebas.** Di bawah angkanya ada "aman Rp…/hari", yaitu angka aman ke depan.

**3. Grafik Pengeluaran harian.** Jatah tiap hari digambar dari angka yang sama.

**4. Chat web dan Telegram.** Ketik "limit harian" untuk melihat jatah hari ini, belanja hari ini, dan aman ke depan. Angkanya persis sama dengan Beranda.

**5. Peringatan per amplop.** Untuk pendapatan Harian dan Mingguan, AI Advisor memperingatkan sebuah amplop hanya kalau isinya diperkirakan habis sebelum pemasukan berikutnya, dengan kecepatan belanjamu saat ini. Contohnya:

- Harian: **"🍜 Makan di Jalan: maksimal Rp25.000 hari ini"**, dengan penjelasan "Biasanya Rp35.000/hari, sisa amplop tinggal Rp25.000 sampai income berikutnya besok."
- Mingguan: **"⛽ Bensin & Operasional: maksimal Rp20.000/hari"**, dengan penjelasan "Kalau tetap Rp30.000/hari, sisa Rp140.000 habis sebelum income berikutnya (7 hari lagi)."

Peringatan ini muncul di kartu AI Advisor dan di strip kartu amplopnya, lengkap dengan tombol seperti **Geser dana**.

## Kenapa Ini Penting?

Batas aman yang terlalu ketat sama tidak bergunanya dengan yang terlalu longgar. Driver ojol, pedagang, dan pekerja harian sekarang mendapat angka yang mengikuti kapan uang mereka benar-benar masuk, bukan asumsi gajian akhir bulan.

Punya masukan? Kirim ke [hi@jatahku.com](mailto:hi@jatahku.com).
