// Riwayat chat bot di webapp: disimpan lokal per user (seperti riwayat chat
// Telegram di HP), dan "ops" dari server diterapkan ke daftar pesan.
//
// Pesan: { id, role: 'user' | 'bot', text, format, buttons, ts, status?, kind?, thumb? }
//   status (pesan user saja): 'sending' | 'failed'
//   kind 'photo' (pesan user): foto struk; thumb = data URL kecil untuk pratinjau

export const MAX_MESSAGES = 100;
const KEY_PREFIX = 'jatahku_chat_';

export function historyKey(userId) {
  return `${KEY_PREFIX}${userId || 'anon'}`;
}

export function loadHistory(userId, storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem(historyKey(userId));
    const list = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(list)) return [];
    // Pesan yang sempat "mengirim" saat aplikasi ditutup dianggap gagal.
    return list
      .filter(m => m && typeof m.id === 'string' && typeof m.text === 'string')
      .map(m => (m.status === 'sending' ? { ...m, status: 'failed' } : m));
  } catch {
    return [];
  }
}

export function saveHistory(userId, messages, storage = globalThis.localStorage) {
  try {
    storage?.setItem(historyKey(userId), JSON.stringify(messages.slice(-MAX_MESSAGES)));
  } catch {}
}

export function clearHistory(userId, storage = globalThis.localStorage) {
  try { storage?.removeItem(historyKey(userId)); } catch {}
}

// Saat logout: hapus riwayat chat semua akun di perangkat ini.
export function clearAllHistory(storage = globalThis.localStorage) {
  try {
    const keys = [];
    for (let i = 0; i < (storage?.length || 0); i++) {
      const k = storage.key(i);
      if (k && k.startsWith(KEY_PREFIX)) keys.push(k);
    }
    keys.forEach(k => storage.removeItem(k));
  } catch {}
}

let seq = 0;
export function localId() {
  seq += 1;
  return `u${Date.now().toString(36)}${seq}`;
}

export function userMessage(text, now = Date.now()) {
  return { id: localId(), role: 'user', text, format: 'plain', buttons: [], ts: now, status: 'sending' };
}

// Foto struk yang dikirim user. `thumb` kecil (±5 KB) supaya riwayat lokal tetap ringan.
export function userPhotoMessage(thumb, now = Date.now()) {
  return {
    id: localId(), role: 'user', kind: 'photo', text: '📷 Foto struk', thumb: thumb || null,
    format: 'plain', buttons: [], ts: now, status: 'sending',
  };
}

export function setStatus(messages, id, status) {
  return messages.map(m => (m.id === id ? { ...m, status } : m));
}

// Terapkan ops dari /bot/chat/*. Mengembalikan { messages, toasts }.
export function applyOps(messages, ops, now = Date.now()) {
  let list = messages.slice();
  const toasts = [];
  for (const op of ops || []) {
    if (!op || typeof op !== 'object') continue;
    if (op.type === 'toast') {
      if (op.text) toasts.push(String(op.text));
      continue;
    }
    const idx = list.findIndex(m => m.id === op.id);
    if (op.type === 'delete') {
      if (idx !== -1) list.splice(idx, 1);
      continue;
    }
    if (op.type === 'message' || (op.type === 'edit' && idx === -1)) {
      if (op.type === 'message' && idx !== -1) continue; // duplikat
      list.push({
        id: String(op.id), role: 'bot', text: String(op.text ?? ''),
        format: op.format || 'plain', buttons: Array.isArray(op.buttons) ? op.buttons : [], ts: now,
      });
    } else if (op.type === 'edit') {
      list[idx] = {
        ...list[idx], text: String(op.text ?? ''), format: op.format || 'plain',
        buttons: Array.isArray(op.buttons) ? op.buttons : [], edited: true,
      };
    } else if (op.type === 'buttons' && idx !== -1) {
      list[idx] = { ...list[idx], buttons: Array.isArray(op.buttons) ? op.buttons : [] };
    }
  }
  return { messages: list.slice(-MAX_MESSAGES), toasts };
}

// Balasan yang menandakan data berubah (transaksi tercatat/dibatalkan, amplop
// dibuat, …) → halaman lain perlu memuat ulang angka.
const CHANGE_RE = /(^|\n)\s*(✅|↩️)|tercatat|dicatat|dibatalkan|ditambahkan|dibuat|digeser/i;

export function looksLikeChange(ops) {
  return (ops || []).some(op => (op?.type === 'message' || op?.type === 'edit') && CHANGE_RE.test(op.text || ''));
}
