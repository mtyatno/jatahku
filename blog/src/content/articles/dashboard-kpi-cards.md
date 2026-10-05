---
title: "Dashboard KPI Cards: Lihat Kondisi Keuangan Sekilas"
description: "Dashboard sekarang punya KPI cards yang menampilkan Dana Dialokasi, Sisa Bebas, Tabungan, dan Daily Spend dalam visual yang mudah dipahami — bukan angka aja, ada chart dan breakdown."
pubDate: 2026-10-05
category: update-fitur
author: Tim Jatahku
cover: /covers/dashboard-kpi-cards.svg
featured: false
---

Dulu, saat buka Dashboard Jatahku, yang tampil adalah:
- Satu card besar untuk Sisa Bebas
- List amplop yang panjang
- Kalau mau detail breakdown, harus scroll atau tap satu per satu

Hasilnya, user yang sibuk tidak bisa dapat snapshot cepat: "Kondisi keuanganku gimana hari ini?"

Sekarang **Dashboard punya KPI Cards** — 6 card kecil yang menampilkan info utama dalam satu layar, lengkap dengan visual breakdown dan chart.

---

## 6 KPI Cards di Dashboard

### 1. 💰 Dana Dialokasi

**Menampilkan:** Total alokasi periode ini + rollover dari periode lalu

**Visual:** Stacked bar chart yang breakdown menjadi 4 bagian:
- **Terpakai** (amber) — spending yang sudah terjadi
- **Tagihan** (slate gray) — bill reserve untuk subscription
- **Tabungan** (indigo) — saving envelope balance
- **Bebas** (brand green) — sisa uang yang bisa dipakai bebas

**Info di card:**
```
Dana Dialokasi: Rp 2.500.000
(+Rp 150.000 rollover dari bulan lalu)

[████████░░] visual bar
Terpakai Rp800k | Tagihan Rp300k | Tabungan Rp600k | Bebas Rp800k
```

**Interaktif:** Tap pada bar → lihat detail breakdown per amplop.

### 2. 🎯 Sisa Bebas

**Menampilkan:** Uang yang benarbenar aman untuk belanja hari ini

Formula: (Total alokasi + rollover) − (Terpakai) − (Reserved bill) − (Saving envelope)

**Visual:** Meter/gauge yang berubah warna:
- 🟢 Green (>30% dari alokasi) — aman
- 🟡 Amber (15-30%) — hati-hati
- 🔴 Red (<15%) — tight

**Info di card:**
```
Sisa Bebas: Rp 800.000
Safe daily: Rp 26.000/hari (until end of period)

[████████░░░░░░░░] meter
```

### 3. 📊 Alokasi per Hari

**Menampilkan:** Breakdown dana per hari (harian, mingguan, atau bulanan tergantung income type)

**Visual:** Simple breakdown:
- Income type + payday countdown
- "Tersisa 8 hari sampai gajian"
- Batas aman dihitung otomatis

**Info di card:**
```
Alokasi Harian
Rp 26.000/hari sampai gajian (8 hari lagi)

[████] 1 hari berjalan
```

### 4. 💎 Target Tabungan

**Menampilkan:** Ringkasan semua saving goal dalam satu card

**Visual:** Mini progress bars untuk top 3-4 saving goals

**Info di card:**
```
Target Tabungan
🎯 Nikah: 40% — estimasi 5 bulan lagi
🚗 Mobil: 15% — estimasi 12 bulan
✈️ Liburan: 60% — estimasi 2 bulan

[Lihat semua goal]
```

### 5. 📈 Pengeluaran Harian

**Menampilkan:** Trend spending dalam 7 hari terakhir

**Visual:** Sparkline chart (mini line chart) yang menunjukkan:
- Spending kemarin, 2 hari lalu, dst
- Garis trend (naik/turun)
- Hari ini (incomplete)

**Info di card:**
```
Pengeluaran Harian
Rata-rata: Rp 250.000/hari
Hari ini: Rp 180.000 (on track)

[mini sparkline chart]
```

### 6. ⚠️ AI Advisor Urgent Alert

**Menampilkan:** Alert paling penting dari AI Advisor hari ini

**Contoh:**
- "🍜 Makan sudah 80%, perlu potong belanja minggu depan"
- "⚠️ Budget berisiko jebol, proyeksi overspend Rp500k"
- "🎯 Tabungan hampir capai target!"

**Visual:** Color-coded berdasarkan severity (red/amber/green)

---

## Mengapa KPI Cards Berguna?

### ✅ Snapshot Cepat

Saat user buka Dashboard, dalam **5 detik** mereka sudah tahu:
- Sisa uang berapa
- Spending trend gimana
- Ada warning apa
- Saving goal progress

Tidak perlu scroll banyak atau tap satu per satu.

### ✅ Visual, Bukan Hanya Angka

Meter dan chart lebih mudah dipahami daripada angka mentah:
- Green meter = aman
- Red meter = tight
- Chart naik = spending naik

### ✅ Contextual Info

Setiap card kasih konteks yang relevan:
- Batas aman hingga kapan
- Sisa hari berapa sampai gajian
- Progress goal dibanding timeline

### ✅ Actionable

Kalau ada alert, user bisa **langsung action**:
- Alert "Makan 80%" → klik → langsung buka proposal amplop Makan
- Alert "Budget berisiko" → klik → lihat breakdown pengeluaran

---

## Contoh Real: Siti Cek Dashboard Pagi Hari

Siti buka Jatahku pagi hari sebelum berangkat kerja.

**Dalam 5 detik, Siti bisa tahu:**

```
┌─ Dana Dialokasi Rp2.500.000 (breakdown visual)
├─ Sisa Bebas Rp800.000 ✅ (aman)
├─ Pengeluaran kemarin Rp350.000 (chart trend)
├─ Saving goal: Liburan 60%, on track ✅
└─ Alert: "Nggak ada warning hari ini 🎉"
```

Siti langsung percaya diri: "Hari ini bisa belanja normal, tidak tight."

Kalau ada warning (contoh: "Budget berisiko jebol"), Siti bisa langsung lihat detail dan adjust pengeluaran sebelum pergi.

---

## KPI Cards vs Halaman Detail

| Info | KPI Card | Detail Page |
|------|----------|-------------|
| **Akses** | Instant (dashboard) | Perlu navigate |
| **Detail** | Summary saja | Lengkap, per amplop |
| **Waktu** | 5 detik | 1-2 menit |
| **Aksi** | Alert + quick action | Deep dive, edit |

**Filosofi:** KPI cards untuk quick check, halaman detail untuk deep analysis.

---

## Dark & Light Mode

KPI cards mendukung dark dan light mode:
- **Light:** Clear contrast, lebih bright
- **Dark:** Mata lebih nyaman malam hari

Chart dan meter warna-nya otomatis adjust sesuai theme.

---

## Responsive Design

- **Mobile (360px):** Cards stack vertikal, full-width
- **Tablet:** 2-3 cards per row
- **Desktop:** Semua 6 cards terlihat jelas dalam satu viewport

---

Dashboard KPI cards adalah evolusi dari "banyak info, sulit dipahami" menjadi "info penting, visualnya jelas, akses cepat". Terutama berguna buat pengguna yang:

✅ Sibuk dan butuh quick check
✅ Prefer visual daripada angka mentah
✅ On-the-go dan perlu decision cepat
✅ Baru belajar budgeting dan perlu guidance yang clear

Sudah coba lihat KPI cards di dashboard? Feedback ke [hi@jatahku.com](mailto:hi@jatahku.com).
