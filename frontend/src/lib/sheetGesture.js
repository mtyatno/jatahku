// Bottom sheet chat di mobile: dua tinggi (setengah layar & penuh), ditarik
// dengan jempol. Semua fungsi murni — dipakai ChatPanel dan diuji terpisah.

export const DRAG_SLOP = 6;   // px — di bawah ini masih dianggap ketukan
export const TOP_GAP = 12;    // px — celah di atas sheet penuh (di bawah safe area)
export const PROJECT_MS = 180; // ms — proyeksi kibasan ke depan saat memilih posisi
const KEYBOARD_MIN = 80;       // px — selisih lebih kecil = bilah browser, bukan keyboard

// Tinggi sheet dari tinggi layar HP yang sedang dipakai.
// `screenH` = tinggi layar tanpa keyboard; `availH` = ruang di atas keyboard.
export function sheetHeights(screenH, safeTop = 0, availH = screenH) {
  const full = Math.max(0, Math.round(availH - safeTop - TOP_GAP));
  const half = Math.min(full, Math.round(screenH / 2));
  return { full, half };
}

// Tinggi keyboard virtual dari Visual Viewport API (0 bila tertutup / tidak ada).
export function keyboardInset(innerH, vvHeight, vvOffsetTop = 0) {
  if (!vvHeight) return 0;
  const d = innerH - vvHeight - vvOffsetTop;
  return d > KEYBOARD_MIN ? Math.round(d) : 0;
}

// Tinggi yang ditampilkan saat menarik: di atas penuh ditahan (efek karet).
export function dragHeight(startH, dy, full) {
  const h = startH - dy;
  return h > full ? full + (h - full) * 0.2 : Math.max(0, h);
}

// Posisi akhir setelah dilepas: tinggi terdekat dari [tutup, setengah, penuh],
// memperhitungkan kibasan (velocity px/ms, positif = ditarik ke atas).
export function pickSnap(h, velocity, { full, half }) {
  const projected = h + velocity * PROJECT_MS;
  const snaps = [
    ['closed', 0],
    ['half', half],
    ['full', full],
  ];
  let best = snaps[0];
  for (const s of snaps) {
    if (Math.abs(projected - s[1]) < Math.abs(projected - best[1])) best = s;
  }
  return best[0];
}
