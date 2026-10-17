---
description: Buka sesi kerja mobile Jatahku untuk satu kode sesi (mis. A01, B07, O03)
argument-hint: <kode sesi, mis. A01>
---

Buka sesi kerja aplikasi mobile Jatahku dengan kode sesi **$ARGUMENTS**.

1. Cari baris di `docs/mobile/PROGRESS.md` yang rentang kode sesinya mencakup `$ARGUMENTS` (mis. A04 ada di `A04–A06`). Sebutkan paket (WBS), jalur, dan apakah ini sesi pertama, tengah, atau terakhir paket itu. Kalau kode tidak ditemukan, berhenti dan tanyakan.
2. Baca: `docs/mobile/00-indeks.md`, `docs/mobile/03-workflow.md` §2, §5, §6 (baris paket ini), `docs/mobile/02-adr.md`, bagian "Aplikasi mobile" di `AGENTS.md`, entri terakhir `docs/mobile/SESI-LOG.md` (terutama untuk paket ini), dan baris WBS paket ini di `docs/mobile/01-kajian.md`.
3. Cek dependensi di kolom "Butuh" dan kolom "Koordinasi AI Advisor": bila dependensi belum selesai di `PROGRESS.md`, atau file yang akan disentuh masih milik sesi AI Advisor yang belum selesai di `docs/ai-advisor/PROGRESS.md`, berhenti dan laporkan.
4. `git fetch origin main`, lalu lanjutkan branch `mobile/<wbs>-*` bila sudah ada di remote, atau buat baru dari `origin/main`.
5. Rangkum dalam maksimal 6 baris: target sesi ini, file yang boleh disentuh, tes yang harus hijau, ADR yang berlaku, dan risiko. **Tunggu "lanjut" sebelum mengubah kode.**
6. Selama bekerja: jalankan tes setiap kali satu bagian selesai; jangan menyentuh file di luar scope tanpa bertanya; temuan di luar scope dicatat, tidak dikerjakan diam-diam.
