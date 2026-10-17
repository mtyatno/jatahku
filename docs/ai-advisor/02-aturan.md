# Mesin aturan AI Advisor — spesifikasi (Okt 2026)

**Status:** revisi 1 **disetujui pemilik produk 16 Okt 2026 malam.** Development mengikuti rencana sesi di `03-workflow.md`. Keputusan penutup: dana darurat lewat field `envelopes.is_emergency`; `transfer_between_envelopes` ikut dikunci di Fase 1 (sesi S5).

**Keputusan dasar (pemilik produk, 16 Okt 2026):**
- **Tanpa LLM.** Semua analisa dihitung aturan deterministik di server Jatahku dari data user sendiri. Tidak ada data keuangan yang dikirim ke pihak ketiga. Alasan: privasi data keuangan pribadi.
- **CTA pemindah dana memakai konfirmasi satu langkah:** rencana tampil, satu tap, lalu dijalankan.

**Dokumen terkait:** `01-desain.md` (permukaan & mockup), `pikir-pikir-desain.md` dan `paritas-web-telegram.md` di project claude.ai "jatahku" (prinsip "cermin, bukan penjaga gerbang"; satu sumber aturan untuk web & bot).

**Isi:**
1. Cara kerja mesin
2. Prinsip
3. Metrik dasar — satu sumber angka
4. Sinyal — deteksi pola
5. Bentuk insight, tone, skor, keyakinan, penekanan
6. Katalog aturan (A–I: 56 aturan + intent chat)
7. Seleksi per slot
8. Perencana dana
9. Anti-ganggu
10. Teks & format
11. Konstanta
12. Contoh lengkap: Beranda 15 Okt
13. Pengujian
14. Struktur kode saat development dibuka
15. Hasil review 16 Okt: diterima, dikoreksi, disanggah

---

## 1. Cara kerja mesin

Setiap permintaan (Beranda, halaman lain, chat, ringkasan terjadwal) melewati 7 langkah:

1. **Snapshot.** Data dimuat sekali dengan query berkelompok (jumlah query tetap, tidak tumbuh per amplop):
   - amplop yang terlihat viewer (bersama + pribadi miliknya);
   - alokasi, transfer, dan top-up 6 periode;
   - transaksi 6 periode;
   - langganan aktif + pembayarannya;
   - target tabungan, snapshot rollover, cocokkan saldo terakhir;
   - pemasukan rumah tangga 6 periode;
   - preferensi notifikasi dan status dismiss (Redis).
2. **Metrik (§3).** Semua angka turunan, sebagai fungsi murni dari snapshot.
3. **Sinyal (§4).** Pola: laju, outlier, struk, rutin, dobel, lonjakan, amplop menganggur, pemasukan terlambat.
4. **Aturan (§6).** Tiap aturan adalah fungsi murni `(metrik, sinyal) → insight[]`.
5. **Perencana dana (§8).** Satu rencana untuk semua kebutuhan dana, supaya satu sumber tidak dipakai dua kali.
6. **Seleksi (§7, §9).** Skor, penekanan, penggabungan, dismiss, batas per slot.
7. **Render (§10).** Template bahasa Indonesia dan format angka, sama untuk web, chat web, dan Telegram.

**Deterministik:** snapshot yang sama selalu menghasilkan insight yang sama. Tiap insight membawa fakta dan cara hitungnya, jadi bisa dijelaskan di "Rincian" dan di chat tanpa model bahasa.

## 2. Prinsip

- **Cermin, bukan penjaga gerbang.** Tidak ada aturan yang memblokir pencatatan. Batas harian berupa peringatan; CTA "Batas harian" baru dirilis setelah Pikir-Pikir Fase 1 mengubah limit harian menjadi peringatan.
- **Artinya apa + lakukan apa.** Insight tanpa aksi hanya tampil sebagai konteks di chip KPI, atau tidak tampil sama sekali.
- **Satu sumber angka.** KPI, chip, grafik, chat, dan Telegram memakai metrik §3. Total selalu sama dengan jumlah bagian-bagiannya.
- **Jujur.** Proyeksi diberi "±", dasar datanya disebut, dan keyakinan rendah memakai kata "kemungkinan" tanpa CTA pemindah dana.
- **Privasi household.**
  - Agregat boleh dipakai.
  - Deskripsi transaksi privat anggota lain tidak pernah dikutip.
  - Total pemasukan pribadi anggota lain tidak ditampilkan.
  - Tidak ada insight yang menilai anggota lain.
- **Aman secara finansial.** Tidak menyarankan utang. Tabungan hanya disebut sebagai sumber terakhir dan selalu eksplisit; dana darurat paling akhir.
- **Uang tidak pindah tanpa konfirmasi**, dan rencana selalu bisa diubah sebelum dijalankan.

## 3. Metrik dasar — satu sumber angka

**Notasi:**
- [ps, pe] = periode berjalan dari Tanggal Gajian (`app/core/period.py`); t = hari ini di zona waktu user.
- D = jumlah hari periode; d = hari ke- (t − ps + 1); r = sisa hari **setelah** hari ini (pe − t).
- floor100 = dibulatkan ke bawah ke Rp100; ceil10rb = dibulatkan ke atas ke Rp10.000.

**Kelompok amplop** (amplop aktif yang terlihat viewer):
- **Belanja** = purpose `expense` + `debt` (cicilan). Sekarang `/analytics/prediction` hanya memakai `expense`, sedangkan kartu Sisa bebas memakai semua selain tabungan; keduanya disatukan di sini.
- **Tabungan** = `saving` + `sinking_fund`.
- **Kebutuhan / keinginan** = `classification` needs / wants. Kosong dianggap needs supaya aman.

### Per amplop e

| Kode | Metrik | Definisi |
|---|---|---|
| M1 | dana(e) | Σ alokasi periode (termasuk transfer masuk/keluar dan top-up) + rollover dari snapshot periode lalu (hanya bila `is_rollover`) |
| M2 | terpakai(e) | Σ transaksi periode yang tidak dihapus, termasuk penyesuaian cocokkan saldo |
| M3 | sisa(e) | M1 − M2 |
| M4 | tagihan_sisa(e) | Langganan aktif di e yang jatuh tempo ≤ pe dan **belum dibayar**. Bulanan: dianggap sudah dibayar bila `next_run` sudah maju **atau** amplop punya transaksi periode ini bernominal **persis sama** (aturan yang sudah dipakai `reserved.py` hari ini: pembayaran manual lewat catat biasa, bot, atau penyesuaian). Satu transaksi melunasi satu tagihan. Mingguan: jumlah kemunculan yang tersisa sampai pe × nominal |
| M5 | sisihan(e) | Langganan tahunan: nominal ÷ 12 per periode |
| M6 | bebas(e) | M3 − M4 − M5 |
| M7 | variabel(e, rentang) | Transaksi dalam rentang, **tanpa**: penyesuaian cocokkan saldo; pembayaran langganan (deskripsi "🔄 …" atau nominal ±10% dari langganan aktif amplop itu); outlier (S2). Toleransi ±10% hanya untuk laju; untuk M4 dipakai nominal persis, supaya tagihan tidak dianggap lunas keliru |
| M8 | laju(e) | variabel 7 hari terakhir ÷ 7, bila amplop punya belanja di ≥ 3 dari 7 hari itu; selain itu variabel sejak ps ÷ d. Tidak dihitung bila d < 3. **Dipakai untuk aturan per amplop** (AMP-02/03, batas harian), bukan untuk total |
| M9 | butuh_sisa(e) | laju(e) × r + M4(e) |
| M10 | surplus(e) | bebas(e) − laju(e) × r × 1,1 (cadangan 10%) |
| M11 | tambalan(e) | Jumlah dan total transfer masuk ke e periode ini, **dari semua anggota** (memperbaiki "ditambal N×" yang sekarang hanya membaca transfer milik sendiri) |
| M12 | porsi_7h(e) | variabel(e, 7 hari terakhir); porsinya terhadap Σ M12 dipakai untuk "penyumbang terbesar" di PER-01 dan grafik, supaya angkanya persis sama dengan T4 |
| M13 | dibayar_manual(e) | Transaksi periode ini yang nominalnya persis sama dengan tagihan `due`/`overdue` di amplop itu, tetapi `next_run` belum maju (status masih belum dibayar). Memicu DAT-06 |

### Total belanja

| Kode | Metrik | Definisi |
|---|---|---|
| T1 | dana_belanja | Σ M1 amplop belanja |
| T2 | terpakai_belanja | Σ M2 amplop belanja |
| T3 | sisa_bebas | Σ M6 amplop belanja. Boleh negatif; minus di satu amplop mengurangi total |
| T4 | laju_total | Σ variabel semua amplop belanja 7 hari terakhir ÷ 7, bila ada belanja di ≥ 3 dari 7 hari itu; selain itu Σ variabel sejak ps ÷ d. **Bukan** Σ laju(e): dengan begitu T4 selalu sama dengan jumlah 7 batang terakhir di grafik ÷ 7, dan labelnya boleh "rata-rata 7 hari terakhir" |
| T5 | belanja_hari_ini | Σ variabel(e, hari ini). Inilah angka utama kartu Jatah hari ini; yang dikecualikan hari ini (tagihan, outlier, penyesuaian) disebut di catatan kaki kartu, bukan dihitung |
| T5b | keluar_hari_ini | Semua transaksi hari ini **kecuali** pembayaran tagihan (tagihan sudah dipotong lewat M4, jadi netral terhadap T3). Termasuk outlier dan penyesuaian |
| T6 | jatah_hari_ini (J0) | floor100((T3 + T5b) ÷ H0) = sisa bebas **awal hari** ÷ H0. Tetap sepanjang hari apa pun yang dicatat; hanya berubah bila ada dana masuk hari ini (alokasi/transfer) |
| T7 | aman_per_hari (J1) | floor100(max(T3, 0) ÷ H) |
| T8 | proyeksi_akhir | T2 + Σ M4 + Σ M5 + T4 × r |
| T9 | kekurangan | max(0, T4 × r − T3), sama dengan proyeksi − dana bila positif |
| T10 | tanggal_habis | t + ⌊T3 ÷ T4⌋ hari (bila T3 > 0 dan T4 > 0) |
| T11 | persen_dana · persen_waktu | T2 ÷ T1 · d ÷ D |

**Horizon H dan H0** (mengikuti Jenis Pendapatan, seperti PR #20):
- Bulanan atau tidak tentu: H = r, H0 = r + 1.
- Harian: H = min(1, r), H0 = 1. Mingguan: H = min(7, r), H0 = min(7, r + 1).
- Hari terakhir periode (r = 0): J1 tidak ditampilkan dan J0 = T3 + T5. Ini sekaligus menutup crash pembagian nol di bot.

**Kenapa J0 dan J1 dipisah.** Kartu "Jatah hari ini" sekarang membandingkan belanja hari ini dengan J1, yang sudah dipotong belanja hari ini lalu dibagi r. Akibatnya batasnya ikut turun saat user belanja. Batas "lewat" tetap sama secara matematis, tapi angka jatah dan lebihnya kurang tepat.
- Usul: kartu Jatah hari ini memakai J0 (contoh: Rp297.100 / Rp165.100, lewat Rp132.000).
- Kartu Sisa bebas memakai J1 (Rp153.200/hari untuk 11 hari ke depan).
- **Invarian J0** (untuk unit test): mencatat transaksi apa pun hari ini, termasuk outlier, penyesuaian saldo, atau tagihan, tidak mengubah J0. Hanya alokasi atau transfer masuk hari ini yang mengubahnya.

**Grafik Pengeluaran harian membaca deret dari metrik ini,** bukan dari `/analytics/daily-spending` (yang sekarang ikut menghitung pembayaran tagihan dan amplop pribadi anggota lain). Batang = variabel per hari, diwarnai menurut S6; pembayaran tagihan dan penyesuaian digambar sebagai segmen abu-abu redup di atas batang, tidak dibandingkan dengan jatah. Dengan begitu grafik, T4, T5, dan daftar transaksi menunjuk angka yang sama.

### Pemasukan

| Kode | Metrik | Definisi |
|---|---|---|
| P1 | pemasukan_saya | Σ Income periode milik viewer, amount > 0, bukan penyesuaian |
| P2 | pemasukan_rumah_tangga | Sama, untuk semua anggota |
| P3 | belum_dijatah | Σ (amount − Σ alokasi positif) per pemasukan periode |
| P4 | pemasukan_biasa | Median P2 dari 3 periode lalu yang punya pemasukan |
| P5 | hari_biasa_masuk | Median (tanggal pemasukan terbesar − ps) di 3 periode lalu |
| P6 | saving_rate | Alokasi ke tabungan dari P1 ÷ P1 (seperti sekarang), ditambah versi rumah tangga |

### Tabungan & target

| Kode | Metrik | Definisi |
|---|---|---|
| G1 | saldo_tabungan(e) | `envelope_lifetime_balance` (sepanjang waktu) |
| G2 | setoran(e, periode) | Σ alokasi positif ke e per periode |
| G3 | setoran_biasa(e) | Median G2, 3 periode lalu |
| G4 | progres(target) | G1 ÷ target |
| G5 | butuh_per_bulan(target) | (target − G1) ÷ bulan tersisa sampai `target_date` |
| G6 | perkiraan_tercapai | (target − G1) ÷ G3 bulan |
| G7 | belanja_bulanan | Median T2 dari 3 periode lalu; fallback T1 periode ini |
| G8 | cakupan_darurat | G1 amplop darurat ÷ G7, dalam bulan. Amplop darurat = tabungan bernama mengandung "darurat"/"emergency", atau yang ditandai user (usul field opsional `envelopes.is_emergency`) |

### Lain-lain

| Kode | Metrik | Definisi |
|---|---|---|
| K1 | hari_sejak_cocokkan | Hari sejak cocokkan saldo terakhir yang tidak dibatalkan |
| K2 | selisih_terakhir | `gap` cocokkan saldo terakhir |
| K3 | hari_tanpa_catatan | Hari sejak transaksi terakhir viewer |
| K4 | beban_tagihan | Σ langganan setara-bulanan di amplop belanja (mingguan × 52/12, tahunan ÷ 12) ÷ T1 |

## 4. Sinyal — deteksi pola

| Kode | Sinyal | Definisi |
|---|---|---|
| S1 | Struk | Transaksi viewer dengan deskripsi `NAMA (Toko)` dari toko yang sama, dirantai bila `created_at` dua transaksi berurutan berjarak ≤ 10 detik. Satu kiriman batch tercatat berurutan dalam hitungan milidetik, jadi satu struk = satu rantai; kiriman kedua yang terpisah beberapa detik membentuk rantai baru |
| S2 | Outlier | > 2× median transaksi amplop itu (90 hari) **dan** > 30% dana amplop (sama dengan `projection.py`) |
| S3 | Pola rutin | `sinking.detect_interval` (mingguan/bulanan/…) + stabilitas nominal, yang belum cocok dengan langganan aktif (tumpang tindih token ≥ 0,5 dan nominal ±15%) |
| S4 | Kemungkinan dobel | Dua transaksi di amplop sama, nominal sama, deskripsi mirip (tumpang tindih token ≥ 0,8), `created_at` berjarak ≤ 10 menit, dan berada di **rantai S1 yang berbeda** (atau bukan bagian struk). Barang kembar di dalam satu rantai tidak ditandai. Kiriman ulang dengan `client_ref` yang sama sudah ditolak server (`idempotency.py`), jadi S4 hanya untuk kiriman baru yang isinya sama |
| S4b | Struk terkirim dua kali | Dua rantai S1 dari toko yang sama dalam ≤ 30 menit dengan ≥ 80% pasangan (nominal, deskripsi) identik. Satu penanda untuk seluruh grup: "Struk {toko} sepertinya tercatat dua kali ({n} barang)" |
| S5 | Lonjakan | variabel 7 hari amplop > 2× median variabel per 7 hari amplop itu di 3 periode lalu, dengan selisih ≥ Rp100 rb |
| S6 | Hari lewat jatah | Hari k dengan belanja variabel > J0 hari k. J0 dihitung ulang per hari dari saldo awal hari k, jadi warna batang grafik tidak lagi diukur dengan garis hari ini |
| S7 | Amplop menganggur | Amplop belanja dengan terpakai ≤ 10% dana pada d ≥ 50% D, dan tanpa tagihan tersisa |
| S8 | Kekurangan kronis | Median terpakai 3 periode > jatah × 1,15 (jatah = `budget_amount`, kalau kosong median alokasi), **atau** ditambal ≥ 3× di ≥ 2 dari 3 periode |
| S9 | Kelebihan kronis | Median terpakai 3 periode ≤ 60% jatah, dan tidak pernah ditambal |
| S10 | Nominal tagihan berubah | Pembayaran "🔄 X" periode ini berbeda > 5% dari nominal langganan X |
| S11 | Langganan ganda | Dua langganan aktif dengan tumpang tindih token ≥ 0,6 dan nominal ±10% |
| S12 | Pemasukan terlambat | P2 = 0 dan t > ps + P5 + 3 hari |
| S13 | Pemasukan lebih kecil | P2 < 0,8 × P4, setelah lewat ps + P5 + 3 hari |
| S14 | Belum dijatah | P3 > Rp10 rb, lebih dari 24 jam sejak pemasukan dicatat |
| S15 | Lupa catat | K3 ≥ 2 hari, padahal dalam 14 hari terakhir user mencatat di ≥ 10 hari |
| S16 | Sisa amplop non-rollover | r ≤ 3 dan ada amplop `is_rollover = false` dengan bebas > 0. Saldo ini akan di-reset ke 0 oleh `rollover.py` |
| S17 | Tren | Terpakai amplop sampai hari ke-d vs periode lalu sampai hari ke-d yang sama: selisih ≥ 25% **dan** ≥ Rp100 rb |
| S18 | Gajian bergeser | Pemasukan terbesar di 2 dari 3 periode terakhir masuk ≥ 3 hari dari `payday_day` |
| S19 | Tagihan dibayar manual | M13 > 0: ada transaksi bernominal persis sama dengan tagihan yang statusnya masih belum dibayar. Sisa bebas sudah benar (M4 menganggapnya lunas), tapi kartu Tagihan dan pengingat masih menagih |

## 5. Bentuk insight, tone, skor, keyakinan, penekanan

### Bentuk insight
- `id` = `<aturan>:<entitas>`, stabil (dipakai untuk dismiss); `slot[]`.
- `tone`, `chip` (≤ 20 huruf), `judul`, `isi` (≤ 2 kalimat).
- `fakta[]` (label + nilai; sekaligus cara hitung), `aksi[]` (lihat katalog CTA di `01-desain.md`).
- `dasar` (data & keyakinan), `skor`, `kunci_dismiss`, `terkait[]` (untuk penekanan).

### Tone, ditentukan oleh jangka waktunya
| Tone | Arti | Contoh |
|---|---|---|
| danger | Sudah terjadi dan merugikan sekarang | Telat bayar, amplop minus, sisa bebas negatif, lewat jatah hari ini ≥ 1,5× |
| warn | Akan terjadi sebelum periode selesai kalau tidak ada tindakan | Sisa bebas habis ±24 Okt, tagihan 2 hari lagi dengan dana kurang |
| info | Struktural, jangka panjang, atau konteks | Dana darurat tipis, jatah kekecilan, pola rutin, pemasukan dicatat pasangan |
| ok | Aman atau kabar baik | Cukup sampai akhir periode, target tercapai |

### Urutan di daftar: kelompok tone dulu, baru skor
Kandidat diurutkan **per kelompok tone** (danger → warn → info), dan skor hanya mengurutkan di dalam kelompoknya. Dengan begitu insight struktural (info) tidak pernah melompati peringatan periode berjalan (warn), berapa pun rupiahnya.

skor = 100 × K × (0,45 · U + 0,35 · I + 0,20 · A)

- **U, urgensi:** 1,0 sudah terjadi · 0,8 dalam ≤ 3 hari · 0,6 dalam ≤ 7 hari · 0,4 sebelum akhir periode · 0,2 struktural / periode depan.
- **I, dampak:** min(1, rupiah_terdampak ÷ (10% × dana_belanja)). `rupiah_terdampak` didefinisikan per aturan di tabel berikut; aturan yang tidak ada di tabel memakai 0.
- **A, aksi:** 1,0 CTA satu langkah · 0,7 CTA membuka form/halaman · 0,4 tanpa CTA.
- **K, keyakinan:** tinggi 1,0 · sedang 0,8 · rendah 0,6.
- Seri diputus berurutan oleh: rupiah_terdampak, lalu id.

| Aturan | rupiah_terdampak | U |
|---|---|---|
| HAR-01 | T5 − J0 (kelebihan hari ini) | 1,0 |
| PER-01 | T9 (kekurangan sampai akhir periode) | 0,4; 0,8 bila T10 ≤ t + 3 |
| PER-02 | |T3| | 1,0 |
| PER-06 | sisa yang akan hangus (S16) | 0,8 |
| AMP-01 | |sisa(e)| | 1,0 |
| AMP-02 / AMP-03 | laju(e) × r − bebas(e) | 0,8 bila habis ≤ 3 hari, selain itu 0,4 |
| AMP-04 | total tambalan periode ini + kekurangan sisa periode (bila AMP-02/03 amplop itu menyala) | 0,4 bila amplopnya habis/akan habis sekarang; selain itu 0,2 |
| AMP-05 / AMP-06 | |median terpakai − jatah| per periode | 0,2 |
| AMP-08 | variabel 7 hari − median 7 hari | 0,6 |
| AMP-09 | `budget_amount` | 0,4 |
| TAG-01 / TAG-02 | nominal tagihan + kekurangan amplop tagihannya | 1,0 / 0,8 |
| TAG-04 | nominal − sisihan terkumpul | 0,6 |
| TAG-06 | selisih nominal | 0,2 |
| INC-01 | P4 (pemasukan yang biasanya sudah masuk) | 0,8 |
| INC-03 | P4 − P2 | 0,4 |
| INC-04 | P3 | 0,6 |
| TAB-01 / TAB-03 | setoran saran periode ini: (target − G1) ÷ 24 untuk target tanpa tenggat, ÷ bulan tersisa untuk target bertenggat; **0 saat PER-01/PER-02 menyala** (lihat penekanan 7) | 0,2 |
| TAB-02 | G5 − setoran periode ini | 0,6 bila tenggat ≤ 3 bulan, selain itu 0,2 |
| DAT-03 / S4b | nominal yang diduga dobel | 1,0 |
| DAT-06 | nominal tagihan | 0,8 |
| Lainnya (TAG-05, INC-06, TAB-06, DAT-01/02/04/05, PP-*) | 0 | 0,2 |

### Keyakinan
- **Fakta** (telat, minus, lewat jatah, tercapai): selalu tinggi.
- **Proyeksi periode berjalan:** tinggi bila d ≥ 7 dan ada ≥ 10 transaksi variabel di jendela; sedang bila d ≥ 3 dan ≥ 5 transaksi; selain itu rendah. Aturan proyeksi tidak menyala bila d < 3.
- **Pola lintas periode** (S3, S8, S9, S13, S17, S18): `confidence.py` — tinggi bila ≥ 4 periode aktif dan sebaran < 50%; sedang bila ≥ 2 periode; selain itu rendah.
- **Efeknya:** keyakinan rendah → tone maksimal warn, kata "kemungkinan", tanpa CTA pemindah dana. Keyakinan sedang → angka diberi "±".

### Penekanan & penggabungan (wajib)
1. **Satu masalah, satu item.** Aturan yang menyangkut entitas yang sama digabung; tone dan skor mengikuti yang tertinggi, faktanya digabung.
2. **Kekurangan total menyerap kekurangan per amplop.** Bila PER-01 menyala, AMP-02 dan AMP-03 tidak tampil sendiri di daftar, tapi menjadi "Rincian" PER-01 (penyumbang kekurangan). Alasannya: memindah dana antar amplop tidak menutup kekurangan total. Yang bisa menutupnya hanya mengerem laju atau pemasukan.
3. **Tagihan menyerap amplopnya.** TAG-01 dan TAG-02 menyerap AMP-01 untuk amplop tagihannya.
4. **Pemasukan terlambat didahulukan.** Bila INC-01 menyala, aksi kekurangan lain mendapat alternatif "tunggu pemasukan", dan CTA "Catat pemasukan" diletakkan pertama.
5. **Kabar baik tidak masuk daftar AI Advisor.** Insight ok hanya tampil di chip KPI, kecuali daftar kosong; maka tampil "Semua aman" + satu kabar baik terbaik.
6. **Hari ini menyatu ke periode.** Bila PER-01 menyala, HAR-01 tidak tampil sebagai item sendiri di daftar: faktanya ("hari ini {rasio}× jatah") masuk ke isi PER-01, dan CTA batas hariannya sama. HAR-01 tetap tampil penuh di chip KPI Jatah hari ini. HAR-01 masuk daftar hanya bila PER-01 tidak menyala, yaitu saat periode masih aman tetapi hari ini lewat ≥ 1,5× jatah.
7. **Tidak menyarankan menabung saat defisit.** Bila PER-01 atau PER-02 menyala, CTA "Setor" di TAB-01/03/04 diganti "Rencanakan di alokasi berikutnya" (membuka rekomendasi alokasi periode depan) dan rupiah_terdampak-nya dihitung 0, karena tidak ada sisa bebas yang bisa disetor. TAB-02 bertenggat ≤ 1 bulan dikecualikan: tetap tampil apa adanya, sebab tenggatnya nyata.
8. **Batas harian menghormati rencana dana.** Bila perencana (§8) memakai amplop e sebagai sumber, semua CTA batas harian dan angka "maksimal/hari" untuk e dihitung dari bebas_setelah_rencana(e) = bebas(e) − dana yang direncanakan keluar dari e. User tidak boleh diberi batas dari uang yang di item lain diminta digeser.

## 6. Katalog aturan

Format tiap aturan: **slot** · **pemicu** · **tone** · **chip** · judul/isi · fakta · **CTA** · catatan. `{…}` adalah variabel template.

### A. Hari ini

**HAR-01 · Lewat jatah hari ini**
- Slot: KPI Jatah hari ini; daftar bila ≥ 1,5× J0 **dan PER-01 tidak menyala** (penekanan 6).
- Pemicu: T5 > J0. Tone: danger bila ≥ 1,5× J0, selain itu warn.
- Chip: "{rasio}× jatah" (bila ≥ 1,5×) atau "Lewat {rp lebih}".
- Judul: "Belanja hari ini {rasio}× jatah". Isi: "Lewat {rp lebih}. {penyumbang} menyumbang {x}%."
  - Penyumbang = struk terbesar (S1) bila ≥ 40% T5; kalau tidak, amplop terbesar.
- Fakta: jatah hari ini sejak pagi (J0) · aman {r} hari ke depan (J1) · J1 turun {J0 − J1}/hari · terbesar hari ini: {amplop} {rp}.
- CTA: Lihat transaksi hari ini · Batas harian {amplop} {floor100(bebas(e) ÷ r)} (bila satu amplop ≥ 50% T5) · Tanya di chat.
- Catatan: kalau penyebabnya outlier, HAR-03 yang tampil. Pembayaran tagihan dan penyesuaian tidak dihitung.

**HAR-02 · Mendekati jatah**
- Slot: KPI. Pemicu: T5 ≥ 80% J0 dan belum lewat. Tone: warn.
- Chip: "Sisa {rp} hari ini".

**HAR-03 · Belanja besar satu kali**
- Slot: KPI; penanda baris di Transaksi. Pemicu: ada outlier (S2) hari ini. Tone: info.
- Chip: "Belanja besar {rp}".
- Isi: "Tidak dihitung sebagai kebiasaan harian. Aman {r} hari ke depan jadi {J1}/hari."
- CTA: Lihat transaksi.

**HAR-04 · Hari ini aman**
- Slot: KPI. Pemicu: T5 < 80% J0. Tone: ok. Chip: "Sisa {rp} hari ini".

**HAR-05 · Belum ada catatan hari ini**
- Slot: KPI. Pemicu: jam ≥ 20.00 waktu user, belum ada transaksi hari ini, dan user biasa mencatat setiap hari (dasar S15). Tone: info.
- Chip: "Belum ada catatan".
- CTA: Catat · Hari ini tidak belanja (check-in, sama dengan tombol bot).

### B. Periode & sisa bebas

**PER-01 · Sisa bebas tidak cukup sampai akhir periode**
- Slot: KPI Sisa bebas (chip "Habis ±{tgl}"), KPI Terpakai (chip "Lewat ±{rp}"), daftar.
- Pemicu: d ≥ 3 dan T9 > 0.
- Tone: warn; danger bila T10 ≤ t + 3 atau T9 ≥ 50% dari max(T3, 0).
- Judul: "Rem belanja harian ke {J1}".
- Isi: "{Hari ini {rasio}× jatah; }{n} dari 7 hari terakhir lewat jatah. Kalau tetap {T4}/hari, dana belanja kurang ±{T9} sebelum {pe}." Bagian pertama hanya bila HAR-01 ikut menyala (penekanan 6).
- Fakta (Rincian):
  - sisa bebas {T3} ÷ {r} hari = {J1}/hari;
  - rata-rata 7 hari terakhir {T4}/hari;
  - 3 penyumbang terbesar menurut porsi_7h(e) (M12), dengan persennya;
  - penyebab non-harian: amplop tagihan minus, tagihan yang belum dibayar.
- CTA:
  - Batas harian di penyumbang terbesar (amplop keinginan didahulukan), dihitung dari bebas_setelah_rencana(e) ÷ r (penekanan 8).
  - Catat pemasukan (bila INC-01 menyala).
  - Pakai tabungan (hanya bila T3 < 0, selalu eksplisit).
  - Tanya di chat.

**PER-02 · Sisa bebas negatif**
- Pemicu: T3 < 0. Tone: danger. Chip: "Minus {rp}".
- Judul: "Dana belanja sudah minus {rp}".
- CTA: Catat pemasukan · Tutup dari tabungan (lewat perencana §8; tabungan umum dulu, dana darurat terakhir).

**PER-03 · Lebih cepat dari waktu**
- Slot: KPI Terpakai, Analitik.
- Pemicu: persen terpakai variabel − persen waktu ≥ 15 poin. Tone: info (warn bila PER-01 juga menyala).
- Chip: "{x}% dana, {y}% waktu".

**PER-04 · Laju membaik**
- Pemicu: laju 7 hari ≤ 85% laju periode, dan T9 = 0. Tone: ok.
- Chip: "Laju turun {z}%".
- Isi: "Kalau bertahan, cukup sampai {pe} dengan sisa ±{rp}."

**PER-05 · Cukup sampai akhir periode**
- Pemicu: T9 = 0. Tone: ok. Chip: "Cukup s/d {pe}".
- Isi: "Perkiraan sisa ±{T3 − T4 × r} di akhir periode."

**PER-06 · Menjelang akhir periode**
- Slot: daftar (info ber-CTA).
- Pemicu: r ≤ 3, dan ada S16 atau perkiraan sisa > Rp50 rb.
- Judul: "Sisa ±{rp} — pindahkan ke tabungan?"
- Isi: "{rp} di {amplop non-rollover} akan kembali ke 0 saat periode berganti."
- CTA: Pindahkan ke {tabungan} (lewat perencana §8).

**PER-07 · Awal periode**
- Slot: daftar. Pemicu: d ≤ 2. Tone: info.
- Judul: "Periode baru: {ringkasan periode lalu}" (jumlah amplop minus, jumlah tambalan, amplop terbesar).
- CTA: Bagi pemasukan (rekomendasi alokasi) · Lihat periode lalu.

### C. Amplop

**AMP-01 · Amplop minus**
- Slot: Amplop, daftar. Pemicu: sisa(e) < 0. Tone: danger. Chip: "Minus {rp}".
- Isi: "Lewat {rp} dari dananya{, sudah ditambal n×}."
- CTA: Tutup minus (lewat perencana §8).
- Catatan: amplop tagihan digabung ke TAG-01/TAG-02.

**AMP-02 · Amplop habis**
- Pemicu: sisa(e) ≤ 0 (bukan minus), r > 0, laju(e) > 0. Tone: warn. Chip: "Habis".
- Isi: "Perlu ±{laju(e) × r} sampai {pe}."
- CTA: Geser {rp} (lewat perencana §8).
- Catatan: ditekan PER-01 bila kekurangan total menyala.

**AMP-03 · Amplop akan habis** (pengganti `env_depletion`)
- Pemicu: d ≥ 3, bebas(e) > 0, laju(e) × r > bebas(e). Tone: warn; danger bila habis dalam ≤ 3 hari.
- Chip: "Habis ±{tgl}". Judul: "{amplop}: maksimal {floor100(bebas(e) ÷ r)}/hari".
- CTA: Batas harian · Geser {kekurangan} (lewat perencana §8).
- Catatan: ditekan PER-01. Horizon untuk pemasukan harian/mingguan tetap seperti sekarang.

**AMP-04 · Ditambal berulang**
- Pemicu: M11 ≥ 3 periode ini. Tone: info; warn bila AMP-02/AMP-03 juga menyala dan PER-01 tidak.
- Chip: "Ditambal {n}×". Judul: "{amplop} ditambal {n}× — jatahnya kekecilan".
- Isi: "Jatah awal {M1 − tambalan}, kebutuhannya ±{laju(e) × D} per periode. Total tambalan {rp} ({n}×){ semuanya dari {sumber} | , terbesar dari {sumber}}{, yang juga menipis}." Kalimat sumber memakai "semuanya dari" bila satu sumber, "terbesar dari" bila lebih dari satu, supaya total tambalan tidak tertukar dengan porsi satu amplop.
- CTA: Naikkan jatah jadi {ceil10rb(laju(e) × D)} mulai periode depan · Geser untuk sisa periode ini (bila PER-01 tidak menyala).

**AMP-05 · Kekurangan kronis** — Pemicu: S8. Tone: info. CTA: Naikkan jatah jadi {ceil10rb(median terpakai)}.

**AMP-06 · Kelebihan kronis**
- Pemicu: S9. Tone: info.
- Isi: "3 periode terakhir hanya terpakai rata-rata {x}% dari jatah."
- CTA: Turunkan jatah jadi {ceil10rb(median × 1,1)}, sisanya ke {tabungan}.

**AMP-07 · Menganggur periode ini**
- Pemicu: S7. Tone: info.
- Hanya tampil di Amplop dan Analitik; dipakai perencana sebagai kandidat sumber dana.

**AMP-08 · Lonjakan**
- Pemicu: S5. Tone: warn. Chip: "{k}× biasanya".
- Isi: "{amplop} 7 hari terakhir {rp}, biasanya {rp}."
- CTA: Lihat transaksi {amplop}.

**AMP-09 · Belum didanai**
- Pemicu: dana(e) = 0, amplop kebutuhan, `budget_amount` > 0, d ≥ 2. Tone: info; warn bila ada tagihan di amplop itu.
- CTA: Alokasikan.

**AMP-10 · Batas harian sering terlewat**
- Pemicu: batas terlewat ≥ 3 dari 7 hari terakhir. Tone: info.
- Isi: "Batas {rp}/hari terlewat {n} dari 7 hari; rata-rata belanjanya {rp}."
- CTA: Sesuaikan batas jadi {rp} · Biarkan.

**AMP-11 · Tren vs periode lalu**
- Pemicu: S17. Tone: info. Slot: Analitik, Amplop.
- Isi: "{+/−x}% dibanding periode lalu di hari yang sama."

### D. Tagihan & langganan

**TAG-01 · Tagihan telat**
- Slot: KPI Tagihan, Langganan, daftar. Pemicu: status `overdue`. Tone: danger.
- Chip: "{nama} telat {n} hari".
- Isi: "{rp}, jatuh tempo {tgl}." Bila bebas(amplop tagihan) < nominal, ditambah: "Amplop {e} {sisa/minus} {rp}, jadi perlu {rp}."
- CTA: Geser & bayar (lewat perencana §8) bila dana amplop kurang; selain itu Bayar.
- Catatan: menyerap AMP-01 untuk amplop tagihannya.

**TAG-02 · Jatuh tempo ≤ 3 hari, dana kurang**
- Tone: warn; danger pada hari jatuh tempo. Chip: "{nama} {n} hari lagi".
- CTA: Geser & bayar · Bayar sekarang (boleh selama jatuh tempo di periode aktif, sesuai PR #55).

**TAG-03 · Jatuh tempo ≤ 3 hari, dana cukup** — Tone: info. CTA: Bayar sekarang.

**TAG-04 · Tagihan tahunan mendekat**
- Pemicu: langganan tahunan dengan next_run ≤ 60 hari lagi dan saldo sisihannya < nominal. Tone: warn.
- Isi: "Butuh {rp} pada {tgl}; terkumpul {rp}. Sisihkan {rp}/bulan."
- CTA: Geser sekarang · Atur sisihan.

**TAG-05 · Beban tagihan tinggi**
- Pemicu: K4 > 40%. Tone: info.
- Isi: "Tagihan rutin {rp}/bulan, {x}% dari dana belanja."
- CTA: Tinjau langganan.

**TAG-06 · Nominal tagihan berubah** — Pemicu: S10. Tone: info. CTA: Perbarui nominal jadi {rp}.

**TAG-07 · Pola rutin → jadikan langganan**
- Pemicu: S3 dengan keyakinan ≥ sedang. Tone: info. Slot: penanda baris di Transaksi, Langganan.
- CTA: Jadikan langganan (prefill dari `actions` di `sinking.py`).

**TAG-08 · Langganan ganda** — Pemicu: S11. Tone: info. CTA: Lihat keduanya.

**TAG-09 · Semua lunas** — Tone: ok. Chip: "Lunas semua" atau "Berikutnya {nama} {tgl}".

### E. Pemasukan

**INC-01 · Pemasukan belum masuk**
- Slot: KPI Income, daftar. Pemicu: S12. Tone: warn; danger bila T3 < 0.
- Chip: "Belum masuk".
- Isi: "Biasanya masuk sekitar tgl {ps + P5}, ±{P4}."
- CTA: Catat pemasukan (jumlah terisi P4, bisa diubah) · Ingatkan besok.

**INC-02 · Pemasukan dicatat anggota lain**
- Slot: KPI Income. Pemicu: P1 = 0 dan P2 > 0. Tone: info.
- Chip: "Terisi dari {nama}".
- Isi: "Belum ada pemasukan atas namamu, tapi amplop bersama sudah terisi dari pemasukan {nama}. Tidak perlu dicatat ulang."
- CTA: Catat pemasukanku.
- Catatan: menggantikan "Belum dicatat" yang palsu dan mencegah pemasukan tercatat dua kali. Yang ditampilkan hanya nama pencatat dan dana yang masuk ke amplop bersama, bukan total pemasukan pribadi anggota lain.

**INC-03 · Pemasukan lebih kecil dari biasa**
- Pemicu: S13. Tone: warn.
- Isi: "Pemasukan periode ini {rp}, biasanya {P4} (−{x}%)."
- CTA: Sesuaikan alokasi (rekomendasi dihitung dengan pemasukan baru).

**INC-04 · Pemasukan belum dijatah**
- Pemicu: S14. Tone: warn. Chip: "{rp} belum dibagi".
- CTA: Bagi sekarang (rekomendasi alokasi).

**INC-05 · Saving rate**
- Slot: KPI Income. Tone: ok bila P6 ≥ 10% (chip "Saving rate {x}%"); info bila turun ≥ 5 poin dari mediannya.

**INC-06 · Tanggal gajian bergeser**
- Pemicu: S18. Tone: info.
- Isi: "2 dari 3 periode terakhir pemasukan masuk tgl {x}, sedangkan pengaturan tgl {payday_day}."
- CTA: Ubah Tanggal Gajian.

### F. Tabungan & target

**TAB-01 · Dana darurat**
- Slot: KPI Tabungan, daftar (info).
- Pemicu dan tone: G8 < 1 bulan → info dengan skor naik; 1–3 bulan → info; ≥ 3 bulan → ok.
- Chip: "Darurat {x}%" atau "Darurat {n} bln".
- Isi: "{saldo} dari {target}; setara {G8} bulan belanja."
- CTA: Setor ke darurat. Saat PER-01/PER-02 menyala: "Rencanakan di alokasi berikutnya", dengan kalimat "Sisa bebas periode ini sedang kurang, jadi setoran dijadwalkan periode depan." (penekanan 7).

**TAB-02 · Target bertenggat tertinggal**
- Pemicu: G5 > G3 × 1,1. Tone: warn bila tenggat ≤ 3 bulan lagi, selain itu info.
- Chip: "{nama} tertinggal". Isi: "Perlu {G5}/bulan sampai {tenggat}, biasanya {G3}."
- CTA: Setor {G5 − setoran periode ini} · Mundurkan tenggat.

**TAB-03 · Target tanpa setoran** (pengganti `saving_stale`) — Pemicu: G2 = 0 dua periode berturut-turut. Tone: info. CTA: Setor.

**TAB-04 · Hampir tercapai** — Pemicu: G4 ≥ 90%. Tone: ok. Chip: "Kurang {rp}". CTA: Setor sisanya.

**TAB-05 · Tercapai** — Pemicu: G4 ≥ 100%. Tone: ok, tampil sekali lalu diam. CTA: Tandai selesai · Pakai untuk tujuannya.

**TAB-06 · Terlalu banyak target paralel**
- Pemicu: ≥ 5 target aktif dan median progres < 15%. Tone: info.
- Isi: "Setoran tersebar ke {n} target, jadi yang terpenting naik pelan."
- CTA: Atur prioritas.

**TAB-07 · Setoran periode ini** — Tone: ok. Chip: "+{rp} periode ini".

### G. Kebersihan data

**DAT-01 · Cocokkan saldo sudah lama** — Pemicu: K1 > 14 hari dan ≥ 20 transaksi sejak itu. Tone: info. CTA: Cocokkan saldo.

**DAT-02 · Selisih terakhir besar**
- Pemicu: K2 > 5% dana belanja. Tone: info.
- Isi: "Cocokkan terakhir selisih {rp}. Cocokkan lebih sering supaya analisa tetap akurat."

**DAT-03 · Kemungkinan dobel**
- Pemicu: S4 atau S4b. Tone: warn. Slot: penanda baris Transaksi; daftar bila nominal ≥ Rp100 rb.
- CTA: Hapus salah satu · Bukan dobel. Untuk S4b: Hapus duplikat ({n} barang) · Bukan dobel, satu konfirmasi untuk seluruh grup.
- "Bukan dobel" mematikan penanda untuk pasangan itu secara permanen (Redis).

**DAT-06 · Tagihan sepertinya sudah dibayar**
- Pemicu: S19. Tone: warn. Slot: KPI Tagihan, Langganan, penanda baris Transaksi, daftar.
- Isi: "Transaksi {deskripsi} {rp} nominalnya sama dengan tagihan {nama}. Sisa bebas sudah menghitungnya lunas, tapi tagihannya masih tercatat belum dibayar."
- CTA: Tandai lunas (memajukan `next_run`, tanpa transaksi baru) · Bukan pembayaran tagihan (M4 berhenti menganggapnya lunas untuk periode ini).
- Catatan: ini menutup celah hitung ganda antara M2 dan M4 sekaligus menyamakan `reserved.py` (nominal persis) dengan `recurring_status.py` (deskripsi "🔄 …"), yang hari ini bisa saling bertentangan.

**DAT-04 · Lupa catat?** — Pemicu: S15. Tone: info. CTA: Catat · Hari ini tidak belanja.

**DAT-05 · Amplop belum diklasifikasi**
- Pemicu: ≥ 1 amplop belanja tanpa needs/wants. Tone: info.
- Isi: "Klasifikasi membantu AI memilih sumber dana yang aman."
- CTA: Klasifikasikan.

### H. Sesudah catat, simulasi, dan chat

**FB-01 · Cermin dampak sesudah simpan** (rancangan Pikir-Pikir §2)
- Slot: sheet/toast di web, balasan konfirmasi di bot.
- Pemicu: nominal ≥ threshold Pikir-Pikir, atau transaksi mengubah status amplop/periode.
- Isi: "Sisa {amplop} {rp} · aman/hari jadi {J1 baru} ({Δ})." Ditambah peringatan bila transaksi ini memicu AMP-03 atau PER-01.
- CTA: Geser (bila amplop minus) · Lihat.

**SIM-01 · "Aman beli?"**
- Slot: chat ("aman beli {x}?"), tombol di form catat.
- Amplop simulasi dipilih deterministik, memakai pencocok yang sudah dipakai pencatatan (`txn_nlp.find_best_envelope`: nama amplop yang disebut, lalu kata kunci yang dipelajari dari catatan sebelumnya). Bila tidak yakin, dipakai amplop belanja dengan variabel 7 hari terbesar, dan balasan menampilkan pilihan "ganti amplop".
- Cara hitung: T3, J1, dan T10 dihitung ulang seolah {x} dicatat di amplop itu.
- Jawaban:
  - ✅ bila J1 baru ≥ 90% J1 dan amplopnya cukup;
  - ⚠️ bila amplop cukup tapi J1 turun > 10%;
  - ❌ bila amplop atau T3 tidak cukup.
- CTA: Catat · Masukkan Incaran (setelah Pikir-Pikir Fase 3).

**CHAT · Pertanyaan yang dijawab mesin**
- Intent: "sisa", "kapan habis", "limit harian", "/status", "kenapa {amplop} habis?", "kenapa boros?", "tagihan bulan ini", "target {nama}".
- Jawabannya render dari insight yang sama: "kenapa boros?" menampilkan Rincian PER-01 + penyumbang, "kenapa {amplop} habis?" menampilkan fakta AMP-0x amplop itu.
- Tombol "Tanya" di web membuka chat dengan pertanyaan terisi. Tanpa LLM; kalau tidak dikenali, bot menawarkan pertanyaan yang tersedia.
- **Chip pertanyaan cepat.** Kotak "Tanya AI Advisor" tidak dibuka sebagai input bebas: saat disentuh, chat terbuka dengan 3–4 chip pertanyaan yang dibentuk dari insight yang sedang menyala (mis. "Kenapa lewat ±Rp525 rb?", "Aman beli Rp100 rb hari ini?", "Rincian dana KPR"). Ketikan bebas tetap boleh, tetapi user diarahkan ke pertanyaan yang pasti terjawab.

### I. Pikir-Pikir (setelah Fase 2/3)

**PP-01 · Refleksi jatuh tempo** — Slot: daftar (info). Pemicu: "Sepadan?" belum dijawab. CTA: Jawab.

**PP-02 · Incaran siap diputuskan** — Pemicu: now ≥ think_until. CTA: Beli → catat · Nggak jadi · Tunda.

**PP-03 · Pola menyesal**
- Pemicu: ≥ 3 jawaban "Menyesal" di amplop yang sama dalam 2 periode. Tone: info.
- CTA: Pakai Incaran untuk {amplop}.

## 7. Seleksi per slot

### Chip KPI
Setiap kartu selalu punya chip. Mesin mengambil aturan yang menyala dengan skor tertinggi, mengikuti urutan prioritas; kalau tidak ada yang menyala, chip ok yang tampil.

| Kartu | Urutan aturan | Bila tidak ada yang menyala |
|---|---|---|
| Jatah hari ini | HAR-01 › HAR-03 › HAR-02 › HAR-05 | HAR-04 |
| Sisa bebas | PER-02 › PER-01 › PER-06 | PER-04 › PER-05 |
| Terpakai periode ini | PER-01 › PER-03 › AMP-08 (terbesar) | PER-05 ("Sesuai jalur") |
| Income periode ini | INC-01 › INC-04 › INC-03 › INC-06 › INC-02 | INC-05 |
| Tagihan belum dibayar | TAG-01 › TAG-02 › TAG-04 › TAG-03 | TAG-09 |
| Tabungan | TAB-02 › TAB-01 › TAB-03 › TAB-06 › TAB-04 › TAB-05 | TAB-07 |

Baris analisa di grafik harian: S6 ("{n} dari 7 hari terakhir lewat jatah") + puncaknya. Kalau tidak ada: "Semua hari dalam jatah minggu ini".

**Peredaman chip.** Bila di Beranda ada ≥ 1 chip danger atau ≥ 2 chip warn, chip bertone info dan ok tampil redam: tanpa latar berwarna dan tanpa ikon ✦, hanya teks dengan garis tepi tipis. Isi popover-nya tetap lengkap. Tujuannya supaya mata langsung ke kartu merah/kuning.

**Cap waktu.** "Diperbarui baru saja" bila analisa dihitung < 5 menit lalu, selain itu "Diperbarui {jam}". Analisa dihitung ulang setiap ada perubahan data (cache dihapus, §14), jadi cap waktu ini selalu ≥ waktu transaksi terakhir.

### Kartu AI Advisor
1. **Kandidat:** insight danger/warn yang punya CTA, ditambah insight info ber-CTA bila kandidatnya kurang dari 3.
2. Jalankan penekanan & penggabungan (§5), lalu urutkan **per kelompok tone (danger → warn → info), skor di dalam kelompok**.
3. **Batas:** maksimal 3 item; maksimal 1 per amplop (kecuali danger); maksimal 2 dari domain yang sama.
4. **Sisanya:** "+N saran lain: {judul pendek}".
5. **Badge** = jumlah semua item, yang tampil maupun sisanya.
6. **Kosong:** "Semua aman" + satu insight ok terbaik.

### Halaman lain
- **Amplop:** satu insight terbaik per kartu, dari AMP-*, TAG-* untuk amplop itu, dan TAB-* untuk amplop tabungan. Kosong → baris ok ("Aman, ±{rp}/hari tersedia").
- **Transaksi:**
  - Banner = insight yang relevan dengan filter aktif (filter hari ini → HAR-*, filter amplop → AMP-*).
  - Penanda baris = HAR-03, DAT-03, TAG-07.
- **Alokasi:**
  - INC-04 / INC-03 di atas form.
  - Alasan per amplop dari AMP-04/05/06, TAG-04 (sisihan), TAB-02, dan AMP-01 (minus yang perlu ditutup).
  - Angka rekomendasi tetap dari `allocation.py`, disesuaikan dengan aturan-aturan ini.
- **Langganan:** TAG-* + ringkasan K4.
- **Analitik:** ringkasan 3 poin dari PER-03/04, AMP-08/11, hari terboros (S6), TAB-06.
- **Chat web & Telegram:**
  - Intent seperti §6H.
  - Ringkasan harian = chip Jatah hari ini + item #1 daftar.
  - Ringkasan mingguan = rekap minggu + 1 aturan struktural (AMP-04/05/06 atau TAB-02).

## 8. Perencana dana

Dipakai oleh semua CTA "Geser", "Geser & bayar", "Tutup minus", dan "Pindahkan ke tabungan".

1. **Kebutuhan.** Diurutkan: telat/jatuh tempo → amplop minus → amplop habis yang punya tagihan → lainnya. Bentuknya {amplop tujuan, jumlah, tenggat}.
2. **Sumber yang boleh dipakai:**
   - amplop belanja yang boleh diubah viewer (bersama, atau pribadi miliknya; **tidak pernah** amplop pribadi anggota lain);
   - tidak terkunci, dan bukan amplop tujuan;
   - surplus(e) > 0, dan tidak punya tagihan tersisa yang belum tertutup.
3. **Urutan sumber:**
   - (a) **Keinginan** (wants).
   - (b) **Kebutuhan dengan riwayat.** Surplus dihitung ulang dengan median belanja sisa periode (hari d sampai akhir) di 3 periode lalu, bila angka itu lebih besar dari laju × r.
   - (c) **Kebutuhan tanpa riwayat.** Hanya dipakai bila (a) + (b) tidak cukup, dan ditandai "cek dulu".
   - (d) Tabungan umum, lalu (e) dana darurat. Keduanya **tidak pernah otomatis**; hanya muncul sebagai CTA terpisah yang menyebut nama tabungannya.
   - Dalam satu tingkat, surplus terbesar didahulukan supaya sumbernya sedikit.
4. **Alokasi global.** Kebutuhan diproses berurutan. Satu sumber boleh dipakai beberapa kebutuhan, sampai surplusnya habis.
5. **Pembulatan.** Tiap sumber dibulatkan ke bawah ke Rp1.000; sumber terakhir menutup sisanya persis.
6. **Kekurangan yang tersisa.** Tampilkan "Masih kurang {rp}", dengan opsi Catat pemasukan atau Pakai tabungan.
7. **Centang default.** Sumber tingkat (a) dan (b) selalu tercentang. Sumber (c) "cek dulu" tercentang **hanya bila** (a) + (b) tidak cukup untuk kebutuhan bertone danger (tagihan telat, amplop minus), supaya tombol konfirmasi langsung menutup kebutuhan penuh; barisnya diberi badge kuning "Cek dulu: belum ada riwayat belanja". Untuk kebutuhan warn/info, sumber (c) tidak tercentang. Tabungan (d, e) tidak pernah tercentang.
8. **Rencana memengaruhi angka lain.** Setelah rencana dihitung, bebas_setelah_rencana(e) dipakai oleh semua CTA batas harian dan angka "maksimal/hari" (penekanan 8). T3 total tidak berubah oleh transfer antar amplop belanja.
9. **Eksekusi (konfirmasi satu langkah):**
   - Lembar konfirmasi menampilkan tiap pemindahan beserta alasan memilih sumbernya. Centang sumber bisa dilepas, lalu rencana dihitung ulang.
   - Satu tap → `POST /advisor/execute`: server **mengunci baris household** (`SELECT … FOR NO KEY UPDATE`, pola yang sudah dipakai `balance_check.py`), menghitung ulang saldo di dalam kunci, membandingkan dengan saldo yang dilihat user (409 bila berubah), lalu menjalankan semua transfer dan pembayaran tagihan dalam satu transaksi DB. Satu kunci per household: tidak perlu mengurutkan kunci per amplop, dan dua anggota yang mengeksekusi bersamaan diserialkan, bukan deadlock.
   - Idempoten dengan `client_ref` (Redis `txnref:*`, sama dengan pencatatan).
   - Kalau 409, rencana dihitung ulang dan ditampilkan lagi.

## 9. Anti-ganggu

- **Nanti:** disembunyikan sampai besok pukul 05.00 waktu user.
- **Sembunyikan periode ini:** sampai pe.
- **Tidak relevan** (di Rincian): aturan itu dimatikan untuk entitas itu selama 90 hari, dan dicatat untuk evaluasi aturan.
- **Muncul lagi lebih awal** hanya bila tone naik (info → warn → danger) atau rupiah terdampak naik ≥ 50% sejak disembunyikan.
- **Urungkan / Munculkan lagi** (revisi 17 Okt 2026, #91): user bisa membatalkan dismiss kapan saja.
  - Setelah menyembunyikan, toast "Disembunyikan sampai …" memberi tombol **Urungkan** (±6 detik).
  - Kartu AI Advisor menampilkan "N disembunyikan · Tampilkan": judul pendek, sampai kapan, dan **Munculkan lagi**.
  - Membatalkan menghapus status dismiss (bukan menyembunyikan ulang), berlaku seketika, hanya untuk dismiss milik viewer sendiri (`DELETE /advisor/dismiss`).
  - Permukaan lain yang membaca status dismiss (notifikasi proaktif S16, chat S17) memakai status terbaru: yang sudah dimunculkan lagi boleh dikirim/dijawab lagi.
- **Notifikasi proaktif** (Telegram, lonceng web, chat web):
  - maksimal 1 per hari dari advisor, isinya item #1 daftar;
  - jam tenang 21.00–07.00, kecuali tagihan yang jatuh tempo hari itu (dikirim pagi);
  - patuh preferensi notifikasi (memperbaiki pengingat tagihan yang sekarang mengabaikan `subscription_due_tg`).
- Hal yang sama tidak dikirim ke lebih dari 2 permukaan proaktif di hari yang sama.

## 10. Teks & format

- **Bahasa:** "kamu", kalimat aktif, isi ≤ 2 kalimat. Judul di daftar berupa aksi ("Lunasi…", "Rem…", "Naikkan…"); judul di KPI berupa temuan.
- **Dilarang:** kata yang menghakimi ("boros", "parah", "gagal"), tanda seru berlebihan, menyebut anggota lain secara negatif.
- **Angka:**
  - chip dan judul memakai `rpCompact` (Rp153 rb, Rp1,68 jt); fakta memakai `rpFull`;
  - nominal pemindahan dan pembayaran persis, tanpa pembulatan;
  - proyeksi diberi "±"; tanggal "24 Okt"; hari "Senin 12 Okt"; rasio 1 desimal ("1,8×").
- **Telegram:** tone dipetakan ke 🔴 danger, 🟡 warn, 🔵 info, 🟢 ok; web mengubahnya jadi ikon (PR #42).
- Semua template tinggal di `render.py`, tidak ada teks bebas di kode aturan, supaya web dan bot selalu sama.

## 11. Konstanta

Nilai default; bisa diatur lewat `AppSetting` tanpa deploy.

| Konstanta | Nilai | Dipakai di |
|---|---|---|
| Hari minimum untuk proyeksi | 3 | M8, PER-*, AMP-03 |
| Jendela laju | 7 hari, minimal 3 hari berbelanja | M8 |
| Cadangan surplus sumber | 10% | M10, §8 |
| Toleransi nominal langganan | ±10% | M7 |
| Outlier | > 2× median **dan** > 30% dana | S2 |
| Danger lewat jatah | ≥ 1,5× J0 | HAR-01 |
| Mendekati jatah | ≥ 80% J0 | HAR-02 |
| Jatuh tempo dekat | ≤ 3 hari | TAG-02/03 |
| Tagihan tahunan dilihat | 60 hari ke depan | TAG-04 |
| Beban tagihan tinggi | > 40% dana belanja | TAG-05 |
| Ditambal berulang | ≥ 3× per periode | AMP-04, S8 |
| Kekurangan / kelebihan kronis | > 115% / ≤ 60% jatah, 3 periode | S8, S9 |
| Lonjakan | > 2× median dan ≥ Rp100 rb | S5 |
| Tren | ≥ 25% dan ≥ Rp100 rb | S17 |
| Kemungkinan dobel | ≤ 10 menit, token ≥ 0,8, rantai S1 berbeda | S4 |
| Struk terkirim dua kali | ≤ 30 menit, ≥ 80% pasangan identik | S4b |
| Struk (rantai) | jeda berurutan ≤ 10 detik, toko sama | S1 |
| Tagihan dianggap lunas (M4) | nominal persis sama, periode ini | M4, S19 |
| Peredaman chip | ≥ 1 danger atau ≥ 2 warn | §7 |
| Setoran saran target tanpa tenggat | (target − saldo) ÷ 24 bulan | TAB-01/03 |
| Pemasukan terlambat | lewat hari biasa + 3 hari | S12 |
| Pemasukan lebih kecil | < 80% median 3 periode | S13 |
| Cocokkan saldo lama | > 14 hari dan ≥ 20 transaksi | DAT-01 |
| Selisih besar | > 5% dana belanja | DAT-02 |
| Cakupan dana darurat | < 1 bln / 1–3 bln / ≥ 3 bln | TAB-01 |
| Target paralel | ≥ 5 target, median progres < 15% | TAB-06 |
| Item daftar AI Advisor | 3 (1 per amplop, 2 per domain) | §7 |
| Notifikasi proaktif | 1/hari, jam tenang 21.00–07.00 | §9 |
| Nanti / tidak relevan | sampai 05.00 besok / 90 hari | §9 |
| Pola menyesal | ≥ 3 jawaban "Menyesal" per amplop dalam 2 periode (`pola_menyesal_n`) | PP-03 |

## 12. Contoh lengkap: Beranda 15 Okt 2026

Data diambil dari screenshot Beranda (periode 27 Sep – 26 Okt, Tanggal Gajian 27). Riwayat periode lalu tidak ada di screenshot, jadi aturan lintas periode tidak dihitung. Laju per amplop memakai rata-rata periode, karena data 7 hari per amplop juga tidak ada.

**Metrik:**
- D = 30, d = 19, r = 11.
- Dana belanja T1 = Rp11.285.200; terpakai T2 = Rp8.000.000 (71% dana; waktu 63%).
- KPR Rp1.600.000 belum dibayar (M4).
- Sisa bebas T3 = Rp1.685.200.
- Belanja hari ini T5 = Rp297.100; tidak ada tagihan, outlier, atau penyesuaian hari ini, jadi T5b = T5. J0 = floor100((1.685.200 + 297.100) ÷ 12) = **Rp165.100**. J1 = floor100(1.685.200 ÷ 11) = **Rp153.200**.
- Laju T4 = Σ variabel 7 hari terakhir (0 + 370 + 0 + 400 + 140 + 200 + 297,1 rb) ÷ 7 = Rp201.014/hari — persis rata-rata 7 batang terakhir grafik; 4 hari berbelanja, jadi jendela 7 hari dipakai.
- Kekurangan T9 = 201.014 × 11 − 1.685.200 = **±Rp525 rb**. Cukup sampai 23 Okt, **habis 24 Okt**. Proyeksi akhir Rp11.811.157.

**Chip KPI:**

| Kartu | Aturan | Chip | Inti analisa |
|---|---|---|---|
| Jatah hari ini | HAR-01 (danger) | 1,8× jatah | Lewat Rp132.000. Struk Indomaret (Rp137.300) menyumbang 46%; J1 turun Rp11.900/hari; terbesar Makan & Jajan Rp168.000 (56,5%) |
| Sisa bebas | PER-01 (warn) | Habis ±24 Okt | Rata-rata 7 hari Rp201 rb/hari vs aman Rp153.200/hari |
| Terpakai | PER-01 (warn) | Lewat ±Rp525 rb | Rp8 jt + KPR Rp1,6 jt + Rp201 rb × 11 = Rp11,81 jt vs dana Rp11,28 jt. Batang: hijau sampai penanda waktu 63%, kuning 63–71% |
| Income | INC-02 (info, **redam**) | Terisi dari Rina | Asumsi contoh: pemasukan periode ini dicatat Rina |
| Tagihan | TAG-01 (danger) | KPR telat 9 hari | Amplop Tagihan & Cicilan minus Rp408.174, jadi perlu Rp2.008.174. Batang: lunas 23% hijau, telat 77% merah |
| Tabungan | TAB-01 (info, **redam**) | Darurat 3% | Rp1,21 jt dari Rp35 jt = 0,11 bulan belanja. CTA "Rencanakan di alokasi berikutnya", karena PER-01 menyala |

Dua chip danger ada di Beranda, jadi chip Income dan Tabungan tampil redam (§7).

**Kartu AI Advisor** (kelompok tone, lalu skor §5):
1. **danger · TAG-01 Lunasi KPR — skor 100.** U = 1; I = min(1, 2.008.174 ÷ 1.128.520) = 1; A = 1.
2. **warn · PER-01 Rem belanja harian ke Rp153 rb — skor 54,3.** U = 0,4 (habis 24 Okt, 9 hari lagi); I = 525.957 ÷ 1.128.520 = 0,466; A = 1. Isi dibuka dengan "Hari ini 1,8× jatah" karena HAR-01 digabung (penekanan 6). CTA: Batas Makan & Jajan floor100(1.463.936 ÷ 11) = Rp133.000/hari; Makan & Jajan bukan sumber rencana dana, jadi angkanya tidak berubah (penekanan 8).
3. **info · AMP-04 Transport ditambal 7× — skor 58,2.** U = 0,4 (Transport habis sekarang); I = (391.500 + 260.816) ÷ 1.128.520 = 0,578; A = 1. Skornya lebih tinggi dari PER-01, tetapi tetap di bawahnya karena kelompok tone didahulukan.
   - Jatah awal Rp59.000; kebutuhan Rp23.711 × 30 = Rp711.316.
   - CTA: Naikkan jatah jadi **Rp720.000** mulai 27 Okt.
4. **Sisa daftar:** "+1 saran lain: Dana Darurat baru 3%" (TAB-01, skor 23: I = 0 karena defisit, A = 0,7). Badge = 4.

**Yang ditekan atau digabung:**
- HAR-01 (skor 69,1 bila berdiri sendiri, lebih tinggi dari PER-01) tidak jadi item: faktanya masuk PER-01, CTA-nya sama (penekanan 6).
- AMP-02 Transport (skor 64,1 bila berdiri sendiri), AMP-02 Hiburan & Self Care, AMP-03 Makan & Jajan (kurang Rp263.239), dan AMP-03 Pengeluaran Rahasia (kurang Rp127.211) masuk Rincian PER-01, karena kekurangannya kekurangan total.
- AMP-01 Tagihan & Cicilan digabung ke TAG-01.

**Rencana dana KPR (§8):** kebutuhan Rp2.008.174.
- (a) Pakaian, keinginan: surplus 473.000 − 1.579 × 11 × 1,1 = Rp453.894, dibulatkan menjadi **Rp453.000**.
- (c) Pendidikan, kebutuhan tanpa riwayat, ditandai "cek dulu": **Rp1.410.000**.
- (c) Kebutuhan Rumah, sumber terakhir: **Rp145.174**.
- Total Rp2.008.174 → Tagihan & Cicilan, lalu bayar KPR. Semua dalam satu konfirmasi. Kedua sumber (c) tercentang sejak awal, dengan badge "Cek dulu", karena (a) saja tidak cukup untuk kebutuhan danger (§8.7).

Mockup di canvas "AI Advisor — Jatahku" sudah disamakan dengan contoh ini.

## 13. Pengujian

- **Unit test per aturan.** Aturan adalah fungsi murni, diuji dengan fixture.
- **Skenario emas** (memperluas `app/tests/evaluator`):
  1. Periode normal: tidak boleh ada danger/warn.
  2. Hari 1–2: tidak ada proyeksi.
  3. Belanja besar sekali (outlier): HAR-03, bukan HAR-01 atau PER-01.
  4. Tagihan dibayar di hari pertama: tidak dianggap laju harian.
  5. Pemasukan dicatat pasangan: INC-02, bukan "Belum dicatat".
  6. Hari terakhir periode: tidak crash; J0 = sisa.
  7. Amplop pribadi anggota lain: tidak pernah muncul di insight, rencana, atau angka.
  8. Pendapatan harian/mingguan: horizon 1/7 hari.
  9. Transaksi dobel vs struk berisi barang kembar.
  10. Perencana: amplop terkunci, milik anggota lain, atau punya tagihan tidak dipakai sebagai sumber; tabungan tidak pernah otomatis.
  11. Kekurangan total vs kekurangan per amplop (penekanan §5.2).
  12. Dismiss, lalu tone naik → muncul lagi.
  13. Invarian J0: mencatat outlier, penyesuaian saldo, atau tagihan hari ini tidak mengubah J0; alokasi hari ini mengubahnya.
  14. Tagihan dibayar manual dengan nominal persis: M4 menganggap lunas (tidak ada hitung ganda di T3) dan DAT-06 menyala.
  15. Struk berisi 2 barang kembar dalam satu rantai S1: tidak ditandai dobel; struk yang sama dikirim ulang 40 detik kemudian: S4b menyala; kiriman ulang dengan `client_ref` sama: ditolak server, tidak ada transaksi baru.
  16. Urutan kelompok tone: info berskor 90 tetap di bawah warn berskor 40.
  17. HAR-01 tidak jadi item saat PER-01 menyala; jadi item saat PER-01 tidak menyala.
  18. Perencana memakai amplop e sebagai sumber → batas harian e turun sesuai bebas_setelah_rencana.
  19. Saat defisit, CTA setor TAB-01 berganti dan skor dampaknya 0.
  20. T4 sama dengan rata-rata 7 batang terakhir grafik; grafik tidak memuat amplop pribadi anggota lain.
- **Paritas.** Dari snapshot yang sama, KPI web, chat "sisa", `/status` Telegram, dan ringkasan harian harus menghasilkan angka identik.
- **Snapshot teks.** Template dibandingkan dengan teks yang disetujui, supaya perubahan kata selalu sengaja.
- **Performa.** Satu snapshot per permintaan dengan jumlah query tetap; target < 150 ms di VPS untuk 10 amplop; cache Redis 60–120 detik.

## 14. Struktur kode saat development dibuka

- **Modul** di `app/services/advisor/`:
  - `snapshot.py` (loader berkelompok), `metrics.py`, `signals.py`;
  - `rules/{hari,periode,amplop,tagihan,pemasukan,tabungan,data,umpan_balik}.py`;
  - `planner.py`, `select.py` (skor, penekanan, dismiss), `render.py` (template).
- **Endpoint:**
  - `GET /advisor/dashboard` dan `GET /advisor/page/{amplop|transaksi|alokasi|langganan|analitik}`;
  - `POST /advisor/plan` (hitung rencana dana) dan `POST /advisor/execute` (jalankan rencana; idempoten).
- **Bot dan ringkasan** (`nlp_cmd`, `handlers`, `summary.py`) memanggil `metrics` dan `render` langsung, bukan lewat HTTP. Rumus lama dihapus.
- **Cache:** kunci `advisor:{household_id}:{viewer_id}` (isi berbeda per viewer karena amplop pribadi), TTL 60–120 detik. Perubahan data oleh **anggota mana pun** menghapus semua kunci household itu (`advisor:{household_id}:*`), supaya Beranda anggota lain tidak menampilkan angka lama. Pemicu hapus: transaksi, transfer, pemasukan, pembayaran/lewati tagihan, ubah amplop, cocokkan saldo.
- **`POST /advisor/execute`:** kunci baris household (`with_for_update(key_share=True)`, seperti `balance_check.apply`), hitung ulang, bandingkan, jalankan, commit. `transfer_between_envelopes` yang ada sekarang tidak memakai kunci; **diputuskan 16 Okt: ikut dikunci di Fase 1 (sesi S5)** dengan pola yang sama.
- **Migrasi (diputuskan 16 Okt):** `envelopes.is_emergency` (boolean, default false), diisi otomatis `true` untuk amplop tabungan yang namanya mengandung "darurat"/"emergency"; bisa diubah user di pengaturan amplop. Dismiss tetap di Redis.
- **Urutan rilis** mengikuti fase di `01-desain.md`. Fase 1 mencakup §3 seluruhnya, aturan A, B, D, DAT-06, dan TAG/INC/TAB yang dipakai chip KPI, perencana dana, serta paritas bot.

## 15. Hasil review 16 Okt: diterima, dikoreksi, disanggah

Review pemilik produk (16 Okt 2026 sore) dicocokkan dengan kode `main` (`31eb446`). Ringkasannya:

| # | Temuan review | Keputusan | Perubahan di spesifikasi |
|---|---|---|---|
| A | T4 = Σ laju(e) hibrida ≠ rata-rata 7 batang grafik, padahal UI menulis "rata-rata 7 hari" | **Diterima** (solusi 1) | T4 = agregat variabel 7 hari ÷ 7 (fallback rata-rata periode); laju(e) hanya untuk aturan per amplop; M12 porsi_7h untuk penyumbang; grafik membaca deret metrik. Tambahan dari kode: `/analytics/daily-spending` ikut menghitung tagihan dan amplop pribadi anggota lain, jadi grafik memang harus pindah sumber |
| B | HAR-01 (skor 69,1) seharusnya masuk daftar tapi tidak tertulis | **Diterima** | Penekanan 6: HAR-01 menyatu ke PER-01 bila PER-01 menyala |
| C | rupiah_terdampak belum didefinisikan; info bisa melompati warn | **Diterima** | Tabel rupiah_terdampak + U per aturan; urutan kelompok tone dulu, skor di dalamnya. Tambahan: penekanan 7 (tidak menyarankan setor saat defisit), yang membuat TAB-01 di contoh tetap berskor 23 |
| D | J0 berubah di tengah hari karena T5 mengecualikan outlier/penyesuaian | **Diterima** | T5b (semua keluar hari ini kecuali tagihan) untuk J0; invarian J0 masuk uji #13. Pembayaran tagihan memang netral terhadap T3 karena sudah dipotong lewat M4 |
| E | Double-submit struk lolos S4 karena S1 menggabungkannya | **Diterima dengan koreksi** | S1 jadi rantai jeda ≤ 10 detik (satu batch tercatat dalam milidetik), S4 mensyaratkan rantai berbeda, S4b untuk struk terkirim dua kali. Koreksi: kiriman ulang dengan `client_ref` yang sama **sudah** ditolak server (`idempotency.py`, Redis `txnref:*`), jadi celahnya hanya untuk kiriman baru (mis. scan ulang) |
| F | Tagihan dibayar manual dihitung ganda di M2 dan M4 | **Diterima dengan koreksi** | Di kode hari ini `reserved.py` sudah menganggap tagihan lunas bila ada transaksi bernominal persis sama, tetapi `recurring_status.py` tetap menampilkannya belum dibayar: ketidaksesuaian ini sudah ada. Spesifikasi mengikuti aturan nominal persis untuk M4 (bukan ±10%, yang hanya untuk laju) dan menambah DAT-06 "Tandai lunas" |
| G | Batas harian bisa dihitung dari uang yang diminta digeser | **Diterima** | Penekanan 8 dan §8.8: bebas_setelah_rencana(e) |
| UI-1 | Warna batang Terpakai dan Tagihan tidak sejalan dengan chip | **Diterima** | Segmen kuning setelah penanda waktu saat PER-01; segmen merah untuk porsi telat |
| UI-2 | Popover menutupi angka kartu | **Diterima** | Popover di bawah kartu, selebar kartu; kartu aktif diberi garis tepi terang |
| UI-3 | Cap waktu 06.05 terkesan basi | **Disanggah sebagian, saran dipakai** | 06.05 di mockup memang sesudah transaksi terakhir (06.02), dan cache dihapus tiap perubahan, jadi angkanya tidak basi. Tetap diubah ke "Diperbarui baru saja" / "Diperbarui {jam}" karena lebih jelas |
| UI-4 | Copy AMP-04 ambigu soal total tambalan | **Diterima** | Template "Total tambalan {rp} ({n}×), semuanya dari / terbesar dari {sumber}" |
| UI-5 | Input bebas "Tanya AI" berisiko tidak dikenali | **Diterima** | Chip pertanyaan cepat dari insight yang menyala |
| Q1 | Kartu Income: pemasukan sendiri + konteks rumah tangga | **Diterima** | INC-02 sudah sesuai: angka utama P1; bila P1 = 0 dan P2 > 0, chip "Terisi dari {nama}" dengan dana yang masuk ke amplop bersama, bukan total pemasukan pasangan |
| Q2 | Redam chip info/ok saat ada danger/warn | **Diterima** | §7 Peredaman chip |
| Q3 | Semua insight untuk semua paket | **Diterima** | Tanpa biaya marginal. Catatan kode: `is_pro_feature` mendaftar export/analytics, tetapi `check_pro_access` tidak pernah dipanggil, jadi hari ini pun tidak ada yang dibatasi; semua 29 user Pro |
| Q4 | `is_emergency` hibrida dengan backfill nama | **Diterima** | §14 Migrasi |
| Q5 | "Cek dulu" tercentang default bila (a)+(b) kurang | **Diterima dengan batasan** | Hanya untuk kebutuhan danger; warn/info tidak tercentang (§8.7) |
| Ars-1 | Hapus cache seluruh anggota household | **Diterima** | §14 Cache |
| Ars-2 | Urutan pencarian amplop untuk SIM-01 | **Diterima dengan koreksi** | Tidak perlu pencari baru: `txn_nlp.find_best_envelope` (dipakai `suggest-envelopes` dan bot) sudah melakukan nama → kata kunci yang dipelajari; fallback amplop paling aktif + pilihan ganti |
| Ars-3 | `SELECT … FOR UPDATE` per amplop terurut `id` | **Disanggah, diganti** | Repo sudah punya pola kunci baris household (`balance_check.py`, `FOR NO KEY UPDATE`). Satu kunci per household menserialkan eksekusi dua anggota tanpa perlu urutan kunci per amplop, dan konsisten dengan kode yang ada |
