import { formatShort } from './utils.js';
import { fundingState } from './envelopeFunding.js';

// Satu baris amplop di tampilan Ringkas: satu angka + satu keterangan pendek.
// tone (angka): 'saving' | 'safe' | 'warning' | 'danger' | 'muted'
// noteTone (keterangan): 'muted' | 'safe' | 'warning' | 'danger'
export function envelopeRow(env, goal) {
  const remaining = Number(env.remaining || 0);
  const reserved = Number(env.reserved || 0);
  const free = Number(env.free ?? remaining);

  if (env.purpose === 'saving' || env.purpose === 'sinking_fund') {
    const amount = goal ? Number(goal.current_balance) : free;
    if (!goal) return { amount, tone: 'saving', note: 'Belum ada target', noteTone: 'muted' };
    const pct = Math.round(goal.progress_pct);
    if (goal.is_achieved) return { amount, tone: 'saving', note: 'Target tercapai', noteTone: 'safe' };
    if (goal.target_date && new Date(goal.target_date) < new Date()) {
      return { amount, tone: 'saving', note: `${pct}% dari target · terlambat`, noteTone: 'warning' };
    }
    return { amount, tone: 'saving', note: `${pct}% dari target`, noteTone: 'muted' };
  }

  const allocated = Number(env.allocated || 0);
  const rollover = Number(env.rollover || 0);
  if (allocated <= 0 && rollover === 0) {
    return { amount: free, tone: 'muted', note: 'Belum ada dana', noteTone: 'warning' };
  }

  // Urutan sama dengan kartu: kurang-reserve tetap amber walau rasio terpakai tinggi.
  const state = fundingState(env);
  const ratio = Number(env.spent_ratio || 0);
  const pct = Math.round(ratio * 100);
  if (state === 'overspent') {
    return { amount: free, tone: 'danger', note: `Minus ${formatShort(Math.abs(remaining))}`, noteTone: 'danger' };
  }
  if (state === 'reserve_short') {
    return { amount: free, tone: 'warning', note: `Tagihan kurang ${formatShort(reserved - remaining)}`, noteTone: 'warning' };
  }
  if (ratio >= 0.9) return { amount: free, tone: 'danger', note: `${pct}% terpakai`, noteTone: 'danger' };
  if (ratio >= 0.7) return { amount: free, tone: 'warning', note: `${pct}% terpakai`, noteTone: 'warning' };
  return { amount: free, tone: 'safe', note: `${pct}% terpakai`, noteTone: 'muted' };
}
