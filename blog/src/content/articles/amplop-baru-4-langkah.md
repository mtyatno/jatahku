---
title: "Amplop Baru Jadi Mudah: 4 Langkah Terstruktur"
description: "Membuat amplop baru di Jatahku sekarang jadi proses 4-step yang fokus pada satu aspek per langkah, tanpa overwhelming di awal."
pubDate: 2026-10-05
category: tutorial
author: Tim Jatahku
cover: /covers/sinking-fund.svg
featured: false
---

Sebelumnya, saat bikin amplop baru, user dihadapkan dengan **satu form besar berisi 15+ field**:

- Nama amplop
- Emoji
- Budget amount
- Purpose (expense/saving/sinking_fund)
- Target amount (untuk saving)
- Target date
- Classification (needs/wants)
- Minimum monthly reserve
- Is rollover?
- Is personal?
- Daily limit
- Cooling period threshold
- Group

Hasilnya, banyak user bingung dan skip field yang penting. Atau paling parah, tidak jadi bikin amplop sama sekali.

Sekarang **proses membuat amplop dibagi jadi 4 langkah** — setiap langkah fokus pada satu pertanyaan. User tidak overwhelmed, dan semua field penting tersedia tapi tidak terasa mendesak.

---

## 4 Langkah Membuat Amplop Baru

### Langkah 1️⃣: Nama & Emoji

**Pertanyaan:** "Amplop untuk apa?"

Di langkah ini, user pilih:
- **Nama amplop** — contoh: "Makan", "Sewa Rumah", "Tabungan Nikah"
- **Emoji** — sistem suggest beberapa emoji populer (🍜, 🏠, 💰, 🚗, 📱, ✈️, dll)

Saat user ketik nama, sistem juga **auto-suggest purpose** berdasarkan keyword:

> User ketik "Tabungan Nikah"
>
> Sistem suggest: "Ini untuk menabung? Purpose: **Saving**" (bisa di-agree atau ubah di langkah 2)

**Keep it simple:** Cuma 2 input, tidak ada yang ribet.

### Langkah 2️⃣: Tujuan (Purpose)

**Pertanyaan:** "Amplop ini untuk apa tujuannya?"

Tiga pilihan:

**💰 Expense** — Pengeluaran rutin (Makan, Transport, Hiburan)
- Alokasi setiap periode, boleh dipakai sampai habis
- Tidak ada target date atau goal

**🎯 Saving** — Target menabung (Liburan, Nikah, Rumah)
- Harus set target amount dan target date
- Ada progress bar menuju goal
- Sistem warn kalau setoran terlalu kecil

**📅 Sinking Fund** — Dana persiapan tahunan/berkala (Pajak, Asuransi, Servis)
- Harus set deadline dan target amount
- Sistem warn kalau perlu sisih lebih banyak tiap bulan agar tepat waktu
- Otomatis di-reserve sampai due date

**Smart suggestion:** Kalau user pernah buat amplop serupa (contoh: sudah ada "Tabungan Liburan 2026"), sistem kasih opsi: "Pake template tabungan sebelumnya?" untuk copy-paste target amount.

### Langkah 3️⃣: Klasifikasi (Needs vs Wants)

**Pertanyaan:** "Ini kebutuhan atau keinginan?"

Hanya muncul **jika purpose = Expense**.

**Kebutuhan (Needs):**
- Tidak bisa ditunda
- Contoh: Makan, Transport, Listrik, Asuransi
- Sistem prioritas ini saat alokasi atau budget squeeze

**Keinginan (Wants):**
- Bisa dikurangi atau ditunda
- Contoh: Hiburan, Kopi di Kafe, Belanja Baju
- Sistem tahu ini flexible spending — bisa dikurangi kalau cash tight

**Efek apa?**
- Analytics menghitung spending trend per kategori
- Budget alert lebih smart: "Makan naik 20%, perlu cut di Hiburan?"

### Langkah 4️⃣: Pengaturan Lanjutan (Opsional)

**Pertanyaan:** "Ada pengaturan khusus?"

Di sini, user bisa set hal-hal advanced (semua optional):

**📌 Rollover**
- "Kalau bulan ini sisa, boleh di-carry ke bulan depan?"
- Default: YES (kebanyakan amplop suka rollover)
- Contoh: "Amplop Transportasi bulan ini sisa Rp50.000, pindah ke bulan depan"

**🔒 Lock/Personal**
- "Amplop ini personal atau boleh dipakai keluarga?"
- Default: Shared
- Kalau di-lock, tidak bisa di-allocate dalam household

**📊 Daily Limit**
- "Batas belanja harian berapa?"
- Default: Auto-calculate berdasarkan target tahunan
- Contoh: Amplop Makan budget Rp1.500.000/bulan → daily limit default Rp50.000/hari

**❄️ Cooling Period**
- "Setelah belanja, berapa jam baru boleh belanja lagi?"
- Default: OFF (untuk anti-belanja impulsif)
- Contoh: Set 3 jam → setelah belanja Makan, tidak bisa belanja di amplop ini selama 3 jam

**📁 Group**
- "Amplop ini masuk group mana?"
- Default: Tidak ada group
- Contoh: Group "Cicilan", "Sewa", "Tabungan"

**Tooltip untuk setiap setting:** User bisa klik `?` di setiap field untuk penjelasan detail.

---

## Visualisasi: Dari Start ke Finish

```
┌─────────────────────────────────────────┐
│ Langkah 1️⃣: Nama & Emoji                │
│                                          │
│ Amplop: [Makan di Jalan      ]          │
│ Emoji:  [🍜]  🚗 📱 🍕 🏪      │
│                                          │
│ [Lanjut]                                │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│ Langkah 2️⃣: Tujuan                      │
│                                          │
│ 💰 Expense (untuk pengeluaran rutin)    │
│ 🎯 Saving  (untuk menabung)             │
│ 📅 Sinking Fund (untuk persiapan)       │
│                                          │
│ ☑ 💰 Expense                           │
│ [Lanjut]                                │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│ Langkah 3️⃣: Klasifikasi                 │
│                                          │
│ ☑ Kebutuhan (Tidak bisa ditunda)        │
│ ○ Keinginan (Bisa dikurangi)            │
│                                          │
│ [Lanjut]                                │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│ Langkah 4️⃣: Pengaturan Lanjutan         │
│                                          │
│ ☑ Rollover sisa ke bulan depan          │
│ ☐ Personal (private amplop)             │
│ Daily Limit: [Auto] Rp50.000/hari       │
│ Cooling Period: [OFF] atau [2 jam]      │
│ Group: [Tidak ada]                      │
│                                          │
│ [Selesai] atau [Edit Lagi]              │
└─────────────────────────────────────────┘
```

---

## Untuk User Baru vs Experienced

**User Baru:**
- Lebih suka simple — tinggal 4 langkah, step 4 mostly default

**User Experienced:**
- Bisa langsung ke step 4 kalau mau banyak custom
- Semua field advance tersedia tanpa dilewatin dari langkah sebelumnya

Sistem flexible — tidak force user untuk step-by-step kalau tidak perlu.

---

## Contoh: Rudi Buat Amplop "Servis Motor"

**Rudi buka FAB → Amplop Baru**

**Langkah 1:** Ketik "Servis Motor", pilih emoji 🔧 ✓

**Langkah 2:** Sistem suggest "Ini persiapan tahunan kan? Purpose: **Sinking Fund**"
Rudi agree ✓

**Langkah 3:** Skip (tidak applicable karena bukan Expense)

**Langkah 4:** 
- Rollover: ON (default)
- Cooling Period: OFF (default)
- Target amount: Rp500.000
- Due date: 12 bulan (tahunan)
- Klik Selesai ✓

**Hasilnya:** Amplop "Servis Motor" buat Sinking Fund, target Rp500.000 setahun, dengan progress bar untuk tracking.

---

## Mengapa 4 Langkah Lebih Baik?

✅ **Tidak overwhelming** — satu pertanyaan per langkah
✅ **Smart defaults** — sistem suggest based on nama & purpose
✅ **Semua field penting tersedia** — tanpa ribet
✅ **Flexible** — user bisa skip atau custom di mana saja
✅ **Progressive disclosure** — langkah 4 optional, muncul kalau dibutuhkan

Proses ini terutama membantu **user baru yang belum familiar** dengan konsep expense/saving/sinking fund — mereka tidak perlu semua field sekaligus, tapi semua aspek penting tetap covered.

Sudah coba buat amplop baru? Feedback Bapak tentang UX flow-nya ke [hi@jatahku.com](mailto:hi@jatahku.com).
