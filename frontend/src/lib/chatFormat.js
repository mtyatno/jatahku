// Render teks balasan bot (format Telegram) menjadi potongan aman untuk React.
// Bot memakai parse_mode Telegram: "HTML" (subset <b>, <i>, <code>, <a> …) atau
// "Markdown" lama (*tebal*, _miring_, `kode`, [teks](url), escape "\").
// Hasilnya daftar node — tidak pernah HTML mentah, jadi tidak ada XSS.
//
// Node: { t: 'text', v, b?, i?, u?, s? } | { t: 'code', v } | { t: 'pre', v }
//     | { t: 'link', v, href } | { t: 'cmd', v: '/status' }

// Perintah bot yang bisa diketuk di teks balasan (sama dengan bot_commands()
// di backend, tanpa perintah akun khusus Telegram).
export const BOT_COMMANDS = new Set([
  'start', 'help', 'status', 'amplop', 'amplop_baru', 'template', 'batal',
  'pending', 'lock', 'setlimit', 'setcooling', 'controls', 'langganan',
  'tambah_langganan', 'hapus_langganan', 'invite', 'join',
]);

// Perintah yang tidak langsung dikirim saat diketuk di teks balasan, tapi
// diisikan ke kotak ketik: butuh argumen, atau mengubah data (/batal).
export const PREFILL_COMMANDS = new Set([
  'batal', 'amplop_baru', 'setlimit', 'setcooling', 'tambah_langganan', 'join',
]);

const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };

export function decodeEntities(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === '#') {
      const code = e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(code) && code > 0 && code < 0x110000 ? String.fromCodePoint(code) : m;
    }
    return ENTITIES[e.toLowerCase()] ?? m;
  });
}

export function safeHref(href) {
  const v = (href || '').trim();
  if (/^https?:\/\//i.test(v)) return v;
  if (/^(www\.|jatahku\.com)/i.test(v)) return `https://${v}`;
  return null;
}

// ── HTML (subset Telegram) ───────────────────────────────────────────────────

const STYLE_TAGS = {
  b: 'b', strong: 'b', i: 'i', em: 'i', u: 'u', ins: 'u', s: 's', strike: 's', del: 's',
};

export function parseHtml(src) {
  const nodes = [];
  const style = { b: 0, i: 0, u: 0, s: 0 };
  let code = null; // { tag, buf }
  let link = null; // { href, buf }
  const tagRe = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[^>]*)?)>/g;
  let last = 0;
  let m;

  const pushText = (raw) => {
    if (!raw) return;
    const v = decodeEntities(raw);
    if (code) { code.buf += v; return; }
    if (link) { link.buf += v; return; }
    nodes.push({ t: 'text', v, ...activeStyle(style) });
  };

  while ((m = tagRe.exec(src)) !== null) {
    pushText(src.slice(last, m.index));
    last = tagRe.lastIndex;
    const closing = m[1] === '/';
    const tag = m[2].toLowerCase();
    if (code) {
      if (closing && tag === code.tag) {
        nodes.push({ t: tag === 'pre' ? 'pre' : 'code', v: code.buf });
        code = null;
      } else if (!(tag === 'code' && code.tag === 'pre')) {
        code.buf += m[0];
      }
      continue;
    }
    if (tag === 'code' || tag === 'pre') {
      if (!closing) code = { tag, buf: '' };
      continue;
    }
    if (tag === 'a') {
      if (!closing) {
        const hm = /href\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/i.exec(m[3] || '');
        link = { href: safeHref(decodeEntities(hm ? (hm[2] ?? hm[3] ?? hm[4] ?? '') : '')), buf: '' };
      } else if (link) {
        if (link.href) nodes.push({ t: 'link', v: link.buf || link.href, href: link.href });
        else if (link.buf) nodes.push({ t: 'text', v: link.buf, ...activeStyle(style) });
        link = null;
      }
      continue;
    }
    if (STYLE_TAGS[tag]) {
      const k = STYLE_TAGS[tag];
      style[k] = Math.max(0, style[k] + (closing ? -1 : 1));
      continue;
    }
    if (tag === 'br') { pushText('\n'); continue; }
    if (tag === 'tg-spoiler' || tag === 'span' || tag === 'blockquote' || tag === 'tg-emoji') continue;
    // Tag tak dikenal: tampilkan apa adanya sebagai teks.
    if (link) link.buf += m[0];
    else nodes.push({ t: 'text', v: m[0], ...activeStyle(style) });
  }
  pushText(src.slice(last));
  if (code) nodes.push({ t: code.tag === 'pre' ? 'pre' : 'code', v: code.buf });
  if (link) nodes.push(link.href ? { t: 'link', v: link.buf || link.href, href: link.href } : { t: 'text', v: link.buf });
  return nodes;
}

function activeStyle(style) {
  const out = {};
  for (const k of ['b', 'i', 'u', 's']) if (style[k] > 0) out[k] = true;
  return out;
}

// ── Markdown lama Telegram ───────────────────────────────────────────────────

export function parseMarkdown(src) {
  const nodes = [];
  let buf = '';
  const flush = () => { if (buf) { nodes.push({ t: 'text', v: buf }); buf = ''; } };
  // Cari penutup `ch` mulai dari `from`, melewati karakter ber-escape.
  const findClose = (ch, from) => {
    for (let j = from; j < src.length; j++) {
      if (src[j] === '\\' && ch !== '`') { j++; continue; }
      if (src[j] === ch) return j;
    }
    return -1;
  };
  const unescape = (s) => s.replace(/\\([_*`[\]()\\])/g, '$1');

  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (c === '\\' && i + 1 < src.length && '_*`[]()\\'.includes(src[i + 1])) {
      buf += src[i + 1];
      i += 2;
      continue;
    }
    if (c === '`' && src.startsWith('```', i)) {
      const end = src.indexOf('```', i + 3);
      if (end !== -1) {
        flush();
        nodes.push({ t: 'pre', v: src.slice(i + 3, end).replace(/^\w*\n/, '') });
        i = end + 3;
        continue;
      }
    }
    if (c === '`') {
      const end = findClose('`', i + 1);
      if (end > i + 1) {
        flush();
        nodes.push({ t: 'code', v: src.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }
    if (c === '*' || c === '_') {
      const end = findClose(c, i + 1);
      if (end > i + 1) {
        flush();
        nodes.push({ t: 'text', v: unescape(src.slice(i + 1, end)), [c === '*' ? 'b' : 'i']: true });
        i = end + 1;
        continue;
      }
    }
    if (c === '[') {
      const close = findClose(']', i + 1);
      if (close > i + 1 && src[close + 1] === '(') {
        const paren = src.indexOf(')', close + 2);
        const href = paren !== -1 ? safeHref(src.slice(close + 2, paren)) : null;
        if (href) {
          flush();
          nodes.push({ t: 'link', v: unescape(src.slice(i + 1, close)), href });
          i = paren + 1;
          continue;
        }
      }
    }
    buf += c;
    i++;
  }
  flush();
  return nodes;
}

// ── Tautan & perintah di teks biasa ─────────────────────────────────────────

const TRAIL = /[.,!?;:'")\]]+$/;
const TOKEN_RE = /(https?:\/\/[^\s<>]+)|((?:www\.)?jatahku\.com(?:\/[^\s<>]*)?)|(\/[a-z][a-z0-9_]{1,31})/gi;

export function linkify(text, style = {}) {
  const out = [];
  let last = 0;
  let m;
  TOKEN_RE.lastIndex = 0;
  const pushText = (v) => { if (v) out.push({ t: 'text', v, ...style }); };
  while ((m = TOKEN_RE.exec(text)) !== null) {
    const before = m.index > 0 ? text[m.index - 1] : '';
    let token = m[0];
    if (m[3]) {
      // Perintah: harus berdiri sendiri ("Rp50rb/bulan" bukan perintah).
      const after = text[m.index + token.length] || '';
      const name = token.slice(1).toLowerCase();
      if ((before && !/[\s(]/.test(before)) || (after && !/[\s.,!?;:)]/.test(after)) || !BOT_COMMANDS.has(name)) {
        continue;
      }
      pushText(text.slice(last, m.index));
      out.push({ t: 'cmd', v: `/${name}` });
      last = m.index + token.length;
      continue;
    }
    if (before && /[\w.@/-]/.test(before)) continue; // bagian dari kata/domain lain
    const trail = token.match(TRAIL);
    if (trail) token = token.slice(0, -trail[0].length);
    const href = safeHref(token);
    if (!href) continue;
    pushText(text.slice(last, m.index));
    out.push({ t: 'link', v: token, href });
    last = m.index + token.length;
    TOKEN_RE.lastIndex = last;
  }
  pushText(text.slice(last));
  return out;
}

function withLinks(nodes) {
  const out = [];
  for (const n of nodes) {
    if (n.t !== 'text') { out.push(n); continue; }
    const { t, v, ...style } = n;
    out.push(...linkify(v, style));
  }
  return out;
}

// Gabungkan node teks bersebelahan dengan gaya yang sama (render lebih ringkas).
function merge(nodes) {
  const out = [];
  for (const n of nodes) {
    const prev = out[out.length - 1];
    if (prev && prev.t === 'text' && n.t === 'text' &&
        !!prev.b === !!n.b && !!prev.i === !!n.i && !!prev.u === !!n.u && !!prev.s === !!n.s) {
      prev.v += n.v;
    } else {
      out.push({ ...n });
    }
  }
  return out;
}

export function formatBotText(text, format = 'plain') {
  const src = String(text ?? '');
  let nodes;
  if (format === 'html') nodes = parseHtml(src);
  else if (format === 'markdown') nodes = parseMarkdown(src);
  else nodes = [{ t: 'text', v: src }];
  return merge(withLinks(merge(nodes)));
}

// Tautan ke halaman webapp sendiri dibuka di dalam aplikasi, bukan tab baru.
const APP_PATHS = ['/envelopes', '/transactions', '/allocate', '/langganan', '/analytics', '/settings', '/upgrade'];

export function inAppPath(href, currentHost = '') {
  try {
    const u = new URL(href);
    const host = u.host.replace(/^www\./, '');
    if (host !== 'jatahku.com' && host !== currentHost) return null;
    const path = u.pathname.replace(/\/+$/, '');
    return APP_PATHS.includes(path) ? path + u.search : null;
  } catch {
    return null;
  }
}
