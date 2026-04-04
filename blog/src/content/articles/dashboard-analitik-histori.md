---
title: "Dashboard Jatahku Kini Punya Histori, Perbandingan Bulan, dan Pola Mingguan"
description: "Update besar dashboard: navigasi ke periode sebelumnya, grafik perbandingan antarbulan, insight otomatis, dan chart pola hari paling boros dalam seminggu."
pubDate: 2026-04-04
category: update-fitur
author: Tim Jatahku
cover: /covers/dashboard-analitik-histori.svg
featured: true
---

Selama ini dashboard Jatahku hanya menampilkan satu hal: periode berjalan. Kamu bisa lihat sisa budget hari ini, tapi tidak ada cara untuk tahu bulan lalu kamu belanja berapa, atau apakah pengeluaranmu bulan ini lebih boros dari biasanya.

Update kali ini mengubah itu semua. Dashboard sekarang bisa menampilkan data bulan-bulan sebelumnya, membandingkannya secara visual, memberikan insight otomatis, dan menunjukkan pola harianmu dalam seminggu — semuanya tanpa meninggalkan halaman utama.

---

## 1. Navigasi Periode — Lihat Bulan Sebelumnya

Di bagian atas dashboard, tepat di bawah nama kamu, sekarang ada navigator kecil:

```
← 28 Feb – 27 Mar    28 Mar – 27 Apr 2026  [Sekarang]  →
```

Klik **←** untuk mundur ke periode sebelumnya. Semua data di bawahnya — KPI cards, grafik pengeluaran harian, breakdown amplop, hingga daftar transaksi — ikut berubah mengikuti periode yang kamu pilih.

Klik **→** untuk maju. Tombol ini otomatis nonaktif saat kamu sudah berada di periode berjalan.

Badge **Sekarang** muncul saat kamu sedang melihat periode aktif, jadi kamu tidak akan kebingungan sedang melihat data bulan apa.

Beberapa hal yang perlu diketahui tentang tampilan histori:

- **KPI cards** (Dana dialokasi, Terpakai, Sisa, Amplop aktif) menampilkan angka sesuai periode yang dipilih
- **Grafik pengeluaran harian** menampilkan seluruh hari dalam periode tersebut — semua bar berwarna solid karena tidak ada hari "masa depan"
- **Breakdown amplop** menampilkan distribusi pengeluaran di periode tersebut
- **Decision Box** (peringatan & kabar baik) hanya muncul di periode berjalan — tidak relevan untuk histori
- **Daftar transaksi** di bawah menampilkan transaksi dalam periode yang dipilih, bukan 10 transaksi terbaru secara global

---

## 2. Perbandingan Periode — Tren 6 Bulan Sekaligus

Di bawah Decision Box, ada section baru yang selalu tampil: **Perbandingan Periode**.

Section ini menampilkan bar chart yang membandingkan pengeluaran dan alokasi dari periode-periode sebelumnya secara berurutan. Batang hijau muda = dana yang dialokasikan, batang hijau tua = yang terpakai. Semakin dekat tinggi kedua batang, semakin mendekati batas budget.

Di bawah chart, ada tabel ringkas yang menampilkan:
- Label periode (misal: 28 Feb – 27 Mar)
- Total terpakai vs dialokasi
- Persentase pemakaian, dengan warna merah jika > 90%, kuning jika > 70%, hijau jika aman

Section ini tidak ikut navigator periode — ia selalu menampilkan 6 periode terakhir yang punya data, sehingga kamu bisa melihat gambaran besar tanpa harus bolak-balik navigasi.

---

## 3. Auto-Insight — Satu Kalimat yang Langsung Informatif

Di bagian atas grafik perbandingan, Jatahku sekarang menampilkan 1–2 insight otomatis berdasarkan data kamu:

**Insight tren pengeluaran:**
> 📊 Pengeluaran turun 12% dibanding periode lalu

atau

> 📊 Pengeluaran naik 21% dibanding periode lalu

atau

> 📊 Pengeluaran stabil dibanding periode lalu

Insight ini dihitung dari perbandingan total pengeluaran dua periode terakhir yang ada datanya. Jika selisihnya kurang dari 5%, dianggap stabil.

**Insight kategori terbesar:**
> 🍽️ Terbanyak: Makan Keluarga (34% dari total)

Ini diambil dari breakdown amplop periode berjalan — amplop dengan pengeluaran terbesar ditampilkan beserta persentasenya dari total pengeluaran.

Kedua insight ini dihitung langsung di frontend dari data yang sudah dimuat, jadi tidak ada loading tambahan.

---

## 4. Pola Mingguan — Hari Apa Kamu Paling Boros?

Section baru di bawah Perbandingan Periode: **Pola Mingguan**.

Grafik ini menampilkan rata-rata pengeluaran per hari dalam seminggu — Senin sampai Minggu — berdasarkan data 3 periode terakhir (sekitar 90 hari). Cara membacanya:

- Setiap bar mewakili satu hari
- Tinggi bar = rata-rata pengeluaran di hari tersebut
- Bar tertinggi di-highlight dengan **warna amber** — itu adalah hari paling boros
- Di pojok kanan atas tercantum label: "Paling boros: [nama hari]"

Contoh insight yang bisa kamu dapatkan dari grafik ini:
- Jumat selalu tinggi? Kemungkinan karena kebiasaan makan siang di luar atau belanja weekend
- Senin rendah? Mungkin karena kamu masih memasak dari bahan belanja minggu lalu
- Sabtu–Minggu konsisten tinggi? Bisa jadi sinyal untuk menyiapkan budget khusus akhir pekan

Rata-rata dihitung per kejadian hari itu dalam periode, bukan per transaksi. Artinya jika dalam 3 bulan ada 13 hari Jumat, total pengeluaran Jumat dibagi 13 — bukan dibagi jumlah transaksi.

---

## 5. Riwayat Transaksi per Periode

Halaman **Transaksi** juga mendapat update yang sama: sekarang ada navigator periode di bagian atas, tepat di bawah judul halaman.

Secara default, halaman transaksi menampilkan semua transaksi dalam **periode berjalan** (bukan 50 terbaru dari semua waktu). Ini lebih intuitif karena selaras dengan cara kerja envelope budgeting — kamu melihat pengeluaran dalam konteks satu periode, bukan scroll tanpa batas.

Navigasi ← → bekerja sama seperti di dashboard. Filter amplop dan filter sumber (Telegram / WebApp) tetap berfungsi di atas periode yang dipilih.

---

## Catatan untuk Pengguna Baru

Jika kamu baru mulai menggunakan Jatahku bulan ini, wajar jika:

- **Perbandingan Periode** belum menampilkan apa-apa — section ini otomatis tersembunyi jika belum ada data historis
- **Pola Mingguan** belum tampil jika belum ada transaksi sama sekali
- **Auto-insight** tidak muncul jika baru ada 1 periode dengan data

Semuanya akan terisi seiring kamu mencatat pengeluaran lebih rutin.

---

## Cara Mendapat Update Ini

Semua perubahan sudah live dan tidak memerlukan update manual. Jika kamu menggunakan Jatahku di browser, cukup refresh halaman. Jika sudah install sebagai PWA di home screen, buka dan tunggu sebentar sampai versi terbaru dimuat.

Ada pertanyaan atau saran? Sampaikan melalui [jatahku.com](https://jatahku.com).
