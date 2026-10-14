import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { PREFILL_COMMANDS, formatBotText, inAppPath, safeHref } from '../lib/chatFormat';
import {
  applyOps, clearHistory, loadHistory, looksLikeChange, saveHistory, setStatus, userMessage,
} from '../lib/chatHistory';
import { Icon } from './Icon';
import VoiceInput from './VoiceInput';

// Chat bot Jatahku di dalam webapp: otak yang sama dengan @JatahkuBot di
// Telegram (backend menjalankan handler bot lewat app/bot/web_adapter.py).
// Mobile: layar penuh. Desktop: panel samping, halaman tetap terlihat.

const QUICK = [
  { label: 'Sisa jatah', text: 'sisa' },
  { label: 'Hari ini', text: 'pengeluaran hari ini' },
  { label: 'Limit harian', text: 'limit harian' },
  { label: 'Kapan habis?', text: 'kapan habis' },
  { label: '/status', text: '/status' },
  { label: '/amplop', text: '/amplop' },
  { label: 'Panduan', text: '/help' },
];

// Contoh di layar kosong. Contoh pengeluaran hanya mengisi kotak ketik —
// jangan sampai mengetuk contoh langsung mencatat transaksi sungguhan.
const EXAMPLES = [
  { text: 'kopi 35k', send: false, hint: 'catat pengeluaran' },
  { text: 'makan 30k, parkir 5k', send: false, hint: 'beberapa sekaligus' },
  { text: 'sisa', send: true, hint: 'cek sisa amplop' },
  { text: 'aman gak beli sepatu 400rb?', send: false, hint: 'tanya dulu sebelum beli' },
];

const TOAST_MS = 2800;
const isDesktop = () => typeof window !== 'undefined' && !!window.matchMedia?.('(min-width: 768px)')?.matches;

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
    return cls ? <span key={i} className={cls}>{n.v}</span> : <Fragment key={i}>{n.v}</Fragment>;
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

export default function ChatPanel({ open, onClose }) {
  const { user } = useAuth();
  const navigate = useNavigate();
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
    if (messages.length !== lastCount.current || pending === 'message') {
      el.scrollTop = el.scrollHeight;
    }
    lastCount.current = messages.length;
  }, [messages.length, pending, open]);

  useLayoutEffect(() => {
    if (open && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (isDesktop()) inputRef.current?.focus();
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    // Kunci gulir halaman di belakang panel layar penuh (mobile).
    const prev = document.body.style.overflow;
    if (!isDesktop()) document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

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

  const send = useCallback((raw) => {
    const text = (raw ?? '').trim();
    if (!text || pending) return;
    const msg = userMessage(text);
    setMessages(m => [...m, msg]);
    setInput('');
    deliver(msg);
  }, [pending, deliver]);

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
      navigate(path);
      if (!isDesktop()) onClose();
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

  return (
    <div
      className={`fixed inset-x-0 top-0 h-[100dvh] z-[70] md:left-auto md:top-14 md:bottom-0 md:h-auto md:w-[420px] md:border-l md:border-gray-100 md:shadow-2xl bg-page flex flex-col ${open ? '' : 'hidden'}`}
      role="dialog"
      aria-modal={!isDesktop()}
      aria-label="Chat Jatahku"
    >
      {/* Header */}
      <div className="bg-white border-b border-gray-100 shrink-0" style={{ paddingTop: 'env(safe-area-inset-top)' }}>
        <div className="h-14 px-3 flex items-center gap-3">
          <button type="button" onClick={onClose} className="md:hidden w-9 h-9 -ml-1 flex items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100" aria-label="Tutup chat">
            <Icon name="close" size={22} weight="bold" />
          </button>
          <div className="w-9 h-9 rounded-xl text-white flex items-center justify-center shrink-0"
            style={{ background: 'linear-gradient(145deg,#1D9E75,#0F6E56)' }}>
            <Icon name="chat" size={20} weight="fill" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-display font-bold text-[15px] leading-tight">Chat Jatahku</p>
            <p className="text-[11.5px] text-gray-400 leading-tight truncate">
              {pending === 'message' ? 'mengetik…' : 'Catat & cek jatah, sama seperti di Telegram'}
            </p>
          </div>
          <button type="button" onClick={clearChat} disabled={!messages.length}
            className="w-9 h-9 flex items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-40"
            title="Hapus riwayat chat" aria-label="Hapus riwayat chat">
            <Icon name="clear" size={19} />
          </button>
          <button type="button" onClick={onClose} className="hidden md:flex w-9 h-9 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600" aria-label="Tutup chat">
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
        <div ref={listRef} className="h-full overflow-y-auto overscroll-contain px-3 py-4 space-y-2.5">
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
                    {mine ? m.text : (
                      <BotText text={m.text} format={m.format} onCommand={onCommand} onLink={openLink} />
                    )}
                    <span className={`block text-right text-[10px] mt-0.5 ${mine ? 'text-white/70' : 'text-gray-400'}`}>
                      {m.edited && !mine ? 'diubah · ' : ''}{timeLabel(m.ts)}
                    </span>
                  </div>
                  {mine && m.status === 'failed' && (
                    <button type="button" onClick={() => !pending && deliver(m)}
                      className="mt-1 inline-flex items-center gap-1 text-[11.5px] text-red-500 hover:underline">
                      <Icon name="retry" size={13} weight="bold" /> Gagal terkirim · Kirim ulang
                    </button>
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
                                  <span className="truncate">{b.text}</span>
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
          {pending === 'message' && <TypingBubble />}
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
          <span className="w-px h-4 bg-gray-200 shrink-0" />
          {QUICK.map(q => (
            <button key={q.text} type="button" onClick={() => send(q.text)} disabled={!!pending}
              className="shrink-0 px-2.5 py-1 rounded-full border border-gray-200 text-xs text-gray-600 hover:border-brand-400 hover:text-brand-600 disabled:opacity-50 whitespace-nowrap">
              {q.label}
            </button>
          ))}
        </div>
        <form className="flex items-end gap-2 p-3" onSubmit={e => { e.preventDefault(); send(input); }}>
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
  );
}
