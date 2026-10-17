# Mobile — catatan serah-terima

Entri terbaru di atas. Format: **Kode sesi · paket · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## O01 · 0.1 Bootstrap dokumen · 2026-10-17 · pemilik produk + Claude

**Selesai**
- Kajian yang disetujui 16 Okt 2026 masuk repo: `docs/mobile/00-indeks.md`, `01-kajian.md`, `02-adr.md` (ADR-M1–M16), `03-workflow.md` (alur kerja + daftar 62 paket, kode sesi O/A/B), `PROGRESS.md`, file ini.
- `AGENTS.md`: bagian baru "Aplikasi mobile" (11 aturan), ditambahkan di akhir file supaya tidak bentrok dengan sesi AI Advisor.
- `CLAUDE.md`: satu baris penunjuk ke `docs/mobile/`.
- Perintah Claude Code `.claude/commands/sesi.md` (`/sesi <kode>`) dan `tutup-sesi.md` (`/tutup-sesi`).

**Digantung**
- Paket 0.2 (akun toko), 0.3 (PSE), 0.4 (privasi), 0.5 (penguji), 0.6 (build iOS) — pekerjaan pemilik produk di luar repo; status diubah di tracker dan `PROGRESS.md`.

**Keputusan kecil**
- Mengikuti pola `docs/ai-advisor/` (indeks, workflow, PROGRESS, SESI-LOG) supaya tim memakai satu cara kerja.
- Paket 1.4 diperkecil: `.github/workflows/test.yml` sudah ada (AI Advisor S0); yang tersisa cek perubahan OpenAPI yang memutus.
- Temuan baru sejak kajian: unggah foto profil di `Settings.jsx` menebak alamat API dari hostname (`localhost` → `http://localhost:8000`); di aplikasi akan patah. Masuk paket 1.5.

**Cara melanjutkan**
- Pemilik produk: isi tanggal mulai minggu 1 di tracker, kerjakan O02–O05.
- Sesi kode pertama yang aman paralel dengan AI Advisor: `/sesi A01` (paket 1.3, `/app/config`).
