import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { compressImage } from '../lib/receiptImage';
import {
  STAGE, failureMessage, checkScanFile, offlineFailure, uploadTimeoutMs, needsPdfSniff, isPdfHead, asPdfFile,
  PDF_HEAD_BYTES,
} from '../lib/receiptProgress';

// Alur baca struk dengan tahap yang terlihat:
//   foto → MENYIAPKAN (kompres) → MENGUNGGAH (progres) → MEMBACA (server) → onResult(hasil) → IDLE
//   PDF  → MENGUNGGAH (file asli dengan namanya, tanpa kompres & gambar kecil) → MEMBACA → onResult(hasil) → IDLE
// Gagal di tahap mana pun → FAILED + pesan sesuai tahap; retry() mengulang unggah dengan
// file yang sudah disiapkan (tanpa kompres ulang). Aturan file (jenis, batas PDF, PDF tanpa tipe, batas waktu
// unggah): receiptProgress.
//
// onResult(hasilApi)  : saat struk berhasil dibaca.
// onBusyChange(bool)  : true selama MENYIAPKAN/MENGUNGGAH/MEMBACA; false saat IDLE, FAILED, dan saat dilepas.
// allowPdf            : PDF boleh dibaca (saklar `receipt_inbox`); tanpa itu PDF ditolak seperti dulu.
// state.noun          : 'struk' (foto) | 'bukti' (PDF) — kata benda teks tahap di ReceiptStatusCard.
const BUSY_STAGES = new Set([STAGE.PREPARING, STAGE.UPLOADING, STAGE.READING]);

// Isian awal tiap pemindaian baru (tanpa stage & stageStartedAt: itu diatur per pemanggilan).
const FRESH = { percent: null, progressSeen: false, thumbUrl: null, failure: null, noun: 'struk' };
const IDLE_STATE = { ...FRESH, stage: STAGE.IDLE, stageStartedAt: 0 };

// Byte awal file untuk receiptProgress.isPdfHead (I/O tipis). Gagal dibaca → null (tidak dikenali sebagai PDF).
async function readHead(file) {
  try {
    return new Uint8Array(await file.slice(0, PDF_HEAD_BYTES).arrayBuffer());
  } catch {
    return null;
  }
}

export function useReceiptScan({ onResult, onBusyChange, allowPdf = false } = {}) {
  const [state, setState] = useState(IDLE_STATE);
  // Sumber kebenaran untuk callback async: state React bisa basi di dalam closure.
  const stateRef = useRef(IDLE_STATE);
  const mountedRef = useRef(true);
  const runRef = useRef(0); // nomor pemindaian; hasil dari pemindaian yang sudah digantikan diabaikan
  const blobRef = useRef(null); // file siap kirim untuk retry(): foto terkompres, atau PDF asli
  const fileRef = useRef(null); // file asli, hanya ditahan bila gagal sebelum sempat disiapkan (offline)
  const busyRef = useRef(false);
  const resultCbRef = useRef(onResult);
  resultCbRef.current = onResult;
  const busyCbRef = useRef(onBusyChange);
  busyCbRef.current = onBusyChange;
  const allowPdfRef = useRef(allowPdf);
  allowPdfRef.current = allowPdf;

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
      // Foto: 60 dtk seperti dulu; PDF besar mendapat waktu unggah lebih lama.
      timeoutMs: uploadTimeoutMs(blob),
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
        noun: stateRef.current.noun,
      }),
    });
  };

  const scanFile = useCallback(async (picked) => {
    if (!picked || !mountedRef.current) return;
    const run = (runRef.current += 1);
    const alive = () => mountedRef.current && runRef.current === run;

    releaseThumb();
    blobRef.current = null;
    fileRef.current = null;

    // Saklar menyala dan file tanpa tipe berguna: PDF dikenali dari isinya, lalu diberi tipe application/pdf.
    // Selain itu (termasuk saklar mati) tidak ada yang dibaca dan tidak ada jeda: file dipakai apa adanya.
    let file = picked;
    if (needsPdfSniff(picked, { allowPdf: allowPdfRef.current })) {
      const head = await readHead(picked);
      if (!alive()) return;
      if (isPdfHead(head)) file = asPdfFile(picked);
    }

    const { kind, noun, failure } = checkScanFile(file, { allowPdf: allowPdfRef.current });
    if (failure) {
      apply({ ...FRESH, noun, stage: STAGE.FAILED, failure });
      return;
    }
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      fileRef.current = file; // retry() memulai dari awal karena belum ada file yang disiapkan
      apply({ ...FRESH, noun, stage: STAGE.FAILED, failure: offlineFailure(noun) });
      return;
    }

    if (kind === 'pdf') {
      // PDF dikirim apa adanya dengan nama aslinya: tanpa kompres, dan tanpa gambar kecil (bukan foto).
      blobRef.current = file;
      apply({ ...FRESH, noun, stage: STAGE.UPLOADING, stageStartedAt: Date.now() });
      await upload(file, run);
      return;
    }

    apply({ ...FRESH, noun, stage: STAGE.PREPARING, stageStartedAt: Date.now() });
    let blob;
    try {
      blob = await compressImage(file);
    } catch {
      if (alive()) apply({ stage: STAGE.FAILED, failure: failureMessage({ stage: STAGE.PREPARING, noun }) });
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
