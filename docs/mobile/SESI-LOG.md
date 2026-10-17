# Mobile — catatan serah-terima

Entri terbaru di atas. Format: **Kode sesi · paket · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## A07 · 1.1 Sesi per perangkat · 2026-10-17 · pemilik produk + Claude

**Selesai** (kriteria paket terpenuhi dalam 1 dari 6 sesi; status review)
- Tabel `auth_sessions` + `users.tokens_revoked_at`, migrasi `d3b8f1a6c2e9` (down: `c5e9a2d7f4b1`). Model `AuthSession` di `models.py`; logika di `app/services/auth_sessions.py`.
- Access token membawa `sid`, refresh token `sid` + `jti`. `deps.get_current_user` menolak sesi yang dicabut/kedaluwarsa; dependency baru `get_current_session_id`.
- `/auth/refresh` merotasi `jti`; `jti` sebelumnya diterima `REFRESH_GRACE` = 30 detik (dua tab), selain itu = dipakai ulang → sesi dicabut (`revoked_reason="reuse"`).
- Token lama tanpa sid: access diterima sampai kedaluwarsa; refresh ditukar sekali jadi sesi (`legacy_token_hash` mencegah tukar ulang); keduanya ditolak setelah logout-all.
- Endpoint baru: `POST /auth/logout` (refresh token di body atau access token; selalu 200), `GET /auth/sessions`, `DELETE /auth/sessions/{id}`. `/user/logout-all` mencabut semua sesi (respons lama tetap).
- Reset sandi: cabut semua lalu login di sini. Ganti sandi: cabut perangkat lain. `/auth/link/claim-telegram` juga lewat `start_session`.
- Web: `api.logout()` memanggil `/auth/logout` (keepalive, tidak ditunggu) lewat `src/lib/authLogout.js`.
- Tes: `app/tests/test_auth_sessions.py` (18, SQLite + httpx ASGITransport), `frontend/src/lib/authLogout.test.js`.

**Digantung**
- UI daftar perangkat di Settings (endpoint sudah ada) — belum diminta; bisa diambil sisa jatah A08–A12 atau paket 1.5/3.x.
- Hapus akun belum mencabut sesi → paket 1.2 (`auth_sessions.revoke_all`).
- Kode token lama (cabang tanpa sid di `deps.py`, `_upgrade_legacy`, kolom `legacy_token_hash`) bisa dibuang ≥30 hari setelah deploy.

**Jebakan**
- **Migrasi wajib manual saat merge**: `users.tokens_revoked_at` dipetakan model, jadi semua query User 500 (termasuk login) sampai `alembic upgrade head` jalan. `deploy.sh` hanya memperingatkan.
- `bcrypt` tidak di-pin di `requirements.txt`; instal baru dapat bcrypt 5 yang patah dengan passlib 1.7.4 (`hash_password` ValueError). Di tes hash dipalsukan. Produksi patah bila venv dipasang ulang — perlu pin ke versi yang terpasang di VPS (mis. `bcrypt<5`; di luar scope, belum dikerjakan).
- Tes SQLite: bila `asyncSetUp` gagal sebelum `engine.dispose`, thread aiosqlite membuat proses menggantung — dispose didaftarkan via `addAsyncCleanup` sejak awal.
- `frontend/dist/index.html` ter-track; kembalikan setelah `npm run build`.

**Keputusan kecil**
- Masa tenggang 30 detik (kajian: "beberapa detik"; jaringan HP lambat). Sesi geser: setiap refresh memperpanjang 30 hari.
- `jti` disimpan apa adanya (tanpa hash): tidak berguna tanpa `JWT_SECRET`. IP tidak dicatat (privasi); hanya `X-Jatahku-Client` dan user agent.
- Satu commit per login: `_tokens()` meng-commit perubahan user + sesi sekaligus.
- FK `auth_sessions.user_id` `ON DELETE CASCADE`, jadi `merge_users` tidak perlu diubah.

**Cara melanjutkan**
- Review PR di sesi terpisah; saat merge jalankan migrasi (langkah di deskripsi PR).
- Status O01 di PROGRESS masih "berjalan" padahal PR #100 sudah merge — rapikan di PR O01/terpisah.
- Paket berikut yang terbuka: `/sesi A13` (1.2, butuh 1.1 merge) atau `/sesi A01` (1.3).

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
