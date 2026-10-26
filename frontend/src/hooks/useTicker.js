import { useEffect, useState } from 'react';

// Waktu terbaru (Date.now()) yang diperbarui tiap `ms` selama `active`.
// Dipakai untuk menghitung lama sebuah tahap berjalan tanpa menyimpan timer di tiap komponen.
export function useTicker(active, ms = 500) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return undefined;
    setNow(Date.now()); // nilai lama dari sebelum aktif jangan dipakai
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [active, ms]);

  return now;
}
