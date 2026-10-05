---
title: "AI Advisor Kini Ikut Ritme Pendapatanmu: Harian, Mingguan, atau Bulanan"
description: "Batas aman belanja di AI Advisor sekarang dihitung dari jenis pendapatanmu. Yang dapat uang setiap hari tidak lagi diminta berhemat seolah gajian masih sebulan lagi."
pubDate: 2026-10-05
category: update-fitur
author: Tim Jatahku
cover: /covers/ai-advisor-ritme-pendapatan.svg
featured: true
---

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

Batas aman hari ini = **sisa bebas ÷ jumlah hari yang harus ditutup**, lalu dibulatkan ke bawah ke kelipatan Rp100.

| Jenis pendapatan | Sisa bebas dibagi |
|---|---|
| Harian | 1 hari, karena pemasukan berikutnya datang besok |
| Mingguan | 7 hari |
| Bulanan dan Tidak Tentu | sisa hari sampai periode budget selesai |

Sisa bebas di sini sudah dipotong belanja hari ini, uang yang disisihkan untuk tagihan langganan, dan saldo amplop tabungan. Penjelasan lengkapnya ada di artikel [Sisa Bebas di Dashboard](/insight/sisa-bebas-dengan-bill-reserve/).

**Contoh hitungan:**

| Jenis | Sisa bebas | Dibagi | Aman hari ini |
|---|---|---|---|
| Harian | Rp180.000 | 1 hari | Rp180.000 |
| Mingguan | Rp420.000 | 7 hari | Rp60.000 |
| Bulanan | Rp751.000 | 20 hari tersisa | Rp37.500 (dari Rp37.550, dibulatkan ke bawah) |

Untuk pendapatan **Harian**, seluruh sisa bebas boleh dipakai hari ini karena besok ada pemasukan baru. AI Advisor baru bilang kamu lewat batas kalau sisa bebasnya sudah minus.

## Di Mana Terlihat?

**1. Baris pertama kartu AI Advisor di Dashboard.** Bunyinya "Hari ini masih aman belanja Rp…", atau "Hari ini sudah lewat Rp… dari jatah harian" kalau sudah kelewatan. Ketuk barisnya untuk melihat hitungannya:

- Harian dan Mingguan: "Sisa bebas semua amplop", "Sampai income berikutnya", "Jatah hari ini = sisa ÷ … hari", dan "Terpakai hari ini (sudah dipotong)".
- Bulanan dan Tidak Tentu: "Sisa bebas semua amplop", "Hari tersisa", "Jatah per hari = sisa ÷ hari", dan "Terpakai hari ini".

**2. Kartu Sisa bebas.** Di bawah angkanya ada baris "≈Rp…/hari aman" dengan angka yang sama.

**3. Grafik Pengeluaran harian.** Garis putus-putus "Batas aman Rp…/hari" juga memakai angka yang sama.

**4. Peringatan per amplop.** Untuk pendapatan Harian dan Mingguan, AI Advisor memperingatkan sebuah amplop hanya kalau isinya diperkirakan habis sebelum pemasukan berikutnya, dengan kecepatan belanjamu saat ini. Contohnya:

- Harian: **"🍜 Makan di Jalan: maksimal Rp25.000 hari ini"**, dengan penjelasan "Biasanya Rp35.000/hari, sisa amplop tinggal Rp25.000 sampai income berikutnya besok."
- Mingguan: **"⛽ Bensin & Operasional: maksimal Rp20.000/hari"**, dengan penjelasan "Kalau tetap Rp30.000/hari, sisa Rp140.000 habis sebelum income berikutnya (7 hari lagi)."

Setiap peringatan punya tautan **Atur alokasi** yang membuka halaman Alokasi.

## Kenapa Ini Penting?

Batas aman yang terlalu ketat sama tidak bergunanya dengan yang terlalu longgar. Driver ojol, pedagang, dan pekerja harian sekarang mendapat angka yang mengikuti kapan uang mereka benar-benar masuk, bukan asumsi gajian akhir bulan.

Punya masukan? Kirim ke [hi@jatahku.com](mailto:hi@jatahku.com).
