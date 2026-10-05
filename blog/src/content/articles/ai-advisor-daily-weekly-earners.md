---
title: "AI Advisor Jatahku Kini Memahami Buruh Harian & Mingguan"
description: "AI Advisor sekarang hitung 'sisa aman' berdasarkan tipe pendapatan: harian, mingguan, atau bulanan. Ojek driver dan pedagang harian akhirnya punya panduan belanja yang realistis, bukan asumsi gajian bulanan."
pubDate: 2026-10-05
category: update-fitur
author: Tim Jatahku
cover: /covers/ai-advisor-daily-weekly.svg
featured: true
---

Sebelumnya, **AI Advisor Jatahku asumsi semua user dapat gaji setiap akhir bulan**. Hasilnya, advice yang diberikan tidak akurat untuk ojek driver, pedagang harian, atau freelancer yang pendapatannya tidak pasti.

Sekarang semuanya berubah. AI Advisor memahami **tiga tipe pendapatan**: harian, mingguan, dan bulanan — dan memberikan saran belanja yang sesuai dengan ritme pendapatanmu.

---

## Masalah: Batas Aman yang Salah untuk Buruh Harian

Bayangkan Rudi, ojek driver. Income harian sekitar Rp150.000, tapi tidak setiap hari dapat pasangan. Rudi punya Rp1.500.000 di amplop Makan.

**Dengan logika lama (bulanan):**
- Jatah harian = Rp1.500.000 ÷ 30 hari = **Rp50.000/hari**

Tapi kalau Rudi macet seminggu — tidak ada income — uang itu akan habis sebelum gajian. Jatah Rp50.000 terasa aman, padahal tidak.

**Dengan logika baru (harian):**
- Rudi set income type sebagai "Harian"
- AI Advisor hitung safe daily berdasarkan **hari sampai income berikutnya**, bukan sampai akhir bulan
- Jatah berubah real-time: hari pertama setelah dapat income = jatah besar, semakin dekat ke hari berikutnya tanpa income = jatah mengecil
- Rudi selalu tahu: "Hari ini batas aman berapa agar tidak kurang saat menunggu income esok hari?"

---

## Tiga Tipe Pendapatan, Tiga Cara Hitung

### 🛵 Harian (Daily Earner)

Untuk pengguna dengan income tidak pasti setiap hari.

**Contoh:** Ojek driver, tukang ojek, pedagang kaki lima, pekerja harian.

**Cara kerja:**
- Dashboard menampilkan "**Batas aman hari ini sampai income berikutnya**"
- Setiap envelope juga punya saran daily limit yang disesuaikan dengan **hari sampai income terdekat** — bukan 30 hari
- Amplop dengan sinking fund (servis motor, asuransi) berubah batas amannya kalau ada deadline — lebih ketat sampai deadline tercapai

**Contoh real:** Rudi dapat Rp200.000 hari ini. Besok mungkin dapat Rp150.000, lusa nggak dapat. AI Advisor tahu: "Ada 3 hari sebelum kamu mungkin dapat income lagi, jadi hari ini batas aman Rp20.000, besok Rp25.000, lusa Rp30.000."

### 📅 Mingguan (Weekly Earner)

Untuk pengguna yang pendapatannya paling stabil dalam seminggu.

**Contoh:** Karyawan paruh waktu yang digaji mingguan, pedagang yang rutin dapat income setiap hari Jumat.

**Cara kerja:**
- Batas aman dihitung dari **hari sampai payday mingguan berikutnya** — bukan sampai akhir bulan
- Setiap amplop disesuaikan dengan siklus 7 hari

**Contoh real:** Siti pedagang mingguan. Setiap Jumat dapat Rp600.000. Pada hari Sabtu batas amannya paling besar, semakin dekat ke Jumat berikutnya jatah mengecil.

### 💼 Bulanan (Monthly Earner) & Tidak Tentu (Irregular)

Tetap sama seperti sebelumnya:
- Bulanan: batas aman dihitung dari hari ini sampai akhir periode budget
- Tidak Tentu: logika mirip bulanan, tapi kasih warning lebih sering

---

## Di Mana Perubahan Ini Terasa?

### 1. Dashboard Hero Advisor

Baris pertama berubah jadi:

**🛵 Harian:** "Rp80.000/hari sampai income berikutnya (dalam 3 hari)"

**📅 Mingguan:** "Rp90.000/hari sampai payday Jumat"

**💼 Bulanan:** "Rp50.000/hari sampai akhir bulan" (tetap sama)

### 2. Saran per Amplop

Di halaman Amplop atau kartu AI Advisor, saran limit juga berubah:

**🛵 Harian — Makan di Jalan:**
> ⚠️ Makan sudah pakai 60%. Sampai income berikutnya (2 hari), batas aman **Rp8.000/hari**.

**📅 Mingguan — Transportasi:**
> ✅ Transportasi on track. Sampai payday minggu depan, batas aman **Rp15.000/hari**.

### 3. Amplop dengan Sinking Fund

Sinkking fund (dana persiapan tahunan) punya special handling:

**Kalau deadline masuk periode ini:**
> ⚠️ Pajak tahunan jatuh tempo 20 hari lagi. Harus sisih **Rp20.000/hari** agar tidak ketinggalan.

**Kalau deadline jauh:**
> ✅ Servis motor on track. Target tercapai sebelum deadline bulan depan.

---

## Cara Set Income Type

### Di Onboarding (User Baru)

Saat pertama kali sign up, Jatahku akan tanya: **"Kamu dapat income gimana?"**

- 🛵 Harian (tidak pasti setiap hari)
- 📅 Mingguan (stabil per minggu)
- 💼 Bulanan (dapat gaji setiap bulan)
- ❓ Tidak tentu (irregular)

Jawab sekali — selesai. Dashboard langsung menyesuaikan.

### Di Settings (User Existing)

Buka **Settings** → **Jenis Pendapatan** → pilih tipe baru.

Saat berganti income type, semua saran AI Advisor akan recalculate otomatis.

---

## Privacy & Household

Kalau pakai fitur **Household** (berbagi budget dengan pasangan):

- Setiap anggota tetap punya income type sendiri
- Dashboard setiap orang menampilkan batas aman berdasarkan income type mereka — tidak tercampur
- Amplop shared tetap shared, tapi saran limit dikalibrasi per person

Contoh: Suami income bulanan, istri harian. Mereka share amplop "Belanja Bulanan". Istri lihat batas aman per hari sampai income berikutnya, suami lihat batas aman per hari sampai akhir bulan.

---

## Hasil yang Diharapkan

Dengan AI Advisor yang paham tipe pendapatan:

✅ **Ojek driver** tidak lagi panik di hari ketiga tanpa income — sudah tahu jatah aman berapa

✅ **Pedagang harian** bisa manage amplop sinking fund (asuransi, servis) tanpa stress — sistem sudah hitung ketat sampai deadline

✅ **User mingguan** akhirnya punya saran yang cocok dengan ritme mereka — bukan misguided monthly average

✅ **Tidak perlu setup manual** — cukup jawab satu pertanyaan saat onboarding, semuanya auto-adjust

---

Teknologi envelope budgeting baru bekerja sesuai cara uang benar-benar bergerak di tangan pengguna. Bukan asumsi ideal — tapi kenyataan.

Ada pertanyaan atau masukan? Hubungi [hi@jatahku.com](mailto:hi@jatahku.com).
