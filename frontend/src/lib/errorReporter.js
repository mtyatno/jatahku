// Laporan error klien ke `POST /app/errors` (paket mobile 1.3). Dibatasi
// supaya satu halaman yang rusak tidak membanjiri server: maksimal
// MAX_REPORTS per muat halaman, pesan yang sama hanya sekali, dan hanya
// bila /app/config mengizinkan (error_reporting.enabled + sample_rate).

export const MAX_REPORTS = 5;

export function createErrorReporter({ send, getConfig, random = Math.random, max = MAX_REPORTS }) {
  const seen = new Set();
  return function report({ message, stack = null, url = null, kind = 'error' }) {
    const er = getConfig()?.error_reporting;
    if (!er?.enabled || seen.size >= max) return false;
    const msg = String(message || 'Error').slice(0, 2000);
    if (seen.has(msg)) return false;
    seen.add(msg);
    if (random() >= er.sample_rate) return false;
    send({ message: msg, stack: stack ? String(stack).slice(0, 8000) : null, url, kind });
    return true;
  };
}

export function installErrorReporter(target, report) {
  const onError = (e) => report({
    message: e?.message || e?.error?.message,
    stack: e?.error?.stack,
    url: target.location?.href,
    kind: 'error',
  });
  const onRejection = (e) => report({
    message: e?.reason?.message || String(e?.reason ?? 'unhandledrejection'),
    stack: e?.reason?.stack,
    url: target.location?.href,
    kind: 'unhandledrejection',
  });
  target.addEventListener('error', onError);
  target.addEventListener('unhandledrejection', onRejection);
  return () => {
    target.removeEventListener('error', onError);
    target.removeEventListener('unhandledrejection', onRejection);
  };
}
