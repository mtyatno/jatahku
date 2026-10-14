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

// Hasil API scan → item baris di form multi-transaksi.
export function receiptToItem(result, key) {
  return {
    key,
    origin: 'receipt',
    scanId: result.scan_id,
    description: result.merchant || 'Belanja',
    amount: Number(result.total) || 0,
    transactionDate: result.date || null,
    confidence: result.confidence,
    envelopeId: '',
    suggested: false,
    touched: false,
    error: null,
    saving: false,
    // Rincian barang (bisa kosong kalau barang tidak terbaca).
    receiptItems: toReceiptItems(result.items),
    adjustments: (result.adjustments || []).map(a => ({ ...a, amount: Number(a.amount) || 0 })),
    savedGroups: {},
    groupErrors: {},
    raiseLimitEnvs: {},
  };
}

function rupiah(n) {
  return 'Rp ' + Number(n).toLocaleString('id-ID');
}

// Pesan ringkas setelah scan (ditampilkan di bawah form).
export function scanMessage(result) {
  const quota = result.quota || {};
  const sisa = quota.limit != null ? ` Sisa scan bulan ini: ${quota.remaining} dari ${quota.limit}.` : '';
  if (!result.total) {
    return { type: 'error', text: `Total struk tidak terbaca. Isi nominalnya manual di baris struk.${sisa}` };
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
    text: `Struk ${toko}terbaca: ${rupiah(result.total)}.${rincian}${yakin} Pilih amplop lalu simpan.${sisa}`,
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
