import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { compressImage } from '../lib/receiptImage';
import { STAGE, failureMessage } from '../lib/receiptProgress';

// Alur baca struk dengan tahap yang terlihat:
//   foto → MENYIAPKAN (kompres) → MENGUNGGAH (progres) → MEMBACA (server) → onResult(hasil) → IDLE
// Gagal di tahap mana pun → FAILED + pesan sesuai tahap; retry() mengulang unggah dengan
// foto yang sudah disiapkan (tanpa kompres ulang).
//
// onResult(hasilApi)  : saat struk berhasil dibaca.
// onBusyChange(bool)  : true selama MENYIAPKAN/MENGUNGGAH/MEMBACA; false saat IDLE, FAILED, dan saat dilepas.
const BUSY_STAGES = new Set([STAGE.PREPARING, STAGE.UPLOADING, STAGE.READING]);

// Isian awal tiap pemindaian baru (tanpa stage & stageStartedAt: itu diatur per pemanggilan).
const FRESH = { percent: null, progressSeen: false, thumbUrl: null, failure: null };
const IDLE_STATE = { ...FRESH, stage: STAGE.IDLE, stageStartedAt: 0 };

const NOT_IMAGE = { text: 'Pilih file foto (JPG/PNG)', canRetry: false, canRetake: true };
const OFFLINE = { text: 'Butuh koneksi internet untuk scan struk', canRetry: true, canRetake: false };

export function useReceiptScan({ onResult, onBusyChange } = {}) {
  const [state, setState] = useState(IDLE_STATE);
  // Sumber kebenaran untuk callback async: state React bisa basi di dalam closure.
  const stateRef = useRef(IDLE_STATE);
  const mountedRef = useRef(true);
  const runRef = useRef(0); // nomor pemindaian; hasil dari pemindaian yang sudah digantikan diabaikan
  const blobRef = useRef(null); // foto terkompres untuk retry()
  const fileRef = useRef(null); // foto asli, hanya ditahan bila gagal sebelum sempat dikompres (offline)
  const busyRef = useRef(false);
  const resultCbRef = useRef(onResult);
  resultCbRef.current = onResult;
  const busyCbRef = useRef(onBusyChange);
  busyCbRef.current = onBusyChange;

  const setBusy = (busy) => {
    if (busyRef.current === busy) return;
    busyRef.current = busy;
    busyCbRef.current?.(busy);
  };

  // Terapkan perubahan state. stageStartedAt hanya diperbarui saat tahap benar-benar berganti
  // (atau bila patch menyebutkannya, mis. pemindaian baru yang menggantikan yang sedang MENYIAPKAN).
  const apply = (patch) => {
    if (!mountedRef.current) return;
    const prev = stateRef.current;
    const next = { ...prev, ...patch };
    if (next.stage !== prev.stage && !('stageStartedAt' in patch)) next.stageStartedAt = Date.now();
    stateRef.current = next;
    setState(next);
    setBusy(BUSY_STAGES.has(next.stage));
  };

  const releaseThumb = () => {
    const url = stateRef.current.thumbUrl;
    if (!url) return;
    URL.revokeObjectURL(url);
    stateRef.current = { ...stateRef.current, thumbUrl: null };
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      runRef.current += 1; // hasil yang masih di jalan tidak perlu diteruskan
      releaseThumb();
      blobRef.current = null;
      fileRef.current = null;
      busyRef.current = false;
      busyCbRef.current?.(false);
    };
  }, []);

  // Unggah + baca. `run` = nomor pemindaian pemanggil; berhenti bila sudah digantikan/dilepas.
  const upload = async (blob, run) => {
    const alive = () => mountedRef.current && runRef.current === run;
    apply({ stage: STAGE.UPLOADING, percent: null, progressSeen: false, failure: null });

    const res = await api.scanReceipt(blob, {
      // Kirim ulang setelah refresh token memulai progres dari 0 lagi: selalu kembali ke MENGUNGGAH.
      onProgress: (percent) => {
        if (!alive()) return;
        const cur = stateRef.current;
        if (cur.stage === STAGE.UPLOADING && cur.progressSeen && cur.percent === percent) return;
        apply({ stage: STAGE.UPLOADING, percent, progressSeen: true });
      },
      // Bisa terpanggil dua kali (kirim ulang): hanya pindah ke MEMBACA bila belum di sana.
      onUploaded: () => {
        if (!alive() || stateRef.current.stage === STAGE.READING) return;
        apply({ stage: STAGE.READING });
      },
    });
    if (!alive()) return;

    if (res.ok) {
      blobRef.current = null;
      releaseThumb();
      try {
        resultCbRef.current?.(res.data);
      } finally {
        apply({ ...FRESH, stage: STAGE.IDLE });
      }
      return;
    }

    // Pesan gagal ditentukan oleh tahap saat jawaban datang, bukan tahap awal.
    const failedAt = stateRef.current.stage === STAGE.READING ? STAGE.READING : STAGE.UPLOADING;
    apply({
      stage: STAGE.FAILED,
      failure: failureMessage({
        stage: failedAt,
        status: res.status,
        detail: res.data?.detail,
        timedOut: res.timedOut,
      }),
    });
  };

  const scanFile = useCallback(async (file) => {
    if (!file || !mountedRef.current) return;
    const run = (runRef.current += 1);
    const alive = () => mountedRef.current && runRef.current === run;

    releaseThumb();
    blobRef.current = null;
    fileRef.current = null;

    if (!String(file.type || '').startsWith('image/')) {
      apply({ ...FRESH, stage: STAGE.FAILED, failure: NOT_IMAGE });
      return;
    }
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      fileRef.current = file; // retry() memulai dari awal karena belum ada foto terkompres
      apply({ ...FRESH, stage: STAGE.FAILED, failure: OFFLINE });
      return;
    }

    apply({ ...FRESH, stage: STAGE.PREPARING, stageStartedAt: Date.now() });
    let blob;
    try {
      blob = await compressImage(file);
    } catch {
      if (alive()) apply({ stage: STAGE.FAILED, failure: failureMessage({ stage: STAGE.PREPARING }) });
      return;
    }
    if (!alive()) return;

    blobRef.current = blob;
    apply({ thumbUrl: URL.createObjectURL(blob) });
    await upload(blob, run);
  }, []);

  const retry = useCallback(() => {
    if (!mountedRef.current || stateRef.current.stage !== STAGE.FAILED) return;
    if (blobRef.current) {
      const run = (runRef.current += 1);
      upload(blobRef.current, run);
    } else if (fileRef.current) {
      scanFile(fileRef.current);
    }
  }, [scanFile]);

  const reset = useCallback(() => {
    runRef.current += 1; // pemindaian yang masih jalan tidak boleh mengubah state lagi
    releaseThumb();
    blobRef.current = null;
    fileRef.current = null;
    apply({ ...FRESH, stage: STAGE.IDLE });
  }, []);

  return { state, scanFile, retry, reset };
}
