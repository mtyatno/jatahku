---
title: "Bagi Otomatis: Income Dibagi ke Amplop Sesuai Kebutuhannya"
description: "Tombol Bagi otomatis membagi income ke semua amplop sebanding dengan kebutuhan bulanan masing-masing. Nominalnya dibulatkan ke Rp100 dan sisanya masuk Tabungan."
pubDate: 2026-10-05
category: update-fitur
author: Tim Jatahku
cover: /covers/bagi-otomatis.svg
featured: false
---

Setiap kali ada pemasukan, pertanyaannya sama: uang ini dibagi ke amplop mana saja, dan berapa?

Kalau pemasukannya kecil, misalnya hasil narik hari ini, godaannya adalah memasukkan semuanya ke satu amplop saja. Akibatnya amplop lain kosong terus. Tombol **Bagi otomatis** mengerjakan hitungannya untuk kamu.

## Di Mana Tombolnya?

1. Ketuk tombol **+** di pojok kanan bawah, lalu pilih **Income**.
2. Di jendela **Income baru**, isi **Jumlah (Rp)** dan **Keterangan**, misalnya "Gaji" atau "Pendapatan harian".
3. Ketuk **Bagi otomatis**. Setiap amplop langsung terisi persen dan nominalnya.
4. Periksa hasilnya, ubah kalau perlu, lalu ketuk **Simpan Income**.

## Cara Membaginya

**1. Hitung kebutuhan bulanan tiap amplop.** Jatahku mengambil angka terbesar dari tiga hal: budget target amplop, median belanja bulanan amplop itu di periode-periode sebelumnya, dan uang yang wajib disisihkan (misalnya tagihan langganan atau minus dari periode lalu).

**2. Bagi sebanding.** Kalau income lebih kecil dari total kebutuhan, setiap amplop mendapat porsi yang sama besar dari kebutuhannya. Rumusnya: kebutuhan amplop × (income ÷ total kebutuhan). Kalau income lebih besar dari total kebutuhan, setiap amplop mendapat kebutuhannya penuh.

**3. Bulatkan ke bawah ke kelipatan Rp100.** Rp100 adalah pecahan rupiah terkecil yang masih dipakai, jadi tidak ada nominal seperti Rp17.352. Karena dibulatkan ke bawah, totalnya tidak pernah melebihi income.

**4. Sisa masuk Tabungan.** Selisih karena pembulatan, atau kelebihan income di atas total kebutuhan, ditampilkan sebagai "💰 … → Tabungan" dan masuk ke amplop Tabungan saat disimpan.

Amplop berjenis **Target menabung** dan amplop yang dikunci tidak ikut dibagi otomatis. Kamu tetap bisa mengisinya secara manual.

## Contoh: Pendapatan Harian Rp150.000

Misalkan seorang driver ojol memakai template Driver & Kurir, dan kebutuhan bulanan amplopnya seperti di tabel. Totalnya Rp3.500.000. Hari ini dia mendapat Rp150.000, jadi setiap amplop mendapat 150.000 ÷ 3.500.000, sekitar 4,3% dari kebutuhannya.

| Amplop | Kebutuhan bulanan | Sebelum dibulatkan | Dapat |
|---|---|---|---|
| ⛽ Bensin & Operasional | Rp1.000.000 | ±Rp42.857 | **Rp42.800** |
| 🍜 Makan di Jalan | Rp800.000 | ±Rp34.285 | **Rp34.200** |
| 📱 Pulsa & Kuota Narik | Rp150.000 | ±Rp6.428 | **Rp6.400** |
| 🔧 Servis & Ganti Oli | Rp250.000 | ±Rp10.714 | **Rp10.700** |
| 🏠 Kebutuhan Rumah | Rp1.300.000 | ±Rp55.714 | **Rp55.700** |

Totalnya Rp149.800. Sisa Rp200 masuk Tabungan. Amplop "💰 Tabungan / Darurat" berjenis Target menabung, jadi tidak ikut dibagi.

Dengan amplop yang sama, gaji Rp5.000.000 akan mengisi setiap amplop sesuai kebutuhannya penuh (total Rp3.500.000), dan Rp1.500.000 sisanya masuk Tabungan.

## Mengubah Hasilnya

- **Ubah persen**: nominal rupiah ikut dihitung ulang dan dibulatkan ke bawah ke Rp100.
- **Ketik nominal rupiah**: angka yang kamu ketik dipakai apa adanya, dan persennya menyesuaikan.
- **Ubah jumlah income**: baris yang diisi dengan persen ikut berubah, sedangkan nominal yang kamu ketik tetap.

Kalau total alokasi melebihi income, baris ringkasan menampilkan **Kelebihan** berwarna merah, disertai pesan "Total alokasi …% dari income, lebih Rp…. Kurangi persen atau jumlah di salah satu amplop supaya bisa disimpan." Tombol Simpan Income baru aktif lagi setelah totalnya pas.

Kalau belum ada satu pun amplop yang punya target, riwayat belanja, atau tagihan, Bagi otomatis belum bisa menghitung dan akan meminta kamu mengisi manual dulu.

Ada masukan soal Bagi otomatis? Kirim ke [hi@jatahku.com](mailto:hi@jatahku.com).
