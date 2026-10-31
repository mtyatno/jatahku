# Buku Usaha dan ruang usaha — desain

Dua dokumen desain yang menjadi acuan sesi Fase 2 sampai Fase 4 (`03-workflow.md`):

- **Bagian A** — mockup Jatahku dengan plugin Buku Usaha: artboard di kanvas, keputusan desain per layar, dan data contoh.
- **Bagian B** — keputusan ruang usaha: kanal chat, pencatatan cerdas, anggota, peran, dan batasan.

Keputusan yang mengikat juga tercatat sebagai ADR di `02-adr.md`; bila ada beda, ADR yang berlaku. Salinan dari dokumen project claude.ai "jatahku" (`plugin-buku-usaha-mockup.md`, `ruang-usaha-keputusan.md`) per 31 Okt 2026. Perubahan dibuat di sini lewat PR, lalu disalin ke project.

## A. Mockup Jatahku dengan plugin Buku Usaha

31 Okt 2026 · kanvas desain: https://claude.ai/artifact/NFHnjALwuskpZz8pxB3Z8k

Visualisasi Jatahku saat sistem plugin aktif, dengan Buku Usaha sebagai contoh. Mengikuti kajian `01-kajian.md`. Gaya diambil dari kode `frontend/` (commit 8c7fde2, tema gelap hijau). Data usaha (katering "Dapur Nusa", Oktober 2026) adalah contoh fiktif, bukan data user.

Keputusan pemilik produk tentang ruang terpisah, kanal chat (Telegram dan chat web hanya untuk ruang keluarga), laporan untuk admin, pencatatan cerdas di ruang usaha, anggota ruang usaha, Pikir-Pikir yang masuk inti, dan Buku Usaha sebagai plugin pertama ada di bagian B. Kanvas ini menjadi acuan cakupan Buku Usaha v1 di `03-workflow.md`.

### A1. Artboard

| Artboard | Isi | Interaksi (tombol Play) |
| --- | --- | --- |
| Beranda ruang usaha (desktop) | Pemilih ruang, grup menu Usaha, 3 KPI Buku Usaha, Arus kas 13 minggu, AI Advisor campuran saran inti dan BU-01, Alokasi omzet, Beban per akun, Transaksi terbaru dengan pemasok dan prive, Pelanggan teratas | Pemilih ruang, menu Catat ▾ |
| Atur Beranda + Galeri kartu | Mode Atur: pegangan geser, sembunyikan, ukuran S–XL, Naik/Turun, laci Kartu tersembunyi, galeri per sumber (Buku Usaha, Bawaan, plugin lain yang belum dipasang). Bukan bagian Buku Usaha v1 | Seret, angkat lewat pegangan, Naik/Turun, ubah ukuran, sembunyikan, tambah, urungkan, kembalikan ke bawaan |
| Beranda usaha di HP | Header dengan pemilih ruang, KPI bertumpuk, FAB, bottom nav 6 item | FAB (aksi Penjualan dan Prive), sheet Lainnya, sheet pemilih ruang |
| Chat: ruang keluarga + laporan Dapur Nusa | Diperbarui sesuai keputusan 31 Okt: mencatat pengeluaran keluarga seperti sekarang; pengingat kas usaha dan `/laba` Dapur Nusa untuk admin, berlabel nama ruang, dengan tombol yang hanya membuka Jatahku | Statis |
| Pemilih ruang, menu Catat, form penjualan | Dropdown ruang, menu Catat dengan grup Buku Usaha, form Jenis pemasukan + Pelanggan + pratinjau alokasi | Ganti jenis pemasukan, ubah jumlah |
| Halaman Buku Usaha | Tab Laba rugi (vs September, bagian "Di luar laba rugi"), Alokasi omzet (aturan persen), Kontak | Tab, edit persen (validasi 100%), saring kontak |
| Fitur Tambahan | Buku Usaha terpasang; katalog; panel pasang Faktur & Piutang atau Pajak UMKM: butuh, yang ditambahkan, izin + risiko, tawaran kartu, catatan data. Pikir-Pikir tampil sebagai "Bawaan" ruang Rumah tangga (keputusan 6 di bagian B) | Pilih, centang kartu, pasang, jeda Buku Usaha |
| Karyawan: Beranda di ruang usaha (HP) | Dewi (kasir): Catat cepat, Menunggu persetujuan, penjualan dan pengeluaran saya hari ini, Catatan saya hari ini, Batasan dari admin, pengingat bahwa ruang keluarganya terpisah. Tanpa kartu laba, kas, dan saldo amplop; tanpa tombol chat | Sheet pemilih ruang, sheet Lainnya, buka Catat cepat |
| Karyawan: Catat cepat dengan deteksi otomatis (HP) | Kotak teks seperti chat; kartu Terdeteksi (jenis, nominal, keterangan, amplop dan sumber tebakannya, pemasok atau pelanggan); "Aturan admin untuk catatan ini"; tawaran pindah ke ruang keluarga; daftar amplop dengan yang dikunci admin | Ketik bebas atau pilih 5 contoh; ubah jenis; pilih amplop (yang terkunci tidak bisa); ajari kata baru; lampirkan atau hapus foto nota; simpan ke Dapur Nusa, kirim untuk persetujuan, atau catat di ruang keluarga |
| Admin: anggota, batasan, persetujuan, kata yang dipelajari (desktop) | Pengaturan › Ruang Dapur Nusa: daftar anggota dan peran, antrean Menunggu persetujuan, Kata yang dipelajari di Dapur Nusa, panel Batasan per karyawan (peran, jabatan, jenis catatan, amplop, batas nominal, foto nota, ubah atau hapus, yang bisa dilihat, jam kerja) | Pilih anggota, ganti peran Karyawan/Admin, centang jenis dan amplop, ubah batas, setujui atau tolak, hapus kata, urungkan |

Chip "Contoh" di Catat cepat hanya alat bantu prototipe untuk mencoba lima skenario: kardus (kamus ruang), nasi box (penjualan), ayam potong 2,46 jt (di atas batas dan wajib foto), tisu (kata baru yang diajarkan), pulsa (pengeluaran pribadi).

### A2. Keputusan desain (usulan, acuan sesi R4–U6)

1. Pemilih ruang di bawah logo sidebar; di HP menggantikan logo di header.
2. Menu plugin tampil sebagai grup "Usaha" di sidebar. Fitur Tambahan di kaki sidebar, di atas Pengaturan.
3. Kartu plugin diberi penanda kecil (ikon puzzle, label "Buku Usaha"); kartu bawaan tanpa penanda.
4. Menu Catat ▾ punya grup per plugin, maksimal 2 aksi: Penjualan, Prive ke Rumah tangga. Di HP lewat FAB.
5. Saran plugin masuk kartu AI Advisor yang sama, dengan label sumber.
6. Mode Atur menyembunyikan sidebar dan menempelkan Galeri kartu di kanan, supaya grid tetap 3 kartu S per baris.
7. Pemasangan memakai katalog + panel detail, bukan modal. Status Jeda menyembunyikan menu dan kartu tanpa menghapus data.
8. Bottom nav HP menjadi 6 item; item baru "Lainnya" memuat Analitik dan menu plugin.
9. Periode ruang usaha per bulan kalender (1–31 Okt), bukan periode gajian.
10. Kontras: badge merah memakai #DC2626 dan badge hitungan AI Advisor memakai teks gelap di atas #34d399, karena warna sekarang di bawah 4,5:1.
11. Tombol utama Catat bisa diatur per ruang: Pengeluaran di ruang keluarga, Penjualan di ruang usaha.
12. Karyawan punya satu pintu Catat (kartu Catat cepat dan FAB) yang membuka Catat cepat; jenis catatan dideteksi, bukan dipilih dari menu.
13. Kartu Terdeteksi selalu menyebut sumber tebakannya: kamus Dapur Nusa beserta siapa yang mengajarkan, Kontak Buku Usaha, kamus usaha bawaan, atau kata yang diajarkan user sendiri.
14. Koreksi amplop memberi tahu bahwa kata itu masuk kamus Dapur Nusa untuk semua anggota, bisa dihapus admin, dan tidak dipakai di ruang keluarga.
15. Aturan admin tampil saat berlaku ("Aturan admin untuk catatan ini") dan lengkap di bagian bawah. Di atas batas nominal, tombol simpan menjadi "Kirim untuk persetujuan" berwarna kuning.
16. Amplop yang tidak diizinkan tetap terlihat tetapi terkunci dengan alasannya ("Hanya pemilik", "Dikunci admin untukmu").
17. Tawaran "pengeluaran pribadi" hanya terlihat oleh karyawan itu dan tidak tercatat untuk admin; pilihannya mencatat di ruang keluarganya sendiri.
18. Halaman admin: daftar anggota di kiri, panel batasan di kanan; perubahan tersimpan otomatis dan tercatat di log ruang. Antrean persetujuan dan kamus ruang ada di halaman yang sama.

### A3. Data contoh (konsisten antar-artboard)

- Oktober: omzet Rp48.650.000 (112 penjualan), beban Rp36.300.000, laba bersih Rp12.350.000 (25,4%).
- September: omzet Rp44.600.000, beban Rp34.950.000, laba Rp9.650.000 (21,6%).
- Alokasi omzet: Bahan 45%, Operasional 30%, Prive 15%, Laba ditahan 9%, Pajak 1%. Operasional lewat Rp305.000.
- Kas usaha Rp13.755.000, kebutuhan dua minggu Rp16,39 jt, sehingga BU-01 menyala (cukup ±11 hari).
- Prive Rp6.000.000 (49% dari laba). Omzet Januari–Oktober Rp453,6 jt.
- Anggota Dapur Nusa: yatno (Pemilik), Dewi (Karyawan, kasir), Bagas (Karyawan, staf dapur).
- Batasan Dewi: pengeluaran dan penjualan; amplop Bahan dan Operasional; batas Rp1.000.000 per pengeluaran; foto nota di atas Rp300.000; ubah atau hapus di hari yang sama; saldo amplop tidak ditampilkan; tanpa jam kerja.
- Batasan Bagas: pengeluaran saja; amplop Bahan dan Operasional; batas Rp500.000; foto nota di atas Rp200.000; saldo amplop ditampilkan; jam kerja 07.00–15.00.
- Hari Dewi (Sabtu, 31 Okt): 4 penjualan Rp1.150.000, 2 pengeluaran Rp175.000, 1 menunggu persetujuan (ayam potong 60 kg, UD Sumber Unggas, Rp2.460.000, 13.10).
- Kamus Dapur Nusa: kardus → Operasional (Bagas, 4×), ayam → Bahan (yatno, 12×), nasi box dan pax → Penjualan (Dewi, 9×), elpiji → Operasional (Bagas, 6×), arunika → PT Arunika Data (Dewi, 8×), es batu → Operasional (Dewi, 3×).

Usulan: data ini dipakai juga sebagai fixture tes Buku Usaha (U2–U4), supaya angka di kanvas, tes, dan layar bisa dibandingkan langsung.

### A4. Pertanyaan terbuka (desain)

Diputuskan sesi yang membangun layarnya, dicatat di `SESI-LOG.md` sebagai keputusan kecil, atau dibawa ke pemilik produk bila mengubah cakupan.

- Sidebar disembunyikan saat Mode Atur, atau tetap tampil dengan grid lebih sempit? (Mode Atur, setelah beta)
- Bottom nav 6 item, atau "Lainnya" menggantikan Langganan? (R4, H3)
- Penanda sumber kartu tampil selalu, atau hanya di Mode Atur? (U4)
- Antrean persetujuan untuk admin: cukup di Pengaturan ruang seperti mockup, atau juga sebagai kartu di Beranda pemilik? (R6)
- Batas nominal cukup per catatan, atau perlu juga batas harian per karyawan? (R5)
- Pertanyaan tentang kanal chat, peran, dan batasan ada di bagian B.

## B. Ruang usaha: kanal chat, pencatatan, dan anggota

31 Okt 2026 · keputusan pemilik produk dari percakapan perancangan sistem plugin. Melengkapi `01-kajian.md` (kajian), bagian A (mockup), dan `03-workflow.md` (rencana development). Keputusan yang mengikat tercatat juga sebagai ADR di `02-adr.md`.

Cara baca: **Diputuskan** berarti keputusan pemilik produk. **Usulan** berarti rincian turunan yang belum diputuskan.

### Ringkasan keputusan (diputuskan 31 Okt 2026)

1. **Ruang terpisah.** Uang keluarga dan uang usaha dicatat di ruang yang berbeda. User cukup memilih ruang aktif; menu, aksi Catat, dan Beranda mengikuti ruang itu. Menu inti (Beranda, Amplop, Transaksi, Alokasi, Langganan) sama di semua ruang, Fitur Tambahan hanya menambah, dan amplop tetap dipakai di ruang usaha. (ADR-P1)
2. **Transaksi lewat chat hanya untuk ruang keluarga.** Telegram dan chat web tetap seperti sistem yang berjalan sekarang: mencatat pengeluaran, menambah amplop, dan perintah lain, hanya untuk ruang keluarga. User tidak bisa bertransaksi pada Fitur Tambahan atau ruang usaha lewat chat. (ADR-P2)
3. **Dari ruang usaha, chat hanya menerima laporan dan notifikasi.** Data laporan seperti `/laba` hanya diterima admin ruang usaha. (ADR-P2, P3)
4. **Pencatatan di ruang usaha tetap cerdas.** Di web dan aplikasi, sistem tetap mendeteksi apa yang diinput user dan terus belajar. (ADR-P5)
5. **Banyak anggota di satu ruang usaha.** Satu ruang usaha bisa berisi banyak user, misalnya 10 karyawan toko. Setiap user tetap punya ruang keluarga sendiri yang tidak terhubung ke ruang usaha, sehingga tetap bisa mencatat keuangan pribadi dan memantau tabungannya. Di jam kerja user membuka ruang usaha dan bekerja di sana, misalnya mencatat pembelian bahan baku dan penjualan, sesuai Fitur Tambahan di ruang itu dan batasan yang diatur admin. (ADR-P4)
6. **Pikir-Pikir masuk sistem inti ruang keluarga.** Sepadan?, Incaran, dan Uang Selamat menjadi bagian inti ruang keluarga, bukan Fitur Tambahan, sehingga fiturnya tetap bisa dipakai lewat Telegram dan chat web. (ADR-P6)
7. **Buku Usaha menjadi plugin pertama.** Pemilik produk memilih Buku Usaha, yang desainnya sudah lengkap di kanvas, sebagai plugin pertama yang dikembangkan, menggantikan modul pilot ringan di roadmap kajian. Urutan dan sesi development ada di `03-workflow.md`. (ADR-P7)

Pada 31 Okt malam pemilik produk juga menyetujui rencana development beserta rekomendasi untuk dua belas keputusan pendukungnya. Lima di antaranya menjawab pertanyaan terbuka bagian ini (B6).

Alasan pemilik produk: tanpa batas ruang, pengeluaran pribadi mudah tercatat sebagai uang usaha, dan banyak ruang dalam satu chat membingungkan user.

### B1. Satu orang, beberapa ruang

| Orang | Ruang keluarga | Ruang usaha "Dapur Nusa" |
| --- | --- | --- |
| Pemilik usaha | Miliknya sendiri, boleh berbagi dengan keluarga seperti fitur household sekarang | Pemilik |
| Kasir | Miliknya sendiri | Karyawan |
| Staf dapur | Miliknya sendiri | Karyawan |

Diputuskan: ruang keluarga setiap user tidak terhubung ke ruang usaha.

Usulan, batas yang dijaga sistem:
- Pemilik dan admin usaha tidak pernah bisa melihat ruang keluarga karyawan, termasuk ringkasan, statistik, dan saran AI Advisor.
- Tidak ada angka dari ruang keluarga yang masuk ke laporan, AI Advisor, atau Beranda ruang usaha, dan sebaliknya.
- Uang hanya berpindah antar-ruang lewat jalur resmi: Prive (ruang usaha ke ruang keluarga pemilik). Gaji karyawan dicatat sebagai beban di ruang usaha; karyawan mencatat gajinya sendiri sebagai pemasukan di ruang keluarganya. Sistem tidak menyalinnya otomatis, karena itu akan menghubungkan dua ruang.

Tafsiran yang perlu dikonfirmasi: "tidak terhubung ke manapun kecuali dirinya" diartikan ruang usaha dan adminnya tidak punya akses. Fitur household yang sekarang (mengundang pasangan atau keluarga ke ruang keluarga) tetap ada dan diatur oleh pemilik ruang keluarga itu.

### B2. Kanal chat

#### B2.1 Pembagian kanal

| Kanal | Ruang keluarga | Ruang usaha |
| --- | --- | --- |
| Telegram | Semua yang berjalan sekarang: catat pengeluaran (teks, multi-item, foto struk), isi dana amplop, langganan, `/status`, `/amplop`, dan lainnya; Pikir-Pikir (`/incaran`, "cek 450k hiburan", tombol refleksi "Sepadan?") | Hanya menerima laporan dan notifikasi; perintah baca seperti `/laba` untuk admin |
| Chat web (PWA) | Sama dengan Telegram (satu otak bot) | Sama dengan Telegram |
| Form web dan aplikasi | Semua | Semua pencatatan ruang usaha |

#### B2.2 Aturan rinci

Diputuskan:
- Chat selalu memakai ruang keluarga milik user. Tidak ada perintah `/ruang` dan tidak ada ruang aktif per chat.
- Tidak ada transaksi Fitur Tambahan lewat chat.
- `/laba` dan data laporan usaha hanya untuk admin ruang usaha.
- Pikir-Pikir bagian inti ruang keluarga, jadi perintah dan tombolnya di chat tetap jalan.

Usulan:
- Data keuangan usaha lain (kas, omzet, arus kas, piutang, pajak) mengikuti aturan `/laba`: hanya pemilik dan admin.
- Setiap pesan dari ruang usaha diawali nama ruangnya dan menyebut periodenya, mis. "[Dapur Nusa] Laba Oktober 2026".
- Tombol di pesan ruang usaha hanya membuka halaman terkait di Jatahku. Tidak ada tombol yang mencatat atau mengubah data, mis. "Tandai lunas" atau "Pindahkan dana"; tindakan itu dikerjakan di aplikasi.
- Membalas atau mengetik setelah pesan laporan tetap diproses sebagai catatan ruang keluarga, seperti biasa.
- Karyawan yang mengetik `/laba` mendapat jawaban "Laporan Dapur Nusa hanya untuk admin ruang". Daftar perintah Telegram per chat hanya menampilkan `/laba` untuk admin.
- User yang menjadi admin di lebih dari satu ruang usaha memilih ruang lewat tombol (baca saja) sebelum laporan tampil.
- Notifikasi Fitur Tambahan: penerima bawaan pemilik dan admin. Notifikasi operasional tanpa angka keuangan (mis. stok menipis) boleh ke karyawan bila admin mengizinkan (diputuskan 31 Okt, B6; ADR-P19).
- Jam tenang dan batas harian notifikasi memakai penyaring yang sama dengan `app/services/advisor/proaktif.py`.
- Chat web belum bisa menerima pesan inisiatif bot (bagian "Belum ada (follow-up)" di `docs/chat-bot-web.md`), jadi di web laporan dan notifikasi ruang usaha muncul di lonceng notifikasi.

#### B2.3 Dampak

- **Paritas web ↔ Telegram** (`paritas-web-telegram.md` di project claude.ai "jatahku") tetap berlaku penuh di ruang keluarga. Ruang usaha hanya dicatat lewat form web dan aplikasi, yang memakai bundle yang sama, jadi tetap satu metode.
- **Kode bot:** handler bot memakai ruang keluarga utama user secara eksplisit (mis. resolver `ruang_keluarga(user)`), tidak pernah ruang aktif web. Chat web ikut, karena memakai handler yang sama.
- **Manifest Fitur Tambahan:** `bot_commands` hanya boleh berjenis baca dan wajib menyatakan penerimanya (`audience: "admin"` untuk data keuangan). `bot_callbacks` hanya untuk navigasi baca, mis. memilih ruang. Validator manifest di CI menolak perintah tulis.
- **Rencana P4 lebih ringan:** tidak perlu `/ruang`, ruang aktif per chat, intent penjualan dan pelunasan faktur di bot, maupun pemeriksaan kepemilikan untuk tombol tulis plugin. Intent "catat pemasukan lewat bot" tidak lagi dibutuhkan Paket Usaha.
- **Pikir-Pikir (diputuskan, keputusan 6):** masuk inti ruang keluarga, bukan Fitur Tambahan pilot seperti rencana awal kajian. Akibatnya:
  - Fase 2–3 (tabel `wishlist_items` dan `transaction_reflections`, kartu Sepadan?, Incaran, Uang Selamat, perintah bot, job, tipe notifikasi) dibangun di inti. Pekerjaan ini tidak menunggu host plugin dan bisa berjalan paralel. Aturan PP-01 sampai PP-03 di `rules/pikir.py` tetap dipakai.
  - Host plugin tidak lagi memakai modul pilot ringan: Buku Usaha menjadi plugin pertama (keputusan 7), dan gerbang host diuji pada kerangka Buku Usaha (sesi U1 di `03-workflow.md`).
  - Usulan: Pikir-Pikir tidak muncul di ruang usaha.
- **Fitur Tambahan rumah tangga lain (usulan turunan keputusan 2):** Arisan, Patungan & Split Bill, dan plugin rumah tangga lain di katalog kajian tetap Fitur Tambahan. Di chat mereka hanya mengirim pengingat dan menjawab perintah untuk melihat (mis. `/arisan` menampilkan jadwal); mencatat setoran atau patungan dilakukan di aplikasi.

### B3. Pencatatan cerdas di ruang usaha

#### B3.1 Yang sudah ada dan dipakai ulang

- `app/services/txn_nlp.py`: satu NLP untuk bot dan web (ekstraksi kata kunci, tebakan kategori, pencocokan kata yang dipelajari). Web memakainya lewat `POST /transactions/suggest-envelope` dan `/suggest-envelopes`; Kotak Struk lewat `app/services/kotak_struk/suggest.py`.
- Pembelajaran:
  - `expense_rules.after_expense_recorded` → `save_learned_keywords` → `UserEnvelopeKeyword` (per user, per amplop).
  - `MerchantEnvelopeMap`: merchant → amplop, per rumah tangga.
  - `GlobalIntentPhrase`: frasa → intent, berlaku untuk semua user.
  - `ReceiptLearnVote`: hasil belajar struk baru dipakai setelah disetujui minimal 2 user berbeda.
- Parser nominal dan multi-item: `parseAmount.js` ⇄ `parse_amount`, dengan kasus uji bersama.
- Input teks, suara (`VoiceInput`), dan foto struk (`ReceiptInput`, Kotak Struk).

#### B3.2 Yang perlu disesuaikan (usulan)

1. **Ruang dari input, bukan dari keanggotaan pertama.** `suggest-envelope(s)` sekarang mencari household dengan `scalar_one_or_none()` atas keanggotaan user. Ini salah satu dari 86 titik di kajian dan harus memakai ruang tempat user sedang mencatat.
2. **Kotak "Catat cepat" di ruang usaha.** Karena chat tidak dipakai untuk ruang usaha, form Catat di web dan aplikasi punya kotak teks dengan pengalaman seperti chat: user mengetik "ayam potong 40kg 1,64jt ud sumber unggas", sistem menampilkan kartu pratinjau (nominal, keterangan, amplop Bahan, pemasok UD Sumber Unggas), user mengoreksi bila perlu, lalu menyimpan. Suara dan foto nota juga tersedia. Mockup: artboard "Karyawan: Catat cepat dengan deteksi otomatis" (B4.3).
3. **Kamus kategori per jenis ruang.** `CATEGORY_KEYWORDS` sekarang berisi kategori rumah tangga (makan, transport, hiburan, belanja, tagihan, kesehatan). Buku Usaha menyumbang kamus usaha (bahan baku, kemasan, gas dan listrik, gaji, sewa, kirim, promosi) yang hanya aktif di ruang usaha, lewat titik ekstensi baru (mis. `nlp_kamus`).
4. **Deteksi tambahan Buku Usaha:** jenis pemasukan dari kata kunci ("jual", "laku", "DP", "terima pembayaran" → Penjualan; "setor modal" → Modal pemilik; "pinjam" → Pinjaman); nama pelanggan dan pemasok yang dicocokkan dengan Kontak; jumlah dan satuan ("40 kg", "50 pax") sebagai keterangan.
5. **Belajar bersama per ruang.** Di ruang usaha, koreksi dari anggota mana pun mengajari kamus ruang itu, supaya karyawan baru langsung terbantu. Polanya sudah ada di `MerchantEnvelopeMap` yang per rumah tangga. Urutan pencocokan: kata yang dipelajari user sendiri, lalu kamus ruang, lalu kamus kategori. Admin bisa melihat dan menghapus kata yang dipelajari.
6. **Tidak bocor antar-ruang.** Yang dipelajari di ruang usaha tidak dipakai di ruang keluarga, dan sebaliknya. Pembelajaran yang menjadi global (`GlobalIntentPhrase`, label struk) tetap memakai aturan minimal 2 user berbeda seperti `ReceiptLearnVote` dan tidak pernah memuat nama kontak atau nominal.
7. **Deteksi salah ruang.** Bila teks yang diketik di ruang usaha sangat cocok dengan kata pribadi user sendiri (mis. "pulsa", "jajan") dan tidak cocok dengan amplop usaha, muncul tawaran "Sepertinya pengeluaran pribadi. Catat di ruang keluargamu?". Pengecekan memakai data user itu sendiri, hasilnya hanya tampil ke dia, dan tidak tercatat untuk admin.
8. **Aturan tetap satu sumber.** Pencatatan ruang usaha tetap lewat `expense_rules` (cek amplop, dana, limit), sama dengan ruang keluarga. Kuota Basic tidak berlaku di ruang usaha (kajian no. 10, ADR-P13).

### B4. Anggota, peran, dan batasan (usulan)

Dasar: `HouseholdRole` sudah punya `owner`, `admin`, dan `member`. Di UI: Pemilik, Admin, Karyawan.

#### B4.1 Hak bawaan per peran

| Aksi | Pemilik | Admin | Karyawan |
| --- | --- | --- | --- |
| Mencatat pengeluaran dan penjualan | Ya | Ya | Ya, dalam batasan |
| Mengubah atau menghapus catatan | Semua | Semua | Hanya miliknya, di hari yang sama |
| Melihat saldo amplop dan kas | Ya | Ya | Hanya amplop yang diizinkan |
| Melihat laporan (laba, kas, omzet, arus kas) | Ya | Ya | Tidak |
| Menerima laporan dan `/laba` di Telegram | Ya | Ya | Tidak |
| Mengatur amplop dan alokasi omzet | Ya | Ya | Tidak |
| Memasang, menjeda, mencopot Fitur Tambahan | Ya | Ya | Tidak |
| Mengundang dan mengeluarkan anggota, mengatur batasan | Ya | Ya, kecuali terhadap pemilik | Tidak |
| Mencatat Prive ke ruang keluarga | Ya | Tidak | Tidak |
| Menghapus ruang usaha | Ya | Tidak | Tidak |

#### B4.2 Batasan yang bisa diatur admin

- Amplop yang boleh dipakai, per karyawan atau per peran (mis. kasir hanya Bahan dan Operasional).
- Jenis catatan yang boleh: pengeluaran, penjualan, atau aksi tertentu dari Fitur Tambahan.
- Batas nominal per catatan. Di atas batas, catatan masuk antrean "Menunggu persetujuan" dan admin mendapat notifikasi; persetujuan dilakukan di aplikasi, bukan lewat tombol Telegram. Antrean ini bagian inti ruang usaha (diputuskan 31 Okt, ADR-P18).
- Wajib foto nota di atas nominal tertentu.
- Jam kerja: ruang usaha hanya bisa dibuka pada jam yang ditentukan admin. Pilihan per karyawan, bawaan mati (diputuskan 31 Okt, ADR-P17).

#### B4.3 Tampilan karyawan

- Menu sama dengan ruang itu, tetapi item yang tidak diizinkan untuk perannya disembunyikan. Ini batas hak per peran, bukan per jenis ruang, jadi tidak bertentangan dengan keputusan 1.
- Beranda template "Karyawan": Catat cepat, catatan saya hari ini, penjualan saya hari ini, dan catatan yang menunggu persetujuan. Tanpa kartu laba atau kas.
- Mockup 31 Okt di kanvas desain (baris "Karyawan di ruang usaha"):
  - **Karyawan: Beranda di ruang usaha** (HP, Dewi sebagai kasir): Catat cepat, catatan yang menunggu persetujuan, penjualan dan pengeluaran saya hari ini, catatan saya hari ini, ringkasan batasan dari admin, dan pengingat bahwa ruang keluarganya terpisah. Tanpa tombol chat (diputuskan 31 Okt: disembunyikan untuk karyawan, ADR-P16).
  - **Karyawan: Catat cepat dengan deteksi otomatis** (HP): kartu Terdeteksi dengan sumber tiap tebakan, kotak "Aturan admin untuk catatan ini" (batas nominal dan foto nota), amplop yang dikunci beserta alasannya, tawaran pindah ke ruang keluarga untuk pengeluaran pribadi, dan catatan bahwa koreksi masuk kamus ruang.
  - **Admin: anggota, batasan, persetujuan, kata yang dipelajari** (desktop, Pengaturan › Ruang Dapur Nusa): daftar anggota, panel batasan per karyawan, antrean persetujuan, dan kamus Dapur Nusa yang bisa dihapus per kata.

#### B4.4 Jejak, keluar, dan privasi

- Setiap catatan menyimpan pencatat dan kanalnya (`Transaction.user_id` dan `source` sudah ada) dan terlihat oleh admin.
- Karyawan yang keluar atau dikeluarkan langsung kehilangan akses ke ruang usaha. Catatan usaha yang ia buat tetap milik ruang usaha dengan namanya; ruang keluarganya tidak tersentuh. Bila akunnya dihapus, nama pencatat menjadi "Mantan anggota" (kajian).
- Data karyawan adalah data pribadi: pemilik usaha sebagai pengendali, Jatahku sebagai prosesor (kajian, bagian UU PDP).

### B5. Contoh sehari-hari

1. 07.30: kasir mengetik "sarapan 15rb" di Telegram. Tercatat di ruang keluarganya, seperti sekarang.
2. 08.10: di aplikasi ia pindah ke Dapur Nusa dan mengetik "kardus 50 pcs 125rb" di Catat cepat. Sistem menebak amplop Operasional dan pemasok Toko Plastik Jaya, hasil belajar dari koreksi staf dapur minggu lalu.
3. 12.00: ia mencatat "nasi box 30 pax 900rb pt arunika". Sistem mendeteksi Penjualan dengan pelanggan PT Arunika Data, lalu membaginya ke 5 amplop.
4. 13.10: ia mencatat belanja Rp2,5 jt, melebihi batasnya Rp1 jt. Catatan menunggu persetujuan. Pemilik menerima "[Dapur Nusa] 1 catatan menunggu persetujuan" di Telegram dengan tombol yang membuka aplikasi, lalu menyetujuinya di sana.
5. 21.00: pemilik mengetik `/laba` di Telegram dan menerima laba Dapur Nusa. Kasir yang mengetik `/laba` mendapat jawaban bahwa laporan hanya untuk admin.
6. Malam hari: kasir mengetik "cek 450k hiburan" di Telegram dan Pikir-Pikir menjawab dari ruang keluarganya.
7. Kapan pun: tabungan dan catatan pribadi kasir hanya terlihat oleh dirinya.

### B6. Keputusan lanjutan (diputuskan 31 Okt malam)

Kelimanya dulu pertanyaan terbuka dan diputuskan sesuai rekomendasi rencana development.

1. **Tombol chat saat ruang usaha aktif:** disembunyikan untuk karyawan; pemilik dan admin tetap melihatnya dengan label "Ruang keluarga". ADR-P16, dibutuhkan sesi R4.
2. **Jam akses ruang usaha:** pilihan per karyawan, bawaan mati. ADR-P17, dibutuhkan sesi R5.
3. **Antrean persetujuan di atas batas nominal:** bagian inti ruang usaha, bukan Fitur Tambahan "Reimburse & Persetujuan". ADR-P18, dibutuhkan sesi R5.
4. **Harga Paket Usaha untuk ruang dengan banyak anggota:** langganan per ruang, hipotesis Rp25.000–Rp50.000 per bulan; tingkat menurut jumlah anggota dinilai dari data beta. ADR-P12, dibutuhkan sesi V1.
5. **Notifikasi operasional untuk karyawan** (mis. stok menipis): boleh bila admin mengizinkan, tanpa angka keuangan. ADR-P19, dibutuhkan sesi U6.

Yang masih perlu dikonfirmasi hanya tafsiran di B1: ruang usaha dan adminnya tidak punya akses ke ruang keluarga anggota, sementara fitur household yang sekarang tetap ada.
