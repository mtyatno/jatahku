# AI Advisor di seluruh Jatahku — desain (Okt 2026)

**Status:**
- Desain dan spesifikasi aturan (`02-aturan.md` revisi 1) **disetujui pemilik produk 16 Okt 2026.**
- Development mengikuti rencana sesi di `03-workflow.md` (19 sesi, 4 fase).

**Mockup:** canvas "AI Advisor — Jatahku" di claude.ai (privat untuk organisasi), berisi Beranda desktop, Beranda HP (bottom sheet), dan contoh slot di halaman lain. Angka contoh mengikuti `02-aturan.md` §12; nama orang di contoh fiktif.

## Permintaan & kondisi awal
- **Permintaan (16 Okt 2026):** AI Advisor hadir di setiap bagian.
  - Di Beranda, tiap kartu KPI punya hasil analisa AI di pojok kanan atas.
  - Kartu "Perlu perhatian" jadi AI Advisor yang eksplisit, dengan tombol CTA untuk aksi apa pun.
  - Halaman lain juga dianalisa per bagian.
- **Kondisi awal:** mesin aturan tanpa LLM di `app/services/advisor/` (5 aturan, rekomendasi alokasi, saran sinking fund).
  - Sejak PR #51 tidak punya kartu sendiri di Beranda.
  - `allocation_drift`, `goal_progress`, dan `budget_overspend` tetap dihitung tiap Beranda dibuka, tapi tidak ditampilkan sejak 3 Okt (PR #8).

## Keputusan (pemilik produk, 16 Okt 2026)
1. **Tanpa LLM.** Ini menyangkut keuangan pribadi; sebagian user bisa keberatan datanya diproses pihak ketiga.
   - Semua analisa memakai mesin aturan deterministik di server Jatahku.
   - Konsisten dengan ini, fallback LLM scan struk tetap mati.
2. **CTA pemindah dana memakai konfirmasi satu langkah.** Rencana tampil, sumber bisa dilepas, satu tap, lalu dijalankan.
3. **Dari review 16 Okt:**
   - **Kartu Income:** angka utama tetap pemasukan sendiri. Bila pemasukan sendiri Rp0 tetapi amplop bersama terisi dari anggota lain, chip "Terisi dari {nama}" menampilkan dana yang masuk ke amplop bersama, bukan total pemasukan pribadi anggota itu.
   - **Chip diredam** bila di Beranda ada ≥ 1 chip danger atau ≥ 2 chip warn: chip info/ok tampil tanpa latar dan tanpa ikon ✦, hanya teks bergaris tepi tipis.
   - **Semua insight untuk semua paket.** (`check_pro_access` tidak pernah dipanggil, jadi hari ini pun tidak ada yang dibatasi.)
   - **Sumber "cek dulu"** tercentang default hanya bila sumber keinginan + kebutuhan berriwayat tidak cukup untuk kebutuhan danger; diberi badge kuning.
4. **Penutup:**
   - **Dana darurat** lewat field baru `envelopes.is_emergency` (default false), diisi otomatis dari nama "darurat"/"emergency" saat migrasi, bisa diubah user. Sesi S1 (migrasi) dan S11 (toggle di UI).
   - **`transfer_between_envelopes` ikut dikunci di Fase 1** (sesi S5) dengan kunci baris household yang sama dengan `POST /advisor/execute`.

## Prinsip
- **Tiap angka menjawab dua hal:** artinya apa, dan lakukan apa. Insight tanpa aksi tidak ditampilkan, kecuali kabar "aman".
- **Satu sumber angka.** Chip AI, KPI, grafik, chat web, dan Telegram membaca angka dari satu modul. Tidak boleh ada dua rumus "aman per hari".
- **Cermin, bukan penjaga gerbang.** Saran tidak pernah memblokir pencatatan; limit harian = peringatan.
- **Uang tidak pindah tanpa konfirmasi.**
- **Jujur soal dasar & keyakinan.** Tiap analisa menyebut dasarnya ("dari 19 hari data") dan cara hitungnya bisa dibuka.
- **Bisa dibungkam.** Tiap insight punya "Nanti" / "Sembunyikan hari ini".
- **Privasi household:** ikut kontrak `app/services/visibility.py`. Deskripsi transaksi privat anggota lain tidak pernah dikutip.

## Anatomi insight
Satu bentuk untuk semua permukaan (web, chat web, Telegram): `id` stabil, `slot`, `tone` (danger · warn · info · ok), `chip` (≤20 huruf), `title`, `body` (≤2 kalimat), `facts[]` (sekaligus "cara hitung"), `actions[]`, `basis`, `dismiss`. Detail tone, skor, dan penekanan di `02-aturan.md` §5; bentuk JSON di `04-kontrak-api.md`.

## Beranda

### Chip AI di 6 kartu KPI
Chip menggantikan badge status di pojok kanan atas. Klik chip membuka popover (desktop) atau bottom sheet (HP): judul, 1–2 kalimat analisa, angka kunci, 1–2 CTA, dasar analisa, "Sembunyikan".
- Popover muncul **di bawah kartu**, selebar kartu; kartu aktif diberi garis tepi terang.
- Cap waktu: "Diperbarui baru saja" (< 5 menit) atau "Diperbarui {jam}".

| Kartu | Contoh chip | Isi analisa | CTA |
|---|---|---|---|
| Jatah hari ini | "1,8× jatah" (danger) | Penyumbang terbesar hari ini; jatah sejak pagi (Rp165.100) vs aman 11 hari ke depan (Rp153.200) | Lihat transaksi hari ini · Tanya di chat |
| Sisa bebas | "Habis ±24 Okt" (warn) / "Cukup s/d 26 Okt" (ok) | Rata-rata 7 hari vs batas aman, tanggal habis, kekurangan | Batas harian di penyumbang terbesar · Tanya di chat |
| Terpakai periode ini | "Lewat ±Rp525 rb" (warn) | Proyeksi = terpakai + tagihan belum dibayar + laju 7 hari × sisa hari. Batang: hijau sampai penanda waktu, kuning setelahnya | Lihat per amplop · Atur alokasi |
| Income periode ini | "Terisi dari Rina" (info, redam) / "Belum masuk" (warn) | Pemasukan sendiri vs rumah tangga; jangan minta catat ulang | Catat pemasukan |
| Tagihan belum dibayar | "KPR telat 9 hari" (danger) | Jatuh tempo, kondisi amplop tagihan, rencana tutup. Batang: lunas hijau, telat merah | Geser & bayar · Bayar saja |
| Tabungan | "Darurat baru 3%" (info, redam) | Target terpenting, kecukupan dana darurat. Saat defisit, CTA "Rencanakan di alokasi berikutnya" | Setor · Lihat target |

Grafik Pengeluaran harian membaca deret harian dari metrik yang sama (belanja variabel; tagihan dan penyesuaian sebagai segmen redup) + satu baris analisa + tautan ke transaksi hari itu.

**Angka yang berubah karena satu sumber:**
- **Jatah hari ini** dibandingkan dengan jatah sejak pagi (J0): Rp297.100 / Rp165.100, lewat Rp132.000 (sebelumnya / Rp153.200, lewat Rp143.900).
- **Terpakai** dari dana belanja (71%, sebelumnya 44% dari semua amplop termasuk tabungan), dengan penanda waktu 63%.
- **Arus kas:** sisa − (tagihan belum dibayar + laju 7 hari × sisa hari): −Rp525 rb (sebelumnya −Rp1,34 jt karena tagihan dirata-rata sebagai belanja harian).
- **Laju:** rata-rata 7 hari terakhir, sama persis dengan 7 batang terakhir grafik.

### Kartu AI Advisor (pengganti "Perlu perhatian")
- Judul "AI Advisor" + badge jumlah + cap waktu; subjudul "Tiga langkah paling berdampak untuk sisa periode ini".
- Maksimal 3 item, urut **kelompok tone (danger → warn → info), lalu skor**. Sisanya "+N saran lain · Lihat semua".
- Tiap item: judul berupa aksi, satu kalimat alasan dengan angka, **Rincian**, CTA utama, **Nanti**.
- Rencana dana dihitung bersama untuk semua item (`02-aturan.md` §8).
- Kekurangan total menyerap kekurangan per amplop; lewat jatah hari ini digabung ke "Rem belanja harian" bila periode defisit; tidak menyarankan menabung saat defisit.
- "Tanya AI Advisor" menampilkan 3–4 chip pertanyaan cepat + "Ketik sendiri…", dijawab intent aturan.
- Contoh (15 Okt): Lunasi KPR (Geser & bayar Rp2.008.174 dari Pakaian Rp453.000, Pendidikan Rp1.410.000 "cek dulu", Kebutuhan Rumah Rp145.174) · Rem belanja harian ke Rp153 rb (batas Makan & Jajan Rp133 rb/hari) · Transport ditambal 7× (naikkan jatah jadi Rp720 rb) · +1 saran lain.

## Halaman lain
- **Amplop:** strip AI per kartu (menggantikan `lib/envelopeInsight.js`); CTA Naikkan jatah, Geser dana, Pasang limit, Setor, Atur target.
- **Transaksi:** banner ringkasan + penanda baris: pola rutin → "Jadikan langganan", kemungkinan dobel (termasuk struk terkirim dua kali), pengeluaran besar satu kali, nominal = tagihan belum dibayar → "Tandai lunas".
- **Alokasi:** rekomendasi dengan alasan per amplop + keyakinan, "Terapkan ke form".
- **Langganan:** beban tagihan, telat/jatuh tempo, Geser & bayar, Tandai lunas.
- **Analitik:** "Ringkasan AI periode ini" menggantikan "Insight (Beta)".
- **Chat web & Telegram:** angka dan saran yang sama, tombol aksi yang sama.

## Katalog CTA

| Aksi | Yang terjadi | Perlu dibangun | Sesi |
|---|---|---|---|
| Bayar tagihan | Bayar langganan tertentu | `PaySubscriptions` fokus satu langganan | S8 |
| Geser dana (1+ sumber) | Lembar rencana → konfirmasi → transfer | `FundEnvelopeModal` via event, multi-sumber; lembar konfirmasi | S5, S8 |
| Geser & bayar | Transfer lalu bayar, satu konfirmasi | `POST /advisor/execute` atomik, kunci household, `client_ref` | S5 |
| Tandai lunas | Memajukan `next_run` tanpa transaksi baru | `POST /recurring/{id}/mark-paid` | S4 |
| Catat pemasukan | Modal pemasukan terisi | `QuickAddIncome` prefill + `txn-added` | S8 |
| Naikkan jatah | Jatah amplop mulai periode depan | Endpoint jatah + konfirmasi | S11 |
| Pasang limit harian | Limit amplop (peringatan) | Behavior controls; rilis setelah Pikir-Pikir Fase 1 | S8 |
| Jadikan langganan | Form langganan terisi dari pola | `RecurringModal` mode buat + prefill | S8 |
| Setor tabungan | Geser ke amplop tabungan | Sama dengan Geser dana | S5, S8 |
| Lihat transaksi | `/transactions?date=…&envelope=…` | Halaman reaktif ke query | S8 |
| Atur alokasi | `/allocate?new=1` terisi | Form terbuka + terisi | S8, S14 |
| Tanya di chat | Chat dengan chip pertanyaan cepat | `ChatPanel` teks awal + chip | S8, S9 |
| Nanti / Sembunyikan / Bukan dobel | Dismiss | `POST /advisor/dismiss`, Redis | S3, S7 |

`jatahku:open-action` harus menerima objek `{kind, payload}` (sekarang hanya string).

## Arsitektur
- **`app/services/advisor/metrics.py` = satu sumber angka periode**, dipakai `/analytics/prediction`, KPI, grafik, aturan, bot, dan ringkasan.
- **Insight builder** di `app/services/advisor/`: aturan murni (tanpa DB). Struktur modul di `02-aturan.md` §14.
- **Endpoint:** `GET /advisor/dashboard`, lalu `GET /advisor/page/{…}`, `POST /advisor/plan`, `POST /advisor/execute`, `POST /advisor/dismiss` (`04-kontrak-api.md`).
- **Flag rilis:** AppSetting `advisor_v2_users` (daftar `user_id` atau `*`).
- **Cache:** Redis `advisor:{household_id}:{viewer_id}`, 60–120 detik; perubahan data oleh anggota mana pun menghapus semua kunci household itu.
- **Migrasi:** `envelopes.is_emergency` dengan backfill dari nama; dijalankan manual di VPS (checklist `AGENTS.md`).

## Yang dibereskan sepanjang development
1. "Aman per hari" punya ≥4 rumus (web prediction, bot, ringkasan harian/mingguan, aturan advisor).
2. Kartu Terpakai: persen dari semua amplop vs "Prediksi lewat" dari amplop belanja.
3. Arus kas menganggap tagihan sebagai belanja harian.
4. Income periode ini hanya pemasukan sendiri (`_income_totals` memfilter `user_id`) → "Belum dicatat" palsu di rumah tangga.
5. Bot crash di hari terakhir periode (`handle_limit_harian`, `handle_proyeksi`).
6. Bot "pengeluaran hari ini" menghitung belanja hari ini dua kali.
7. `reserved` di konteks advisor tidak mengurangi tagihan yang sudah dibayar.
8. Tautan ke `/allocate` mendarat di form tertutup.
9. `/analytics/daily-spending` ikut menghitung amplop pribadi anggota lain dan pembayaran tagihan.
10. Pengingat tagihan Telegram berulang tiap hari dan mengabaikan `subscription_due_tg`.
11. Kode & dokumen basi: `frontend/src/lib/advisorToday.js`, `docs/ai-advisor-review-2026-06-30.md`, bagian Advisor lama di `AGENTS.md`.
12. Kartu Jatah hari ini membandingkan dengan J1 (ikut turun saat belanja), seharusnya J0.
13. Kelompok amplop belum seragam (`debt` di Sisa bebas vs tidak di prediction). Disatukan: belanja = `expense` + `debt`.
14. Pembayaran tagihan manual: `reserved.py` vs `recurring_status.py` saling bertentangan → DAT-06 "Tandai lunas".
15. `transfer_between_envelopes` tanpa kunci → dikunci di S5.

## Metrik keberhasilan
- Klik CTA per tipe insight, rasio "Nanti"/sembunyikan, laporan "tidak relevan".
- Hari lewat jatah per periode, amplop minus di akhir periode, jumlah tambalan antar amplop, tagihan telat, ledger drift.
