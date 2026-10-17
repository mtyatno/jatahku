# AI Advisor — kontrak API (v1, 16 Okt 2026)

Bentuk respons yang disepakati supaya frontend (S6–S8) bisa dikerjakan paralel dengan backend (S3–S5). Mengubah bentuk = PR yang menyentuh file ini dan memberi tahu pemilik sesi frontend.

```jsonc
// GET /advisor/dashboard
{
  "enabled": true,                       // flag advisor_v2_users untuk user ini
  "generated_at": "2026-10-15T06:05:00+07:00",
  "metrics": { "dana_belanja": 11285200, "terpakai": 8000000, "tagihan_sisa": 1600000,
               "sisa_bebas": 1685200, "j0": 165100, "j1": 153200, "laju7": 201014,
               "belanja_hari_ini": 297100, "proyeksi_akhir": 11811157, "kekurangan": 525957,
               "tanggal_habis": "2026-10-24", "hari_ke": 19, "hari_total": 30, "sisa_hari": 11,
               "pemasukan_saya": 0, "pemasukan_rumah_tangga": 7500000,
               "harian": [{"tanggal": "2026-09-27", "variabel": 0, "tagihan": 0, "penyesuaian": 0,
                           "outlier": 0, "jatah": 376100, "lewat": false}] },
  // metrics = Metrics.to_api() dari app/services/advisor/metrics.py (S1). harian: satu baris per hari ps..hari ini,
  // hanya amplop belanja; "jatah" = J0 hari itu, "lewat" = variabel > jatah (S6). outlier & jatah ditambah di S1.
  // Angka null bila belum bisa dihitung: j1 di hari terakhir; proyeksi_akhir/kekurangan/tanggal_habis bila hari_ke < 3.
  "kpi": { "jatah": {/* insight */}, "sisa_bebas": {}, "terpakai": {}, "income": {}, "tagihan": {}, "tabungan": {} },
  // kpi.<kartu> = insight terpilih untuk kartu itu (chip sudah sesuai kartu: PER-01 di Terpakai = "Lewat ±Rp525 rb",
  // di Sisa bebas = "Habis ±24 Okt"), atau null. Sejak S4 keenam kartu terisi (income: INC-*, cadangan INC-05;
  // tagihan: TAG-01/02/04, DAT-06, TAG-03, cadangan TAG-09; tabungan: TAB-*, cadangan TAB-07 — null hanya bila
  // household tanpa amplop tabungan). Bisa juga null bila satu-satunya insight kartu itu sedang di-dismiss.
  "grafik": { "teks": "4 dari 7 hari terakhir lewat jatah, tertinggi Senin 12 Okt Rp400 rb", "aksi": {/* CTA route */} | null },
  "advisor": { "items": [/* insight, maks 3 */], "sisa": [{"id": "TAB-01:…", "judul_pendek": "Dana Darurat baru 3%"}], "total": 4,
               "aman": null,  // aman = satu insight ok terbaik bila items kosong ("Semua aman"), selain itu null
               "disembunyikan": [{"kunci": "HAR-01:2026-10-17", "judul_pendek": "…", "pilihan": "nanti"}] },
  // disembunyikan (#91) = insight yang sedang menyala tapi di-dismiss viewer (daftar maupun chip KPI), urut tone/skor.
  // Kartu AI Advisor menampilkannya sebagai "N disembunyikan · Tampilkan" + Munculkan lagi. [] bila tidak ada.
  "redam_chip": true
}
// User di luar flag advisor_v2_users → { "enabled": false } saja (tanpa field lain).
// Cache server 90 detik per (household, viewer); dihapus otomatis setiap commit yang mengubah data household.

// insight
{ "id": "TAG-01:<recurring_id>", "aturan": "TAG-01", "tone": "danger", "chip": "KPR telat 9 hari",
  "judul": "Lunasi KPR Rumah — telat 9 hari", "isi": "…", "fakta": [{"label": "…", "nilai": "…"}],
  "aksi": [{"kind": "plan", "label": "Geser & bayar KPR", "payload": {"kebutuhan": [{"tujuan_id": "…", "jumlah": 2008174, "bayar_recurring_id": "…"}]}},
           {"kind": "pay", "label": "Bayar saja", "payload": {"recurring_id": "…"}}],
  "dasar": {"teks": "Dari 19 hari data", "keyakinan": "tinggi"},
  "dismiss": {"kunci": "TAG-01:<id>", "pilihan": ["nanti", "periode", "tidak_relevan"]},
  "skor": 100.0,                                            // §5, untuk debug/urutan; frontend tidak menghitung
  "rincian": [{"id": "HAR-01:2026-10-15", "aturan": "HAR-01", "judul": "…", "isi": "…"}] }  // opsional: insight yang
  // diserap (penekanan 2/3/6), mis. HAR-01 & AMP-02/03 di Rincian PER-01. aksi[].payload sudah lengkap (chat: {teks}).

// kind yang dikenal S8: plan | fund | pay | mark_paid | income | daily_limit | raise_budget | make_recurring
//                      | route | chat | dismiss | undismiss | delete_txn | not_duplicate   (undismiss: #91, hanya frontend)

// POST /advisor/plan  { "kebutuhan": [{"tujuan_id","jumlah","bayar_recurring_id"?}],   (1–10 item)
//                      "kecuali": ["<dari_id>"]?,      // sumber yang dilepas user → dihitung ulang tanpa itu
//                      "sertakan": ["<amplop_id>"]? }  // tabungan (d) / dana darurat (e) yang DIPILIH user
//   → { "rencana": [{"dari_id","dari_nama","jumlah","alasan","tingkat":"a|b|c|d|e","tercentang":true,
//                    "ke": [{"tujuan_id","tujuan_nama","jumlah"}]}],   // satu baris per sumber (dari_id unik)
//       "kurang": 0,                       // Σ kebutuhan − Σ baris tercentang
//       "bayar": [{"recurring_id","jumlah"}],  // hanya bila kebutuhannya tertutup penuh oleh baris tercentang
//       "saldo_versi": "<hash>",
//       "kebutuhan": [...], "kecuali": [...], "sertakan": [...],   // gaung permintaan (dinormalisasi, urut prioritas)
//       "opsi_tabungan": [{"amplop_id","nama","saldo","darurat"}] }  // CTA "Pakai tabungan" bila kurang > 0
//   400 {"detail"} bila tujuan tak terlihat / jumlah ≤ 0 / langganan bukan di amplop tujuan.
//   Tingkat c ("Cek dulu") tercentang hanya untuk kebutuhan danger; d/e tidak pernah otomatis (§8).
// POST /advisor/execute { "rencana": [...baris tercentang, dengan "ke"], "bayar": [...], "saldo_versi": "<hash>",
//                         "client_ref": "<uuid>", "kebutuhan"?, "kecuali"?, "sertakan"? }   // 3 terakhir: untuk rencana_baru
//   → 200 {"status":"ok","transfer":[{"dari_id","dari_nama","ke_id","ke_nama","jumlah","income_id"}],
//          "dibayar":[{"recurring_id","deskripsi","jumlah","txn_id","next_run"}]}
//   | 409 {"detail":"Saldo berubah","rencana_baru":{…bentuk /plan…}}   // saldo_versi beda; tidak ada yang ditulis
//   | 409 {"detail":"Rencana ini sedang diproses"}  (client_ref yang sama sedang berjalan) | 409 {"detail":"<jendela bayar>"}
//   | 400 {"detail"} bila baris tidak sah (sumber terkunci/tak terlihat/melebihi sisa, sumber = tujuan, kosong).
//   client_ref sama dikirim ulang sesudah sukses → hasil pertama dikembalikan, tidak ada transfer baru.
// POST /recurring/{id}/mark-paid  (S4, DAT-06 "Tandai lunas") → 200 {"prev_next_run","next_run"}
//   next_run maju satu frekuensi, TANPA transaksi baru. 404 langganan tak terlihat; 409 {"detail"} bila jatuh
//   tempo di periode depan (jendela bayar sama dengan /pay dan /skip).
// POST /advisor/dismiss { "kunci": "…", "pilihan": "nanti|periode|tidak_relevan" } → 204
//   nanti = sampai besok 05.00 waktu user · periode = sampai akhir periode · tidak_relevan = 90 hari.
//   Muncul lagi lebih awal bila tone naik atau rupiah terdampak naik ≥ 50% (§9). Dismiss juga berlaku untuk chip KPI.
// DELETE /advisor/dismiss?kunci=…  (#91, Urungkan / Munculkan lagi) → 204
//   Menghapus dismiss milik viewer sendiri untuk kunci itu + cache dashboard viewer; insight tampil lagi di muatan
//   berikutnya. Idempoten: 204 juga bila kunci tidak sedang disembunyikan. Dismiss viewer lain tidak tersentuh.
```

## Aksi CTA di frontend (S8)

Aksi dijalankan lewat `window.dispatchEvent(new CustomEvent('jatahku:open-action', { detail: aksi }))` (helper `openAction()` di `frontend/src/lib/advisorAction.js`). `detail` boleh string lama (`expense`, `envelope`, `income`, `langganan`, `balance`, `chat`) atau objek `{kind, label?, payload}` dari `insight.aksi[]`. `Layout.jsx` adalah satu-satunya penerima.

| kind | payload | Yang terjadi |
|---|---|---|
| `plan` | `{kebutuhan: [{tujuan_id, jumlah, bayar_recurring_id?}]}` | `PlanSheet`: `POST /advisor/plan` → lembar konfirmasi → `POST /advisor/execute` (`client_ref` baru per rencana). Melepas centang sumber → plan diminta ulang dengan `kecuali`. 409 → `rencana_baru` ditampilkan. "Masih kurang" → Catat pemasukan |
| `fund` | `{amplop_id, jumlah?}` | `FundEnvelopeModal` mode advisor: tab Geser = rencana multi-sumber (plan/execute), tab Top-up = pemasukan langsung ke amplop |
| `pay` | `{recurring_id}` | Modal Langganan, `PaySubscriptions` fokus satu langganan (Bayar/Lewati) |
| `mark_paid` | `{recurring_id}` | Sama, tombol **Tandai lunas** → `POST /recurring/{id}/mark-paid` (S4) |
| `income` | `{jumlah?, sumber?, amplop_id?}` | `QuickAddIncome` terisi; `amplop_id` → 100% ke amplop itu. Simpan → `jatahku:txn-added` |
| `daily_limit` | `{amplop_id, jumlah}` | Konfirmasi lalu `PUT /envelopes/{id}` `daily_limit` |
| `raise_budget` | `{amplop_id, jumlah}` | Konfirmasi lalu `PUT /envelopes/{id}` `budget_amount` (berlaku untuk alokasi berikutnya) |
| `make_recurring` | `{deskripsi, jumlah, frekuensi?, amplop_id?, next_run?}` | Modal Langganan tab Tambah, `RecurringModal` terisi |
| `route` | `{path}` | Navigasi SPA; hanya path relatif di daftar halaman app (`safeRoute`). Halaman reaktif: `/transactions?date=YYYY-MM-DD&envelope=<id>`, `/allocate?new=1&amount=&source=` |
| `chat` | `{teks?, chip?: [string \| {label, text}], kirim?}` | Chat terbuka, teks diisikan (atau dikirim bila `kirim`), chip tampil paling depan |
| `dismiss` | `{kunci, pilihan?}` | `POST /advisor/dismiss` (default `nanti`) → event `jatahku:advisor-dismissed` `{kunci, pilihan}` → toast "Disembunyikan sampai …" dengan tombol **Urungkan** (= `undismiss`, #91) |
| `not_duplicate` | `{kunci}` | Sama dengan `dismiss`, pilihan `tidak_relevan`; toast "Ditandai bukan dobel" + **Urungkan** |
| `undismiss` | `{kunci}` | `DELETE /advisor/dismiss?kunci=` → event `jatahku:advisor-undismissed` `{kunci}` (Beranda memuat ulang) → toast "Ditampilkan lagi". Dipakai tombol Urungkan dan **Munculkan lagi** di kartu (#91) |
| `delete_txn` | `{txn_id, txn_ids?, konfirmasi?}` | `confirm()` lalu `DELETE /transactions/{id}` untuk tiap id (`txn_ids` bila ada: struk terkirim dua kali, DAT-03 S4b) → `jatahku:txn-added` |

Setelah data berubah, penerima menembakkan `jatahku:txn-added` (dan `jatahku:envelope-updated` untuk transfer/amplop) supaya Beranda dan halaman lain memuat ulang (dan cache advisor server dihapus oleh route terkait, S3).

