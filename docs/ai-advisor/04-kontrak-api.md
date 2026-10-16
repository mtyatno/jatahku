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
  "grafik": { "teks": "4 dari 7 hari terakhir lewat jatah…", "aksi": {/* CTA */} },
  "advisor": { "items": [/* insight, maks 3 */], "sisa": [{"id": "TAB-01:…", "judul_pendek": "Dana Darurat baru 3%"}], "total": 4 },
  "redam_chip": true
}

// insight
{ "id": "TAG-01:<recurring_id>", "aturan": "TAG-01", "tone": "danger", "chip": "KPR telat 9 hari",
  "judul": "Lunasi KPR Rumah — telat 9 hari", "isi": "…", "fakta": [{"label": "…", "nilai": "…"}],
  "aksi": [{"kind": "plan", "label": "Geser & bayar KPR", "payload": {"kebutuhan": [{"tujuan_id": "…", "jumlah": 2008174, "bayar_recurring_id": "…"}]}},
           {"kind": "pay", "label": "Bayar saja", "payload": {"recurring_id": "…"}}],
  "dasar": {"teks": "Dari 19 hari data", "keyakinan": "tinggi"},
  "dismiss": {"kunci": "TAG-01:<id>", "pilihan": ["nanti", "periode", "tidak_relevan"]} }

// kind yang dikenal S8: plan | fund | pay | mark_paid | income | daily_limit | raise_budget | make_recurring
//                      | route | chat | dismiss | delete_txn | not_duplicate

// POST /advisor/plan  { "kebutuhan": [...], "kecuali": ["<dari_id>"]? }  → { "rencana": [{"dari_id","dari_nama","jumlah","alasan","tingkat":"a|b|c","tercentang":true}],
//                                               "kurang": 0, "bayar": [{"recurring_id","jumlah"}], "saldo_versi": "<hash>" }
// POST /advisor/execute { "rencana": [...], "bayar": [...], "saldo_versi": "<hash>", "client_ref": "<uuid>" }
//                      → 200 {"status":"ok","transfer":[…],"dibayar":[…]} | 409 {"detail":"Saldo berubah","rencana_baru":{…}}
// POST /advisor/dismiss { "kunci": "…", "pilihan": "nanti|periode|tidak_relevan" } → 204
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
| `dismiss` | `{kunci, pilihan?}` | `POST /advisor/dismiss` (default `nanti`) → event `jatahku:advisor-dismissed` `{kunci, pilihan}` |
| `not_duplicate` | `{kunci}` | Sama dengan `dismiss`, pilihan `tidak_relevan` |
| `delete_txn` | `{txn_id, konfirmasi?}` | `confirm()` lalu `DELETE /transactions/{id}` → `jatahku:txn-added` |

Setelah data berubah, penerima menembakkan `jatahku:txn-added` (dan `jatahku:envelope-updated` untuk transfer/amplop) supaya Beranda dan halaman lain memuat ulang (dan cache advisor server dihapus oleh route terkait, S3).

