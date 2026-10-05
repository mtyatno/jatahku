---
title: "Masuk dengan Google: Login Jatahku Jadi Lebih Gampang"
description: "Bisa login Jatahku dengan akun Google — tidak perlu ingat password, tidak perlu daftar email lagi. Link akun existing atau buat baru, semuanya seamless."
pubDate: 2026-10-05
category: update-fitur
author: Tim Jatahku
cover: /covers/google-signin.svg
featured: false
---

Sebelumnya, saat mau login Jatahku, pilihan hanya:
1. Email + Password
2. Telegram (@JatahkuBot)

Kalau user lupa password atau baru daftar, harus isi form email dan buat password — sesuatu yang sering user malas lakukan atau malah lupa.

Sekarang ada pilihan ketiga: **Masuk dengan Google**.

Klik satu tombol → redirect ke Google → select akun → kembali ke Jatahku → selesai. Tidak perlu password, tidak perlu form, tidak perlu email verification.

---

## Cara Login dengan Google

### Saat Pertama Kali

**Kalau belum punya akun Jatahku:**

1. Buka [jatahku.com](https://jatahku.com)
2. Klik **"Daftar"**
3. Lihat opsi **"Daftar dengan Google"** (besar, eye-catching)
4. Klik tombol Google
5. Browser redirect ke Google login
6. Pilih akun Gmail yang mau dipakai
7. Google tanya: "Boleh akun ini akses Jatahku?"
8. Klik "Allow"
9. Redirect balik ke Jatahku
10. Setup onboarding (tipe pendapatan, dll)

**Selesai.** Akun sudah jadi, tidak perlu password, tidak perlu email verification.

### Saat Sudah Punya Akun

**Kalau sudah ada akun Jatahku (email + password):**

1. Buka [jatahku.com](https://jatahku.com) → **"Masuk"**
2. Klik **"Masuk dengan Google"**
3. Google login
4. Jatahku tanya: "Email Gmail kamu cocok dengan akun Jatahku ada?"
5. Kalau cocok → otomatis link akun, masuk langsung
6. Kalau tidak cocok → opsi bikin akun baru atau pilih akun existing yang lain

---

## Keuntungan Login dengan Google

### ✅ Cepat dan Gampang

Tidak perlu isi form email, tidak perlu bikin password rumit, tidak perlu ingat password nanti.

**Sebelumnya:** Email + password → email verification → confirm → baru bisa login (5+ langkah)

**Sekarang:** Klik Google button → allow → login (2-3 langkah)

### ✅ Aman

Google handle authentication — Jatahku tidak perlu simpan password user. Lebih aman buat user (tidak ada risk password di-hack di Jatahku), lebih aman untuk Jatahku (tidak perlu manage database password).

### ✅ Single Sign-On

Kalau user sudah login di Chrome/device, cukup klik Google button → langsung masuk tanpa perlu type password lagi.

### ✅ Account Recovery

Lupa password? Tidak masalah — bisa login dengan Google. Atau update password di Google, automatic terupdate di Jatahku juga.

---

## Account Linking: Telegram, Email, dan Google

Satu akun Jatahku sekarang bisa di-link dengan **tiga cara login berbeda**:

### Skenario 1: User Mulai dari Google

User A mulai dari "Daftar dengan Google".

- Akun terbuat di Jatahku dengan email Gmail-nya
- Nanti, di Settings bisa link akun Telegram atau email+password

**Contoh:**
```
Account: Muhammad Ihsan
Login methods:
- Google (ihsan@gmail.com) ✓ PRIMARY
- Telegram (@IhsanUser) ✓
- Email (ihsan@example.com) + Password ✓
```

Ihsan bisa login dengan salah satu dari tiga cara itu.

### Skenario 2: User Mulai dari Email, Nambah Google Later

User B dulu pakai email + password.

Nanti di Settings → Account, bisa klik "Link dengan Google".

**Hasil:**
```
Account: Budi Hartono
Login methods:
- Email (budi@jatahku.id) + Password ✓ PRIMARY
- Google (budi.hartono@gmail.com) ✓
- Telegram (@BudiH) ✓
```

---

## Privacy & Data

### ✅ Jatahku tidak Baca Email Gmail

Login dengan Google hanya untuk **authentication** — verifikasi "kamu siapa".

Jatahku **tidak bisa baca** isi email user atau kontak atau apapun di akun Gmail. Google hanya send "oke, orang ini valid" ke Jatahku.

### ✅ Tidak Ada Sync Otomatis

Jatahku tidak sync GMail, kontak, atau data Google lainnya. Login dengan Google hanya untuk masuk — selesai.

---

## Di Mana Tombol Google Signin?

### Halaman Login
```
┌─────────────────────────────────────────┐
│ Jatahku                                 │
│ Setiap rupiah ada jatahnya             │
│                                          │
│ [Masuk] [Daftar]                        │
│                                          │
│ [Google logo] Masuk dengan Google       │
│ atau gunakan email                      │
│                                          │
│ Email: [________________]                │
│ Password: [________________]             │
│ [Masuk dengan Email]                    │
└─────────────────────────────────────────┘
```

### Halaman Daftar
```
┌─────────────────────────────────────────┐
│ [Google logo] Daftar dengan Google      │
│ atau gunakan email                      │
│                                          │
│ Nama: [________________]                 │
│ Email: [________________]                │
│ Password: [________________]             │
│ [Daftar dengan Email]                   │
└─────────────────────────────────────────┘
```

---

## Skenario: Rina Daftar dengan Google

**Rina buka jatahku.com untuk pertama kali.**

1. Rina: "Saya mau coba budgeting app ini"
2. Lihat tombol "Daftar dengan Google" → Klik
3. Google: "Pilih akun mana?"
4. Rina: Select rina.santoso@gmail.com
5. Google: "Boleh Jatahku akses data ini?"
6. Rina: Allow
7. **Redirect ke Jatahku → Onboarding start**
8. Tanya tipe pendapatan: "Harian" (Rina ojek driver)
9. Tanya income: "Rp150.000/hari, kerja 20 hari"
10. Pilih template: "Driver & Kurir"
11. Setup saldo awal: "Rp0"
12. **Selesai → Dashboard ready**

Total waktu: **< 2 menit**. Rina tidak perlu ingat password, tidak perlu email verification — langsung bisa mulai budgeting.

---

## FAQ: Login dengan Google

**Q: Kalau akun Gmail saya di-hack, bagaimana Jatahku-nya?**

A: Kalau Gmail di-hack, orang itu bisa login ke Jatahku pakai Gmail tersebut. Segera update password Gmail, dan pergi ke Jatahku Settings untuk remove Google link atau set password backup.

**Q: Bisa login dengan akun Google kerja/organizational?**

A: Tergantung konfigurasi Gmail. Biasanya bisa, tapi beberapa organisasi blokir third-party app. Hubungi admin IT kamu.

**Q: Gimana kalau dua orang pakai email Gmail yang sama?**

A: Tidak mungkin — Gmail unique per person. Tapi bisa pakai dua Gmail yang berbeda untuk dua akun Jatahku.

**Q: Harus bikin Gmail baru untuk Jatahku?**

A: Tidak, pakai Gmail yang sudah ada. Atau bikin Gmail baru kalau mau terpisah.

---

## Keamanan & Best Practice

✅ **Gunakan password Google yang kuat** — jangan shared, jangan simple

✅ **Enable 2-factor authentication di Google** — double-check saat login

✅ **Review koneksi app di Google Settings** — lihat app mana aja yang bisa akses Gmail mu

✅ **Logout Jatahku di device shared** — jangan biarkan session tetap aktif

---

Login dengan Google adalah step kecil tapi penting untuk **membuat Jatahku lebih accessible**. Terutama untuk:

✅ **User baru** yang malas isi form
✅ **Mobile user** yang prefer convenience
✅ **Multiple account** yang ingin terpisah

Google signin already live di jatahku.com. Coba sekarang, atau kalau punya feedback, kirim ke [hi@jatahku.com](mailto:hi@jatahku.com).
