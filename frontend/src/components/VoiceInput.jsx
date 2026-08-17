import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { Icon } from './Icon';

const MAX_RECORD_MS = 60_000;

// Tombol input suara. 3 state: idle → recording → transcribing.
// Setelah transkripsi: panggil onTranscript(text); error: onError(pesan).
export default function VoiceInput({ onTranscript, onError, disabled = false }) {
  const [state, setState] = useState('idle'); // idle | recording | transcribing
  const mediaRef = useRef(null);   // MediaRecorder
  const streamRef = useRef(null);  // MediaStream
  const chunksRef = useRef([]);
  const timerRef = useRef(null);
  const startingRef = useRef(false); // guard re-entry saat await getUserMedia
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimeout(timerRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
    };
  }, []);

  const start = async () => {
    if (startingRef.current || mediaRef.current) return; // jaga double-start
    startingRef.current = true;
    try {
      if (!navigator.mediaDevices?.getUserMedia) { onError('Browser tidak mendukung rekam suara'); return; }
      if (!navigator.onLine) { onError('Butuh koneksi internet untuk input suara'); return; }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
        .find(m => window.MediaRecorder && MediaRecorder.isTypeSupported(m));
      if (!mime) {
        stream.getTracks().forEach(t => t.stop());
        streamRef.current = null;
        onError('Browser tidak mendukung rekam suara');
        return;
      }
      const rec = new MediaRecorder(stream, { mimeType: mime });
      mediaRef.current = rec;
      chunksRef.current = [];
      rec.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onerror = () => {
        streamRef.current?.getTracks().forEach(t => t.stop());
        streamRef.current = null;
        mediaRef.current = null;
        clearTimeout(timerRef.current);
        setState('idle');
        onError('Gagal merekam. Coba lagi.');
      };
      rec.onstop = finish;
      rec.start();
      setState('recording');
      timerRef.current = setTimeout(() => mediaRef.current?.stop(), MAX_RECORD_MS);
    } catch (err) {
      const denied = err && (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError');
      onError(denied
        ? 'Izin mikrofon ditolak. Aktifkan izin mikrofon di pengaturan browser, atau ketik manual.'
        : 'Gagal memulai rekaman. Coba lagi.');
    } finally {
      startingRef.current = false;
    }
  };

  const stop = () => {
    if (mediaRef.current?.state !== 'recording') return; // jaga double-stop
    clearTimeout(timerRef.current);
    mediaRef.current.stop();
  };

  const finish = async () => {
    clearTimeout(timerRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    mediaRef.current = null;
    const blob = new Blob(chunksRef.current, { type: chunksRef.current[0]?.type || 'audio/webm' });
    chunksRef.current = [];
    if (!mountedRef.current) return; // komponen sudah unmount — buang hasil
    if (blob.size === 0) { setState('idle'); onError('Tidak ada suara terdeteksi, coba lagi'); return; }
    setState('transcribing');
    let res;
    try {
      res = await api.transcribe(blob);
    } catch {
      if (!mountedRef.current) return;
      setState('idle');
      onError('Transkripsi gagal, coba lagi');
      return;
    }
    if (!mountedRef.current) return; // unmount saat transkripsi berjalan
    if (res.ok && res.data.text) {
      setState('idle');
      onTranscript(res.data.text);
    } else {
      setState('idle');
      onError(res.data?.detail || 'Transkripsi gagal, coba lagi');
    }
  };

  if (state === 'transcribing') {
    return (
      <button type="button" disabled className="inline-flex items-center gap-1.5 text-xs text-gray-400">
        <Icon name="mic" size={16} /> Mendengarkan...
      </button>
    );
  }

  if (state === 'recording') {
    return (
      <button type="button" onClick={stop} className="inline-flex items-center gap-1.5 text-xs text-red-600 shrink-0">
        <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
        <Icon name="stop" size={16} /> Selesai
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={start}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 text-xs text-brand-600 hover:text-brand-700 disabled:opacity-50 shrink-0"
      title="Catat via suara"
    >
      <Icon name="mic" size={16} /> Suara
    </button>
  );
}
