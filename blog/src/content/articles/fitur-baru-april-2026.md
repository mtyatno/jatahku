---
title: "Update Jatahku April 2026: Dashboard Lebih Informatif, Laporan Bulan Sebelumnya, dan Notifikasi Langsung"
description: "Ringkasan fitur baru Jatahku: dashboard peringatan dipisah dari info positif, navigasi laporan PDF ke bulan sebelumnya, dan admin bisa kirim pesan langsung ke pengguna."
pubDate: 2026-04-02
category: update-fitur
author: Tim Jatahku
featured: false
---

Beberapa pembaruan baru sudah live di Jatahku. Tidak ada perubahan besar yang perlu dipelajari ulang — semuanya improvement kecil yang membuat pengalaman harian lebih nyaman.

---

## 1. Dashboard: Peringatan dan Kabar Baik Dipisah

Sebelumnya, semua notifikasi budget — entah itu peringatan amplop hampir habis maupun kabar baik bahwa kamu hemat bulan ini — ditampilkan dalam satu card merah.

Hasilnya membingungkan: kabar baik terasa seperti peringatan karena tampilnya sama-sama di background merah.

Sekarang keduanya dipisah:

**Card merah/kuning** → hanya berisi peringatan yang perlu perhatian segera, misalnya:
- Amplop hampir kosong
- Pengeluaran melampaui batas aman

**Card hijau** → hanya berisi kabar positif, misalnya:
- Kamu hemat bulan ini
- Saldo amplop masih aman

Dengan pemisahan ini, saat kamu buka dashboard dan lihat card hijau saja — kamu langsung tahu kondisi keuangan sedang baik, tanpa perlu membaca satu per satu.

---

## 2. Navigasi Laporan ke Bulan Sebelumnya

Sebelumnya, tombol **Laporan** di dashboard hanya bisa membuka laporan bulan berjalan. Untuk lihat bulan lalu? Tidak bisa dari webapp.

Sekarang, setelah laporan PDF terbuka, ada tombol navigasi **‹ ›** di toolbar:

- Klik **‹** untuk melihat laporan bulan sebelumnya
- Klik **›** untuk kembali ke bulan yang lebih baru
- Tombol **›** otomatis nonaktif saat kamu sudah di bulan berjalan

Kamu bisa menelusuri riwayat laporan tanpa menutup modal atau keluar dari halaman.

---

## 3. Bot Makin Pintar Mengingat Keyword

Saat kamu memilih amplop untuk kata tertentu di keyboard bot ("gojek → Transportasi"), bot sudah lama belajar dan mengingat pilihan itu.

Yang baru: bot sekarang juga menyimpan keyword dari **deteksi otomatis yang sudah percaya diri**. Artinya, jika bot langsung memetakan "gojek" ke Transportasi tanpa perlu konfirmasi, pemetaan itu tetap tersimpan untuk memperhalus deteksi ke depannya.

Efeknya: makin sering kamu pakai bot, makin jarang muncul keyboard konfirmasi.

---

## Catatan Teknis Lainnya

Beberapa perbaikan di balik layar:

- **Deploy health check** diperbaiki — CI/CD sekarang mengecek endpoint API yang benar sehingga status deploy lebih akurat
- **Laporan PDF** sudah konsisten menggunakan periode gajian (bukan bulan kalender), jadi laporan akurat untuk pengguna yang gajian di tanggal selain 1

---

Semua pembaruan ini sudah live dan tidak memerlukan update app. Jika kamu install Jatahku sebagai PWA di home screen, cukup buka dan refresh sekali untuk mendapat versi terbaru.

Ada saran fitur atau laporan bug? Hubungi kami melalui halaman [jatahku.com](https://jatahku.com).
