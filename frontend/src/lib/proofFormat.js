// Aturan kartu konfirmasi bukti (ProofCard) — logika murni tanpa DOM, supaya bisa dites dengan node --test.
//
// Kartu menampilkan satu item Kotak Struk (`GET /kotak-struk/{id}`, docs/kotak-struk.md bagian API) dari jenis apa
// pun: QRIS, transfer, struk belanja, dan tidak dikenali (kotak "Bukti menunggu" memuat semuanya). Satu kartu = satu
// transaksi untuk total dokumen; rincian per barang tetap di form Catat. Tanggal dan jam selalu WIB (receiptScan
// wibDate/wibTime: `paid_at` dari server berbentuk UTC). Aturan tanggal dokumen sama dengan form Catat dan bot
// (receiptScan.documentDateKind/dateNotice, server Task B0).
import {
  wibDate, wibTime, wibToday, shortDate, documentDateKind, dateNotice, isProofRow, proofBlockReason, confidenceLabel,
} from './receiptScan.js';
import { isDailyLimitError, isInsufficientFundsError, queuedText } from './multiAddRows.js';

export const ISSUER_LABEL = {
  bca_mobile: 'BCA mobile', livin: "Livin' by Mandiri", brimo: 'BRImo', bni: 'wondr by BNI', bsi: 'BSI', jago: 'Jago',
  seabank: 'SeaBank', blu: 'blu', gopay: 'GoPay', ovo: 'OVO', dana: 'DANA', shopeepay: 'ShopeePay',
};

const KIND_LABEL = { qris: 'QRIS', transfer: 'Transfer', struk_belanja: 'Struk belanja', tidak_dikenali: 'Bukti bayar' };

const STATUS = {
  berhasil: { statusText: 'Berhasil', statusTone: 'success' },
  pending: { statusText: 'Pending', statusTone: 'warning' },
  gagal: { statusText: 'Gagal', statusTone: 'danger' },
};
const NO_STATUS = { statusText: '', statusTone: 'muted' };

const SKIP_TEXT = {
  top_up: 'Ini top-up saldo, biasanya bukan pengeluaran.',
  masuk: 'Ini uang masuk, biasanya bukan pengeluaran.',
  antar_rekening_sendiri: 'Sepertinya transfer ke rekeningmu sendiri.',
};

// Singkatan yang tetap huruf besar (server merchants.ACRONYMS) saat teks huruf besar semua dirapikan.
const ACRONYMS = new Set(['PT', 'CV', 'UD', 'TB', 'SPBU', 'BRI', 'BCA', 'BNI', 'BSI', 'BTN', 'QRIS', 'RS', 'RSUD']);

const DOUBTFUL_TOTAL = new Set(['rendah', 'gagal']);

// Jenis dokumen item: kolom item, atau dari dokumennya (dokumen dan kolom sama; kolom ada sebelum dokumen terbaca).
function docTypeOf(item) {
  return item?.doc_type || item?.document?.doc_type || null;
}

// Cermin server merchants.display_name: huruf besar semua → kapital awal per kata (singkatan tetap); teks campuran
// dibiarkan. Spasi dirapatkan. Dipakai untuk kota ("BANDUNG" → "Bandung"), sama dengan pesan bot.
function displayCase(raw) {
  const s = String(raw ?? '').split(/\s+/).filter(Boolean).join(' ');
  if (!/\p{Lu}/u.test(s) || /\p{Ll}/u.test(s)) return s;
  return s.replace(/\p{L}+/gu, w => (ACRONYMS.has(w) ? w : w.charAt(0) + w.slice(1).toLowerCase()));
}

// Nama yang tampil untuk merchant: nama panggilan rumah tangga, lalu nama dari bukti (sudah dirapikan server).
export function displayNameOf(merchant) {
  return (merchant?.display_name || merchant?.name || '').trim();
}

// Badge jenis (+ penerbit untuk QRIS/transfer) dan status pembayaran dari dokumen.
export function proofHeader(item) {
  const doc = item?.document || {};
  const type = docTypeOf(item);
  const kind = KIND_LABEL[type] || 'Bukti bayar';
  const issuer = isProofRow(type) ? ISSUER_LABEL[doc.issuer] : null;
  return { badge: issuer ? `${kind} · ${issuer}` : kind, ...(STATUS[doc.status] || NO_STATUS) };
}

// "26 Okt 2026, 08.12 · Bandung" (WIB). Struk belanja dan tidak dikenali tanpa jam: tanggalnya tengah malam WIB.
export function paidLabel(item) {
  const parts = [];
  const date = wibDate(item?.paid_at);
  if (date) {
    const time = isProofRow(docTypeOf(item)) ? wibTime(item.paid_at) : null;
    parts.push(time ? `${shortDate(date)}, ${time}` : shortDate(date));
  }
  const city = displayCase(item?.document?.counterparty?.city);
  if (city) parts.push(city);
  return parts.join(' · ');
}

// Peringatan kartu, berurutan: blokir (danger; `blockedReason` = penolakan 409 yang diterima kartu, menggantikan
// blokir dari server), arah uang, duplikat lunak (teks kartu, jam WIB), lalu peringatan server apa adanya (sudah
// memuat "Bukti ini juga dibagikan {nama}"; duplikat ref yang belum tercatat tidak menambah teks).
export function proofWarnings(item, { blockedReason = null } = {}) {
  const flags = item?.flags || {};
  const out = [];
  const blocked = blockedReason || proofBlockReason(flags);
  if (blocked) out.push({ tone: 'danger', text: blocked });
  const skip = SKIP_TEXT[flags.skip_suggestion];
  if (skip) out.push({ tone: 'warning', text: skip });
  if (flags.duplicate_of?.kind === 'soft') {
    const txn = flags.duplicate_of.transaction || {};
    const what = txn.description ? `"${txn.description}"` : 'transaksi';
    out.push({ tone: 'warning', text: `Mirip ${what} yang dicatat ${wibTime(txn.created_at) || 'tadi'}. Sudah dicatat?` });
  }
  for (const w of flags.warnings || []) {
    if (typeof w === 'string' && w.trim()) out.push({ tone: 'warning', text: w.trim() });
  }
  return out;
}

// Total dokumen (rupiah bulat > 0) atau null.
export function proofTotal(item) {
  const n = Number(item?.document?.amounts?.total);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : null;
}

// Nominal boleh diubah di kartu (lalu nominal ubahan yang dikirim): tanpa total, keyakinan total rendah/gagal, atau
// bukan QRIS/transfer (struk belanja, tidak dikenali). QRIS/transfer yang terbaca yakin hanya ditampilkan.
export function amountEditable(item) {
  if (!proofTotal(item) || !isProofRow(docTypeOf(item))) return true;
  return DOUBTFUL_TOTAL.has(item?.document?.confidence?.total);
}

// Label keyakinan di atas isian nominal (teks yang sama dengan baris struk form Catat): tanpa total → "total tidak
// terbaca"; keyakinan selain tinggi → labelnya. Kosong bila nominal hanya dibaca.
export function amountHint(item) {
  if (!amountEditable(item)) return '';
  if (!proofTotal(item)) return confidenceLabel('gagal');
  const conf = item?.document?.confidence?.total;
  return conf && conf !== 'tinggi' ? confidenceLabel(conf) : '';
}

// Isian nominal → rupiah bulat > 0, atau null. Boleh awalan Rp/IDR dan pemisah ribuan titik, koma, atau spasi
// ("25.000", "25,000", "25 000"). Pecahan ("25.5", "25.000,00") ditolak: lebih aman diisi ulang daripada ditebak.
export function parseAmountInput(text) {
  const s = String(text ?? '').replace(/^\s*(?:rp|idr)\.?/i, '').replace(/\s+/g, '');
  if (!/^(?:\d+|\d{1,3}(?:\.\d{3})+|\d{1,3}(?:,\d{3})+)$/.test(s)) return null;
  const n = Number(s.replace(/[.,]/g, ''));
  return Number.isSafeInteger(n) && n > 0 ? n : null;
}

// Isi kolom nominal: ketikan user bila sudah disentuh (teks, juga kosong), selain itu total dokumen terbaru, supaya item
// yang baru terbaca sesudah kartu dipasang (diterima/diproses → siap, id sama) tetap terisi totalnya.
export function amountFieldText(item, amountText) {
  return typeof amountText === 'string' ? amountText : String(proofTotal(item) || '');
}

// Nominal yang dicatat: isian kartu bila nominal boleh diubah dan isiannya ada, selain itu total dokumen.
export function saveAmount(item, amountText) {
  if (!amountEditable(item) || amountText === undefined || amountText === null) return proofTotal(item);
  return parseAmountInput(amountText);
}

// Tanggal catat dari tanggal dokumen (WIB dari `paid_at`) terhadap periode berjalan, aturan yang sama dengan baris
// form Catat: 'past' (sebelum awal periode) → pertanyaan dan pilihan "Hari ini" / tanggal dokumen, tanggal kosong
// sampai dipilih (`dateChoice` 'today' | 'doc'; "Hari ini" dibaca saat itu juga); 'future' (salah baca) → hari ini
// dengan keterangan; 'current' → tanggal dokumen; tanpa `paid_at` → tanpa tanggal (server: hari ini). Periode belum
// terbaca → tidak pernah 'past'. Bukti yang diblokir tidak ditanya.
export function proofDate(item, { period = null, today = wibToday(), dateChoice = null, blockedReason = null } = {}) {
  const docDate = wibDate(item?.paid_at);
  const kind = documentDateKind(docDate, { periodStart: period?.start ?? null, today });
  const notice = dateNotice({
    docType: docTypeOf(item), docDate, dateKind: kind, datePeriod: period,
    blockedReason: blockedReason || proofBlockReason(item?.flags),
  }, today);
  let date = docDate;
  if (kind === 'future') date = today;
  else if (kind === 'past') date = dateChoice === 'today' ? today : dateChoice === 'doc' ? docDate : null;
  const choices = (notice?.choices || []).map(c => {
    const key = c.date === today ? 'today' : 'doc';
    return { key, label: c.label, date: c.date, picked: key === dateChoice };
  });
  return { kind, docDate, date, notice, choices };
}

// Keterangan transaksi, aturan server compose_description: tanpa catatan QRIS `{nama} (QRIS)`, transfer
// `Transfer ke {nama}`; dengan catatan `{catatan} ({nama})`. Struk belanja dan tidak dikenali tanpa catatan: nama
// toko atau "Belanja" (sama dengan form Catat dan bot). `preview` = keterangan terakhir dari server
// ({note, name, text}; bawaan: `description_preview` item tanpa catatan) dipakai bila catatan dan namanya masih sama;
// selain itu (saran belum kembali, gagal, nama baru lewat Ubah nama) disusun di sini, supaya catatan tidak hilang.
export function descriptionFor(item, { note = '', preview, merchant = item?.merchant } = {}) {
  const n = String(note ?? '').trim();
  const name = displayNameOf(merchant);
  const type = docTypeOf(item);
  const withName = text => (name ? `${text} (${name})` : text);
  if (!isProofRow(type)) return n ? withName(n) : (name || 'Belanja');
  const p = preview === undefined
    ? { note: '', name: displayNameOf(item?.merchant), text: item?.description_preview }
    : preview;
  if (p?.text && p.note === n && p.name === name) return p.text;
  if (n) return withName(n);
  if (type === 'qris') return name ? `${name} (QRIS)` : 'Pembayaran QRIS';
  return name ? `Transfer ke ${name}` : 'Transfer';
}

// Pilihan amplop: daftar yang sama dengan form Catat dan bot (aktif, terlihat, bukan tabungan/sinking fund). Amplop
// yang disarankan paling depan (`first`: id saran awal, supaya urutan tidak berubah saat saran diperbarui);
// `suggested` (label "disarankan") hanya untuk saran yang yakin.
export function envelopeChoices(envelopes, suggestion, { first = suggestion?.envelope_id } = {}) {
  const list = (Array.isArray(envelopes) ? envelopes : []).filter(e => e?.id && e.is_active !== false
    && e.purpose !== 'saving' && e.purpose !== 'sinking_fund');
  const ordered = first ? [...list.filter(e => e.id === first), ...list.filter(e => e.id !== first)] : list;
  const sure = suggestion?.confident ? suggestion.envelope_id : null;
  return ordered.map(e => ({ id: e.id, name: e.name, emoji: e.emoji, suggested: !!sure && e.id === sure }));
}

// Amplop yang terpilih: pilihan user (selama masih ada di daftar), selain itu saran yang yakin bila ada di daftar.
export function effectiveEnvelope(choices, { picked = null, suggestion = null } = {}) {
  const ids = new Set((choices || []).map(c => c.id));
  if (picked) return ids.has(picked) ? picked : '';
  const sure = suggestion?.confident ? suggestion.envelope_id : null;
  return sure && ids.has(sure) ? sure : '';
}

const SKIP_SAME = { label: 'Sama, lewati', reason: 'duplikat' };
const SKIP_NOT_EXPENSE = { label: 'Bukan pengeluaran', reason: 'bukan_pengeluaran' };

// Tombol lewati (`kotakSkip(id, reason)`): "Bukan pengeluaran" selalu; "Sama, lewati" untuk duplikat lunak, dan satu-
// satunya untuk bukti yang sudah tercatat (supaya tidak menunggu di kotak sampai kedaluwarsa). Tidak ada sesudah
// kartu menerima penolakan 409 (bukti itu sudah tercatat / kedaluwarsa / dilewati di tempat lain), dan tidak untuk item
// yang simpanannya di antrean offline (`queued`: melewatinya membuat simpanan antrean itu ditolak selamanya).
export function skipActions(item, { blockedReason = null, queued = false } = {}) {
  if (queued || blockedReason || item?.status !== 'siap') return [];
  const flags = item.flags || {};
  if (flags.blocked === 'sudah_tercatat') return [SKIP_SAME];
  if (!flags.blocked && flags.duplicate_of?.kind === 'soft') return [SKIP_SAME, SKIP_NOT_EXPENSE];
  return [SKIP_NOT_EXPENSE];
}

const no = reason => ({ ok: false, reason });

// Status yang sudah selesai (item disegarkan induk sesudah dicatat/dilewati/kedaluwarsa di tempat lain). Struk belanja
// yang tercatat tidak membawa `blocked` (boleh dicatat lagi per barang di form Catat), jadi alasannya dari status.
const DONE_REASON = {
  tercatat: 'Bukti ini sudah tercatat.',
  dilewati: 'Bukti ini sudah dilewati.',
  kedaluwarsa: 'Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya.',
};

// Boleh disimpan sekarang? Alasan pertama yang menghalangi, urut dari atas kartu: blokir, belum siap (status selesai
// dengan alasannya sendiri), simpanan di antrean offline (`form.queued`: struk dari form Catat yang disimpan offline,
// menunggu atau ditolak; kirim ulangnya lewat pemberitahuan antrean), nominal, tanggal, amplop, lalu koneksi (kartu
// tidak punya antrean offline).
export function canSave(item, form = {}) {
  const blocked = form.blockedReason || proofBlockReason(item?.flags);
  if (blocked) return no(blocked);
  if (item?.status !== 'siap') return no(DONE_REASON[item?.status] || 'Bukti belum siap');
  if (form.queued) return no(queuedText(docTypeOf(item)));
  if (!(saveAmount(item, form.amountText) > 0)) return no('Nominal tidak terbaca');
  const { kind, date } = proofDate(item, form);
  if (kind === 'past' && !date) return no('Pilih tanggal catat');
  if (!form.envelopeId) return no('Pilih amplop dulu');
  if (form.online === false) return no('Butuh koneksi internet');
  return { ok: true, reason: null };
}

// Kartu tanpa isian dan tombol → null (kartu biasa) atau { text, tone: 'danger' | 'warning' | 'muted', queued }:
// item yang belum siap atau sudah selesai (badge + alasan seperti sebelumnya; gagal: pesan `error` item), dan item siap
// yang simpanannya masih di antrean offline (`form.queued`: tanpa Simpan dan tanpa tombol lewati). Alasannya dari
// canSave; merah bila diblokir atau gagal.
export function readOnlyNotice(item, form = {}) {
  const queued = item?.status === 'siap' && !!form.queued;
  if (item?.status === 'siap' && !queued) return null;
  const blocked = form.blockedReason || proofBlockReason(item?.flags);
  const failed = item?.status === 'gagal';
  const text = failed && item.error ? item.error : canSave(item, form).reason;
  const tone = blocked || failed ? 'danger' : queued ? 'warning' : 'muted';
  return { text, tone, queued };
}

// Cek ulang tepat sebelum kartu menyimpan: hanya struk belanja. Server mengizinkan beberapa transaksi per struk (dicatat
// per barang di form Catat), jadi tab/HP lain atau antrean offline bisa mencatatnya lagi; jenis lain mengandalkan klaim
// eksklusif server (409 "Bukti ini sudah tercatat.").
export function needsRecheck(item) {
  return docTypeOf(item) === 'struk_belanja';
}

// Detail terbaru dari cek ulang (api.kotakItem; null bila gagal atau lewat batas waktu) → null (simpan seperti biasa,
// server yang menilai; struk yang kedaluwarsa tetap boleh dicatat) atau hasil seperti saveOutcome: tercatat → blocked
// "Struk ini sudah tercatat."; dilewati → blocked dengan alasan status selesai kartu; tidak terbaca → galat koneksi
// kartu, tidak ada yang dikirim (`resend`: kiriman sebelumnya belum pasti → tetap belum pasti, isian tetap dikunci).
export function recheckOutcome(fresh, { resend = false } = {}) {
  if (!fresh) return { kind: resend ? 'uncertain' : 'error', text: MSG_CONNECTION };
  if (fresh.status === 'tercatat') return { kind: 'blocked', text: 'Struk ini sudah tercatat.' };
  if (fresh.status === 'dilewati') return { kind: 'blocked', text: DONE_REASON.dilewati };
  return null;
}

// Body `POST /transactions/` untuk isian kartu (`form` sama dengan canSave): nominal ubahan bila boleh diubah,
// tanggal catat (WIB, pilihan tanggal, masa depan → hari ini), `receipt_item_id`, dan `client_ref` (satu per kartu).
export function savePayload(item, form = {}) {
  const { date } = proofDate(item, form);
  return {
    envelope_id: form.envelopeId,
    amount: saveAmount(item, form.amountText),
    description: form.description ?? descriptionFor(item, form),
    source: 'webapp',
    ...(date ? { transaction_date: date } : {}),
    receipt_item_id: item.id,
    client_ref: form.ref,
    ...(form.raiseLimit ? { raise_daily_limit: true } : {}),
  };
}

const MSG_CONNECTION = 'Koneksi terputus. Coba lagi — tidak akan tercatat dua kali.';
const RESEND = 'Tekan Simpan lagi — tidak akan tercatat dua kali.';

const detailOf = res => (typeof res?.data?.detail === 'string' ? res.data.detail.trim() : '');
const sentence = s => (s ? `${s.replace(/\.$/, '')}.` : '');

// Hasil `api.createTransaction` (null bila melempar: jaringan) → apa yang dilakukan kartu:
// saved | uncertain (bisa jadi sudah tercatat: kirim ulang payload yang SAMA, isian dikunci) | blocked (409: bukti
// sudah tercatat, kedaluwarsa, belum siap, gagal → alasan blokir kartu) | limit (tawarkan naikkan limit) |
// funds (pilih amplop lain) | error.
export function saveOutcome(res) {
  if (res?.ok) return { kind: 'saved', transaction: res.data || {}, quotaNotice: res.data?.quota_notice || null };
  if (!res?.status) return { kind: 'uncertain', text: MSG_CONNECTION };
  const detail = detailOf(res);
  if (res.status >= 500 || (res.status === 409 && /sedang diproses/i.test(detail))) {
    return { kind: 'uncertain', text: detail ? `${detail} ${RESEND}` : `Hasil simpan belum pasti. ${RESEND}` };
  }
  if (res.status === 409) return { kind: 'blocked', text: sentence(detail) || 'Bukti ini tidak bisa dicatat.' };
  if (isDailyLimitError(detail)) return { kind: 'limit', text: detail };
  if (isInsufficientFundsError(detail)) return { kind: 'funds', text: detail };
  return { kind: 'error', text: detail || 'Gagal menyimpan. Coba lagi.' };
}

// Hasil `api.kotakSkip` → skipped | blocked (409/404: alasan blokir kartu) | error (kartu tetap, bisa dicoba lagi).
export function skipOutcome(res) {
  if (res?.ok) return { kind: 'skipped', item: res.data || null };
  const detail = detailOf(res);
  if (res?.status === 409 || res?.status === 404) return { kind: 'blocked', text: sentence(detail) || 'Bukti ini tidak bisa dilewati.' };
  return { kind: 'error', text: detail || 'Koneksi gagal, coba lagi' };
}

// Satu permintaan bersama untuk banyak kartu (mis. periode berjalan): panggilan bersamaan memakai janji yang sama,
// hasil disimpan `ttlMs`; gagal (melempar) atau null tidak disimpan, panggilan berikutnya mencoba lagi. Tidak
// pernah menolak: gagal → null.
export function createSharedLoader(load, { ttlMs = 60_000, now = () => Date.now() } = {}) {
  let entry = null;
  return function get() {
    const t = now();
    if (entry && (entry.pending || t - entry.at < ttlMs)) return entry.promise;
    const current = { at: t, pending: true, promise: null };
    current.promise = Promise.resolve()
      .then(load)
      .catch(() => null)
      .then(value => {
        current.pending = false;
        if (value == null && entry === current) entry = null;
        return value ?? null;
      });
    entry = current;
    return current.promise;
  };
}

const countOf = v => (Number.isSafeInteger(v) && v > 0 ? v : 0);

// Teks banner "bukti menunggu" (PendingProofsBanner di Layout): `unsent` = bukti yang dibagikan tapi belum terkirim
// (kotak share lokal), `ready` = item siap yang menunggu dicatat (server). Keduanya 0 → null (banner tidak tampil).
// Kata sesudah " · " adalah tindakannya: Kirim bila hanya ada yang belum terkirim, selain itu Tinjau.
export function pendingBannerText({ unsent = 0, ready = 0 } = {}) {
  const u = countOf(unsent);
  const r = countOf(ready);
  if (u && r) return `${u} bukti menunggu dikirim, ${r} menunggu dicatat · Tinjau`;
  if (u) return `${u} bukti menunggu dikirim · Kirim`;
  if (r) return `${r} bukti menunggu dicatat · Tinjau`;
  return null;
}
