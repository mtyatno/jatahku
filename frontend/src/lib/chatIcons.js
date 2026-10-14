// Emoji & simbol teks di balasan bot → elemen visual aplikasi di chat webapp.
// Bot (sama dengan Telegram) menulis emoji, bar teks "▰▰▱▱", dan garis "────".
// Di web, emoji itu tampil memakai font emoji sistem (di Windows terlihat jadul);
// di sini dipetakan ke ikon Phosphor aplikasi, titik status, bar sungguhan, dan
// garis pemisah — sama dengan bahasa visual halaman lain. Fungsi murni (diuji).

// Titik status amplop: 🟢 aman, 🟡/🟠 menipis, 🔴 habis/minus, ⚪ belum didanai.
export const DOT_EMOJI = { '🟢': 'ok', '🟡': 'warn', '🟠': 'warn', '🔴': 'bad', '⚪': 'none', '⚫': 'none' };

// Emoji dekoratif → [nama ikon di Icon.jsx, nada warna].
// Emoji lain (kategori amplop: 🍜 🏠 🚗 📁 💰 …) diserahkan ke EnvelopeIcon,
// dan yang tidak dikenal (wajah, keluarga) tetap tampil sebagai emoji.
export const CHAT_EMOJI = {
  '✅': ['check', 'ok'], '☑': ['check', 'ok'], '✔': ['check', 'ok'],
  '⚠': ['warning', 'warn'], '🚨': ['warning', 'bad'],
  '❌': ['xcircle', 'bad'], '⛔': ['xcircle', 'bad'], '🚫': ['xcircle', 'bad'],
  '💡': ['bulb', 'warn'],
  '📊': ['dashboard', 'brand'], '📈': ['trendup', 'brand'], '🔝': ['trendup', 'brand'],
  '📅': ['calendar', 'brand'], '🗓': ['calendar', 'brand'], '📆': ['calendar', 'brand'],
  '💸': ['income', 'brand'],
  '⏳': ['hourglass', 'muted'], '⌛': ['hourglass', 'muted'],
  '⏰': ['alarm', 'muted'], '⏱': ['timer', 'muted'], '🕐': ['clock', 'muted'],
  '🔄': ['langganan', 'brand'], '🔁': ['transfer', 'brand'], '↩': ['undo', 'brand'],
  '⏭': ['skip', 'muted'], '➡': ['arrowright', 'muted'],
  '🔥': ['fire', 'fire'],
  '🧾': ['receipt', 'brand'],
  '👍': ['thumbsup', 'brand'],
  '🔒': ['lock', 'warn'], '🔐': ['lock', 'warn'], '🔓': ['unlock', 'brand'],
  '🌱': ['plant', 'ok'],
  '📸': ['camera', 'brand'], '📷': ['camera', 'brand'],
  '⭐': ['star', 'warn'], '🌟': ['star', 'warn'],
  '✏': ['edit', 'muted'],
  '🔍': ['search', 'muted'], '🔎': ['search', 'muted'],
  '💤': ['moon', 'muted'],
  '📋': ['clipboard', 'brand'],
  '👋': ['wave', 'warn'],
  '🌐': ['globe', 'brand'],
  '✨': ['advisor', 'warn'], '🔮': ['advisor', 'brand'],
  '💬': ['chat', 'brand'],
  '⚙': ['settings', 'muted'],
  '🏦': ['bank', 'brand'],
  '📖': ['book', 'brand'],
  '🔗': ['link', 'brand'],
  '📄': ['file', 'muted'],
  '🎤': ['mic', 'brand'],
  '🎉': ['party', 'warn'], '🥳': ['party', 'warn'],
  '🏆': ['trophy', 'warn'],
  'ℹ': ['info', 'brand'],
};

// Satu "emoji" utuh: termasuk variation selector & rangkaian ZWJ (👨‍👩‍👧).
const EMOJI = '\\p{Extended_Pictographic}\\uFE0F?(?:\\u200D\\p{Extended_Pictographic}\\uFE0F?)*';
const BAR = '[▓█▰░▱]{4,}';
const RULE = '─{5,}';
const TOKEN_RE = new RegExp(`(${EMOJI})|(${BAR})|(${RULE})`, 'gu');

const FILLED = /[▓█▰]/g;

export function barRatio(token) {
  const total = [...token].length;
  const filled = (token.match(FILLED) || []).length;
  return total ? filled / total : 0;
}

// Teks → potongan: {t:'text'} | {t:'icon', icon, tone, v} | {t:'dot', level, v}
// | {t:'emoji', v} (diserahkan ke EnvelopeIcon) | {t:'bar', ratio, v} | {t:'rule', v}
export function chatSegments(text) {
  const src = String(text ?? '');
  const out = [];
  let last = 0;
  TOKEN_RE.lastIndex = 0;
  let m;
  while ((m = TOKEN_RE.exec(src)) !== null) {
    if (m.index > last) out.push({ t: 'text', v: src.slice(last, m.index) });
    const v = m[0];
    if (m[1]) {
      const bare = v.replace(/️/g, '');
      if (DOT_EMOJI[bare]) out.push({ t: 'dot', level: DOT_EMOJI[bare], v });
      else if (CHAT_EMOJI[bare]) out.push({ t: 'icon', icon: CHAT_EMOJI[bare][0], tone: CHAT_EMOJI[bare][1], v });
      else out.push({ t: 'emoji', v });
    } else if (m[2]) {
      out.push({ t: 'bar', ratio: barRatio(v), v });
    } else {
      out.push({ t: 'rule', v });
    }
    last = m.index + v.length;
  }
  if (last < src.length) out.push({ t: 'text', v: src.slice(last) });
  return out;
}

// Warna bar mengikuti tingkat pemakaian (sama dengan titik status bot).
export function barLevel(ratio) {
  if (ratio >= 0.9) return 'bad';
  if (ratio >= 0.7) return 'warn';
  return 'ok';
}
