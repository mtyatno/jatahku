// Confidence display copy for the allocation recommendation (Plan C2 §8.4).
const LABELS = { high: 'Tinggi', medium: 'Sedang', low: 'Rendah' };
const TONES = { high: 'green', medium: 'amber', low: 'gray' };

export function confidenceLabel(level) {
  if (level == null) return '';
  return LABELS[level] || String(level);
}

export function confidenceTone(level) {
  return TONES[level] || 'gray';
}
