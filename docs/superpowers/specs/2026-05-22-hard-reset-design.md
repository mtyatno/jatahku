# Hard Reset Data — Design Spec

**Date:** 2026-05-22
**Status:** Approved

## Overview

Fitur yang memungkinkan user menghapus semua data finansial mereka dan memulai dari awal, tanpa menghapus akun. Sebelum data dihapus, backend otomatis generate export JSON dan kirim ke email user sebagai backup.

---

## Scope Reset

### Data yang dihapus
- Envelopes (beserta alokasi & rollover)
- Transactions
- Allocations
- Incomes
- Recurring transactions

### Data yang tidak dihapus
- Settings akun (payday_day, timezone, theme, color)
- Notification preferences
- Pro status & payment history
- Household membership & relasi

---

## Alur Konfirmasi (Dialog — 4 Steps)

Dibuka dari tombol **"Reset Semua Data"** di Settings page (Zona Berbahaya).

### Step 1 — Warning
Tampilkan ringkasan data yang akan dihapus. Jika user adalah anggota household, tampilkan peringatan tambahan:
> "Kamu adalah anggota household. Envelope yang kamu share juga akan terdampak."

### Step 2 — Email (kondisional)
- Jika user sudah punya email → step ini dilewati, langsung ke Step 3.
- Jika belum → tampilkan input field: *"Masukkan email untuk menerima backup data kamu sebelum reset."* Email disimpan ke akun sekaligus dipakai kirim backup.

### Step 3 — Type-to-confirm
Input field dengan placeholder `ketik RESET untuk melanjutkan`. Tombol **"Reset Sekarang"** hanya aktif jika input persis `RESET` (case-sensitive).

### Step 4 — Processing & Selesai
- Backend dieksekusi (lihat bagian Backend)
- Setelah selesai: redirect ke `/envelopes` dengan toast sukses:
  - Jika email berhasil: *"Data berhasil direset. Backup dikirim ke [email]."*
  - Jika email gagal: *"Data berhasil direset. Backup tidak berhasil dikirim."*

---

## Backend

**Endpoint:** `POST /user/reset`
- Auth: JWT required (current user)

### Flow eksekusi
1. Ambil semua data finansial user
2. Generate export JSON (envelopes + transactions + incomes + recurring transactions)
3. Jika email baru diinput di Step 2, update `user.email` terlebih dahulu
4. Kirim email via `email_service.py` dengan attachment file JSON bernama `jatahku-backup-{date}.json`
5. Hapus semua data dalam satu DB transaction, urutan:
   - `transactions`
   - `allocations`
   - `incomes`
   - `recurring_transactions`
   - `envelopes`
6. Return `{"success": true, "email_sent": true|false}`

### Error handling
- Jika kirim email gagal → tetap lanjut reset, response include `{"email_sent": false}`
- Semua DELETE dalam satu DB transaction — jika salah satu gagal, seluruh operasi rollback

---

## UI Placement

Halaman **Settings**, section **"Zona Berbahaya"** di paling bawah halaman:
- Dipisahkan dengan garis merah tipis
- Background sedikit berbeda untuk sinyal visual destructive area
- Tombol: `Reset Semua Data` — merah, outline style, dengan icon warning/trash

---

## Edge Cases

| Kondisi | Penanganan |
|---|---|
| User belum punya email | Minta input email on the spot (Step 2) |
| User anggota household | Tampilkan peringatan di Step 1, reset tetap bisa dilanjutkan |
| Email gagal terkirim | Reset tetap dieksekusi, toast warning ditampilkan |
| DB transaction gagal | Rollback semua, tampilkan pesan error |
