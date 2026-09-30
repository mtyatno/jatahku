// Helper murni modal "Cocokkan saldo" (spec 2026-09-30). Tanpa React/DOM.

export function toNumber(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

export function sumLines(lines) {
  return lines.reduce((s, l) => s + toNumber(l.amount), 0);
}

// Sisa selisih yang belum dibagi (negatif = kelebihan). Dibulatkan ke sen agar
// noise float (0.1 + 0.2) tidak membuat "belum pas"; normalisasi -0 → 0.
export function unassigned(total, lines) {
  const v = Math.round((toNumber(total) - sumLines(lines)) * 100) / 100;
  return v === 0 ? 0 : v;
}

// Semua selisih ke satu amplop; baris lain jadi 0. Target di luar daftar ditambahkan.
export function allToOne(lines, target, total) {
  const next = lines.map(l => ({ ...l, amount: l.envelope_id === target.envelope_id ? total : 0 }));
  if (!next.some(l => l.envelope_id === target.envelope_id)) {
    next.push({ ...target, amount: total });
  }
  return next;
}

export function canSubmit(direction, total, lines, target) {
  if (direction === 'match') return true;
  if (direction === 'surplus') return Boolean(target);
  if (direction !== 'unrecorded_expense') return false;
  if (lines.some(l => toNumber(l.amount) < 0)) return false;
  if (!lines.some(l => toNumber(l.amount) > 0)) return false;
  return unassigned(total, lines) === 0;
}

export function toApplyLines(direction, lines, target, gapAbs) {
  if (direction === 'unrecorded_expense') {
    return lines
      .filter(l => toNumber(l.amount) > 0)
      .map(l => ({ envelope_id: l.envelope_id, amount: toNumber(l.amount) }));
  }
  if (direction === 'surplus') return [{ envelope_id: target, amount: gapAbs }];
  return [];
}

export function formatLastChecked(iso, now = new Date()) {
  if (!iso) return 'belum pernah';
  const day = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(new Date(iso))) / 86400000);
  if (days <= 0) return 'hari ini';
  if (days === 1) return 'kemarin';
  return `${days} hari lalu`;
}

// Pesan error dari response API. Error service = string; error validasi FastAPI (422)
// = array objek → pakai fallback supaya React tidak merender objek.
export function errorText(data, fallback) {
  const detail = data?.detail;
  return typeof detail === 'string' && detail ? detail : fallback;
}
