// Rincian struk: cocokkan barang dengan total & catat per barang (logika murni, tanpa DOM).
//
// Aturan: total struk = yang benar-benar dibayar dan jadi patokan. Setiap barang
// dicatat sebagai satu transaksi di amplopnya sendiri, dan Σ nominal semua
// transaksi SELALU = total. Voucher yang melekat ke barang mengurangi barang itu;
// diskon global, pajak, dan selisih yang belum terjelaskan dibagi proporsional
// menurut nilai bersih tiap barang (pembulatan sisa terbesar).

export function itemNet(it) {
  return Math.max(0, (Number(it.amount) || 0) - (Number(it.discount) || 0));
}

function liveItems(items) {
  return (items || []).filter(it => !it.removed);
}

// Σ barang − diskon + pajak dibanding total struk.
export function reconcileItems(items, adjustments, total) {
  const live = liveItems(items);
  const adj = adjustments || [];
  const itemsTotal = live.reduce((s, it) => s + (Number(it.amount) || 0), 0);
  const discounts = live.reduce((s, it) => s + (Number(it.discount) || 0), 0)
    + adj.filter(a => a.kind === 'discount').reduce((s, a) => s + (Number(a.amount) || 0), 0);
  const charges = adj.filter(a => a.kind === 'charge').reduce((s, a) => s + (Number(a.amount) || 0), 0);
  const expected = itemsTotal - discounts + charges;
  const t = Number(total) || 0;
  const diff = t - expected;
  const status = live.length === 0 ? 'kosong' : diff === 0 ? 'cocok' : 'selisih';
  return { itemsTotal, discounts, charges, expected, total: t, diff, status };
}

export function effectiveEnvelope(item, defaultEnvelopeId) {
  return item.envelopeId || defaultEnvelopeId || '';
}

// Bagi `total` (bilangan bulat) menurut bobot; Σ hasil === total.
function largestRemainder(total, weights) {
  const sum = weights.reduce((s, w) => s + w, 0);
  const exact = weights.map(w => (total * w) / sum);
  const out = exact.map(Math.floor);
  let rest = total - out.reduce((s, v) => s + v, 0);
  const byFraction = exact
    .map((v, i) => ({ i, frac: v - Math.floor(v) }))
    .sort((a, b) => b.frac - a.frac || a.i - b.i);
  for (let k = 0; rest > 0; k = (k + 1) % byFraction.length, rest--) out[byFraction[k].i] += 1;
  return out;
}

// Bagian per barang: [{ itemId, name, envelopeId, amount }], Σ amount === total.
// Barang yang bagiannya 0 (mis. gratis karena voucher) tidak dicatat. Tanpa
// barang/nilai → seluruh total jadi satu bagian di amplop struk (itemId null).
export function splitByItem(items, total, defaultEnvelopeId) {
  const t = Math.max(0, Math.round(Number(total) || 0));
  const live = liveItems(items);
  const weights = live.map(itemNet);
  const whole = [{ itemId: null, name: null, envelopeId: defaultEnvelopeId || '', amount: t }];
  if (live.length === 0 || weights.every(w => w <= 0)) return whole;
  const amounts = largestRemainder(t, weights);
  const out = live
    .map((it, i) => ({ itemId: it.id ?? `i${i}`, name: it.name, envelopeId: effectiveEnvelope(it, defaultEnvelopeId), amount: amounts[i] }))
    .filter(p => p.amount > 0);
  // Total 0 → tetap satu bagian (validasi nominal menolaknya saat simpan).
  return out.length ? out : whole;
}

// Keterangan transaksi per barang: "Roti Tawar (Indomaret)". Nama barang di depan
// supaya daftar transaksi mudah dipindai; nama toko di belakang sebagai konteks.
export function itemDescription(merchant, name) {
  const item = String(name || '').trim() || 'Barang';
  const shop = String(merchant || '').trim().slice(0, 100);
  return (shop ? `${item} (${shop})` : item).slice(0, 500);
}

// Rencana simpan struk: 1 transaksi per barang. Dibekukan saat pertama disimpan,
// supaya percobaan ulang mengirim bagian yang sama persis (Σ tetap = total).
export function buildPlan(entry) {
  const merchant = String(entry.description || '').trim();
  return splitByItem(entry.receiptItems, entry.amount, entry.envelopeId).map((p, i) => ({
    id: `g${i}`,
    itemId: p.itemId,
    name: p.name,
    envelopeId: p.envelopeId,
    amount: p.amount,
    description: p.itemId === null
      ? (merchant || 'Belanja').slice(0, 500)
      : itemDescription(merchant, p.name),
    saved: false,
    error: null,
    raiseLimit: false,
  }));
}

// Ringkasan rencana per amplop untuk ditampilkan (urutan kemunculan pertama):
// [{ envelopeId, amount, count, savedCount, allSaved, failed[], failedAmount,
//    error, raiseLimit }]. `failed` = bagian yang belum tersimpan & punya error.
export function summarizePlan(plan) {
  const rows = [];
  const byEnv = new Map();
  for (const g of plan || []) {
    const env = g.envelopeId || '';
    if (!byEnv.has(env)) {
      const row = { envelopeId: env, amount: 0, count: 0, savedCount: 0, groups: [] };
      byEnv.set(env, row);
      rows.push(row);
    }
    const row = byEnv.get(env);
    row.amount += Number(g.amount) || 0;
    row.count += 1;
    if (g.saved) row.savedCount += 1;
    row.groups.push(g);
  }
  return rows.map(row => {
    const failed = row.groups.filter(g => !g.saved && g.error);
    return {
      ...row,
      allSaved: row.savedCount === row.count,
      failed,
      failedAmount: failed.reduce((s, g) => s + (Number(g.amount) || 0), 0),
      error: failed[0]?.error || null,
      raiseLimit: row.groups.some(g => !g.saved && g.raiseLimit),
    };
  });
}

// Hasil API → barang yang bisa diedit di kartu struk.
export function toReceiptItems(apiItems) {
  return (apiItems || []).map((it, idx) => ({
    id: `r${idx}`,
    name: it.name || 'Barang',
    qty: it.qty ?? null,
    unitPrice: it.unit_price ?? null,
    amount: Number(it.amount) || 0,
    discount: Number(it.discount) || 0,
    flag: it.flag || 'ok',
    note: it.note || null,
    suggestion: it.suggestion ?? null,
    envelopeId: '',
    removed: false,
  }));
}
