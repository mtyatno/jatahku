const AMOUNT_RE = /(?:rp\.?\s*)?(\d{1,3}(?:\.\d{3})+|\d+\.\d{1,2}|\d+(?:,\d+)?)\s*(jt|juta|rb|ribu|k)?(?!\w)|(?:rp\.?\s*)(\d+)/i;
const MULTIPLIERS = { jt: 1_000_000, juta: 1_000_000, rb: 1_000, ribu: 1_000, k: 1_000 };

export function parseAmount(text) {
  const match = AMOUNT_RE.exec(text.trim());
  if (!match) return null;

  let numberStr, multiplierStr;

  if (match[1]) {
    numberStr = match[1];
    multiplierStr = match[2];
  } else if (match[3]) {
    numberStr = match[3];
    multiplierStr = null;
  } else {
    return null;
  }

  let number;
  if (/^\d{1,3}(\.\d{3})+$/.test(numberStr)) {
    number = parseFloat(numberStr.replace(/\./g, ''));
  } else if (/^\d{1,3}(,\d{3})+$/.test(numberStr)) {
    number = parseFloat(numberStr.replace(/,/g, ''));
  } else {
    number = parseFloat(numberStr.replace(',', '.'));
  }

  if (isNaN(number)) return null;

  const multiplier = multiplierStr ? (MULTIPLIERS[multiplierStr.toLowerCase()] || 1) : 1;
  const amount = Math.round(number * multiplier);

  if (amount <= 0) return null;

  const before = text.trim().slice(0, match.index).trim();
  const after = text.trim().slice(match.index + match[0].length).trim();
  let desc = (before + ' ' + after).trim();
  if (!desc) desc = 'Pengeluaran';

  return { amount, description: desc };
}

// Pemisah koma: koma = pemisah item KECUALI diikuti angka (koma desimal
// "1,5"). Guard ke depan (bukan lookbehind), karena pemisah item biasanya
// langsung menempel angka jumlah ("kopi 35.000, gojek 20.000" — koma
// diawali digit, lookbehind ?<!\d malah memblokir split).
const COMMA_SEP = /\s*,(?!\d)\s*|;/i;
const WORD_SEPS = [/\s+(?:terus|lalu)\s+/i, /\s+dan\s+/i];

export function parseMultiExpense(text) {
  const trimmed = text.trim();
  if (!trimmed) return null;

  // Tahap 1: pecah per baris, lalu per koma/titik-koma di dalam tiap baris.
  // Semua jenis pemisah dipakai sekaligus — bukan "pola pertama yang cocok
  // menang" (dulu: input campuran koma+newline hanya kebaca newline-nya).
  const lines = trimmed.split(/\s*\n+\s*/).filter(p => p.trim());
  const parts = [];
  for (const line of lines) {
    parts.push(...line.split(COMMA_SEP).filter(p => p.trim()));
  }

  // Tahap 2: "terus"/"lalu"/"dan" dipecah HANYA bila setiap sisinya punya
  // jumlah — agar deskripsi seperti "bakso dan es teh 10 ribu" tidak terbelah.
  const expanded = [];
  for (const part of parts) {
    let matched = false;
    for (const sep of WORD_SEPS) {
      const sides = part.split(sep).filter(p => p.trim());
      if (sides.length >= 2 && sides.every(s => parseAmount(s))) {
        expanded.push(...sides);
        matched = true;
        break;
      }
    }
    if (!matched) expanded.push(part);
  }

  const results = expanded
    .map(p => parseAmount(p.trim()))
    .filter(r => r !== null);
  if (results.length >= 2) {
    return results;
  }

  return null;
}
