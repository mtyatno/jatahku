# AI Advisor v2 — catatan serah-terima

Entri terbaru di atas. Format: **Sesi · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

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
