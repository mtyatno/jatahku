import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { PREFILL_COMMANDS, formatBotText, inAppPath, safeHref } from '../lib/chatFormat';
import {
  applyOps, clearHistory, loadHistory, looksLikeChange, saveHistory, setStatus, userMessage, userPhotoMessage,
} from '../lib/chatHistory';
import { quickChips } from '../lib/chatChips';
import { compressImage, thumbnailDataUrl } from '../lib/receiptImage';
import { DRAG_SLOP, dragHeight, keyboardInset, pickSnap, sheetHeights } from '../lib/sheetGesture';
import ChatText from './ChatText';
import { Icon } from './Icon';
import VoiceInput from './VoiceInput';

// Chat bot Jatahku di dalam webapp: otak yang sama dengan @JatahkuBot di
// Telegram (backend menjalankan handler bot lewat app/bot/web_adapter.py).
// Mobile: bottom sheet setinggi setengah layar HP (dihitung dari tinggi layar
// yang sedang dipakai), bisa ditarik ke atas jadi penuh; ditutup dari jangkauan
// jempol (tombol ⌄ di samping kotak ketik, tarik ke bawah, ketuk latar, atau
// Back Android). Saat keyboard terbuka sheet otomatis penuh di atas keyboard.
// Desktop: panel samping, halaman tetap terlihat.

// Contoh di layar kosong. Contoh pengeluaran hanya mengisi kotak ketik —
// jangan sampai mengetuk contoh langsung mencatat transaksi sungguhan.
const EXAMPLES = [
  { text: 'kopi 35k', send: false, hint: 'catat pengeluaran' },
  { text: 'makan 30k, parkir 5k', send: false, hint: 'beberapa sekaligus' },
  { text: 'sisa', send: true, hint: 'cek sisa amplop' },
  { text: 'aman gak beli sepatu 400rb?', send: false, hint: 'tanya dulu sebelum beli' },
];

const TOAST_MS = 2800;
const SHEET_MS = 300; // durasi animasi buka/tutup
const isDesktop = () => typeof window !== 'undefined' && !!window.matchMedia?.('(min-width: 768px)')?.matches;

// ── Ukuran layar untuk sheet mobile ───────────────────────────────────────────

let safeTopCache = null;
function safeAreaTop() {
  if (safeTopCache !== null) return safeTopCache;
  try {
    const probe = document.createElement('div');
    probe.style.cssText = 'position:fixed;top:0;left:0;width:0;height:env(safe-area-inset-top);visibility:hidden;pointer-events:none';
    document.body.appendChild(probe);
    safeTopCache = probe.getBoundingClientRect().height || 0;
    probe.remove();
  } catch {
    safeTopCache = 0;
  }
  return safeTopCache;
}

const isEditing = () => {
  const el = typeof document !== 'undefined' ? document.activeElement : null;
  return !!el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.isContentEditable);
};

let tallestSeen = 0; // tinggi layar tanpa keyboard (browser yang ikut mengecilkan layout)

function measureViewport() {
  if (typeof window === 'undefined') return { desktop: false, screenH: 800, availH: 800, inset: 0, keyboard: false, safeTop: 0 };
  const innerH = window.innerHeight;
  const vv = window.visualViewport;
  const editing = isEditing();
  tallestSeen = editing ? Math.max(tallestSeen, innerH) : innerH;
  const inset = keyboardInset(innerH, vv?.height, vv?.offsetTop);
  const keyboard = editing && (inset > 0 || innerH < tallestSeen - 120);
  return {
    desktop: isDesktop(),
    screenH: tallestSeen,
    availH: innerH - inset,
    inset,
    keyboard,
    safeTop: safeAreaTop(),
  };
}

// Ukuran layar terkini (berubah saat keyboard muncul/hilang atau HP diputar).
function useViewport(active) {
  const [vp, setVp] = useState(measureViewport);
  useEffect(() => {
    if (!active) return;
    let raf = 0;
    const update = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => setVp(measureViewport()));
    };
    update();
    const vv = window.visualViewport;
    window.addEventListener('resize', update);
    window.addEventListener('focusin', update);
    window.addEventListener('focusout', update);
    vv?.addEventListener('resize', update);
    vv?.addEventListener('scroll', update);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', update);
      window.removeEventListener('focusin', update);
      window.removeEventListener('focusout', update);
      vv?.removeEventListener('resize', update);
      vv?.removeEventListener('scroll', update);
    };
  }, [active]);
  return vp;
}

function timeLabel(ts) {
  try { return new Date(ts).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }); } catch { return ''; }
}

function dayLabel(ts) {
  const d = new Date(ts);
  const today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Hari ini';
  if (d.toDateString() === y.toDateString()) return 'Kemarin';
  return d.toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: d.getFullYear() === today.getFullYear() ? undefined : 'numeric' });
}

function BotText({ text, format, onCommand, onLink }) {
  const nodes = formatBotText(text, format);
  return nodes.map((n, i) => {
    if (n.t === 'code') {
      return <code key={i} className="font-mono text-[12.5px] px-1 py-0.5 rounded bg-gray-100">{n.v}</code>;
    }
    if (n.t === 'pre') {
      return <pre key={i} className="font-mono text-xs bg-gray-50 rounded-lg p-2 my-1 overflow-x-auto whitespace-pre">{n.v}</pre>;
    }
    if (n.t === 'link') {
      return (
        <a key={i} href={n.href} target="_blank" rel="noopener noreferrer"
          onClick={e => onLink(e, n.href)}
          className="text-brand-600 underline underline-offset-2 break-all">{n.v}</a>
      );
    }
    if (n.t === 'cmd') {
      return (
        <button key={i} type="button" onClick={() => onCommand(n.v)}
          className="text-brand-600 font-semibold hover:underline underline-offset-2">{n.v}</button>
      );
    }
    const cls = [n.b && 'font-semibold', n.i && 'italic', n.u && 'underline', n.s && 'line-through']
      .filter(Boolean).join(' ');
    // Emoji, bar teks & garis dari bot → ikon dan elemen visual aplikasi.
    return cls
      ? <span key={i} className={cls}><ChatText text={n.v} /></span>
      : <Fragment key={i}><ChatText text={n.v} /></Fragment>;
  });
}

function TypingBubble() {
  return (
    <div className="flex justify-start" aria-live="polite" aria-label="Bot sedang mengetik">
      <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-md px-4 py-3 shadow-sm flex gap-1">
        {[0, 1, 2].map(i => (
          <span key={i} className="w-1.5 h-1.5 rounded-full bg-gray-400"
            style={{ animation: `chatDot 1s ${i * 0.15}s infinite ease-in-out` }} />
        ))}
      </div>
    </div>
  );
}

function Welcome({ name, onExample }) {
  return (
    <div className="flex flex-col items-center text-center px-4 pt-6 pb-2">
      <div className="w-14 h-14 rounded-2xl text-white flex items-center justify-center mb-3"
        style={{ background: 'linear-gradient(145deg,#1D9E75,#0F6E56)' }}>
        <Icon name="chat" size={30} weight="fill" />
      </div>
      <h3 className="font-display font-bold text-lg">Hai{name ? `, ${name}` : ''}!</h3>
      <p className="text-sm text-gray-500 mt-1 max-w-xs">
        Catat dan cek jatah lewat chat — sama seperti @JatahkuBot di Telegram. Ketik pengeluaran, amplopnya dipilihkan otomatis.
      </p>
      <div className="w-full max-w-xs mt-5 space-y-2">
        {EXAMPLES.map(ex => (
          <button key={ex.text} type="button" onClick={() => onExample(ex)}
            className="w-full flex items-center justify-between gap-3 px-3.5 py-2.5 rounded-xl bg-white border border-gray-100 hover:border-brand-200 text-left transition-colors">
            <span className="font-mono text-[13px] text-gray-800">{ex.text}</span>
            <span className="text-[11px] text-gray-400 shrink-0">{ex.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// draft: { text, chips, send, nonce } dari CTA "Tanya di chat" (open-action kind `chat`).
// Teks diisikan ke kotak ketik (atau langsung dikirim bila send), chip tampil
// paling depan di baris pertanyaan cepat.
export default function ChatPanel({ open, onClose, draft = null }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const uid = user?.id;
  const firstName = (user?.name || '').trim().split(/\s+/)[0] || '';

  const [messages, setMessages] = useState(() => loadHistory(uid));
  const [input, setInput] = useState('');
  const [pending, setPending] = useState(null); // null | 'message' | `${msgId}:${data}`
  const [toast, setToast] = useState(null);
  const listRef = useRef(null);
  const inputRef = useRef(null);
  const toastTimer = useRef(null);
  const lastCount = useRef(messages.length);
  const loadedFor = useRef(uid);
  const sheetRef = useRef(null);
  const drag = useRef(null);       // status tarikan header (mobile)
  const pushedRef = useRef(false); // entri riwayat browser untuk tombol Back
  const atBottom = useRef(true);   // daftar pesan sedang di paling bawah?
  const photoFiles = useRef(new Map()); // id pesan foto → blob (untuk kirim ulang di sesi ini)
  const fileRef = useRef(null);
  const [mode, setMode] = useState('half'); // tinggi sheet mobile: 'half' | 'full'
  const [draftChips, setDraftChips] = useState([]);
  const draftSeen = useRef(null);

  // Fase animasi: closed → opening → open → closing → closed.
  const [phase, setPhase] = useState('closed');
  useEffect(() => {
    if (open) {
      setPhase('opening');
      let f2;
      const f1 = requestAnimationFrame(() => { f2 = requestAnimationFrame(() => setPhase('open')); });
      return () => { cancelAnimationFrame(f1); cancelAnimationFrame(f2); };
    }
    setPhase(p => (p === 'closed' ? 'closed' : 'closing'));
    const t = setTimeout(() => setPhase('closed'), SHEET_MS);
    return () => clearTimeout(t);
  }, [open]);

  // Sheet mobile: setengah tinggi layar HP ini, atau penuh. Keyboard terbuka →
  // penuh di atas keyboard supaya kotak ketik & pesan terakhir tetap terlihat.
  const vp = useViewport(phase !== 'closed');
  const heights = sheetHeights(vp.screenH, vp.safeTop, vp.availH);
  const sheetMode = vp.keyboard ? 'full' : mode;
  const targetH = heights[sheetMode];
  useEffect(() => { if (open) setMode('half'); }, [open]); // selalu mulai setengah

  useLayoutEffect(() => {
    const el = sheetRef.current;
    if (!el) return;
    if (vp.desktop) {
      // Panel samping (≥768px, termasuk tablet): keyboard layar menutupi bagian bawah
      // tanpa mengecilkan layout, jadi panel dinaikkan di atasnya.
      el.style.height = '';
      el.style.bottom = vp.keyboard && vp.inset > 0 ? `${vp.inset}px` : '';
      return;
    }
    if (drag.current?.active) return;
    el.style.height = `${targetH}px`;
    el.style.bottom = `${vp.inset}px`;
  }, [targetH, vp.inset, vp.keyboard, vp.desktop, phase]);

  // Daftar pesan tetap menempel di bawah saat tinggi sheet berubah.
  useEffect(() => {
    const el = listRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => { if (atBottom.current) el.scrollTop = el.scrollHeight; });
    ro.observe(el);
    return () => ro.disconnect();
  }, [phase === 'closed']);

  // Mobile: membuka chat menambah satu entri riwayat, jadi tombol/gestur Back
  // menutup chat (bukan meninggalkan halaman).
  useEffect(() => {
    if (!open || isDesktop()) return;
    try {
      // Sekali saja per pembukaan (efek bisa berjalan dua kali di StrictMode).
      if (!window.history.state?.jatahkuChat) {
        window.history.pushState({ ...(window.history.state || {}), jatahkuChat: true }, '');
      }
      pushedRef.current = true;
    } catch { /* riwayat tidak tersedia — tetap bisa ditutup lewat tombol */ }
    const onPop = () => {
      if (window.history.state?.jatahkuChat) return;
      pushedRef.current = false;
      onClose();
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [open, onClose]);

  const close = useCallback(() => {
    if (pushedRef.current && window.history.state?.jatahkuChat) {
      window.history.back(); // popstate di atas yang menutup panel
      return;
    }
    pushedRef.current = false;
    onClose();
  }, [onClose]);

  // Tarik header: ke atas → penuh, ke bawah → setengah / tutup (mobile).
  const paintHeight = (h) => {
    const el = sheetRef.current;
    if (!el) return;
    el.style.transition = 'none';
    if (h >= heights.half) {
      el.style.height = `${h}px`;
      el.style.transform = 'translateY(0px)';
    } else {
      // Di bawah setengah layar sheet turun utuh (siap ditutup).
      el.style.height = `${heights.half}px`;
      el.style.transform = `translateY(${heights.half - h}px)`;
    }
  };
  const onDragStart = (e) => {
    if (vp.desktop || e.button > 0) return;
    const now = performance.now();
    const startH = sheetRef.current?.getBoundingClientRect().height || targetH;
    drag.current = { y: e.clientY, startH, h: startH, active: false, lastY: e.clientY, lastT: now, v: 0 };
  };
  const onDragMove = (e) => {
    const d = drag.current;
    if (!d) return;
    const dy = e.clientY - d.y;
    if (!d.active && Math.abs(dy) < DRAG_SLOP) return;
    if (!d.active) {
      d.active = true;
      e.currentTarget.setPointerCapture?.(e.pointerId);
    }
    const now = performance.now();
    const dt = now - d.lastT;
    if (dt > 0) d.v = 0.7 * ((d.lastY - e.clientY) / dt) + 0.3 * d.v; // px/ms, + = ke atas
    d.lastY = e.clientY;
    d.lastT = now;
    d.h = dragHeight(d.startH, dy, heights.full);
    paintHeight(d.h);
  };
  const onDragEnd = () => {
    const d = drag.current;
    drag.current = null;
    const el = sheetRef.current;
    if (!d || !d.active || !el) return;
    const v = performance.now() - d.lastT > 80 ? 0 : d.v; // berhenti sebelum dilepas
    const snap = pickSnap(d.h, v, heights);
    el.style.transition = '';
    if (snap === 'closed') {
      el.style.transform = 'translateY(100%)';
      close();
      return;
    }
    el.style.transform = '';
    if (snap === 'half' && vp.keyboard) inputRef.current?.blur(); // tutup keyboard dulu
    setMode(snap);
    el.style.height = `${heights[snap]}px`;
  };
  const toggleSize = () => {
    if (mode === 'full' || vp.keyboard) {
      if (vp.keyboard) inputRef.current?.blur();
      setMode('half');
    } else {
      setMode('full');
    }
  };

  // Ganti akun → muat riwayat milik akun itu.
  useEffect(() => {
    if (loadedFor.current === uid) return;
    loadedFor.current = uid;
    setMessages(loadHistory(uid));
  }, [uid]);

  useEffect(() => { saveHistory(uid, messages); }, [uid, messages]);

  const showToast = useCallback((text) => {
    clearTimeout(toastTimer.current);
    setToast(text);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_MS);
  }, []);
  useEffect(() => () => clearTimeout(toastTimer.current), []);

  // Gulir ke bawah saat ada pesan baru / bot mengetik / panel dibuka. Edit pesan
  // lama (tombol ditekan) tidak menggulir, seperti Telegram.
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el || !open) return;
    if (messages.length !== lastCount.current || pending === 'message' || pending === 'photo') {
      el.scrollTop = el.scrollHeight;
    }
    lastCount.current = messages.length;
  }, [messages.length, pending, open]);

  // Panel baru dirender saat fase 'opening' — baru saat itu daftar pesan ada.
  const opening = phase === 'opening';
  useLayoutEffect(() => {
    if (opening && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [opening]);

  // Desktop: langsung siap mengetik. Mobile tidak, supaya keyboard tidak
  // menutupi riwayat saat chat baru dibuka.
  useEffect(() => {
    if (phase === 'open' && isDesktop()) inputRef.current?.focus();
  }, [phase]);

  useEffect(() => {
    if (!open) return;
    const onKey = e => { if (e.key === 'Escape') close(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, close]);

  // Kunci gulir halaman di belakang sheet (mobile); dilepas saat layar diputar
  // ke lebar ≥768px dan chat menjadi panel samping.
  useEffect(() => {
    if (!open || vp.desktop) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open, vp.desktop]);

  // Tinggi kotak ketik mengikuti isi (maks ±4 baris).
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 112)}px`;
  }, [input]);

  const receive = useCallback((ops) => {
    setMessages(m => applyOps(m, ops).messages);
    const toasts = ops.filter(o => o?.type === 'toast' && o.text);
    if (toasts.length) showToast(toasts[toasts.length - 1].text);
    if (looksLikeChange(ops)) window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
  }, [showToast]);

  // AI Advisor proaktif (S16): saat panel dibuka, tarik item hari ini. Server yang membatasi
  // (sekali per hari, maks 2 permukaan), jadi buka-tutup panel tidak menggandakan pesan.
  // Tidak dibatalkan saat panel ditutup: server sudah mencatatnya terkirim, jadi tetap disimpan.
  useEffect(() => {
    if (!open || !uid) return;
    api.chatProaktif().then(res => {
      if (res.ok && res.ops.length) receive(res.ops);
    });
  }, [open, uid, receive]);

  const deliver = useCallback(async (msg) => {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      setMessages(m => setStatus(m, msg.id, 'failed'));
      showToast('Kamu sedang offline. Pesan belum terkirim.');
      return;
    }
    setMessages(m => setStatus(m, msg.id, 'sending'));
    setPending('message');
    const res = await api.chatSend(msg.text, msg.id);
    setPending(null);
    if (!res.ok) {
      setMessages(m => setStatus(m, msg.id, 'failed'));
      showToast(res.error);
      return;
    }
    setMessages(m => setStatus(m, msg.id, undefined));
    receive(res.ops);
  }, [receive, showToast]);

  // Foto struk → alur scan struk bot (sama dengan kirim foto ke @JatahkuBot).
  const deliverPhoto = useCallback(async (msg) => {
    const blob = photoFiles.current.get(msg.id);
    if (!blob) { showToast('Foto sudah tidak tersimpan. Pilih ulang fotonya.'); return; }
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      setMessages(m => setStatus(m, msg.id, 'failed'));
      showToast('Kamu sedang offline. Foto belum terkirim.');
      return;
    }
    setMessages(m => setStatus(m, msg.id, 'sending'));
    setPending('photo');
    const res = await api.chatPhoto(blob, msg.id);
    setPending(null);
    if (!res.ok) {
      setMessages(m => setStatus(m, msg.id, 'failed'));
      showToast(res.error);
      return;
    }
    photoFiles.current.delete(msg.id);
    setMessages(m => setStatus(m, msg.id, undefined));
    receive(res.ops);
  }, [receive, showToast]);

  const onPickPhoto = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // foto yang sama bisa dipilih ulang
    if (!file || pending) return;
    if (!file.type.startsWith('image/')) { showToast('Pilih file foto (JPG/PNG)'); return; }
    setPending('photo');
    let blob;
    try {
      blob = await compressImage(file);
    } catch {
      setPending(null);
      showToast('Foto tidak bisa dibuka. Coba foto ulang atau pilih format JPG.');
      return;
    }
    const msg = userPhotoMessage(await thumbnailDataUrl(blob));
    photoFiles.current.set(msg.id, blob);
    setMessages(m => [...m, msg]);
    setPending(null);
    deliverPhoto(msg);
  };

  const retry = (m) => {
    if (pending) return;
    if (m.kind === 'photo') deliverPhoto(m); else deliver(m);
  };

  const send = useCallback((raw) => {
    const text = (raw ?? '').trim();
    if (!text || pending) return;
    const msg = userMessage(text);
    setMessages(m => [...m, msg]);
    setInput('');
    deliver(msg);
  }, [pending, deliver]);

  // Draf baru dari CTA: pasang sekali per nonce. Kalau bot masih menjawab, teks
  // hanya diisikan ke kotak ketik supaya tidak hilang.
  useEffect(() => {
    if (!draft || draftSeen.current === draft.nonce) return;
    draftSeen.current = draft.nonce;
    setDraftChips(draft.chips || []);
    if (!draft.text) return;
    if (draft.send && !pending) { send(draft.text); return; }
    setInput(draft.text);
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [draft, pending, send]);

  const press = async (msg, btn) => {
    if (btn.url) {
      const href = safeHref(btn.url);
      if (href) openLink(null, href);
      return;
    }
    if (pending || !btn.data) return;
    setPending(`${msg.id}:${btn.data}`);
    const res = await api.chatAction(msg.id, btn.data);
    setPending(null);
    if (!res.ok) { showToast(res.error); return; }
    receive(res.ops);
  };

  const openLink = (e, href) => {
    const path = inAppPath(href, window.location.host);
    if (path) {
      e?.preventDefault();
      if (!isDesktop()) {
        // Ganti entri riwayat milik chat, supaya Back dari halaman itu tidak
        // kembali ke entri chat yang sudah tertutup.
        const replace = pushedRef.current && !!window.history.state?.jatahkuChat;
        pushedRef.current = false;
        navigate(path, { replace });
        onClose();
      } else {
        navigate(path);
      }
    } else if (!e) {
      window.open(href, '_blank', 'noopener,noreferrer');
    }
  };

  // Perintah di teks balasan: kirim langsung, kecuali yang butuh argumen atau
  // mengubah data — itu diisikan ke kotak ketik dulu.
  const onCommand = (cmd) => {
    if (PREFILL_COMMANDS.has(cmd.slice(1))) {
      setInput(`${cmd} `);
      inputRef.current?.focus();
      return;
    }
    send(cmd);
  };

  const onExample = (ex) => {
    if (ex.send) { send(ex.text); return; }
    setInput(ex.text);
    inputRef.current?.focus();
  };

  const clearChat = () => {
    if (!messages.length) return;
    if (!window.confirm('Hapus riwayat chat di perangkat ini? Transaksi yang sudah tercatat tidak terhapus.')) return;
    clearHistory(uid);
    setMessages([]);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(input);
    }
  };

  if (phase === 'closed') return null;
  const shown = phase === 'open';

  return (
    <>
      {/* Latar redup di mobile — ketuk untuk menutup */}
      <div
        className={`md:hidden fixed inset-0 z-[69] bg-black/30 transition-opacity duration-300 motion-reduce:transition-none ${shown ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
        onClick={close}
        aria-hidden="true"
      />
    <div
      ref={sheetRef}
      className={`fixed inset-x-0 bottom-0 z-[70] rounded-t-3xl overflow-hidden shadow-2xl
        md:left-auto md:top-14 lg:top-[88px] md:w-[420px] md:rounded-none md:border-l md:border-gray-100
        bg-page flex flex-col transition-[transform,height] duration-300 ease-[cubic-bezier(.32,.72,0,1)] motion-reduce:transition-none
        ${shown ? 'translate-y-0 md:translate-x-0' : 'translate-y-full md:translate-y-0 md:translate-x-full'}`}
      role="dialog"
      aria-modal={!isDesktop()}
      aria-label="Chat Jatahku"
    >
      {/* Header — di mobile juga pegangan untuk ditarik ke bawah */}
      <div
        className="bg-white border-b border-gray-100 shrink-0 touch-none md:touch-auto select-none md:select-auto"
        onPointerDown={onDragStart}
        onPointerMove={onDragMove}
        onPointerUp={onDragEnd}
        onPointerCancel={onDragEnd}
      >
        <div className="md:hidden flex justify-center">
          <button type="button" onClick={toggleSize}
            className="px-6 pt-2 pb-1"
            aria-label={sheetMode === 'full' ? 'Perkecil chat' : 'Perbesar chat'}
            title={sheetMode === 'full' ? 'Perkecil' : 'Perbesar'}>
            <span className="block w-10 h-1.5 rounded-full bg-gray-300" />
          </button>
        </div>
        <div className="h-14 px-3 flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl text-white flex items-center justify-center shrink-0"
            style={{ background: 'linear-gradient(145deg,#1D9E75,#0F6E56)' }}>
            <Icon name="chat" size={20} weight="fill" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-display font-bold text-[15px] leading-tight">Chat Jatahku</p>
            <p className="text-[11.5px] text-gray-400 leading-tight truncate">
              {pending === 'message' ? 'mengetik…' : pending === 'photo' ? 'membaca struk…' : 'Catat & cek jatah, sama seperti di Telegram'}
            </p>
          </div>
          <button type="button" onClick={clearChat} disabled={!messages.length}
            className="w-9 h-9 flex items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-40"
            title="Hapus riwayat chat" aria-label="Hapus riwayat chat">
            <Icon name="clear" size={19} />
          </button>
          <button type="button" onClick={close} className="hidden md:flex w-9 h-9 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600" aria-label="Tutup chat">
            <Icon name="close" size={20} weight="bold" />
          </button>
        </div>
      </div>

      {/* Pesan */}
      <div className="relative flex-1 min-h-0">
        {toast && (
          <div className="absolute top-3 inset-x-0 z-10 flex justify-center pointer-events-none px-4">
            <div className="px-3.5 py-2 rounded-full text-xs font-medium shadow-lg"
              style={{ animation: 'fadeIn .15s ease-out', background: 'var(--text)', color: 'var(--page)' }}
              role="status">{toast}</div>
          </div>
        )}
        <div ref={listRef} className="h-full overflow-y-auto overscroll-contain px-3 py-4 space-y-2.5"
          onScroll={e => { const el = e.currentTarget; atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}>
          {messages.length === 0 && <Welcome name={firstName} onExample={onExample} />}
          {messages.map((m, idx) => {
            const prev = messages[idx - 1];
            const newDay = !prev || new Date(prev.ts).toDateString() !== new Date(m.ts).toDateString();
            const mine = m.role === 'user';
            return (
              <Fragment key={m.id}>
                {newDay && (
                  <div className="flex justify-center py-1">
                    <span className="text-[11px] text-gray-400 px-2.5 py-0.5 rounded-full bg-gray-100">{dayLabel(m.ts)}</span>
                  </div>
                )}
                <div className={`flex flex-col ${mine ? 'items-end' : 'items-start'}`}>
                  <div className={`max-w-[85%] px-3.5 py-2 text-[14px] leading-[1.5] whitespace-pre-wrap break-words shadow-sm ${
                    mine
                      ? 'chat-mine bg-brand-600 text-white rounded-2xl rounded-tr-md'
                      : 'bg-white border border-gray-100 rounded-2xl rounded-tl-md text-gray-800'
                  } ${m.status === 'sending' ? 'opacity-70' : ''}`}>
                    {mine && m.kind === 'photo' ? (
                      m.thumb
                        ? <img src={m.thumb} alt="Foto struk" className="block max-w-[180px] max-h-60 rounded-xl -mx-1 -mt-0.5 object-cover" />
                        : m.text
                    ) : mine ? m.text : (
                      <BotText text={m.text} format={m.format} onCommand={onCommand} onLink={openLink} />
                    )}
                    <span className={`block text-right text-[10px] mt-0.5 ${mine ? 'text-white/70' : 'text-gray-400'}`}>
                      {m.edited && !mine ? 'diubah · ' : ''}{timeLabel(m.ts)}
                    </span>
                  </div>
                  {mine && m.status === 'failed' && (m.kind !== 'photo' || photoFiles.current.has(m.id)) && (
                    <button type="button" onClick={() => retry(m)}
                      className="mt-1 inline-flex items-center gap-1 text-[11.5px] text-red-500 hover:underline">
                      <Icon name="retry" size={13} weight="bold" /> Gagal terkirim · Kirim ulang
                    </button>
                  )}
                  {mine && m.status === 'failed' && m.kind === 'photo' && !photoFiles.current.has(m.id) && (
                    <span className="mt-1 text-[11.5px] text-red-500">Gagal terkirim · pilih ulang fotonya</span>
                  )}
                  {!mine && m.buttons?.length > 0 && (
                    <div className="mt-1.5 w-full max-w-[85%] space-y-1.5">
                      {m.buttons.map((row, r) => (
                        <div key={r} className="flex gap-1.5">
                          {row.map((b, c) => {
                            const busy = pending === `${m.id}:${b.data}`;
                            return (
                              <button key={c} type="button" onClick={() => press(m, b)} disabled={!!pending}
                                className="flex-1 min-w-0 px-3 py-2 rounded-xl border border-brand-200 bg-white text-brand-600 text-[13px] font-medium hover:bg-brand-50 active:scale-[0.98] transition-all disabled:opacity-60 disabled:active:scale-100">
                                <span className="inline-flex items-center justify-center gap-1.5 max-w-full">
                                  {busy && <span className="w-3 h-3 rounded-full border-2 border-brand-400 border-t-transparent animate-spin shrink-0" />}
                                  <span className="truncate"><ChatText text={b.text} size={15} /></span>
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </Fragment>
            );
          })}
          {(pending === 'message' || pending === 'photo') && <TypingBubble />}
        </div>
      </div>

      {/* Kotak ketik */}
      <div className="bg-white border-t border-gray-100 shrink-0" style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}>
        <div className="flex items-center gap-2 px-3 pt-2 overflow-x-auto no-scrollbar">
          <VoiceInput
            onTranscript={t => { setInput(prev => (prev ? `${prev} ${t}` : t)); inputRef.current?.focus(); }}
            onError={showToast}
            disabled={!!pending}
          />
          {/* Foto struk: kamera atau galeri (HP menawarkan keduanya) */}
          <button type="button" onClick={() => fileRef.current?.click()} disabled={!!pending}
            className="inline-flex items-center gap-1.5 text-xs text-brand-600 hover:text-brand-700 disabled:opacity-50 shrink-0"
            title="Catat dari foto struk" aria-label="Kirim foto struk">
            <Icon name="camera" size={16} /> Struk
          </button>
          <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onPickPhoto}
            aria-hidden="true" tabIndex={-1} />
          <span className="w-px h-4 bg-gray-200 shrink-0" />
          {/* Chip cepat (§6H): dari insight dulu, lalu pertanyaan halaman ini (lib/chatChips) */}
          {quickChips(pathname, draftChips).map(q => (
            <button key={`${q.draft ? 'd' : 'q'}-${q.text}`} type="button" disabled={!!pending}
              onClick={() => {
                if (!q.fill) { send(q.text); return; }
                setInput(q.text);
                inputRef.current?.focus();
              }}
              className={q.draft
                ? 'shrink-0 px-2.5 py-1 rounded-full border border-brand-200 bg-brand-50 text-xs text-brand-700 hover:border-brand-400 disabled:opacity-50 whitespace-nowrap'
                : 'shrink-0 px-2.5 py-1 rounded-full border border-gray-200 text-xs text-gray-600 hover:border-brand-400 hover:text-brand-600 disabled:opacity-50 whitespace-nowrap'}>
              {q.label}
            </button>
          ))}
        </div>
        <form className="flex items-end gap-2 p-3" onSubmit={e => { e.preventDefault(); send(input); }}>
          {/* Tutup di jangkauan jempol (mobile); desktop memakai X di header */}
          <button type="button" onClick={close}
            className="md:hidden w-11 h-11 shrink-0 rounded-xl bg-gray-100 border border-gray-200 text-gray-500 flex items-center justify-center active:scale-95 transition-transform"
            aria-label="Tutup chat" title="Tutup chat">
            <Icon name="chevron" size={22} weight="bold" />
          </button>
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            enterKeyHint="send"
            maxLength={500}
            placeholder="Ketik: kopi 35k, sisa, /status…"
            className="input resize-none leading-snug py-2.5 max-h-28"
            aria-label="Pesan untuk bot"
          />
          <button type="submit" disabled={!input.trim() || !!pending}
            className="w-11 h-11 shrink-0 rounded-xl text-white flex items-center justify-center transition-all active:scale-95 disabled:opacity-40 disabled:active:scale-100"
            style={{ background: 'linear-gradient(145deg,#1D9E75,#0F6E56)' }}
            aria-label="Kirim">
            <Icon name="send" size={20} weight="fill" />
          </button>
        </form>
      </div>
    </div>
    </>
  );
}
