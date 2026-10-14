---
title: "Update Jatahku Oktober 2026: Foto Struk, Chat di Webapp, dan Telegram Setara Webapp"
description: "Pembaruan 15 Oktober 2026: catat dari foto struk, chat bot di webapp, transaksi tidak lagi ditahan, dan aturan yang sama di webapp dan Telegram."
pubDate: 2026-10-15
category: update-fitur
author: Tim Jatahku
cover: /covers/update-oktober-2026.svg
featured: false
---

Pembaruan kali ini cukup banyak: dua fitur baru, satu perubahan cara kerja, dan sejumlah perbaikan supaya webapp dan bot Telegram berperilaku sama. Semuanya sudah live.

## 1. Catat dari Foto Struk

Di form **Pengeluaran**, ketuk **Struk** lalu foto struk belanjamu. Jatahku membaca rincian barangnya, mencocokkannya dengan total struk, lalu mencatat tiap barang sebagai satu transaksi di amplopnya sendiri, misalnya `ROTI TAWAR (Indomaret)` di amplop Makan dan `SABUN MANDI (Indomaret)` di amplop Rumah Tangga.

Lewat chat, cukup kirim fotonya ke [@JatahkuBot](https://t.me/JatahkuBot) di Telegram, atau ketuk **Struk** di Chat Jatahku di webapp. Struk dicatat sebagai satu transaksi dengan tanggal yang tertulis di struk.

Panduan lengkapnya ada di artikel [Catat Belanja dari Foto Struk](/insight/catat-belanja-dari-foto-struk/).

## 2. Chat Jatahku di Webapp

Bot yang sama dengan @JatahkuBot sekarang ada di dalam webapp, jadi kamu tidak perlu akun Telegram untuk mencatat lewat chat. Di HP, ketuk tombol gelembung chat di samping tombol **+**. Di laptop, ketuk ikon chat di bagian atas halaman.

Chat ini juga bisa menerima foto struk. Balasannya memakai ikon dan bar pemakaian yang sama dengan bagian lain aplikasi.

Baca selengkapnya di [Chat Jatahku Kini Ada di Webapp](/insight/chat-jatahku-di-webapp/).

## 3. Cooling Period Tidak Lagi Menahan Transaksi

Dulu, pengeluaran di atas batas cooling ditahan 24 jam sebelum tercatat. Dari webapp, pengeluaran seperti itu malah tidak bisa dicatat sama sekali.

Masalahnya, kebanyakan dari kita mencatat **setelah** membayar. Menahan catatan tidak membatalkan pembelian. Yang hilang hanya catatannya, dan sisa amplop jadi tidak sesuai dengan uang yang sebenarnya.

Sekarang pengeluaran di atas batas cooling langsung tercatat, di webapp maupun Telegram. Batas cooling tetap tersimpan dan akan dipakai fitur refleksi "Sepadan?" yang segera hadir. Transaksi yang masih tertahan bisa kamu konfirmasi atau batalkan lewat `/pending` selama belum kedaluwarsa, yaitu 48 jam setelah dicatat.

Alasan lengkapnya ada di artikel [Kenapa Jatahku Tidak Lagi Menahan Transaksi 24 Jam](/insight/fitur-cooling-period-anti-belanja-impulsif/).

## 4. Kontrol Amplop untuk Semua Paket

Kunci amplop, limit harian, dan batas cooling tersedia di semua paket, termasuk Basic. Halaman Upgrade tidak lagi mencantumkannya sebagai fitur khusus Pro.

## 5. Webapp dan Telegram Kini Mengikuti Aturan yang Sama

**Isi dana amplop dari Telegram.** Kalau dana amplop kurang, bot menawarkan dua cara: geser dana dari amplop lain, dengan amplop yang sisanya paling besar ditampilkan lebih dulu, atau catat pemasukan sebesar kekurangannya. Setelah kamu memilih, transaksinya langsung tercatat. Ini juga berlaku saat mencatat beberapa pengeluaran sekaligus: tiap item yang kurang dana ditawari satu per satu.

**Naikkan limit harian dari webapp.** Kalau pengeluaran melewati limit harian, webapp sekarang menawarkan **Catat, naikkan limit hari ini**, sama seperti bot. Limit amplop itu dinaikkan sampai tengah malam, lalu kembali normal besok. Di form beberapa pengeluaran sekaligus, tombolnya **Naikkan limit** di baris yang terkena. Di Telegram, tawaran yang sama kini juga muncul saat mencatat beberapa pengeluaran sekaligus.

**Beberapa pengeluaran tanpa koma di Telegram.** Pesan seperti ini sekarang terbaca sebagai dua pengeluaran:

```
kopi 35 ribu gojek 20 ribu
35k kopi 20k parkir
```

Angka tanpa satuan tidak memecah pengeluaran, jadi `beli 2 kopi 25 ribu` tetap terbaca sebagai satu pengeluaran sebesar Rp25.000. Webapp dan bot sekarang memakai aturan baca nominal yang sama, jadi teks yang sama memberi hasil yang sama di keduanya.

**Amplop tabungan tidak ditawarkan untuk pengeluaran.** Di Telegram, pilihan amplop untuk pengeluaran tidak lagi menampilkan amplop Target menabung dan Dana persiapan, dan pengeluaran tidak bisa dicatat langsung ke amplop tersebut. Aturan ini sama dengan di webapp.

## 6. Perbaikan Lainnya

- **Notifikasi "🎯 Goal tercapai!"** sekarang terkirim saat saldo amplop melewati targetnya, misalnya setelah income dibagi atau dana dipindahkan ke amplop itu. Sebelumnya notifikasi ini tidak pernah terkirim.
- **Simpan ulang tanpa dobel.** Kalau koneksi putus saat kamu menyimpan dari form Catat pengeluaran, baris yang hasilnya belum pasti ditandai dan dikunci. Tekan Simpan lagi, dan transaksi yang sudah tercatat tidak akan tercatat dua kali. Perlindungan yang sama berlaku untuk transaksi dari antrean offline.
- **Transaksi offline yang ditolak tidak hilang lagi.** Dulu, transaksi yang dicatat saat offline lalu ditolak waktu dikirim, misalnya karena dana amplop kurang atau amplop dikunci, bisa hilang tanpa pemberitahuan. Sekarang muncul pemberitahuan "⚠️ … transaksi yang dicatat saat offline gagal tersimpan". Ketuk **Tinjau** untuk melihat alasannya, mengganti amplop, mencoba lagi, atau menghapusnya.
- **Kuota Basic tidak memutus pencatatan di tengah jalan.** Kalau kuota 50 transaksi per bulan habis di tengah satu kali mencatat, misalnya saat menyimpan beberapa pengeluaran sekaligus, pencatatan itu tetap diselesaikan utuh. Sesudahnya Jatahku memberi tahu bahwa kuota sudah habis dan tanggal berapa bisa mencatat lagi.
- **Keterangan panjang tidak lagi gagal disimpan.** Keterangan lebih dari 500 karakter sekarang dipotong otomatis.
- **Versi aplikasi di Settings.** Di bagian paling bawah Settings sekarang tertulis versi aplikasi, misalnya "Versi 1a2b3c4". Kalau melaporkan masalah, sertakan versi ini.

---

Semua pembaruan ini sudah live. Kalau Jatahku terpasang di home screen dan fitur barunya belum muncul, tutup aplikasinya lalu buka lagi. Versi yang sedang aktif bisa dicek di bagian bawah Settings.

Ada saran atau menemukan masalah? Kirim ke [hi@jatahku.com](mailto:hi@jatahku.com).
