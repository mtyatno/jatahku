"""Konstanta Kotak Struk ("Bagikan ke Jatahku"). Nilai persis dari spec
docs/superpowers/specs/2026-10-26-bagikan-ke-jatahku-design.md."""
from datetime import timedelta
from fractions import Fraction

WAIT_BOT_S = 10      # bot dan PWA menunggu hasil sebelum menjawab "masih dibaca" (detik)
WAIT_FORM_S = 45     # tombol Struk di form Catat (mode tunggu) sebelum membalas "sedang ramai" (detik)

STALE_PROCESSING = timedelta(minutes=5)   # item 'diproses' lebih lama dari ini dikembalikan ke antrean
MAX_ATTEMPTS = 3                          # setelah itu item 'gagal'
ITEM_EXPIRY = timedelta(days=7)           # item siap/gagal yang tidak dikonfirmasi -> 'kedaluwarsa'

RATE_PER_HOUR = 30         # bukti per user per jam, gabungan semua kanal
MAX_FILES_PER_SHARE = 10   # file per satu share
MAX_PENDING = 20           # item belum selesai per user

IMAGE_MAX_BYTES = 8 * 1024 * 1024
PDF_MAX_BYTES = 10 * 1024 * 1024
PDF_MAX_PAGES = 5
PDF_TIMEOUT_S = 15

NOTE_TTL_S = 300                          # bot menunggu teks catatan setelah tombol "Tambah catatan"
SOFT_DUP_WINDOW = timedelta(hours=3)      # kecocokan lunak dengan transaksi manual (+/- jendela ini)
CONFIDENT_SHARE = Fraction(2, 3)          # porsi minimal amplop teratas di peta merchant agar saran yakin
OLD_PROOF_DAYS = 60                       # bukti lebih tua dari ini diberi peringatan
TEXT_MAX_CHARS = 4000                     # batas panjang teks bukti
ORPHAN_FILE_AGE = timedelta(hours=1)      # file yatim di folder sementara lebih tua dari ini dihapus
READER_THRESHOLD = 0.5                    # skor minimum pembaca qris/transfer

# Status item
ST_DITERIMA = "diterima"
ST_DIPROSES = "diproses"
ST_SIAP = "siap"
ST_GAGAL = "gagal"
ST_TERCATAT = "tercatat"
ST_DILEWATI = "dilewati"
ST_KEDALUWARSA = "kedaluwarsa"
OPEN_STATUSES = {ST_DITERIMA, ST_DIPROSES, ST_SIAP}

# doc_type: struk_belanja | qris | transfer | tidak_dikenali
PROOF_TYPES = {"qris", "transfer"}

# source (nanti: web_upload, android, ios, email)
SOURCES = {"telegram", "web_chat", "web_form", "pwa_share"}
