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

const SEP_PATTERNS = [
  /\s*\n+\s*/,
  /\s*(?<!\d),\s*|;/i,
  /\s+(?:terus|lalu)\s+/i,
  /\s+dan\s+/i,
];

export function parseMultiExpense(text) {
  const trimmed = text.trim();
  if (!trimmed) return null;

  for (const sep of SEP_PATTERNS) {
    const parts = trimmed.split(sep).filter(p => p.trim());
    if (parts.length >= 2) {
      const results = parts
        .map(p => parseAmount(p.trim()))
        .filter(r => r !== null);
      if (results.length >= 2) {
        return results;
      }
    }
  }

  return null;
}
