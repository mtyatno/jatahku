---
title: "Memahami Budget Amount — Rencana vs Realisasi di Jatahku"
description: "Apa itu budget_amount? Kenapa penting? Bagaimana bedanya dengan allocated? Tutorial lengkap memahami konsep budget di envelope budgeting."
pubDate: 2026-06-29
category: tutorial
author: "Tim Jatahku"
cover: /covers/cara-pakai-bot-telegram.svg
---

Salah satu konsep yang sering ditanyakan pengguna Jatahku: **apa bedanya budget_amount dan allocated?** Kenapa amplop punya dua angka yang mirip?

Artikel ini akan menjelaskan perbedaan keduanya, kenapa budget_amount penting, dan bagaimana cara mengaturnya dengan benar.

## Budget vs Allocated — Dua Konsep Berbeda

| | Budget | Allocated |
|---|---|---|
| **Artinya** | Rencana/target bulanan | Uang aktual yang masuk |
| **Kapan di-set** | Sekali saat buat amplop | Setiap kali ada income |
| **Berubah?** | Tetap (kecuali diedit manual) | Dinamis (bertambah tiap alokasi) |
| **Gunanya di sistem** | Bobot distribusi proporsional | Menunjukkan realisasi |

**Contoh konkret:**

Kamu membuat amplop "Makan" dengan budget 2.000.000/bulan. Budget ini adalah **rencana** — kamu memperkirakan butuh sekitar 2 juta untuk makan sebulan.

Bulan ini income kamu 8 juta. Sistem mendistribusikan secara proporsional berdasarkan budget: Makan dapat 1.500.000 (karena total budget semua amplop = 10,5jt, jadi Makan = 2/10,5 × 8jt = 1,5jt).

Di dashboard:
- **Budget** = 2.000.000 (rencana, tetap)
- **Allocated** = 1.500.000 (realisasi, sesuai income bulan ini)
- **Funded ratio** = 75% (baru terpenuhi 75% dari rencana)

Bulan depan income 12 juta? Allocated bisa 2.300.000 (110% funded). Budget tetap 2.000.000 — karena rencana tidak berubah.

## Kenapa Budget Tidak Auto-Set dari Allocated?

Kalau budget otomatis mengikuti allocated setiap bulan, maka:
- Bulan income kecil → budget kecil → distribusi proporsional kacau
- Bulan income besar → budget besar → tidak realistis untuk bulan berikutnya
- Tidak ada patokan stabil untuk perencanaan

**Budget harus stabil** supaya sistem proportional distribution bekerja dengan konsisten. Kamu tidak ingin amplop Makan tiba-tiba dapat porsi 50% lebih besar hanya karena bulan lalu income besar.

## Cara Setting Budget yang Benar

### 1. Untuk Amplop Baru

Saat membuat amplop baru via FAB atau halaman Amplop, sistem akan **otomatis mengisi budget** dari jumlah funding yang kamu masukkan:

- Isi funding Rp 2.000.000 → budget auto-set ke Rp 2.000.000
- Kamu bisa mengubahnya manual kalau rencana berbeda dari funding awal

### 2. Untuk Amplop Existing

Kalau kamu sudah punya amplop yang budget-nya 0 (belum diisi), sistem akan **otomatis mengisi budget** dari rata-rata alokasi historis saat server restart. Kamu juga bisa mengeditnya manual kapan saja via halaman Amplop → Edit.

### 3. Untuk Amplop Saving

Amplop tipe saving **tidak perlu budget**. Fokusnya adalah target goal (Rp 10.000.000 untuk Nikah), bukan budget bulanan. Budget otomatis di-set ke 0 dan tidak bisa diubah.

### 4. Untuk Amplop Sinking Fund

Amplop tipe sinking fund **boleh diisi budget** sebagai panduan opsional. Kalau kamu memperkirakan butuh sisihkan 500rb/bulan untuk pajak tahunan, kamu bisa set budget = 500.000. Tapi yang utama tetap target goal + deadline.

## Apa Dampaknya Kalau Budget = 0?

Untuk amplop expense, budget = 0 berarti:

- **Tidak punya bobot** di proportional distribution — amplop ini tidak dapat jatah otomatis
- **Funded ratio selalu 0%** — tidak ada indikator ketercapaian rencana
- **Tidak muncul di AI Advisor** untuk allocation drift

Karena itu, pastikan setiap amplop expense memiliki budget > 0. Sistem akan membantu dengan auto-fill, tapi kamu tetap bisa menyesuaikan manual.

---

Budget amount adalah fondasi dari **zero-based envelope budgeting** — setiap rupiah punya jatahnya, dan setiap jatah punya rencana. Dengan budget yang benar, Jatahku bisa membantu kamu mendistribusikan income secara proporsional, memonitor kesehatan amplop, dan memberi insight yang akurat.
