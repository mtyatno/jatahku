// Olah foto struk di browser sebelum upload (butuh DOM: canvas, createImageBitmap).
// Dipakai tombol Struk di form transaksi dan di chat bot.
import { fitDimensions } from './receiptScan';

async function decode(file) {
  try {
    // imageOrientation menghormati rotasi EXIF foto kamera.
    return await createImageBitmap(file, { imageOrientation: 'from-image' });
  } catch {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('decode')); };
      img.src = url;
    });
  }
}

function draw(source, maxSide) {
  const { width, height } = fitDimensions(source.width, source.height, maxSide);
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  canvas.getContext('2d').drawImage(source, 0, 0, width, height);
  return canvas;
}

// Kompres untuk scan: sisi panjang ≤1600px, JPEG 85% (±200–400 KB).
export async function compressImage(file) {
  const source = await decode(file);
  const canvas = draw(source, 1600);
  if (source.close) source.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob(b => (b ? resolve(b) : reject(new Error('encode'))), 'image/jpeg', 0.85)
  );
}

// Pratinjau kecil untuk riwayat chat (data URL ±5 KB). null bila gagal.
export async function thumbnailDataUrl(blob, maxSide = 240) {
  try {
    const source = await decode(blob);
    const canvas = draw(source, maxSide);
    if (source.close) source.close();
    return canvas.toDataURL('image/jpeg', 0.6);
  } catch {
    return null;
  }
}
