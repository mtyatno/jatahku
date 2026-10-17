---
title: "Sisa Bebas di Dashboard: Sudah Dipotong Tagihan dan Tabungan"
description: "Kenapa Sisa bebas di Dashboard lebih kecil dari total saldo amplopmu? Karena uang untuk tagihan langganan dan saldo amplop tabungan tidak dihitung sebagai uang bebas."
pubDate: 2026-10-05
updatedDate: 2026-10-17
category: tutorial
author: Tim Jatahku
cover: /covers/sisa-bebas.svg
featured: false
---

**Diperbarui 17 Oktober 2026:** sisa bebas sekarang dihitung dari amplop belanja saja (Pengeluaran rutin dan Cicilan/Utang). Tagihan yang dipotong adalah yang **belum dibayar**, dan angka di kartu Sisa bebas, AI Advisor, chat, serta Telegram kini selalu sama.

Pernah melihat saldo semua amplop masih banyak, tapi kartu **Sisa bebas** di Dashboard menunjukkan angka yang jauh lebih kecil? Itu disengaja.

Sisa bebas adalah uang yang **benar-benar bebas dipakai**. Dua hal tidak ikut dihitung:

1. **Uang untuk tagihan langganan** yang sudah disisihkan
2. **Saldo amplop tabungan**, yaitu amplop Target menabung dan Dana persiapan

Kalau keduanya ikut dihitung, angkanya terlihat lega padahal sebagian uang itu sudah punya tujuan.

## Rumusnya

```
Sisa bebas = dana amplop belanja − yang sudah terpakai − tagihan belum dibayar
```

Amplop belanja adalah amplop **Pengeluaran rutin** dan **Cicilan/Utang**. Amplop tabungan (Target menabung dan Dana persiapan) tidak ikut sama sekali, jadi saldonya tidak perlu dikurangkan lagi.

## Kapan Tagihan Disisihkan?

Setiap langganan yang kamu daftarkan (lewat tombol **+** → **Langganan** → **Tambah Langganan**) otomatis menyisihkan uang di amplopnya:

- **Bulanan**: disisihkan penuh selama tanggal jatuh temponya masih di periode budget ini, termasuk kalau sudah lewat jatuh tempo tapi belum dibayar.
- **Tahunan**: di setiap periode, 1/12 dari nominalnya disisihkan. Bagian ini tidak menumpuk dari bulan ke bulan, jadi untuk mengumpulkan dana tagihan tahunan sampai penuh, pakai amplop Dana persiapan (baca [Jangan Kaget Pas Bayar STNK atau Uang Pangkal Sekolah: Pakai Sistem Sinking Fund](/insight/sinking-fund-cara-siapkan-tagihan-tahunan/)).
- **Mingguan**: disisihkan sebanyak kemunculan yang tersisa sampai akhir periode × nominal.

Tagihan bulanan berhenti disisihkan setelah kamu menekan **Bayar** (pengeluarannya ikut tercatat) atau **Lewati** di halaman Langganan, karena tanggal jatuh temponya pindah ke periode berikutnya. Paling rapi bayar lewat tombol **Bayar**.

Kalau terlanjur mencatatnya sebagai pengeluaran biasa dengan nominal yang persis sama, Jatahku menganggap tagihannya sudah dibayar. AI Advisor juga menawarkan **Tandai lunas** supaya halaman Langganan ikut beres. Sudah bayar di luar Jatahku tanpa mencatat? Pakai **Tandai lunas** juga.

## Contoh Hitungan

Misalkan dalam satu periode:

- Dana dialokasi Rp2.500.000, ditambah rollover Rp150.000 dari periode lalu, jadi total dananya Rp2.650.000. Dari situ, Rp500.000 masuk amplop Tabungan, jadi dana amplop belanja Rp2.150.000.
- Sudah terpakai Rp1.100.000 dari amplop belanja. Saldo semua amplop jadi Rp1.550.000 (termasuk Tabungan).
- Ada dua tagihan bulanan yang belum dibayar: asuransi motor Rp250.000 (jatuh tempo tanggal 8, sudah lewat) dan langganan streaming Rp49.000 (jatuh tempo tanggal 10). Totalnya Rp299.000.

```
Sisa bebas = Rp2.150.000 − Rp1.100.000 − Rp299.000
           = Rp751.000
```

Kalau hanya melihat saldo semua amplop, kamu mengira masih punya Rp1.550.000. Padahal yang benar-benar bebas Rp751.000.

Setelah asuransi motor dibayar lewat tombol **Bayar**, Rp250.000 itu tercatat sebagai pengeluaran dan tidak lagi disisihkan. Sisa bebasnya tetap Rp751.000, karena uang itu memang sudah disiapkan untuk tagihan tersebut.

## Di Mana Angka Ini Dipakai?

- **Kartu Sisa bebas** di Dashboard, beserta chip-nya ("Habis ±24 Okt" atau "Cukup s/d 26 Okt").
- **Batas aman per hari.** Dengan pendapatan bulanan dan 20 hari tersisa, batas amannya Rp751.000 ÷ 20 = Rp37.550, dibulatkan ke bawah menjadi **Rp37.500**. Untuk pendapatan harian dan mingguan hitungannya berbeda, lihat artikel [AI Advisor Kini Ikut Ritme Pendapatanmu](/insight/ai-advisor-daily-weekly-earners/).
- **Chat web dan Telegram.** Jawaban untuk "sisa", "/status", dan "kapan habis?", serta ringkasan harian.

Semua tempat itu membaca angka dari satu sumber, jadi tidak ada lagi selisih antara kartu Sisa bebas dan AI Advisor.

Ada pertanyaan soal Sisa bebas? Kirim ke [hi@jatahku.com](mailto:hi@jatahku.com).
