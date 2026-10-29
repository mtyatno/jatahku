// Aturan baris form Catat (MultiAddTransaction) — logika murni tanpa DOM, supaya bisa dites dengan node --test.
//
// Baris: ketikan (origin 'text'/'held') atau hasil scan (origin 'receipt', lib/receiptScan.receiptToItem). Baris
// scan dengan item Kotak Struk membawa `receiptItemId` (dikirim sebagai `receipt_item_id` di setiap jalur simpan:
// batch, antrean offline, bagian rencana struk), `blockedReason` (blokir dari server, tidak hilang karena diedit),
// dan aturan tanggal dokumen (`dateKind`, receiptScan.applyDocumentDate).
import { buildPlan } from './receiptSplit.js';
import { docNoun, isProofRow } from './receiptScan.js';

// Ditolak karena limit harian → tawarkan "naikkan limit hari ini" (sama dengan bot).
export function isDailyLimitError(errMsg) {
  return !!errMsg && String(errMsg).toLowerCase().includes('limit harian');
}

export function isInsufficientFundsError(errMsg) {
  if (!errMsg) return false;
  const lower = String(errMsg).toLowerCase();
  return lower.includes('dana tidak cukup') || lower.includes('belum ada dana') || lower.includes('belum didanai');
}

// Struk dengan rincian barang → disimpan lewat rencana (1 transaksi per barang).
export function hasReceiptItems(item) {
  return item.origin === 'receipt' && (item.receiptItems || []).length > 0;
}

// Rencana yang dibekukan (sesudah percobaan simpan) atau dihitung dari isian sekarang.
export function receiptPlan(item) {
  return item.plan || buildPlan(item);
}

// Struk/bukti dari periode lalu yang tanggal catatnya belum dipilih ("Hari ini" atau tanggal dokumen).
export function needsDate(item) {
  return item.dateKind === 'past' && !item.transactionDate;
}

// Siap disimpan: tidak diblokir, tanggal sudah dipilih bila ditanya, dan punya amplop (struk: setiap bagian yang
// belum tersimpan punya amplop).
export function isReady(item) {
  if (item.blockedReason || needsDate(item)) return false;
  if (hasReceiptItems(item)) {
    const left = receiptPlan(item).filter(g => !g.saved);
    return left.length > 0 && left.every(g => g.envelopeId);
  }
  return !!item.envelopeId;
}

// Untuk hitungan "perlu amplop": baris yang diblokir tidak dihitung (amplopnya memang tidak bisa dipilih).
export function needsEnvelope(item) {
  if (item.blockedReason) return false;
  if (hasReceiptItems(item)) return receiptPlan(item).some(g => !g.saved && !g.envelopeId);
  return !item.envelopeId;
}

// Pesan bila tidak ada baris yang siap: semua diblokir → alasan blokirnya; ada yang menunggu tanggal → pilih
// tanggal; selain itu amplop.
export function notReadyMessage(items) {
  const open = items.filter(i => !i.blockedReason);
  if (items.length > 0 && open.length === 0) return items[0].blockedReason;
  if (open.some(needsDate)) return 'Pilih tanggal catat';
  return 'Pilih amplop untuk setiap item';
}

// Suntingan user pada satu baris: error simpan sebelumnya hilang, blokir dari server tetap. Mengganti tanggal
// sendiri menyembunyikan keterangan "dicatat hari ini" (receiptScan.dateNotice).
export function applyRowPatch(item, patch) {
  const next = { ...item, ...patch, error: null };
  if (item.blockedReason) next.blockedReason = item.blockedReason;
  if ('transactionDate' in patch) next.dateEdited = true;
  return next;
}

// Tepat sebelum disimpan: tanggal baris Kotak Struk yang sesudah hari ini jadi hari ini (aturan server B0). Form
// menggantinya sendiri karena hasil batch tidak membawa tanggal: payload, antrean offline, dan feedbackFor memakai
// tanggal yang sama dengan yang tercatat.
export function withSaveDate(item, today) {
  if (!item.receiptItemId || !item.transactionDate || !today || item.transactionDate <= today) return item;
  return { ...item, transactionDate: today };
}

export function toPayload(item) {
  return {
    envelope_id: item.envelopeId,
    amount: item.amount,
    description: (item.description || '').trim() || 'Belanja',
    source: 'webapp',
    ...(item.transactionDate ? { transaction_date: item.transactionDate } : {}),
    ...(item.raiseDailyLimit ? { raise_daily_limit: true } : {}),
    ...(item.ref ? { client_ref: item.ref } : {}),
    ...(item.receiptItemId ? { receipt_item_id: item.receiptItemId } : {}),
  };
}

// Satu entri → satu atau beberapa transaksi. Struk dengan rincian memakai rencana (1 transaksi per barang, semuanya
// dengan receipt_item_id struk itu); bagian yang sudah tersimpan tidak dikirim ulang.
export function toParts(item, plan) {
  if (plan) {
    return plan.filter(g => !g.saved).map(g => ({
      key: item.key,
      gid: g.id,
      payload: toPayload({
        ...item,
        envelopeId: g.envelopeId,
        amount: g.amount,
        description: g.description,
        raiseDailyLimit: g.raiseLimit,
        ref: g.ref,
      }),
    }));
  }
  return [{ key: item.key, gid: null, payload: toPayload(item) }];
}

// Umpan balik belajar scan struk (receiptFeedback) hanya untuk struk belanja dan scan lama tanpa jenis, sama dengan
// bot. Bukti bayar belajar di server saat tercatat (peta merchant); umpan balik struk akan mengajarinya alias salah.
export function wantsReceiptFeedback(item) {
  return item?.origin === 'receipt' && !!item.scanId && (!item.docType || item.docType === 'struk_belanja');
}

// Baris struk/bukti dihapus (×) atau sisanya dilewati: umpan balik "tidak disimpan" (struk belanja) dan item Kotak
// Struk dilewati di server dengan alasan 'batal' (seperti tombol Batal bot), supaya tidak menunggu dicatat. `rows` =
// daftar baris saat ini: selama baris/kartu lain masih memakai item (atau scan) yang sama, tidak ada yang dikirim,
// karena item yang dilewati tidak bisa dicatat lagi dari baris lain itu.
export function removalCalls(item, rows = []) {
  const others = (rows || []).filter(r => r.key !== item?.key);
  const feedback = wantsReceiptFeedback(item) && !others.some(r => r.scanId === item.scanId) ? item.scanId : null;
  const skip = item?.origin === 'receipt' && item.receiptItemId && !others.some(r => r.receiptItemId === item.receiptItemId)
    ? item.receiptItemId : null;
  return { feedback, skip };
}

// Satu item Kotak Struk = satu baris/kartu. Foto yang sama di-scan lagi (server mengembalikan item yang sama selama
// belum selesai) tidak menambah baris: pesan pengganti hasil scan, atau null bila item itu belum ada di daftar.
// `queuedIds` (Set id item di antrean offline, menunggu maupun ditolak; offlineQueue.queuedReceiptItemIds): item yang
// sudah disimpan offline juga tidak menambah baris. Simpan kedua akan mencatat struk yang sama dua kali, dan × pada
// baris itu melewati item yang simpanannya belum terkirim (simpanan itu lalu ditolak selamanya). Perbaikan dan kirim
// ulang lewat pemberitahuan antrean offline. null / tanpa Set → hanya baris di daftar.
export function alreadyListed(result, rows, queuedIds = null) {
  const id = result?.item_id;
  if (!id) return null;
  const noun = docNoun(result.doc_type) === 'bukti' ? 'Bukti' : 'Struk';
  if ((rows || []).some(r => r.receiptItemId === id)) return { type: 'mixed', text: `${noun} ini sudah ada di daftar.` };
  if (typeof queuedIds?.has === 'function' && queuedIds.has(id)) {
    return { type: 'mixed', text: `${noun} ini sudah disimpan offline dan menunggu dikirim. Cek pemberitahuan antrean offline.` };
  }
  return null;
}

// Penolakan bukti dari server saat simpan (record.MSG_*; di batch: `error` baris itu): permanen, mengulang simpan
// tidak akan berhasil.
const RECEIPT_REJECTIONS = new Set([
  'Bukti ini sudah tercatat',
  'Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya',
  'Bukti ini belum siap dicatat',
  'Bukti tidak ditemukan',
  'Transaksi gagal, tidak bisa dicatat',
]);

// Galat simpan satu baris (hasil batch) → baris. Penolakan bukti untuk baris dengan item Kotak Struk menjadi alasan
// blokir yang terlihat (bukan hanya tooltip "Gagal") dan baris tidak dikirim lagi; galat lain tetap `error` (Gagal,
// Geser, Naikkan limit, coba lagi). "Sedang diproses" bukan penolakan.
// Penolakan berlaku untuk seluruh struk: bagian rencana yang belum tersimpan tidak membawa galatnya sendiri lagi, jadi
// kartu hanya menampilkan alasannya, tanpa "Gagal: …" per amplop dan tanpa pindah amplop/Geser/Naikkan limit.
export function withSaveError(item, error) {
  const text = typeof error === 'string' ? error.trim().replace(/\.$/, '') : '';
  if (item.receiptItemId && RECEIPT_REJECTIONS.has(text)) {
    const out = { ...item, error: null, blockedReason: `${text}.` };
    if (Array.isArray(item.plan)) out.plan = item.plan.map(g => (g.saved ? g : { ...g, error: null }));
    return out;
  }
  return { ...item, error: error || null };
}

// "Ubah rincian" di kartu struk (rencana dihitung ulang): hanya rencana yang sudah dibekukan, tanpa bagian yang
// tersimpan, tanpa hasil simpan yang belum pasti, dan bukan kartu yang diblokir server (isiannya tetap terkunci).
export function canUnlockPlan(item) {
  return Array.isArray(item?.plan) && !item.uncertain && !item.blockedReason && !item.plan.some(g => g.saved);
}

// Saran kata kunci (suggest-envelopes) hanya untuk baris yang tidak membawa saran server: QRIS dan transfer sudah memakai
// saran Kotak Struk (peta merchant + kata kunci), jadi tidak ditimpa. Tidak dikenali seperti struk belanja (sama dengan
// bot): saran kata kunci dari nama tokonya.
export function wantsKeywordSuggestion(item) {
  return !isProofRow(item.docType);
}

// Baris Kotak Struk yang dicatat di tanggal sebelum awal periode berjalan: server melewati blok dana dan limit
// harian (B0), jadi form tidak menawarkan Geser atau "limit ↑" dari dugaannya sendiri. Galat dana/limit yang tetap
// dijawab server (gajian berubah, sinkron offline sesudah gajian) ditampilkan seperti biasa.
export function pastDated(item, periodStart) {
  return !!(item.receiptItemId && item.transactionDate && periodStart && item.transactionDate < periodStart);
}

// Amplop yang ditawarkan "Geser / Isi Dana" di pesan dana kurang: baris yang memang ditolak karena dana, lalu
// baris lain yang punya amplop — tapi bukan baris bertanggal periode lalu.
export function fundCandidate(items, periodStart) {
  return items.find(i => isInsufficientFundsError(i.error))
    || items.find(i => i.envelopeId && !pastDated(i, periodStart))
    || null;
}

// Tanda "limit ↑" (limit harian dinaikkan saat disimpan): tidak untuk baris bertanggal periode lalu, karena server
// tidak menaikkan limit untuk baris itu.
export function showRaisedLimit(item, periodStart) {
  return !!item.raiseDailyLimit && !item.error && !pastDated(item, periodStart);
}
