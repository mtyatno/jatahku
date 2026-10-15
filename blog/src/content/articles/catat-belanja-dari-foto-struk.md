---
title: "Catat Belanja dari Foto Struk: Tiap Barang Masuk Amplopnya Sendiri"
description: "Foto struk di webapp, dan Jatahku mencatat tiap barang ke amplopnya sendiri setelah mencocokkannya dengan total. Chat dan bot Telegram juga bisa membaca struk."
pubDate: 2026-10-15
category: update-fitur
author: Tim Jatahku
cover: /covers/scan-struk.svg
featured: true
---

Belanja di minimarket jarang hanya satu jenis barang. Satu struk bisa berisi roti, susu, sabun, dan deterjen. Kalau dicatat satu baris saja, misalnya `indomaret 64.900`, semuanya masuk ke satu amplop. Padahal roti dan susu milik amplop Makan, sedangkan sabun dan deterjen milik amplop Rumah Tangga.

Sekarang kamu cukup memfoto strukmu. Jatahku membaca rincian barangnya, mencocokkan jumlahnya dengan total di struk, lalu mencatat tiap barang ke amplopnya sendiri.

## Cara Pakai di Webapp

1. Ketuk tombol **+** di kanan bawah, lalu pilih **Pengeluaran**.
2. Ketuk **Struk** di atas kotak ketik. Tombolnya berikon kamera dan ada di samping tombol **Suara**.
3. Ambil foto struk atau pilih foto dari galeri. Selama struk dibaca, muncul tulisan "Membaca struk...".
4. Kartu struk muncul berisi nama toko, tanggal struk, total, dan pilihan amplop. Semuanya bisa kamu ubah.
5. Periksa rinciannya, pilih amplop, lalu ketuk **Simpan Semua**.

Kalau tanggal di struk terbaca, transaksi tercatat dengan tanggal itu, bukan tanggal hari ini. Struk kemarin yang baru sempat kamu foto malam ini tetap tercatat di hari belanjanya.

Jatahku juga mencocokkan total dengan pembayaran yang tertulis di struk, yaitu uang tunai dikurangi kembalian atau pembayaran non-tunai. Kalau totalnya belum bisa dipastikan, kolom total diberi warna kuning dan ada keterangan seperti "cek lagi nominalnya".

## Rincian Barang Dicocokkan dengan Total

Di bawah kepala struk ada bilah status:

- **✓ Rincian 4 barang cocok dengan total** (hijau). Jumlah semua barang, dikurangi diskon dan ditambah pajak, sama dengan total struk.
- **Rincian Rp… · total Rp… · kurang Rp…** (kuning). Ada selisih. Mungkin ada barang yang tidak terbaca, ada yang terbaca dua kali, atau ada diskon yang terlewat.

Kalau rinciannya cocok, daftar barang dilipat. Ketuk **Lihat 4 barang** untuk membukanya. Setiap barang menampilkan nama dan harganya, plus keterangan bila ada, misalnya `2 × Rp 9.000` atau `voucher −Rp 2.000`. Nama dan harga barang bisa diubah, dan barang bisa dihapus lewat tombol ×.

Jatahku hanya membetulkan angka sendiri kalau buktinya jelas di struk, misalnya jumlah barang dikali harga satuan. Barang yang meragukan ditandai ⚠ beserta sarannya:

- **Pakai Rp…** mengganti harga barang dengan nilai yang disarankan.
- **Hapus barang ini** muncul kalau barangnya kemungkinan terbaca dua kali.

Angka tidak pernah diubah diam-diam. Kalau rincian masih kurang dari total karena ada barang yang tidak terbaca, ketuk **Tambah "Lainnya"** untuk menambah satu baris sebesar selisihnya.

## Satu Barang, Satu Transaksi

Setiap barang bisa punya amplop sendiri. Pilihan amplopnya ada di baris barang itu. Kalau dibiarkan **Ikut amplop struk**, barang masuk ke amplop yang dipilih di kepala struk.

Saat disimpan, tiap barang menjadi satu transaksi. Keterangannya berisi nama barang lalu nama toko, misalnya:

```
ROTI TAWAR (Indomaret)
SUSU UHT (Indomaret)
SABUN MANDI (Indomaret)
DETERJEN (Indomaret)
```

Dengan nama barang di depan, daftar transaksimu mudah dipindai. Kalau nanti kamu bertanya "bulan ini habis berapa untuk deterjen?", jawabannya ada di sana.

Sebelum menyimpan, Jatahku menampilkan rencananya, misalnya "Dicatat 4 transaksi, 1 per barang", lalu ringkasan per amplop seperti "Makan · 2 barang" beserta jumlahnya. Total semua transaksi **selalu sama dengan total struk**:

- Voucher yang melekat ke satu barang mengurangi harga barang itu saja.
- Diskon belanja, pajak, dan selisih yang belum terjelaskan dibagi ke semua barang sesuai nilainya masing-masing.
- Barang yang menjadi gratis karena voucher tidak dicatat.

Kalau rincian barang sama sekali tidak terbaca, struk dicatat sebagai satu transaksi sebesar totalnya, seperti mencatat biasa.

## Amplop Disarankan dari Catatanmu

Jatahku belajar dari amplop yang kamu pilih untuk tiap barang. Misalnya kamu pernah mencatat SABUN MANDI ke amplop Rumah Tangga. Lain kali, sabun di struk berikutnya bisa langsung diarahkan ke amplop yang sama dan diberi label **disarankan**. Ringkasannya juga menyebut berapa barang yang amplopnya disarankan dari catatanmu sebelumnya.

Saran hanya mengisi barang yang amplopnya belum kamu pilih. Pilihanmu sendiri tidak pernah ditimpa. Makin sering kamu mencatat per barang, makin banyak barang yang amplopnya terisi otomatis.

## Kalau Dana Amplop Kurang

Kalau sisa dana sebuah amplop tidak cukup, atau limit hariannya terlewati, sebagian barang di amplop itu bisa gagal disimpan. Barang lainnya tetap tercatat. Di ringkasan muncul pilihan untuk amplop yang gagal:

- **Geser**: tambah dana dari amplop lain atau dari pemasukan.
- **Naikkan limit**: naikkan limit harian amplop itu sampai tengah malam. Besok limitnya kembali normal.
- Pindahkan barang-barang itu ke amplop lain lewat pilihan amplop di ringkasan.

Pilihan itu berlaku untuk semua barang yang gagal di amplop tersebut. Setelah itu ketuk **Simpan Semua** lagi. Barang yang sudah tersimpan tidak dikirim ulang. Kalau tidak ingin melanjutkan, ketuk **Lewati yang gagal**.

## Kalau Koneksi Putus Saat Menyimpan

Kadang sinyal hilang tepat saat kamu menekan Simpan, sehingga tidak jelas apakah transaksinya sudah tercatat. Dalam kasus itu Jatahku menampilkan "Hasil simpan belum pasti" dan mengunci isiannya. Tekan **Simpan Semua** lagi setelah sinyal kembali. Transaksi yang sudah tercatat tidak akan tercatat dua kali.

Perlindungan ini berlaku untuk semua pencatatan lewat form Catat pengeluaran, termasuk transaksi dari antrean offline, tidak hanya struk.

## Lewat Bot Telegram atau Chat Jatahku

Kirim foto struk ke [@JatahkuBot](https://t.me/JatahkuBot), atau ketuk **Struk** di Chat Jatahku di webapp. Keduanya bekerja sama: bot membalas dengan nama toko, tanggal, total, dan ringkasan rincian barang, lalu menanyakan amplopnya. Amplop yang disarankan muncul paling atas dengan tanda ⭐.

Lewat chat, satu struk dicatat sebagai **satu transaksi** sebesar totalnya, dengan tanggal struk. Untuk memecah struk per barang atau memperbaiki rinciannya, pakai tombol **+** → **Pengeluaran** → **Struk** di webapp.

Kalau total yang terbaca salah, ketuk **✏️ Nominal salah**, lalu ketik pengeluarannya seperti biasa, misalnya `indomaret 64900`. Catatan yang kamu ketik ulang ini memakai tanggal hari ini. Kalau dana amplop kurang atau limit harian terlewati, bot menawarkan geser dana atau naikkan limit, dan transaksinya tetap memakai tanggal struk.

## Tips Memfoto Struk

- Foto tegak lurus dari atas, dengan cahaya cukup dan tanpa bayangan tangan atau HP.
- Pastikan seluruh struk masuk ke foto, dari nama toko sampai baris total dan pembayaran.
- Satu foto untuk satu struk.
- Struk yang kusut umumnya masih terbaca. Struk yang tintanya sudah pudar lebih sulit dibaca.

Kalau totalnya tidak terbaca sama sekali, Jatahku memberi tahu dan kamu bisa mengisi nominalnya sendiri. Scan yang gagal seperti ini tidak dihitung dalam kuota.

## Kuota

- **Pro**: scan struk dan transaksi tanpa batas.
- **Basic**: 15 scan per bulan, dihitung bersama untuk form Pengeluaran, Chat Jatahku, dan Telegram. Sisa kuota scan bulan ini ditampilkan setiap selesai scan.

Di paket Basic, struk yang dicatat per barang juga memakai kuota 50 transaksi per bulan: **tiap barang dihitung sebagai satu transaksi**, bukan satu struk. Struk berisi 8 barang memakai 8 transaksi. Struk yang dicatat lewat chat atau Telegram dihitung satu transaksi, karena memang dicatat sebagai satu transaksi.

Kuota dicek sekali saat struk mulai disimpan. Kalau kuota masih ada, struk itu selalu disimpan utuh walaupun jumlah transaksinya melewati 50, termasuk saat kamu menyimpan ulang barang yang sempat gagal. Sesudahnya Jatahku memberi tahu bahwa kuota sudah habis dan pencatatan berikutnya bisa lagi mulai tanggal 1 bulan depan.

## Tanya Jawab

**Apakah foto strukku disimpan?**

Tidak. Foto dibaca oleh mesin pembaca teks (OCR) di server Jatahku dan tidak disimpan. Teks lengkap hasil bacaannya disimpan sementara untuk mencocokkan koreksimu, lalu dihapus setelah kamu menyimpan atau membatalkan struk. Kalau scan tidak diselesaikan, misalnya form-nya ditutup, teks itu dihapus otomatis sekitar 24 jam kemudian.

Yang tetap disimpan hanya ringkasan scan, yaitu nama toko, total, dan tanggal, untuk menghitung kuota dan memantau akurasi scan.

**Kalau aku mengoreksi total atau nama toko, apa gunanya?**

Koreksi membantu Jatahku membaca struk dari toko yang sama dengan lebih tepat. Koreksi baru dipakai untuk semua pengguna setelah koreksi yang sama datang dari beberapa orang berbeda. Koreksi total juga harus cocok dengan pembayaran yang tertulis di struk. Jadi satu koreksi yang keliru tidak mengubah hasil scan orang lain.

**Struk dari toko mana saja yang bisa dibaca?**

Jatahku membaca struk belanja cetak, terutama yang mencantumkan baris total dan pembayaran. Kami mengujinya dengan struk minimarket asli yang kusut, berbayang, dan agak buram. Kalau struk dari toko tertentu sering salah terbaca, kabari kami supaya bisa diperbaiki.

Ada masukan soal scan struk? Kirim ke [hi@jatahku.com](mailto:hi@jatahku.com).
