import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { compressImage } from '../lib/receiptImage';
import { Icon } from './Icon';

// Tombol "Struk": pilih/ambil foto → kompres → scan di server.
// onResult(hasilApi) saat berhasil; onError(pesan) saat gagal.
// onBusyChange(bool): true selama membaca struk (induk menahan tombol Simpan).
export default function ReceiptInput({ onResult, onError, onBusyChange, disabled = false }) {
  const [scanning, setScanning] = useState(false);
  const inputRef = useRef(null);
  const mountedRef = useRef(true);
  const busyCbRef = useRef(onBusyChange);
  busyCbRef.current = onBusyChange;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      busyCbRef.current?.(false);
    };
  }, []);

  useEffect(() => {
    busyCbRef.current?.(scanning);
  }, [scanning]);

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // supaya foto yang sama bisa dipilih ulang
    if (!file) return;
    if (!navigator.onLine) { onError('Butuh koneksi internet untuk scan struk'); return; }
    if (!file.type.startsWith('image/')) { onError('Pilih file foto (JPG/PNG)'); return; }
    setScanning(true);
    let blob;
    try {
      blob = await compressImage(file);
    } catch {
      if (mountedRef.current) setScanning(false);
      onError('Foto tidak bisa dibuka. Coba foto ulang atau pilih format JPG.');
      return;
    }
    const res = await api.scanReceipt(blob);
    if (!mountedRef.current) return;
    setScanning(false);
    if (res.ok) onResult(res.data);
    else onError(res.data?.detail || 'Scan struk gagal, coba lagi');
  };

  if (scanning) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-gray-400 shrink-0" role="status">
        <Icon name="camera" size={16} /> Membaca struk...
      </span>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={disabled}
        className="inline-flex items-center gap-1.5 text-xs text-brand-600 hover:text-brand-700 disabled:opacity-50 shrink-0"
        title="Catat dari foto struk"
      >
        <Icon name="camera" size={16} /> Struk
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleFile}
        aria-label="Foto struk"
      />
    </>
  );
}
