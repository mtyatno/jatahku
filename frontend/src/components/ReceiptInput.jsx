import { native } from '../native';
import { pickMessages } from '../lib/receiptProgress';
import { Icon } from './Icon';

// Buka kamera ('camera'), galeri ('gallery'), atau pemilih dokumen gambar/PDF ('document', tombol PDF).
// HARUS dipanggil langsung di dalam handler ketukan: tidak boleh ada await sebelum native.camera.* /
// native.files.pickDocument (iPhone Safari menolak membuka kamera/pemilih file dari tempat lain).
// Dibatalkan (null) → tidak melakukan apa-apa. Offline → onError(pesan) dan pemilih tidak dibuka.
export function pickReceiptPhoto(source, { onFile, onError }) {
  const msg = pickMessages(source);
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    onError?.(msg.offline);
    return;
  }
  let pending;
  try {
    pending = source === 'document' ? native.files.pickDocument()
      : source === 'camera' ? native.camera.takePhoto() : native.camera.pickPhoto();
  } catch {
    onError?.(msg.failed);
    return;
  }
  Promise.resolve(pending).then(
    (file) => { if (file) onFile(file); },
    () => onError?.(msg.failed),
  );
}

// Tombol ambil foto struk. Hanya memilih file: pembacaannya oleh useReceiptScan
// (onFile = scan.scanFile), tahapnya ditampilkan ReceiptStatusCard.
//   size="sm": tombol teks kecil "Foto" / "Galeri", plus "PDF" bila allowPdf (form Catat)
//   size="lg": tombol utama "Ambil foto struk" + tautan "pilih dari galeri"
// allowPdf: tombol PDF (bukti bayar PDF atau gambar), hanya saat saklar `receipt_inbox` menyala.
export default function ReceiptInput({ onFile, onError, disabled = false, size = 'sm', allowPdf = false }) {
  const pick = (source) => pickReceiptPhoto(source, { onFile, onError });

  if (size === 'lg') {
    return (
      <div className="flex flex-col items-center gap-2">
        <button
          type="button"
          onClick={() => pick('camera')}
          disabled={disabled}
          className="btn-primary inline-flex items-center gap-2 disabled:opacity-50"
        >
          <Icon name="camera" size={18} /> Ambil foto struk
        </button>
        <button
          type="button"
          onClick={() => pick('gallery')}
          disabled={disabled}
          className="text-xs text-brand-600 hover:text-brand-700 underline disabled:opacity-50"
        >
          pilih dari galeri
        </button>
      </div>
    );
  }

  const btn = 'inline-flex items-center gap-1.5 text-xs text-brand-600 hover:text-brand-700 disabled:opacity-50';
  return (
    <span className="inline-flex items-center gap-3 shrink-0">
      <button
        type="button"
        onClick={() => pick('camera')}
        disabled={disabled}
        className={btn}
        title="Foto struk dengan kamera"
      >
        <Icon name="camera" size={16} /> Foto
      </button>
      <button
        type="button"
        onClick={() => pick('gallery')}
        disabled={disabled}
        className={btn}
        title="Pilih foto struk dari galeri"
      >
        <Icon name="gallery" size={16} /> Galeri
      </button>
      {allowPdf && (
        <button
          type="button"
          onClick={() => pick('document')}
          disabled={disabled}
          className={btn}
          title="Pilih PDF bukti bayar"
        >
          <Icon name="file" size={16} /> PDF
        </button>
      )}
    </span>
  );
}
