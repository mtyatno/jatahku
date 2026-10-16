# AI Advisor v2 — catatan serah-terima

Entri terbaru di atas. Format: **Sesi · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## S2 · 2026-10-16 · pemilik produk + Claude

**Selesai**
- `app/services/advisor/signals.py`: `compute_signals(snapshot, metrics) -> Signals`, fungsi murni. S1–S19 + S4b, masing-masing field list/dict di `Signals` (kosong/None = tidak menyala); `Signals.aktif()` → kode yang menyala. Konstanta §11 di `KonstantaSinyal`.
- Memakai yang sudah ada, tidak menghitung ulang: outlier dari `metrics.jenis_transaksi` (rumus `projection.py`), S6 dari `metrics.harian[].lewat`, S19 dari M13 (`amplop[e].dibayar_manual`, aturan nominal persis `reserved.py`), S3 dari `sinking.detect_interval` + `_amount_stability` + `_token_overlap`/`normalize_description`.
- `metrics.py` (hanya menambah): `Metrics.periode` dan `Metrics.riwayat[eid]` = `RiwayatAmplop` (dana, terpakai, variabel, alokasi_utama, tambalan_n per periode; terpakai s/d hari ini; terpakai periode lalu s/d hari ke-d). Dipakai S5, S8, S9, S17.
- `snapshot.py`: field `Snapshot.now` (UTC saat muat) untuk S14 "lebih dari 24 jam" tanpa jam sistem di signals.
- Tes `test_advisor_signals.py` (46): struk-rantai, dobel vs kembar (skenario 9 & 15), S4b, lonjakan, menganggur, pemasukan terlambat/lebih kecil (+ skenario 5), kronis, tren, tagihan berubah/ganda/manual, pola rutin, belum dijatah, lupa catat, non-rollover, gajian bergeser (termasuk masuk lebih awal), contoh §12 hanya S6.

**Digantung (sengaja, sesi lain)**
- Belum ada pemakai: aturan (S3/S4) yang membaca `Signals`. Teks penanda ("Struk {toko} sepertinya tercatat dua kali…") di `render.py` (S3/S13).
- `KonstantaSinyal` dari AppSetting — bersama `Konstanta` (S3).

**Keputusan kecil (tertulis juga di docstring signals.py)**
- S1/S4/S4b hanya periode berjalan. S1 hanya transaksi viewer. S4 hanya pasangan dari pencatat yang sama dan deskripsinya terlihat (dua "Transaksi privat" anggota lain tidak dibandingkan). S4 dikelompokkan: satu grup per transaksi asli, `hapus_saran` = kiriman berikutnya.
- S4b butuh rantai ≥ 2 barang; struk 1 barang terkirim dua kali → S4. Pasangan yang sudah tercakup S4b tidak dilaporkan lagi sebagai S4. Jendela 30 menit diukur dari akhir rantai pertama ke awal rantai kedua; porsi = pasangan identik ÷ jumlah barang rantai terbesar.
- S3: ≥ 2 tanggal, keyakinan interval ≥ medium, nominal exact/stable_range, kemunculan terakhir ≤ 2× interval yang lalu; cocok langganan aktif bila token ≥ 0,5 dan nominal ±15%.
- S5: median variabel per 7 hari = median (variabel periode × 7 ÷ D) dari ≤ 3 periode lalu yang punya dana/terpakai; butuh ≥ 2 periode. Nilai 7 hari ini = M12.
- S8/S9 butuh 3 periode lalu beraktivitas. "Median alokasi" = alokasi positif dari pemasukan sungguhan (tanpa transfer/penyesuaian). S9 juga batal bila periode ini sudah ditambal.
- S12/S13/S18 hanya Jenis Pendapatan bulanan. S15 harfiah: hari mencatat dalam t−13..t. S17 tidak membandingkan bila periode lalu terpakai 0. S18 memakai selisih ke awal periode terdekat (gaji masuk lebih awal = selisih negatif).

**Jebakan**
- `riwayat[].variabel` periode lalu memakai `jenis_transaksi`, yang outlier-nya diukur dengan median 90 hari s/d **hari ini** (bukan s/d periode itu). Untuk S5 cukup; jangan dipakai untuk menampilkan "variabel periode lalu" ke user tanpa catatan.
- `harian[].lewat` di contoh §12 menyala untuk beberapa hari, bukan hanya hari ini — benar, karena J0 per hari dihitung dari saldo awal hari itu.

**Baseline tes:** backend 689 OK · frontend 250 OK · build OK.

**Lanjut ke S3:** prompt pembuka §3 dengan SN = S3 (#58). Aturan HAR-*/PER-* membaca `Metrics` + `Signals` (`compute_signals(snap, compute_metrics(snap))`); HAR-03 dari `signals.outlier` (`hari_ini`), DAT-03 dari `dobel`/`struk_dobel`.

---

## S8 · 2026-10-16 · Claude

**Selesai**
- `lib/advisorAction.js` (+ tes): `normalizeAction` (string lama tetap jalan, objek `{kind, payload}`), `safeRoute`, parser query `/transactions` & `/allocate`, prefill income/langganan/chat, helper lembar rencana (`executeBody`, `toggleRow`, `newClientRef`).
- `Layout.jsx`: satu penerima `jatahku:open-action` untuk semua kind di `04-kontrak-api.md` §"Aksi CTA di frontend"; toast kecil untuk hasil dismiss/hapus. `QuickAddIncome` prefill + `jatahku:txn-added` setelah simpan (sebelumnya tidak menembak event).
- `PlanSheet.jsx` (baru): `PlanReview` + modal. `FundEnvelopeModal` prop `advisor` (dibuka lewat kind `fund`) memakai `PlanReview` multi-sumber.
- `PaySubscriptions` fokus satu langganan + mode `mark_paid`; `RecurringModal` prop `prefill`; `ChatPanel` prop `draft` (teks + chip).
- `/transactions?date=&envelope=` dan `/allocate?new=1&amount=&source=` reaktif ke URL (juga saat halaman sudah terbuka); tanggal memilih periode yang memuatnya, chip tanggal bisa dihapus; form alokasi digulir ke layar.
- `api.js`: `advisorPlan(kebutuhan, kecuali)`, `advisorExecute`, `advisorDismiss`, `markRecurringPaid`, `updateEnvelopeFields` (generalisasi `updateEnvelopeClassification`).
- Kontrak: kind baru `fund`, field opsional `kecuali` di `POST /advisor/plan`, tabel payload per kind.

**Digantung / untuk sesi lain**
- **S5:** implementasikan `kecuali` (daftar `dari_id` yang dilepas user) di `POST /advisor/plan`, dan kembalikan 409 dengan `rencana_baru` (frontend membaca `data.rencana_baru` atau `data.detail.rencana_baru`). Sampai S5 live, `plan`/`fund` menampilkan "Rencana dana belum tersedia" (404).
- **S4:** `POST /recurring/{id}/mark-paid`; sampai itu, Tandai lunas menampilkan "belum tersedia".
- **S3/S7:** `POST /advisor/dismiss`; kartu bisa mendengarkan `jatahku:advisor-dismissed` untuk menyembunyikan item.
- Pemanggil lama `FundEnvelopeModal` (QuickAddTransaction, MultiAddTransaction, SpendingEnvelopes) masih transfer satu sumber langsung. Setelah S5 live, pindahkan ke `advisor` (aturan kerja #5) — S11.
- Tidak ada UI baru yang terlihat tanpa CTA advisor; jadi tidak perlu flag. Perubahan yang terlihat user lama: chip tanggal di Transaksi (hanya bila ada `?date=`), event `txn-added` setelah income dari FAB.

**Jebakan**
- `PlanReview` memuat ulang rencana setiap identitas array `kebutuhan` berubah — pemanggil wajib menyimpannya di state/`useMemo`.
- Uji browser butuh user dengan `telegram_id`, kalau tidak modal TelegramPrompt menutupi semuanya.

**Tes:** `node --test src/lib/*.test.js` 250 OK (10 baru) · build OK · uji Playwright dengan API di-mock untuk setiap kind (skrip tidak di-commit).

**Cara mencoba:** di konsol browser, `window.dispatchEvent(new CustomEvent('jatahku:open-action', {detail: {kind: 'pay', payload: {recurring_id: '<id>'}}}))`, atau kind lain dari tabel di `04-kontrak-api.md`.

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
