# HANDOFF — Bagikan ke Jatahku (Part A, server)

Session moved to another Claude account at 2026-10-26 22:46 WIB. Read this file first, then continue.

## Where things are
- Branch: `feat/bagikan-ke-jatahku-server` (base `a1d2dcb`), pushed to origin. HEAD = the commit that adds this file.
- Spec (binding): `docs/superpowers/specs/2026-10-26-bagikan-ke-jatahku-design.md`
- Plan: `docs/superpowers/plans/2026-10-26-bagikan-ke-jatahku.md` (tasks A1–A14, B1–B6)
- Method: superpowers `subagent-driven-development` (one implementer subagent per task → task reviewer → fix rounds,
  max 5, rounds 4–5 fresh + more capable model → ledger). User asked: "kerjakan dengan subagent-driven, agar benar
  benar teliti dan kalau ada finding di satu task, bisa di selesaikan finding tersebut sebelum memulai task berikutnya."
- The SDD ledger (normally in git-ignored `.superpowers/sdd/2026-10-26-bagikan-ke-jatahku/progress.md`) is copied
  below verbatim. To resume: recreate that folder, put the ledger section below into `progress.md`, and regenerate
  briefs with the plan (task brief = plan's Global Constraints + Review Focus + the task section).

## Status
- DONE (review clean): A1–A11. Commits on the branch; see the ledger's `complete` lines.
- NEXT: **A12** (maintenance, account deletion, Admin stats). The dispatch was prepared but not sent. Controller
  decisions to hand the A12 implementer:
  1. `expire_items` = ONE conditional UPDATE (`WHERE status IN ('siap','gagal') AND expires_at < :now`) →
     `kedaluwarsa`, `ocr_lines=NULL`; rows kept; don't touch `transaction_ids`, `ref_hash`, `file_sha256`.
  2. `purge_stale_ocr_text` (24 h) stays as is (spec line 203).
  3. Orphan files: never delete files of `diterima`/`diproses` items; only regular files directly in `KOTAK_DIR`
     (no recursion, no symlinks); missing dir → 0; vanished file not an error. Check intake.py file naming.
  4. Household deletion removes `MerchantEnvelopeMap` (via merchant ids) + `HouseholdMerchant` before envelopes;
     a single member deleting their account → map stays, `last_user_id` → NULL (explicit if FK action can't be
     relied on); test both.
  5. `accuracy_stats` additions don't change existing keys; legacy rows (status NULL) not in `by_issuer`.
- THEN: A13 (corpus tool + gate). A14 is BLOCKED until the user provides real QRIS/transfer screenshots/PDFs
  (also apply the A5 parked one-line fix there: a title from a name line may only contribute gagal/pending,
  never berhasil).
- Finish Part A: docs (`docs/kotak-struk.md`, ADR-M17, FS-1/FS-2 split in `docs/mobile`, AGENTS.md deploy
  checklist; also fix `docs/chat-bot-web.md` quota text and `docs/scan-struk.md:228`), final whole-branch review on
  the most capable model pointed at the ledger's `minor (deferred)` and `parked` lines, ONE fix wave, then PR with
  label `migrasi`. **Push to main / merge needs the user's consent** (main auto-deploys).
- Part B (B1–B6) on stacked branch `feat/bagikan-ke-jatahku-web` from Part A's head.
- Final message to the user must list every ledger line containing `Ruling:` under "Rulings I made", with cost if wrong.

## Test commands
- Backend: `DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python -m unittest discover -s app/tests -t .` (last full run: 1675 OK at A11)
- API additive check: `python -m app.scripts.openapi_cek`
- Frontend: `cd frontend && node --test src/lib/*.test.js src/native/*.test.js && npm run build`

## Ledger (verbatim copy of progress.md)

# SDD ledger — plan: docs/superpowers/plans/2026-10-26-bagikan-ke-jatahku.md

Spec: docs/superpowers/specs/2026-10-26-bagikan-ke-jatahku-design.md (Project doc claude/bagikan-ke-jatahku-desain.md)
Repo: /home/claude/jatahku, branch feat/bagikan-ke-jatahku-server, start base a1d2dcb (main, includes camera plan merge)
Baseline backend suite: 1096 tests OK (python3.13 local; CI 3.12). Test cmd: DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test JWT_SECRET=test-secret python3 -m unittest discover -s app/tests -t .

## Pre-flight scan

| Pair / task | Produces → consumes | Finding |
|---|---|---|
| A1 → A2..A12 | package `kotak_struk/__init__.py`, model columns, constants | consistent |
| A2 → A5 | `Ref`, `Counterparty`, `mask_digits` | consistent |
| A2 → A7 | `counterparty_key(cp, nmid=, account_number=, bank_code=)`, `hmac_hex` ← `Secrets(ref_values, account_number, bank_code, nmid)` (A4) | consistent |
| A3 → A4/A7 | `TextDoc`, `extract_text`, `ExtractError.user_message` | consistent |
| A4 → A5 | `register_proof_reader`, stub `checks.py`, tie order proof readers before struk_belanja | consistent (A4 "bukti bayar sebelum struk belanja" = A5 order) |
| A4 self | test `test_llm_fallback_kept_for_low_confidence_receipt` lines ["TOKO","TOTAL 10.000","x"] → parse_receipt gives `sedang` (strong label) → LLM never called; also struk detect<0.5 → Unknown | CONFLICT → Ruling R3 |
| A4 ↔ A10 | old `test_low_confidence_uses_llm_fallback` (lines ["buram"]) expects LLM fallback; with registry, unreadable → UnknownReader (no LLM) = behavior regression | CONFLICT → Ruling R3 |
| A5 self | synthetic corpus vs reader rules (labels, fallback Rp amount, top-up/masuk via TransferReader, "dari" label for masuk) | consistent; masuk needs `dari` label (not in GENERIC merchant list) — implementer handles in TransferReader |
| A6 → A9 | `create_item(db, req, *, redis, kotak_dir, now)`, `IntakeRejected.status_code/detail` | consistent |
| A7 → A11 | worker calls `app.bot.receipt_cmd.send_ready_message(item_id)` (lazy import) | consistent (A11 defines it; until A11, AttributeError is caught+logged) |
| A7 → A9/A10 | `wait_for_item(item_id, timeout_s, ...)` | consistent |
| A8 → A9/A10/A11 | `suggest_for_item`, `check_recordable`, `learn_text_for_item`, `mark_recorded(db, item_id, *, user_id, transaction_id, envelope_id)` | consistent |
| A9 → A10/A11 | `item_detail(db, item, user, *, note)` | consistent |
| A10 → A11 | `scan_receipt_response(item, detail)` reused by bot for struk_belanja message | consistent (A10 before A11) |
| A10 self | `learned_keywords() == {"bakso"}` for "bakso 2 (Siti Aminah)" | consistent with `extract_keywords` (len≥3, phrase not duplicated) |
| A12, A13 | stats breakdown, corpus eval over synthetic corpus | consistent |
| A14 | needs real samples from owner | BLOCKED → Ruling R1 |
| Global: "Bagian B dimulai setelah PR Bagian A di-merge" | B needs A's API | Ruling R2 |
| B1..B6 ↔ camera plan | `api.uploadForm`, `receiptProgress`, `useReceiptScan`, `ReceiptInput`, `native.camera` internals | camera plan merged in base a1d2dcb — verify names at B-task dispatch |

## Rulings

- Ruling R1: Execute A1–A13 now; A14 parked until owner supplies real samples (user is collecting them). — corpus gate test skips until real reviewed samples exist; proof readers stay behind `features.receipt_inbox` (default off). — cost if wrong: none for code; release gate simply not yet met.
- Ruling R2: Part B runs on a stacked branch `feat/bagikan-ke-jatahku-web` created from Part A's final head, instead of waiting for Part A's merge. — merge needs owner consent; stacking lets work continue. — cost if wrong: rebase of B if A changes during PR review.
- Ruling R3: (a) A4 LLM test uses a receipt-shaped low-confidence input (e.g. ["TOKO MAJU", "ROTI 10.000", "SUSU 5.000", "SUBTOTAL 15.000"]) so StrukBelanjaReader is chosen and confidence is `rendah`; (b) UnknownReader also attempts the existing LLM fallback when `ctx.llm` and `ctx.image` are set, and on success returns a `struk_belanja` document with `extra["engine"]="llm"` — preserves today's behavior (any rendah/gagal scan tries LLM). — LLM is disabled by default and budget-capped. — cost if wrong: extra LLM calls on unrecognized docs when LLM is enabled.

## Progress
Task A1: complete (commits a1d2dcb..666d24c, review clean)
Task A1: minor (deferred): partial unique index (user_id, upload_id) only in KOTAK_DDL, not model → carried into A6 dispatch
Task A1: minor (deferred): KOTAK_HMAC_KEY default "" → A2 derives key from JWT_SECRET with warning (plan); final review to confirm fail-safe
Task A1: minor (deferred): test_every_new_column_has_ddl does not check DDL types/index statements
Task A1: minor (deferred): startup DDL locks/race on multi-worker start (pre-existing pattern)
Task A1: minor (deferred): receipt_scans.household_id has no FK (brief-compliant)
Task A2: fix round 1/5 (2 addressed, 0 open — fallback descriptions no longer learnable; dot/dash-masked accounts not hashed; commits 4f38bdb..31d214f)
Task A2: complete (commits 666d24c..31d214f, review clean after 1 fix round)
Task A2: minor (deferred): test order-dependence of HMAC warning (_warned_no_key global) / stderr noise when run alone
Task A2: minor (deferred): display_name "DOMINO'S" → "Domino'S"; acronym list misses KFC/PLN (plan-mandated list)
Task A2: minor (deferred): bank_code not normalized inside rek: key → A5 readers must emit uppercase stripped bank_code (carried to A5 dispatch)
Task A2: minor (deferred): no tests for different accounts → different keys / bank_code changes key / whitespace nmid
Task A2: note: a note exactly "transfer"/"bukti bayar"/"pembayaran qris" learns nothing (accepted by controller decision)
Task A3: Ruling: add RLIMIT_CPU (PDF_TIMEOUT_S + 5 s) in the child initializer although the brief listed only RLIMIT_AS — spec 6b ("memori dan CPU") is binding — cost if wrong: none (extra backstop).
Task A3: Ruling: owner-password-only encrypted PDFs (open without a password) are accepted; only PDFs that need a user password to open are rejected ("PDF terkunci kata sandi") — many bank-generated PDFs restrict editing with an owner password; rejecting them would reject legitimate proofs; spec "Terenkripsi ditolak" read as "cannot be opened" — cost if wrong: owner-restricted PDFs are read (no security impact, content is visible anyway).
Task A3: fix round 1/5 (2 addressed, 0 open — child killed on cancel/any early exit; RLIMIT_CPU added; owner-password ruling applied; commits 274dcf0..5eab96c)
Task A3: complete (commits 31d214f..5eab96c, review clean after 1 fix round)
Task A3: minor (deferred): _kill_pool uses private executor._processes (recheck on Python 3.14); SIGTERM only
Task A3: minor (deferred): mixed PDFs — OCR lines appended after all text-layer lines (page order lost); pages with any text layer never OCRed
Task A3: minor (deferred): mid-document OcrBusy discards already-OCRed pages
Task A3: minor (deferred): no real-PDF test for password/owner-password; render cap not exercised in child; Pillow not pinned (transitive via rapidocr); no RLIMIT_CORE
Task A4: Ruling: expose normalized parse_receipt lines as Parsed.extra["ocr_lines"] (reviewer Important, plan gap) — feedback learning (payment_amounts/find_label_for_amount) reads normalized lines from receipt_scans.ocr_lines today — cost if wrong: none.
Task A4: fix round 1/5 (1 addressed, 0 open — extra["ocr_lines"] normalized lines; commits 4de6849..be35fb1)
Task A4: complete (commits 5eab96c..be35fb1, review clean after 1 fix round)
Task A4: minor (deferred): LLM rescue in UnknownReader discards OCR merchant/date/total_label (blank ReceiptParse base)
Task A4: minor (deferred): ReadResult.reader "tidak_dikenali" while doc_type "struk_belanja" on LLM rescue → A7 must branch on doc_type/extra["engine"] (carried to A7)
Task A4: minor (deferred): test_stub_checks_leave_store_receipt_without_checks pins A5 stub (checks == []) → A5 updates it (carried to A5)
Task A4: minor (deferred): ParseContext.content_type None + image → LLM call fails silently (content_type.startswith) → A7 must pass item.content_type (carried to A7)
Task A4: minor (deferred): date parsing: 2-digit years → None; trailing Z/WITA/WIT read as WIB; "13:00 PM" → 00:00
Task A4: minor (deferred): struk_belanja _is_item_like counts TUNAI/KEMBALI/PPN/Nominal lines → transfer slips score 0.9 on struk detector (carried to A5); find_amount None for < Rp100 (fees) → A5 treats None as 0
Task A4: minor (deferred): item_discounts / extra not persisted → A7/A10 decide (carried)
Task A4: minor (deferred): two copies of LLM override logic (receipt_scan.py and struk_belanja.py) until A10 retires the old path
Task A5: Ruling: common_checks run only for proof doc types (qris/transfer), not struk_belanja — keeps store-receipt behavior unchanged (review focus 2); spec 3c checks are proof-oriented — cost if wrong: store receipts get no date warnings (same as today).
Task A5: Ruling: proofs keep Parsed.extra without ocr_lines (proof OCR text is not persisted) — learning from OCR lines (apply_feedback) is store-receipt only, and proof text holds names/account numbers — cost if wrong: none for learning; less data retained.
Task A5: Ruling: add generic labels "nama penerima", "nomor rekening", "nomor referensi" (and similar common variants) now, updating the test that pins the label list — plan-mandated gap; without a reference value no ref_hash → dedup cannot fire — cost if wrong: minor label overlap, covered by tests.
Task A5: fix round 1/5 (5 addressed, 2 new Important — CTA filter suppressed real gagal; store-receipt veto rules misfire on proofs; commits 2e7617d..d4cd8b9)
Task A5: fix round 2/5 (1 addressed, 2 open — store-receipt veto still fires on unlisted extra-charge lines; widened _is_cash_line routes failed proofs to struk_belanja; commits d4cd8b9..1bd3ff4)
Task A5: Ruling: defense in depth for review focus "transfer gagal tidak bisa dicatat" — the shared status detector also runs for struk_belanja (header tier only; default berhasil), and common_checks' status checks (status_gagal/status_pending) apply to every doc type, while the other checks stay proof-only — a misrouted failed proof can then never be recorded — cost if wrong: a store receipt with "gagal" in its first lines gets blocked (very rare; user can retake).
Task A5: fix round 3/5 (3 addressed + 4 minors, 1 new Important open — N1 extra labels (layanan/tips/donasi/ongkir) add phone numbers to fee/total; commits 1bd3ff4..5d855f7)
Task A5: Ruling: round 4 also closes (a) UnknownReader status detection (header tier → gagal/pending, so status_gagal applies) — completes the defense-in-depth ruling; (b) N2 help-line lines ("Info/Bantuan untuk transaksi gagal: 14017") must not block a successful proof — a hard block of a valid proof is user-facing — cost if wrong: small extra scope in round 4.
Task A5: fix round 4/5 (3 addressed, 1 new Important — NB1 help line with two status words blocks successful proof; commits 5d855f7..7ab78a5)
Task A5: fix round 5/5 (3 addressed, 0 open — NB1 help phrases with several status words; NB2 status titles under name labels; N1 plain-number fees ≤4 digits; commits 7ab78a5..3f53577)
Task A5: parked — name-line status title may contribute "berhasil" and let an unlabelled failure below line 4 through (e.g. "Tujuan Transfer CV SUKSES JAYA" before "Transaksi Gagal") — Ruling: real, rare; one-line fix (a title from a name line may only contribute gagal/pending, never berhasil) carried into Task A14 calibration and the final review; loop cap reached — cost if wrong: a rare failed proof could be recorded until A14.
Task A5: complete (commits be35fb1..3f53577, 1 parked)
Task A5: minor (deferred): "Tujuan Transfer TOKO GAGAL MANIA" / "Ke Rekening TOKO PENDING" names can set gagal/pending on a successful proof (rare)
Task A5: minor (deferred): "Ongkir 15000,-" plain digits with ",-" → fee 0; "Tips 10000" plain 5+ digits → fee 0 (under-count, never inflate)
Task A5: minor (deferred): bare "Gagal" under a standalone "Merchant" label not counted; "Info transaksi pending/gagal: 14017" (no "untuk") still blocks a successful proof; "Status: Berhasil (jika gagal, hubungi CS)" reads gagal
Task A5: minor (deferred): with readers off, struk_belanja reads help-line phone numbers into its total (legacy parser)
Task A5: minor (deferred): 1–2 item receipts with plain prices (no thousands separator) + bare QRIS line + NMID read as qris/tidak_diketahui (not blocked); one-marker transfers (DANA "Kirim Uang") read as struk_belanja — calibrate in A14
Task A5: minor (deferred): duplicated label-prefix regex (labels.py/proof_common.py/profiles.py); transfer.py hand-written label lists; NMID on same line as merchant name not extracted
Task A5: minor (deferred): bank code with slash "BCA/0123456789" → "BCA/" changes rek: key; "Total Diskon" not read as discount; "Convenience Fee" not a fee label; "Transaksi tidak dapat diproses" read as pending (warn) not gagal
Task A6: Ruling: add the partial unique index uq_receipt_scans_upload to ReceiptScan.__table_args__ (postgresql_where/sqlite_where upload_id IS NOT NULL, same name as KOTAK_DDL) and handle the IntegrityError race in create_item by returning the existing item — closes the A1 minor; DB-level idempotency for concurrent double-share — cost if wrong: none (same index name, DDL becomes no-op).
Task A6: complete (commits 3f53577..27bd71b, review clean)
Task A6: minor (deferred): rate counter INCR then EXPIRE not atomic — TTL-less key could 429 a user permanently (repo-wide pattern)
Task A6: minor (deferred): commit-failure path deletes file even if commit succeeded server-side (ambiguous failure) — prefer leaving file for the sweeper
Task A6: minor (deferred): file not removed if SAVEPOINT release/file_path UPDATE fails after write
Task A6: minor (deferred): synchronous 10 MB file write inside open transaction (asyncio.to_thread)
Task A6: minor (deferred): KOTAK_DIR mode only applied to newly created leaf (deploy must create 0700)
Task A6: minor (deferred): concurrent identical shares without upload_id can create two open items (confirm-time recorded_duplicate blocks double record)
Task A7: Ruling: for struk_belanja items the worker stores the legacy-response data that DokumenBayar cannot hold (item_discounts, adjustments, reconciliation, confidence_source, total_label) in the item document JSON under a reserved "receipt" key (DokumenBayar.from_json ignores it); ocr_lines persisted only for struk_belanja (normalized extra["ocr_lines"]), never for proofs — A10 rebuilds the old scan-receipt response from it; proof OCR text is not retained — cost if wrong: one extra JSON key.
Task A7: Ruling: run the proof readers' detect() even when the flag is off; if any proof reader scores ≥ READER_THRESHOLD on the text, the item is "proof-like": do not persist ocr_lines and do not upsert household_merchants for it (regardless of the routed doc_type) — keeps the "nomor rekening/RRN tidak pernah disimpan utuh" constraint while the flag is off — cost if wrong: a store receipt that looks like a proof loses OCR-based feedback learning for that one scan.
Task A7: Ruling: the proof-like guard applies only to items routed to struk_belanja/tidak_dikenali; proofs read by the qris/transfer readers (flag on) still upsert the household merchant map — A8 suggestions are built from that map and those items never store ocr_lines — cost if wrong: none for privacy (keys are nmid/name/hmac only).
Task A7: fix round 1/5 (1 addressed, 0 open — flag-off proofs stored raw acct/RRN in ocr_lines + junk merchant row; commits 4986810..5fa7156)
Task A7: minor (deferred): test noise "Executing <Task ...asyncSetUp> took 0.12s" — configure_mappers() in setUpModule
Task A7: minor (deferred): run_worker has no backoff when the DB is down
Task A7: minor (deferred): no test pins a _store commit failure
Task A7: minor (deferred): flag-off proof items still carry merchant="Transfer Berhasil"/counterparty_key "nama:transfer berhasil|" on the item row (not in merchant map); A8 must not learn from item-level key of unread proofs
Task A7: minor (deferred): looks_like_proof runs proof detect() a second time for flag-on store receipts (regex cost only)
Task A7: carry → A11: send_ready_message is called for gagal items too; A11 must render failed items
Task A7: carry → A12: receipt_scan.purge_stale_ocr_text nulls ocr_lines after 24h and sets outcome="expired" for siap struk items still open in Kotak (7-day expiry) — A12 must make the purge skip open Kotak items (status diterima/diproses/siap)
Task A7: complete (commits 27bd71b..5fa7156, review clean)
Task A8: review a42c2c1 — spec ✅, quality Approved, 0 Critical/Important; 3 ⚠️ resolved by controller below
Task A8: Ruling: set_display_name with an empty name returns the row with display_name=None (clears the nickname), None only for missing/other-household merchant; no commit (A9 route commits) — matches A9's PUT contract (404 only for another household) — cost if wrong: A9 adjusts one return check.
Task A8: Ruling: cross-task double-record window confirmed as a real gap (A10 plan commits the transaction before mark_recorded; check_recordable takes no lock → bot+web or two taps with different client_refs can both record one proof). Fix in A8: add record.claim_for_recording(db, item_id, user_id) -> bool (no commit; proof items: conditional UPDATE status siap→tercatat for the owner; non-proof: True iff owned and siap/tercatat, no change) and make mark_recorded idempotent per transaction_id. A10/A11 must call the claim in the SAME commit as the transaction insert and answer 409/"Bukti ini sudah tercatat" when it returns False — cost if wrong: one extra helper; A10/A11 dispatch must carry this.
Task A8: Ruling: Review Focus 5's named pin (test_hidden_or_inactive_envelopes_never_suggested) does not pin "saran jatuh ke sinyal berikutnya" nor visible-only confidence, and the ruling-1 guard test passes with the guard removed — treated as a confirmed gap (the plan names these tests as the pins), not a deferred minor — cost if wrong: a few extra tests.
Task A8: minor (deferred): ruling 2 untested for tidak_dikenali items; _bump_map IntegrityError fallback untested
Task A8: minor (deferred): record.py uses private _find_merchant where merchant_for_item fits
Task A8: minor (deferred): household lookup `.limit(1)` without ORDER BY duplicates envelope_balance.get_household_id (same pattern in intake.py:188)
Task A8: minor (deferred): mark_recorded's learning try/except wraps begin_nested autoflush of the item change → misleading warning; flush before the try
Task A8: minor (deferred): pre-existing full-suite noise (~315 lines from advisor/Redis tests) — separate cleanup
Task A8: minor (deferred): cross-ITEM concurrent record of the same ref_hash by two members (two items, same proof) still has a window; consider a partial unique index on (household_id, ref_hash) WHERE status='tercatat'
Task A8: fix round 1/5 (3 addressed, 0 open — claim_for_recording for double-record window; mark_recorded idempotent per transaction_id; Review Focus 5 pins; commits a42c2c1..0bac151)
Task A8: minor (deferred): mark_recorded's idempotent early return does not commit though docstring says it commits (nothing pending in practice)
Task A8: carry → A10/A11: order is check_recordable → claim_for_recording (same session) → insert transaction → ONE commit → mark_recorded; claim False → 409 / "Bukti ini sudah tercatat" with rollback. On a client_ref idempotent replay that carries receipt_item_id, call mark_recorded again (idempotent) so a crash between commit and mark_recorded heals.
Task A8: complete (commits 5fa7156..0bac151, review clean)
Task A9: review 59a2222 — spec ✅, quality Approved, 0 Critical/Important; ⚠️ resolved by controller: intake rejects file+text (422, intake.py:139), 429 for rate and MAX_PENDING (intake.py:176,184), openapi_cek "Tidak ada perubahan API yang memutus"
Task A9: Ruling: accepted implementer deviations — soft_duplicate gets optional viewer_id (fails closed without it) and excludes other members' personal envelopes; compares the WIB date of paid_at (matches worker parsed_date) instead of paid_at.date() — repo visibility contract + UTC storage — cost if wrong: users outside WIB get soft-dup misses near midnight.
Task A9: minor (deferred): lewati read-merge-writes channel_meta (lost update if A11 writes channel_meta concurrently)
Task A9: minor (deferred): GET /kotak-struk/ runs item_detail per row (N+1, ~500 queries for 50 tercatat rows) — revisit before Part B polls it
Task A9: minor (deferred): rename_merchant hand-rolls household lookup instead of envelope_balance.get_household_id
Task A9: minor (deferred): soft_duplicate lower window bound untested; pending-ref vs soft precedence untested
Task A9: minor (deferred): test_kotak_api raises slow_callback_duration to 2.0s class-wide to silence asyncio debug warnings
Task A9: minor (deferred): no response_model/201 status declared → openapi_cek can't catch field removals in the detail body
Task A9: carry → Part B: routes live at /kotak-struk/ (trailing slash; no-slash → 307)
Task A9: carry → A11: HTTP route accepts source=telegram (intake SOURCES) with no channel_meta — the worker's ready-notification must dispatch on channel_meta (chat_id) presence, not on source, and never crash on a telegram item without chat_id; for blocked=="sudah_tercatat" the bot needs the recorded transaction's date/envelope, which item_detail doesn't carry (see task-A9-report.md)
Task A9: complete (commits 0bac151..59a2222, review clean)
Task A10: review 7ee5270 — spec ✅, quality Needs fixes (1 Important)
Task A10: Ruling: claim exclusivity covers every non-struk_belanja doc_type (qris, transfer, tidak_dikenali), matching check_recordable; merchant learning stays PROOF_TYPES-only — my A8 ruling said PROOF_TYPES, which left tidak_dikenali recordable twice — cost if wrong: none (tidak_dikenali is one row per item per spec §5c).
Task A10: Ruling: sparse store-receipt photos (e.g. ["TOKO","45.500"]) that fall to UnknownReader must keep the legacy low-confidence best guess (parse_receipt total/merchant/date) when no amount was read — Review Focus 2 says ordinary receipt photos behave as today, and this regresses with the flag OFF (production default); restore test_llm_crash_keeps_ocr_result's original input — cost if wrong: random text shares get a low-confidence guessed amount the user must confirm anyway.
Task A10: Ruling: move the Kotak recording sequence (_after_recorded: learn → streak → mark_recorded; _heal_receipt_record guards) from routes/transactions.py into kotak_struk/record.py now, because A11's bot path needs the same sequence (load-bearing, not a deferred minor); the helper rolls the session back after a swallowed DB error so the rest of the request (quota notice, next batch line) still works — cost if wrong: a small refactor.
Task A10: minor (deferred): docs/scan-struk.md:228 still says missing OCR package → 503 "Scan struk sedang tidak tersedia" (now gagal + 422 "Baca bukti sedang tidak bisa. Catat manual dulu.")
Task A10: minor (deferred): run_receipt_scan `except (ScanBusy, OcrBusy)` redundant; OcrUnavailable branch unreachable from scan_receipt
Task A10: carry → A11: bot caller of scan_receipt — IntakeRejected uncaught (HEIC/GIF documents, 30/h rate, MAX_PENDING → stuck "🧾 Membaca struk..." message); items labelled source="web_form"; waits WAIT_FORM_S (45) instead of WAIT_BOT_S (10)
Task A10: carry → A11: struk_belanja items recorded via the bot must also leave the inbox — _receipt_feedback_saved calls apply_feedback AND mark_recorded (when transaction_id given); a bot cancel/discard of a Kotak item → dilewati (conditional, like A9 lewati) — otherwise bot-recorded receipts linger as "siap" in the web inbox/banner for 7 days (spec §5 only names mark_recorded for non-struk)
Task A10: Ruling: struk_belanja items recorded or discarded through the bot leave the inbox (apply_feedback AND mark_recorded on record; dilewati on discard) although spec §5 names mark_recorded only for non-struk items — otherwise bot-recorded receipts show as waiting in the web inbox for 7 days — cost if wrong: struk items vanish from the inbox after a bot save, which is the intent.
Task A10: fix round 1/5 (3 addressed, 0 open — tidak_dikenali claim exclusivity; UnknownReader legacy guess; record.after_recorded/heal_recorded + session recovery; commits 7ee5270..31d5097)
Task A10: Ruling: the re-review's "Minor" new breakage is promoted to a fix — UnknownReader's legacy guess emits doc_type struk_belanja, so non-proof text like ["Rek BCA 1234567890","a.n. BUDI","150.000"] keeps the full account number in ocr_lines (Global Constraint: account numbers never stored in full) and departs from spec §223/§421 ("tidak_dikenali: item siap dengan nominal keyakinan rendah atau tanpa nominal"); the guess must keep doc_type tidak_dikenali (low confidence) — no ocr_lines retention, exclusive claim — cost if wrong: sparse store-receipt photos lose OCR-based feedback learning (total still shown as before).
Task A10: minor (deferred): path without receipt_item_id still calls after_expense_recorded with no session recovery (pre-existing)
Task A10: minor (deferred): commit trailers of subagent commits name the subagent's model (e.g. "Claude Sonnet 5.5") — accepted
Task A10: fix round 2/5 (1 addressed, 0 open — legacy guess stays tidak_dikenali, no ocr_lines, no account digits; commits 31d5097..e4f6cf9)
Task A10: minor (deferred): UnknownReader Rp-line path takes max(amounts) from any Rp/IDR line — a long digit run on such a line could become total
Task A10: minor (deferred): guessed merchant names keep the "a.n." (atas nama) prefix, e.g. household merchant "A.N. Budi"
Task A10: complete (commits 59a2222..e4f6cf9, review clean)
Task A11: Ruling: bot record paths use check_recordable + claim_for_recording in the same commit as the Transaction (one helper for the three paths) — same never-twice rule as web — cost if wrong: one helper.
Task A11: Ruling: A9's lewati conditional UPDATE moves into record.skip_item and is shared by the route and the bot (kx_/kd_/struk_no) — cost if wrong: small refactor.
Task A11: Ruling: notification race — the bot sets notify with a conditional UPDATE (status still diterima/diproses; rowcount 0 → render now) and the worker decides to notify from a fresh channel_meta read after its commit (worker.py _store/_fail/recover_stale) — otherwise a slow item can be promised "nanti kukabari" and never announced — cost if wrong: one extra SELECT per finished item.
Task A11: Ruling: item_detail shape unchanged; "sudah tercatat" date/envelope come from a helper + proof_message(detail, *, recorded=None); envelope name hidden when the viewer may not see that envelope — keeps A9's pinned flags shape and the visibility contract — cost if wrong: message lacks the envelope name in rare cases.
Task A11: carry file task-A11-carry.md (C1–C6) handed to implementer and reviewer
Task A11: Ruling: /batal while a note is pending only cancels the note (does not undo the last transaction) — the prompt "Ketik isi belanjaannya (atau /batal)" means cancel the note; undoing a transaction there would surprise the user — cost if wrong: user must send /batal twice to undo.
Task A11: Ruling: accepted implementer calls — "📝 {description_preview}" line after a note; struk_fix_ ("Nominal salah") also moves the item to dilewati; web_adapter.py WebBot/WebContext(bot=) change — cost if wrong: cosmetic / item leaves the inbox when the user fixes the amount by typing.
Task A11: carry → finish Part A docs: docs/chat-bot-web.md still describes the scan quota; web chat photo route (/bot/chat/photo) still refuses PDFs (A10 allow_pdf=False) — decide in Part B whether web chat accepts PDFs
Task A11: review e18a7d3 — spec ✅, quality Needs fixes (1 Important: stale kotak:note swallows next message)
Task A11: Ruling: web chat photo route (/bot/chat/photo) stays image-only in Part A — the web chat UI has no PDF picker and web PDFs arrive via the Catat form (B2) and the share target — cost if wrong: web-chat users can't drop a PDF into chat; one-line change later.
Task A11: Ruling: ⚠️ confirmed as a real gap (Review Focus 1 at bot level): sending the same file twice while it is still being read overwrites status_message_id, so the first "nanti kukabari" never resolves — enters fix round 1 — cost if wrong: small change.
Task A11: minor (deferred): no bot-level test records a tidak_dikenali item (claim covered at route/unit level)
Task A11: minor (deferred): _promise_notification holds the receipt row lock across the Telegram edit_text — bound it with asyncio.wait_for
Task A11: minor (deferred): handle_struk_callback says "❌ Struk dibatalkan." even when skip_item returned False (item recorded on web) and says "Struk" for QRIS/transfer
Task A11: minor (deferred): bot note uncapped vs API NOTE_MAX=200 (compose_description caps the description)
Task A11: minor (deferred): MSG_UNREADABLE ("Bukti tidak bisa dibaca") also used for DB/Redis failures and item None
Task A11: minor (deferred): send_ready_message has no fallback when _result_reply fails (Redis down) → promised notification never resolves
Task A11: minor (deferred): three UUID parsers (receipt_cmd:144, handlers:408, view:79); post-commit sequence repeated at handlers 617/874/1546; two "spendable" envelope rules in receipt_cmd
Task A11: minor (deferred): QRIS/transfer proof with no readable total falls into _store_reply wording ("foto tegak lurus") — wrong for PDF/text
Task A11: minor (deferred): test_kotak_bot silences asyncio debug with slow_callback_duration=2.0; pre-existing tracebacks in focused runs
Task A11: minor (deferred): bot imports WIB from reader-internal kotak_struk.readers.labels
Task A11: fix round 1/5 (2 addressed, 0 open — stale note no longer hijacks typing; same proof re-sent while reading keeps the first promise; commits e18a7d3..bfceff0)
Task A11: minor (deferred): if the first bot handler failed before promising notify and the user resends while the item is still waiting, message 2 says "hasilnya nanti di pesan sebelumnya" but nobody edits message 1 (window: until the item finishes)
Task A11: minor (deferred): forget_note on every t_ press cancels a pending note even for unrelated buttons (benign)
Task A11: minor (deferred): capture_note siap-check → edit TOCTOU vs a concurrent t_ tap may overwrite the success message (no double record — C1 claim)
Task A11: minor (deferred): fshift: forget_note untested; "same chat, no notify yet" branch of _answered_elsewhere not pinned by a committed test
Task A11: complete (commits e4f6cf9..bfceff0, review clean)
Task A12: Ruling: my A7 carry ("purge must skip open Kotak items") is rescinded — spec line 203 says ocr_lines are deleted after feedback or 24 h "seperti sekarang", so purge_stale_ocr_text stays as is (it never changes Kotak status); struk items confirmed after 24 h lose OCR-based learning, as legacy scans do — cost if wrong: slightly less learning from late confirmations.


## A11 carry file (task-A11-carry.md, already implemented)

# Task A11 — controller decisions carried from earlier tasks (binding)

These come from reviews of A7–A10 and are rulings recorded in the ledger. They add to the brief; where they
conflict with the brief's literal text, these win.

## C1. Never recorded twice — atomic claim in every bot record path
The bot records through the `t_{key}_{idx}` callback paths in `app/bot/handlers.py` (direct ±549, fund shift ±795,
daily-limit raise ±1441 — verify the exact places). For a payload whose `scan_id` is a Kotak item that is NOT
`struk_belanja` (qris, transfer, tidak_dikenali):
- before inserting the Transaction: `record.check_recordable(db, item_id, user)`; `NotRecordable` → edit the
  message with its `detail`, no transaction;
- in the SAME session, immediately before the commit that inserts the Transaction:
  `record.claim_for_recording(db, item_id, user.id)`; False → `rollback`, edit "✅ Bukti ini sudah tercatat.",
  no transaction;
- after the commit: learning (`learn_text_for_scan`) + `_receipt_feedback_saved(..., transaction_id, envelope_id)`
  as the brief says (`mark_recorded` is idempotent per transaction).
For `struk_belanja` items `claim_for_recording` returns True without changes (several transactions per receipt are
allowed) — calling it uniformly is fine. Do not write the check/claim logic three times: one helper used by the three
paths. A test must show a proof claimed by another session (e.g. web) between the button press and the commit →
no Transaction row, message says it is already recorded.

## C2. Struk belanja items recorded or discarded via the bot leave the inbox
`_receipt_feedback_saved`: proof/tidak_dikenali item → `mark_recorded(...)` only (brief test pins
`apply_feedback` NOT awaited); `struk_belanja` item → `apply_feedback` as today AND, when `transaction_id` is given,
`mark_recorded(...)` (appends the id, sets `tercatat`, no merchant learning). Otherwise bot-recorded receipts stay
`siap` in the web inbox/banner for 7 days.
"❌ Batal" (`struk_no_{item_id}`) and `kx_`/`kd_` move a `siap` item to `dilewati` (reason `batal` /
`bukan_pengeluaran` / `duplikat`). A9's `POST /kotak-struk/{id}/lewati` already does this with ONE conditional UPDATE
(`WHERE id AND user_id AND status IN ('siap','gagal')`) inside the route `app/api/routes/kotak_struk.py`; move that
into a shared helper in `app/services/kotak_struk/record.py` (e.g. `skip_item(db, item_id, user_id, reason) -> bool`,
no other behaviour change) and use it from both the route and the bot. Keep the existing discarded-feedback call for
struk items.

## C3. Notification race (Telegram "⏳ Masih dibaca, nanti kukabari.")
Current worker (`app/services/kotak_struk/worker.py` `_store` / `_fail` / `recover_stale`) decides whether to notify
from `channel_meta` loaded BEFORE its commit. If the bot sets `notify` after that load but before the worker commits,
the notification is lost; if the bot sets it after the worker finished, nobody renders. Rulings:
- the bot sets `notify` with ONE conditional UPDATE (`WHERE id=:id AND status IN ('diterima','diproses')`, merging
  `notify: true` into `channel_meta`); rowcount 0 → the item already finished → reload it and render immediately
  (no "Masih dibaca" message);
- the worker decides to notify from a FRESH read of `channel_meta` after its commit (a new SELECT), in `_store`,
  `_fail` and the `recover_stale` give-up path.
Tests: notify set between the worker's load and its commit → `send_ready_message` still called; item finished before
the bot's update → bot renders directly and the worker does not notify.

## C4. `send_ready_message(item_id)` robustness
- It renders `gagal` items too (message with `item.error`, e.g. "PDF terkunci kata sandi"), not only `siap`.
- It dispatches on `channel_meta` (`notify` and `chat_id` present), not on `source`: the HTTP route accepts
  `source=telegram` without any `channel_meta`; such items must be a silent no-op, never an exception.
- Edit `status_message_id`; edit failure → send a new message (brief).

## C5. "sudah tercatat" message needs the recorded transaction
`item_detail` does not carry the recorded transaction (see task-A9-report.md, "Catatan untuk tugas berikutnya").
Do not change `item_detail`'s shape (A9 tests pin `flags` exactly). Instead:
- `proof_message(detail, *, recorded=None)` stays pure; `recorded = {"date": date, "envelope_name": str | None}`.
- A helper (receipt_cmd or `kotak_struk/view.py`) finds the recorded item (the item itself when it is `tercatat`,
  else `flags.duplicate_of["item_id"]` when `duplicate_of.recorded`), its first transaction (not deleted), and the
  envelope name — `None` when the viewer may not see that envelope (personal envelope of another member; see
  `app/services/visibility.py`).
- Text: `"✅ Bukti ini sudah tercatat {tgl} di {amplop}."`; without envelope `"✅ Bukti ini sudah tercatat {tgl}."`;
  without any info `"✅ Bukti ini sudah tercatat."`. `{tgl}` like "26 Okt".

## C6. Intake from the bot
The bot must no longer go through `receipt_scan.scan_receipt` (it labels items `web_form` and waits 45 s). Use
`create_item(source="web_chat" if is_web() else "telegram", channel_meta=…)` + `wait_for_item(WAIT_BOT_S)` as the
brief says. Every `IntakeRejected` (415 HEIC/GIF documents, 413, 429 hourly limit / `MAX_PENDING`) edits the status
message with its `detail` — the "🧾 Membaca bukti..." message must never be left hanging. `ScanBusy`/`OcrBusy`
handling for the web form stays as A10 left it.
