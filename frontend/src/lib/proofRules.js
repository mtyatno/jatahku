// Bagian "Aturan belajar" di kartu Admin "Scan Struk" (spec 2026-11-01 §6; API app/api/routes/admin_kotak.py):
// logika murni, diuji dengan node --test; JSX (components/ProofRulesSection.jsx) hanya merender hasilnya.
//
// Daftar dimuat sekali dengan `GET /admin/kotak/rules?status=semua` lalu dikelompokkan per tab di sini; sesudah
// setiap keputusan (setujui/tolak/cabut) daftar dimuat ulang. Tab "Suara" hanya menampilkan angka per aplikasi dan
// jenis (`GET /admin/kotak/votes`), tidak pernah teks label. Contoh aturan selalu SINTETIS: label aturan + nilai
// tersamar, tidak pernah data user. Transisi status = G5 (server `belajar.DECISIONS`); server tetap penentu (409).
import { ISSUER_LABEL } from './proofFormat.js';
import { wibDate, shortDate } from './receiptScan.js';

export const KIND_LABEL = { label_total: 'Nominal', label_pihak: 'Nama penerima', label_tanggal: 'Tanggal' };

export const RULE_TABS = [
  { key: 'menunggu', label: 'Menunggu' },
  { key: 'disetujui', label: 'Disetujui' },
  { key: 'ditolak', label: 'Ditolak' },
  { key: 'dicabut', label: 'Dicabut' },
  { key: 'suara', label: 'Suara' },
];
const STATUSES = ['menunggu', 'disetujui', 'ditolak', 'dicabut'];

export const NOTE_MAX = 200;   // = server NOTE_MAX (kolom proof_rules.note)
export const RULE_MIN_USERS = 2;   // = server config.RULE_MIN_USERS: setujui di bawahnya → 409 "Aturan belum didukung 2 user"
export const THRESHOLD_HINT = `Belum didukung ${RULE_MIN_USERS} user`;

export const WARNING_TEXT = 'Label ini mirip kata status/metode — periksa contohnya.';

// Nilai tersamar per jenis (= server admin_kotak.EXAMPLE_VALUE): tanpa angka sama sekali.
const EXAMPLE_VALUE = { label_total: 'Rp##.###', label_pihak: 'NAMA PENERIMA', label_tanggal: '## Okt ####' };

// Transisi G5: setujui ← menunggu|ditolak|dicabut; tolak ← menunggu; cabut ← disetujui.
const ACTIONS = { menunggu: ['setujui', 'tolak'], disetujui: ['cabut'], ditolak: ['setujui'], dicabut: ['setujui'] };
const ACTION_LABEL = { setujui: 'Setujui', tolak: 'Tolak', cabut: 'Cabut' };
const DONE_TEXT = { setujui: 'Aturan disetujui.', tolak: 'Aturan ditolak.', cabut: 'Aturan dicabut.' };
const DECIDED_VERB = { disetujui: 'Disetujui', ditolak: 'Ditolak', dicabut: 'Dicabut' };
// Petunjuk aturan di bawah ambang: yang disetujui masih dipakai pembaca (pemilik bisa mencabutnya); status lain belum
// bisa disetujui (tombol Setujui tidak ditampilkan).
const THRESHOLD_TEXT = {
  disetujui: `${THRESHOLD_HINT} — masih dipakai pembaca; pertimbangkan Cabut.`,
  other: `${THRESHOLD_HINT}, jadi belum bisa disetujui.`,
};

const EMPTY_TEXT = {
  menunggu: 'Tidak ada aturan yang menunggu.',
  disetujui: 'Belum ada aturan yang disetujui.',
  ditolak: 'Belum ada aturan yang ditolak.',
  dicabut: 'Belum ada aturan yang dicabut.',
  suara: 'Belum ada suara.',
};

const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const isText = v => typeof v === 'string' && v.length > 0;
const count = v => (Number.isSafeInteger(v) && v > 0 ? v : 0);
const own = (map, key) => typeof key === 'string' && Object.hasOwn(map, key);
const time = v => {
  const t = typeof v === 'string' ? Date.parse(v) : NaN;
  return Number.isNaN(t) ? null : t;
};
const byText = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// "GoPay"; `logo:x` → "Aplikasi baru: x"; kunci lain (profil yang belum diberi label di klien) apa adanya.
export function ruleAppLabel(ruleKey) {
  if (!isText(ruleKey)) return '–';
  if (own(ISSUER_LABEL, ruleKey)) return ISSUER_LABEL[ruleKey];
  if (ruleKey.startsWith('logo:') && ruleKey.length > 5) return `Aplikasi baru: ${ruleKey.slice(5)}`;
  return ruleKey;
}

// "Total bayar Rp##.###" dari label dan jenis aturan saja (field lain, termasuk `example` server, tidak dipakai).
export function syntheticExample(rule) {
  const value = rule?.value;
  if (!isText(value)) return null;
  const label = value[0].toUpperCase() + value.slice(1);
  return `${label} ${own(EXAMPLE_VALUE, rule.kind) ? EXAMPLE_VALUE[rule.kind] : '…'}`;
}

export function ruleActions(status) {
  return own(ACTIONS, status) ? [...ACTIONS[status]] : [];
}

// Aksi satu baris: transisi G5, tanpa Setujui bila pendukungnya < RULE_MIN_USERS (server menolaknya dengan 409).
export function rowActions(status, users) {
  const actions = ruleActions(status);
  return count(users) < RULE_MIN_USERS ? actions.filter(a => a !== 'setujui') : actions;
}

// Tombol satu baris (hasil ruleRows); semuanya mati selama satu keputusan sedang dikirim (`busy`) atau bila
// catatannya tidak sah (`note`, lihat noteError).
export function actionButtons(row, busy, note) {
  const blocked = !!busy || noteError(note) !== null;
  return (Array.isArray(row?.actions) ? row.actions : [])
    .filter(a => own(ACTION_LABEL, a))
    .map(action => ({ action, label: ACTION_LABEL[action], disabled: blocked }));
}

// {menunggu, disetujui, ditolak, dicabut} dari `counts` server (seluruh tabel); rusak → 0.
export function tabCounts(resp) {
  const counts = isObj(resp?.counts) ? resp.counts : {};
  return Object.fromEntries(STATUSES.map(s => [s, count(counts[s])]));
}

// "3 menunggu · 1 disetujui · 2 ditolak · 0 dicabut", atau null tanpa `counts`.
export function ruleSummary(resp) {
  if (!isObj(resp?.counts)) return null;
  const c = tabCounts(resp);
  return STATUSES.map(s => `${c[s]} ${s}`).join(' · ');
}

function dateLine(rule) {
  if (rule.status === 'menunggu') {
    const d = wibDate(rule.created_at);
    return d ? `Masuk ${shortDate(d)}` : null;
  }
  const d = wibDate(rule.decided_at);
  if (!d) return null;
  const by = isText(rule.decided_by_name) ? ` oleh ${rule.decided_by_name}` : '';
  return `${DECIDED_VERB[rule.status]} ${shortDate(d)}${by}`;
}

const validRule = r => isObj(r) && isText(r.id) && own(ACTIONS, r.status) && isText(r.kind) && isText(r.value);

// Menunggu: pendukung terbanyak dulu, lalu yang lebih dulu masuk (= urutan server). Tab keputusan: keputusan terbaru
// dulu (tanpa tanggal di belakang), lalu pendukung terbanyak.
function compare(tab) {
  if (tab === 'menunggu') {
    return (a, b) => count(b.users) - count(a.users)
      || (time(a.created_at) ?? Infinity) - (time(b.created_at) ?? Infinity) || byText(a.id, b.id);
  }
  return (a, b) => (time(b.decided_at) ?? -Infinity) - (time(a.decided_at) ?? -Infinity)
    || count(b.users) - count(a.users) || byText(a.id, b.id);
}

// Baris satu tab (status) → [{id, status, kind, app, label, example, support, date, meta, note, warning, threshold,
// actions}] (`meta` = support · date; `threshold` = petunjuk di bawah ambang atau null);
// tab "suara"/tidak dikenal → []; respons tanpa daftar → null. Baris rusak dilewati, tidak pernah melempar.
export function ruleRows(resp, tab) {
  if (!Array.isArray(resp?.rules)) return null;
  if (!own(ACTIONS, tab)) return [];
  return resp.rules.filter(r => validRule(r) && r.status === tab).sort(compare(tab)).map((r) => {
    const support = `${count(r.users)} user · ${count(r.households)} rumah tangga`;
    const date = dateLine(r);
    const below = count(r.users) < RULE_MIN_USERS;
    return {
      id: r.id,
      status: r.status,
      kind: own(KIND_LABEL, r.kind) ? KIND_LABEL[r.kind] : r.kind,
      app: ruleAppLabel(r.rule_key),
      label: r.value,
      example: syntheticExample(r),
      support,
      date,
      meta: date ? `${support} · ${date}` : support,
      note: typeof r.note === 'string' && r.note.trim() ? r.note.trim() : null,
      warning: r.warning === true ? WARNING_TEXT : null,
      threshold: below ? THRESHOLD_TEXT[r.status === 'disetujui' ? 'disetujui' : 'other'] : null,
      actions: rowActions(r.status, r.users),
    };
  });
}

// Tab "Suara": hanya angka (user berbeda, label berbeda) per aplikasi dan jenis; field lain diabaikan.
// Urut user terbanyak, lalu aplikasi, lalu urutan jenis. Respons tanpa `rows` → null.
const KIND_ORDER = Object.keys(KIND_LABEL);
export function voteRows(resp) {
  if (!Array.isArray(resp?.rows)) return null;
  const kindRank = k => (KIND_ORDER.includes(k) ? KIND_ORDER.indexOf(k) : KIND_ORDER.length);
  return resp.rows.filter(r => isObj(r) && isText(r.rule_key) && isText(r.kind)).map((r) => {
    const users = count(r.users);
    const values = count(r.values);
    return {
      key: `${r.rule_key}|${r.kind}`,
      app: ruleAppLabel(r.rule_key),
      kind: own(KIND_LABEL, r.kind) ? KIND_LABEL[r.kind] : r.kind,
      users,
      values,
      text: `${users} user · ${values} label`,
      _rank: kindRank(r.kind),
    };
  }).sort((a, b) => b.users - a.users || a.app.localeCompare(b.app) || a._rank - b._rank || byText(a.key, b.key))
    .map(({ _rank, ...row }) => row);
}

// Spasi yang dibuang `str.strip()` Python (server merapikan catatan SEBELUM batas panjang). Berbeda dari `trim()` JS:
// U+FEFF tidak dibuang, U+001C–U+001F dan U+0085 dibuang.
const PY_SPACE = '\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, 'g');
// Karakter kontrol (server: kategori Cc → 422) dan U+FEFF (tak terlihat; ditolak klien).
const BAD_NOTE_CHAR = /[\p{Cc}\uFEFF]/u;

// Catatan dikirim sesudah dirapikan seperti server; kosong → null.
export function notePayload(note) {
  if (typeof note !== 'string') return null;
  const t = note.replace(PY_STRIP, '');
  return t || null;
}

// Galat catatan sebelum dikirim, atau null. Panjang dihitung per code point seperti server (Python).
export function noteError(note) {
  const t = notePayload(note);
  if (!t) return null;
  if (BAD_NOTE_CHAR.test(t)) return 'Catatan tidak boleh memuat tab, baris baru, atau karakter khusus lain.';
  const n = [...t].length;
  return n > NOTE_MAX ? `Catatan maksimal ${NOTE_MAX} karakter (sekarang ${n}).` : null;
}

// Body POST keputusan: catatan yang sudah dirapikan + `from_status` = status baris yang dilihat admin, supaya server
// menolak (409) bila admin lain sudah memutuskan lebih dulu (review L4a m-2).
export function decisionBody(row, note) {
  return { note: notePayload(note), from_status: own(ACTIONS, row?.status) ? row.status : null };
}

// Teks `detail` server hanya dipakai bila berupa kalimat pendek (bukan JSON/objek).
function serverText(data) {
  const d = data?.detail;
  if (typeof d !== 'string') return null;
  const t = d.trim();
  if (!t || t.length > 200 || /^[[{]/.test(t)) return null;
  return t;
}

// Hasil keputusan ({ok, status, data} dari api.adminProofRuleAction) → {kind: 'ok'|'conflict'|'error', text, reload}.
// `reload`: daftar dimuat ulang (berhasil, 409 status sudah berubah, 404 aturan hilang).
export function actionOutcome(action, res) {
  if (res?.ok) return { kind: 'ok', text: DONE_TEXT[action] || 'Keputusan tersimpan.', reload: true };
  const status = Number.isSafeInteger(res?.status) ? res.status : 0;
  if (status === 409) {
    const t = serverText(res.data);
    return {
      kind: 'conflict',
      text: t ? `${t.replace(/[.!]+$/, '')}. Daftar dimuat ulang.` : 'Status aturan ini sudah berubah. Daftar dimuat ulang.',
      reload: true,
    };
  }
  if (status === 404) return { kind: 'conflict', text: 'Aturan tidak ditemukan lagi. Daftar dimuat ulang.', reload: true };
  if (status === 403) return { kind: 'error', text: 'Hanya admin yang bisa memutuskan aturan.', reload: false };
  if (status === 422) return { kind: 'error', text: 'Catatan tidak diterima.', reload: false };
  if (status === 0) return { kind: 'error', text: 'Koneksi gagal, coba lagi.', reload: false };
  return { kind: 'error', text: `Keputusan belum tersimpan (kode ${status}). Coba lagi.`, reload: false };
}

// Lencana kepala kartu "N aturan menunggu": dari daftar yang terakhir dimuat bila ada (lebih baru dari stats),
// selain itu dari `rules_pending` stats. 0 atau tidak ada → null (tidak dirender).
export function pendingBadge(stats, resp) {
  const fromList = resp?.counts?.menunggu;
  const n = Number.isSafeInteger(fromList) && fromList >= 0 ? fromList : stats?.rules_pending;
  return Number.isSafeInteger(n) && n > 0 ? `${n} aturan menunggu` : null;
}

// Server lama tanpa API aturan (stats tanpa `rules_pending`) → bagian tidak dirender.
export function hasRulesSection(stats) {
  return Number.isSafeInteger(stats?.rules_pending);
}

// Tab berikutnya untuk tombol panah/Home/End di daftar tab (pola tab WAI-ARIA, melingkar), atau null.
export function nextTab(current, key) {
  const keys = RULE_TABS.map(t => t.key);
  const i = keys.indexOf(current);
  if (i < 0) return null;
  if (key === 'ArrowRight') return keys[(i + 1) % keys.length];
  if (key === 'ArrowLeft') return keys[(i - 1 + keys.length) % keys.length];
  if (key === 'Home') return keys[0];
  if (key === 'End') return keys[keys.length - 1];
  return null;
}

export function emptyText(tab) {
  return own(EMPTY_TEXT, tab) ? EMPTY_TEXT[tab] : '';
}
