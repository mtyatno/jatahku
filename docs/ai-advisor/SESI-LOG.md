# AI Advisor v2 — catatan serah-terima

Entri terbaru di atas. Format: **Sesi · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## S15 Halaman Analitik · 2026-10-17 · pemilik produk + Claude

**Selesai**
- `app/services/advisor/page_analitik.py` (baru, pola S13): `GET /advisor/page/analitik` → `{enabled, generated_at, period_start, period_end, hari_ini, ringkasan, harian, grafik}`. Mesin sama dengan Beranda (`dashboard.analisa`).
- Ringkasan ≤ 3 poin (§7 "Analitik"):
  - satu terbaik per kelompok: periode (PER-03/04), amplop (AMP-08/11), hari terboros (S6), tabungan (TAB-06);
  - urut tone lalu urutan kelompok; kurang dari 3 → AMP-08/11 amplop lain mengisi;
  - insight yang di-dismiss tidak tampil.
- Poin hari terboros (`render.poin_hari_terboros`, `page_analitik.hari_terboros`): belanja variabel tertinggi periode ini dari `metrics.harian` vs J0 hari itu + jumlah hari lewat jatah (`signals.lewat_jatah`). warn bila ≥ 3 hari lewat, info bila lewat, ok bila semua dalam jatah. CTA `route` ke `/transactions?date=`. Bukan aturan → `dismiss: null`.
- Slot `analitik` ditambahkan ke PER-03, PER-04 (`rules/periode.py`) dan TAB-06 (`rules/tabungan.py`), atas izin pemilik produk. AMP-08/11 sudah punya slot ini.
- `harian` + `grafik` = deret metrik + baris analisa Beranda (dites identik). Analytics.jsx periode berjalan (flag) memakai `DailySpendingChart` mode advisor (komponen S6, tidak diubah) dan heatmap dari belanja variabel yang sama.
- `/analytics/daily-spending`: filter pemilik (bersama + pribadi milik viewer), sama dengan endpoint analytics lain. Berlaku untuk semua user (perbaikan privasi), dipakai jalur lama/periode lama.
- `sinking.py`: `actions[]` memakai kind pipa CTA S8: `make_recurring` (mingguan/bulanan/tahunan), `route` /langganan (adjust), `route` /transactions?envelope= (review, triwulanan/semesteran) + `dismiss` `SNK:<id>` (tidak_relevan, 90 hari). Rekomendasi yang di-dismiss disaring di server. Frontend menampilkan tombolnya hanya untuk user di flag.
- Frontend: `api.getAdvisorAnalitik()`, `lib/analyticsAdvice.js` (+ tes), kartu "Ringkasan AI" menggantikan kotak "Insight" (flag + periode berjalan). Halaman memuat ulang pada `txn-added`, `envelope-updated`, `advisor-dismissed`, `advisor-undismissed`.
- Dokumen: `04-kontrak-api.md`, `03-workflow.md` §7 (baris kepemilikan S15), `AGENTS.md` peta v2, `00-indeks.md`.

**Digantung**
- `analyticsInsight.js` (`busiestWeekday`, `categoryDelta`, `buildWeekHeatmap`) tetap dipakai: jalur lama (flag mati / periode lama), heatmap dan kartu "Naik vs turun". Hapus `busiestWeekday` + kotak Insight lama di S10b.
- Kartu "Prediksi akhir bulan", "Cash Flow", dan garis batas aman lama masih membaca `/analytics/prediction`; belum dipindah ke metrik (di luar scope issue; usul issue terpisah bila perlu).
- Uji di produksi dengan akun tim belum dilakukan.
- Temuan di luar scope: `STRIP_STYLE.info` di `Envelopes.jsx` memakai `bg-blue-50` yang tidak punya padanan mode gelap → teks strip info hampir tak terbaca di tema gelap. Perlu issue terpisah (file S11).

**Keputusan kecil**
- PER-01 tidak masuk ringkasan walau menyala: §7 menyebut sumber persis, dan PER-01 sudah di Beranda.
- Ringkasan boleh kurang dari 3 poin (tidak diisi poin ok buatan); kosong → "Belum cukup data untuk ringkasan periode ini."
- Ringkasan & grafik v2 hanya untuk periode berjalan (metrik hanya ada untuk periode berjalan); periode lama tetap jalur lama.
- Tone info di kartu memakai `bg-gray-50` (ada padanan gelap), bukan `bg-blue-50`.
- Analytics: muat ulang karena event tidak menampilkan "Loading..." (data lama tetap tampil); respons basi diabaikan.

**Jebakan**
- Build produksi memanggil `https://api.jatahku.com`, jadi `page.route('**/api/**')` hanya berfungsi di `npx vite` (dev), bukan `vite preview`.
- Matikan server dengan `kill $(pgrep -f 'vite --port 417[9]')`: kurung siku mencegah pola cocok dengan shell pemanggil (jebakan `pkill` S11).
- `npm run build` mengubah `frontend/dist/index.html`; kembalikan sebelum commit.

**Tes:** backend 923 OK (17 baru, `test_advisor_page_analitik.py`) · frontend 289 OK (5 baru, `analyticsAdvice.test.js`) · build OK · Playwright (API di-mock, mode gelap): Ringkasan AI 3 poin dengan tombol + Nanti, grafik deret metrik, tombol "Jadikan langganan"/"Abaikan" di Sinking fund advisor.

**Cara mencoba:** user di flag → Analitik (periode berjalan) → kartu "Ringkasan AI", grafik Pengeluaran harian sama dengan Beranda, Sinking fund advisor → **Jadikan langganan** membuka modal Langganan terisi. Server: `python -m unittest app.tests.test_advisor_page_analitik -v`.

**Lanjut:** review PR (tanpa migrasi), merge, cek di produksi dengan akun tim; buka issue untuk `bg-blue-50` di strip Amplop. Sesi berikutnya: S16/S17 (prompt pembuka §3).

---

## S11 Halaman Amplop · 2026-10-17 · pemilik produk + Claude

**Selesai**
- `app/services/advisor/halaman.py` (baru): `GET /advisor/page/amplop` → `{enabled, generated_at, amplop: {envelope_id: insight | baris dasar | null}}`. Mesin sama dengan Beranda (`dashboard.analisa`: rencana bersama, skor, keyakinan, dismiss viewer); modul ini hanya memilih per kartu. Calon = slot `amplop` + `amplop_id` itu, domain AMP/TAG, TAB hanya untuk amplop tabungan; urut `kunci_urut` (tone dulu, skor).
- `render.baris_dasar_amplop`: kartu tanpa insight → belanja "Aman, ±{rp}/hari tersedia" (hari terakhir: "Aman, {rp} tersedia hari ini"), "Dana {amplop} sudah terpakai semua" + `fund` "Isi dana" (bebas ≤ 0 tanpa aturan, mis. d < 3), tabungan "{amplop}: saldo {rp}" + `fund` "Setor" ("Tambahkan target biar terarah." bila tanpa target).
- Route `GET /advisor/page/amplop` di `routes/advisor.py`; `api.getAdvisorAmplop()` (seragam dengan `getAdvisorLangganan`/`getAdvisorTransaksi` S12/S13).
- `Envelopes.jsx`: strip v2 (`AdvisorStripV2`: judul, isi, maks 2 tombol open-action, "Nanti" bila bisa di-dismiss) menggantikan `envelopeInsight` untuk user di flag; halaman memuat ulang pada `txn-added`, `envelope-updated`, `advisor-dismissed`, `advisor-undismissed`. Pembantu murni `lib/envelopeStrip.js` (+ tes).
- Toggle **Dana darurat** di form amplop (langkah target, hanya tabungan): nilai awal = `is_emergency` tersimpan; amplop baru = tebakan nama (sama dengan `metrics.is_emergency_name`), dikirim `null` supaya server yang menebak.
- CTA: Naikkan/Turunkan jatah (AMP-04/05/06 `raise_budget`), Geser dana (AMP-02/03 `plan`), Setor (TAB-* `plan`, baris dasar `fund`), Atur target (tombol "Buat target" yang sudah ada + TAB-02 "Mundurkan tenggat"). Pasang limit (`daily_limit`) tetap ikut `cta_batas_harian` = false (§2) — belum tampil.
- Pemanggil lama `FundEnvelopeModal` (QuickAddTransaction, MultiAddTransaction, SpendingEnvelopes — file S8, disetujui pemilik produk) kini memakai mode `advisor`: tab Geser = rencana multi-sumber `/advisor/plan` → `/advisor/execute` (aturan kerja #5), tab Top-up tidak berubah. Bentuk `onSuccess` sama, jadi pemanggil hanya menambah prop.
- Dokumen: `04-kontrak-api.md` (endpoint), `03-workflow.md` §7 (baris kepemilikan S11), `AGENTS.md` peta v2, `00-indeks.md`.

**Digantung**
- `envelopeInsight.js` + tesnya masih ada sebagai jalur flag-mati; hapus di S10b bersama jalur lama lain.
- Tombol "Geser dana" bawaan kartu (TransferModal satu sumber) tetap ada; strip v2 memakai `plan`/`fund`.

**Keputusan kecil (juga di docstring halaman.py)**
- Insight yang diserap insight lain di amplop yang sama (AMP-01 oleh TAG-01/02) tidak dipilih; yang diserap insight tingkat periode (AMP-02/03 oleh PER-01, AMP-01 oleh PER-02) tetap tampil di kartunya — PER-* tidak punya slot amplop. Jadi Beranda bisa menampilkan PER-01 sementara kartu Makan menampilkan AMP-03 (contoh §12: "maksimal Rp153 rb/hari").
- Semua calon kartu di-dismiss → `null` (tanpa strip), bukan "Aman": masalahnya masih ada.
- "Maksimal/hari" baris aman = `ctx.batas` (bebas_setelah_rencana, penekanan 8), sama dengan chip; cadangan `batas_harian(bebas)`.
- Tanpa cache Redis (13 query tetap per muat halaman); bila lambat, pakai kunci cache per halaman di `advisor_cache`.
- Strip tetap disembunyikan untuk amplop belum didanai (kotak "Belum ada dana · Alokasikan" lama tetap).

**Jebakan**
- `npm run build` mengubah `frontend/dist/index.html`; kembalikan sebelum commit.
- `pkill -f <pola>` ikut membunuh shell pemanggil bila pola itu ada di baris perintahnya (termasuk isi heredoc) → exit 144. Matikan server di perintah terpisah.
- Mock Playwright Beranda: `/analytics/periods` harus array berisi `period_start`; endpoint lain yang di-`filter` harus array.
- Tes lokal butuh `pip install -r requirements.txt -r requirements-test.txt` (container baru tidak punya `pydantic_settings`).
- Uji browser: Playwright global di `/opt/node-tools/node_modules/playwright`, API di-mock lewat `page.route('**/api/**')`, `localStorage.jatahku_token` + `telegram_id` di `/auth/me`.

**Merge dengan S12/S13/S14 (#94, #95, #98):** `halaman.py` dibuat dua sesi sekaligus → digabung: bagian Amplop (S11) di atas, Langganan (S12) di bawah, impor dashboard jadi di tingkat modul (isi `get_page_langganan` tidak berubah). Route `/page/amplop`, `/page/transaksi`, `/page/langganan` berdampingan. S14 (Alokasi) tidak menyentuh berkas S11.

**Tes (sesudah merge main #98):** backend 906 OK (12 baru, `test_advisor_page_amplop.py`) · frontend 284 OK (7 baru, `envelopeStrip.test.js`) · build OK · Playwright (API di-mock): strip warn/danger/ok dengan tombol aksi tampil di kartu; Beranda → kartu Amplop pengeluaran → Tutup minus membuka rencana `/advisor/plan` (Hobi → Makan).

**Cara mencoba:** user di flag → halaman Amplop → buka kartu: strip AI + tombol (Geser/Bayar/Setor). Server: `python -m unittest app.tests.test_advisor_page_amplop -v`.

**Lanjut:** S15 Halaman Analitik (#70) — prompt pembuka §3. Halaman baru: tambah `susun_<halaman>` di `halaman.py` (pola S11/S12) atau modul sendiri (pola S13 `page_transaksi.py`).

---

## S14 · 2026-10-17 · pemilik produk + Claude

**Selesai**
- `allocation.py`: rekomendasi tetap dari `allocate_income_to_targets`, disesuaikan aturan v2 (`sesuaikan_dengan_aturan`, murni):
  - AMP-01 → minimum ≥ minus;
  - AMP-04/05 → target ≥ saran;
  - AMP-06 → target turun ke saran (sisanya ke amplop penerima sisa);
  - TAG-04 → minimum ≥ sisihan/bulan;
  - TAB-02 → minimum ≥ kurang periode ini, kecuali `tunda` (penekanan 7).
  - Amplop yang jadi punya minimum naik ke prioritas 10.
- Respons `POST /advisor/allocation-recommendation` ditambah: `items[].alasan` (`render.alasan_alokasi`), `items[].keyakinan` (`confidence.py` per amplop), `sisa_ke`, `banner`. Field lama tetap.
- `GET /advisor/page/alokasi` (baru): banner INC-04/INC-03 (yang disembunyikan tidak tampil) + `sisa_ke`.
- Minimum satu tingkat prioritas yang tak tertutup income dibagi proporsional (bulat Rp100, sisa pembulatan ke minimum terbesar), lalu berhenti.
- Frontend:
  - `lib/allocationAdvice.js` (+ tes);
  - `Allocate.jsx`: banner di atas form (CTA ke `/allocate` dibuka di tempat), alasan + keyakinan per amplop, `?new=1&amount=` langsung menghitung dan menerapkan rekomendasi;
  - `QuickAddIncome` (Layout.jsx) "Bagi otomatis" = rekomendasi yang sama.
  - Pencocokan nama "Tabungan" di `Layout.jsx`/`Allocate.jsx` diganti `sisa_ke.envelope_id`.
- `04-kontrak-api.md`: endpoint & field baru.

**Digantung**
- `routes/incomes.py` masih mencari amplop sisa dengan nama "Tabungan" (`_get_or_create_tabungan`); `sisa_ke` meniru aturan itu di satu tempat (`allocation.SISA_KE`). Bila aturan sisa diubah (mis. ke `purpose='saving'` / `is_emergency`), ubah keduanya — perlu issue terpisah (di luar kepemilikan S14).
- `categoryColor('Tabungan')` di Allocate.jsx mencocokkan label kategori distribusi dari backend, bukan nama amplop — dibiarkan.
- "Bagi proporsional" (per `budget_amount`) di Allocate tetap ada sebagai pilihan manual.
- Uji di produksi dengan akun tim belum dilakukan.

**Keputusan kecil**
- Alasan v2 hanya dari insight yang tidak disembunyikan viewer (sama dengan Beranda).
- Analisa v2 di alokasi mengikuti flag `advisor_v2_users`. Bila gagal, dicatat di log lalu jatuh ke rekomendasi lama tanpa alasan.
- "Bagi otomatis" sebelumnya membagi proporsional terhadap kebutuhan (target) di frontend. Sekarang mengikuti backend: minimum dulu (proporsional bila kurang), lalu target per prioritas. Income kecil/harian tetap terbagi ke amplop kebutuhan (minimum = 0,6 × median), bukan ke satu amplop.
- Keyakinan per amplop memakai kosakata lama `high/medium/low` supaya `confidenceCopy.js` tetap dipakai.

**Jebakan**
- `analisa_alokasi` memuat snapshot penuh setiap kali rekomendasi diminta (tanpa cache); cukup cepat (target 150 ms), tapi jangan dipanggil per ketikan.
- Tes yang memanggil `build_allocation_recommendation` dengan `db=None` tanpa mem-patch `analisa_alokasi` akan mencetak traceback log (lalu jatuh ke jalur lama) — patch `analisa_alokasi` seperti di `test_advisor_alokasi_v2.py`.
- Sesi ini merge `origin/main` (#96) di tengah jalan; konflik hanya di `04-kontrak-api.md` (baris 503 #91 + blok S14).

**Tes:** backend 870 OK (13 baru) · frontend 267 OK (5 baru) · build OK · uji Playwright halaman Alokasi dengan API tiruan (banner → form terisi → rekomendasi diterapkan → alasan + keyakinan; skrip tidak di-commit).

**Cara mencoba:** Beranda (flag aktif) dengan pemasukan yang belum dibagi > 24 jam → buka Alokasi → banner "Bagi Rp… ke amplop" → **Bagi sekarang**. Atau FAB → Pemasukan → isi jumlah → **Bagi otomatis**.

**Lanjut:** review PR, merge (tanpa migrasi), cek di produksi dengan akun tim; buka issue untuk aturan amplop sisa di `incomes.py`.

---

## S13 · 2026-10-17 · pemilik produk + Claude

**Selesai (PR ini)**
- `GET /advisor/page/transaksi?tanggal=&amplop=` (`app/services/advisor/page_transaksi.py`, route di `routes/advisor.py`; kontrak di `04-kontrak-api.md`).
  - **Banner** mengikuti filter aktif. Filter amplop → AMP-* amplop itu (tone dulu, lalu skor). Kalau tidak, tanggal = hari ini → isi chip KPI Jatah (HAR-*, sama dengan Beranda). Selain itu null.
  - **Penanda baris** = insight ber-slot `transaksi`, dipetakan ke id transaksi:
    - HAR-03 / DAT-06 / TAG-06 → `txn_id`;
    - DAT-03 dobel → kedua anggota pasangan;
    - DAT-03 struk dua kali → barang di struk kedua;
    - TAG-07 → kemunculan terakhir.
  - Dismiss viewer dihormati. Di luar flag → `{"enabled": false}`.
- Frontend:
  - `api.getAdvisorTransaksi`;
  - `lib/transaksiAdvisor.js` (query dari filter, penyaringan yang baru disembunyikan, CTA maks 2 tanpa rute ke halaman yang sama);
  - `components/TxnAdvisor.jsx` (banner + chip penanda memakai `AdvisorChip`/`InsightPopover` S6);
  - `Transactions.jsx` memuat ulang saat filter berubah, `txn-added`, dan `advisor-undismissed`, serta langsung menyembunyikan pada `advisor-dismissed`.
- Aksi Hapus salah satu / Hapus duplikat / Bukan dobel / Jadikan langganan / Tandai lunas memakai pipa CTA S8 yang sudah ada (tidak ada kind baru).

**Digantung**
- #93: "Bukan dobel" belum permanen (sekarang `tidak_relevan` = 90 hari). Spesifikasi §6G meminta permanen.
- Belum dicoba di browser dengan data sungguhan. Hanya tes unit/integrasi + build. Cek visual di produksi dengan akun tim setelah merge (flag `*` sudah aktif).
- Endpoint tanpa cache server: dihitung ulang tiap muat halaman/ganti filter. Bila lambat (> 150 ms) pertimbangkan cache per (household, viewer, filter) di `advisor_cache`.

**Keputusan kecil**
- Filter amplop menang atas filter hari ini bila keduanya aktif (lebih sempit). Tanggal selain hari ini → tanpa banner (HAR-* hanya untuk hari ini).
- Tab "Hari Ini" dianggap sama dengan filter tanggal hari ini. Tanggal dari browser (`localDateStr`); bila beda dengan hari server di sekitar tengah malam, banner kosong (bukan salah angka).
- TAG-06 (nominal tagihan berubah) ikut tampil sebagai penanda karena slotnya sudah `transaksi` sejak S4.
- TAG-07 hanya menandai kemunculan terakhir supaya daftar tidak penuh chip "Pola rutin".
- AMP-01 yang diserap PER-02 di Beranda tetap boleh jadi banner amplop (penyerapan hanya berlaku untuk daftar Beranda).

**Jebakan**
- Tes backend butuh `pip install -r requirements-test.txt` + env `DATABASE_URL`/`JWT_SECRET` (lihat `test.yml`). Tanpa itu, 53 modul gagal impor.
- `npm run build` butuh `npm ci` dulu dan mengubah `frontend/dist/index.html`; kembalikan sebelum commit.

**Tes:** backend 868 OK (13 baru) · frontend 267 OK (5 baru) · build OK.

**Cara mencoba:** Transaksi → tab **Hari Ini** (banner HAR-*) atau pilih satu amplop (banner AMP-*). Catat dua transaksi sama (mis. "belanja pasar 150k") berjarak < 10 menit → chip **Dobel?** di kedua baris → Hapus salah satu / Bukan dobel (toast + Urungkan). Lokal: `python -m unittest app.tests.test_advisor_page_transaksi -v`; `cd frontend && node --test src/lib/transaksiAdvisor.test.js`.

**Lanjut:** review PR, merge, cek visual di produksi. Kerjakan #93 sebagai PR kecil terpisah. Sesi berikutnya yang bebas: S11, S14, S15 (prompt pembuka §3).

---

## S12 · 2026-10-17 · pemilik produk + Claude

**Selesai**
- `GET /advisor/page/langganan` (`app/services/advisor/halaman.py`, route di `routes/advisor.py`): satu analisa yang sama dengan Beranda (`dashboard.analisa`), lalu dipilah:
  - `per_langganan` = satu insight terbaik per baris (TAG-01/02/03/04/06, DAT-06);
  - `ringkasan` = K4 (`beban_bulanan`, `beban_persen`, `dana_belanja`, `tagihan_sisa`, belum/lunas) + insight TAG-05 (bila menyala) atau TAG-09;
  - `pola` = TAG-07 (Jadikan langganan), `lain` = TAG-08 dengan `recurring_ids`, `disembunyikan`.
- `metrics.py`: field baru `beban_tagihan_bulanan` (pembilang K4 yang sudah dihitung; rumus tidak berubah).
- Frontend: `api.getAdvisorLangganan`, `lib/advisorLangganan.js` (+ tes), `components/AdvisorRowStrip.jsx` (strip AI per baris: judul, Rincian, CTA, pilihan sembunyikan), `pages/Langganan.jsx`: kartu AI Advisor di atas daftar + strip per baris. Tandai lunas (`mark_paid`), Geser & bayar (`plan`), Bayar (`pay`), Jadikan langganan (`make_recurring`) lewat pipa CTA S8. Tanpa flag → halaman lama persis.
- `04-kontrak-api.md`: bentuk `/advisor/page/langganan`.

**Digantung**
- Belum dicoba di browser dengan data produksi (lingkungan sesi tanpa Postgres). Coba dengan akun tim setelah deploy.
- TAG-06 "Perbarui nominal" membuka form edit tanpa nominal baru terisi (payload `route` tidak membawa jumlah). Kalau perlu: kind `edit_recurring` dengan `{recurring_id, jumlah}` — menyentuh `rules/tagihan.py` (S4) dan pipa S8.
- S11 (`/advisor/page/amplop`) bisa memakai `halaman.py` + `AdvisorRowStrip` yang sama.

**Jebakan**
- `frontend/dist/index.html` ter-track dan berubah tiap `npm run build` — jangan ikut di-commit.
- `RecurringTransaction` tidak punya `user_id` (fixture integrasi).
- Lingkungan cloud baru: `pip install -r requirements-test.txt` dan `npm ci` dulu sebelum tes.

**Keputusan kecil**
- Tanpa cache Redis untuk halaman ini (jarang dibuka; entri cache Beranda per viewer tidak boleh tertimpa). Dismiss dari halaman ini tetap memakai `POST /advisor/dismiss` yang sama (meta dihitung ulang bila cache Beranda kosong).
- CTA `route` ke `/langganan` di halaman ini dipetakan lokal: baris → form edit (TAG-04 Atur sisihan, TAG-06), TAG-08 → saring ke dua langganan + "Tampilkan semua", TAG-05 → urut termahal.
- Baris ringkasan "Tagihan rutin {rp}/bulan · {x}% dari dana belanja" adalah label angka di frontend (angka dari server), bukan teks insight; insight-nya tetap TAG-05/TAG-09 dari `render.py`.
- Menyentuh file milik sesi lain dengan izin pemilik produk: `Langganan.jsx` (S8), `routes/advisor.py` (S3), `metrics.py` (S1, hanya field baru).

**Tes:** backend 866 OK (11 baru) · frontend 267 OK (5 baru) · build OK.

**Cara mencoba:** user di flag → `/langganan`. Tagihan telat/jatuh tempo ≤ 3 hari → strip di barisnya dengan Geser & bayar / Bayar; transaksi manual senilai tagihan → Tandai lunas; pola rutin 3+ periode → "Jadikan langganan" di kartu AI Advisor atas. API: `GET /advisor/page/langganan`.

**Lanjut:** `git fetch && git checkout ai-advisor/s12-langganan` · `python -m unittest app.tests.test_advisor_halaman_langganan -v`

---

## #91 Urungkan sembunyikan + S10 lanjutan · 2026-10-17 · pemilik produk + Claude

**Selesai (#91)**
- `DELETE /advisor/dismiss?kunci=` (204, idempoten): `advisor_cache.hapus_dismiss` + `dashboard.batal_dismiss` (hapus cache dashboard viewer). Hanya dismiss milik viewer sendiri.
- `GET /advisor/dashboard` → `advisor.disembunyikan` = `[{kunci, judul_pendek, pilihan}]` dari `sel.disembunyikan` (insight yang menyala tapi di-dismiss, daftar maupun chip KPI), urut `kunci_urut`.
- Frontend:
  - toast setelah dismiss ("Disembunyikan sampai besok 05.00" / "… akhir periode" / "Ditandai tidak relevan" / "Ditandai bukan dobel") dengan tombol **Urungkan** (6 detik);
  - kind baru `undismiss`;
  - event `jatahku:advisor-undismissed` (Beranda memuat ulang, kartu langsung memperbarui);
  - kartu AI Advisor: "N disembunyikan · Tampilkan" → judul pendek + sampai kapan + **Munculkan lagi**.
- Spesifikasi: `02-aturan.md` §9 (aturan Urungkan / Munculkan lagi), `04-kontrak-api.md` (endpoint, field, kind). `03-workflow.md` §7: baris S16 & S17 diberi catatan **cek #91**.

**Selesai (S10 lanjutan, di luar PR #86)**
- **Insiden 17 Okt:** migrasi `a9c3e7d1f5b2` + `c5e9a2d7f4b1` belum jalan di produksi → setiap query amplop 500 (`envelopes.is_emergency`). Ditemukan oleh `advisor_paritas` (crash 95/95). `alembic upgrade head` + restart; cek ulang: ok 54 · beda 0 · crash 0 · lewati 41.
- **Deploy:** `/opt/jatahku/deploy.sh` ternyata salinan 4 Okt (perubahan repo sejak 5 Okt tidak pernah jalan).
  - #87: cek migrasi (exit 2 bila tertinggal).
  - #88: repo disamakan dengan VPS — blog rsync dari CI, landing dari repo, webhook diperbaiki.
  - Symlink `/opt/jatahku/deploy.sh → app/deploy.sh`.
  - #89: mode 100755.
  - #90: `sudo git reset` di workflow dihapus.
  - Deploy #365 hijau lewat symlink.
- Uji akun tim (langkah 3) lolos: Beranda, chat `sisa`, Telegram `/status`, perubahan angka setelah transaksi tes. Flag `*` dinyalakan 17 Okt 11:39 WIB; log bersih sejak itu (pantauan 24 jam berjalan).

**Digantung**
- S10: cek ringkasan harian malam 17 Okt + paritas pagi 18 Okt, lalu **S10b** (hapus jalur lama, tutup #65).
- #91 belum mengubah chat/Telegram (tidak ada tombol sembunyikan di sana). **S16/S17 wajib cek #91** (catatan di 03-workflow §7).

**Jebakan**
- `journalctl --since` memakai jam server (UTC), bukan WIB, dan tidak menerima akhiran `Asia/Jakarta`. Konversi dulu: `date -u -d 'TZ="Asia/Jakarta" 2026-10-17 11:39' '+%F %T'`.
- `chmod` manual pada file ter-track di VPS membuat `git pull` di `deploy.sh` gagal. Mode file diatur lewat git (`git update-index --chmod=+x`).
- Peringatan `(trapped) error reading bcrypt version` di log = passlib vs bcrypt baru, tidak berbahaya.

**Tes:** backend 855 OK (2 baru) · frontend 262 OK (2 baru) · build OK.

**Cara mencoba:** Beranda (flag aktif) → chip KPI → Sembunyikan → toast **Urungkan**; atau kartu AI Advisor → Nanti → "1 disembunyikan · Tampilkan" → **Munculkan lagi**.

---

## S10 · 2026-10-17 · pemilik produk + Claude

**Selesai (PR ini)**
- `app/scripts/advisor_paritas.py` (baru): cek read-only sebelum melebarkan flag. Untuk tiap user (flag diabaikan, tidak menulis DB/cache): Beranda (`dashboard._hitung`) vs chat "sisa", `/status`, ringkasan harian (`chat.muat`) — baris Dana belanja, Sisa bebas, Jatah hari ini · belanja harus sama; nama amplop pribadi anggota lain tidak boleh muncul di payload maupun teks (skenario 7); crash ditangkap per user; waktu hitung dibandingkan target 150 ms. Kode keluar 1 bila ada `beda`/`crash`. Tes: `test_advisor_paritas_script.py` (7, SQLite).
- `docs/ai-advisor/05-verifikasi-rilis.md` (baru): cara menyetel flag (konsol browser / psql — tidak ada UI Admin), rollback, langkah 1–5 (deploy, cek paritas semua user, uji akun tim di Beranda/chat/Telegram/ringkasan, nyalakan `*`, pantau log 24 jam), daftar penghapusan jalur lama, tabel Catatan uji.
- `AGENTS.md`: bagian v1 ditulis ulang (hanya untuk user di luar flag, jangan menambah aturan v1, mana yang tetap dipakai); bagian v2 + peta modul v2 dan aturan flag (`advisor_v2_users`, `advisor_konstanta`, cek paritas sebelum melebarkan flag).
- Arsip: `docs/ai-advisor-review-2026-06-30.md` → `docs/arsip/` dengan catatan "jangan dipakai sebagai acuan kerja".
- `PROGRESS.md`: S0–S7, S9 → selesai (semua sudah di `main`); S10 → review. `00-indeks.md`: fase sekarang + baris `05-verifikasi-rilis.md`.

**Digantung (butuh VPS/admin — pemilik produk)**
- Langkah 1–5 `05-verifikasi-rilis.md`: jalankan `advisor_paritas` di VPS, uji akun tim, nyalakan flag `*`, pantau. Isi tabel Catatan uji. Sampai itu, S10 belum selesai walau PR ini di-merge.
- **S10b (PR lanjutan, sesudah `*` stabil):** hapus jalur lama — jawaban bot lama (`nlp_cmd`, `handlers.cmd_status`, `checkin_cmd`, `summary.py`, `advisor_cmd` tanpa fallback), `AttentionCard`/`attentionItems`/`getAdvisorInsights`, cabang flag-mati `Dashboard.jsx`, `GET /advisor/insights` + aturan v1 + `context.py` bila tak terpakai. Menyentuh file milik S6/S7/S9 — sudah disetujui pemilik produk ("ikut usulmu") untuk dikerjakan sesudah flag `*`.
- Masih terbuka dari sesi lain: kartu grafik memanjang di layar lebar (S6 lanjutan), bot `fund_shift` tanpa kunci household (S5/S9), "Lihat semua" saran (S7).

**Keputusan kecil**
- Penghapusan jalur lama dipisah dari PR ini supaya user di luar flag tidak kehilangan bot/Beranda bila flag `*` tertunda atau di-rollback.
- Skrip paritas memaksa flag lewat `pengaturan` (bukan menulis AppSetting) supaya bisa menilai semua user sebelum `*` tanpa efek samping.
- Nama amplop pribadi yang kembar dengan amplop yang terlihat viewer tidak dihitung bocor (tidak bisa dibedakan dari teks).
- Paket baru `app/scripts/` untuk skrip operasional (dijalankan `python -m app.scripts.<nama>` dari `/opt/jatahku/app`).

**Jebakan**
- Tidak ada UI Admin untuk `advisor_v2_users`; `PUT /admin/settings/{key}?value=` butuh token admin (lihat konsol browser di 05).
- Cache dashboard 90 detik: perubahan flag/data di Beranda bisa tertunda ≤ 90 detik, bot & ringkasan seketika — jangan dikira beda angka saat uji.
- `npm run build` mengubah `frontend/dist/index.html`; kembalikan sebelum commit.
- Sesi ini dikerjakan di branch `ai-advisor/s10-verifikasi-rilis` (bukan branch bawaan sesi Claude Code).

**Tes:** backend 853 OK (7 baru) · frontend 260 OK · build OK.

**Cara mencoba:** di VPS sesudah deploy: `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.advisor_paritas` (atau `--user <id>`). Lokal: `python -m unittest app.tests.test_advisor_paritas_script -v`.

**Lanjut:** ikuti `05-verifikasi-rilis.md` langkah 1–5, catat hasilnya; lalu buka sesi "S10b hapus jalur lama" (prompt pembuka §3, issue #65 atau issue baru berlabel `ai-advisor`) dengan daftar di langkah 6. Bila cek paritas menemukan `beda`/`crash`, kirim keluarannya (tanpa data pribadi) ke sesi Claude Code untuk perbaikan kecil sebelum `*`.

---

## S6 lanjutan · 2026-10-16 · Claude

**Selesai**
- `Dashboard.jsx`: flag aktif + periode berjalan → `<AdvisorCard dash={advisorDash} stamp={stamp} isDark={isDark} />` di samping grafik; selain itu `AttentionCard` lama tidak berubah. Dirujuk ke #62 (S7), bukan issue baru.
- Dibuat bertumpuk di atas #83 (S7) karena `AdvisorCard.jsx` baru ada di sana; #83 sudah di-merge, base PR ini sudah `main`.

**Digantung**
- Di layar lebar, kartu AI Advisor lebih tinggi dari kartu lama, jadi kartu grafik ikut memanjang dengan ruang kosong di bawahnya (grid `stretch`). Belum diubah.

**Tes (sesudah merge S9):** backend 846 OK · frontend 260 OK · build OK · Playwright (API di-mock): flag aktif → kartu AI Advisor, `{"enabled": false}` → "Perlu perhatian".

**Lanjut:** S10 (#65) — prompt pembuka §3 dengan SN = S10.

---

## S9 · 2026-10-16 · pemilik produk + Claude

**Selesai**
- `services/advisor/chat.py` (baru): pilih jawaban per intent dari `dashboard.analisa` (Konteks + Seleksi) — tanpa rumus (metrics.py) dan tanpa kalimat (render.py). `muat(user, db)` = flag `advisor_v2_users` → snapshot → dismiss → analisa; None di luar flag / tanpa amplop. Jawaban: `jawab_status`, `jawab_sisa`, `jawab_limit_harian`, `jawab_proyeksi`, `jawab_hari_ini`, `jawab_kenapa` (boros / {amplop} / hari ini), `jawab_aman_beli` (SIM-01), `ringkasan_harian`, `ringkasan_mingguan`.
- `render.py` (tambahan, bagian "Chat web & Telegram"): `blok_angka` (dana belanja, terpakai, disisihkan tagihan, sisa bebas T3, aman J1/hari, jatah J0 · belanja T5 — dipakai "sisa", /status, ringkasan harian & mingguan → paritas §13), `baris_amplop` (M6; tabungan G1), `teks_insight_html` (+fakta & rincian), `teks_chip_html`, `chat_*`, `ringkasan_*`. HTML Telegram, nama/teks user di-escape.
- `metrics.simulasi_belanja(snap, eid, jumlah)`: `compute_metrics` dengan satu transaksi simulasi hari ini (SIM-01: T3, J1, T10 dihitung ulang, bukan dikurangi tangan).
- `bot/advisor_cmd.py` (baru): `jawab(update, user, intent)` → True bila v2 membalas; False (di luar flag / gagal, dengan log) → handler memakai jawaban lama. Dipanggil sesudah cek setup di `nlp_cmd` (sisa, limit harian, kapan habis, "boncos ga" → proyeksi, emosi → kenapa, pengeluaran hari ini), `handlers.cmd_status` (+ baris streak), `checkin_cmd.handle_whatif` (SIM-01).
- Intent baru `KENAPA_RE` ("kenapa/kok … boros/habis/lewat/kurang/minus …") dirutekan bersama `EMOSI_RE` ke `handle_emosi`; chip Tanya web ("Kenapa dana belanja kurang?", "Kenapa belanja hari ini lewat jatah?") ikut terjawab.
- `summary.py`: harian v2 = chip Jatah hari ini + item #1 daftar + `blok_angka`; mingguan v2 = rekap 7 hari (transaksi, seperti dulu) + T4 + angka periode + chip Sisa bebas + 1 aturan struktural (AMP-04/05/06/TAB-02, tidak di-dismiss) + konsistensi mencatat + streak. Mesin advisor memakai sesi DB sendiri (gagal → ringkasan lama tetap terkirim).
- **Crash hari terakhir:** jawaban lama `limit harian`/`kapan habis` membagi `days_remaining` = 0 di hari terakhir periode (ZeroDivisionError). `_period_days` kini minimal 1. Jalur v2 memakai `metrics` (H = 0 → J0 = sisa, J1 None, "Hari terakhir periode: sisa bebas = jatah hari ini").
- **Aman beli (periode gajian):** `handle_whatif` dulu memanggil `get_envelopes_with_spent` tanpa `payday_day` (bulan kalender); sekarang periode gajian user.
- Chat web: 🔵 (tone info) jadi titik biru di `ChatText` (`DOT_EMOJI`).
- Tes: `test_advisor_chat.py` (37): paritas §13 dari fixture §12 dan end-to-end SQLite (`GET /advisor/dashboard` vs "sisa"/status/ringkasan, amplop pribadi anggota lain tidak muncul), hari terakhir (v2 + jawaban lama), d < 3, kenapa boros/amplop/hari ini, `cari_amplop`, SIM-01 aman/turun/kurang/ditebak, bot (flag, fallback gagal, /status + streak, whatif payday, rute kenapa), ringkasan v2 harian/mingguan, flag mati tanpa query. Dua tes lama diberi patch flag mati (jalur lama).

**Digantung / untuk sesi lain**
- **S10:** jawaban lama di `nlp_cmd`/`cmd_status`/`checkin_cmd`/`summary.py` masih ada untuk user di luar flag. Setelah flag `*`, hapus jalur lama (rumus `total_free / days_left`, `daily_avg × hari`, `free ≥ 2× harga`) dan `advisor_cmd` boleh dipanggil tanpa fallback.
- **S17:** "aman beli" dengan tombol ganti amplop (sekarang: amplop ditebak dari M12 + teks "sebut nama amplopnya"); intent "tagihan bulan ini", "target {nama}"; chip pertanyaan cepat; `help_cmd.py`.
- **S16:** notifikasi proaktif bisa memakai `chat.ringkasan_harian`/`utama` (item #1) dan `teks_insight_html`.
- `handle_comparison` (bulan ini vs lalu) dan `pengeluaran hari lalu` belum lewat v2 — bukan angka periode berjalan; ikut S17 bila perlu.
- Bot geser dana (`fund_shift`) belum memakai kunci household (catatan S5) — tidak disentuh di S9.

**Keputusan kecil (juga di docstring chat.py)**
- Bot ikut flag `advisor_v2_users` (03-workflow §5: UI baru Fase 1 hanya untuk user di daftar) supaya angka bot tetap sama dengan layar yang user lihat: flag aktif = Beranda baru + bot v2; flag mati = keduanya lama.
- "kenapa boros?" = PER-01 › PER-02 › HAR-01 › PER-03 › PER-04 › PER-05 › PER-07 (walau di-dismiss: user bertanya langsung) + 2 item daftar lain. "kenapa {amplop} habis?" = AMP-01/02/03, TAG-01/02, AMP-04/08/10/05 amplop itu (termasuk yang diserap PER-01); tidak ada → "{amplop} masih aman" + angkanya. "kenapa … hari ini …" = HAR-01 › 03 › 02 › 04 › 05.
- Nama amplop di teks: nama utuh dulu, lalu kata ≥ 4 huruf yang bukan kata umum; frasa "dana belanja" / "belanja hari ini" dibuang dulu (amplop bernama "Belanja" tidak tertangkap chip Tanya).
- SIM-01 ✅ bila J1 baru ≥ 90% J1 dan amplop & T3 cukup; ⚠️ bila cukup tapi J1 turun > 10%; ❌ bila bebas amplop atau T3 < 0. Hari terakhir (J1 None): pembanding = sisa bebas total.
- "boncos ga?" (SANTAI) dijawab proyeksi; emosi ("duit lari kemana") dijawab "kenapa boros".
- `blok_angka` menampilkan "Disisihkan tagihan" (M4 + M5) supaya dana − terpakai − disisihkan = sisa bebas (§2 "total = jumlah bagian").
- "Pengeluaran hari ini" v2 = T5 (variabel, seluruh amplop belanja terlihat, sama dengan KPI Jatah hari ini) + "Tagihan & lainnya" terpisah; 5 transaksi terakhir dari snapshot (deskripsi anggota lain sudah disamarkan). Jawaban lama hanya transaksi viewer.

**Jebakan**
- Tes handler lama yang memalsukan `AsyncSessionLocal` dengan urutan hasil `db.execute` akan kehabisan hasil bila jalur v2 ikut membaca AppSetting. Patch `advisor_cmd.analisa` → None (bot) atau `summary._pengaturan_advisor` → {} (ringkasan).
- Jangan `rollback()` sesi loop ringkasan: objek `user` ter-expire dan akses atribut async gagal. Karena itu `_analisa_v2` membuka sesi sendiri.
- `simulasi_belanja` dengan nominal sama persis dengan tagihan amplop itu yang belum dibayar → dianggap melunasi (M4), T3 tidak turun — sama dengan bila dicatat sungguhan.

**Tes:** backend 846 OK (37 baru) · frontend 253 OK (1 baru) · build OK.

**Cara mencoba:** `PUT /admin/settings/advisor_v2_users?value=<user_id>`, lalu di Telegram/chat web: `/status`, "sisa", "limit harian", "kapan habis", "pengeluaran hari ini", "kenapa boros?", "kenapa makan habis?", "aman gak beli sepatu 300k". Ringkasan untuk satu user saja: di VPS, `python -c "import asyncio; from app.services.summary import send_daily_summary as f; asyncio.run(f(user_id='<id>'))"` (endpoint `/daily-summary` admin mengirim ke **semua** user).

**Lanjut:** S7 (#62, kartu AI Advisor) bila belum; lalu S10 (#65) dengan prompt pembuka §3. Di S10, bandingkan Beranda vs `/status` vs "sisa" di chat web untuk akun tim (angka harus identik, lihat `test_advisor_chat.ParitasDatabaseTests`), nyalakan flag `*`, lalu hapus jawaban lama di `nlp_cmd`/`cmd_status`/`checkin_cmd`/`summary.py` (cari pemanggil `advisor_cmd.jawab` dan `_analisa_v2`).
## S7 · 2026-10-16 · Claude

**Selesai**
- `lib/advisorCard.js` (+ tes, 6): `dismissOptions` (label §9 dari `dismiss.pilihan`), `visibleItems`/`badgeCount` (sembunyikan seketika sebelum muatan ulang), `overflowLabel` ("+N saran lain: {judul pendek}", maks 2 judul), `primaryAction`, `askChips` (3–4 pertanyaan dari payload aksi `chat` insight yang menyala — daftar dulu, lalu chip KPI — dilengkapi intent tetap bot: kapan habis, limit harian, sisa, pengeluaran hari ini), `askAction`. Tidak ada teks insight atau angka di frontend; semua dari `render.py`.
- `components/AdvisorCard.jsx` (baru): judul "AI Advisor" + badge (`advisor.total`) + cap waktu (`updatedLabel`); maks 3 item dari `advisor.items` (urutan server); tiap item: titik tone, judul, isi, CTA utama (`aksi[0]` via `openAction`), **Rincian** (fakta, insight yang diserap, CTA lain, dasar + keyakinan + cap waktu, **Sembunyikan periode ini** / **Tidak relevan**), **Nanti**. "+N saran lain". Kosong → "Semua aman" + `advisor.aman`. Kotak **Tanya AI Advisor**: chip cepat → chat terkirim langsung (chip lain tetap di chat), "Ketik sendiri…" → chat terbuka dengan chip.
- `Dashboard.jsx` (milik S6) **tidak** diubah: pemasangan kartu sempat dibuat lalu di-revert atas permintaan pemilik produk. Kartu belum tampil di Beranda sampai dipasang (lihat Digantung).

**Digantung / untuk sesi lain**
- S4 (#81) dan S6 (#82) sudah di `main`; branch ini sudah di-merge dengan `main`, jadi kartu langsung berisi semua aturan (TAG/AMP/INC/TAB/DAT).
- **Pemasangan kartu di Beranda** (`Dashboard.jsx`, milik S6): dikerjakan di PR lanjutan S6 (lihat entri "S6 lanjutan").
- Sesi ini dikerjakan tanpa ritual pembuka (rangkuman + "lanjut") dan di branch `claude/festive-bell-3hg12l`. Pekerjaan berikutnya memakai `ai-advisor/sN-*`.
- "Lihat semua" untuk `advisor.sisa` belum ada: server hanya mengirim `{id, judul_pendek}`. Kalau mau dibuka, kontrak perlu insight utuh di `sisa` (atau endpoint terpisah).
- `AttentionCard.jsx` + `attentionItems` (`dashboardInsights.js`) + `api.getAdvisorInsights` masih dipakai UI lama; hapus setelah flag `*` (S10).
- Ringkasan "Rencana dana dihitung bersama" tidak ditampilkan khusus: CTA `plan` di item membuka `PlanSheet` (S8) dengan payload dari server (sudah satu rencana bersama, S3).

**Keputusan kecil**
- Tombol utama gelap hanya untuk item pertama bertone danger; lainnya outline, supaya mata ke satu aksi.
- "Nanti" hanya tampil bila `nanti` ada di `dismiss.pilihan`; dua pilihan lain di Rincian.
- Chip Tanya memakai teks pertanyaan dari `aksi[].payload.teks` sebagai label (label aksi "Tanya di chat" tidak informatif sebagai chip).
- Sembunyi lokal direset setiap payload dashboard baru (server sudah menyaring yang di-dismiss).
- Pilihan dismiss yang sudah jadi CTA insight (INC-01 "Ingatkan besok" = `nanti`, AMP-10 "Biarkan" = `periode`) tidak diulang sebagai tombol kartu (**Nanti** / pilihan Rincian).

**Jebakan**
- `npm run build` mengubah `frontend/dist/index.html`; kembalikan sebelum commit.
- Uji Playwright perlu `serviceWorkers: 'block'` dan user dengan `telegram_id`.

**Tes (sesudah merge `main` dengan S4 & S6):** backend 809 OK · frontend 259 OK (7 baru) · build OK · Playwright dengan API di-mock (payload asli `susun_dashboard(contoh_15_okt())` dari branch S4): 3 item + "+1 saran lain", Rincian PER-01, Nanti → `POST /advisor/dismiss {"kunci":"TAG-01:kpr","pilihan":"nanti"}`, chip Tanya → chat terkirim, "Semua aman", desktop & HP (skrip tidak di-commit).

**Cara mencoba:** `PUT /admin/settings/advisor_v2_users?value=<user_id>`, buka Beranda; kartu AI Advisor menggantikan "Perlu perhatian".

**Lanjut:** S7 selesai setelah PR di-merge. Sesi berikutnya: S9 (#64) — prompt pembuka §3 dengan SN = S9. S10 memeriksa kartu ini di produksi bersama chip KPI.

---

## S6 · 2026-10-16 · pemilik produk + Claude

**Selesai**
- `lib/advisorDashboard.js` (+ tes, 8): `advisorEnabled`, `updatedLabel` (cap waktu §7: "baru saja" < 5 menit, selain itu jam dari `generated_at` = zona waktu user), `chipLook` (peredaman: info/ok redam bila `redam_chip`), `popoverActions` (maks 2 CTA), `basisLabel`, `advisorDailySeries` (deret grafik dari `metrics.harian`), `advisorKpi` (nilai kartu dari `metrics`). Tidak ada rumus angka periode — hanya rasio tampilan (lebar batang, persen bulat).
- `api.getAdvisorDashboard()`: null bila gagal; `{"enabled": false}` dan null → Beranda memakai UI lama.
- `components/AdvisorChip.jsx` (baru): `AdvisorChip` (✦ + latar tone; redam = teks + garis tepi tipis tanpa ✦), `InsightPopover` (layar ≥ 768px: popover di bawah kartu, selebar kartu; HP: bottom sheet lewat portal). Isi: judul, isi, fakta, rincian, maks 2 CTA (`openAction`), dasar + keyakinan + cap waktu, **Sembunyikan** (= aksi `dismiss` `nanti` lewat Layout). Escape / klik di luar menutup.
- `KpiTile`: prop `advisor` (chip menggantikan badge, kartu aktif bergaris tepi brand) dan `bar.split`/`bar.lateColor` (Terpakai: hijau sampai penanda waktu, kuning sesudahnya).
- `Dashboard.jsx`: periode berjalan + flag aktif → kartu Jatah hari ini (belanja hari ini / **J0**), Sisa bebas (T3, "aman J1/hari"), Terpakai (dari dana belanja, waktu %, perkiraan akhir ±T8), Income (pemasukan **rumah tangga**, "kamu Rp…", arus kas dari T9) membaca `metrics`. Chip di keenam kartu bila `kpi.<kartu>` ada. Muat ulang saat `txn-added`, `envelope-updated`, `advisor-dismissed`. Periode lalu / flag mati → UI lama tanpa perubahan.
- `DailySpendingChart` prop `advisor`: batang = variabel (warna dari `lewat`), segmen redup "Tagihan & lainnya" (tagihan + penyesuaian + outlier), garis tangga jatah J0 per hari, baris analisa `grafik.teks` + aksi (Lihat {tgl}). Tooltip: lewat/dalam jatah hari itu + rincian segmen redup.
- Dihapus: `lib/advisorToday.js` (+ tes) — sudah tidak dipakai.

**Digantung / untuk sesi lain**
- **S4 (sudah di `main`):** chip Income/Tagihan/Tabungan tampil karena `kpi.income|tagihan|tabungan` kini terisi. Nilai kartu Tagihan & Tabungan masih angka lama (`/recurring/summary/period`, `getGoals`) (badge lama tergantikan chip). Angka Tagihan (M4) dan batang lunas/telat per tagihan belum ada di `metrics.to_api()` — kalau mau satu sumber, tambahkan field (mis. `tagihan_lunas`, `tagihan_telat`) di kontrak lalu baca di kartu.
- **S7:** kartu "Perlu perhatian" masih `AttentionCard` lama di samping grafik; ganti dengan `advisor.items`. Cap waktu kartu bisa memakai `updatedLabel`.
- Saving rate tidak ada di `metrics` API; kartu Income versi baru memakai batang "bagian yang kamu catat". Bila saving rate mau kembali, tambahkan `saving_rate_rumah_tangga` ke `to_api()`.
- `/analytics/prediction` masih dimuat untuk label periode & "N hari lagi" di header (dan UI lama). Hapus pemanggilannya setelah flag `*` (S10) bila label diambil dari `metrics`.

**Keputusan kecil**
- Outlier masuk segmen redup (bukan batang) supaya rata-rata 7 batang terakhir = `laju7` persis (§12).
- "Hari ini" grafik advisor = tanggal di `generated_at` (zona waktu user), bukan jam browser.
- Jatah hari ini tetap memakai `dailyMeter` (rasio tampilan) dengan J0; badge "Lewat" diganti chip.

**Jebakan**
- Popover desktop absolut di dalam kartu: kartu aktif diberi `z-30` supaya tidak tertutup kartu/section di bawahnya. Klik di luar ditangani di `KpiTile` (bukan untuk bottom sheet, yang punya latar sendiri).
- `npm run build` mengubah `frontend/dist/index.html`; kembalikan sebelum commit (sama dengan S1).

**Tes:** backend 761 OK · frontend 252 OK (8 baru, 7 dihapus bersama `advisorToday`) · build OK · Playwright dengan API di-mock (payload asli `susun_dashboard(contoh_15_okt())`): kartu, chip, redam, popover desktop, bottom sheet HP, flag mati → UI lama (skrip tidak di-commit).

**Cara mencoba:** `PUT /admin/settings/advisor_v2_users?value=<user_id>`, buka Beranda, klik chip di kartu KPI.

---

## S4 · 2026-10-16 · pemilik produk + Claude

**Selesai**
- `rules/amplop.py` AMP-01..11, `rules/tagihan.py` TAG-01..09, `rules/pemasukan.py` INC-01..06, `rules/tabungan.py` TAB-01..07, `rules/data.py` DAT-01..06 (DAT-03 untuk S4 dan S4b) — fungsi murni `(Konteks) → [Insight]`, didaftarkan di `dashboard.EVALUATOR`. Template semua aturan + label aksi di `render.py`.
- Keenam chip KPI terisi: Income (INC-01 › 04 › 03 › 06 › 02, cadangan INC-05), Tagihan (TAG-01 › 02 › 04 › DAT-06 › TAG-03, cadangan TAG-09), Tabungan (TAB-02 › 01 › 03 › 06 › 04 › 05, cadangan TAB-07).
- `select.py`: rencana bersama tidak memakai kebutuhan insight yang diserap (AMP-02/03 oleh PER-01, AMP-01 oleh TAG-01/02 atau PER-02); kebutuhan tanpa tagihan ke amplop yang juga "geser & bayar" hanya menambah kelebihannya (minus amplop tagihan tidak direncanakan dua kali). PER-02 menyerap AMP-01 amplop belanja minus. Penekanan 4 (INC-01 → "Catat pemasukan" pertama di insight kekurangan). Penekanan 7 di `rules/tabungan.py`.
- `POST /recurring/{id}/mark-paid` (Tandai lunas: `next_run` maju tanpa transaksi, jendela bayar sama dengan /pay).
- `metrics.py` (hanya tambahan): `ceil10rb`, `jumlah_transaksi_laju_amplop`, `variabel_harian_amplop`, `saving_rate_riwayat`. `KonstantaAturan` + konstanta §11 untuk aturan S4.
- Frontend kecil: `delete_txn` menghapus semua `txn_ids` (Hapus duplikat struk, S4b).
- Tes: `test_advisor_aturan_s4.py` (46: §12 chip Tagihan/Tabungan/Income + skor TAG-01 100 & TAB-01 23, skenario 4, 5, 14, 15, 19, tiap aturan, penekanan 3/4/7, render semua) + 2 tes mark-paid di `test_recurring_pay.py`. Dua tes S3 diperbarui: Rincian PER-01 §12 kini juga memuat AMP-03 Makan & Jajan (sesuai §12).

**Digantung / untuk sesi lain**
- **DAT-06 "Bukan pembayaran tagihan"** sekarang hanya dismiss `tidak_relevan`; M4 masih menganggap tagihan lunas. Supaya M4 berhenti menganggapnya lunas, snapshot perlu membaca status itu (Redis) dan `compute_bills` melewati transaksi itu — S12/S13.
- **"Hari ini tidak belanja"** (HAR-05/DAT-04) belum ada di web; CTA yang ada: Catat.
- **TAG-06 Perbarui nominal / TAG-08 Lihat keduanya** membuka `/langganan`; belum ada kind untuk mengubah langganan langsung (S12).
- **Alternatif "tunggu pemasukan"** (penekanan 4) belum ada; yang ada: Catat pemasukan diletakkan pertama.
- **S6/S7:** `kpi.income/tagihan/tabungan` sudah terisi; slot halaman (`amplop`, `langganan`, `alokasi`, `analitik`, `transaksi`) sudah diisi aturan, menunggu `GET /advisor/page/*` (S11–S15).
- **S9:** chat "kenapa {amplop} habis?" = fakta AMP-02/03 amplop itu (`render_insight` dari `sel.semua`, termasuk yang diserap PER-01).

**Keputusan kecil (juga di docstring tiap modul)**
- AMP-02 "habis" = bebas ≤ 0 dan sisa ≥ 0; kebutuhan geser = laju × r − bebas. Amplop minus dihitung "habis sekarang" untuk AMP-04 (U 0,4; §12 Transport skor ±58).
- TAG-01/02 "perlu" = Σ nominal tagihan belum dibayar s/d tagihan ini − sisa(e) amplop tagihan (§12: Rp2.008.174). rupiah = nominal + minus amplop. Tagihan mingguan dinilai per kemunculan berikutnya.
- TAG-04 terkumpul = sisa(e) amplop tagihan tahunan (0..nominal).
- INC-02 menyebut anggota yang paling banyak mengisi amplop bersama, dengan jumlah ke amplop bersama saja.
- INC-05 selalu ada (cadangan chip): ok ≥ 10%, info bila < 10% atau turun ≥ 5 poin dari median; tanpa pemasukan → "Belum ada pemasukan".
- TAB-01 target = goal di amplop darurat, tanpa goal = 3 × G7; U 0,2 (skor 23 di §12). TAB-02 bertenggat > 1 bulan juga ditunda saat defisit.
- TAB-03 butuh setoran sebelumnya atau saldo > 0 (target baru tidak langsung ditegur).
- DAT-01 tidak menyala bila belum pernah cocokkan saldo. DAT-02 tanpa CTA → hanya slot `analitik`.
- DAT-03 masuk daftar bila total diduga dobel ≥ Rp100 rb; "Bukan dobel" = dismiss `tidak_relevan` (90 hari).
- DAT-06 ikut urutan chip Tagihan sesudah TAG-04.
- AMP-06 memakai kind `raise_budget` untuk menurunkan jatah juga (payload jumlah baru, label "Turunkan jatah…").

**Jebakan**
- `sinking._next_expected_date` mengembalikan string, bukan `date` (TAG-07 mengubahnya).
- `test_recurring_pay.py` sebelumnya gagal bila dijalankan sendiri (env `DATABASE_URL`/`JWT_SECRET`); sudah diberi default.

**Baseline tes:** backend 809 OK · frontend 251 OK · build OK.

**Cara mencoba:** `PUT /admin/settings/advisor_v2_users?value=<user_id>` lalu `GET /advisor/dashboard` — `kpi.income/tagihan/tabungan` terisi. Tandai lunas: `POST /recurring/<id>/mark-paid`.

---

## S3 · 2026-10-16 · pemilik produk + Claude

**Selesai**
- `insight.py` (baru): skema `Insight` (data saja: aturan, entitas, tone, slot, `data`, aksi tanpa label, rupiah terdampak, U, keyakinan), `KonstantaAturan` (§11 bagian aturan/seleksi), skor §5 (`hitung_skor`, `kunci_urut` = kelompok tone dulu), efek keyakinan rendah, `Konteks` untuk aturan.
- `rules/hari.py` HAR-01..05, `rules/periode.py` PER-01..07 — fungsi murni `(Konteks) → [Insight]`, angka dari metrics/sinyal.
- `select.py`: satu rencana dana bersama dari semua CTA `plan` (§8.4) → batas harian & "maksimal/hari" dari `batas_harian_setelah_rencana` (penekanan 8); penekanan 2 (PER-01 menyerap AMP-02/03), 3 (TAG-01/02 menyerap AMP-01, tone/skor tertinggi), 5, 6 (HAR-01 menyatu ke PER-01, tanpa menaikkan tone PER-01); chip per kartu (urutan §7); daftar maks 3 / 1 per amplop kecuali danger / 2 per domain; "+N saran lain"; "Semua aman" (`advisor.aman`); peredaman chip; dismiss §9 (muncul lagi bila tone naik / rupiah +50%).
- `render.py`: semua teks HAR/PER, label aksi, dasar, "Kemungkinan:" untuk keyakinan rendah, baris grafik, `teks_telegram` (untuk S9), format `rp_ringkas`/`rp_penuh`/`tgl`/`hari_tgl`/`rasio`. Teks `ALASAN` perencana dipindah ke sini (`alasan_rencana`).
- `dashboard.py`: `analisa`/`susun_dashboard` (murni) + `get_dashboard` (flag `advisor_v2_users`, cache, dismiss, zona waktu user) + `dismiss`. AppSetting `advisor_konstanta` (JSON) menimpa `Konstanta`, `KonstantaSinyal`, `KonstantaAturan` tanpa deploy.
- `advisor_cache.py`: cache `advisor:{hid}:{viewer}` 90 detik, `invalidate(hid)`, dismiss `advisor:dismiss:{viewer}:{kunci}` dengan TTL §9, dan **hook sesi SQLAlchemy** (`install()` di `main.py` lifespan): `after_flush` mengumpulkan household dari Transaction/Income/Allocation/Envelope/RecurringTransaction/Goal/MonthlySnapshot/BalanceCheck yang ditulis, `after_commit` menjadwalkan `invalidate` (rollback → dibuang).
- Route `GET /advisor/dashboard`, `POST /advisor/dismiss` (204).
- `metrics.py` (hanya tambahan): `variabel_hari_ini_per_amplop`, `laju_periode`, `laju_7_hari`, `persen_variabel`, `perkiraan_sisa`, `jumlah_transaksi_laju`, `ringkasan_periode_lalu`. `signals.py`: `hari_mencatat`/`biasa_mencatat` (dipakai S15 dan HAR-05, perilaku S15 sama).
- Tes: `test_advisor_insight_v2.py` (39: §12 chip & skor 69,1/54,3, skenario 1, 2, 3, 6, 11, 13, 16, 17, tiap aturan, seleksi, dismiss, rencana bersama, render, konstanta) dan `test_advisor_dashboard_integration.py` (9, SQLite: flag, cache, hook commit/rollback, dismiss).
- Kontrak `04-kontrak-api.md`: `advisor.aman`, `rincian`, `skor`, `{"enabled": false}`, kpi null, aturan dismiss.

**Digantung / untuk sesi lain**
- **S4:** tambahkan `rules/{amplop,tagihan,pemasukan,tabungan,data}.py` ke `EVALUATOR` di `dashboard.py` dan template-nya di `render.TEMPLATE`. Chip income/tagihan/tabungan masih null. Penekanan 2/3 sudah jalan begitu AMP-01/02/03 dan TAG-01/02 ada (isi `amplop_id`). Penekanan 7 (tidak menyarankan setor saat defisit): aturan TAB cukup cek apakah PER-01/PER-02 menyala di daftar insight (atau `m.kekurangan > 0 or m.sisa_bebas < 0`).
- **CTA "Batas harian"** dimatikan default (`KonstantaAturan.cta_batas_harian = False`, §2: rilis setelah Pikir-Pikir Fase 1 menjadikan limit harian peringatan). Angka "Batas aman {amplop}" tetap tampil sebagai fakta. Nyalakan tanpa deploy: AppSetting `advisor_konstanta` = `{"cta_batas_harian": true}`.
- **S6:** baca `kpi.<kartu>.chip/tone`, `redam_chip`, `grafik`, `generated_at` (cap waktu). `{"enabled": false}` → UI lama.
- **S7:** `advisor.items/sisa/total/aman`; dismiss sudah live (`POST /advisor/dismiss`), item hilang di muatan berikutnya (cache viewer dihapus).
- **S9:** `teks_telegram(render_insight(...))`; `analisa(snap, now_local=…)` memberi `Konteks` + `Seleksi` tanpa HTTP.
- HAR-05 "Hari ini tidak belanja" belum ada (check-in hanya di bot); CTA yang ada: Catat.
- Admin UI untuk `advisor_v2_users` belum ada; pakai `PUT /admin/settings/advisor_v2_users?value=<id,id|*>`.

**Keputusan kecil (juga di docstring)**
- Chip mengikuti urutan prioritas kartu; di dalam satu aturan, skor tertinggi. Fallback tambahan: PER-07 untuk Sisa bebas & Terpakai di hari 1–2 (belum ada proyeksi). HAR-04 juga fallback bila J0 = 0 (chip "Jatah Rp0", info).
- PER-01 tidak menyala di hari terakhir (r = 0); minus ditangani PER-02. PER-02 "Tutup minus" = rencana untuk amplop belanja yang minus.
- CTA batas harian PER-01: amplop keinginan pertama di 3 penyumbang terbesar, selain itu penyumbang terbesar.
- PER-06 tujuan: tabungan pertama yang boleh diubah viewer, tabungan umum dulu, dana darurat terakhir; jumlah = Σ bebas non-rollover (S16), selain itu perkiraan sisa.
- A (§5): 1,0 untuk plan/fund/pay/mark_paid/daily_limit/raise_budget/delete_txn/not_duplicate; 0,7 untuk income/route/chat/make_recurring/catat.
- Dismiss juga menyembunyikan chip; kartu bisa tanpa chip bila satu-satunya insight-nya disembunyikan.
- Cache dashboard dibuang bila tanggal `generated_at` ≠ hari ini (ganti hari tanpa menunggu TTL).

**Jebakan**
- `test_advisor_plan_integration` merah di `main` sesudah 17.00 UTC: tes memakai `date.today()` (UTC), snapshot memakai tanggal Asia/Jakarta → tagihan jatuh tempo "hari ini" terbaca telat 1 hari. Diperbaiki di tes (`user_today`). Tes baru memakai `datetime.now(Asia/Jakarta)`.
- Hook cache hanya terpasang lewat `main.py` lifespan; tes yang ingin mengujinya memanggil `advisor_cache.install()` dan `uninstall()`.
- Hook menjalankan satu `SELECT household_id` di `after_flush` bila flush menyentuh transaksi/langganan/alokasi; gagal → hanya log, tulis data tetap jalan.

**Baseline tes:** backend 761 OK · frontend 251 OK · build OK.

**Cara mencoba:** `PUT /admin/settings/advisor_v2_users?value=<user_id>` lalu `GET /advisor/dashboard`. Dismiss: `POST /advisor/dismiss {"kunci": "<id item>", "pilihan": "nanti"}`.

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
