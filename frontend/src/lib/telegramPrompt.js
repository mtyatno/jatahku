// Kapan modal "Hubungkan Telegram" muncul. Data funnel Okt 2026: semua user
// yang bertahan memakai bot, jadi ajakan ini penting — tapi dulu muncul di
// SETIAP sesi (dismiss hanya di sessionStorage), termasuk untuk user WhatsApp.
// Aturan: tepat setelah onboarding selalu muncul; selebihnya paling sering
// sekali per minggu; tidak pernah bila Telegram/WhatsApp sudah tertaut.
export const TELEGRAM_PROMPT_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000;

// Kode link dari /auth/link/generate berlaku 5 menit sejak DIBUAT (LINK_TTL
// backend), bukan sejak tombol ditekan. `marginMs` untuk menyegarkan kode yang
// hampir mati sebelum Telegram dibuka.
export const LINK_CODE_TTL_MS = 5 * 60 * 1000;

export function isLinkCodeUsable(codeAt, now, marginMs = 0) {
  return codeAt > 0 && now - codeAt < LINK_CODE_TTL_MS - marginMs;
}

export function shouldShowTelegramPrompt({
  telegramLinked, whatsappLinked, hasEnvelopes, justOnboarded, lastShownAt, now,
}) {
  if (telegramLinked || whatsappLinked) return false;
  if (justOnboarded) return true;
  if (!hasEnvelopes) return false;
  if (lastShownAt == null) return true;
  return now - lastShownAt >= TELEGRAM_PROMPT_INTERVAL_MS;
}

// Mode modal: 'connect' = ajak hubungkan Telegram; 'return' = user datang dari
// bot (sudah tertaut) dan baru selesai onboarding di web → ajak kembali ke
// Telegram untuk mencatat pertama kali; null = tidak tampil.
export function telegramPromptMode(params) {
  if (params.telegramLinked) return params.justOnboarded ? 'return' : null;
  return shouldShowTelegramPrompt(params) ? 'connect' : null;
}
