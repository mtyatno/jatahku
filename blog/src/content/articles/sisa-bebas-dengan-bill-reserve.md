---
title: "Sisa Bebas di Dashboard: Sudah Dipotong Tagihan dan Tabungan"
description: "Kenapa Sisa bebas di Dashboard lebih kecil dari total saldo amplopmu? Karena uang untuk tagihan langganan dan saldo amplop tabungan tidak dihitung sebagai uang bebas."
pubDate: 2026-10-05
category: tutorial
author: Tim Jatahku
cover: /covers/sisa-bebas.svg
featured: false
---

Pernah melihat saldo semua amplop masih banyak, tapi kartu **Sisa bebas** di Dashboard menunjukkan angka yang jauh lebih kecil? Itu disengaja.

Sisa bebas adalah uang yang **benar-benar bebas dipakai**. Dua hal tidak ikut dihitung:

1. **Uang untuk tagihan langganan** yang sudah disisihkan
2. **Saldo amplop tabungan**, yaitu amplop Target menabung dan Dana persiapan

Kalau keduanya ikut dihitung, angkanya terlihat lega padahal sebagian uang itu sudah punya tujuan.

## Rumusnya

```
Sisa bebas = saldo semua amplop − uang untuk tagihan − saldo amplop tabungan
```

## Kapan Tagihan Disisihkan?

Setiap langganan yang kamu daftarkan (lewat tombol **+** → **Langganan** → **Tambah Langganan**) otomatis menyisihkan uang di amplopnya:

- **Bulanan**: disisihkan penuh selama tanggal jatuh temponya masih di periode budget ini, termasuk kalau sudah lewat jatuh tempo tapi belum dibayar.
- **Tahunan**: di setiap periode, 1/12 dari nominalnya disisihkan. Bagian ini tidak menumpuk dari bulan ke bulan, jadi untuk mengumpulkan dana tagihan tahunan sampai penuh, pakai amplop Dana persiapan (baca [Jangan Kaget Pas Bayar STNK atau Uang Pangkal Sekolah: Pakai Sistem Sinking Fund](/insight/sinking-fund-cara-siapkan-tagihan-tahunan/)).
- **Mingguan**: disisihkan setara sebulan, yaitu nominal × 52 ÷ 12.

Tagihan bulanan berhenti disisihkan setelah kamu menekan **Bayar** (pengeluarannya ikut tercatat) atau **Lewati** di halaman Langganan, karena tanggal jatuh temponya pindah ke periode berikutnya. Jadi bayarlah tagihan lewat tombol **Bayar**, bukan dengan mencatat pengeluaran biasa. Kalau dicatat sebagai pengeluaran biasa, langganannya tetap terlihat belum dibayar di halaman Langganan.

## Contoh Hitungan

Misalkan dalam satu periode:

- Dana dialokasi Rp2.500.000, ditambah rollover Rp150.000 dari periode lalu, jadi total dananya Rp2.650.000
- Sudah terpakai Rp1.100.000, jadi saldo semua amplop Rp1.550.000
- Ada dua tagihan bulanan yang belum dibayar: asuransi motor Rp250.000 (jatuh tempo tanggal 8, sudah lewat) dan langganan streaming Rp49.000 (jatuh tempo tanggal 10). Totalnya Rp299.000.
- Saldo amplop Tabungan Rp500.000

```
Sisa bebas = Rp1.550.000 − Rp299.000 − Rp500.000
           = Rp751.000
```

Kalau hanya melihat saldo semua amplop, kamu mengira masih punya Rp1.550.000. Padahal yang benar-benar bebas Rp751.000.

Setelah asuransi motor dibayar lewat tombol **Bayar**, Rp250.000 itu tercatat sebagai pengeluaran dan tidak lagi disisihkan. Sisa bebasnya tetap Rp751.000, karena uang itu memang sudah disiapkan untuk tagihan tersebut.

## Di Mana Angka Ini Dipakai?

- **Kartu Sisa bebas** di Dashboard.
- **Batang di kartu Dana dialokasi**, yang membagi dana menjadi Terpakai, Tagihan, Tabungan, dan Bebas.
- **Batas aman belanja hari ini** di kartu AI Advisor. Dengan pendapatan bulanan dan 20 hari tersisa di periode, batas amannya Rp751.000 ÷ 20 = Rp37.550, dibulatkan ke bawah menjadi **Rp37.500**. Untuk pendapatan harian dan mingguan hitungannya berbeda, lihat artikel [AI Advisor Kini Ikut Ritme Pendapatanmu](/insight/ai-advisor-daily-weekly-earners/).

Satu catatan: AI Advisor hanya menghitung amplop Pengeluaran rutin. Kalau kamu punya amplop Cicilan/Utang yang masih ada saldonya, sisa bebas di AI Advisor bisa sedikit lebih kecil dari angka di kartu Sisa bebas. Dalam contoh di atas tidak ada amplop Cicilan/Utang, jadi angkanya sama.

Ada pertanyaan soal Sisa bebas? Kirim ke [hi@jatahku.com](mailto:hi@jatahku.com).
