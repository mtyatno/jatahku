# Multi-Session Workflow Bundle — Design

**Date:** 2026-06-27
**Status:** Approved (brainstorming)

## Goal

Buat sebuah **bundle folder yang bisa di-copy** ke repo lain (baru maupun eksisting) untuk menanamkan pola kerja multi-session ala superpowers — **tanpa bergantung pada plugin superpowers** dan **agent-agnostic** (Claude Code, Codex, Cursor, dll). Bundle membawa esensi workflow sebagai teks/instruksi + template + lapisan memory in-repo.

## Context

Repo jatahku memakai 3 lapisan kontinuitas antar-sesi:
1. Auto-memory eksternal (`~/.claude/...`) — khas Claude Code, per-mesin.
2. Superpowers specs/plans di-commit (`docs/superpowers/{specs,plans}`) — checkbox `- [ ]` sebagai titik resume.
3. Brainstorm/scratch artifacts (`.superpowers/`, `temporary_file/`) — untracked.

User ingin mem-port pola ini ke repo lain, tapi:
- **Tidak terikat plugin** → esensi workflow ditanam sebagai teks biasa yang dibaca agent apa pun.
- **Agent-agnostic** → `AGENTS.md` jadi sumber kebenaran, `CLAUDE.md` cukup nge-link.
- **Memory in-repo & di-commit** → fakta awet jadi milik bersama tim, bukan per-mesin.

## Approach Decision: Pointer-Based (chosen)

Masalah: repo eksisting sering sudah punya `AGENTS.md`/`CLAUDE.md`. Bundle yang membawa file penuh akan bentrok/menimpa.

Solusi: **seluruh isi workflow tinggal di `docs/superpowers/WORKFLOW.md`** (file baru, dir baru → nol konflik). File instruksi (`AGENTS.md`/`CLAUDE.md`) cukup ditambah **satu baris pointer** ke WORKFLOW.md.

- **Repo baru:** salin semua; `AGENTS.md` & `CLAUDE.md` ikut dibuat.
- **Repo eksisting:** salin folder `docs/superpowers/` (aman), tempel 1 baris pointer ke instruksi yang sudah ada, tambah baris `.gitignore`. Nol konflik.

Alternatif yang ditolak:
- *AGENTS.md penuh dibawa bundle* — bentrok dengan file eksisting.
- *Script installer* — user memilih copy manual (lebih sederhana, tanpa eksekusi).

## Architecture / Structure

Bundle dibuat **di luar repo jatahku**, di `Z:\jatahku.com-v3\multisession-bundle\`.

```
multisession-bundle/                 # folder bundle; user copy isinya
├── INSTALL.md                       # cara pasang (TIDAK ikut disalin ke target)
├── _snippets/
│   ├── agents-pointer.md            # 1 baris untuk AGENTS.md / CLAUDE.md
│   └── gitignore.txt                # baris scratch untuk .gitignore
└── docs/                            # INI yang disalin ke root repo target
    └── superpowers/
        ├── WORKFLOW.md              # kanonik, self-contained, plugin-independent
        ├── README.md                # orientasi singkat
        ├── specs/
        │   ├── .gitkeep
        │   └── _TEMPLATE-design.md
        ├── plans/
        │   ├── .gitkeep
        │   └── _TEMPLATE-plan.md
        └── memory/
            ├── MEMORY.md            # index (di-commit, dibagi tim)
            └── _TEMPLATE.md
```

## Components

### `docs/superpowers/WORKFLOW.md` (inti)
Self-contained, tool-agnostic. Menanam lifecycle superpowers sebagai instruksi tertulis:
- **Lifecycle:** brainstorm → spec → plan → execute (TDD) → review → verify → finish.
- **Spec:** apa & kapan, lokasi `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`.
- **Plan:** task-by-task, tiap task mulai "Step 1: write the failing test"; checkbox `- [ ]` = titik resume antar-sesi; lokasi `docs/superpowers/plans/`.
- **TDD:** red → green → refactor.
- **Systematic debugging:** telusuri akar masalah sebelum menebak fix.
- **Verification before completion:** jalankan verifikasi & lihat output asli sebelum klaim selesai.
- **Memory in-repo:** satu fakta satu file di `docs/superpowers/memory/`, indeks di `MEMORY.md`; kapan menulis vs tidak.
- **Scratch convention:** working files di dir untracked; jangan di-commit.
- Catatan: jika kebetulan pakai plugin superpowers, skill-nya melengkapi; tapi workflow ini tidak mensyaratkannya.

### `_TEMPLATE-design.md`
Kerangka spec: Goal, Context, Approaches (2-3 + rekomendasi), Design/Architecture, Components, Testing.

### `_TEMPLATE-plan.md`
Kerangka plan task-by-task; tiap task: `Files:` (modify/test), `- [ ] Step 1: Write the failing test`, `- [ ] Step 2: Implement`, `- [ ] Step 3: Verify`.

### `memory/MEMORY.md` + `_TEMPLATE.md`
Index satu-baris-per-memori + aturan "satu fakta satu file" dengan frontmatter (name, description, type). Berbeda dari auto-memory eksternal: ini **di-commit & dibagi tim**.

### `README.md`
Orientasi 1 layar: apa isi folder ini, alur singkat, link ke WORKFLOW.md.

### `INSTALL.md` (tidak disalin ke target)
Langkah pasang untuk repo baru vs eksisting + checklist verifikasi.

### `_snippets/`
- `agents-pointer.md`: baris pointer untuk ditempel ke AGENTS.md/CLAUDE.md.
- `gitignore.txt`: baris scratch dir untuk ditambah ke .gitignore.

## Data Flow (cara dipakai di repo target)

1. User copy `docs/superpowers/` ke root repo target.
2. Repo baru → copy juga AGENTS.md/CLAUDE.md (dibuat dari snippet). Repo eksisting → tempel baris pointer ke file yang ada.
3. Tambah baris `.gitignore`.
4. Agent membaca AGENTS.md → diarahkan ke WORKFLOW.md → mengikuti pola: brainstorm ke spec, plan ke plans, eksekusi via checkbox, catat fakta ke memory.

## Error Handling / Edge Cases

- **Repo eksisting sudah punya AGENTS.md/CLAUDE.md** → pointer-based append, bukan overwrite.
- **Tidak ada AGENTS.md** → INSTALL.md sediakan konten minimal.
- **Konflik nama folder docs/superpowers** → tidak diharapkan; INSTALL.md ingatkan cek dulu.
- **Plugin superpowers kebetulan ada** → tidak masalah; WORKFLOW.md tetap valid, skill plugin melengkapi.

## Testing

Bundle berisi dokumen/template (bukan kode), jadi verifikasi bersifat manual:
- **Smoke test struktur:** seluruh file ada sesuai pohon di atas.
- **Dry-run repo baru:** copy ke folder kosong, pastikan AGENTS.md→WORKFLOW.md konsisten, template terbaca.
- **Dry-run repo eksisting:** copy `docs/superpowers/` + tempel pointer ke AGENTS.md dummy yang sudah berisi konten lain; pastikan nol konflik & pointer terbaca.
- **Lint tautan:** semua referensi antar-file (pointer, README→WORKFLOW, MEMORY index) valid.

## Out of Scope (YAGNI)

- Script installer otomatis (user memilih copy manual).
- Template repo terpisah.
- Integrasi auto-memory eksternal Claude (digantikan memory in-repo; boleh disebut sebagai opsi 1 kalimat di WORKFLOW.md).
