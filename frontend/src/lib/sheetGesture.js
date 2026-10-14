// Gestur tarik-ke-bawah untuk menutup bottom sheet (panel chat di mobile).

export const DISMISS_DISTANCE = 110; // px — tarik cukup jauh
export const DISMISS_VELOCITY = 0.6; // px/ms — atau kibas cepat
const FLICK_MIN_DISTANCE = 30;       // kibasan pendek sekali tidak dihitung
export const DRAG_SLOP = 6;          // px — di bawah ini masih dianggap ketukan

// Geser yang ditampilkan saat menarik: ke bawah 1:1, ke atas ditahan.
export function dragOffset(dy) {
  return dy > 0 ? dy : 0;
}

export function shouldDismiss(dy, durationMs) {
  if (dy >= DISMISS_DISTANCE) return true;
  const velocity = durationMs > 0 ? dy / durationMs : 0;
  return dy >= FLICK_MIN_DISTANCE && velocity >= DISMISS_VELOCITY;
}
