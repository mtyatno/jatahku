// Peringatan di form Alokasi untuk amplop yang tidak membawa sisa ke periode berikutnya (`is_rollover === false`).
// Dengan siklus household, anggota yang gajiannya tanggal 25 bisa mengalokasikan menjelang akhir periode rumah
// tangga; saldo akhir amplop non-rollover (sisa maupun minus) tidak dibawa (rollover = 0, lihat `snapshot_values`
// di app/services/rollover.py), jadi uang yang dialokasikan sekarang cuma sempat dipakai beberapa hari.
// Murni (tanpa React), supaya bisa dites dengan node --test.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const DAY_MS = 24 * 60 * 60 * 1000;

// Peringatan muncul bila periode berakhir dalam sejumlah hari ini (0 = berakhir hari ini).
const WARN_WITHIN_DAYS = 7;

// "YYYY-MM-DD" (dibaca sebagai teks) atau Date (komponen LOKAL, tanggal di jam dinding pengguna) -> hari kalender
// { month (1-12), day, utc }, `utc` = tengah malam UTC hari itu supaya selisih dua hari selalu kelipatan 24 jam
// utuh. Null bila bukan tanggal kalender yang ada (teks asal, 2026-02-30, bulan 13, Date tidak sah).
// Sengaja tanpa `new Date("YYYY-MM-DD")`: dibaca sebagai UTC, lalu dicampur `new Date()` lokal selisihnya
// meleset sehari di zona waktu mana pun selain UTC.
function calendarDay(value) {
  let year;
  let month;
  let day;
  if (value instanceof Date) {
    year = value.getFullYear();
    month = value.getMonth() + 1;
    day = value.getDate();
  } else {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(typeof value === 'string' ? value : '');
    if (!m) return null;
    year = Number(m[1]);
    month = Number(m[2]);
    day = Number(m[3]);
  }
  const utc = new Date(Date.UTC(year, month - 1, day));
  const exists = utc.getUTCFullYear() === year && utc.getUTCMonth() === month - 1 && utc.getUTCDate() === day;
  return exists ? { month, day, utc: utc.getTime() } : null;
}

// Teks peringatan untuk satu baris amplop di form, atau null bila tidak perlu.
//   env        baris dari GET /envelopes/summary; hanya `is_rollover === false` yang diperingatkan
//              (field hilang = dianggap membawa sisa, seperti default server)
//   periodEnd  `period_end` periode berjalan (item terakhir GET /analytics/periods), "YYYY-MM-DD"
//   today      "YYYY-MM-DD" atau Date (tanggal lokal)
//   amount     jumlah yang sedang dialokasikan ke amplop itu; tanpa jumlah positif tidak ada yang perlu diingatkan
export function nonRolloverWarning(env, periodEnd, today, amount) {
  if (env?.is_rollover !== false) return null;
  if (!(Number(amount) > 0)) return null;
  const end = calendarDay(periodEnd);
  const now = calendarDay(today);
  if (!end || !now) return null;
  const n = (end.utc - now.utc) / DAY_MS;
  if (n < 0 || n > WARN_WITHIN_DAYS) return null;
  const tgl = `${end.day} ${MONTHS[end.month - 1]}`;
  const sisa = n === 0 ? 'hari ini' : `${n} hari lagi`;
  return `Amplop ini tidak membawa sisa ke periode berikutnya. Yang tidak terpakai di-reset ${tgl} (${sisa}).`;
}
