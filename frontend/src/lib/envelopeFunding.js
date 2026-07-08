// Keadaan pendanaan amplop expense — bedakan overspend beneran vs kurang-reserve. (kartu amplop)
export function fundingState(env) {
  const allocated = Number(env.allocated || 0);
  const rollover = Number(env.rollover || 0);
  const spent = Number(env.spent || 0);
  const free = Number(env.free ?? (allocated + rollover - spent - Number(env.reserved || 0)));
  const remaining = allocated + rollover - spent;
  if (remaining < 0) return 'overspent';
  if (free < 0) return 'reserve_short';
  return 'ok';
}
