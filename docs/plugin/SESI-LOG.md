# Plugin — catatan serah-terima

Entri terbaru di atas. Format: **Kode sesi · nama · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## H1 · Host inti · 2026-11-01 · pemilik produk + Claude

**Selesai** (status review, PR #176, issue #149; review keamanan terpisah lulus 2 Nov, temuan 1–5 dikerjakan di branch ini)
- `app/plugins/host/manifest.py`: skema manifest (pydantic, kunci asing ditolak) dengan aturan T1: penerbit "Jatahku" (ADR-P9); izin dari `IZIN`, `ai:analyze`/`network:*` ditolak (ADR-P14); cakupan `ruang` saja (ADR-P11); awalan `p_<id>_` untuk tabel dan `<id>.` untuk kartu/aksi/notifikasi; perintah bot `kind: read` + `audience` wajib; aksi cepat ≤ 2; copot = `archive_90_days` (ADR-P15); `engines.plugin_api` dicocokkan dengan `PLUGIN_API_VERSION` 1.0.0.
- `registry.py`: muat `app/plugins/<id>/manifest.json` (folder `host`, `sdk`, `_*` dilewati); aturan antarplugin (folder = id, `requires` ada/tidak melingkar/mendukung jenis ruang, `conflicts` ada, prefix callback/perintah bot/aturan advisor/flag unik). Mode ketat (CI, tes) vs mode start (lewati yang rusak dan pemakainya, `log.error`). `muat_saat_start()` di lifespan mencetak `🧩 plugin dimuat: …`.
- `validator.py` + langkah "Validator manifest plugin" di workflow "Tes".
- `siklus.py` (satu-satunya penulis `plugin_installations`/`plugin_audit_log`): pasang (tanpa wizard → active, dengan `contributes.setup` → installed), lanjut, jeda, copot (`purge_after` +90 hari), pulihkan (pasang pada arsip = baris yang sama); idempoten tanpa audit ganda; jenis ruang, requires, conflicts dua arah, `dibutuhkan_plugin_lain`; flag `plugin_<id>_users` (pasang butuh flag, jeda/copot tidak); saklar darurat `plugin_saklar_darurat` (pasang/lanjut 503, jeda/copot boleh, status per ruang utuh); hak dari `entitlements` hanya ditampilkan; `aktif_di_ruang()` untuk H2/H3; `bersihkan_kedaluwarsa()`.
- Model + migrasi `a7e3c1f5d9b2`: `plugin_installations` (indeks unik parsial `owner_id IS NULL` / `IS NOT NULL`), `entitlements` (cek pemilik user atau ruang, unik `source`+`external_ref`), `plugin_audit_log`.
- `app/api/routes/plugins.py`: `GET /plugins` (`RuangAktif`), `POST /ruang/{ruang_id}/plugins/{plugin_id}/pasang|lanjut|jeda|copot` (ruang dari path lewat `ruang_objek`, lalu owner/admin).
- Tes `app/tests/test_plugin_host.py` (33): manifest, registry, validator, HTTP (siklus, IDOR, peran, header tidak menentukan ruang tulis, flag R4, requires/conflicts, saklar, flag dicabut, pembersih, keunikan). Pagar `test_ruang_pagar`: empat route tulis baru di kelompok `objek`.
- Dokumen: kontrak §5 v1 (katalog + siklus; `contributions` tetap v0 untuk H3) dan §7 (6 kode baru); checklist deploy H1 di `AGENTS.md` (+ saklar darurat, urutan migrasi dengan R5); `00-indeks.md`; `PROGRESS.md` (R3, R4 selesai).
- Merge `main` (R4 #174) di branch: konflik `main.py`, `AGENTS.md`, `00-indeks.md`, `PROGRESS.md`.
- Tes: unittest 2426 (1 gagal = `test_basic_quota_bot_fund_shift_finishes_started_input`, sama dengan `main`) · node --test 628 (`src/lib`; 653 dengan `src/native`) · build ok · `cek-migrasi.sh origin/main` di PostgreSQL 16 ok · `openapi_cek` tanpa perubahan memutus.

- **Review keamanan terpisah (2 Nov):** semua gerbang H1 lulus, tidak ada temuan yang memblokir. Temuan yang dikerjakan di branch ini:
  1. **Sedang:** race `requires`/`conflicts` (`pasang a` ∥ `pasang b` yang bentrok, `jeda`/`copot a` ∥ `pasang` plugin yang butuh `a`) lolos 13–15/20 di PostgreSQL. Sekarang `_kunci_ruang` (FOR UPDATE baris `households`) di awal pasang/lanjut/jeda/copot: 0/20.
  2. **Rendah:** validator menerima perintah bot inti (`/start`, `/lock`), prefix callback yang ditangkap pola inti (`lock_`, `kn_`, `ky_`, `batch_`), dan `flag` berupa kunci AppSetting inti. Sekarang ditolak lewat `PERINTAH_INTI`, `POLA_CALLBACK_INTI`, dan pola `plugin_<nama>_users`; tes memastikan konstanta itu sama dengan `bot_commands()`/`bot_callbacks()`.
  3. **Rendah:** `lanjut` mengabaikan flag rollout. Sekarang 404 `plugin_tidak_ada` seperti pasang.
  4. **Info:** nama plugin tersembunyi bisa ditebak dari beda `plugin_tidak_aktif` vs `plugin_tidak_ada`. Sekarang seragam.
  5. **Info:** saklar darurat kini tidak peka huruf besar-kecil.

**Digantung**
- Dari review (info, sengaja tidak dikerjakan di H1): persetujuan izin belum terikat ke daftar izin yang ditampilkan (klien bisa mengirim versi manifest, server 409 bila beda; bersama layar izin H3); toggle saklar dan flag tidak tercatat di `plugin_audit_log` (hanya lewat `PUT /admin/settings` yang tidak diaudit); FK CASCADE ke `households` ikut menghapus hak berbayar dan jejak audit saat ruang dihapus (keputusan sadar di V1); jalur `IntegrityError` di `pasang` memakai `rollback` penuh, aman sekarang (kunci ruang membuatnya hampir tak terjangkau di PostgreSQL), pertimbangkan savepoint di H2.
- **Urutan migrasi dengan R5 (#175):** H1 `a7e3c1f5d9b2` dan R5 `c5r5a8e2d417` sama-sama menginduk ke `2d51b9031a6b`. PR yang di-merge kedua memindahkan `down_revision`-nya ke yang pertama (dan memperbarui langkah 2 checklist-nya) sebelum merge; cek `alembic heads` satu baris.
- Job pembersih arsip belum dijadwalkan: ADR-P15 butuh pemberitahuan 7 hari sebelumnya dan hook hapus data `p_*` per plugin (H2 `notifications`/`jobs`, U1). Baru relevan ≥ 90 hari setelah copot pertama.
- Endpoint ekspor (`GET /ruang/{id}/plugins/{plugin_id}/ekspor`) di U1; `copot` menjawab `ekspor: null` sampai itu.
- Titik `settings` (form dari JSON Schema + validasi server): `pasang` menolak `pengaturan` tidak kosong (422). `jsonschema` bukan dependensi produksi: pilih pustaka atau validator sendiri di H2/U1.
- Validator: tabrakan prefix callback plugin dengan callback bot inti, dan pemeriksaan pemanggilan `PluginContext` terhadap izin, di H2.
- Izin yang bertambah di manifest versi baru belum memicu persetujuan ulang untuk instalasi yang sudah aktif (`granted_permissions` hanya diperbarui saat pasang/pulihkan). `PluginContext` (H2) harus memeriksa `granted_permissions`, bukan izin manifest.
- `butuh_paket_usaha` (402) belum ditegakkan (V1).
- Hapus akun/ruang: FK `plugin_installations` dan `plugin_audit_log` ke `households` CASCADE, ke `users` SET NULL (`installed_by`, `actor_id`) atau CASCADE (`owner_id`); `account_deletion.py` belum perlu diubah selama tabel `p_*` belum ada.

**Jebakan**
- Sejak R4, `ruang_objek` juga menolak ruang usaha di luar flag `ruang_usaha_users`. Tes yang memakai ruang usaha harus mengisi flag itu (`AppSetting ruang_usaha_users`), kalau tidak semua aksi 404.
- `logging` tidak dikonfigurasi di API: `log.info` tidak sampai ke journal. Ringkasan start memakai `print` seperti baris start lain; galat per plugin tetap `log.error`.
- UNIQUE biasa pada `(household_id, plugin_id, owner_id)` tidak mencegah dua baris saat `owner_id` NULL; pakai indeks parsial (model dan migrasi harus identik, dicek `alembic check`).
- `npm run build` mengubah `frontend/dist/index.html` yang ter-track: `git checkout -- frontend/dist` sebelum commit.
- `pyflakes app/main.py` gagal karena dua import lama yang tidak terpakai (sudah di `main`); jangan dijadikan syarat di rantai `&&`.

**Keputusan kecil**
- Status API: `tersedia | terpasang | aktif | dijeda | arsip` (v0 tanpa `aktif`, dengan `dicopot`). `lanjut` juga menjadi "wizard selesai" (installed → active).
- Bukan anggota, ruang tidak ada, atau ID bukan UUID → 404 `ruang_tidak_ada`; member → 403 `khusus_admin`; plugin tidak dikenal atau di luar flag saat pasang → 404 `plugin_tidak_ada`.
- Pulihkan memakai baris yang sama dan menyetujui ulang izin manifest versi sekarang.
- Katalog tetap menampilkan plugin yang punya baris instalasi walau flag dicabut, supaya bisa dijeda/dicopot.
- `hak` tanpa baris entitlement = `uji_coba` (beta, ADR-P13); tanpa SKU di manifest = `gratis`.
- Saklar darurat tidak memblokir jeda dan copot.

**Cara melanjutkan**
- Review keamanan sudah lulus (2 Nov). Merge ditahan sampai pemilik bisa menjalankan migrasi di VPS pada jam yang sama.
- Sebelum merge: cek apakah R5 (#175) sudah di-merge; bila ya, pindahkan `down_revision` H1 ke `c5r5a8e2d417`. Lalu "Urutan merge PR bermigrasi" dan checklist "Plugin H1" di `AGENTS.md`.
- Berikutnya `/sesi-plugin H2` (PluginContext dan titik ekstensi server; butuh H1 selesai), atau R5/R8 di jalur ruang usaha.

---

## R4 · Membuat dan berpindah ruang · 2026-11-01 · pemilik produk + Claude

**Selesai** (status review, PR #174, issue #144; tanpa tanda review/migrasi)
- `app/api/routes/ruang.py`: `GET /ruang` (daftar untuk pemilih: ruang keluarga dulu, lalu urut bergabung; `paket` dan `jam_kerja` null sampai H1/V1 dan R5; field tambahan `boleh_buat_usaha`) dan `POST /ruang` (ruang usaha, pembuat owner, nama 1–60 huruf, batas 3 ruang usaha per pemilik dengan kunci baris user, 403 `ruang_usaha_belum_dibuka` di luar flag, 409 `batas_ruang_usaha`).
- Flag `ruang_usaha_users` jadi saklar di `app/services/ruang.py` (`ruang_usaha_dibuka`, `_anggota_ruang_terbuka`): di luar flag, ruang usaha tidak tampil, tidak bisa dibuka lewat header (403), dan objeknya tidak bisa ditulis (`ruang_objek`/`ruang_amplop*` → None → 404). Ruang keluarga tidak terpengaruh.
- `household_cycle.init_ruang_usaha`: ruang usaha baru `payday_day = 1` (bulan kalender, desain A2 butir 9); tanpa ini `household_payday` menurunkan siklus dari gajian owner.
- Frontend: `lib/ruangAktif.js` (pilihan di perangkat, hanya id ruang selain ruang keluarga; header; akhiran cache offline per ruang; ADR-P16), `components/RuangPicker.jsx` (sidebar di bawah logo; HP menggantikan logo; buat ruang usaha), `lib/api.js` (header di `request` dan `uploadForm`, `daftarRuang`, `buatRuang`, 403 `ruang_tidak_diizinkan` → kembali ke ruang keluarga + Beranda, dikosongkan saat logout), `Layout.jsx` (chat berlabel "Ruang keluarga" untuk pemilik/admin di ruang usaha, disembunyikan untuk member), `ChatPanel.jsx` (label di judul), ikon `home`/`store`.
- Tes: `app/tests/test_ruang_r4.py` (9: daftar tanpa/dengan flag, buat, validasi nama, batas, undangan dari ruang usaha ditolak, flag dicabut menutup baca dan tulis, hapus akun menghapus ruang usaha miliknya; uji mutasi saklar flag → gagal); fixture ruang usaha di `test_ruang_gerbang.py` dan `test_ruang_resolver.py` diberi flag; pagar: `POST /ruang` di kelompok tanpa ruang, kueri keanggotaan `routes/ruang.py` (2) dan `services/ruang.py` (4). `src/lib/ruangAktif.test.js` (9).
- Diperiksa di browser (Playwright, API dipalsukan): pemilih desktop dan HP, terang dan gelap, form buat ruang; header terkirim hanya saat ruang usaha dipilih dan tidak pernah ke `/ruang`; 403 ruang → pilihan dihapus, kembali ke `/`, permintaan berikutnya tanpa header.
- Dokumen: kontrak §1 (klien mengirim header sejak R4), §2 v1 (+ saklar flag, perilaku klien), §7 (2 kode baru); `AGENTS.md` checklist R4 + R3 sudah jalan; `00-indeks.md` (fase, peta kode); `PROGRESS.md` (R3 selesai, R4 review, Gerbang R).
- Tes: unittest 2393 (1 gagal = `test_basic_quota_bot_fund_shift_finishes_started_input`, juga gagal di `main`) · node --test 628 lulus · build ok · Migrasi: tidak berlaku · `openapi_cek` tanpa perubahan memutus.

**Digantung**
- Menu yang hanya bermakna di ruang keluarga (Telegram, Pengaturan household, Pikir-Pikir) belum disaring per ruang: menu inti sama di semua ruang (ADR-P1); penyaringan per peran di R6, grup menu Usaha di H3.
- Bottom nav 6 item / "Lainnya" (pertanyaan A4) belum diputuskan: R4 tidak menambah item menu, jadi ditunda ke H3.
- Kotak Struk dan foto struk di ruang usaha tetap ruang keluarga untuk bukti baru (R7); mencatat ke amplop ruang usaha masuk ruang amplop itu (R3).
- Tutup/ganti nama/hapus ruang usaha belum ada (R5/R6 bersama halaman Anggota).
- `test_basic_quota_bot_fund_shift_finishes_started_input` masih gagal di `main`; perlu PR kecil terpisah.

**Jebakan**
- `npm run build` mengubah `frontend/dist/index.html` yang ter-track: kembalikan dengan `git checkout -- frontend/dist` sebelum commit.
- Fixture ruang usaha di tes lama perlu `AppSetting(ruang_usaha_users)`; tanpa itu header ruang usaha kini 403 dan objeknya 404.
- Tema di Playwright: kunci `jatahku_theme` berisi JSON `{color: hijau|laut|senja, mode}`.

**Keputusan kecil**
- Pindah ruang = muat ulang penuh ke `/` (bukan remount sebagian): tidak ada state, cache, atau chat ruang lama yang tertinggal. Pindah ruang jarang, jadi biaya muat ulang dapat diterima.
- 403 `ruang_tidak_diizinkan` tidak diulang tanpa header, karena permintaan tulis bisa masuk ruang yang salah.
- Batas 3 ruang usaha per pemilik selama beta (menahan ruang kosong menumpuk); bisa ditinjau di V1 bersama Paket Usaha.
- Flag juga menutup tulis dari objek (bukan hanya header), supaya mencabut flag benar-benar menutup ruang usaha.

**Cara melanjutkan**
- Merge (tanpa review terpisah, tanpa migrasi), lalu checklist "Plugin R4" di `AGENTS.md`: `ruang_paritas`, buka flag hanya untuk pemilik, uji buat/pindah/catat, jangan `*` sebelum R5 dan V1.
- Berikutnya `/sesi-plugin R5` (peran, batasan, persetujuan, undangan ruang usaha; migrasi + review) atau R8 / H1.

---

## R3 · Ruang dari objek saat menulis · 2026-11-01 · pemilik produk + Claude

**Selesai** (status review, PR #171; review keamanan terpisah lulus 1 Nov, temuan 1–5 dikerjakan di branch ini; issue #143)
- Keputusan pemilik produk (1 Nov): **A** objek baru tanpa induk memakai ruang dari header yang sah (`ruang_aktif`; tanpa header = ruang keluarga); **B** hak Paket Usaha (kode `butuh_paket_usaha` 402) baru dipasang di H1/V1, ruang usaha belum dibatasi selama beta.
- `app/services/ruang.py`: `ruang_objek` (ruang objek bila user anggota, selain itu None), `ruang_amplop`, `ruang_amplop_satu` (semua amplop satu ruang; dua ruang milik user → `LintasRuang` 400 `lintas_ruang`), `ruang_jenis`; `RuangDitolak` menerima status. Docstring modul menjelaskan aturan R3.
- Route tulis dari objek, lalu keanggotaan: `PUT`/`DELETE /envelopes/{id}`, `PATCH`/`DELETE /envelopes/groups/{id}`, `POST /envelopes/transfer`, `POST`/`DELETE /transactions`, `POST /goals/` + `PUT`/`DELETE /goals/{id}`, `POST /recurring/` + ubah/hapus/bayar/lewati/tandai, `POST /incomes/` dengan alokasi, `POST /balance-check/{id}/undo` (`svc.ruang_cek`), `PUT /kotak-struk/merchants/{id}`. Objek ruang lain → 404 dengan pesan "tidak ditemukan" biasa.
- `POST /transactions/batch`: ruang per baris dari amplopnya; baris asing ditolak per baris; kuota Basic hanya untuk baris di luar ruang usaha.
- Objek baru tanpa induk (`ruang_aktif`): `POST /envelopes/`, `/envelopes/groups`, `/incomes/` tanpa alokasi, `/user/reset`, `/snapshots/recompute`, `/balance-check/apply`, `/advisor/plan` + `/execute`, `/transactions/suggest-envelope(s)`. `ruang_tulis` tinggal di `POST /household/invite`.
- Kuota per ruang (`plan_limits.py`): `check_transaction_limit` / `quota_notice_after_input` / `check_envelope_limit` / `check_recurring_limit` menerima `household_id`; ruang usaha tanpa kuota Basic; `monthly_txn_usage` dan `usage.txn_this_month` di `/user/profile` menghitung transaksi di luar ruang usaha (`di_luar_ruang_usaha`). `check_expense` (bot + web) memakai ruang amplop. Pengecualian `DIIZINKAN_BEDA_SAMPAI_R3` dihapus dari tes gerbang.
- Tes: gerbang +6 (tulis objek ruang usaha sendiri tanpa header, objek baru ke ruang header, lintas ruang, antrean offline per baris, kuota per ruang, reset dengan header ruang usaha); IDOR +4 aksi buat (transaksi, target, langganan, pemasukan ke amplop household lain) + cek tidak ada baris terbentuk; pagar: daftar route non-GET dengan `ruang_aktif` diperbarui. Tes lama disesuaikan (hapus `hid=` dari pemanggilan langsung handler tulis; patch `ruang_amplop` / `_ruang_langganan` / `ruang_cek` di tes mock).
- Dokumen: kontrak §1 (baris tulis R3, kuota per ruang) dan §7 (`lintas_ruang`); `AGENTS.md` aturan 1, checklist R3, checklist R2 sudah jalan; `00-indeks.md`; `PROGRESS.md` (R2 selesai, Gerbang R).
- Tes: unittest 2159 (1 gagal = `test_basic_quota_bot_fund_shift_finishes_started_input`, gagal juga di `main`) · node --test 584 lulus · build ok · Migrasi: tidak berlaku · `openapi_cek` tanpa perubahan memutus.

- Review keamanan PR #171 (sesi terpisah): lulus semua gerbang 03-workflow.md. Temuan yang dikerjakan: (1) pagar tes `test_setiap_route_tulis_punya_sumber_ruang`: setiap route non-GET wajib tercatat sebagai ruang dari objek (badan fungsi memanggil helper `ruang_*`), `RuangAktif`/`RuangTulis`, atau tanpa ruang; (2) 404 eksplisit tepat setelah helper ruang, tidak lagi bergantung pada `household_id IS NULL`; (3) `POST /incomes/` dengan amplop orang lain → 404; (4) pemberitahuan kuota `POST /transactions/` memakai ruang transaksinya; (5) docstring pagar. Tes IDOR kini menuntut 404 persis.
- Tes sesudah review dan merge `main` (#169, #172, #173): lihat PR #171.

**Digantung**
- Batasan per peran (anggota/karyawan hanya amplop tertentu, batas nominal, persetujuan) di R5: sekarang setiap anggota ruang boleh menulis ke semua objek ruang itu, sama seperti household hari ini.
- Kotak Struk: bukti baru dan saran amplopnya masih ruang keluarga (R7). Mencatat bukti ke amplop ruang usaha masuk ruang amplop itu.
- Prive dua sisi (pengecualian `lintas_ruang`) di R8.
- Bot: `check_envelope_limit` di bot tetap ruang keluarga (chat hanya ruang keluarga, ADR-P2).
- Catatan review untuk R4/R5: sampai R5 semua anggota ruang boleh menulis ke seluruh isi ruang (`balance-check/apply`, `advisor/execute`, amplop baru lewat header). Aman karena ruang usaha belum bisa mengundang anggota: undangan ruang usaha harus aktif di PR yang sama dengan penegakan peran R5; R4 tidak membuka undangan.
- Catatan review untuk R5: `POST /user/reset` di ruang usaha hanya owner, tetapi menghapus transaksi semua anggota sementara email cadangan hanya berisi transaksi owner (sudah begitu sejak sebelum R3). Dengan karyawan, catatan karyawan hilang tanpa jejak → masuk cakupan log audit R5.
- `test_basic_quota_bot_fund_shift_finishes_started_input` masih gagal di `main` (tanggal struk tetap `2026-10-10`); perlu PR kecil terpisah.

**Jebakan**
- Pembantu pengubah tanda tangan route sempat menghapus seluruh badan fungsi (slice yang salah); hasil dicek lewat pyflakes dan diff sebelum lanjut. Pembantu di scratchpad, bukan di repo.
- Handler tulis tidak lagi punya parameter `hid`; tes yang memanggil handler langsung cukup tanpa `hid=` (integrasi SQLite) atau mem-patch pembantu ruang objek (tes mock).
- `Envelope.budget_amount` wajib > 0 untuk amplop belanja: tes membuat amplop harus memberi budget.
- `main` bergerak dua kali (#168, #170); rebase bersih. Sesudah review, `main` bergerak lagi (#169 siklus household, #172, #173): di-merge ke branch, konflik hanya di dokumen plugin.
- `POST /transactions/`: 404 amplop eksplisit harus sesudah cek idempotensi dan cek struk (spec 5d, `test_receipt_check_runs_after_idempotency_and_before_envelope_checks`), bukan tepat sesudah helper ruang.

**Keputusan kecil**
- `POST /incomes/` dengan alokasi: ruang dari amplop alokasi menang atas header (pemasukan mengikuti amplopnya).
- Transfer/alokasi yang melibatkan amplop household orang lain → 404 (amplop "tidak ditemukan"), bukan `lintas_ruang`, supaya keberadaan ruang lain tidak bocor; `lintas_ruang` hanya bila kedua ruang milik user.
- Kuota transaksi Basic tetap per user (bukan per ruang keluarga tertentu): semua catatan di luar ruang usaha, termasuk household lama yang ditinggalkan, seperti sebelum R3.
- Saran amplop (`suggest-envelope(s)`) memakai ruang header (siap untuk lembar Catat cepat di R7).

**Cara melanjutkan**
- Merge: tanpa migrasi; checklist "Plugin R3" di `AGENTS.md` (`ruang_paritas` sesudah deploy, uji catat/geser/bayar/antrean offline).
- Berikutnya `/sesi-plugin R4` (membuat dan berpindah ruang, flag `ruang_usaha_users`; merge dulu PR terbuka yang menyentuh `Layout.jsx`/`api.js`), atau R5 / R8 / H1 (semuanya butuh R3).
## B3 (lanjutan) · Rilis Beranda registry ke pemilik · 2026-11-01 · pemilik produk + Claude

**Selesai** (status **selesai** per keputusan pemilik 1 Nov 14:08; PR #167, #168, #172; issue #140 ditutup)
- `beranda_paritas` di VPS (data produksi): **105 user · ok 105 · beda 0 · crash 0 · lewati 0 · batch p95 231 ms → Gerbang B (angka): LULUS**.
- Flag `beranda_registry_users` = user_id pemilik. Beranda registry jalan di akun pemilik (`POST /dashboard/data` 200, ±7 kB untuk 14 kartu).
- Log produksi pertama: `dashboard penyedia core.kpi.jatah/sisa_bebas 154–220 ms` di setiap muat, tanpa `dashboard batch` (batch < 500 ms). Penyebab: kartu inti pertama menanggung muat sumber bersama. #168: peringatan per penyedia hanya untuk kartu plugin; `Sumber` mencatat waktu muat per sumber; `dashboard batch` menyebut tiga sumber terlama. Tes baru di `test_dashboard_registry.py`. Deploy `774c294` terverifikasi.

**Digantung**
- Banding tampilan otomatis (`scripts/banding_beranda.py`) belum dijalankan di laptop; dicoba di VPS dan gagal (`python` tidak ada, tanpa Chrome/Playwright — memang alat laptop). Pengganti sementara: banding manual `?beranda=lama` vs `?beranda=registry` di HP pemilik.
- Flag `*` setelah sehari dipakai pemilik tanpa `dashboard batch` / `dashboard sumber … gagal` di `journalctl`. Lalu: Gerbang B lulus, B3 `selesai`, tutup #140 (PR dokumen kecil).
- Hapus `BerandaLama.jsx` dan `?beranda=` setelah `*` stabil (sesi kecil terpisah).

**Jebakan**
- Token akses pemilik sempat ditempel di chat dan di shell VPS (perintah `JATAHKU_TOKEN=… python …`). Pemilik diminta logout sesi itu (mencabut `sid` di server) dan menghapus baris dari riwayat shell. Petunjuk alat banding kini memakai `read -s` supaya token tidak masuk riwayat.
- `scripts/banding_beranda.py` butuh Python dengan Playwright + Chrome: jalankan di laptop, bukan VPS produksi.

**Keputusan kecil**
- B3 ditandai `selesai` dan Gerbang B `lulus` atas keputusan pemilik, dengan dasar paritas produksi (angka dan p95). Banding tampilan otomatis tidak dijalankan; perluasan flag ke `*` dan pemantauan log dilakukan pemilik mengikuti `AGENTS.md` "Rilis Beranda registry" langkah 3–5.
- Anggaran 150 ms per penyedia hanya untuk kartu plugin, sesuai 01-kajian.md; kartu inti dinilai dari total batch.

**Cara melanjutkan**
- Pemilik: `journalctl -u jatahku --since today | grep -E "dashboard (batch|sumber)"` kosong → `sudo -u postgres psql jatahku_db -c "UPDATE app_settings SET value = '*' WHERE key = 'beranda_registry_users'"`.
- Lalu `/sesi-plugin B3` sebentar untuk menandai Gerbang B lulus dan B3 selesai (atau digabung ke PR sesi berikutnya). Jalur ruang: `/sesi-plugin R3`.

---

## B3 · Verifikasi dan rilis Beranda registry · 2026-11-01 · pemilik produk + Claude

**Selesai** (status berjalan: alat di PR #167, issue #140 tetap terbuka sampai flag `*`)
- `app/scripts/beranda_paritas.py` (di VPS, hanya membaca): semua user atau `--user`, periode berjalan dan lalu, template Beranda lewat `batch.jalankan`: tanpa crash/kartu error; setiap sumber di setiap kartu = endpoint lama dihitung ulang di sesi terpisah; `value` KPI = sumbernya; nama amplop pribadi anggota lain tidak muncul; p95 batch ≤ 500 ms (satu user pemanasan tidak dihitung). Cache AI Advisor tidak dibaca dan tidak ditulis (dihitung segar). Keluaran tanpa nama/nominal. Kode keluar 1 bila gagal. Tes `test_beranda_paritas_script.py` (7).
- `scripts/banding_beranda.py` (di laptop): screenshot `/?beranda=lama` vs `/?beranda=registry` di 390/820/1100/1440 px, gelap dan terang, banding per piksel, gambar selisih bila beda. Token dari env, tidak ditulis ke disk.
- `Dashboard.jsx`: `?beranda=lama|registry` memaksa salah satu Beranda (banding dan uji di HP sungguhan); `pilihBeranda`/`paksaDariUrl` murni + tes.
- `AGENTS.md` "Rilis Beranda registry": paritas di VPS, banding tampilan, flag bertahap (SQL dicoba di PostgreSQL lokal), pantau log, kembali ke Beranda lama dengan value kosong.
- Uji lokal (PostgreSQL + Redis): paritas 2 user `ok`, p95 49 ms, tidak ada kunci cache dashboard tertulis; banding tampilan 8/8 identik. Tes: unittest 2117 (1 gagal = #164, juga di `main`) · node --test 609 · build ok · `openapi_cek` ok.

**Digantung (pemilik produk, butuh akses produksi)**
- Jalankan `beranda_paritas` di VPS dan `banding_beranda.py` di laptop; tempel dua baris terakhir keduanya di #140. Lalu flag `beranda_registry_users` = id sendiri sehari, lalu `*`. Setelah itu Gerbang B dan B3 ditandai lulus/selesai (bisa di PR sesi berikutnya).
- Hapus `BerandaLama.jsx` dan jalur `?beranda=lama` setelah `*` stabil (sesi kecil terpisah, sesudah beta tidak wajib).

**Jebakan**
- Proses skrip baru membayar impor tertunda dan koneksi pertama (~500 ms) di user pertama; tanpa pemanasan p95 tampak gagal di data kecil.
- Token akses lokal kedaluwarsa cepat; alat banding berhenti dengan pesan jelas bila dialihkan ke `/login`.

**Keputusan kecil**
- Paritas membandingkan sumber per kartu (bukan per nama sumber saja), supaya penyedia satu kartu yang menyimpang ketahuan.
- Banding tampilan memakai `?beranda=` di akun sendiri, bukan flag, supaya bisa dijalankan sebelum flag menyala dan tanpa mengubah produksi.
- PR B3 tidak menutup #140: issue itu ditutup saat flag `*` dan Gerbang B lulus.

**Cara melanjutkan**
- Pemilik produk: langkah 1–5 "Rilis Beranda registry" di `AGENTS.md`.
- Sesi berikutnya: `/sesi-plugin R3` di jalur ruang (R2 #166 di-merge saat sesi ini berjalan; branch B3 menggabungkan `main` dan skrip paritas memakai `ruang_keluarga` + `household_id` dari R2). H1 butuh B1 dan R3.

---

## R2 · Resolver `ruang_aktif` · 2026-11-01 · pemilik produk + Claude

**Selesai** (status review, PR #166, menunggu review keamanan terpisah, issue #142). Direncanakan 2 sesi; selesai dalam satu sesi, termasuk route, skrip paritas, dan dokumen yang semula untuk sesi 2.
- `app/services/ruang.py`: `ruang_aktif` (membaca; header `X-Jatahku-Ruang`, kosong/tanpa header = ruang keluarga), `ruang_tulis` (menulis; ruang keluarga sampai R3, header ruang lain → 403), `ruang_keluarga` / `ruang_keluarga_id` (household `rumah_tangga`, keanggotaan tertua bila ganda), `keanggotaan`, `keanggotaan_keluarga`, `RuangDitolak` + `install()` (403 `{detail, kode: ruang_tidak_diizinkan}`, dipasang di `main.py`). Header tercantum di OpenAPI.
- Route: parameter keyword-only `*, hid: RuangAktif` / `hid: RuangTulis` di semua route ber-ruang (envelopes, transactions, incomes, goals, recurring, analytics, snapshots, export, balance-check, advisor, dashboard, household, user, kotak-struk). GET dan POST yang hanya membaca (`/dashboard/data`, `/balance-check/preview`, `/advisor/allocation-recommendation`) = aktif; `PUT /dashboard/layout` dan dismiss advisor = aktif (status per user/viewer); `/advisor/plan` = tulis (sepasang dengan execute); lainnya = tulis.
- Services menerima `household_id` eksplisit: `compute_envelope_summaries`, `balance_check.*`, `advisor` (`load_snapshot`, `load_advisor_context`, `chat.muat`, `get_dashboard`, `dismiss`, `batal_dismiss`, halaman, alokasi, sinking, `build_plan`/`execute_plan`), `dashboard.batch.jalankan` (`Sumber.hid` diteruskan ke handler), `export._get_export_data`. Helper `get_household_id` (×2), `_get_hid` (×5), `_household_id`, `_get_household_id`, `_get_membership` dihapus.
- Bot (`handlers` dan semua `*_cmd.py`), ringkasan harian/mingguan, pengingat gajian, proaktif, kuota (`plan_limits`, `/user/profile`), Kotak Struk (intake, saran): `ruang_keluarga`. Gabung akun (`merge.py`, `link.py`) dan pindah household (web + bot) hanya menyentuh keanggotaan ruang keluarga; admin menampilkan ruang keluarga.
- Perbaikan data (ditemukan saat refactor, dikerjakan lebih dulu): `POST /user/reset` hanya menghapus pemasukan user di household yang di-reset (dulu semua household, termasuk household lama yang masih dipakai anggota lain → saldo mereka rusak); cadangan email reset juga hanya isi ruang itu. `/user/export-data`: ruang keluarga = semua catatan user di luar ruang usaha (perilaku lama untuk user sekarang), ruang usaha = catatan ruang itu saja.
- Tes baru: `test_ruang_resolver.py` (12), `test_ruang_gerbang.py` (7: 40 endpoint GET identik sebelum/sesudah user diberi ruang usaha, untuk dia dan anggota lain; header ruang usaha membaca usaha; header asing 403; IDOR 14 aksi ber-ID terhadap household orang lain dan ruang usaha sendiri; reset tidak menyentuh ruang lain), `test_ruang_pagar.py` (pagar sumber + skrip paritas). ±250 tes lama disesuaikan (patch `get_household_id` → `ruang_keluarga`, hasil `FakeResult(HID)` pertama dihapus, `hid=`/`household_id=` eksplisit).
- `app/scripts/ruang_paritas.py` (baca saja): household lama vs `ruang_keluarga_id` per user + uji asap ringkasan amplop dan snapshot.
- Dokumen: `04-kontrak-api.md` §1 v1; `00-indeks.md` (fase, peta kode); `AGENTS.md` aturan 1, checklist "Plugin R2", checklist R1 dan B1 ditandai sudah jalan.
- Tes: unittest 2134 (1 gagal = `test_basic_quota_bot_fund_shift_finishes_started_input`, gagal juga di `main`) · node --test 583 lulus · build ok · Migrasi: tidak berlaku (tanpa model/migrasi) · `openapi_cek` tanpa perubahan memutus.

**Review keamanan PR #166 (1 Nov, sesi terpisah) — temuan dikerjakan di branch ini**
- Wajib: `POST /auth/link/merge` (tanpa login, cukup kode gabung) meneruskan `keep_household_id` dari body ke `merge_users` tanpa cek. Dengan UUID household orang lain, amplop/pemasukan household yang dibuang pindah ke sana dan akun target menjadi anggotanya (bug lama, sebelum R2). Diperbaiki di `merge_users`: hanya ruang keluarga salah satu akun, selain itu `{"error": …}` sebelum ada perubahan; route menolak UUID tidak sah dengan 400. Tes: household orang lain, ruang usaha target, dan `bukan-uuid` → 400 tanpa perubahan data; ruang keluarga sah tetap jalan, ruang usaha target tidak tersentuh.
- Disarankan, ikut dikerjakan: join web dan `/join` bot menolak undangan ke household selain `rumah_tangga` (sebelum R5 memakai kunci Redis yang sama untuk undangan ruang usaha). Tes web dan bot (tes bot terbukti gagal tanpa perbaikan).
- Disarankan, ikut dikerjakan: `test_ruang_pagar.py` mencatat pengecualian eksplisit route non-GET yang memakai `ruang_aktif` (3 POST yang hanya membaca, `PUT /dashboard/layout`, dismiss advisor); route tulis baru dengan `ruang_aktif` gagal tes.
- Catatan untuk R5 dari review: semua endpoint baca `ruang_aktif` (termasuk `/export`, `/user/export-data`, `/analytics/*`, `/dashboard/data`, halaman advisor) terbuka untuk setiap anggota ruang; itu daftar yang harus disaring di gerbang "Karyawan tidak melihat laporan".

**Digantung**
- Kuota transaksi Basic masih per user lintas ruang (`plan_limits.monthly_txn_usage`, `usage.txn_this_month` di `/user/profile`). Ditandai `DIIZINKAN_BEDA_SAMPAI_R3` di `test_ruang_gerbang.py`; R3 wajib menghapusnya. Kuota amplop/langganan sudah ruang keluarga.
- Penulisan sampai R3 = ruang keluarga (`ruang_tulis`). R3 menggantinya dengan ruang dari objek (amplop, transaksi, goal, …) dan mengubah header ruang lain di endpoint tulis dari 403 menjadi "ditentukan objek".
- Saran amplop Kotak Struk dan kamus NLP masih ruang keluarga (R7). Bukti baru Kotak Struk dicatat ke ruang keluarga (R3).
- Job snapshot bulanan (`scheduler.py`) memproses semua household anggota user dengan payday user, termasuk ruang usaha bila ada. Tidak galat; perlu dicek ulang bersama rencana siklus household (`households.payday_day`).
- Gabung akun: keanggotaan ruang usaha akun **sumber** (akun bot yang dihapus) ikut terhapus. Akun bot-only praktis tidak punya ruang usaha; dinilai ulang di R5 (undangan ruang usaha).
- `/user/export-data` dan cadangan reset belum mencakup semua ruang sekaligus (ekspor per ruang). Hak akses data pribadi lintas ruang (UU PDP) dibahas sebelum beta.
- `test_basic_quota_bot_fund_shift_finishes_started_input` gagal di `main` juga (dua tes kuota lain pulih setelah 07:00 WIB); perlu dibuat tidak bergantung tanggal.

**Jebakan**
- Parameter route `hid=Depends(...)` dengan nilai bawaan membuat pemanggil langsung (Sumber Beranda, tes) meneruskan objek `Depends` sebagai id ruang tanpa galat. Karena itu `*, hid: RuangAktif` (Annotated, tanpa default); pagar menolak pola lama.
- Pemecah route per `@router` ikut menyapu fungsi pembantu di antara dua route (`_resolve_rec` di `recurring.py` sempat kehilangan `hid`); pyflakes "undefined name" menangkapnya.
- Tes HTTP yang mengganti `get_db` dengan `None` (mis. `DismissHttpTests`) harus juga mengganti `ruang_aktif` lewat `dependency_overrides`, karena resolver membaca database.
- `create_all` + `HouseholdMember(created_at=…)` bisa diatur di tes untuk membuktikan ruang keluarga tidak ditentukan urutan keanggotaan.
- `main` bergerak (B2 #165) selama sesi; rebase hanya bentrok di `00-indeks.md`.

**Keputusan kecil**
- Header kosong = tanpa header (ruang keluarga), bukan 403.
- Endpoint tulis dengan header ruang keluarga sendiri diterima; header ruang lain ditolak, bukan diabaikan.
- Selisih yang diizinkan di gerbang hanya satu kunci (`usage.txn_this_month`), dengan nama konstanta yang memaksa R3 menghapusnya.
- Skrip paritas tidak bisa dijalankan sebelum merge (file baru); checklist memakai kueri psql untuk keanggotaan ganda sebelum merge dan skrip sesudah deploy.

**Cara melanjutkan**
- Review keamanan terpisah: sesi Claude Code baru dengan "review PR #166 terhadap 03-workflow.md bagian keamanan". Temuan dikerjakan di branch ini sebelum merge.
- Merge: tanpa migrasi; ikuti checklist "Plugin R2" di `AGENTS.md` (psql keanggotaan ganda = 0 sebelum merge, `python -m app.scripts.ruang_paritas` sesudah deploy).
- Berikutnya `/sesi-plugin R3` (ruang dari objek saat menulis, kuota per ruang; hapus `DIIZINKAN_BEDA_SAMPAI_R3`), atau `/sesi-plugin B3`. R5 dan R8 juga hanya butuh R3.

---

## B2 · Beranda dari registry · 2026-11-01 · pemilik produk + Claude

**Selesai** (status review, PR #165, issue #139)
- **Temuan keamanan, diperbaiki lebih dulu** (commit terpisah): cache offline `jatahku_cache_*` (profil, ringkasan amplop, transaksi periode berjalan) tidak dihapus saat logout dan kuncinya tidak per user; user berikutnya di perangkat yang sama bisa melihat data user sebelumnya lewat jalur offline `api.js`. `clearAllCache()` di `localCache.js`, dipanggil `logout()`; tes `localCache.test.js`; dicek di browser (cache kosong setelah logout).
- Backend: `GET /dashboard/layout` membawa `enabled` (AppSetting `beranda_registry_users`, daftar id atau `*`), aditif; kontrak §4 dan tes.
- `Dashboard.jsx` = pemilih: `enabled` → `BerandaRegistry.jsx`, selain itu `BerandaLama.jsx`. Tata letak terakhir disimpan di localCache per user (`beranda_layout:<uid>`), jadi kunjungan berikutnya langsung memakai Beranda yang benar.
- `BerandaRegistry.jsx`: satu `POST /dashboard/data` untuk semua instans yang tidak disembunyikan; respons periode berjalan di localCache per user (`beranda_data:<uid>`) untuk offline; muat ulang lewat event `refresh_on` kartu; permintaan basi diabaikan.
- `src/cards/`: `CardRegistry.js`, `DashboardGrid.jsx` (urutan + ukuran, kartu terakhir di baris melebar, P1 1,65 : 1, jarak antarbaris meniru Beranda lama: KPI 12, kelompok yang di ≥1280 px sebaris lalu bertumpuk 16, lainnya 24), `CardFrame.jsx` (error boundary, kerangka, galat per kartu), `core/index.jsx` (15 kartu inti; `kosong` untuk kartu yang Beranda lama tidak gambar: AI Advisor dan Cocokkan saldo di periode lalu, amplop/target tanpa isi, Ke mana uangmu tanpa belanja, Papan disiplin < 2 anggota).
- Bagian bersama supaya kedua Beranda tidak menyimpang: `lib/berandaModel.js` (turunan angka dari Dashboard.jsx lama, murni + tes), `components/BerandaKpi.jsx` (enam KPI), `components/BerandaHeader.jsx` (banner, periode, kepala HP), `hooks/useBerandaShell.js`. `BerandaLama.jsx` = Dashboard.jsx lama yang memakai bagian itu.
- Tes: `node --test` 608 lulus (583 di `src/lib`) · build ok · unittest 2110 (1 gagal, juga gagal di `main`: #164) · `openapi_cek` tanpa perubahan memutus.
- **Uji tampilan lokal** (backend + PostgreSQL + Redis + Vite lokal, Chrome headless, data contoh): Beranda lama vs registry **identik piksel** di 390/820/1100/1440 px (periode berjalan, tema gelap), periode lalu dengan tema terang (HP, desktop), dan flag advisor mati (HP, desktop). Permintaan API Beranda saat dimuat ulang 49 → 24.

**Digantung**
- Gerbang B (B3): paritas untuk semua user produksi dan p95 ≤ 500 ms di data nyata; perbandingan tampilan di perangkat sungguhan (Android/iOS, tablet).
- Kunjungan pertama setelah flag menyala masih memuat Beranda lama sekali (belum ada tata letak di cache), lalu berpindah ke registry.
- Endpoint lama yang masih dipanggil saat Beranda registry tampil berasal dari luar Beranda (sidebar/Layout: `/envelopes/summary`, `/recurring/`, notifikasi) dan kepala halaman (`/analytics/periods`, `/user/streak`, `/household/leaderboard`).
- `BerandaLama.jsx` dihapus setelah B3 menyalakan flag untuk semua user (`*`) dan stabil.
- `value` KPI Tabungan dan teks KPI masih dari frontend (catatan B1).

**Jebakan**
- `-mt-1` pada tautan Cocokkan saldo di Beranda lama tidak berlaku (kalah spesifisitas dari `space-y-6`), jadi jaraknya 24 px, bukan 20. Diukur, bukan ditebak: skrip Playwright membandingkan posisi kartu dan piksel.
- Komponen yang `return null` saat kosong (`SpendBreakdown`) tidak menyisakan jarak di Beranda lama; di grid registry kartu itu harus ditandai `kosong`, kalau tidak muncul jarak 24 px.
- Mode dev memakai `React.StrictMode`, jadi `POST /dashboard/data` terlihat dua kali saat dimuat di dev; di produksi sekali.
- `pkill -f <pola>` di Bash tool ikut mematikan shell-nya sendiri (pola cocok dengan baris perintahnya); hentikan proses dengan PID.
- Tes kuota yang bergantung jam: dua lulus lagi setelah 07:00 WIB; `test_basic_quota_bot_fund_shift_finishes_started_input` tetap gagal karena tanggal struk tetap `2026-10-10` (#164).

**Keputusan kecil**
- Flag dikirim lewat field `enabled` di `GET /dashboard/layout` (bukan endpoint baru), seperti `{"enabled": false}` di `/advisor/dashboard`.
- Breakpoint dibaca dari lebar layar di JS (`useBreakpoint`) supaya kartu terakhir di baris bisa melebar dan grid tetap satu sumber; urutan DOM tetap urutan tata letak.
- Saat batch gagal: periode berjalan memakai cache bila ada, selain itu setiap kartu menampilkan galat sendiri; respons cache dari periode lain tidak ditampilkan (kerangka sampai data periode itu datang).
- Galat sumber `insights` di kartu Perlu perhatian kini menjadi galat kartu (CardFrame), bukan pesan di dalam kartu seperti di UI lama.

**Cara melanjutkan**
- Merge PR ini aman: tanpa migrasi, dan flag `beranda_registry_users` belum ada di produksi, jadi semua user tetap memakai Beranda lama. Uji dengan menambah id sendiri: AppSetting `beranda_registry_users` = `<user_id>`.
- Berikutnya `/sesi-plugin B3` (skrip paritas pola `advisor_paritas` untuk semua user, perbandingan tampilan desktop dan HP, flag menjadi `*`), atau `/sesi-plugin R2` di jalur ruang.

---

## B1 · Registry kartu dan data batch · 2026-11-01 · pemilik produk + Claude

**Selesai** (status review, PR #162, issue #138)
- `app/services/dashboard/`: `registry.py` (15 kartu inti, template Beranda = Beranda sekarang, 14 kartu a1–a14; Papan disiplin hanya di katalog), `providers.py` (satu penyedia per kartu, tanpa rumus), `sources.py` (endpoint lama yang dipanggil `Dashboard.jsx`, dimuat sekali per permintaan dan dipakai bersama), `batch.py` (galat per kartu, log anggaran 500/150 ms), `layout.py` (tata letak efektif, validasi, `if_version`).
- `app/api/routes/dashboard.py`: `GET`/`PUT /dashboard/layout`, `GET /dashboard/cards`, `POST /dashboard/data`, `GET /dashboard/data/{id}`. Belum dipanggil frontend (B2), jadi belum perlu flag.
- Model `DashboardLayout` + migrasi `b1d4a7c2e9f0` (revisi dari R1 `1c7e5a9d3b20`; idempoten, `downgrade` menghapus tabel). Checklist deploy di `AGENTS.md`.
- `04-kontrak-api.md` §4 v1 (termasuk tabel sumber dan kartu) dan kode galat baru di §7; peta kode di `00-indeks.md`.
- Tes baru `app/tests/test_dashboard_registry.py` (19): paritas lewat HTTP terhadap endpoint lama (periode berjalan dan lalu, advisor aktif dan mati, anggota lain), amplop pribadi anggota lain dan household lain tidak bocor, `ruang_id` di body diabaikan, tata letak (409, `instans_hilang`, validasi, parkir), galat per kartu, p95 < 500 ms di SQLite. Uji mutasi: mengubah satu parameter sumber membuat 4 tes paritas gagal.
- Tes: unittest 2068 (3 gagal, sama dengan `main`, lihat jebakan R1) · node --test 562 lulus · build ok · `cek-migrasi.sh origin/main` di PostgreSQL 16 ok · `openapi_cek` tanpa perubahan memutus. Uji manual: `create_all` lebih dulu lalu `alembic upgrade head` tetap lulus (urutan produksi).

**Digantung**
- Gerbang B (paritas semua user produksi, p95 ≤ 500 ms di data nyata) diuji di B3, bukan di sini. Anggaran di produksi baru terlihat dari log `jatahku.dashboard`.
- `value` kartu Tabungan masih `null` (total dijumlah frontend); teks KPI (footer, sufiks) masih dirakit frontend. Memindahkannya ke layanan dan templat server = pekerjaan terpisah, paling lambat sebelum kartu dipakai aplikasi lain selain web.
- Penyedia memanggil handler route lama (impor tertunda). Memindahkan rumus `daily_spending`, `envelope_breakdown`, `spending_prediction`, dll. dari route ke services = refactor terpisah; tes paritas menjaga hasilnya tetap sama.
- Gerbang keamanan "Karyawan tidak melihat laporan" untuk `/dashboard/data`: belum ada kartu laporan dan belum ada peran ruang usaha, jadi belum bisa diuji. Saat U4 menambah kartu laporan, katalog dan data harus menyaring peran `member` (403 `khusus_admin`).

**Jebakan**
- R1 di-merge saat sesi ini berjalan: branch di-rebase ke `225122e`, migrasi B1 kini merevisi `1c7e5a9d3b20`, dan checklist B1 menunggu migrasi R1 jalan dulu.
- Deploy R1 (#161, run 41246922327) **gagal** di "Deploy to VPS", kemungkinan besar `deploy.sh` exit 2 karena migrasi `1c7e5a9d3b20` belum dijalankan (log run tidak bisa dibuka dari sesi cloud). Jalankan checklist R1, lalu jalankan ulang job deploy, sebelum merge B1.
- R1 membolehkan satu user anggota beberapa household. `get_household_id` (`scalar_one_or_none`) akan galat begitu ada user dengan dua household (mulai R4). `app/api/routes/dashboard.py` memakai `get_household_id` dari `envelope_balance.py`, jadi ikut diganti `ruang_aktif` di R2.
- Clone dangkal hanya melacak `main`: setelah push branch baru, tambahkan refspec (`git config --add remote.origin.fetch '+refs/heads/<branch>:refs/remotes/origin/<branch>'`) supaya hook stop tidak mengira branch belum di-push.
- PostgreSQL lokal bisa mati di antara giliran; jalankan ulang `pg_ctl ... start` sebelum `cek-migrasi.sh`.

**Keputusan kecil**
- `periode` di `POST /dashboard/data` = `period_start` dari `GET /analytics/periods` (24 terakhir) atau `null`, bukan `"2026-10"` seperti v0: periode Jatahku mengikuti tanggal gajian. Rentang bebas ditolak (`periode_tidak_dikenal`).
- Kartu inti membawa `sumber` (respons endpoint lama) supaya B2 bisa menggambar komponen yang sama tanpa perubahan tampilan; bentuk baru `inti` untuk kartu inti dengan komponen sendiri. `value` KPI hanya diisi bila angkanya utuh di respons server.
- Potongan `advisor` per kartu: KPI mendapat metrik tanpa deret harian + chip kartunya; Pengeluaran harian mendapat deret harian + `grafik`; kartu AI Advisor mendapat muatan utuh. Saat flag advisor mati, kartu AI Advisor ikut membawa sumber UI Perlu perhatian.
- `GET /dashboard/layout` tidak menyimpan apa pun; dokumen pertama dibuat `PUT` dengan `if_version: 0`. `PUT` menyimpan hanya field yang dikenal (whitelist), bukan JSON bebas dari klien.
- `GET /dashboard/data/{id}` membaca kartu dan pengaturan dari tata letak tersimpan user sendiri, bukan dari query.

**Cara melanjutkan**
- Sebelum merge B1: deploy R1 harus hijau (migrasi `1c7e5a9d3b20` jalan, job deploy diulang). Lalu ikuti "Urutan merge PR bermigrasi" dan checklist "Plugin B1" di `AGENTS.md`; `alembic current` harus `1c7e5a9d3b20` sebelum upgrade.
- Berikutnya `/sesi-plugin B2` (Beranda dari registry di balik `beranda_registry_users`; merge dulu PR terbuka yang menyentuh `Dashboard.jsx`), atau `/sesi-plugin R2` di jalur ruang.

---

## R1 · Model ruang · 2026-11-01 · pemilik produk + Claude

**Selesai** (status review, PR #161, issue #141)
- `households.type` (`rumah_tangga` | `usaha`, bawaan `rumah_tangga`) dan `incomes.kind` (`pemasukan` | `transfer` | `top-up` | `penyesuaian`, bawaan `pemasukan`), konstanta `HouseholdType` dan `IncomeKind` di `models.py` (String, bukan SAEnum).
- Unik `uq_household_members_user_household` `(user_id, household_id)`: satu user boleh anggota beberapa household, sekali per household. Belum ada jalan membuat household kedua (R4, di balik `ruang_usaha_users`).
- `app/services/ruang_schema.py`: `RUANG_DDL` (kolom, idempoten) dijalankan di `lifespan` dan migrasi; `KIND_BACKFILL` hanya di migrasi `1c7e5a9d3b20`. Migrasi berhenti dengan daftar baris bila ada keanggotaan ganda, tanpa menghapus apa pun.
- Penulis `Income` mengisi `kind`: `fund_shift.record_transfer` dan refund/tutup minus saat hapus amplop → `transfer`; `record_topup` (bot) → `top-up`; `apply_balance_check` → `penyesuaian`; `POST /incomes/` menerima `kind` opsional (`pemasukan` | `top-up`, lainnya 422).
- API aditif: `type` di `GET /household/`, `kind` di respons `POST /incomes/` dan item `GET /incomes/` (`04-kontrak-api.md` bagian 0, v1). `openapi_cek`: tidak ada perubahan memutus.
- Checklist deploy R1 di `AGENTS.md`; tes baru `app/tests/test_ruang_model.py` (22 tes, SQLite).
- Tes: unittest 2049 (3 gagal, sama dengan `main`, lihat jebakan) · node --test 562 lulus · build ok · `cek-migrasi.sh origin/main` di PostgreSQL 16 ok. Uji manual di PostgreSQL: urutan produksi (restart → DDL, lalu migrasi → backfill) mengisi keempat jenis; keanggotaan ganda membuat migrasi berhenti dan tergulung balik.

**Digantung**
- #160: web (`FundEnvelopeModal.jsx`, `Envelopes.jsx`) belum mengirim `kind: 'top-up'`, jadi top-up web baru tersimpan `pemasukan`. Belum ada pembaca `kind`, jadi belum berdampak.
- `incomes.kind` belum dipakai di mana pun (mis. hitungan "ditambal N×" atau `type` di `GET /incomes/`, yang masih diturunkan dari nominal 0).
- Rencana siklus household (`households.payday_day`, project claude.ai) belum di repo; migrasinya sekarang harus merevisi dari `1c7e5a9d3b20` (atau sebaliknya bila tayang lebih dulu).

**Jebakan**
- 3 tes kuota (`test_basic_quota_bot_fund_shift_finishes_started_input`, `test_quota_endpoint_counts_scans_but_never_limits`, `test_basic_has_no_scan_quota`) gagal juga di `main` tanpa perubahan R1 saat dijalankan 1 Nov 04:00 WIB (UTC masih 31 Okt): baris dibuat dengan waktu UTC, hitungan bulan memakai tanggal lokal. Tidak disentuh; perlu dicek ulang setelah 07:00 WIB dan dibuat tidak bergantung jam bila tetap muncul.
- Unit-of-work SQLAlchemy menjalankan INSERT sebelum DELETE dalam satu flush. Pindah household (hapus keanggotaan lama + tambah baru) aman karena `household_id` berbeda; tapi kode baru yang menghapus lalu menambah keanggotaan ke household yang **sama** dalam satu flush akan kena constraint unik. Flush di antaranya.
- PostgreSQL lokal: direktori scratchpad tidak bisa diakses user `claude`; pakai direktori di `/home/claude` untuk `initdb`.

**Keputusan kecil**
- Backfill `kind` hanya di migrasi, bukan tiap start: aturan teks "Top-up" menebak, dan baris baru sudah ditulis benar oleh jalurnya. Backfill hanya mengubah baris yang masih `pemasukan`, berurutan penyesuaian → transfer → top-up.
- Aturan top-up: keterangan `Top-up` persis atau diawali `Top-up ` (bot, bawaan modal web, form amplop baru); "Top-upan …" tetap `pemasukan`.
- Klien tidak boleh menulis `transfer` atau `penyesuaian` lewat `POST /incomes/`.
- Jenis usaha (penjualan, modal, pinjaman) tidak masuk `incomes.kind`; milik tabel Buku Usaha (U1–U2).
- `PROGRESS.md`: F0 ditandai `selesai` (PR #159 sudah di-merge).

**Cara melanjutkan**
- Sebelum merge: jalankan langkah 1–2 checklist "Plugin R1" di `AGENTS.md` (hak tabel, cek keanggotaan ganda), lalu ikuti "Urutan merge PR bermigrasi". Merge hanya oleh orang yang bisa menjalankan migrasi di VPS pada jam yang sama.
- Berikutnya `/sesi-plugin R2` (dua sesi, satu PR, review keamanan) setelah R1 di-merge dan migrasinya jalan; atau `/sesi-plugin B1` di jalur Beranda.

---

## F0 · Bootstrap repo dan CI migrasi · 2026-10-31 · pemilik produk + Claude

**Selesai** (sesi selesai; status review, PR #159, issue #137)
- `docs/plugin/`: `00-indeks.md`; `01-kajian.md` (salinan kajian di claude.ai per 31 Okt, rujukan dokumen project diganti file repo); `02-adr.md` (ADR-P1–P19, plus keputusan kajian no. 7, 9, 11 yang belum diambil); `03-workflow.md` (rencana development yang disetujui, dengan kolom issue, tabel keputusan pendukung sebagai ADR, dan template PR); `04-kontrak-api.md` v0; `05-desain-buku-usaha.md` (mockup kanvas + keputusan ruang usaha); `PROGRESS.md` (23 sesi + tabel gerbang); file ini.
- `AGENTS.md`: bagian baru "Plugin dan ruang" (sembilan aturan, flag, migrasi) dan satu butir di "Database Schema" tentang workflow "Migrasi", karena berlaku untuk semua sesi yang menyentuh model.
- `.claude/commands/sesi-plugin.md` dan `tutup-sesi-plugin.md`, turunan `/sesi` dan `/tutup-sesi` mobile.
- `.github/workflows/migrasi.yml` + `.github/scripts/cek-migrasi.sh`: di PR yang menyentuh model atau migrasi, skema awal dibuat seperti produksi (`create_all` dari model commit dasar + `alembic stamp head`), lalu `upgrade head`, `alembic check`, `downgrade` ke head dasar, `upgrade head`. Diuji lokal di PostgreSQL 16: `main` tanpa perubahan lulus; model + migrasi baru lulus; model baru tanpa migrasi gagal di `alembic check` (kode keluar bukan 0).
- GitHub: label `plugin` dan `review-keamanan` (label `migrasi` sudah ada), milestone "Plugin Fase 0 — Persiapan" sampai "Plugin Fase 5 — Beta", issue #137–#158 (satu per sesi, berlabel sesuai tanda).
- Artifact "Tracker Plugin Jatahku" di claude.ai untuk manusia.

**Digantung**
- `04-kontrak-api.md` masih v0 dari kajian. Sesi pembuat endpoint (B1, R2, R4, R5, R7, H1, H3, U1–U3) menetapkannya menjadi v1 di PR-nya sendiri. Yang paling mungkin berubah: endpoint Buku Usaha (bagian 6) dan respons 202 untuk draf persetujuan.
- Keputusan kajian no. 7 (Beranda bawaan dari pemilik), no. 9 (payment gateway), no. 11 (harga di toko aplikasi) belum diputuskan; tidak menghalangi sesi mana pun sampai V1.
- Tafsiran di `05-desain-buku-usaha.md` B1 (ruang usaha dan adminnya tidak punya akses ke ruang keluarga anggota, fitur household yang sekarang tetap ada) masih perlu dikonfirmasi pemilik produk sebelum R5.
- Sebelum beta: klausul pemrosesan data di S&K ruang usaha dan penilaian dampak ringkas UU PDP (`03-workflow.md`, "Keamanan lebih dulu").
- Dokumen "Rencana Development Plugin Buku Usaha" di claude.ai disalin dari `03-workflow.md`; perubahan rencana berikutnya dibuat di repo dulu.

**Jebakan**
- `alembic upgrade head` dari database kosong **gagal** (`relation "notification_preferences" does not exist`): migrasi awal hanya membuat 11 tabel, sisanya dibuat `create_all` saat start. Karena itu cek migrasi membangun skema dasar dengan `create_all` dari model commit dasar, bukan dari migrasi.
- `alembic check` kini menjadi gerbang untuk **semua** PR yang menyentuh `app/models/**`, termasuk sesi mobile dan AI Advisor: model yang berubah tanpa migrasi gagal. Di `main`, `alembic check` tidak menemukan selisih palsu antara model dan skema hasil `create_all` (dicek lokal), jadi kegagalan berarti selisih sungguhan.
- `cek-migrasi.sh` memakai `git worktree` pada commit dasar; di clone dangkal ambil dulu commitnya (`git fetch --depth=1 origin <sha>`, sudah ada di workflow). Butuh `psycopg2-binary` (tidak ada di `requirements-test.txt`; workflow memasangnya sendiri).
- Di lingkungan Claude Code cloud, `gh` lewat GraphQL ditolak (403): pakai REST (`gh api repos/mtyatno/jatahku/...`) untuk label, issue, dan PR.
- PostgreSQL lokal untuk uji: `initdb` dan `pg_ctl` harus dijalankan sebagai user non-root (mis. `runuser -u claude -- /usr/lib/postgresql/16/bin/pg_ctl ...`).

**Keputusan kecil**
- Cek migrasi ditambah `alembic check` (lebih ketat dari rencana yang hanya menyebut upgrade dan downgrade), karena `create_all` saat start bisa menutupi migrasi yang terlupa sampai deploy berikutnya.
- Workflow "Migrasi" hanya berjalan bila PR menyentuh model, migrasi, `database.py`, `requirements.txt`, atau file workflow itu sendiri; PR lain tidak melambat.
- Galat baru tetap memakai `detail` berupa teks (klien sekarang menampilkannya langsung) dan menambah field `kode` (`04-kontrak-api.md`, aturan 6).
- Data contoh kanvas (Dapur Nusa) diusulkan menjadi fixture tes Buku Usaha (`05-desain-buku-usaha.md` A3).

**Cara melanjutkan**
- Pemilik produk: PR ini hanya dokumen, perintah sesi, dan CI; tidak mengubah kode yang berjalan, jadi aman di-merge kapan saja. Workflow "Migrasi" ikut berjalan di PR ini (menyentuh file workflow-nya) dan harus hijau.
- Bila dikerjakan sendiri: `/sesi-plugin B1` (Beranda registry; lebih kecil, di balik flag, dan B2 dibutuhkan R6). Bila dua orang: B1 dan `/sesi-plugin R1` paralel.
- R2 adalah sesi paling berisiko (86 titik di 31 file, dua sesi di satu PR): jadwalkan setelah R1 di-merge dan saat tidak ada PR mobile atau AI Advisor lain yang menyentuh `bot/handlers.py` dan `envelope_balance.py`.
