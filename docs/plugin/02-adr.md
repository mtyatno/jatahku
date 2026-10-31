# Plugin dan ruang usaha — keputusan arsitektur (ADR-P1 sampai P19)

**Status:** semua disetujui pemilik produk pada 31 Okt 2026. ADR-P1 sampai P7 adalah keputusan yang diambil selama perancangan; ADR-P8 sampai P19 adalah rekomendasi kajian dan rencana development yang disetujui sekaligus (sesi O1). Setiap PR plugin merujuk ADR yang relevan. Mengubah ADR = PR yang mengubah file ini dan disetujui pemilik produk.

Alasan lengkap dan perbandingan opsi ada di `01-kajian.md` (bagian "Keputusan untuk pemilik produk" memakai nomor kajian di kolom Sumber) dan di `05-desain-buku-usaha.md` bagian B (keputusan ruang usaha).

| ID | Keputusan | Alasan | Biaya kalau diubah nanti | Sumber |
| --- | --- | --- | --- | --- |
| ADR-P1 | Uang usaha dipisah lewat **ruang**: ruang usaha adalah household kedua (`households.type` = `rumah_tangga` atau `usaha`), dan satu user boleh menjadi anggota beberapa ruang. Menu inti sama di semua ruang; Fitur Tambahan hanya menambah; amplop tetap dipakai di ruang usaha | Data, anggota, dan visibilitas terpisah rapi; semua aturan amplop langsung berlaku di ruang usaha; mencegah pengeluaran pribadi tercatat sebagai uang usaha | Tinggi: kunci tabel, resolver, dan migrasi data | Kajian no. 2; ruang usaha 1 |
| ADR-P2 | Telegram dan chat web **hanya mencatat ke ruang keluarga** milik user. Tidak ada perintah `/ruang`, tidak ada transaksi ruang usaha atau Fitur Tambahan lewat chat. Dari ruang usaha, chat hanya menerima laporan dan notifikasi berawalan nama ruang, dengan tombol yang hanya membuka Jatahku | Banyak ruang dalam satu chat membingungkan user; paritas web ↔ Telegram tetap utuh di ruang keluarga | Sedang: handler bot dan manifest | Kajian no. 14; ruang usaha 2, 3 |
| ADR-P3 | Laporan dan data keuangan usaha di chat (mis. `/laba`) **hanya untuk pemilik dan admin** ruang usaha; menu perintah Telegram per chat mengikuti peran | Karyawan tidak boleh melihat laba, kas, atau omzet | Rendah | Kajian no. 15 |
| ADR-P4 | Satu ruang usaha boleh berisi **banyak anggota** dengan peran Pemilik, Admin, Karyawan (`HouseholdRole` owner, admin, member) dan batasan dari admin. Ruang keluarga tiap anggota tidak terhubung ke ruang usaha dan tidak terlihat dari sana | Toko dengan karyawan; privasi keuangan pribadi karyawan | Tinggi: model izin | Kajian no. 16; ruang usaha 5 |
| ADR-P5 | Pencatatan ruang usaha di web dan aplikasi **tetap mendeteksi dan belajar** seperti chat (kotak Catat cepat). Koreksi anggota mengajari kamus ruang itu; urutan cocok: kata user, kamus ruang, kamus kategori. Kamus tidak pernah dipakai lintas ruang | Pencatatan cepat tanpa chat; karyawan baru langsung terbantu | Sedang | Kajian no. 17; ruang usaha 4 |
| ADR-P6 | **Pikir-Pikir masuk inti ruang keluarga**, bukan Fitur Tambahan; perintah dan tombolnya di chat tetap jalan | ADR-P2 melarang transaksi plugin lewat chat | Sedang | Kajian no. 4; ruang usaha 6 |
| ADR-P7 | **Buku Usaha adalah plugin pertama**, tanpa modul pilot ringan. Urutan: Beranda registry dan ruang usaha (dua jalur), lalu host plugin, lalu Buku Usaha, lalu beta; gerbang host diuji pada kerangka Buku Usaha (U1) | Desain Buku Usaha sudah lengkap; plugin pertama butuh ruang usaha dan registry kartu sekaligus | Sedang: urutan sesi | Ruang usaha 7 |
| ADR-P8 | Tata letak Beranda memakai model **urutan + ukuran** (S, M, L, XL), satu dokumen per user per ruang per permukaan | Satu daftar untuk semua lebar layar; aksesibel dengan Naik/Turun; bisa ditingkatkan ke grid bebas nanti | Tinggi setelah tabel `dashboard_layouts` berisi data | Kajian no. 1 |
| ADR-P9 | Selama 12 bulan hanya **plugin tingkat T1**: plugin buatan Jatahku sendiri yang ikut rilis, tanpa kode mitra | Disiplin manifest dan izin dulu; sandbox mitra (T2) belakangan | Sedang | Kajian no. 3 |
| ADR-P10 | Istilah: **"Fitur Tambahan"** di UI, "plugin" di kode dan dokumen | Bahasa user | Rendah | Kajian no. 5 |
| ADR-P11 | **Pemilik dan admin ruang** yang memasang, menjeda, dan mencopot plugin. Plugin bercakupan pribadi yang dipasang anggota untuk dirinya diputuskan saat ada plugin pertamanya | Plugin menyentuh data seluruh ruang | Rendah | Kajian no. 6 |
| ADR-P12 | Paket Usaha dijual sebagai **langganan per ruang**, hipotesis Rp25.000–Rp50.000 per bulan; tingkat menurut jumlah anggota dinilai dari data beta | Harga mengikuti ruang, bukan orang; data beta menentukan tingkat | Sedang: halaman harga dan hak | Kajian no. 8; ruang usaha 6.4 |
| ADR-P13 | **Kuota Basic tidak berlaku di ruang usaha**; ruang usaha butuh Paket Usaha, dengan uji coba gratis selama beta | Ruang usaha adalah produk berbayar; kuota dihitung per ruang | Sedang | Kajian no. 10 |
| ADR-P14 | Plugin **dilarang memakai LLM pihak ketiga** di T1 | Konsisten dengan keputusan AI Advisor: hanya aturan, demi privasi keuangan | Rendah | Kajian no. 12 |
| ADR-P15 | Data plugin yang dicopot **diarsipkan 90 hari** lalu dihapus permanen, dengan pemberitahuan 7 hari sebelumnya; layar copot selalu menawarkan ekspor | Cukup waktu untuk berubah pikiran; tidak menyimpan data tanpa batas | Rendah | Kajian no. 13 |
| ADR-P16 | Saat ruang usaha aktif, **tombol chat disembunyikan untuk karyawan**; pemilik dan admin tetap melihatnya dengan label "Ruang keluarga" | Chat selalu ruang keluarga (ADR-P2); karyawan tidak boleh mengira chat mencatat ke ruang usaha | Rendah | Ruang usaha 6.1 |
| ADR-P17 | **Jam akses ruang usaha** adalah pilihan per karyawan, bawaan mati | Tidak semua usaha butuh; jangan memblokir secara bawaan | Rendah | Ruang usaha 6.2 |
| ADR-P18 | **Antrean persetujuan** di atas batas nominal adalah bagian inti ruang usaha, bukan Fitur Tambahan. Draf disimpan terpisah dan baru menjadi transaksi saat disetujui, lewat jalur pencatatan yang sama | Batas nominal tidak berarti tanpa persetujuan; saldo tidak berubah sebelum disetujui | Sedang | Ruang usaha 6.3 |
| ADR-P19 | **Notifikasi operasional** untuk karyawan (mis. stok menipis) boleh bila admin mengizinkan, tanpa angka keuangan | ADR-P3 tetap berlaku untuk angka keuangan | Rendah | Ruang usaha 6.5 |

## Belum diputuskan

Tidak menghalangi rencana di `03-workflow.md`.

| Kajian no. | Keputusan | Rekomendasi kajian | Dibutuhkan sebelum |
| --- | --- | --- | --- |
| 7 | Beranda bawaan dari pemilik household | Ya | Mode Atur (P2 kajian) |
| 9 | Payment gateway untuk tagihan berulang | Penyedia dengan QRIS, virtual account, dan tagihan berulang | Rilis berbayar setelah beta |
| 11 | Harga plugin di toko aplikasi | Diputuskan bersama harga Pro di toko | Jualan di toko aplikasi |
