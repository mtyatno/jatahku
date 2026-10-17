---
description: Verifikasi bahwa sebuah PR/commit sudah benar-benar tayang di produksi, lewat hasil workflow deploy di GitHub
argument-hint: <nomor PR atau SHA commit; kosong = HEAD main>
---

Verifikasi deploy untuk **$ARGUMENTS** (kosong = commit terbaru di `main`).

Sesi Claude Code di cloud tidak bisa membuka `api.jatahku.com` atau `jatahku.com` (akses jaringan dibatasi), dan memang tidak perlu: langkah **"Verifikasi versi yang tayang"** di `.github/workflows/deploy.yml` sudah mengecek `/health` (commit API) dan `/version.json` (commit web) dari runner GitHub, dan hanya lulus bila keduanya menjalankan commit itu atau yang lebih baru. Jadi baca hasil workflow itu lewat GitHub API.

1. Tentukan SHA:
   - Nomor PR → `gh api repos/mtyatno/jatahku/pulls/<n> --jq '{merged: .merged, sha: .merge_commit_sha}'`. Bila belum di-merge, laporkan "belum di-merge, belum dideploy" dan berhenti.
   - Kosong → `git fetch -q origin main && git rev-parse origin/main`.
2. Cari run deploy untuk SHA itu:
   `gh api "repos/mtyatno/jatahku/actions/workflows/deploy.yml/runs?head_sha=<sha>" --jq '.workflow_runs[0] | {id, status, conclusion, html_url}'`
3. Baca hasilnya:
   - `completed` + `success` → **terverifikasi tayang** (API dan web menjalankan commit ini atau yang lebih baru).
   - `queued` / `in_progress` → deploy masih antre/berjalan; tunggu ±2 menit lalu cek lagi (maks 5 kali), jangan melapor "gagal".
   - `cancelled` atau tidak ada run → wajar bila push lain menyusul (antrean deploy hanya menyimpan satu run yang menunggu). Ambil run sukses terbaru: `gh api "repos/mtyatno/jatahku/actions/workflows/deploy.yml/runs?status=success&per_page=1" --jq '.workflow_runs[0] | {head_sha, html_url}'`, lalu `gh api repos/mtyatno/jatahku/compare/<sha>...<head_sha_run_sukses> --jq .status`. `ahead` atau `identical` → **terverifikasi lewat deploy yang lebih baru**; selain itu → belum tayang.
   - `failure` → **deploy gagal**: `gh api repos/mtyatno/jatahku/actions/runs/<id>/jobs --jq '.jobs[] | {name, conclusion, steps: [.steps[] | select(.conclusion=="failure") | .name]}'`, laporkan langkah yang gagal + tautan run. Gagal di "Verifikasi versi yang tayang" berarti kode sudah di VPS tapi proses lama masih melayani; perlu dicek di VPS (`journalctl -u jatahku`).
4. Laporkan satu baris: `Deploy <sha7>: terverifikasi tayang | masih berjalan | gagal di <langkah> | belum di-merge — <tautan run>`.
5. Yang tidak tercakup di sini (butuh orang/laptop dengan akses produksi): migrasi alembic manual, isi data produksi, dan uji tampilan di perangkat. Sebutkan bila paket ini membutuhkannya.
