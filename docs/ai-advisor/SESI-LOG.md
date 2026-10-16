# AI Advisor v2 — catatan serah-terima

Entri terbaru di atas. Format: **Sesi · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## S1 · 2026-10-16 · pemilik produk + Claude

**Selesai**
- `app/services/advisor/snapshot.py`: `load_snapshot(user, db, today=None)` → `Snapshot` (dataclass, tanpa ORM). 13 query tetap, tidak tumbuh per amplop (dikunci tes). Memuat amplop terlihat, pemasukan + alokasi + transfer rumah tangga 6 periode, transaksi 6 periode, langganan aktif, target, snapshot rollover, saldo sepanjang waktu amplop tabungan (G1), cocokkan saldo terakhir, transaksi terakhir viewer, nama anggota. Privasi ditegakkan di loader: deskripsi sudah disamarkan, alokasi ke amplop tak terlihat `envelope_id=None`.
- `app/services/advisor/metrics.py`: `compute_metrics(snapshot) -> Metrics` murni. M1–M13, T1–T11 (+T5b, `cukup_sampai`), P1–P6 (+`pemasukan_per_anggota_bersama` untuk INC-02 "Terisi dari {nama}"), G1–G8, K1–K4, `tagihan` (status per langganan: sisa, sisihan, telat_hari, lunas_oleh), `jenis_transaksi` (variabel/tagihan/outlier/penyesuaian), deret `harian` dengan J0 per hari. `Metrics.to_api()` = blok `metrics` di kontrak. Konstanta §11 di `Konstanta` (default; belum dibaca dari AppSetting).
- Migrasi `c5e9a2d7f4b1` `envelopes.is_emergency` + backfill nama. Field di `EnvelopeCreate` (opsional), `EnvelopeResponse`, `EnvelopeSummary`. Buat: `None` → ditebak dari nama; ubah: `None` → nilai lama; hanya tabungan (selain itu 400 bila diminta true, dilepas otomatis bila purpose pindah).
- Tes: `test_advisor_metrics.py` (51, termasuk angka persis §12 dan skenario 2, 3, 4, 5, 6, 8, 13, 14, 20) dan `test_advisor_snapshot_integration.py` (10, SQLite: skenario 7, jumlah query, route `is_emergency`). Fixture: `app/tests/advisor_v2_fixtures.py` (`SnapshotBuilder`, `contoh_15_okt()`).
- Checklist migrasi di `AGENTS.md`. `04-kontrak-api.md`: `harian` ditambah `outlier` dan `jatah`.

**Digantung (sengaja, sesi lain)**
- Belum ada pemakai: `/analytics/prediction`, bot, ringkasan, dan aturan v1 masih memakai rumus lama / `context.py`. Pemindahan di S3 (endpoint), S6 (frontend), S9 (bot & ringkasan).
- Preferensi notifikasi & status dismiss (Redis) belum masuk snapshot — S3/S16.
- `Konstanta` dari AppSetting — saat dibutuhkan (S3).

**Keputusan kecil (tertulis juga di docstring metrics.py)**
- Jendela laju = t−6..t (termasuk hari ini, sesuai §12). Bila d < 7, T4/M8 = variabel sejak ps ÷ d (jendela belum utuh).
- M8, T8, T9, T10 `None` bila d < 3. T4 tetap dihitung (grafik & laju7 selalu ada).
- `tanggal_habis` = t + ⌊T3 ÷ T4⌋ + 1 (hari pertama uang tidak cukup; §12 "habis 24 Okt"), `cukup_sampai` = tanpa +1.
- J0 dibatasi ≥ 0; Income penyesuaian (cocokkan saldo, gap positif) hari ini juga dikeluarkan dari J0 → invarian J0 berlaku untuk penyesuaian dua arah.
- M4: "🔄 X" hanya melunasi langganan X (next_run maju) dan tidak ikut kolam nominal-persis; tagihan telat dari periode lalu tidak dicocokkan (sama dengan `reserved.py`). Akibatnya bisa berbeda dari `reserved.py` di kasus dua langganan bernominal sama — `reserved.py` yang keliru; disatukan saat dashboard pindah ke metrics.
- M4 mingguan = kemunculan tersisa s/d pe × nominal (spesifikasi), bukan ×52/12 seperti `reserved.py`; tahunan hanya di M5.
- Outlier (S2) dihitung di metrics karena M7 bergantung padanya: median 90 hari s/d t, dana = M1 periode transaksi itu. `signals.py` (S2) memakai `jenis_transaksi`, jangan menghitung ulang.
- G8 hanya membaca flag `is_emergency` (bukan nama), supaya pilihan user dihormati setelah backfill.
- G5 tanpa tenggat memakai (target − saldo) ÷ 24 dengan `tanpa_tenggat=True`; G6 `None` bila setoran biasa 0.
- P3 hanya pemasukan viewer; P6 tidak menghitung transfer ke tabungan (bukan dari P1).

**Jebakan**
- Tes SQLite yang gagal di `asyncSetUp` menggantung selamanya bila engine tidak di-dispose (thread aiosqlite). Pakai `self.addAsyncCleanup(self.engine.dispose)` tepat setelah membuat engine.
- Model memetakan `is_emergency`: setiap `select(Envelope)` gagal di produksi sampai migrasi jalan. Merge hanya bila migrasi bisa dijalankan saat itu juga.
- `npm run build` mengubah `frontend/dist/index.html` yang ter-track; kembalikan dengan `git checkout -- frontend/dist/` sebelum commit.

**Baseline tes:** backend 643 OK · frontend 240 OK · build OK.

**Lanjut ke S2:** prompt pembuka §3 dengan SN = S2 (#57). `signals.py` membaca `Snapshot` + `Metrics` (`jenis_transaksi`, `harian[].lewat` = S6, `amplop[e].tambalan_n`, `tagihan`). Buat fixture dengan `SnapshotBuilder`.

---

## S0 · 2026-10-16 · pemilik produk + Claude

**Selesai**
- `docs/ai-advisor/` dibuat: 00-indeks, 01-desain, 02-aturan (revisi 1, disetujui), 03-workflow, 04-kontrak-api, PROGRESS, SESI-LOG.
- `AGENTS.md`: bagian "AI Advisor v2" (6 aturan kerja); bagian "Advisor Insights Engine" lama diperbarui (path `advisor.py` sudah jadi paket).
- CI tes baru `.github/workflows/test.yml`: unittest backend + `node --test` + build frontend di setiap PR dan push ke `main`. Deploy tetap di `deploy.yml`.
- `requirements-test.txt`: `slowapi`, `email-validator`, `aiosqlite` (dipakai app/tes tapi tidak tercantum di `requirements.txt`).
- Issue GitHub per sesi (S1–S19) + label `ai-advisor`, `migrasi`, `paralel` + milestone Fase 1–4.

**Jebakan**
- Di `main` per `31eb446`, 14 tes merah: `test_income_type_safe_daily` (13) dan `test_prediction_rollover` (1). Penyebabnya mock `db_with(...)` kurang satu hasil untuk query `_income_totals` yang ditambahkan ke `/analytics/prediction`. Sudah diperbaiki di tes saja (tanpa mengubah kode app). Mock berurutan seperti ini rapuh: sesi S1/S3 yang memindah prediction ke `metrics.py` sebaiknya menulis tes baru berbasis fixture snapshot, bukan menambah urutan mock.
- Tanpa `slowapi`/`email-validator` terpasang, 10 modul tes gagal import. Di VPS keduanya terpasang manual. Pasang dari `requirements-test.txt` untuk menjalankan tes lokal.
- Repo publik: nama anggota keluarga di contoh spesifikasi diganti fiktif ("Rina"). Jangan menaruh data user nyata di fixture atau dokumen.

**Baseline tes:** backend 582 tes OK · frontend 240 tes OK · build OK.

**Lanjut ke S1:** prompt pembuka di `03-workflow.md` §3 dengan SN = S1, issue "AI Advisor S1". Baca `02-aturan.md` §1, §3, §14 dan `app/services/advisor/context.py` (loader yang diperluas jadi `snapshot.py`).
