# AI Advisor v2 — indeks

Mesin aturan deterministik (tanpa LLM) yang memberi analisa + tombol aksi di setiap bagian Jatahku: chip AI di 6 KPI Beranda, kartu AI Advisor, halaman Amplop/Transaksi/Alokasi/Langganan/Analitik, chat web, dan Telegram — semuanya dari satu sumber angka (`app/services/advisor/metrics.py`).

**Fase sekarang:** Fase 1 — Fondasi + Beranda. S1 (snapshot & metrik), S2 (sinyal), S8 (pipa CTA) di review/selesai; S5 (perencana dana) di review; berikutnya S3 (insight inti). Status per sesi: `PROGRESS.md`.

## Dokumen
| File | Isi | Kapan dibaca |
|---|---|---|
| `01-desain.md` | Permukaan, keputusan pemilik produk, katalog CTA, arsitektur | Sesi frontend; saat ragu "harus tampil di mana" |
| `02-aturan.md` | Spesifikasi mesin: metrik (§3), sinyal (§4), skor & penekanan (§5), 56 aturan (§6), seleksi per slot (§7), perencana dana (§8), konstanta (§11), contoh angka (§12), skenario uji (§13) | Setiap sesi backend — baca bagian yang disebut issue |
| `03-workflow.md` | Cara kerja tim: satu sesi = satu PR, ritual pembuka/penutup, template PR, flag, migrasi, daftar sesi & kepemilikan file, jadwal | Awal setiap sesi (§2, §5, §6) |
| `04-kontrak-api.md` | Bentuk JSON `/advisor/dashboard`, `/plan`, `/execute`, `/dismiss`, dan `kind` aksi | Sesi yang menyentuh endpoint atau frontend |
| `PROGRESS.md` | Status tiap sesi | Awal dan akhir setiap sesi |
| `SESI-LOG.md` | Catatan serah-terima | Entri terakhir dibaca di awal sesi; entri baru ditulis di akhir |

## Aturan singkat
Enam aturan kerja ada di `AGENTS.md` bagian "AI Advisor v2". Yang paling sering dilanggar: **tidak boleh ada rumus angka periode di luar `metrics.py`**, dan **tidak ada teks insight di luar `render.py`**.

## Sumber di luar repo
- Project claude.ai "jatahku": salinan dokumen ini + `pikir-pikir-desain.md`, `paritas-web-telegram.md`. Kalau spesifikasi berubah, ubah di repo lewat PR, lalu sinkronkan ke project.
- Papan progres "Papan AI Advisor" dan canvas mockup "AI Advisor — Jatahku" di claude.ai (privat untuk organisasi).
