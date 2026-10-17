---
title: "AI Advisor Baru: Analisa dan Tombol Aksi di Setiap Halaman Jatahku"
description: "AI Advisor sekarang ada di kartu KPI, amplop, transaksi, alokasi, langganan, chat web, dan Telegram, dengan angka yang sama di semua tempat. Tiap analisa menjawab artinya apa dan lakukan apa, lengkap dengan tombolnya."
pubDate: 2026-10-17
category: update-fitur
author: Tim Jatahku
cover: /covers/ai-advisor-setiap-halaman.svg
featured: true
---

AI Advisor versi pertama hanya punya satu kartu di Dashboard. Isinya berguna, tapi setelah membaca "budget berisiko jebol", kamu masih harus mencari sendiri harus berbuat apa.

Versi baru mengubah dua hal:

1. **AI Advisor ada di setiap bagian Jatahku**, bukan hanya satu kartu.
2. **Setiap analisa punya tombol aksi.** Ada masalah, ada langkahnya, dan langkah itu bisa dijalankan dengan satu ketukan.

## Tiap Angka Menjawab Dua Hal

Prinsipnya sederhana: setiap angka menjawab **artinya apa** dan **lakukan apa**. Analisa yang tidak punya langkah tidak ditampilkan, kecuali kabar baik bahwa kondisimu aman.

Contoh dari satu Beranda di pertengahan periode:

> 🔴 **Lunasi KPR**: telat 9 hari, dan amplop Tagihan & Cicilan sudah minus. Perlu Rp2.008.174.
> **[Geser & bayar]**

Ketuk tombolnya, dan Jatahku menyiapkan rencana: ambil Rp453.000 dari Pakaian, Rp1.410.000 dari Pendidikan, dan Rp145.174 dari Kebutuhan Rumah, lalu bayar KPR. Kamu bisa melepas sumber yang tidak mau dipakai. Setelah itu cukup satu ketukan untuk konfirmasi, dan dana digeser sekaligus tagihannya dibayar.

**Uang tidak pernah pindah tanpa konfirmasimu.**

## Di Mana Saja?

### Beranda: chip di enam kartu KPI

Di pojok kanan atas setiap kartu KPI ada chip kecil bertanda ✦:

| Kartu | Contoh chip |
|---|---|
| Jatah hari ini | "1,8× jatah" |
| Sisa bebas | "Habis ±24 Okt" atau "Cukup s/d 26 Okt" |
| Terpakai periode ini | "Lewat ±Rp525 rb" |
| Income periode ini | "Terisi dari Rina" atau "Belum masuk" |
| Tagihan belum dibayar | "KPR telat 9 hari" |
| Tabungan | "Darurat baru 3%" |

Ketuk chip untuk membuka analisanya: judul, satu atau dua kalimat, angka kuncinya, dan tombol aksi.

Kalau ada masalah serius di Beranda, chip yang hanya berisi informasi tampil lebih redup supaya perhatianmu tidak terpecah.

### Beranda: kartu AI Advisor

Kartu ini menampilkan **tiga langkah paling berdampak untuk sisa periode ini**. Urutannya dari yang paling mendesak, lalu dari yang paling besar pengaruhnya. Saran lainnya ada di "+N saran lain".

Tiap item punya **Rincian** (cara hitungnya), tombol aksi, dan **Nanti** untuk menyembunyikannya sementara.

Di bawahnya ada kotak **Tanya AI Advisor** dengan pertanyaan cepat seperti "Kenapa boros?" atau "Kapan habis?".

### Halaman Amplop

Setiap kartu amplop punya strip analisa sendiri, misalnya:

- "Makan & Jajan: maksimal Rp133 rb/hari"
- "Geser ±Rp391 rb ke Transport"
- "Aman, ±Rp45 rb/hari tersedia"

Tombolnya ikut menyesuaikan: **Geser dana**, **Bayar**, **Naikkan jatah**, atau **Setor** untuk amplop tabungan.

Di form amplop tabungan juga ada pilihan **Dana darurat**, supaya AI Advisor tahu amplop mana yang dipakai untuk menghitung kecukupan dana daruratmu.

### Halaman Transaksi

AI Advisor menandai baris yang perlu dicek:

- **Kemungkinan dobel**, termasuk struk yang terkirim dua kali. Pilihannya: hapus salah satu, atau tandai "Bukan dobel".
- **Pengeluaran besar satu kali.** Tidak dihitung sebagai kebiasaan harian, jadi batas aman harianmu tidak ikut kacau.
- **Pola rutin** yang belum didaftarkan sebagai langganan. Pilihannya: **Jadikan langganan**.
- **Nominal yang sama dengan tagihan belum dibayar.** Pilihannya: **Tandai lunas**.

### Halaman Alokasi

Rekomendasi alokasi sekarang menyebut **alasannya per amplop**, misalnya "Transport ditambal 7× periode ini", lengkap dengan tingkat keyakinannya. Tombol **Bagi otomatis** di form pemasukan memakai rekomendasi yang sama.

### Halaman Langganan

Ada ringkasan beban tagihan, serta tanda telat atau jatuh tempo di setiap baris. Tombolnya **Geser & bayar**, **Bayar**, atau **Tandai lunas**, untuk tagihan yang sudah kamu bayar di luar Jatahku.

### Chat web dan Telegram

Tanya "kapan habis?", "kenapa boros?", "kenapa makan habis?", atau "aman beli sepatu 450rb?". Jawabannya memakai **angka yang persis sama** dengan Beranda.

## Satu Sumber Angka

Dulu "aman per hari" bisa berbeda antara Dashboard, bot, dan ringkasan harian, karena tiap bagian menghitung dengan caranya sendiri. Sekarang semua angka periode dihitung di satu tempat. Kartu KPI, grafik, kartu amplop, chat web, dan Telegram membaca dari sumber yang sama.

Ada juga beberapa hitungan yang lebih tepat:

- **Jatah hari ini dibandingkan dengan jatah sejak pagi.** Jatah ini tidak ikut turun setiap kali kamu belanja. Contoh: belanja Rp297.100 dari jatah Rp165.100, berarti lewat Rp132.000.
- **Terpakai dihitung dari dana belanja.** Amplop tabungan tidak ikut, jadi persentasenya lebih jujur.
- **Tagihan tidak dianggap belanja harian.** Proyeksi akhir periode = terpakai + tagihan belum dibayar + rata-rata 7 hari terakhir × sisa hari.
- **Pemasukan rumah tangga ikut dihitung.** Kalau pasanganmu yang mencatat gaji, Jatahku tidak lagi bilang "Belum dicatat".

## Jujur Soal Dasar Hitungan

Setiap analisa menyebut dasarnya, misalnya "dari 19 hari data", beserta tingkat keyakinannya. Cara hitungnya bisa dibuka lewat **Rincian**.

Di awal periode, saat datanya belum cukup, AI Advisor tidak berpura-pura tahu. Proyeksi baru muncul mulai hari ke-3.

## Tanpa Model Bahasa Pihak Ketiga

Meski namanya AI Advisor, analisanya tidak dikirim ke layanan AI luar. Semuanya dihitung dengan aturan tetap di server Jatahku. Ini menyangkut keuangan pribadi, jadi datamu tetap di tempatnya.

Privasi rumah tangga juga dijaga:

- Analisa hanya memakai amplop yang boleh kamu lihat.
- Rencana geser dana tidak pernah mengambil dari amplop pribadi anggota lain.
- Deskripsi transaksi pribadi anggota lain tidak pernah dikutip.

## Bisa Dibungkam

Tidak setuju dengan sebuah saran? Ketuk **Nanti** atau **Sembunyikan**, dan saran itu tidak muncul lagi untuk sementara.

AI Advisor adalah cermin, bukan penjaga gerbang. Ia tidak pernah memblokir pencatatan.

---

AI Advisor tersedia untuk **semua paket**, Basic maupun Pro. Punya masukan, atau ada saran yang terasa tidak relevan? Kirim ke [hi@jatahku.com](mailto:hi@jatahku.com).
