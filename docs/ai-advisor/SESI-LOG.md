# AI Advisor v2 — catatan serah-terima

Entri terbaru di atas. Format: **Sesi · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## S5 · 2026-10-16 · pemilik produk + Claude

**Selesai**
- `app/services/advisor/planner.py` (murni): `susun_rencana(snap, metrics, kebutuhan, kecuali, sertakan) -> Rencana` mengikuti §8 — urutan kebutuhan (telat/jatuh tempo → minus → habis+tagihan → lain), sumber sah (belanja, boleh diubah viewer, tidak terkunci, bukan tujuan, M4 = 0, surplus > 0), tingkat a/b/c, alokasi global, pembulatan Rp1.000 + penutup persis, centang default, `opsi_tabungan`. `saldo_versi`, `bebas_setelah_rencana`, `batas_harian_setelah_rencana`. Angka §12 "Rencana dana KPR" keluar persis (453.000 / 1.410.000 / 145.174).
- `metrics.py` (hanya tambahan): `belanja_sisa_riwayat` (median belanja variabel hari d s/d akhir, 3 periode lalu), `perkiraan_belanja_sisa`, `surplus_rencana`, `batas_harian`.
- `app/services/advisor/execute.py`: `build_plan`, `execute_plan` — `client_ref` (Redis `txnref:*`, hasil JSON disimpan), kunci household `FOR NO KEY UPDATE`, snapshot dihitung ulang di dalam kunci, 409 + `rencana_baru`, validasi ulang baris (terkunci / tak terlihat / > sisa / sumber = tujuan), transfer (`fund_shift.record_transfer`) + bayar tagihan (🔄, `next_run` maju, jendela bayar) dalam satu commit; notifikasi target sesudah commit.
- Route `POST /advisor/plan`, `POST /advisor/execute` (`routes/advisor.py`). `POST /envelopes/transfer` memakai kunci household yang sama (`lock_household`).
- Frontend kecil: `executeBody` mengirim balik `kebutuhan`/`kecuali`/`sertakan` dari respons plan (untuk `rencana_baru`). Server tetap bisa menurunkan kebutuhan dari `ke` bila tidak dikirim.
- Kontrak `04-kontrak-api.md`: bentuk lengkap plan/execute (field baru `ke`, `sertakan`, `opsi_tabungan`, gaung permintaan, tingkat d/e, semua respons error).
- Tes: `test_advisor_planner.py` (16: §12, skenario 10 & 18, kecuali, sertakan, c non-danger, alokasi global, tingkat b, d < 3, saldo_versi) dan `test_advisor_plan_integration.py` (8, SQLite: plan → execute satu commit, client_ref sekali, 409 tanpa tulis, baris diubah klien ditolak, tabungan bila dipilih, transfer manual dengan kunci).

**Digantung / untuk sesi lain**
- **S3:** `advisor_cache.invalidate(hid)` belum ada → panggil dari `execute_plan` (sesudah commit) dan `transfer_between_envelopes` saat S3 membuatnya. Teks `ALASAN` di `planner.py` dipindah ke `render.py` (aturan #2).
- **S3/S4:** aturan yang punya CTA batas harian memakai `batas_harian_setelah_rencana(m, rencana)` (penekanan 8) — rencana dihitung sekali per dashboard dari kebutuhan semua insight (§8.4 "satu sumber tidak dipakai dua kali").
- **S8/S11:** UI "Pakai tabungan" (`opsi_tabungan` → plan ulang dengan `sertakan`) belum ada; `PlanReview` baru menampilkan "Catat pemasukan".
- **Bot:** geser dana di bot (`fund_shift`) belum memakai kunci household; kalau perlu, ikut di S9.

**Keputusan kecil (juga di docstring planner.py / metrics.py)**
- Satu baris rencana per sumber (frontend mencentang per `dari_id`); rincian tujuan di `ke`.
- Sumber (c) tetap memakan surplus walau tidak tercentang (supaya sah bila dicentang); `kurang` hanya dari baris tercentang. Baris (c) yang dipakai kebutuhan danger dan non-danger: tercentang.
- `bayar` hanya diisi bila kebutuhannya tertutup penuh oleh baris tercentang.
- Tingkat (b) = kebutuhan dengan ≥ 1 dari 3 periode lalu punya transaksi di amplop itu; surplus memakai max(laju × r, median riwayat) × 1,1.
- d < 3 (laju belum ada): perkiraan belanja = median riwayat, atau jatah × r ÷ D dengan jatah = `budget_amount` bila diisi dan < dana (selain itu dana). Akibatnya amplop yang didanai pas jatah tidak jadi sumber di hari 1–2 — sengaja konservatif.
- Kapasitas tabungan (d/e) = sisa periode amplop (M3), sama dengan batas transfer manual, bukan saldo sepanjang waktu (G1).
- `saldo_versi` = sha256 dari hari ini + (sisa, bebas, M4, terkunci) tiap amplop terlihat + (jatuh tempo, sisa) tiap tagihan. Ganti hari = rencana basi (r berubah).
- Execute memvalidasi baris tercentang terhadap aturan transfer (bukan menuntut sama persis dengan rencana server), plus: tidak terkunci, sumber bukan tujuan.

**Jebakan**
- `with_for_update` di SQLite tidak menghasilkan SQL (tes integrasi tetap jalan); kunci sungguhan hanya teruji di Postgres produksi.
- Execute memakai `snap.today` (zona waktu user) untuk tanggal transaksi bayar, sedangkan `POST /recurring/{id}/pay` memakai `date.today()` server — sama kecuali sekitar tengah malam.

**Baseline tes:** backend 667 OK · frontend 251 OK · build OK.

**Cara mencoba:** login, lalu di konsol `window.dispatchEvent(new CustomEvent('jatahku:open-action', {detail: {kind: 'plan', payload: {kebutuhan: [{tujuan_id: '<amplop>', jumlah: 50000}]}}}))`.

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
