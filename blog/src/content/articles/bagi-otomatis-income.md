---
title: "Bagi Otomatis: Pembagi Pendapatan Pintar yang Proporsional"
description: "Bagi Otomatis membagi income sesuai target setiap amplop, bukan sembarangan. Sisa yang tidak terpakai otomatis masuk Tabungan — dan semua nominal dibulatkan ke Rp100 agar realistis."
pubDate: 2026-10-05
category: update-fitur
author: Tim Jatahku
cover: /covers/fitur-cooling-period.svg
featured: false
---

Sebelumnya, saat masukkan income, Jatahku tidak punya saran pintar untuk bagi-bagi. User harus manual hitung: "Rp200.000 ini mau ke Makan berapa, Transportasi berapa, Tabungan berapa."

Kalau income kecil (hari ini dapat Rp150.000), user sering bingung: "Kalau setiap amplop dapat sedikit, ngapain diinput? Mending masukkan semua ke satu amplop aja." Hasilnya, tidak semua amplop ter-alokasi dengan fair.

Sekarang ada **Bagi Otomatis** — fitur yang bagi income secara **proporsional** ke semua amplop berdasarkan target bulanan atau minimum amount masing-masing.

---

## Masalah: Pembagian Manual itu Stress

Saat tambah income, dialog yang sering terjadi:

> **User:** "Hari ini dapat Rp200.000. Mau bagi ke mana aja?"
>
> **Jatahku dulu:** Kosong. User harus pikir sendiri.
>
> Hasilnya: User sering memilih yang simple — masukkan semua ke satu amplop, skip yang lain.

Atau:

> **User:** "Rp1.200.000 dapat dari gaji. Lalu bagi gimana?"
>
> **Jatahku dulu:** User harus ambil kalkulator, hitung persen setiap amplop, terus ketik satu-satu.

Ini cukup ribet apalagi kalau ada 10-15 amplop.

---

## Solusi: Bagi Otomatis yang Cerdas

Sekarang, saat klik **Bagi Otomatis**, sistem melakukan:

### 1. Hitung Target / Minimum Setiap Amplop

Sistem baca **target bulanan** atau **minimum amount** dari setiap amplop:

- **Makan:** Target Rp1.500.000/bulan
- **Transportasi:** Target Rp400.000/bulan
- **Bensin:** Target Rp700.000/bulan
- **Sinking Fund (Servis):** Minimum Rp50.000 setiap bulan
- **Tabungan:** Target Rp500.000/bulan

### 2. Bagi Proporsional ke Setiap Amplop

Kalau income hari ini Rp800.000:

**Total kebutuhan:** Rp1.500 + Rp400 + Rp700 + Rp50 + Rp500 = Rp3.150.000

**Skala alokasi:** Rp800.000 ÷ Rp3.150.000 = 0,25 (25% dari target)

**Hasil alokasi:**
- Makan: Rp1.500.000 × 0,25 = **Rp375.000**
- Transportasi: Rp400.000 × 0,25 = **Rp100.000**
- Bensin: Rp700.000 × 0,25 = **Rp175.000**
- Sinking Fund: Rp50.000 × 0,25 = **Rp12.500**
- Tabungan: Rp500.000 × 0,25 = **Rp125.000**

**Total:** Rp787.500

**Sisa:** Rp800.000 − Rp787.500 = **Rp12.500** → otomatis masuk **Tabungan**

### 3. Pembulatan ke Rp100

Semua nominal dibulatkan **ke bawah** ke kelipatan Rp100:

- Rp375.000 → Rp375.000 ✓
- Rp100.000 → Rp100.000 ✓
- Rp175.000 → Rp175.000 ✓
- Rp12.500 → Rp12.500 ✓ (tapi kalau Rp12.768, jadi Rp12.700)
- Rp125.000 → Rp125.000 ✓

Alasan pembulatan ke bawah: jadi **total alokasi tidak pernah melebihi income** — tidak ada "hutang" ke depan.

---

## Cara Pakai Bagi Otomatis

### Saat Tambah Income di Dashboard / Bot

1. **Ketik jumlah income** (atau kirim bot: "dapat 800k")
2. **Klik tombol "Bagi Otomatis"** (atau pilih di menu)
3. **Tinjau hasil alokasi** — semua amplop mendapat bagian proporsional
4. Kalau suka, **Simpan**. Kalau tidak, manual aja dan edit satu per satu.

### Jangan Paksakan Bagi Otomatis untuk...

❌ **Amplop yang tidak punya target/minimum:** Sistem perlu info untuk bisa bagi fair. Kalau amplop blank target-nya, sistem skip amplop itu (atau tanya user).

❌ **Amplop personal / locked:** Kalau ada amplop yang di-lock (tidak boleh di-allocate), sistem otomatis skip.

---

## Update Manual Alokasi Masih Bisa

Kalau Bagi Otomatis hasilnya tidak 100% sesuai, user tetap bisa:

1. **Edit persen** → "Makan jadi 30%, Transportasi 15%"
2. **Edit jumlah langsung** → "Makan 400k, Transportasi 100k"
3. **Ubah keduanya** → Persen dan jumlah saling update

Semua perubahan tetap dibulatkan ke Rp100.

---

## Contoh Real: Rudi Ojek Driver

Rudi dapat income tidak pasti. Hari ini dapat Rp250.000, hari lain Rp100.000 — tergantung order.

**Setup amplop Rudi:**
- Bensin & Operasional: Target Rp400.000/bulan
- Makan di Jalan: Target Rp200.000/bulan
- Servis Motor: Minimum Rp50.000/bulan
- Kebutuhan Rumah: Target Rp500.000/bulan
- Tabungan: Target Rp100.000/bulan

**Saat Rudi dapat Rp250.000 pagi hari:**

Rudi buka Jatahku, ketik "dapat 250k", klik **Bagi Otomatis**.

Sistem bagi proporsi:
- Bensin: Rp80.000
- Makan: Rp32.000
- Servis: Rp10.000
- Rumah: Rp100.000
- Tabungan: Rp20.000
- Sisa: Rp8.000 → Tabungan

**Total:** Rp250.000

Rudi tinggal klik Simpan — selesai. Semua amplop dapat alokasi fair, tidak ada yang kelewat.

---

## Perbedaan: Bagi Otomatis vs Manual

| Aspek | Bagi Otomatis | Manual |
|-------|---------------|--------|
| **Waktu** | 5 detik | 2-3 menit hitung + ketik |
| **Fair** | Proporsional ke target | Sesuai mood / memory user |
| **Akurat** | Otomatis hitung | Rentan salah hitung |
| **Fleksibel** | Bisa diubah setelah | Bisa, tapi ribet |

---

Fitur Bagi Otomatis dirancang untuk **menghilangkan beban mental** saat alokasi income. Terutama buat daily dan weekly earners yang pendapatannya tidak pasti — setiap income bisa langsung dibagi fair tanpa perlu mikir.

Ada feedback atau saran pakai Bagi Otomatis? Kirim ke [hi@jatahku.com](mailto:hi@jatahku.com).
