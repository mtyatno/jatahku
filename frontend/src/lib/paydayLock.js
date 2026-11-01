// Siklus anggaran (tanggal gajian) milik household: owner yang memutuskan, anggota lain hanya membaca
// (spec siklus-household, bagian 6). Keputusan tampilan Settings dan Onboarding ada di sini supaya bisa
// diuji `node --test` tanpa React.

// Household sendirian menyimpan tanggal gajian saat input berubah, ditunda sebentar supaya mengetik "25"
// tidak menyimpan "2" dulu (tiap perubahan tanggal menghitung ulang riwayat di server).
export const PAYDAY_SAVE_DELAY_MS = 600;

// Tanggal gajian yang berlaku: milik household bila profil membawanya, jika tidak cermin `payday_day` di user
// (profil lama di cache belum punya field household).
export function householdPayday(profile) {
  const p = profile || {};
  return p.household_payday_day ?? p.payday_day ?? 1;
}

// Isi input tanggal gajian (teks atau angka) jadi bilangan bulat 1-31 (rentang yang diterima server), atau null bila
// kosong, di luar rentang, atau bukan bilangan bulat. Dulu input kosong lolos sebagai NaN dan terkirim sebagai null.
export function parsePaydayDay(raw) {
  if (raw === '' || raw == null) return null;
  const day = Number(raw);
  return Number.isInteger(day) && day >= 1 && day <= 31 ? day : null;
}

// Apa yang boleh dilakukan user dengan tanggal gajiannya, dari respons GET /user/profile:
//   locked       anggota biasa di household berisi lebih dari satu orang: hanya membaca `note`, tidak pernah mengirim payday_day
//   needsConfirm owner/admin household >1 anggota: ubah lewat tombol Simpan + dialog `confirmText`
//   selain itu   household sendirian: simpan saat input berubah (debounce PAYDAY_SAVE_DELAY_MS)
// Profil tanpa field baru (cache lama) dan profil kosong dianggap sendirian dan tidak terkunci.
export function paydayLockState(profile) {
  const p = profile || {};
  const locked = !!p.payday_locked;
  const needsConfirm = !locked && (p.household_member_count ?? 1) > 1;
  const owner = p.payday_owner_name ? ` (diatur ${p.payday_owner_name})` : '';
  return {
    locked,
    note: locked ? `Mengikuti siklus rumah tangga: tanggal ${householdPayday(p)}${owner}.` : null,
    needsConfirm,
    confirmText: needsConfirm
      ? `Mengubah tanggal gajian berlaku untuk semua anggota ${p.household_name || 'rumah tangga'}, dan riwayat anggarannya dihitung ulang. Lanjutkan?`
      : null,
  };
}

// Flash setelah gabung household dari web. `paydayDay` dari respons POST /household/join; tanpa itu (respons lama)
// pesannya tetap yang dulu.
export function joinSuccessMessage(householdName, paydayDay) {
  const base = `Berhasil bergabung ke ${householdName}!`;
  return paydayDay ? `${base} Siklus anggaranmu sekarang mengikuti rumah ini: tanggal ${paydayDay}.` : base;
}

// Body PUT /user/profile di akhir Onboarding: payday_day hanya untuk household sendirian, selain itu income_type saja.
// - Anggota yang tanggalnya dikunci household: PUT yang membawa tanggal lain ditolak 403 dan tidak menyimpan apa pun,
//   income_type ikut hilang.
// - Owner/admin household berisi lebih dari satu orang (needsConfirm): mengubah tanggal rumah menghitung ulang riwayat
//   dan memberi tahu semua anggota, dan Onboarding tidak punya dialog konfirmasi; pekerja harian/mingguan akan
//   mengirim tanggal 1 tanpa sadar. Tanggal rumah diubah lewat Settings (Simpan + konfirmasi).
export function onboardingProfileBody(profile, { paydayDay, incomeType }) {
  const { locked, needsConfirm } = paydayLockState(profile);
  return locked || needsConfirm
    ? { income_type: incomeType }
    : { payday_day: paydayDay, income_type: incomeType };
}
