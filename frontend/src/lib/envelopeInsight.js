// Baris coaching murni (tanpa presentasi) untuk strip advisor di kartu amplop.
// Return { text, tone } dengan tone: 'safe' | 'warning' | 'danger' | 'neutral'.
// Pemetaan warna/ikon per-tone ada di komponen, bukan di sini.
export function envelopeInsight(env, goal) {
  const purpose = env.purpose;
  const isSavingLike = purpose === 'saving' || purpose === 'sinking_fund';

  if (isSavingLike) {
    if (!goal) return { text: 'Tambahkan target biar terarah', tone: 'neutral' };
    if (goal.is_achieved) return { text: 'Target tercapai, mantap!', tone: 'safe' };
    if (goal.target_date && new Date(goal.target_date) < new Date()) {
      return { text: 'Sedikit tertinggal dari target', tone: 'warning' };
    }
    return { text: 'Menuju target dengan konsisten', tone: 'safe' };
  }

  // expense
  const free = Number(env.free ?? env.remaining ?? 0);
  const ratio = Number(env.spent_ratio || 0);
  if (free <= 0) return { text: 'Melewati budget bulan ini', tone: 'danger' };
  if (ratio >= 0.9) return { text: 'Sudah mepet, rem dulu', tone: 'danger' };
  if (ratio >= 0.7) return { text: 'Hati-hati, mendekati batas', tone: 'warning' };
  return { text: 'Masih aman, tetap jaga ya!', tone: 'safe' };
}
