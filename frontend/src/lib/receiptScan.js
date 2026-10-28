// Logika murni scan struk (tanpa DOM) — dipakai MultiAddTransaction & ReceiptInput.
import { toReceiptItems } from './receiptSplit.js';

const MAX_SIDE = 1600;

// Ukuran target kompresi: sisi panjang ≤ 1600px, rasio dipertahankan, tidak diperbesar.
export function fitDimensions(width, height, maxSide = MAX_SIDE) {
  const long = Math.max(width, height);
  if (!long || long <= maxSide) return { width, height };
  const s = maxSide / long;
  return { width: Math.round(width * s), height: Math.round(height * s) };
}

const CONFIDENCE_LABEL = {
  tinggi: 'cocok dengan pembayaran',
  sedang: 'cek lagi nominalnya',
  rendah: 'kurang yakin, mohon dicek',
  gagal: 'total tidak terbaca',
};

export function confidenceLabel(conf) {
  return CONFIDENCE_LABEL[conf] || '';
}

// ── Tanggal & waktu WIB ─────────────────────────────────────────────────────
// `paid_at` dari server berbentuk UTC di Postgres ("…T01:12:00+00:00" = 08.12 WIB), jadi tanggal tidak boleh diambil
// dengan `.slice(0, 10)`. Semua tanggal/jam dari `paid_at` lewat sini; server ("hari ini", awal periode) juga WIB.

const WIB_PARTS = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Jakarta', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

const HAS_ZONE = /(?:[zZ]|[+-]\d{2}:?\d{2})$/;

// {date: 'YYYY-MM-DD', time: 'HH.MM'} dalam WIB, atau null. Teks ISO tanpa zona dianggap UTC, seperti server
// (receipt_cmd._wib, dedup.soft_duplicate); pecahan detik lebih dari 3 angka (Python) dipotong.
function wibFields(value) {
  let d = null;
  if (value instanceof Date) d = value;
  else if (typeof value === 'string' && value) {
    const iso = value.replace(/(\.\d{3})\d+/, '$1');
    d = new Date(iso.includes('T') && !HAS_ZONE.test(iso) ? `${iso}Z` : iso);
  }
  if (!d || Number.isNaN(d.getTime())) return null;
  const p = Object.fromEntries(WIB_PARTS.formatToParts(d).map(x => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}.${p.minute}` };
}

export function wibDate(value) {
  return wibFields(value)?.date ?? null;
}

export function wibTime(value) {
  return wibFields(value)?.time ?? null;
}

export function wibToday(now = new Date()) {
  return wibDate(now);
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const isIsoDay = v => typeof v === 'string' && ISO_DAY.test(v);

const BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

// "30 Sep"; dengan tahun bila bukan tahun `today` ("30 Des 2025") — sama dengan bot (receipt_cmd.short_date).
export function shortDate(iso, today) {
  if (!isIsoDay(iso)) return '';
  const [y, m, d] = iso.split('-');
  const text = `${Number(d)} ${BULAN[Number(m) - 1]}`;
  return isIsoDay(today) && today.slice(0, 4) === y ? text : `${text} ${y}`;
}

// "27 Okt–26 Nov" — sama dengan bot (receipt_cmd.period_label).
export function periodLabel(start, end, today) {
  return `${shortDate(start, today)}–${shortDate(end, today)}`;
}

// Periode berjalan dari GET /analytics/periods (terlama dulu: yang berjalan paling akhir) → {start, end} atau null.
export function currentPeriod(periods) {
  const p = Array.isArray(periods) ? periods[periods.length - 1] : null;
  if (!p || !isIsoDay(p.period_start) || !isIsoDay(p.period_end)) return null;
  return { start: p.period_start, end: p.period_end };
}

// Tanggal dokumen (struk/bukti) terhadap periode anggaran berjalan, cermin app/core/period.py document_date_kind:
// null (tanpa tanggal), 'future' (sesudah hari ini), 'past' (sebelum awal periode), atau 'current'. Tanpa
// `periodStart` (periode tidak terbaca) tidak pernah 'past': form tidak bertanya, seperti dulu.
export function documentDateKind(docDate, { periodStart = null, today = null } = {}) {
  if (!isIsoDay(docDate)) return null;
  if (isIsoDay(today) && docDate > today) return 'future';
  if (isIsoDay(periodStart) && docDate < periodStart) return 'past';
  return 'current';
}

// ── Jenis dokumen ───────────────────────────────────────────────────────────

const PROOF_ROW_TYPES = new Set(['qris', 'transfer']);

// Baris dari bukti bayar (QRIS/transfer): keterangan dan saran amplop dari server, tanpa rincian barang. Tidak dikenali
// (foto buram, saklar mati) diperlakukan seperti struk belanja, sama dengan bot: nama toko atau "Belanja", saran kata kunci.
export function isProofRow(docType) {
  return PROOF_ROW_TYPES.has(docType);
}

// Kata benda di teks tanggal: "bukti" untuk QRIS/transfer, "struk" untuk lainnya (sama dengan bot).
export function docNoun(docType) {
  return docType === 'qris' || docType === 'transfer' ? 'bukti' : 'struk';
}

// `flags.blocked` dari server → alasan baris tidak bisa disimpan, untuk SEMUA jenis dokumen (saklar
// `receipt_inbox` mati: setiap bukti terbaca sebagai struk belanja). null bila tidak diblokir.
export function proofBlockReason(flags) {
  const blocked = flags?.blocked;
  if (blocked === 'transaksi_gagal') return 'Transaksi ini gagal di bank, jadi tidak bisa dicatat.';
  if (blocked === 'sudah_tercatat') return 'Bukti ini sudah tercatat.';
  return null;
}

// Hasil API scan → item baris di form multi-transaksi. `receiptItemId` (item Kotak Struk) ikut disimpan dan
// dikirim sebagai `receipt_item_id`; scan tanpa field itu (bentuk lama) berperilaku seperti dulu.
export function receiptToItem(result, key) {
  const docDate = result.date || wibDate(result.paid_at) || null;
  const item = {
    key,
    origin: 'receipt',
    scanId: result.scan_id,
    receiptItemId: result.item_id || null,
    docType: result.doc_type || null,
    description: result.merchant || 'Belanja',
    amount: Number(result.total) || 0,
    transactionDate: docDate,
    docDate,
    confidence: result.confidence,
    envelopeId: '',
    suggested: false,
    touched: false,
    error: null,
    saving: false,
    // Rincian barang (bisa kosong kalau barang tidak terbaca).
    receiptItems: toReceiptItems(result.items),
    adjustments: (result.adjustments || []).map(a => ({ ...a, amount: Number(a.amount) || 0 })),
    confidenceSource: result.confidence_source || null,
    plan: null, // rencana simpan (1 transaksi per barang); dibekukan saat pertama disimpan
    blockedReason: proofBlockReason(result.flags),
  };
  if (!isProofRow(result.doc_type)) return item;
  // Bukti: keterangan dari server; saran amplop server hanya dipilihkan bila yakin.
  const suggestion = result.suggestion;
  const confident = !!(suggestion?.confident && suggestion.envelope_id);
  return {
    ...item,
    description: result.description_preview || result.merchant || 'Belanja',
    envelopeId: confident ? suggestion.envelope_id : '',
    suggested: confident,
    receiptItems: [],
  };
}

// Aturan tanggal dokumen (sama dengan bot, Task H1; server Task B0) untuk baris dari scan dengan item Kotak Struk:
// sebelum awal periode berjalan → tanggal dikosongkan dan ditanya ("Hari ini" atau tanggal dokumen); sesudah hari
// ini (salah baca) → hari ini. Scan tanpa item Kotak Struk, bukti yang diblokir, dan periode yang tidak terbaca
// (tidak 'past') → seperti dulu.
export function applyDocumentDate(item, { period = null, today = null } = {}) {
  if (!item.receiptItemId || item.blockedReason) return item;
  const kind = documentDateKind(item.docDate, { periodStart: period?.start ?? null, today });
  if (kind === 'past') return { ...item, dateKind: kind, datePeriod: period, transactionDate: null };
  if (kind === 'future') return { ...item, dateKind: kind, transactionDate: today };
  return item;
}

// Teks tanggal untuk baris: 'past' → pertanyaan + pilihan "Hari ini" / tanggal dokumen (tetap terlihat sesudah
// dipilih, supaya bisa diganti); 'future' → keterangan, sampai user mengganti tanggalnya sendiri. null bila tidak ada.
export function dateNotice(item, today) {
  if (item.blockedReason) return null;
  const noun = docNoun(item.docType);
  const doc = shortDate(item.docDate, today);
  if (item.dateKind === 'past' && item.datePeriod) {
    return {
      kind: 'past',
      text: `Tanggal di ${noun}: ${doc} — di luar periode sekarang (${periodLabel(item.datePeriod.start, item.datePeriod.end, today)}). Catat untuk tanggal berapa?`,
      choices: [{ label: 'Hari ini', date: today }, { label: doc, date: item.docDate }],
    };
  }
  if (item.dateKind === 'future' && !item.dateEdited) {
    return { kind: 'future', text: `Tanggal di ${noun} (${doc}) belum lewat — dicatat hari ini.` };
  }
  return null;
}

function rupiah(n) {
  return 'Rp ' + Number(n).toLocaleString('id-ID');
}

const PROOF_LABEL = { qris: 'QRIS', transfer: 'transfer' };
const SKIP_WHAT = { top_up: 'top-up saldo', masuk: 'uang masuk', antar_rekening_sendiri: 'transfer ke rekening sendiri' };

const sentence = s => (/[.!?]$/.test(s) ? s : `${s}.`);

// Satu peringatan untuk pesan bukti: peringatan server dulu, lalu duplikat lunak, lalu "bukan pengeluaran?".
// Duplikat ref anggota lain sudah ada di `warnings` (server), jadi `kind: 'ref'` tidak menambah teks.
function firstProofWarning(flags) {
  const f = flags || {};
  const server = (f.warnings || []).find(w => typeof w === 'string' && w.trim());
  if (server) return sentence(server.trim());
  const soft = f.duplicate_of?.kind === 'soft' ? f.duplicate_of.transaction?.description : null;
  if (soft) return `Mirip "${soft}" yang sudah dicatat — cek dulu sebelum menyimpan.`;
  const skip = SKIP_WHAT[f.skip_suggestion];
  if (skip) return `Ini ${skip}, biasanya bukan pengeluaran.`;
  return null;
}

// Pesan ringkas setelah scan (ditampilkan di bawah form). Kuota scan sudah tidak ada.
export function scanMessage(result) {
  const blocked = proofBlockReason(result.flags);
  if (blocked) return { type: 'error', text: blocked };
  if (!result.total) {
    return { type: 'error', text: 'Total struk tidak terbaca. Isi nominalnya manual di baris struk.' };
  }
  const proofLabel = PROOF_LABEL[result.doc_type];
  if (proofLabel) {
    const name = result.merchant || result.counterparty?.name || '';
    const text = `Bukti ${proofLabel}${name ? ` ${name}` : ''} terbaca: ${rupiah(result.total)}. Pilih amplop lalu simpan.`;
    const warning = firstProofWarning(result.flags);
    return warning ? { type: 'mixed', text: `${text} ${warning}` } : { type: 'success', text };
  }
  const toko = result.merchant ? `${result.merchant} ` : '';
  const yakin = result.confidence === 'tinggi' ? '' : ` Mohon cek nominalnya (${confidenceLabel(result.confidence)}).`;
  const rec = result.reconciliation;
  const n = (result.items || []).length;
  let rincian = '';
  if (rec && n > 0 && rec.status === 'cocok') rincian = ` ${n} barang cocok dengan total.`;
  else if (rec && n > 0 && rec.status === 'selisih') rincian = ` Rincian ${n} barang selisih ${rupiah(Math.abs(rec.diff))} — cek barang yang ditandai.`;
  const ok = result.confidence === 'tinggi' && (!rec || rec.status !== 'selisih');
  return {
    type: ok ? 'success' : 'mixed',
    text: `Struk ${toko}terbaca: ${rupiah(result.total)}.${rincian}${yakin} Pilih amplop lalu simpan.`,
  };
}

// Item struk → payload feedback ke server (bahan belajar parser).
export function feedbackFor(item, saved) {
  if (!saved) return { saved: false };
  return {
    saved: true,
    total: Number(item.amount) || null,
    transaction_date: item.transactionDate || null,
    merchant: item.description || null,
  };
}
