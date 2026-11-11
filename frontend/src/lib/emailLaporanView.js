// Kartu Admin "Email laporan": logika murni (tes di emailLaporanView.test.js); komponen hanya merender.
// Angka datang jadi dari server (pantau_email.keadaan_email); di sini hanya diformat.

export const PESAN_GAGAL_MUAT = 'Status email laporan tidak bisa dimuat.';

const TEKS_ALARM = {
  pindah_penyedia: 'Saatnya pindah ke penyedia email transaksional (langkah di AGENTS.md).',
  worker_mati: 'Worker email tidak berjalan.',
  antrean_tersendat: 'Antrean tersendat lebih dari 6 jam.',
  email_gagal: 'Ada email laporan yang gagal dikirim.',
};

export function teksAlarm(kode) {
  return Object.prototype.hasOwnProperty.call(TEKS_ALARM, kode) ? TEKS_ALARM[kode] : '';
}

// 'HH.MM' di zona waktu `zona` (bawaan: zona pemirsa); '' bila waktu tak terbaca.
export function jamLokal(iso, zona) {
  const t = new Date(iso);
  if (!iso || Number.isNaN(t.getTime())) return '';
  const bagian = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', ...(zona ? { timeZone: zona } : {}),
  }).formatToParts(t);
  const ambil = (tipe) => bagian.find((b) => b.type === tipe)?.value ?? '';
  return `${ambil('hour')}.${ambil('minute')}`;
}

function teksMenunggu(menunggu, tertuaMenit) {
  if (!menunggu) return '0';
  if (tertuaMenit === null || tertuaMenit === undefined) return String(menunggu);
  const jam = Math.floor(tertuaMenit / 60);
  const menit = tertuaMenit % 60;
  return `${menunggu} · tertua ${jam > 0 ? `${jam} jam ` : ''}${menit} menit`;
}

const desimal = (n) => String(n).replace('.', ',');

// [{label, nilai, nada}] dengan nada 'baik' | 'biasa' | 'bahaya'.
export function barisKartu(k, zona) {
  const jam = k.worker_hidup ? jamLokal(k.worker_terakhir, zona) : '';
  return [
    {
      label: 'Worker',
      nilai: k.worker_hidup ? (jam ? `Hidup · terakhir ${jam}` : 'Hidup') : 'Tidak memberi tanda hidup',
      nada: k.worker_hidup ? 'baik' : 'bahaya',
    },
    { label: 'Menunggu', nilai: teksMenunggu(k.menunggu, k.tertua_menit), nada: 'biasa' },
    { label: 'Terkirim 24 jam', nilai: String(k.terkirim_24_jam), nada: 'biasa' },
    { label: 'Gagal 7 hari', nilai: String(k.gagal_7_hari), nada: k.gagal_7_hari > 0 ? 'bahaya' : 'biasa' },
    {
      label: 'Penerima',
      nilai: `${k.penerima} / ${k.ambang_penerima}`,
      nada: k.penerima >= k.ambang_penerima ? 'bahaya' : 'biasa',
    },
    { label: 'Laju', nilai: `${desimal(k.laju_per_detik)} email/detik`, nada: 'biasa' },
  ];
}
