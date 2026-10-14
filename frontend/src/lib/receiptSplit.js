// Rincian struk: cocokkan barang dengan total & pecah per amplop (logika murni, tanpa DOM).
//
// Aturan: total struk = yang benar-benar dibayar dan jadi patokan. Σ nominal per
// amplop SELALU = total. Diskon/voucher yang melekat ke barang mengurangi barang
// itu; diskon global, pajak, dan selisih yang belum terjelaskan dibagi
// proporsional menurut nilai bersih tiap barang.

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

// Barang dipecah ke lebih dari satu amplop?
export function isSplit(items, defaultEnvelopeId) {
  const envs = new Set(liveItems(items).map(it => effectiveEnvelope(it, defaultEnvelopeId)));
  return envs.size > 1;
}

// Nominal per amplop: [{ envelopeId, amount, names }], Σ amount === total (pembulatan
// sisa terbesar). Tanpa barang/nilai → seluruh total ke amplop struk.
export function splitByEnvelope(items, total, defaultEnvelopeId) {
  const t = Math.max(0, Math.round(Number(total) || 0));
  const live = liveItems(items);
  const order = [];
  const groups = {};
  for (const it of live) {
    const env = effectiveEnvelope(it, defaultEnvelopeId);
    if (!groups[env]) {
      groups[env] = { envelopeId: env, weight: 0, names: [] };
      order.push(env);
    }
    groups[env].weight += itemNet(it);
    groups[env].names.push(it.name);
  }
  const weightSum = order.reduce((s, env) => s + groups[env].weight, 0);
  if (order.length === 0 || weightSum <= 0) {
    return [{ envelopeId: defaultEnvelopeId || '', amount: t, names: live.map(it => it.name) }];
  }
  // Amplop struk (default) di urutan pertama.
  order.sort((a, b) => (a === (defaultEnvelopeId || '') ? -1 : b === (defaultEnvelopeId || '') ? 1 : 0));
  const exact = order.map(env => (t * groups[env].weight) / weightSum);
  const floors = exact.map(Math.floor);
  let rest = t - floors.reduce((s, v) => s + v, 0);
  const byFraction = exact
    .map((v, i) => ({ i, frac: v - Math.floor(v) }))
    .sort((a, b) => b.frac - a.frac || a.i - b.i);
  for (let k = 0; rest > 0; k = (k + 1) % byFraction.length, rest--) floors[byFraction[k].i] += 1;
  const out = order
    .map((env, i) => ({ envelopeId: env, amount: floors[i], names: groups[env].names }))
    .filter(g => g.amount > 0);
  // Total 0 → tetap satu bagian (validasi nominal menolaknya saat simpan).
  return out.length ? out : [{ envelopeId: order[0], amount: 0, names: groups[order[0]].names }];
}

// Keterangan transaksi per amplop: "Indomaret (3 barang)". Nama barang sengaja
// tidak dimasukkan: amplop bersama menampilkan keterangan ke anggota rumah tangga.
export function groupDescription(merchant, count, { split } = {}) {
  const base = ((merchant || '').trim() || 'Belanja').slice(0, 100);
  if (!split || !count) return base;
  return `${base} (${count} barang)`;
}

// Rencana simpan struk: 1 transaksi per amplop. Dibekukan saat pertama disimpan,
// supaya percobaan ulang mengirim bagian yang sama persis (Σ tetap = total).
export function buildPlan(entry) {
  const groups = splitByEnvelope(entry.receiptItems, entry.amount, entry.envelopeId);
  const split = groups.length > 1;
  return groups.map((g, i) => ({
    id: `g${i}`,
    envelopeId: g.envelopeId,
    amount: g.amount,
    count: g.names.length,
    description: groupDescription(entry.description, g.names.length, { split }),
    saved: false,
    error: null,
    raiseLimit: false,
  }));
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
