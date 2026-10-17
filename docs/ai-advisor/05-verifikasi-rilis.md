# AI Advisor v2 — verifikasi & rilis Fase 1 (S10)

Daftar cek untuk menyalakan flag `advisor_v2_users` = `*` (03-workflow.md §5). Langkah 1–5 dijalankan pemilik produk (butuh VPS / akun admin); hasilnya ditulis di bagian **Catatan uji** di bawah dan di `SESI-LOG.md`. Penghapusan jalur lama (langkah 6) dikerjakan di PR terpisah **sesudah** flag `*` menyala dan cek lolos.

## Menyetel flag

Tidak ada UI Admin untuk flag ini. Pilih salah satu:

- **Konsol browser** di `jatahku.com`, login sebagai admin:
  ```js
  const set = v => fetch(`https://api.jatahku.com/admin/settings/advisor_v2_users?value=${encodeURIComponent(v)}`,
    {method: 'PUT', headers: {Authorization: `Bearer ${localStorage.getItem('jatahku_token')}`}}).then(r => r.json())
  await set('<id1>,<id2>')   // akun tim
  await set('*')             // semua user
  ```
  Baca nilai sekarang: `GET /admin/settings/advisor_v2_users`.
- **psql di VPS:** `UPDATE app_settings SET value = '*' WHERE key = 'advisor_v2_users';`

Cache dashboard 90 detik (`advisor_cache.TTL_DASHBOARD`); perubahan flag berlaku untuk Beranda paling lambat 90 detik kemudian, untuk bot & ringkasan seketika.

**Rollback:** setel kembali ke daftar akun tim (atau kosongkan). Tidak ada migrasi atau data yang perlu dikembalikan; UI dan bot lama masih ada sampai langkah 6.

## 1. Deploy & kesehatan
- [ ] PR S10 di-merge; `api.jatahku.com/health` → `commit` = commit merge; `jatahku.com/version.json` sama.
- [ ] Migrasi S1 (`c5e9a2d7f4b1`, `is_emergency`) sudah `alembic current` di VPS.

## 2. Cek paritas semua user (read-only, sebelum flag `*`)
```
cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.advisor_paritas
```
Untuk setiap user (flag diabaikan, tidak ada yang ditulis): Beranda (`/advisor/dashboard`) vs chat "sisa" vs `/status` vs ringkasan harian, nama amplop pribadi anggota lain tidak muncul (skenario 7), tidak crash, waktu hitung (target < 150 ms).
- [ ] Baris akhir: `beda 0 · crash 0`. Kode keluar 0.
- [ ] Catat jumlah user `> 150 ms`. Bukan penghalang rilis, tapi tulis di Catatan uji.
- [ ] Bila ada `crash`/`beda`: jangan nyalakan `*`. Kirim keluaran (tanpa data pribadi) ke sesi Claude Code untuk perbaikan kecil.

## 3. Uji akun tim (flag = id akun tim)
Pakai minimal satu akun household dengan dua anggota dan satu amplop pribadi milik anggota lain.

**Angka — harus identik di keempat tempat:** Beranda (kartu KPI), chat web ("sisa"), Telegram (`/status`, "sisa"), ringkasan harian.
- [ ] Dana belanja · Terpakai · Disisihkan tagihan · Sisa bebas · Aman N hari ke depan (J1) · Jatah hari ini (J0) · belanja hari ini.
- [ ] Catat satu pengeluaran (web) → Beranda, chat, Telegram berubah ke angka yang sama (≤ 90 detik untuk Beranda).
- [ ] Catat satu pengeluaran di Telegram → Beranda ikut berubah.

**Beranda**
- [ ] Chip AI muncul di 6 kartu KPI; popover (desktop) / bottom sheet (HP); Sembunyikan → chip hilang.
- [ ] Grafik harian: batang + garis jatah J0 + baris analisa; rata-rata 7 batang terakhir = laju di teks (skenario 20).
- [ ] Kartu AI Advisor: maks 3 item, Rincian, Nanti / Sembunyikan periode ini / Tidak relevan, "+N saran lain", Tanya → chat terbuka/terkirim.
- [ ] CTA rencana dana: lembar rencana muncul, sumber bukan amplop pribadi anggota lain / tabungan / terkunci; Eksekusi → saldo amplop berubah sesuai rencana; klik dua kali tidak membuat transfer ganda.
- [ ] Tandai lunas langganan dari CTA.
- [ ] Periode lalu (pilih periode sebelumnya) → UI lama, tidak error.

**Chat web & Telegram**
- [ ] "limit harian", "kapan habis", "pengeluaran hari ini", "kenapa boros?", "kenapa {amplop} habis?", "aman gak beli sepatu 300k".
- [ ] Anggota lain tidak melihat nama/deskripsi amplop pribadi kita di jawaban mana pun.

**Ringkasan** (satu user saja, jangan endpoint admin — itu mengirim ke semua user):
```
cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -c "import asyncio; from app.services.summary import send_daily_summary as f; asyncio.run(f(user_id='<id>'))"
```
- [ ] Angka di ringkasan = Beranda.

## 4. Nyalakan `*`
- [ ] Langkah 2 lolos dan langkah 3 tercentang.
- [ ] `set('*')`; buka Beranda dengan akun yang **bukan** akun tim → UI baru.

## 5. Pantau 24 jam
```
sudo journalctl -u jatahku.service --since "1 hour ago" | grep -E "jatahku\.advisor|advisor chat: gagal|Advisor summary failed|Traceback"
```
- [ ] Tidak ada traceback dari `jatahku.advisor.*`, "advisor chat: gagal …" (bot jatuh ke jawaban lama), atau "Advisor summary failed" (ringkasan jatuh ke versi lama).
- [ ] Ulangi langkah 2 besok pagi (ringkasan harian sudah terkirim dengan v2).

## 6. Sesudah `*` stabil → PR lanjutan "S10b: hapus jalur lama"
Dicatat dari S6/S7/S9; dikerjakan setelah langkah 4–5:
- Bot & ringkasan: jawaban lama di `nlp_cmd` (sisa, limit harian, kapan habis, hari ini, kenapa), `handlers.cmd_status`, `checkin_cmd.handle_whatif`, `summary.py`; `advisor_cmd.jawab` tanpa fallback.
- Frontend: `AttentionCard.jsx`, `attentionItems` (`dashboardInsights.js`), `api.getAdvisorInsights`; cabang flag-mati di `Dashboard.jsx`; `/analytics/prediction` di header bila label bisa dari `metrics`.
- Backend v1: `GET /advisor/insights`, `rules/{depletion,subscription,drift,goals,overspend}.py`, `context.py` bila tidak ada pemakai lain.
- Flag tetap ada (sebagai saklar darurat) sampai jalur lama terhapus; sesudahnya `flag_aktif` boleh dihapus.

## Catatan uji
| Tanggal | Langkah | Akun / jumlah user | Hasil | Catatan |
|---|---|---|---|---|
| | | | | |
