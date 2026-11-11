// Show the "hide description from household" toggle only when it can matter:
// a multi-member household AND a shared envelope. (Plan C2 §8.3)
//
// Shared == no owner. We gate on `owner_id` (not `is_personal`) because the
// GET /envelopes/ response this consumes always serializes is_personal=false
// (it is not an ORM attribute — only owner_id is), whereas owner_id is real:
// null for shared, a user id for personal.
//
// Ruang usaha tidak punya pengeluaran privat (keputusan 11 Nov 2026): pengeluaran usaha terbuka bagi pemilik dan
// admin, untuk semua peran, jadi pilihannya tidak pernah tampil di sana. Server menolak kiriman bertanda privat di ruang
// usaha (422 `privat_tidak_tersedia`), jadi ini hanya tampilan.
export function shouldShowPrivateToggle(memberCount, envelope, { ruangUsaha = false } = {}) {
  return !ruangUsaha && memberCount > 1 && !!envelope && envelope.owner_id == null;
}
