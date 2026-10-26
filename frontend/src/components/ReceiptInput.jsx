import { native } from '../native';
import { Icon } from './Icon';

const OFFLINE_MSG = 'Butuh koneksi internet untuk scan struk';
const PICK_FAILED_MSG = 'Foto tidak bisa diambil, coba lagi';

// Buka kamera ('camera') atau galeri ('gallery'). HARUS dipanggil langsung di dalam
// handler ketukan: tidak boleh ada await sebelum native.camera.* (iPhone Safari menolak
// membuka kamera dari tempat lain). Dibatalkan (null) → tidak melakukan apa-apa.
// Offline → onError(pesan) dan kamera tidak dibuka.
export function pickReceiptPhoto(source, { onFile, onError }) {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    onError?.(OFFLINE_MSG);
    return;
  }
  let pending;
  try {
    pending = source === 'camera' ? native.camera.takePhoto() : native.camera.pickPhoto();
  } catch {
    onError?.(PICK_FAILED_MSG);
    return;
  }
  Promise.resolve(pending).then(
    (file) => { if (file) onFile(file); },
    () => onError?.(PICK_FAILED_MSG),
  );
}

// Tombol ambil foto struk. Hanya memilih foto: pembacaannya oleh useReceiptScan
// (onFile = scan.scanFile), tahapnya ditampilkan ReceiptStatusCard.
//   size="sm": dua tombol teks kecil "Foto" / "Galeri" (form Catat)
//   size="lg": tombol utama "Ambil foto struk" + tautan "pilih dari galeri"
export default function ReceiptInput({ onFile, onError, disabled = false, size = 'sm' }) {
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
    </span>
  );
}
