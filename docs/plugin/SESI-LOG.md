# Plugin — catatan serah-terima

Entri terbaru di atas. Format: **Kode sesi · nama · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## R7 · Catat cepat dan kamus per ruang · 2026-11-04 · pemilik produk + Claude

**Selesai** (status review, PR #191; issue #147; label `migrasi`, `review-keamanan`; menunggu review sesi keamanan terpisah)
- Keputusan pemilik produk (4 Nov, "lanjut" atas lima usulan pembukaan sesi): **(A)** kamus ruang hanya di ruang usaha; ruang keluarga tetap belajar per user. **(B)** Tawaran "pengeluaran pribadi" dihitung di klien lewat permintaan terpisah tanpa header ruang (ruang keluarga user sendiri), tanpa kueri lintas ruang di server; `tawaran_pribadi` v0 dihapus dari kontrak. **(C)** Admin menghapus kata = juga menghapus kata user yang sama untuk amplop itu di ruang itu. **(D)** Lampiran foto nota karyawan (Kotak Struk di ruang usaha), titipan R4/R6, ditunda ke sesi sendiri. **(E)** Catat cepat juga pintu Catat pemilik/admin di ruang usaha, dengan tautan "Form lengkap".
- Server: tabel `ruang_kamus` (migrasi `d7r7k4a1m9c3`, hanya tabel baru, idempoten). `txn_nlp.cari_amplop` (urutan kata user → kamus ruang → kamus kategori → nama amplop, `Tebakan.sumber`, `amplop_boleh` untuk karyawan; `find_best_envelope` tetap pembungkus); `ajari_kamus_ruang` (upsert atomik, hanya amplop bersama aktif bertujuan pengeluaran di ruang usaha; `kata_kamus` tanpa nominal/angka/satuan, maks 12 kata + frasa). Belajar hanya dari `routes/transactions._after_saved` dengan `kamus_ruang=not is_private` (catat, batch, draf disetujui atas nama pencatat); bot dan Kotak Struk tidak. `suggest-envelope`: `sumber`, `aturan` (`peran.aturan_catatan`), request `amount`; `suggest-envelopes`: `sumber`. `GET`/`DELETE /ruang/{id}/kamus` di `ruang_kelola.py` (log `kata_dihapus`). Reset ruang dan hapus akun.
- Web: `components/CatatCepat.jsx` menggantikan `CatatKaryawan.jsx` (dihapus): satu kotak teks + suara, kartu Terdeteksi dengan sumber tebakan, aturan admin, pesan "kata ini masuk kamus", tawaran pribadi; `lib/catatCepat.js` + tes; `api.request` opsi `ruangKeluarga`, `saranCatat`, `catatDiRuangKeluarga`, `kamusRuang`, `hapusKamus`; `Layout.jsx` (pintu Catat ruang usaha, `expense-lengkap`); halaman Anggota bagian "Kata yang dipelajari"; label log; teks panel foto nota.
- Tes: `app/tests/test_ruang_r7.py` (10); diperbarui `test_ruang_pagar` (route hapus kata), `test_kotak_schema` (satu head, rantai melewati e7b3d5a9c1f4), `test_plugin_sdk` (kamus ruang sebelum kamus plugin H2, `kamus_plugin`). 13 uji mutasi semuanya tertangkap. unittest 2838 lulus · node --test 695 lulus · build ok · `openapi_cek` tanpa perubahan memutus · `cek-migrasi.sh origin/main` di PostgreSQL 16 ok · upsert bersamaan di PostgreSQL ok (3 pengajar → hitungan 3).
- Browser (Playwright, API dipalsukan): karyawan dan pemilik, 390 dan 1440 px, terang dan gelap; saran ruang usaha dengan header, saran dan catat ke ruang keluarga tanpa header; karyawan tidak memanggil `/kamus`; hapus kata dari halaman Anggota → log.
- Dokumen: kontrak §2 (kamus v1) dan §3 (Catat cepat v1); `AGENTS.md` aturan 8 + checklist "Plugin R7"; `00-indeks.md`; `PROGRESS.md`.

- **Review keamanan terpisah (5 Nov): minta perubahan.** Fokus SESI-LOG (gerbang jenis ruang di kueri kamus, belajar hanya dari catatan bukan-privat ke amplop bersama, hapus kata hanya di ruang sendiri, permintaan tanpa header) dinilai benar. Dikerjakan di branch ini, dengan tes yang gagal di kode sebelumnya dan uji mutasi:
  1. **Merah — satu `client_ref` dipakai dua ruang.** Catat cepat memakai satu ref untuk Simpan (ruang usaha) dan "Catat di ruang keluarga"; idempotensi dan `draf_dari_ref` hanya dikunci per user+ref. Respons Simpan hilang → tawaran pribadi dengan ref yang sama → server menjawab draf ruang usaha (PoC1, 202) atau transaksi Operasional (PoC2, 201), dan UI menulis "Tercatat di ruang keluargamu". Perbaikan server: kiriman ulang hanya menjawab transaksi/draf lama bila ruang, jenis, dan amplop sama, selain itu 409 `client_ref_bentrok` (`peran.ref_bentrok`, `cek_ref_draf`; `POST /transactions`, `/transactions/batch` per baris, `POST /incomes` karyawan). Klien: ref terpisah per jalur; hasil belum pasti (0, 409 diproses, 5xx) mengunci isian dan jalur lain, kirim ulang memakai permintaan yang sama persis; "di ruang keluargamu" hanya bila jawabannya amplop itu (`hasilPribadi`). Tes PoC1, PoC2, arah sebaliknya, batch, pemasukan, pembantu tanpa amplop; 7 mutasi tertangkap; Playwright: 403 pasti tidak mengunci + ref berbeda + jawaban Operasional tidak disebut ruang keluarga; koneksi putus mengunci + kirim ulang identik.
  2. **Perlu keputusan — kamus sebagai alat uji catatan orang lain (PoC3).** Keputusan pemilik produk 5 Nov: karyawan melihat tebakan kamus ruang hanya sebagai "Kamus <ruang>" (tanpa `diajarkan_oleh`, `kali`, `oleh_saya`); pemilik/admin tetap melihatnya. Kamus tetap belajar dari semua catatan bukan-privat (bukan hanya koreksi: kata baru tetap masuk, jadi tidak menutup celah). Ditambah batas: description ≤ 500, descriptions ≤ 100 (422), 60/menit `suggest-envelope` dan 20/menit `suggest-envelopes` per user (`kunci_per_user`, 429). Tes di `test_ruang_r7` dan `test_rate_limit.SaranBatasTests`.
  3. Saran tidak memblokir, ikut dikerjakan: `kali` = hitungan kata terbanyak, bukan jumlah semua kata yang cocok (3 catatan = 3×, bukan 9×); hapus kata ikut frasa user yang sama sesudah nominal/satuan dibuang (`txn_nlp.normal_kamus`).
  - Rebase ke `main` 5 Nov sesudah laporan berkala (#190, migrasi `967a27d0c15d`): migrasi R7 kini menginduk ke `967a27d0c15d`; konflik `account_deletion.py` (impor) dan `test_kotak_schema.py` (versi `main`, isinya sama) diselesaikan.
  - Sesudah perbaikan: unittest 3221 (sesudah rebase #190): 3220 lulus, 1 gagal di luar scope (`test_job_dan_notifikasi`, jam tenang; gagal juga di `main` a2f010a pada jam yang sama) · node --test 718 lulus · build ok · `cek-migrasi.sh origin/main` ok (induk `967a27d0c15d`) · `openapi_cek` tanpa perubahan memutus (batas baru tidak tergolong memutus).

**Digantung**
- Lampiran foto nota untuk karyawan (keputusan D): sesi sendiri, dengan review keamanan (unggah file di ruang usaha; belajar struk lintas user tidak boleh memuat data usaha). Sampai itu Catat cepat menahan Simpan bila aturan foto nota berlaku, dan server tetap 422 `perlu_foto_nota`.
- PR #186 (H2) di-merge saat sesi ini ditutup; branch R7 di-rebase ke `a2f010a`. Konflik di `routes/transactions.py` (`peringatan` H2 + `is_private` R7) dan `00-indeks.md` diselesaikan; di `txn_nlp.cari_amplop` kamus plugin H2 (titik `nlp_kamus`) berada sesudah kamus ruang dan sebelum kamus kategori, dengan `sumber.jenis = kamus_plugin` (baru).
- Deteksi jenis catatan (penjualan, modal) dan Kontak: U5. Pemasukan tidak mengajari kamus.
- Kamus tanpa batas jumlah baris per ruang (hanya batas 12 kata per catatan dan `limit` daftar 500); dinilai ulang dari data beta.
- `amplop_terkunci` di kontrak v0 tidak dibuat: daftar amplop karyawan sudah hanya yang diizinkan.
- Retensi (review #191): kata dari akun yang dihapus atau anggota yang keluar tetap di kamus ruang (nama pengajar dikosongkan saat akun dihapus), konsisten dengan `MerchantEnvelopeMap`. Catat di penilaian dampak UU PDP sebelum beta.
- Di luar scope (main, H2): `test_plugin_sdk.SdkDbTests.test_job_dan_notifikasi` gagal bila dijalankan di jam tenang 21.00–07.00 WIB (`proaktif.jam_tenang` memakai jam sekarang; tes tidak membekukan waktu). Ditemukan reviewer dan dicek ulang 5 Nov 04.24 WIB. CI yang berjalan pada 14.00–24.00 UTC ikut merah. Perbaikan kecil (patch `jam_tenang` di tes itu) sebaiknya PR terpisah.

**Jebakan**
- `git add -A frontend` ikut memasukkan `frontend/dist/index.html` hasil build; dikembalikan di commit terpisah. Stage per file.
- Satu kueri kamus tambahan di setiap tebakan yang kata usernya tidak cocok, termasuk ruang keluarga dan bot (kosong karena gerbang jenis ruang di kueri). Tes baru yang memalsukan `db.execute` berurutan di jalur `find_best_envelope` perlu menyediakan hasil untuk kueri itu (tes yang ada tidak terdampak).
- `pkill -f "vite preview"` di Bash membunuh shell-nya sendiri (kode 144) dan ikut menghentikan PostgreSQL lokal; jalankan ulang `pg_ctl ... start`.
- `test_kotak_schema.test_single_head_after_plugin_h1` dulu mengunci head = `e7b3d5a9c1f4`; kini satu head yang rantainya melewati revisi itu.

**Keputusan kecil**
- Pengajar di kamus = pencatat terakhir (`diajarkan_oleh`); `kali` = jumlah catatan. Karyawan melihat nama pengajar ("diajarkan Bagas"), sesuai artboard; `oleh_saya` untuk "diajarkan kamu".
- Kamus belajar dari setiap catatan yang tersimpan (bukan hanya koreksi), sama dengan kata user. Pesan "masuk kamus" hanya tampil bila amplop berbeda dari tebakan kamus/kata user.
- Amplop pribadi (`owner_id`) dan catatan privat tidak mengajari kamus, karena kamus terlihat admin.
- `aturan` juga dijawab saat keterangan kosong (nominal diketik lebih dulu); Simpan ditahan bila ada `foto_nota`, label tombol "Kirim untuk persetujuan" bila ada `persetujuan`.
- Mengosongkan kotak teks membuang pilihan amplop manual.

**Cara melanjutkan**
- Review keamanan di sesi Claude Code terpisah: "review PR #191 terhadap 03-workflow.md bagian keamanan". Fokus: gerbang jenis ruang di kueri kamus, belajar hanya catatan bukan-privat ke amplop bersama, hapus kata hanya ruang sendiri, permintaan tanpa header di klien.
- Merge oleh pemilik produk sesudah review lulus: ikuti "Urutan merge PR bermigrasi" dan checklist "Plugin R7" di `AGENTS.md` (`alembic current` = `967a27d0c15d`, laporan berkala, sebelum upgrade; migrasi R7 di-rebase ke sana 5 Nov sesudah #190). Sesudah deploy terverifikasi, PR kecil "R7 tayang" (status `selesai`).
- Berikutnya `/sesi-plugin H3` (butuh H2, B2, R4; semua selesai).

---

## H2 · PluginContext dan titik ekstensi server · 2026-11-04 · pemilik produk + Claude

**Selesai** (PR #186, issue #150; review keamanan terpisah **lulus** pada putaran keempat, 4 Nov; di-merge atas permintaan pemilik produk sesudah review lulus)
- Keputusan pemilik produk (4 Nov, "lanjut" atas empat usulan pembukaan sesi): **A** audit = setiap tulis/kiriman dan setiap penolakan izin, baca yang diizinkan tidak dicatat per panggilan; **B** metode tulis SDK (`record_income`, `record_expense`, `propose_fund_move`) ditambah di U2 bersama pemakai pertamanya; **C** notifikasi plugin tanpa migrasi (`NotificationType.system`, judul berawalan nama ruang, preferensi per jenis di U6); **D** `form_fields` hanya validasi + hook di H2, disambungkan ke body transaksi/pemasukan di U2; perintah bot plugin dijalankan per ruang yang memasang plugin, berawalan nama ruang.
- `app/plugins/sdk/`: `Plugin` (dekorator `kartu`, `cek`, `aturan_advisor`, `perintah_bot`, `job`, `field_form`, masing-masing dengan `izin=`), `PluginContext` beku dengan sesi DB privat: izin = `granted_permissions` instalasi ∩ manifest ∩ `izin=` fungsi di setiap panggilan; `envelopes`/`transactions`/`incomes`/`income`/`members` lewat `visibility.py` (amplop pribadi orang lain tidak pernah, deskripsi privat tersamar); karyawan (member di ruang usaha) ditolak data keuangan `khusus_admin`; job tanpa user hanya amplop bersama dan semua deskripsi tersamar; penolakan dan kiriman dicatat di `plugin_audit_log` lewat sesi sendiri (penolakan sama sekali per jam per proses). `Saran`, `AksiRoute`, `RencanaPengeluaran`, `NilaiTidakSah`; nominal `Decimal`.
- `host/kode.py`: impor plugin diperiksa AST **sebelum** kode dijalankan (hanya `app.plugins.sdk`, paket sendiri, plugin di `requires`; `importlib`, `__import__`, `._db` ditolak), kode dimuat dari `__init__.py` (`plugin = Plugin("<id>")`), lalu dicocokkan dua arah dengan manifest dan izinnya. `registry.py` memuatnya di kedua mode (ketat: gagal; start: plugin dan pemakainya dilewati). Plugin tanpa `__init__.py` hanya manifest.
- `host/titik.py`, satu pintu inti → plugin, semua lewat `siklus.aktif_dengan_instalasi` (baru) dan kembali tanpa kueri bila belum ada plugin yang menyumbang ke titik itu:
  - `cards`: `kartu_ruang` + `data_kartu`; tata letak dan batch menerima `plugin=` (`dashboard/{registry,layout,batch}.py`, route `dashboard.py`); kartu plugin tidak aktif diparkir / `kartu_tidak_dikenal`; payload diperiksa `rapikan_kartu` (field asing, float, batas baris, aksi hanya `route` ke `/p/<id>`).
  - `checks`: `expense_rules.peringatan_plugin` dipanggil `check_expense` (bot, `BehaviorCheckResult.peringatan`) dan `catat_transaksi` (web, field `peringatan` di respons 201); tidak untuk karyawan, tidak pernah memblokir.
  - `advisor_rules`: `saran_advisor` → `Insight(asal=plugin)` slot `daftar` saja; `select.pilih_daftar` membatasi `daftar_per_plugin` = 1; `render` memakai teks jadi dan label aksi plugin; `advisor_cache` ikut menghapus cache saat `PluginInstallation` berubah; cache yang dilayani disaring `saring_payload_advisor` (saklar darurat, flag).
  - `bot_commands`: `handlers.bot_commands()` = `perintah_plugin()` + `perintah_inti()` (`app/bot/plugin_cmd.py`); `titik.perintah` per ruang, `audience` dicek saat dipanggil, flag ruang usaha, jam kerja karyawan; teks polos.
  - `notifications`: `ctx.notify` → `kirim_notifikasi`: owner/admin yang plugin-nya aktif untuk mereka, jam tenang (`proaktif.jam_tenang`), maksimal 2 per plugin per penerima per hari + 1 per `kunci` (Redis `plugin:notif:*`, mati = tidak mengirim), link hanya `/p/<id>`.
  - `jobs`: `scheduler.plugin_jobs` (menit 23 tiap jam) → `jalankan_job`: jadwal `hourly` / `daily HH:00` di zona waktu pemilik ruang, klaim Redis sekali per periode, sesi DB sendiri.
  - `nlp_kamus`: `txn_nlp.find_best_envelope` mencoba kamus plugin aktif sebelum kamus kategori inti (hanya bila ada `user_id`).
  - `form_fields`: `periksa_field` (tipe bawaan + fungsi plugin; 422 `field_tidak_sah`).
- Manifest (Plugin API 1.1.0): `contributes.checks`, `contributes.nlp_kamus`, jadwal job baku, kode aturan advisor `XX-01` dengan domain di luar `DOMAIN_ADVISOR_INTI`.
- Tes `app/tests/test_plugin_sdk.py` (37): kode/impor/pencocokan, manifest 1.1, pemeriksa keluaran, batas per plugin, tanpa plugin tanpa kerja (db=None), konteks (visibilitas, irisan izin + audit, beku, karyawan, job, pemasukan ruang lain), HTTP Beranda (tata letak, data, jeda, saklar, flag, ruang lain, karyawan 403), peringatan web + bot, advisor (ruang, karyawan, cache, `get_dashboard`), perintah bot (audience, ruang usaha tertutup, gagal, handler teks polos), job + notifikasi (penerima, jam tenang, kunci, batas, Redis mati, link, jenis), kamus, field form. `test_plugin_host`: perintah inti dibandingkan dengan `perintah_inti()`. `test_ruang_pagar`: `plugins/host/titik.py: 3` dengan alasan.
- Dokumen: kontrak §0 (`peringatan`), §5 (titik ekstensi server v1), §7 (`field_tidak_sah`); `AGENTS.md` aturan 4; `00-indeks.md` (fase, peta kode); `PROGRESS.md`.
- Tes: unittest 2785 lulus (1 dilewati) · node --test 654 lulus · build ok · Migrasi: tidak berlaku (model dan migrasi tidak disentuh) · validator manifest: OK (0 plugin) · `openapi_cek`: tanpa perubahan memutus.
- Deploy R8 (#177, `195c17f`): terverifikasi tayang (run 41785622123). Status R6/R8 `selesai` dan Gerbang R lulus dicatat di #189 (`ruang_paritas` 109/109).

- **Review keamanan terpisah (4 Nov, `61e3ff5`):** minta perubahan; kontrol akses dasar (izin per panggilan, ruang dari host, karyawan) lulus. Semua temuan dikerjakan di branch ini, PoC reviewer kini gagal semuanya:
  1. **Sedang:** izin kirim tidak dibatasi per titik. PoC: perintah bot karyawan memicu notifikasi ke admin; cek yang dipicu admin meneruskan amplop pribadi dan deskripsi privatnya ke pemilik lewat `notify`. Sekarang `IZIN_PER_JENIS` (`host/kode.py`): kartu, cek, aturan advisor, perintah bot, field form hanya baca; `notifications:send` hanya job; dicek `cocokkan` saat muat dan `izin_efektif` saat berjalan. `notify` juga menolak konteks yang punya user (`bukan_job`).
  2. **Sedang:** `incomes()`/`income()` tidak melewati kontrak visibilitas (member ruang keluarga membaca gaji owner, job juga). Sekarang di ruang keluarga hanya pemasukan milik viewer (lihat review ulang no. 5); ruang usaha tetap utuh untuk owner/admin/job.
  3. **Sedang:** `ctx.viewer` adalah objek ORM `User` yang terikat sesi (email, hash kata sandi, sesi DB lewat `object_session`; PoC: `is_admin`/`plan` ikut ter-commit). Sekarang `PenggunaView` beku (`id`, `nama`, `zona_waktu`).
  4. **Rendah:** konteks "beku" dan AST mudah dilewati (`dataclasses.replace` mengganti ruang dan izin; impor `sdk.context` memberi `sesi()` dan bisa menekan audit; `getattr`/`vars`/`object.__setattr__`). Sekarang keadaan konteks ada di host (`host/keadaan.py`, `WeakKeyDictionary`), `PluginContext` tanpa atribut (slots, tidak bisa diubah/disalin, konteks palsu gagal); sesi tambahan dan audit pindah ke host; AST hanya mengizinkan `from app.plugins.sdk import <nama di __all__>`, menolak `sys`/`gc`/`inspect`/`ctypes`/`builtins`/`importlib`, `eval`/`exec`/`compile`/`globals`/`locals`/`vars`, `getattr`/`setattr`/`delattr`/`hasattr` dengan nama dinamis atau berawalan `_`, dan atribut dunder (kecuali `__name__`, `__doc__`, `__init__`, `__post_init__`).
  5. **Rendah:** job tidak memeriksa flag `ruang_usaha_users`. Sekarang ruang usaha di luar flag pemiliknya dilewati.
  6. **Info:** audit kiriman membanjir (setiap `notify` satu baris walau 0 terkirim). Sekarang hanya bila ada yang terkirim; `notify` maksimal 10 per konteks (`batas_notify`); tabel penolakan membuang 10% tertua saat penuh, bukan dikosongkan.
  7. **Info:** float di `Saran.rupiah`/`urgensi`, `Decimal` NaN/Infinity, dan `re.match` + `$` (tautan berakhiran baris baru). Sekarang ditolak; `re.fullmatch`.
  - Tes +7 (44): izin per jenis, jalan pintas AST, keluaran ketat, notify hanya dari job, pemasukan ruang keluarga, job ruang usaha tertutup, audit kiriman + batas notify; tes konteks kini memeriksa tidak bisa diubah/disalin dan `viewer` bukan ORM.
- **Review ulang (4 Nov, `77d5cd0`):** temuan 1–3 dan 5–7 tertutup; minta perubahan untuk temuan 4 yang baru tertutup sebagian dan temuan baru, semua dikerjakan (PoC `poc_h2.py` dan `poc_h2b.py` kini gagal semuanya):
  1. **Sedang:** kelas `PluginContext` bisa ditambal (`PluginContext._perlu = …`, properti `ruang_id`/`user_id` ditimpa) atau diturunkan dengan hash peniru, sehingga satu baris plugin mematikan izin untuk semua plugin. Sekarang metaclass menolak menambal/menghapus atribut kelas, `__init_subclass__` menolak turunan, `keadaan.ambil` mewajibkan `type(ctx) is PluginContext` dan mencocokkan identitas (`id` + `weakref`, bukan `__hash__`/`__eq__`), pemeriksaan izin (`perlu`, `tolak`) menjadi fungsi host, dan setiap metode serta `kirim_notifikasi` membaca ruang/viewer/peran dari keadaan host.
  2. **Rendah:** AST masih daftar larangan (`operator.attrgetter("__globals__")`, `pkgutil.resolve_name`, `os.environ`). Sekarang pustaka di luar `app` hanya dari daftar izin `PUSTAKA_BOLEH`; menugasi/menghapus atribut nama SDK dan menurunkan kelas SDK ditolak.
  3. **Rendah:** `ctx._tolak` bisa memalsukan dan membanjiri audit. Sekarang tidak ada metode `_tolak`/`_perlu` di konteks, dan AST menolak atribut berawalan `_` pada objek selain `self`/`cls`.
  4. **Rendah:** `Periode` batch diteruskan apa adanya ke kartu plugin, jadi plugin bisa mengubah periode kartu inti sesudahnya. Sekarang kartu menerima `PeriodeView` beku.
  5. **Info:** pemasukan anggota lain di ruang keluarga masih terlihat per baris (nominal, tanggal). Sekarang plugin di ruang keluarga hanya membaca pemasukan milik viewer, seperti `GET /incomes/`; job tidak membaca pemasukan ruang keluarga. Bila plugin rumah tangga nanti butuh total ruang, tambahkan metode agregat lewat keputusan pemilik produk.
  - Tes 45: kelas tidak bisa ditambal/diturunkan, AST daftar izin + `_`/tambal/turunan, pemasukan ruang keluarga hanya milik viewer, kartu menerima periode beku.
- **Review ulang kedua (4 Nov, `d4d1e5d`):** temuan review ulang 1–5 tertutup; minta perubahan untuk satu temuan baru, dikerjakan (PoC `poc_h2c.py` kini gagal):
  1. **Sedang:** konteks tetap sah sesudah fungsi plugin selesai; plugin yang menyimpan `ctx` di variabel modul (bug multi-tenant yang lazim) membaca ruang, izin, dan sesi DB panggilan pertama untuk user lain (PoC: Orang menerima transaksi Dapur Nusa). Sekarang host memanggil setiap fungsi plugin lewat `titik.panggil`, yang menutup konteks di `finally` (`keadaan.tutup`); konteks simpanan gagal `KonteksTidakSah`.
  2. **Rendah:** introspeksi bingkai (`cr_frame`/`gi_frame`/`f_globals`/`f_back`) dan pengambilan atribut tanpa simpul `Attribute` (`string.Formatter().get_field`, `reduce(getattr, …)`) mencapai modul host; `Keadaan` bisa diubah; kelas `Plugin` bisa ditambal lewat alias. Sekarang atribut bingkai ditolak AST, `getattr`/`setattr`/`delattr`/`hasattr`/`vars`/… hanya boleh dipanggil langsung, `string` keluar dari `PUSTAKA_BOLEH`, `Keadaan` beku (penghitung `notify` terpisah), dan `Plugin` memakai metaclass beku yang sama dengan `PluginContext` (tidak bisa ditambal atau diturunkan).
  - Tes 46: konteks simpanan tidak berlaku untuk user lain, konteks ditutup sesudah `panggil`, kelas `Plugin` beku, AST bingkai/`getattr` sebagai nilai/`string`.
- **Review ulang ketiga (4 Nov, `a086cab`): lulus.** Sisa Rendah/Info ikut ditutup sebelum merge (PoC `poc_h2d.py` kini gagal atau ditolak validator):
  1. **Rendah:** konteks permintaan lain yang sedang berjalan bersamaan bisa dipinjam lewat variabel modul. Sekarang konteks terikat ke task asyncio pembuatnya (`keadaan.ambil` menolak task lain).
  2. **Rendah:** `typing.get_type_hints` mengevaluasi anotasi teks sebagai kode. Sekarang `get_type_hints`, `ForwardRef`, `evaluate_forward_ref`, `_eval_type` ditolak (nama, atribut, impor).
  3. **Info:** `str.format`/`format_map` menelusuri atribut lewat teks di luar AST. Sekarang `.format`/`.format_map` ditolak; f-string tetap boleh.
  4. **Info (kegunaan):** API `namedtuple` berawalan `_` (`_replace`, `_asdict`, `_fields`, `_make`) dikecualikan dari aturan atribut `_`.

**Digantung**
- Metode tulis SDK (`record_income`, `record_expense`, `propose_fund_move`) dengan `client_ref` dan audit tulis: U2 (keputusan B). `funds:move` tetap lewat `/advisor/plan` → `/advisor/execute`.
- `form_fields` belum disambungkan ke `POST /transactions/` dan `POST /incomes/`, dan penyimpanannya di tabel plugin belum ada: U2 (keputusan D).
- Peringatan `checks` hanya di `POST /transactions/` (web) dan `check_expense` (bot, belum ditampilkan bot; ruang keluarga belum punya plugin). `POST /transactions/batch` dan pemasukan belum.
- Akses plugin ke tabelnya sendiri (`p_<id>_*`) lewat SDK: U1, bersama tabel pertama. Sekarang plugin tidak punya sesi DB sama sekali.
- `bot_callbacks` plugin belum didaftarkan; menu perintah Telegram per chat per peran (scope chat): U6.
- Notifikasi untuk karyawan (ADR-P19), preferensi per jenis notifikasi, dan email: U6. `Notification.type` plugin = `system`.
- `GET /dashboard/cards` belum memuat kartu plugin; frontend belum menggambar kartu plugin: H3 (`GET /plugins/contributions`).
- Titik `settings` (form JSON Schema + validasi server) belum ada; `pasang` tetap menolak `pengaturan`. `ctx.settings()` membaca `plugin_installations.settings` apa adanya.
- Job pembersih arsip (ADR-P15, pemberitahuan 7 hari + hapus `p_*`) masih belum dijadwalkan: butuh tabel plugin (U1).
- Saran plugin dari cache yang disaring (saklar darurat/flag) hanya dibuang; `sisa` tidak dinaikkan ke `items` sampai cache dihitung ulang (paling lama sampai ganti hari atau ada tulis data keuangan).
- Batas laju tulis per plugin per ruang (01-kajian "Penegakan") menyusul bersama metode tulis (U2).

**Jebakan**
- **R6 (#185) di-merge lebih dulu (4 Nov):** `main` digabung ke branch H2. Penyatuan: `layout.efektif/ambil/_rapikan/validasi/simpan` dan `batch.jalankan` memakai keyword `karyawan=` (R6) dan `plugin=` (H2); peran Beranda tetap dihitung di layout/batch dari keanggotaan (R6). Kartu plugin selalu `untuk="umum"`: untuk karyawan `visible: false` di tata letak, `khusus_admin` di data tanpa memanggil penyedia, dan `kartu_tidak_dikenal` saat ditambahkan (tes `test_kartu_saklar_flag_dan_ruang_lain` diperbarui; sebelumnya karyawan 403). `AGENTS.md` aturan 3 (R6) dan 4 (H2) digabung.
- `test_ruang_pagar` menghitung `HouseholdMember.user_id ==`: peran di satu ruang pakai `ruang.keanggotaan`; kueri baru butuh baris `DIIZINKAN` dengan alasan.
- `test_plugin_host` membandingkan `PERINTAH_INTI` dengan `perintah_inti()`, bukan `bot_commands()` (yang kini ikut memuat perintah plugin).
- Jalur web pengeluaran tidak memanggil `check_expense` (memakai `check_behavior` langsung), jadi peringatan plugin dipanggil terpisah di `catat_transaksi`. Jalur baru wajib memanggil `expense_rules.peringatan_plugin` juga.
- Tes yang memakai kartu/plugin di ruang usaha butuh `AppSetting ruang_usaha_users` dan `plugin_<id>_users`; audit plugin memakai sesi sendiri, jadi tes memasang `pakai_sesi(Session)`.
- Fungsi plugin yang ditolak izin di kartu Beranda tercatat sebagai `logger.exception` di batch (jejak lengkap) lalu `gagal_memuat`; itu tanda bug plugin, bukan galat inti.
- `npm run build` mengubah `frontend/dist/`: `git checkout -- frontend/dist` sebelum commit.

**Keputusan kecil**
- Plugin API 1.1.0 (minor): manifest yang memakai `checks`/`nlp_kamus` sebaiknya menyatakan `>=1.1 <2.0`.
- Pemeriksaan impor/`._db` menjaga disiplin T1 (kode sendiri yang direview), bukan sandbox; mitra (T2) butuh isolasi sungguhan.
- Plugin dengan kode wajib lengkap (setiap kontribusi server punya fungsi); plugin tanpa kode hanya manifest, kontribusi servernya tidak berbuat apa-apa.
- Nominal dari plugin harus `int`/`Decimal` (float ditolak), dikirim sebagai string desimal; `bar` 0–1 boleh pecahan.
- Batas: 3 peringatan total (2 per plugin), 5 saran per aturan, 1 saran per plugin di daftar, 2 notifikasi per plugin per penerima per hari, kartu `list` ≤ 8 / `table` ≤ 10 baris / `series` ≤ 62 titik.
- Fungsi plugin di jalur permintaan tidak diberi timeout (membatalkan kueri di sesi permintaan bisa merusak sesinya); yang lewat 150 ms dicatat di log.
- Perintah bot di luar plugin aktif menjawab "Perintah ini belum tersedia di ruangmu." (tanpa nama plugin, supaya plugin yang belum dirilis tidak bisa ditebak).

**Cara melanjutkan**
- Review keamanan terpisah lulus (empat putaran, 4 Nov; PoC reviewer di scratchpad sesi, tidak di repo). Merge tanpa migrasi; tidak ada langkah VPS. Sesudah merge: `/cek-deploy 186`.
- Pemeriksaan AST adalah disiplin T1, bukan sandbox: plugin mitra (T2) tetap butuh isolasi proses sungguhan. Menambah pustaka untuk plugin = PR yang mengubah `PUSTAKA_BOLEH` (U1 kemungkinan butuh pustaka untuk tabel plugin; buka lewat SDK bila bisa).
- Berikutnya `/sesi-plugin H3` (butuh H2, B2, R4) atau `/sesi-plugin R6`.

---

## R6 · Halaman Anggota dan batasan, Beranda karyawan · 2026-11-04 · pemilik produk + Claude

**Tayang 4 Nov 2026:** PR #185 di-merge (`d229e92`), deploy terverifikasi (run 41811270106). Pemilik menjalankan checklist "Plugin R6": `ruang_paritas` 109 user · ok 109 · beda 0 · crash 0 (kode keluar 0, juga menutup paritas R8), dan uji dua akun (undang, gabung dengan kode, tampilan karyawan, batas nominal, persetujuan) sesuai, sekaligus menutup uji alur karyawan yang tersisa dari checklist R5. R6 `selesai`. Jebakan saat uji: flag `ruang_usaha_users` sempat diisi dua id tanpa koma, sehingga tidak ada user yang cocok; dicatat di checklist R6 (`AGENTS.md`). Usulan lanjutan (belum diputuskan pemilik): panel "Fitur beta" di halaman Admin untuk mengisi flag tanpa SQL (`PUT /admin/settings/{key}` sudah ada), atau undangan dari ruang usaha di flag sebagai tiket masuk karyawan tanpa flag sendiri (mengubah keputusan R5, butuh review keamanan).

**Selesai** (status review, PR #185; issue #146; label `review-keamanan` atas usulan pembukaan sesi walau rencana tidak bertanda review: R6 membuka `/dashboard/*` untuk karyawan, bagian gerbang "Karyawan tidak melihat laporan")
- Keputusan pemilik produk (4 Nov, "lanjut" atas lima usulan pembukaan sesi): **(1)** admin boleh mengundang admin, menaikkan, menurunkan, dan mengeluarkan admin lain; hanya owner terlindung — dicatat di ADR-P4 (review #175 no. 8). **(2)** Tanpa batas kumulatif harian karyawan selama beta (no. 10; A4 dicoret). **(3)** Antrean persetujuan di halaman Anggota + angka di menu; kartu Beranda usaha dinilai di U4 (A4). **(4)** Daftar/cabut undangan dan ganti nama ruang masuk R6; tutup/hapus ruang usaha ditunda. **(5)** Kartu Catat karyawan membuka form Catat — dikerjakan dengan form karyawan sendiri (lihat keputusan kecil).
- Server: `registry.CardDef.untuk` (`umum` | `karyawan`), enam kartu `core.karyawan.*`, `TEMPLATE_KARYAWAN`, `registry.boleh`. `layout.py` (template per peran, `visible: false` + `alasan` untuk kartu peran lain, `PUT` menolak kartu peran lain kecuali instans lama dikirim balik, `hapus_milik`), `batch.satu_kartu` (kartu umum untuk karyawan → `khusus_admin` tanpa memanggil penyedia), `routes/dashboard.py` (`untuk` di `GET /layout`, karyawan selalu `enabled`, katalog per peran, `GET /cards` kini memakai `ruang_aktif`), lima route dashboard di `KARYAWAN_BOLEH`. Sumber `amplop_diizinkan` (handler `list_envelopes`), `draf_saya`, `catatan_hari_ini` (`peran.py`; `GET /persetujuan/saya` memakai `draf_saya`).
- `ruang_kelola.py`: `GET`/`DELETE /ruang/{id}/undangan` (cabut atomik terhadap `/ruang/gabung`), `PATCH /ruang/{id}` (nama), ganti peran dan keluar membuang tata letak Beranda anggota di ruang itu, `oleh_nama`/`anggota_nama` di log. `GET /ruang`: `jenis_catatan` untuk karyawan.
- Web: `lib/ruangPeran.js` (akses, rute, menu, Catat karyawan, payload/hasil Catat, ringkasan batasan, form batasan, label log) + tes; `pages/RuangKelola.jsx` (`/ruang`: antrean, anggota, panel batasan tersimpan otomatis, peran/jabatan, keluarkan/keluar, undangan buat/salin/cabut, nama ruang, log); `pages/BerandaKaryawan.jsx` + `cards/karyawan/` (layar tutup di luar jam kerja); `components/CatatKaryawan.jsx`; `Layout.jsx` (menu, Catat dan FAB per peran, halaman ditahan sampai peran diketahui, pengalihan rute, angka antrean, Papan disiplin/langganan/Telegram prompt/Kotak Struk tidak untuk karyawan); `RuangPicker.jsx` (Gabung dengan kode, tautan Anggota); `Settings.jsx` (kartu ruang usaha menggantikan household di ruang usaha; ekspor dan reset disembunyikan untuk karyawan); `Transactions.jsx` (tanpa AI Advisor untuk karyawan).
- Tes: `app/tests/test_ruang_r6.py` (13); uji mutasi 6 pemeriksaan (boleh di batch, layout, katalog; cabut; filter user dan ruang di catatan hari ini) semuanya tertangkap. Diperbarui: `test_dashboard_registry` (katalog umum), `test_ruang_r4` (field `jenis_catatan`), `test_ruang_pagar` (route R6). unittest 2761 lulus · node --test 662 lulus · build ok · Migrasi: tidak berlaku · `openapi_cek`: tanpa perubahan memutus.
- Diperiksa di browser (Playwright, API dipalsukan): karyawan dan pemilik, 390 dan 1440 px, terang dan gelap; karyawan tidak memanggil satu pun endpoint tertutup; alur simpan otomatis batasan, setujui draf, dan Catat karyawan 202 → "menunggu persetujuan admin".
- Dokumen: kontrak §2 (undangan, nama ruang, log, `jenis_catatan`, tabel karyawan), §4 ("Beranda karyawan"), §7; ADR-P4; `05-desain-buku-usaha.md` A4; `AGENTS.md` aturan 3 + checklist R6; `00-indeks.md`; `PROGRESS.md` (R6 review, Gerbang R).
- Deploy R8 (#177, `195c17f`) terverifikasi tayang (run 41785622123).

- **Review keamanan terpisah (4 Nov):** minta perubahan; gerbang `/dashboard/*` untuk karyawan dinilai benar. Semua temuan dikerjakan di branch ini, dengan tes yang gagal di kode sebelumnya dan uji mutasi:
  1. **Merah:** kode undangan buatan admin tetap berlaku setelah admin itu dikeluarkan, keluar, atau diturunkan (bisa masuk lagi sebagai admin dan melihat laba/kas selama 7 hari). Sekarang `/ruang/gabung` menolak kode yang pembuatnya bukan lagi owner/admin ruang itu (juga `dibuat_oleh` NULL), dan keluar/dikeluarkan/diturunkan mencabut undangan aktif buatan anggota itu dalam commit yang sama (`undangan_dicabut`, `alasan`). Tes P1, P2, keluar sendiri, lapis kedua di gabung.
  2. **Keamanan:** nilai bawaan `karyawan=None/False` membuat pemanggil yang lupa mendapat tampilan admin. Sekarang `batch.jalankan` dan `layout.ambil`/`simpan` menghitung peran sendiri dari (user, ruang) lewat `layout.peran_karyawan`; `registry.katalog`, `template`, `layout.efektif`, `validasi`, `_rapikan` tanpa nilai bawaan. Tes pemanggilan langsung.
  3. Kirim balik instans peran lain kini dari salinan server (ukuran/pengaturan klien diabaikan).
  4. Cache Beranda per peran (`cacheKeyLayout/Data(uid, 'karyawan')`); BerandaKaryawan membuang cache umum ruang itu; `Layout.jsx` membuang semua cache Beranda ruang aktif bila peran berubah (`peranBerubah`).
  5. `daftar_undangan` menyaring kedaluwarsa di SQL + batas 50; `UbahRuang` mewarisi `RuangBuat` (`NAMA_MAKS`); `CardDef.untuk` divalidasi terhadap `UNTUK`.
  - Tes `/ruang/gabung` di R6 mereset batas laju (`ruang_kelola.limiter.reset()`): batas 10/menit di memori proses terbawa antar tes.
  - Rebase ke `main` 5 Nov sesudah laporan berkala (#190, migrasi `967a27d0c15d`): migrasi R7 kini menginduk ke `967a27d0c15d`; konflik `account_deletion.py` (impor) dan `test_kotak_schema.py` (versi `main`, isinya sama) diselesaikan.
  - Sesudah perbaikan: unittest 2766 lulus · node --test 663 lulus · build ok · `openapi_cek` tanpa perubahan memutus.
- **Review ulang (4 Nov, `1e7f4f6`): lulus, boleh merge dari sisi keamanan.** Dua catatan non-penghalang ikut dikerjakan:
  - `batch.jalankan` dan `layout.ambil` menentukan peran dari keanggotaan (`layout.peran_beranda`: karyawan / umum / bukan anggota). Bukan anggota → `ruang_tidak_diizinkan` per kartu (dan 403 di `ambil`), juga untuk pemanggil langsung (plugin H2). Tidak bergantung lagi pada `izin_pengelola_aktif()`: di dalam `atas_izin_pengelola()` karyawan tetap karyawan. Batasan untuk kartu dari `peran.batasan_anggota`.
  - `_cabut_undangan_milik` memakai UPDATE bersyarat (`dipakai_at`/`dicabut_at` kosong, `RETURNING peran`), sama dengan `cabut_undangan`: kode yang sedang diklaim tidak ikut tercatat dicabut.
  - Tes +2 (orang luar dan jalur persetujuan; kode terpakai tidak dicabut); 3 uji mutasi tertangkap. unittest 2768 lulus · `openapi_cek` tanpa perubahan memutus.

**Digantung**
- Kamus kata ruang di halaman Anggota dan Catat cepat yang menggantikan `CatatKaryawan`: R7. Foto nota untuk karyawan (Kotak Struk di ruang usaha) juga R7; sampai itu, batasan "wajib foto nota" membuat catatan karyawan di atas nominal itu ditolak 422 `perlu_foto_nota` (panel batasan menyebutnya).
- Tutup/hapus ruang usaha belum ada (keputusan 4).
- Notifikasi ke admin saat draf baru dan ke karyawan saat diputus: U6. Karyawan melihat statusnya di kartu Menunggu persetujuan.
- "Urungkan" di halaman Anggota (artboard) belum ada; setiap perubahan tercatat di log ruang.
- Bottom nav HP tanpa item Anggota (sudah 5 item, pertanyaan A4 ke H3); di HP dibuka dari pemilih ruang atau Pengaturan.
- Pemilik/admin di ruang usaha: Telegram prompt, Kotak Struk, ekspor, dan reset tetap membaca ruang aktif (perilaku R4/R5, tidak diubah).
- Bawaan batasan anggota yang diundang lagi tetap tanpa batas nominal (catatan R5); daftar anggota menampilkan batas nominal tiap karyawan.
- R8 di `PROGRESS.md` masih `review`: deploy terverifikasi, sisa `ruang_paritas` di VPS lalu PR kecil "R8 tayang".

**Jebakan**
- Sumber Beranda memanggil handler route langsung (tanpa `ruang_aktif`), jadi gerbang karyawan untuk kartu harus di `batch.satu_kartu` (`registry.boleh`), bukan hanya `KARYAWAN_BOLEH`. Kartu baru yang memuat angka ruang selalu `untuk="umum"`.
- Sebelum `GET /ruang` menjawab, peran belum diketahui: `Layout.jsx` menahan halaman bila ada ruang tersimpan (`menungguPeran`) dan menyimpan daftar ruang di cache per ruang (`ruang_daftar`); tanpa itu Beranda lama dan halaman lain sempat memanggil endpoint tertutup.
- `api.getEnvelopeSummary` mengembalikan `[]` (bukan melempar) pada 403: form yang memakainya kosong untuk karyawan tanpa `lihat_saldo`.
- `normalizeAction` menolak jenis aksi yang tidak dikenal: kartu Catat mengirim `expense`/`income`, dan `Layout.jsx` memetakannya ke form karyawan.
- Mengimpor kelas tes ke modul tes lain membuat tesnya ikut jalan dua kali: `test_ruang_r6.py` mengimpor modul `test_ruang_peran`, bukan kelasnya.
- `envelopes.emoji` bisa token ikon (`food`), jadi kartu mengirim `emoji` terpisah dari nama amplop.

**Keputusan kecil**
- Karyawan memakai `CatatKaryawan` (nominal, keterangan, satu amplop; penjualan dialokasikan penuh ke amplop itu; `client_ref` per form), bukan form Catat/Income lama, karena form lama memanggil ringkasan saldo, alokasi, dan scan yang tertutup untuk karyawan.
- Menu karyawan: Beranda, Transaksi (hanya catatannya), Pengaturan; halaman lain dialihkan ke Beranda.
- Kartu karyawan ukuran M, template a1–a6; "hari ini" = `transaction_date`/`income_date` di zona user; periode diabaikan.
- Ganti peran dan keluar menghapus tata letak Beranda anggota itu di ruang itu; instans `visible: false` boleh dikirim balik apa adanya.
- `PATCH /ruang/{id}` untuk owner dan admin; daftar undangan menampilkan kode utuh ke owner/admin (mereka bisa membuat kode baru pula).
- Admin tidak bisa mengubah perannya sendiri di halaman Anggota (mencegah turun tanpa sengaja), tetapi bisa keluar.
- Warna status draf per tema (kontras A2 butir 10); angka antrean merah #DC2626.

**Cara melanjutkan**
- Review keamanan selesai (review ulang lulus 4 Nov). Merge oleh pemilik produk: tanpa migrasi; checklist "Plugin R6" di `AGENTS.md` (`ruang_paritas` + uji dua akun). Sesudah deploy terverifikasi, PR kecil "R6 tayang" (status `selesai`).
- Berikutnya `/sesi-plugin R7` (Catat cepat dan kamus per ruang; butuh R6) atau `/sesi-plugin H2`.

---

## R8 · Prive dua sisi · 2026-11-01 · pemilik produk + Claude

**Tayang 4 Nov 2026:** PR #177 di-merge (`195c17f`), deploy terverifikasi (run 41785622123); `ruang_paritas` di produksi 109/109 ok (dijalankan sesudah deploy R6). R8 `selesai`; Gerbang R lulus.

**Selesai** (status review, PR #177; issue #148; **wajib review keamanan terpisah sebelum merge** atas keputusan pemilik 1 Nov, walau di rencana tidak bertanda "review": ini satu-satunya jalur tulis lintas ruang dan bagian gerbang "Ruang keluarga tetap pribadi")
- Keputusan pemilik produk (1 Nov): **A** — prive tanpa migrasi. Kedua sisi di `incomes` dengan `kind = "prive"` (nilai baru di kolom String): keluar di ruang usaha = Income bernilai 0 + alokasi `-jumlah` di amplop asal; masuk di ruang keluarga pemilik = pemasukan sungguhan ke Tabungan. Prive tidak pernah menjadi transaksi pengeluaran, jadi tidak menjadi beban dan tidak mengurangi laba (U3).
- `POST /prive` (`app/api/routes/prive.py`): ruang asal dari amplop (`ruang_amplop`, ikut saklar flag `ruang_usaha_users` dari R4 → 404 di luar flag); hanya `owner` ruang usaha (403 `prive_hanya_pemilik`); amplop ruang keluarga 400 `bukan_ruang_usaha`; ruang tujuan = ruang keluarga pemanggil dari server (`ruang_keluarga_id`), header tidak dipakai; tanpa ruang keluarga 400 `tanpa_ruang_keluarga`; sisi masuk tidak boleh melebihi sisa amplop; tanggal bawaan hari ini (zona user), masa depan ditolak; kunci kedua household dalam urutan tetap; satu commit; idempoten `client_ref` di namespace Redis `txnref:{user}:prive:{ref}`; notifikasi target ruang keluarga sesudah commit.
- `fund_shift.record_prive` + `prive_descriptions`; `IncomeKind.PRIVE`; docstring `LintasRuang`/`ruang.py`.
- Tes `app/tests/test_prive.py` (23): dua sisi + saldo + tanpa transaksi, header tidak mengubah tujuan, riwayat per ruang, Tabungan dipakai ulang, admin/karyawan, flag tertutup, amplop keluarga/orang lain/pribadi anggota/nonaktif/tidak ada, melebihi sisa, jumlah tidak sah, tanggal, tanpa ruang keluarga, ruang orang lain tak tersentuh, kirim ulang, ref tidak tertukar dengan transaksi, gagal di tengah tanpa sisa + ref bisa dicoba lagi, pagar chat tanpa jalur prive. Pagar ruang: `POST /prive` di kelompok "objek". `test_ruang_model`: konstanta `IncomeKind.ALL`.
- Dokumen: kontrak §1, §2 (Prive v1), §7 (3 kode baru); `AGENTS.md` aturan 8 + checklist R8; `00-indeks.md`; `PROGRESS.md` (R3 dan R4 `selesai`, R8 `review`, Gerbang R).
- Tes: unittest 2416 (1 gagal = `test_basic_quota_bot_fund_shift_finishes_started_input`, gagal juga di `main`) · node --test 628 lulus · build ok · `cek-migrasi.sh origin/main` di PostgreSQL 16: ok · `openapi_cek`: tanpa perubahan memutus.
- Deploy R4 (#174, `2125226`): terverifikasi tayang (run 41295031430).

- **Review keamanan terpisah (4 Nov):** minta perubahan; kontrol akses lulus. Semua temuan dikerjakan di branch ini:
  1. **Sedang:** prive bertanggal mundur melewati cek sisa amplop (alokasi jatuh ke periode yang rollover-nya sudah dihitung; PoC 3× Rp1 jt bertanggal 40 hari lalu dari amplop Rp1 jt lolos). Sekarang tanggal hanya di periode berjalan (`get_budget_period(payday user, date.today())`, sumber yang sama dengan `compute_envelope_summaries`); bawaan `min(hari ini user, akhir periode)`.
  2. **Rendah:** idempotensi fail-open padahal prive tidak bisa dibatalkan. Sekarang `strict=True` (`RedisTidakTersedia` → 503), pemeriksaan `client_ref` di bawah kunci household, dan hasil disimpan ke Redis **sebelum** commit (commit gagal → kunci dihapus; kunci yang menunjuk baris tak ada = basi).
  3. **Rendah:** ruang nama kunci: `idempotency._key` kini punya `scope`; prive memakai `priveref:{user}:{ref}`, transaksi/advisor tetap `txnref`.
  4. **Rendah:** `notify_goals_reached` sesudah commit dibungkus try (tidak lagi 500 sesudah commit).
  - Tes +7 (30): tanggal sebelum periode (termasuk PoC 40 hari), awal periode boleh, Redis mati → 503 tanpa baris, simpan hasil gagal → 503 tanpa baris lalu kirim ulang 201, tanpa `client_ref` tidak butuh Redis, kunci basi, notifikasi gagal → 201; ruang nama kunci. Tiga tes baru dibuktikan gagal di route lama. unittest 2739 lulus · `openapi_cek` tanpa perubahan memutus.
- **Review ulang (4 Nov, `d1df20a`):** tanggal mundur tertutup; minta perubahan untuk temuan baru, semua dikerjakan:
  1. **Sedang:** cek sisa dan batas tanggal memakai siklus ruang keluarga (`users.payday_day`), padahal ruang usaha selalu bulan kalender (`USAHA_PAYDAY`). PoC: gajian keluarga tgl 25, amplop usaha Rp1 jt dari rollover Oktober → prive Rp1 jt 10 Nov dan 26 Nov sama-sama 201. Sekarang `compute_envelope_summaries(…, payday_day=)` (parameter aditif) memakai `household_payday` ruang usaha; tanggal = irisan periode berjalan kedua ruang; satu sumber "hari ini" (`date.today()`, sama dengan perhitungan saldo).
  2. **Rendah:** commit ambigu (COMMIT sampai, jawaban hilang) bisa dobel karena `except` memanggil `forget`. Sekarang `release` (hanya status pending); commit yang benar-benar gagal dikenali sebagai kunci basi.
  3. **Rendah:** `client_ref` wajib (422) selagi belum ada klien, supaya tidak menjadi perubahan memutus nanti.
  4. **Rendah:** panggilan Redis strict memakai timeout 2 detik (dipanggil sambil memegang kunci dua household).
  5. **Info:** cek tanggal dipindah ke sesudah lookup `client_ref`; kiriman ulang yang melewati pergantian periode mengembalikan jawaban lama. Cek akses tetap di depan.
  - Tes 34 (+4 baru, 1 diganti): siklus ruang usaha (PoC tgl 25 dengan tanggal dipatok), commit ambigu, `client_ref` wajib, timeout Redis, kiriman ulang sesudah ganti periode. Kelimanya gagal di `d1df20a`. unittest 2743 lulus · `openapi_cek` tanpa perubahan memutus.

**Digantung**
- **Temuan di luar PR ini (review ulang #177):** saldo ruang usaha dihitung dengan `users.payday_day`. Bagian saldo (ringkasan, geser dana, cocokkan saldo, cek pengeluaran) dikerjakan di PR terpisah `fix/siklus-ruang-usaha` (`household_cycle.payday_ruang`); tampilan dan laporan (analitik, export, riwayat pemasukan, langganan, AI Advisor) masih terbuka, dicatat di `docs/siklus-household.md`.
- UI prive (menu Catat ▾ "Prive ke Rumah tangga", FAB di HP) belum ada; R8 hanya server. Riwayat pemasukan web melewati sisi keluar (`type: "transfer"`, `transfer: null`) — tampilkan saat UI ruang usaha digarap.
- Hapus/batalkan prive belum ada (tidak ada endpoint hapus pemasukan sama sekali). Bila ditambah: hapus kedua sisi bersama; penghubung dua baris belum ada (hanya tanggal, nominal, keterangan).
- Sisi masuk dihitung `Income.amount > 0`, jadi ikut meredam pengingat gajian (`payday_reminder.py`) dan masuk total pemasukan analitik ruang keluarga. Dianggap benar (prive = gaji pemilik), tetapi belum diputuskan pemilik produk.
- AI Advisor BU-02 (prive melebihi laba) dan `di_luar_laba_rugi.prive` di U3 membaca `incomes.kind = prive` di ruang usaha.
- `test_basic_quota_bot_fund_shift_finishes_started_input` masih gagal di `main`.

**Jebakan**
- `main` bergerak (R4 #174) saat sesi: konflik di `app/main.py` dan dokumen plugin. Sesudah rebase, semua tes prive 404 karena R4 menutup ruang usaha di luar flag `ruang_usaha_users`: tes ruang usaha baru harus mengisi `AppSetting(ruang.FLAG_RUANG_USAHA, "*")`.
- Income bernilai 0 dianggap transfer di banyak tempat (`incomes.py`, `advisor/metrics.py`, `account_deletion.py`, analitik menyaring `amount > 0`). Sisi keluar prive tidak berpasangan seperti transfer (alokasi net negatif): `parse_transfer` mengembalikan None.
- `idempotency` memakai kunci `txnref:{user}:{ref}` bersama transaksi; prive memberi awalan `prive:` supaya `client_ref` tidak tertukar.

**Keputusan kecil**
- Sisi masuk selalu ke Tabungan ruang keluarga (seperti `POST /incomes/` tanpa alokasi); pemilik menggeser sendiri bila perlu. Tidak ada `ke_amplop_id` di v1.
- Jawaban 201 berisi `keluar`/`masuk` dengan `income_id`, `ruang_id`, `amplop`, plus `jumlah`, `tanggal` (kontrak v0 menyebut `keluar.transaction_id`).
- Keterangan: "Prive ke Rumah tangga" / "Prive dari <nama ruang usaha>", ditambah `: <catatan>` (maks. 200).
- Kirim ulang `client_ref` mengembalikan jawaban tersimpan tanpa memeriksa ulang peran (sama dengan `advisor/execute`); kunci Redis per user, jadi user lain tidak bisa memakainya.

**Cara melanjutkan**
- Review ulang kedua (4 Nov, `3e9e026`): **lulus**, siap merge. Saran dikerjakan: tes siklus kini memakai isi amplop bertanggal 28 Okt, sehingga di kode lama prive kedua (26 Nov) lolos 201 seperti PoC.
- Merge: tanpa migrasi; checklist "Plugin R8" di `AGENTS.md` (`ruang_paritas` sesudah deploy). Lalu PR kecil "R8 tayang" (status `selesai`, Gerbang R).
- Merge: tanpa migrasi; checklist "Plugin R8" di `AGENTS.md` (`ruang_paritas` sesudah deploy). Lalu Gerbang R bisa dinilai lulus (R2, R3, R8).
- Berikutnya `/sesi-plugin R5` (peran, batasan, persetujuan; migrasi, review) atau `/sesi-plugin H1`.

---

## H1 · Host inti · 2026-11-01 · pemilik produk + Claude

**Tayang 4 Nov 2026:** PR #176 di-merge (`e739245`); migrasi `a7e3c1f5d9b2` dijalankan pemilik di VPS; deploy ulang hijau (run 41687358185, percobaan ke-2). H1 `selesai`. Sisa dari checklist yang dikerjakan pemilik: langkah 4 (`\d plugin_installations`, baris `plugin dimuat: (tidak ada)` di journal, `GET /plugins` → `[]`). PR #180 (Kotak Belajar) bermigrasi dari `c5r5a8e2d417`: induknya harus dipindah ke `a7e3c1f5d9b2` sebelum merge.

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
- Urutan migrasi dengan R5 (#175): **beres 2 Nov**. R5 di-merge lebih dulu; `main` di-merge ke branch dan `down_revision` H1 dipindah ke `c5r5a8e2d417`. Checklist H1 langkah 2 kini mensyaratkan `alembic current` = `c5r5a8e2d417`.
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
- Sebelum merge: checklist "Plugin R5" sudah jalan di VPS (`alembic current` = `c5r5a8e2d417`), lalu "Urutan merge PR bermigrasi" dan checklist "Plugin H1" di `AGENTS.md`.
- Berikutnya `/sesi-plugin H2` (PluginContext dan titik ekstensi server; butuh H1 selesai), atau R5/R8 di jalur ruang usaha.

---

## R5 · Peran, batasan, persetujuan di server · 2026-11-01 · pemilik produk + Claude

**Tayang 4 Nov 2026:** PR #175 di-merge 2 Nov (`9d26d7c`); migrasi `c5r5a8e2d417` dijalankan pemilik di VPS; deploy ulang hijau (run 41360830696, percobaan ke-2). R5 `selesai`. Sisa dari checklist yang dikerjakan pemilik: uji alur karyawan di ruang usaha uji (undang, batas nominal, draf, setujui).

**Selesai** (status review, PR #175, menunggu review keamanan terpisah; issue #145)
- Keputusan pemilik produk (1 Nov, "lanjut" atas dua usulan pembukaan sesi): **(1)** tafsiran `05-desain-buku-usaha.md` B1 dikonfirmasi: ruang usaha dan adminnya tidak punya akses apa pun ke ruang keluarga anggota; fitur household yang sekarang tetap. **(2)** R5 menegakkan batasan tulis, antrean persetujuan, audit, dan pagar baca berupa tolak-bawaan; Beranda template "Karyawan" dan penyaringan per kartu di R6.
- Migrasi `c5r5a8e2d417`: hanya tabel baru `ruang_batasan` (jabatan + batasan per anggota), `ruang_undangan` (kode sekali pakai, berperan, 7 hari), `ruang_draf` (antrean; unik parsial `user_id, client_ref`), `ruang_audit`. Tidak ada kolom baru di tabel lama, jadi tanpa jendela 500; idempoten seperti B1.
- `app/services/peran.py`: `batasan_karyawan` (None untuk ruang keluarga, owner, admin), `cek_catat` (jenis → amplop → foto → nominal), jam kerja (`validasi_jam_kerja`, `buka_lagi`, sif lewat tengah malam), `cek_jendela_ubah`, `buat_draf` (idempoten per `client_ref`), `batalkan_draf_anggota`, `audit`, `atas_izin_pengelola()` (ContextVar untuk persetujuan).
- **Tolak-bawaan** di `app/services/ruang.py`: `ruang_aktif` dengan header ruang usaha menolak karyawan (403 `khusus_admin`) kecuali `KARYAWAN_BOLEH` (7 route), dan di luar jam kerja (403 `di_luar_jam_kerja` + `buka_lagi`). Pembantu ruang objek menerima `karyawan=True` hanya di jalur pencatatan; selain itu karyawan → 403. `RuangDitolak.extra` untuk field tambahan.
- Jalur tulis: `POST /transactions` (dipecah menjadi `catat_transaksi`), `/batch` (galat per baris dengan `kode`, `draf_id`), `DELETE /transactions/{id}` (jendela ubah), `POST /incomes` (`catat_pemasukan`, jenis penjualan). Di atas batas nominal → 202 draf; kirim ulang → draf yang sama; sesudah disetujui → 201 transaksi yang sama.
- Baca untuk karyawan: `/envelopes/` hanya amplop yang diizinkan (anggaran 0 tanpa `lihat_saldo`), `/envelopes/summary` 403 tanpa `lihat_saldo`, `/transactions/` hanya miliknya, saran amplop tidak menyarankan amplop terlarang.
- Route baru `app/api/routes/ruang_kelola.py` (semula `ruang.py`, dipindah saat merge R4): anggota (daftar, ubah peran/jabatan, keluarkan/keluar), batasan, undangan + `/ruang/gabung`, persetujuan (daftar, setujui, tolak), `/persetujuan/saya`, `/ruang/{id}/audit`. Hanya ruang usaha; admin tidak bisa menyentuh owner; persetujuan diklaim atomik (menunggu → diproses), gagal → kembali menunggu.
- `POST /user/reset` di ruang usaha: audit `reset_ruang` (jumlah catatan per pencatat, tanpa nominal) dan draf menunggu dibatalkan (catatan review R3).
- Tes: `app/tests/test_ruang_peran.py` (19: aturan murni, tolak-bawaan semua route `ruang_aktif`, tulis objek, batasan, draf→setujui/tolak, penjualan, jam kerja, jendela ubah, anggota/undangan, keluar, reset, ruang keluarga tidak berubah); pagar diperbarui (route R5, delegasi `catat_transaksi`, kueri keanggotaan `peran.py`/`routes/ruang.py`); dua tes fake-DB mem-patch `batasan_karyawan`.
- Dokumen: kontrak §1, §2 (v1 R5), §7; `AGENTS.md` aturan 3 + checklist R5; `00-indeks.md`; `PROGRESS.md` (R3 selesai, R5 review).
- Tes: unittest 2403 (1 gagal = `test_basic_quota_bot_fund_shift_finishes_started_input`, sama dengan `main`) · node --test 644 lulus · build ok · `cek-migrasi.sh origin/main` di PostgreSQL 16 ok, plus urutan produksi (`create_all` model baru → stamp → upgrade) ok · `openapi_cek` tanpa perubahan memutus.

- **Review keamanan PR #175** (sesi terpisah, 1 Nov): Request Changes, tiga temuan menahan merge. Semua dikerjakan di branch ini dengan tes di `test_ruang_peran.py` (+5 tes, total 24): (1) pesan dana/limit tanpa angka untuk karyawan tanpa `lihat_saldo` (`peran.pesan_cek_karyawan`, jalur tunggal dan batch); (2) `raise_daily_limit` diabaikan untuk karyawan (`peran.boleh_naikkan_limit`); (3) penjualan karyawan wajib dialokasikan penuh, 422 `alokasi_tidak_penuh`, supaya sisa tidak jatuh ke atau membuat Tabungan. Ikut di PR ini: (4) notifikasi target dari penjualan karyawan ke owner (`peran.owner_ruang`), juga saat draf disetujui; (5) validasi alokasi sebelum cabang draf; (6) `client_ref` aditif di `POST /incomes` untuk idempotensi draf penjualan; (7) audit `catatan_dihapus`; (9 sebagian) `@limiter.limit("10/minute")` di `/ruang/gabung`.
- Tes sesudah review: unittest 2408 (1 gagal yang sama dengan `main`) · `openapi_cek` tanpa perubahan memutus.
- **Review ulang** (1 Nov, terhadap `f740996`): temuan 1–3 tuntas, tetapi satu temuan baru menahan merge: nominal negatif (sudah ada sebelum PR). Pengeluaran −Rp3 jt menambah saldo dan melewati batas nominal/foto; penjualan Rp0 dengan alokasi +5 jt/−5 jt lolos syarat alokasi penuh. Perbaikan: `TransactionCreate.amount` dan `IncomeCreate.amount` `Field(gt=0)`, `AllocationItem.amount` `Field(ge=0)` (berlaku untuk semua peran); batch menolak per baris (`kode: nominal_tidak_sah`) supaya satu baris buruk tidak menahan seluruh antrean offline. Tes `test_nominal_negatif_ditolak`.
- **Merge `main` (R4, #174):** route R4 tetap di `routes/ruang.py` (prefix `/ruang`); route R5 dipindah ke `routes/ruang_kelola.py` (tanpa prefix, karena `/persetujuan/saya`). Route R5 ikut flag `ruang_usaha_users`: di luar flag `/ruang/{id}/…` 404 dan `/ruang/gabung` 403 `ruang_usaha_belum_dibuka`, jadi karyawan yang diundang juga harus masuk flag selama beta. `GET /ruang` kini mengisi `jam_kerja` untuk karyawan. Tes R5 menyalakan flag; tes baru `test_ikut_flag_ruang_usaha_dan_jam_kerja_di_daftar_ruang`.
- Tes sesudah merge: unittest 2419 (1 gagal yang sama dengan `main`) · node --test 653 lulus · build ok · `cek-migrasi.sh origin/main` di PostgreSQL 16 ok · `openapi_cek` tanpa perubahan memutus.

**Digantung**
- Notifikasi ke admin saat draf baru dan ke karyawan saat diputus belum ada (`Notification.type` masih SAEnum; perlu migrasi enum atau kolom `kind`): masuk U6 (notifikasi admin) dan R6 (tampilan karyawan).
- Daftar dan pencabutan undangan (`dicabut_at` sudah ada di tabel) belum punya endpoint: R6 bersama halaman Anggota.
- `client_ref` pemasukan baru dipakai untuk draf karyawan; idempotensi pemasukan biasa (owner/admin) belum ada, sama seperti sebelum R5. Perlu sebelum form penjualan U2.
- **Butuh keputusan pemilik produk (review #8, #10):** (8) admin sekarang boleh membuat undangan berperan admin, menaikkan anggota menjadi admin, dan menurunkan atau mengeluarkan admin lain; ADR-P4 hanya melindungi owner. Bila disengaja, tulis di ADR; bila tidak, batasi aksi atas admin ke owner. (10) batas nominal berlaku per catatan, jadi satu belanja bisa dipecah; apakah perlu batas kumulatif harian per karyawan?
- Pencabutan undangan (review #9, `dicabut_at` sudah ada) masuk R6 bersama daftar undangan.
- Beranda template "Karyawan" dan penyaringan per kartu (`/dashboard/*` sekarang 403 untuk karyawan): R6. Kotak Struk untuk karyawan (unggah bukti ke ruang usaha): R7.
- Draf yang macet di status `diproses` (proses mati di antara klaim dan pencatatan) tidak bisa disetujui ulang dari UI; transaksi ganda tetap tercegah `client_ref`. Bila muncul: ubah status ke `menunggu` di DB.
- Anggota yang keluar lalu diundang lagi mendapat batasan bawaan (tanpa batas nominal); admin perlu mengatur ulang. Pertimbangkan bawaan yang lebih ketat di R6.

**Jebakan**
- `request.scope["endpoint"]` dipakai `ruang_aktif` untuk mengenali route (`modul.nama_fungsi`); mengganti nama handler di `KARYAWAN_BOLEH` membuatnya tertolak untuk karyawan (aman, tapi tes `test_karyawan_hanya_route_pencatatan_lewat_header` menangkapnya).
- Tes dengan fake DB berskrip (`app/tests/fakes.py`) yang memanggil handler baca langsung harus mem-patch `app.services.peran.batasan_karyawan`, karena kueri peran memakan satu hasil skrip.
- `catat_transaksi` dipanggil juga dari persetujuan: jangan menambah cek yang bergantung pada user yang login di sana; pakai `peran.izin_pengelola_aktif()` bila perlu membedakan.
- PostgreSQL lokal: `initdb`/`pg_ctl` sebagai user `claude` di `/home/claude/pg` (socket `-k`, port 5433).

**Keputusan kecil**
- Batasan bawaan (admin belum mengatur): dua jenis, semua amplop, tanpa batas nominal dan foto, `hari_sama`, `lihat_saldo` false, tanpa jam kerja — sama dengan contoh kontrak, dengan saldo tertutup sebagai bawaan yang aman.
- "Foto nota" = `receipt_item_id` (item Kotak Struk); pemasukan tidak dicek foto.
- Pemasukan karyawan = jenis `penjualan`; amplop alokasinya ikut `amplop_ids`.
- Zona jam kerja = zona admin yang menyimpan (disimpan di `jam_kerja.zona`); jendela ubah memakai zona yang sama, bawaan WIB.
- Undangan sekali pakai (satu kode per orang) dan admin boleh mengundang admin; tidak ada transfer kepemilikan.
- Draf dibuat sesudah cek amplop dan "bisa dibelanjakan", tetapi sebelum cek dana dan limit harian; cek itu dijalankan saat persetujuan, karena saldo bisa berubah sampai admin memutus.
- Batch: baris draf dikembalikan `ok: false` + `kode: perlu_persetujuan`, supaya klien lama menyimpan barisnya; kiriman ulangnya idempoten.

**Cara melanjutkan**
- Review ulang kedua yang singkat: "review ulang PR #175 terhadap 03-workflow.md bagian keamanan, fokus validasi nominal (temuan baru) dan gabungan dengan R4 (flag `ruang_usaha_users`, `ruang_kelola.py`)".
- Merge: label `migrasi`; checklist "Plugin R5" di `AGENTS.md`, mengikuti "Urutan merge PR bermigrasi".
- Berikutnya R6 (butuh R4, R5, B2), R8, atau H1.

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
