// Unggah foto dengan progres nyata. fetch tidak bisa melaporkan progres unggah,
// jadi unggahan pindah ke XMLHttpRequest. Logikanya murni (XHR disuntikkan)
// supaya bisa dites dengan node --test; api.js hanya membungkusnya.

export const UPLOAD_TIMEOUT_MS = 60000;

function parseBody(text) {
  try {
    const data = JSON.parse(text);
    return data && typeof data === 'object' ? data : {};
  } catch {
    return {};
  }
}

// Tidak pernah reject: error jaringan/abort → status 0, batas waktu → status 0 + timedOut.
export function xhrUpload({
  url,
  body,
  headers = {},
  XHR = globalThis.XMLHttpRequest,
  timeoutMs = UPLOAD_TIMEOUT_MS,
  onProgress,
  onUploaded,
}) {
  return new Promise(resolve => {
    let xhr;
    try {
      xhr = new XHR();
      xhr.open('POST', url);
      xhr.timeout = timeoutMs;
      for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);

      // Listener unggahan harus terpasang sebelum send(), kalau tidak browser tidak melaporkan progres.
      xhr.upload.addEventListener('progress', e => {
        if (e && e.lengthComputable && e.total > 0 && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      });
      xhr.upload.addEventListener('load', () => {
        if (onUploaded) onUploaded();
      });

      xhr.addEventListener('load', () => {
        resolve({ status: xhr.status, data: parseBody(xhr.responseText), timedOut: false });
      });
      xhr.addEventListener('error', () => resolve({ status: 0, data: {}, timedOut: false }));
      xhr.addEventListener('abort', () => resolve({ status: 0, data: {}, timedOut: false }));
      xhr.addEventListener('timeout', () => resolve({ status: 0, data: {}, timedOut: true }));

      xhr.send(body);
    } catch {
      resolve({ status: 0, data: {}, timedOut: false });
    }
  });
}

// Satu kali coba ulang setelah 401 bila token berhasil diperbarui (sama seperti ApiClient.request).
export async function sendWithRefresh(send, { hasRefreshToken, refresh }) {
  const first = await send();
  if (first.status === 401 && hasRefreshToken() && (await refresh())) {
    return send();
  }
  return first;
}
