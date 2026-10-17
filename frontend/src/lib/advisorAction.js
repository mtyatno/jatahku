// Pipa CTA AI Advisor (S8): bentuk event `jatahku:open-action`, rute aman,
// query halaman, dan hitungan lembar rencana. Murni (tanpa DOM/React) supaya
// bisa dites dengan node --test. Kontrak: docs/ai-advisor/04-kontrak-api.md.

// Aksi FAB lama: event masih boleh membawa string ini saja.
export const LEGACY_ACTIONS = ['expense', 'envelope', 'income', 'langganan', 'balance', 'chat'];

export const ACTION_KINDS = [
  'plan', 'fund', 'pay', 'mark_paid', 'income', 'daily_limit', 'raise_budget', 'make_recurring',
  'route', 'chat', 'dismiss', 'undismiss', 'delete_txn', 'not_duplicate',
];

// Detail event → { kind, payload } atau null. String lama dipetakan ke kind
// yang sama dengan payload kosong; objek tanpa kind yang dikenal diabaikan.
export function normalizeAction(detail) {
  if (typeof detail === 'string') {
    if (LEGACY_ACTIONS.includes(detail)) return { kind: detail, payload: {} };
    return ACTION_KINDS.includes(detail) ? { kind: detail, payload: {} } : null;
  }
  if (!detail || typeof detail !== 'object') return null;
  const { kind } = detail;
  if (!LEGACY_ACTIONS.includes(kind) && !ACTION_KINDS.includes(kind)) return null;
  const payload = detail.payload && typeof detail.payload === 'object' ? detail.payload : {};
  return typeof detail.label === 'string' && detail.label ? { kind, payload, label: detail.label } : { kind, payload };
}

// Toast sesudah menyembunyikan (§9), dengan tombol Urungkan (#91).
const DISMISS_NOTICE = {
  nanti: 'Disembunyikan sampai besok 05.00',
  periode: 'Disembunyikan sampai akhir periode',
  tidak_relevan: 'Ditandai tidak relevan',
};
export const dismissNotice = (kind, pilihan) =>
  (kind === 'not_duplicate' ? 'Ditandai bukan dobel' : DISMISS_NOTICE[pilihan] || DISMISS_NOTICE.nanti);

export function openAction(detail) {
  window.dispatchEvent(new CustomEvent('jatahku:open-action', { detail }));
}

// Halaman SPA yang boleh dituju aksi `route`. Hanya path relatif dalam app.
const ROUTE_PATHS = ['/', '/envelopes', '/transactions', '/allocate', '/langganan', '/analytics', '/settings', '/upgrade'];

export function safeRoute(path) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) return null;
  let u;
  try { u = new URL(path, 'https://jatahku.invalid'); } catch { return null; }
  if (u.origin !== 'https://jatahku.invalid') return null;
  const p = u.pathname.length > 1 ? u.pathname.replace(/\/+$/, '') : u.pathname;
  return ROUTE_PATHS.includes(p) ? p + u.search : null;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
export const isIsoDate = s => typeof s === 'string' && ISO_DATE.test(s) && !Number.isNaN(Date.parse(`${s}T00:00:00Z`));

// /transactions?date=YYYY-MM-DD&envelope=<id>
export function parseTransactionsQuery(search) {
  const q = new URLSearchParams(search || '');
  const date = q.get('date');
  return { envelope: q.get('envelope') || null, date: isIsoDate(date) ? date : null };
}

// Indeks periode yang memuat tanggal itu (period_start ≤ date ≤ period_end), atau null.
export function periodIndexFor(periods, date) {
  if (!date || !Array.isArray(periods)) return null;
  const i = periods.findIndex(p => p.period_start <= date && date <= p.period_end);
  return i >= 0 ? i : null;
}

const posInt = v => {
  const n = Math.round(Number(v));
  return Number.isFinite(n) && n > 0 ? n : null;
};

// /allocate?new=1&amount=…&source=…
export function parseAllocateQuery(search) {
  const q = new URLSearchParams(search || '');
  return {
    open: q.get('new') === '1',
    amount: posInt(q.get('amount')),
    source: (q.get('source') || '').trim().slice(0, 100) || null,
  };
}

// Prefill modal pemasukan dari payload aksi `income`.
export function incomePrefill(payload = {}) {
  const amount = posInt(payload.jumlah ?? payload.amount);
  return {
    amount: amount ? String(amount) : '',
    source: String(payload.sumber ?? payload.source ?? '').trim() || 'Gaji',
    envelopeId: payload.amplop_id ?? payload.envelope_id ?? null,
  };
}

// Prefill RecurringModal (mode buat) dari payload aksi `make_recurring`.
const FREQS = ['weekly', 'monthly', 'yearly'];
export function recurringPrefill(payload = {}) {
  const amount = posInt(payload.jumlah ?? payload.amount);
  const next = payload.next_run ?? payload.jatuh_tempo;
  return {
    description: String(payload.deskripsi ?? payload.description ?? '').trim(),
    amount: amount ? String(amount) : '',
    frequency: FREQS.includes(payload.frekuensi ?? payload.frequency) ? (payload.frekuensi ?? payload.frequency) : 'monthly',
    envelopeId: payload.amplop_id ?? payload.envelope_id ?? '',
    nextRun: isIsoDate(next) ? next : null,
  };
}

// Payload aksi `chat` → teks awal + chip pertanyaan cepat.
export function chatDraft(payload = {}) {
  const text = String(payload.teks ?? payload.text ?? '').slice(0, 500);
  const chips = (Array.isArray(payload.chip ?? payload.chips) ? (payload.chip ?? payload.chips) : [])
    .map(c => (typeof c === 'string' ? { label: c, text: c } : { label: c?.label ?? c?.text, text: c?.text ?? c?.label }))
    .filter(c => typeof c.text === 'string' && c.text.trim())
    .slice(0, 4);
  return { text, chips, send: payload.kirim === true || payload.send === true };
}

// ── Lembar rencana (/advisor/plan → /advisor/execute) ─────────────────────────

export const TINGKAT_LABEL = { a: 'Keinginan', b: 'Kebutuhan, ada sisa', c: 'Cek dulu' };

export const kebutuhanTotal = kebutuhan => (kebutuhan || []).reduce((s, k) => s + (Number(k.jumlah) || 0), 0);
export const rencanaTotal = rencana => (rencana || []).filter(r => r.tercentang).reduce((s, r) => s + (Number(r.jumlah) || 0), 0);

// Sumber yang dilepas user → dikirim sebagai `kecuali` supaya server menghitung ulang.
export function excludedSources(rencana, prev = []) {
  const off = (rencana || []).filter(r => !r.tercentang).map(r => r.dari_id);
  return [...new Set([...prev, ...off])];
}

export function toggleRow(rencana, dariId) {
  return (rencana || []).map(r => (r.dari_id === dariId ? { ...r, tercentang: !r.tercentang } : r));
}

// kebutuhan/kecuali/sertakan digaungkan server di respons plan; dikirim balik supaya
// 409 "Saldo berubah" bisa langsung menyertakan rencana_baru untuk permintaan yang sama.
export function executeBody(plan, clientRef) {
  const body = {
    rencana: (plan?.rencana || []).filter(r => r.tercentang),
    bayar: plan?.bayar || [],
    saldo_versi: plan?.saldo_versi,
    client_ref: clientRef,
  };
  if (plan?.kebutuhan) body.kebutuhan = plan.kebutuhan;
  if (plan?.kecuali?.length) body.kecuali = plan.kecuali;
  if (plan?.sertakan?.length) body.sertakan = plan.sertakan;
  return body;
}

export function newClientRef() {
  try { if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID(); } catch { /* lanjut */ }
  return `ref-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
