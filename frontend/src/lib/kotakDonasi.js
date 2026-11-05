// Kartu Settings "Bantu Jatahku membaca bukti bayar" (donasi contoh Kotak Struk tahap 2; API
// `GET/PUT /user/kotak-donasi`, app/api/routes/user_settings.py): logika murni, diuji dengan node --test; JSX di
// pages/Settings.jsx hanya merender hasilnya.
//
// Kartu tampil bila saklar `features.kotak_donasi` menyala (`available`) ATAU user sudah setuju (`consented`), supaya
// persetujuan tetap bisa ditarik walau saklar dimatikan. Teks persetujuan = keputusan pemilik (A16, G3), apa adanya.
import { wibDate, shortDate } from './receiptScan.js';

export const CONSENT_TEXT = Object.freeze({
  title: 'Bantu Jatahku membaca bukti bayar',
  body: 'Bantu Jatahku menjadi lebih tepat dalam membaca berbagai model dan bentuk bukti bayar (struk) dari berbagai '
    + 'bank dan layanan keuangan di seluruh Indonesia. Teks bukti yang sudah disamarkan dikirim ke pengelola untuk '
    + 'ditinjau; bisa dimatikan kapan saja.',
});

const CLOSED_TEXT = 'Donasi contoh sedang ditutup; kamu tetap bisa mematikannya.';
const CONFLICT_TEXT = 'Donasi contoh belum dibuka.';
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);

// Respons server → {show, on, label, since, closed} atau null bila bentuknya rusak. `since` = hari WIB persetujuan
// ("5 Nov 2026") atau null; `closed` = catatan saat sudah setuju tetapi saklar mati, selain itu null.
export function consentView(resp) {
  if (!isObj(resp) || typeof resp.available !== 'boolean' || typeof resp.consented !== 'boolean') return null;
  const on = resp.consented;
  const day = on ? wibDate(resp.consented_at) : null;
  const since = day ? shortDate(day) : null;
  return {
    show: resp.available || on,
    on,
    label: on ? (since ? `Aktif sejak ${since}` : 'Aktif') : 'Mati',
    since,
    closed: on && !resp.available ? CLOSED_TEXT : null,
  };
}

// `detail` server hanya dipakai bila kalimat pendek (bukan JSON/objek).
function serverText(data) {
  const d = data?.detail;
  if (typeof d !== 'string') return null;
  const t = d.trim();
  if (!t || t.length > 200 || /^[[{]/.test(t)) return null;
  return `${t.replace(/[.!]+$/, '')}.`;
}

// Hasil `api.setKotakDonasi` ({ok, status, data}) → {kind: ok|conflict|error, text, view}. `view` = consentView isi
// jawaban (null = muat ulang). 409 (saklar mati saat menyalakan) → teks server. Tidak pernah melempar.
export function toggleOutcome(res) {
  if (isObj(res) && res.ok) {
    const view = consentView(res.data);
    const text = view?.on === false
      ? 'Dimatikan. Contoh yang belum ditinjau sudah dihapus.'
      : 'Terima kasih, bantuanmu aktif.';
    return { kind: 'ok', text, view };
  }
  const status = Number.isSafeInteger(res?.status) ? res.status : 0;
  if (status === 409) return { kind: 'conflict', text: serverText(res.data) || CONFLICT_TEXT, view: null };
  if (status === 0) return { kind: 'error', text: 'Koneksi gagal, coba lagi.', view: null };
  return { kind: 'error', text: `Belum tersimpan (kode ${status}). Coba lagi.`, view: null };
}

// Sesudah toggle (review M1e temuan 1): → {view, message}. Kartu yang sudah tampil tetap tampil sepanjang kunjungan
// (`show: true`), supaya pesan 409/koneksi gagal terlihat dan "Mati" tetap terlihat sesudah menarik persetujuan saat
// saklar ditutup. `reloaded` (jawaban GET baru) hanya dipakai bila PUT berhasil tetapi isinya rusak; bila PUT gagal,
// tampilan sebelumnya tetap. `message` = {kind, text}. Tidak pernah melempar.
export function afterToggle(prevView, res, reloaded) {
  const out = toggleOutcome(res);
  const base = out.kind === 'ok' ? (out.view ?? consentView(reloaded) ?? prevView) : prevView;
  return {
    view: base ? { ...base, show: true } : null,
    message: { kind: out.kind, text: out.text },
  };
}
