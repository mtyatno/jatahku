# AI Advisor v2 — catatan serah-terima

Entri terbaru di atas. Format: **Sesi · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

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
