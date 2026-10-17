# AI Advisor — alur kerja development & rencana sesi (Okt 2026)

**Status:** usulan 16 Okt 2026 malam. Spesifikasi (`02-aturan.md` revisi 1) dan desain (`01-desain.md`) sudah disetujui pemilik produk. Development dibuka begitu S0 selesai.

**Keputusan tambahan (16 Okt 2026):**
- Dana darurat ditandai lewat field baru `envelopes.is_emergency` (backfill dari nama "darurat"/"emergency").
- `transfer_between_envelopes` ikut memakai kunci baris household di **Fase 1** (sesi S5), bersama `POST /advisor/execute`.

**Papan progres:** artifact "Papan AI Advisor" di claude.ai (tautan ada di project claude.ai "jatahku"; privat untuk organisasi) (status tiap sesi, pemilik, PR, catatan serah-terima). Hanya bisa dibuka anggota organisasi claude.ai pemilik; kalau ada anggota tim di luar organisasi, pakai GitHub Project dengan kolom yang sama.

---

## 1. Cara kerja: repo adalah memori

Setiap sesi Claude Code mulai dari nol, dan laptop bisa berpindah tangan atau jeda berhari-hari. Karena itu **semua yang perlu diketahui sesi berikutnya harus ada di repo**, bukan di ingatan orang atau di chat.

- `docs/ai-advisor/00-indeks.md` — peta dokumen dan status fase (satu paragraf, selalu mutakhir).
- `docs/ai-advisor/01-desain.md`, `02-aturan.md` — salinan dokumen project ini. Kalau spesifikasi berubah, ubah di repo lewat PR, lalu sinkronkan ke project claude.ai.
- `docs/ai-advisor/03-workflow.md` — dokumen ini.
- `docs/ai-advisor/04-kontrak-api.md` — bentuk respons `GET /advisor/dashboard`, `POST /advisor/plan`, `POST /advisor/execute`, `POST /advisor/dismiss` (§10), supaya frontend dan backend bisa dikerjakan paralel.
- `docs/ai-advisor/PROGRESS.md` — tabel sesi: status, pemilik, PR, tanggal. Diubah **di PR sesi itu sendiri**, jadi status tidak pernah lepas dari kodenya.
- `docs/ai-advisor/SESI-LOG.md` — catatan serah-terima per sesi: apa yang selesai, apa yang digantung, jebakan yang ditemui, keputusan kecil. Sesi berikutnya membaca entri terakhir sebelum mulai.
- `AGENTS.md` — bagian baru "AI Advisor v2" berisi 6 aturan kerja (lihat §6) supaya Claude Code di sesi mana pun tidak menambah rumus "aman per hari" ketiga belas.

## 2. Satu sesi = satu PR

- **Sesi** = satu duduk Claude Code, 2–4 jam, dengan hasil yang bisa di-merge sendiri. Daftar sesi di §7; tiap sesi punya issue GitHub bernomor sama.
- **Branch** `ai-advisor/sN-slug`, dari `main` terbaru. **PR** berjudul `AI Advisor SN: <nama sesi>`, squash merge.
- **Jeda di tengah sesi aman:** push branch, buka PR sebagai draft dengan judul berawalan `WIP`, tulis "Status jeda" di deskripsi PR (apa yang jalan, apa yang belum, perintah tes terakhir). Siapa pun bisa melanjutkan dari situ, termasuk Claude Code sesi lain.
- **Tidak ada pekerjaan tanpa issue.** Temuan di luar scope sesi dicatat sebagai issue baru berlabel `ai-advisor`, bukan dikerjakan diam-diam.

## 3. Ritual pembuka & penutup (prompt untuk Claude Code)

**Pembuka** — tempel ini di awal sesi, ganti `SN`:

```
Kerjakan sesi SN AI Advisor Jatahku.
1. git fetch && git checkout -b ai-advisor/sN-<slug> origin/main
2. Baca docs/ai-advisor/00-indeks.md, 03-workflow.md (§2, §5, §6), entri terakhir SESI-LOG.md, lalu issue GitHub sesi ini. Baca bagian 02-aturan.md yang disebut issue.
3. Rangkum dalam 5 baris: scope sesi, file yang boleh disentuh, tes yang harus hijau, dan risiko. Tunggu "lanjut" dariku sebelum mengubah kode.
4. Setiap kali selesai satu bagian, jalankan tesnya. Jangan menyentuh file di luar daftar kepemilikan sesi ini tanpa bertanya.
```

**Penutup** — tempel ini sebelum berhenti, walau sesi belum selesai:

```
Tutup sesi SN.
1. Jalankan: python -m unittest discover -s app/tests -t . ; cd frontend && node --test src/lib/*.test.js && npm run build
2. Perbarui docs/ai-advisor/PROGRESS.md (status, PR, tanggal) dan tambah entri di SESI-LOG.md: selesai apa, digantung apa, jebakan, keputusan kecil, perintah untuk melanjutkan.
3. Commit, push, buka PR (draft + "WIP" kalau belum selesai) dengan template di 03-workflow.md §4. Sertakan ringkasan untuk reviewer dan cara mencobanya.
4. Beri tahu aku status papan: belum / berjalan / jeda / review / selesai.
```

## 4. Template PR

```
## Sesi SN — <nama>
Issue: #…  ·  Spesifikasi: 02-aturan.md §…
### Yang berubah
- …
### Cara mencoba
- …
### Tes
- unittest: … hijau · node --test: … hijau · build: ok
### Catatan untuk reviewer
- Risiko / keputusan kecil / yang sengaja ditunda
### Checklist
- [ ] Tidak ada rumus angka baru di luar metrics.py / tidak ada teks insight di luar render.py
- [ ] Angka web, chat, Telegram masih identik (tes paritas) — wajib untuk S3, S4, S9
- [ ] PROGRESS.md & SESI-LOG.md diperbarui
- [ ] Migrasi? → langkah manual ditulis di deskripsi dan diberi label `migrasi`
```

## 5. Rilis, flag, migrasi, review

- **Deploy otomatis** saat merge ke `main` (antrean, lihat `CLAUDE.md`). Verifikasi `api.jatahku.com/health` → commit, `jatahku.com/version.json` → commit web.
- **Flag `advisor_v2_users`** (AppSetting, diatur dari Admin): daftar `user_id` dipisah koma, atau `*`. Semua UI baru Fase 1 hanya tampil untuk user di daftar; UI lama tetap jalan untuk yang lain. Dinyalakan `*` di S10 setelah tim mencoba di produksi dengan akun sendiri. Backend baru (endpoint `/advisor/*`) boleh live kapan saja karena tidak mengubah layar lama.
- **Migrasi** (S1: `is_emergency`): CI tidak menjalankan alembic. Ikuti checklist di `AGENTS.md` (cek ownership tabel, `alembic current`, `alembic upgrade head`, restart service). Sesi bermigrasi diberi label `migrasi` di issue dan papan; merge hanya oleh orang yang bisa menjalankannya di VPS pada jam yang sama.
- **Review:** PR direview orang yang tidak menulisnya. Kalau sendirian, buka sesi Claude Code baru hanya untuk review (`/review` atau "review PR #N terhadap 02-aturan.md §…") supaya pekerjaan tidak menilai dirinya sendiri.
- **CI tes (S0):** workflow `test.yml` menjalankan unittest + `node --test` + build frontend pada setiap PR. Hari ini CI hanya deploy.

## 6. Enam aturan kerja untuk `AGENTS.md`

1. **Satu sumber angka.** Semua angka periode (dana belanja, terpakai, sisa bebas, J0, J1, laju, proyeksi) hanya dihitung di `app/services/advisor/metrics.py`. Dilarang menulis rumus pembagi hari di route, bot, scheduler, atau frontend.
2. **Teks insight hanya di `render.py`.** Aturan mengembalikan data; kalimat dirakit dari template, sama untuk web, chat web, Telegram.
3. **Aturan adalah fungsi murni** `(metrik, sinyal) → insight[]`, tanpa DB, diuji dengan fixture. Loader DB hanya di `snapshot.py`.
4. **Frontend tidak menghitung ulang.** KPI, chip, grafik, dan kartu membaca `GET /advisor/dashboard`. Frontend hanya memformat (`rpCompact`, `rpFull`).
5. **CTA pemindah dana lewat `/advisor/plan` → `/advisor/execute`**, dengan `client_ref`. Tidak ada transfer dari frontend tanpa rencana.
6. **Privasi household** tetap lewat `visibility.py`; perencana tidak pernah memakai amplop pribadi anggota lain; cache dihapus per household.

## 7. Daftar sesi

Estimasi dalam jam Claude Code aktif. "Paralel" = boleh dikerjakan bersamaan oleh orang lain setelah dependensinya selesai.

### Fase 0 — Persiapan
| Sesi | Nama | Jam | Dependensi | Hasil & file |
|---|---|---|---|---|
| **S0** | Bootstrap repo, CI tes, issue, papan | 1,5 | — | `docs/ai-advisor/*` (salin 01–04, PROGRESS, SESI-LOG), bagian "AI Advisor v2" di `AGENTS.md`, `.github/workflows/test.yml`, label `ai-advisor` + `migrasi`, milestone Fase 1–4, 1 issue per sesi, papan progres terisi |

### Fase 1 — Fondasi + Beranda (UI di balik flag sampai S10)
| Sesi | Nama | Jam | Dependensi | Hasil & file |
|---|---|---|---|---|
| **S1** ⚠ migrasi | Snapshot & metrik | 3 | S0 | `advisor/snapshot.py` (loader berkelompok, perluasan `load_advisor_context`), `advisor/metrics.py` (M1–M13, T1–T11, P1–P6, G1–G8, K1–K4), fixture + unit test; migrasi `is_emergency` + backfill, field di API amplop. Belum ada perubahan UI |
| **S2** | Sinyal | 2,5 | S1 | `advisor/signals.py` S1–S19 memakai `projection.py` (outlier), `sinking.detect_interval` (rutin), aturan nominal persis `reserved.py` (M4/M13); tes struk-rantai, dobel vs kembar, S4b, lonjakan, menganggur, pemasukan terlambat |
| **S3** | Insight inti: Hari ini & Periode, seleksi, render, endpoint | 3,5 | S1, S2 | skema insight, `select.py` (skor, tone dulu, penekanan 1–8), `render.py`, aturan HAR-* & PER-*, `GET /advisor/dashboard` (metrics + chip Jatah/Sisa/Terpakai + daftar), flag `advisor_v2_users`, cache Redis per household + `advisor_cache.invalidate(hid)` dipanggil dari route transaksi/pemasukan/transfer/langganan/cocokkan saldo dan bot. Tes skenario 1, 2, 3, 6, 11, 13, 16, 17 |
| **S4** | Aturan Amplop, Tagihan, Pemasukan, Tabungan, Data | 3,5 | S3 | AMP-01..11, TAG-01..09, INC-01..06, TAB-01..07, DAT-01..06; chip Income/Tagihan/Tabungan; `POST /recurring/{id}/mark-paid` (Tandai lunas). Tes 4, 5, 14, 15, 19 |
| **S5** | Perencana dana & eksekusi | 3 | S1 (paralel dgn S3/S4) | `advisor/planner.py`, `POST /advisor/plan`, `POST /advisor/execute` (kunci household, `client_ref`, transfer + bayar atomik), kunci household di `transfer_between_envelopes`, `bebas_setelah_rencana`. Tes 10, 18 + integrasi SQLite (pola `test_fund_shift_integration.py`) |
| **S6** | Frontend Beranda A: KPI & grafik | 3 | S3 (lengkap setelah S4) | `api.getAdvisorDashboard`, chip AI + popover/bottom sheet + peredaman + cap waktu, `KpiTile` membaca metrik endpoint, `DailySpendingChart` dari deret metrik + baris analisa, hapus `advisorToday.js`. Di balik flag |
| **S7** | Frontend Beranda B: kartu AI Advisor | 2,5 | S4, S6 | daftar 3 item, Rincian, Nanti/Sembunyikan/Tidak relevan (`POST /advisor/dismiss`), "+N saran lain", kotak Tanya dengan chip cepat → ChatPanel |
| **S8** | Pipa CTA (frontend) | 3 | S0 (kontrak API) — **paralel sejak hari pertama** | `jatahku:open-action` menerima objek `{kind, payload}` (string lama tetap jalan), `FundEnvelopeModal` via event + multi-sumber, `PaySubscriptions` fokus satu langganan, `QuickAddIncome` prefill + `txn-added`, `ChatPanel` teks awal + chip, `RecurringModal` mode buat + prefill, `/transactions?date=&envelope=` reaktif, `/allocate?new=1` + prefill, lembar konfirmasi rencana (`/advisor/plan|execute`) |
| **S9** | Paritas bot & ringkasan | 3 | S3, S4 | `nlp_cmd` (sisa, limit harian, kapan habis, pengeluaran hari ini), `handlers.cmd_status`, `checkin_cmd` (periode gajian), `summary.py` harian/mingguan → `metrics` + `render`; intent "kenapa boros", "kenapa {amplop} habis", "aman beli" (SIM-01 via `find_best_envelope`); crash hari terakhir hilang; tes paritas |
| **S10** | Verifikasi & rilis Fase 1 | 2 | S1–S9 | uji di produksi dengan akun tim (flag), bandingkan Beranda vs chat vs Telegram, perbaikan kecil, flag `*`, `AGENTS.md` bagian Advisor diperbarui, arsipkan `docs/ai-advisor-review-2026-06-30.md` |

### Fase 2 — Amplop & Langganan
| Sesi | Nama | Jam | Dependensi | Hasil & file |
|---|---|---|---|---|
| **S11** | Halaman Amplop | 3 | S4, S5, S8 | `GET /advisor/page/amplop`; strip AI per kartu menggantikan `envelopeInsight.js`; CTA Naikkan jatah, Geser dana, Pasang limit, Setor, Atur target; toggle `is_emergency` di form amplop |
| **S12** | Halaman Langganan | 2,5 | S4, S5, S8 | `GET /advisor/page/langganan`; ringkasan beban tagihan; TAG-* per baris; Tandai lunas; Geser & bayar dari baris; Jadikan langganan dari pola |

### Fase 3 — Transaksi, Alokasi, Analitik
| Sesi | Nama | Jam | Dependensi | Hasil & file |
|---|---|---|---|---|
| **S13** | Halaman Transaksi | 3 | S4, S8 | banner kontekstual; penanda baris HAR-03, DAT-03/S4b, TAG-07, DAT-06; aksi Hapus salah satu / Bukan dobel / Jadikan langganan / Tandai lunas |
| **S14** | Halaman Alokasi | 3 | S4, S8 | rekomendasi dengan alasan per amplop + keyakinan; `?new=1` form terbuka + terisi; INC-03/04 di atas form; "Bagi otomatis" di `QuickAddIncome` memakai rekomendasi yang sama; hapus pencocokan nama "Tabungan" (`Layout.jsx`, `Allocate.jsx`) |
| **S15** | Halaman Analitik | 2,5 | S4 | ringkasan AI 3 poin menggantikan `analyticsInsight.js`; `/analytics/daily-spending` filter pemilik + deret metrik; Sinking fund advisor dengan CTA dari `actions[]` |

### Fase 4 — Proaktif, chat, copy
| Sesi | Nama | Jam | Dependensi | Hasil & file |
|---|---|---|---|---|
| **S16** | Notifikasi proaktif | 3 | S9 | ringkasan harian/mingguan dari insight; pengingat tagihan patuh preferensi dan tidak berulang; jam tenang; 1/hari; lonceng web + Telegram + chat web; `send_budget_warning` dari insight danger; **cek #91**: notifikasi menghormati dismiss terbaru (termasuk yang di-Urungkan) dan tidak membuat jalur dismiss sendiri |
| **S17** | Chat lengkap | 2 | S9 | semua intent §6H, chip cepat per halaman, `help_cmd.py`, daftar `BotCommand`, "aman beli" dengan pilihan ganti amplop; **cek #91**: bila chat menawarkan sembunyikan/munculkan lagi, pakai `POST`/`DELETE /advisor/dismiss` yang sama |
| **S18** | Copy, landing, blog, dokumen | 2 | S10 | `landing.html` (±10 tempat), 6 artikel blog + 1 artikel baru, `README.md`, `og-image.svg`, hapus kode basi |
| **S19** | Pikir-Pikir masuk AI Advisor | 2 | Pikir-Pikir Fase 2/3 | PP-01..03 — menunggu |

**Total:** Fase 1 ≈ 30,5 jam (11 sesi) · Fase 2 ≈ 5,5 jam · Fase 3 ≈ 8,5 jam · Fase 4 ≈ 7 jam (+ S19). Keseluruhan ≈ 52 jam, 19 sesi + S19.

### Kepemilikan file (mencegah konflik saat paralel)
| Area | Sesi pemilik | Catatan |
|---|---|---|
| `app/services/advisor/{snapshot,metrics}.py` | S1 | S2–S5 hanya menambah fungsi, tidak mengubah rumus |
| `app/services/advisor/signals.py` | S2 | |
| `app/services/advisor/{select,render}.py`, `rules/hari.py`, `rules/periode.py`, `app/api/routes/advisor.py` | S3 | S4 menambah file `rules/*` baru + route kecil |
| `rules/{amplop,tagihan,pemasukan,tabungan,data}.py`, `routes/recurring.py` (mark-paid) | S4 | |
| `advisor/planner.py`, `routes/advisor.py` (plan/execute), `routes/envelopes.py` (kunci transfer) | S5 | |
| `frontend/src/pages/Dashboard.jsx`, `components/KpiCard.jsx`, `DailySpendingChart.jsx`, `lib/api.js` (getAdvisorDashboard) | S6 | |
| `components/AttentionCard.jsx` → `AdvisorCard.jsx`, `lib/dashboardInsights.js` | S7 | |
| `components/Layout.jsx`, `FundEnvelopeModal.jsx`, `PaySubscriptions.jsx`, `ChatPanel.jsx`, `pages/Langganan.jsx` (RecurringModal), `pages/Transactions.jsx` (query), `pages/Allocate.jsx` (`?new=1`), `components/PlanSheet.jsx` (baru) | S8 | S6/S7 memanggil lewat event, tidak mengubah file ini |
| `app/bot/*`, `app/services/summary.py` | S9 | |
| `app/services/advisor/halaman.py` (bagian Amplop), `routes/advisor.py` (`/page/amplop`), `pages/Envelopes.jsx`, `lib/envelopeStrip.js` | S11 | S12–S15 menambah fungsi halaman sendiri di `halaman.py` |

## 8. Jadwal usulan

Asumsi: 1 sesi per orang per hari kerja, mulai **Senin 19 Okt 2026**. Tanggal boleh bergeser; papan progres yang jadi acuan nyata.

**Jalur A — dua orang (Y = pemilik produk, T = anggota tim):**

| Hari | Y | T |
|---|---|---|
| Sen 19 Okt | S0 pagi, S1 | S8 (pipa CTA, mulai dari kontrak API) |
| Sel 20 Okt | S2 | S8 selesai → S5 mulai |
| Rab 21 Okt | S3 | S5 selesai |
| Kam 22 Okt | S4 | S6 |
| Jum 23 Okt | S9 | S7 |
| Sen 26 Okt | **S10 bersama → Fase 1 live** | |
| Sel 27 Okt | S11 | S12 |
| Rab 28 Okt | S14 | S13 |
| Kam 29 Okt | S16 | S15 |
| Jum 30 Okt | S17 | S18 |

Fase 2–4 selesai sekitar **30 Okt 2026**; tambah seminggu cadangan → target aman **6 Nov 2026**. S19 menunggu Pikir-Pikir.

**Jalur B — sendirian, 1 sesi per hari kerja:** S0–S10 selesai ±4 Nov (Fase 1 live), S11–S18 ±18 Nov. Dengan 1 sesi per 2 hari: Fase 1 ±20 Nov, selesai ±18 Des.

**Urutan yang tidak boleh ditukar:** S1 → S2 → S3 → S4; S3 → S6 → S7; S3 + S4 → S9; semua → S10. Yang bebas: S8 kapan saja; S5 setelah S1; S11–S18 setelah S10 dalam urutan apa pun.

## 9. Pelacakan progres

- **Papan progres (artifact)** — tampilan untuk manusia: status per sesi (belum / berjalan / jeda / review / selesai), pemilik, tautan PR, catatan serah-terima, jam selesai vs total, dan jadwal usulan. Siapa pun di tim mengubah statusnya langsung di papan saat membuka/menutup sesi.
- **`PROGRESS.md` di repo** — sumber kebenaran untuk Claude Code, berubah lewat PR sesi. Kolomnya sama dengan papan supaya mudah dicocokkan: `Sesi | Status | Pemilik | PR | Mulai | Selesai`.
- **GitHub issue per sesi** — tempat diskusi scope dan temuan; ditutup oleh PR-nya.
- **Cek mingguan (Jumat):** pemilik produk membaca papan + `SESI-LOG.md`, memutuskan sesi minggu depan, dan menyinkronkan dokumen project claude.ai dengan `docs/ai-advisor/` bila ada perubahan spesifikasi.

## 10. Kontrak API

Dipindah ke `04-kontrak-api.md`.
