// Kartu AI Advisor Beranda (S7): pembantu murni di atas `advisor` dari GET /advisor/dashboard
// (04-kontrak-api.md). Urutan, batas 3 item, "+N saran lain", dan badge sudah diputuskan server
// (select.py, 02-aturan.md §7); teks insight dari render.py. Di sini hanya memilih yang tampil
// dan menyusun label tombol (aturan kerja #2 & #4).

// Pilihan dismiss §9, urutan tampil di Rincian. "Nanti" juga tombol cepat di tiap item.
export const DISMISS_LABEL = {
  nanti: 'Nanti',
  periode: 'Sembunyikan periode ini',
  tidak_relevan: 'Tidak relevan',
};

export const dismissKey = (insight) => insight?.dismiss?.kunci || null;

// Pilihan dismiss yang sudah jadi CTA insight itu sendiri (mis. INC-01 "Ingatkan besok" = nanti).
const dismissInActions = (insight) => new Set((insight?.aksi || [])
  .filter(a => a && a.kind === 'dismiss')
  .map(a => a.payload?.pilihan || 'nanti'));

// Pilihan yang ditawarkan server untuk insight ini (default: ketiganya), tanpa yang sudah
// tampil sebagai CTA supaya tidak ada dua tombol dengan efek sama.
export function dismissOptions(insight) {
  if (!dismissKey(insight)) return [];
  const raw = Array.isArray(insight.dismiss.pilihan) ? insight.dismiss.pilihan : Object.keys(DISMISS_LABEL);
  const taken = dismissInActions(insight);
  return raw.filter(p => DISMISS_LABEL[p] && !taken.has(p)).map(p => ({ pilihan: p, label: DISMISS_LABEL[p] }));
}

// "N disembunyikan" di kartu: `advisor.disembunyikan` dari server, tanpa yang baru saja
// dimunculkan lagi (sebelum muatan ulang tiba).
const HIDDEN_UNTIL = { nanti: 'sampai pukul 05.00', periode: 'sampai akhir periode', tidak_relevan: 'tidak relevan' };
export function hiddenList(advisor, restored = []) {
  const back = new Set(restored);
  return (Array.isArray(advisor?.disembunyikan) ? advisor.disembunyikan : [])
    .filter(d => d && d.kunci && !back.has(d.kunci))
    .map(d => ({ kunci: d.kunci, judul: d.judul_pendek || d.kunci, sampai: HIDDEN_UNTIL[d.pilihan] || HIDDEN_UNTIL.nanti }));
}

// Item yang tampil, tanpa yang baru saja disembunyikan (sebelum muatan ulang tiba).
export function visibleItems(advisor, hidden = []) {
  const items = Array.isArray(advisor?.items) ? advisor.items : [];
  const off = new Set(hidden);
  return items.filter(it => !off.has(dismissKey(it)) && !off.has(it.id));
}

// Badge = semua item (tampil + sisa) dikurangi yang baru disembunyikan.
export function badgeCount(advisor, hidden = []) {
  const items = Array.isArray(advisor?.items) ? advisor.items : [];
  const total = Number(advisor?.total);
  const base = Number.isFinite(total) ? total : items.length + (advisor?.sisa?.length || 0);
  return Math.max(0, base - (items.length - visibleItems(advisor, hidden).length));
}

// "+N saran lain: {judul pendek}" (§7 langkah 4). Paling banyak 2 judul disebut.
export function overflowLabel(sisa) {
  const list = (Array.isArray(sisa) ? sisa : []).filter(s => s && s.judul_pendek);
  if (list.length === 0) return '';
  const names = list.slice(0, 2).map(s => s.judul_pendek).join(' · ');
  const more = list.length > 2 ? ` · +${list.length - 2}` : '';
  return `+${list.length} saran lain: ${names}${more}`;
}

// CTA utama = aksi pertama (urutan dari server).
export const primaryAction = (insight) => (insight?.aksi || [])[0] || null;

// Pertanyaan yang pasti dijawab bot (intent yang sama dengan chip ChatPanel), pengisi bila
// insight yang menyala tidak membawa pertanyaan sendiri.
const INTENT_CHIPS = [
  { label: 'Kapan habis?', text: 'kapan habis' },
  { label: 'Limit harian', text: 'limit harian' },
  { label: 'Sisa jatah', text: 'sisa' },
  { label: 'Pengeluaran hari ini', text: 'pengeluaran hari ini' },
];

// Chip "Tanya AI Advisor" (§6H CHAT): 3–4 pertanyaan dari insight yang menyala (payload aksi
// `chat` dari render.py: daftar dulu, lalu chip KPI), dilengkapi intent tetap sampai `max`.
export function askChips(dash, max = 4) {
  const out = [];
  const seen = new Set();
  const add = (label, text) => {
    const t = String(text || '').trim();
    const key = t.toLowerCase();
    if (!t || seen.has(key) || out.length >= max) return;
    seen.add(key);
    out.push({ label: String(label || t).trim(), text: t });
  };
  const adv = dash?.advisor || {};
  const sources = [
    ...(adv.items || []),
    ...Object.values(dash?.kpi || {}),
    adv.aman,
  ].filter(Boolean);
  sources.forEach(ins => (ins.aksi || [])
    .filter(a => a && a.kind === 'chat' && a.payload?.teks)
    .forEach(a => add(a.payload.teks, a.payload.teks)));
  INTENT_CHIPS.forEach(c => add(c.label, c.text));
  return out;
}

// Aksi `chat` untuk satu chip: kirim langsung, chip lain tetap tampil di chat.
export function askAction(chips, chip) {
  return {
    kind: 'chat',
    payload: chip
      ? { teks: chip.text, kirim: true, chip: chips.filter(c => c.text !== chip.text) }
      : { chip: chips },
  };
}
