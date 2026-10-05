---
title: "Sisa Bebas Jadi Lebih Akurat: Sekarang Dikurangi Bill Reserve"
description: "Sisa Bebas sekarang sudah mengurangi uang yang disisihkan untuk subscription — jadi angka yang ditampilkan benar-benar uang yang aman untuk belanja hari ini."
pubDate: 2026-10-05
category: update-fitur
author: Tim Jatahku
cover: /covers/cara-pakai-bot-telegram.svg
featured: false
---

Sebelumnya, **Sisa Bebas = Total Alokasi − Terpakai**

Artinya, jika alokasi Rp2.000.000 dan sudah belanja Rp800.000, maka Sisa Bebas = **Rp1.200.000**.

Tapi ada masalahnya: Di dalam Rp1.200.000 itu, ada uang yang **sudah disisihkan untuk langganan**. Misalnya streaming bulanan Rp29.000 due date Rp10, atau asuransi mobil Rp250.000 due date Rp15.

Kalau user tidak hati-hati, bisa pakai Rp1.200.000 itu semua, terus waktu langganan due, tidak ada uang untuk bayar.

Sekarang **Sisa Bebas sudah smart: mengurangi bill reserve** sebelum tampil angkanya.

---

## Apa itu Bill Reserve?

**Bill Reserve** adalah uang yang sudah disisihkan untuk subscription atau recurring bill yang due dalam periode ini.

**Contoh:**

Rudi punya:
- Streaming Netflix: Rp49.000, due date 10
- Asuransi mobil: Rp250.000, due date 8
- Domain hosting: Rp150.000, due date 25

Total bill reserve = Rp49k + Rp250k + Rp150k = **Rp449.000**

Uang ini **sudah direncanakan untuk dibayar** — tidak bisa dihitung sebagai "sisa bebas untuk belanja".

---

## Formula Sisa Bebas yang Baru

### Sebelumnya (Lama):
```
Sisa Bebas = Total Alokasi − Terpakai
```

### Sekarang (Baru):
```
Sisa Bebas = Total Alokasi − Terpakai − Bill Reserve − Saving Envelope Balance
```

**Breakdown:**
- **Total Alokasi:** Dana yang dialokasikan periode ini + rollover dari periode lalu
- **Terpakai:** Spending yang sudah terjadi
- **Bill Reserve:** Uang yang disisihkan untuk langganan (sudah due atau akan due minggu ini)
- **Saving Envelope Balance:** Uang yang ada di amplop saving/sinking fund (tidak termasuk "bebas" karena untuk tujuan khusus)

---

## Contoh Real: Rudi Ojek Driver

**Alokasi Rudi bulan ini:**
- Total alokasi: Rp2.500.000
- Total rollover dari bulan lalu: Rp150.000
- **Total tersedia: Rp2.650.000**

**Pengeluaran:**
- Bensin: Rp600.000
- Makan: Rp300.000
- Lainnya: Rp200.000
- **Total terpakai: Rp1.100.000**

**Bill Reserve (langganan/recurring):**
- Asuransi motor: Rp250.000 (tanggal 8, sudah terlewat, masih di-reserve)
- Netflix: Rp49.000 (tanggal 10)
- **Total reserve: Rp299.000**

**Saving envelope:**
- Tabungan sinking fund (servis): Rp500.000 (uang untuk rencana, bukan bebas)

**Kalkulasi Sisa Bebas:**
```
Sisa Bebas = Rp2.650.000 − Rp1.100.000 − Rp299.000 − Rp500.000
           = Rp751.000
```

**Arti:** Rudi benar-benar punya Rp751.000 yang aman untuk belanja bebas hari ini tanpa khawatir nanti tidak ada uang untuk bayar langganan atau ambil sinking fund.

---

## Kalau Kalkulasi Lama?

Dengan kalkulasi lama:
```
Sisa Bebas = Rp2.650.000 − Rp1.100.000
           = Rp1.550.000
```

Terlihat seperti Rudi punya Rp1.550.000 tersisa.

Tapi **kenyataannya:**
- Rp299.000 harus untuk bayar langganan
- Rp500.000 harus di-reserve untuk sinking fund
- **Benar-benar bebas:** Rp751.000 saja

Kalau Rudi percaya Sisa Bebas = Rp1.550.000 dan pakai semuanya untuk belanja, nanti pas langganan due atau sinking fund terpakai, Rudi akan kekurangan uang.

---

## Sisa Bebas di Berbagai Bagian Jatahku

Sekarang, **Sisa Bebas dengan bill reserve** ditampilkan di:

### 1. Dashboard Hero Card
```
Sisa Bebas: Rp 751.000
Aman untuk belanja hari ini
```

### 2. AI Advisor Daily Line
```
Batas aman hari ini: Rp24.200/hari
(Rp751.000 sisa ÷ 31 hari tersisa)
```

*Catatan: Untuk ojek driver dan daily earner, sisa aman dihitung sampai income berikutnya (bisa 1-3 hari), bukan sampai 31 hari.*

### 3. Notifikasi per Amplop
```
🍜 Makan
Balance: Rp300.000
Status: On track ✅
```

### 4. Dashboard Breakdown
Dashboard menampilkan visual breakdown yang detail:
- **Terpakai:** Rp1.100.000
- **Reserve (langganan):** Rp299.000
- **Saving target:** Rp500.000
- **Benar-benar bebas:** Rp751.000

---

## Kapan Bill Reserve Berubah?

Bill reserve **otomatis update** saat:

✅ **Tambah langganan baru** → reserve bertambah
✅ **Bayar langganan** → reserve berkurang
✅ **Skip langganan** → reserve dihapus/berkurang
✅ **Ubah tanggal langganan** → sistem recalculate

**Contoh:** Rudi baru sign-up Netflix Rp49.000. Dashboard langsung update:
- Bill reserve: Rp299.000 → **Rp348.000**
- Sisa Bebas: Rp751.000 → **Rp702.000**

---

## Edge Case: Langganan yang Overdue

Kalau ada langganan yang due date sudah lewat (misal streaming sudah missed payment), sistem tetap reserve itu:
- Status: ⚠️ Overdue
- Reserve: Tetap di-hold sampai dibayar atau di-skip

Rudi akan lihat warning: "Streaming overdue dari 10 Oktober — perlu bayar atau skip segera."

---

## Mengapa Ini Penting?

Terutama untuk **pengguna dengan banyak subscription** (asuransi, streaming, langganan apps, cicilan):

✅ **Sisa Bebas tidak misleading** — angka yang ditampilkan benar-benar uang yang aman pakai
✅ **Mencegah overspend** — user tidak akan secara tidak sengaja pakai uang yang sudah di-reserve
✅ **Stress berkurang** — tidak perlu khawatir "besok langganan due, ada uang tidak ya?"
✅ **Planning lebih akurat** — kalau sisa bebas hanya Rp751.000, user tahu harus prioritas apa hari ini

---

## Perbedaan: Sebelum vs Sesudah

| Scenario | Kalkulasi Lama | Kalkulasi Baru |
|----------|---|---|
| Alokasi Rp2.500, terpakai Rp1.000, reserve Rp300, saving Rp500 | Rp1.500 | Rp700 |
| User berpikir bisa belanja Rp1.500 | ✗ (overspend nanti) | ✓ (aman) |
| Langganan due hari ini | Kaget tidak ada uang | Sudah reserve jadi ok |

---

**Sisa Bebas dengan bill reserve adalah langkah menuju budgeting yang lebih akurat dan stress-free.** User tidak lagi perlu khawatir "uangnya mana saat langganan due" — sistem sudah handle itu.

Sudah lihat perubahan Sisa Bebas di dashboard? Feedback ke [hi@jatahku.com](mailto:hi@jatahku.com).
