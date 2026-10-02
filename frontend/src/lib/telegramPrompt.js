// Kapan modal "Hubungkan Telegram" muncul. Data funnel Okt 2026: semua user
// yang bertahan memakai bot, jadi ajakan ini penting — tapi dulu muncul di
// SETIAP sesi (dismiss hanya di sessionStorage), termasuk untuk user WhatsApp.
// Aturan: tepat setelah onboarding selalu muncul; selebihnya paling sering
// sekali per minggu; tidak pernah bila Telegram/WhatsApp sudah tertaut.
export const TELEGRAM_PROMPT_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000;

export function shouldShowTelegramPrompt({
  telegramLinked, whatsappLinked, hasEnvelopes, justOnboarded, lastShownAt, now,
}) {
  if (telegramLinked || whatsappLinked) return false;
  if (justOnboarded) return true;
  if (!hasEnvelopes) return false;
  if (lastShownAt == null) return true;
  return now - lastShownAt >= TELEGRAM_PROMPT_INTERVAL_MS;
}
