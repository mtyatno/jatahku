// Beranda AI Advisor (S6): pembantu murni di atas GET /advisor/dashboard (04-kontrak-api.md).
// Tidak ada rumus angka periode di sini — semua angka datang dari `metrics`; yang ada hanya
// memilih, memformat, dan menyusun tampilan (aturan kerja #4).
import { parseDay } from './dashboardInsights.js';

const p2 = (n) => String(n).padStart(2, '0');
const dayStr = (d) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
const num = (v) => Number(v) || 0;

// Payload siap dipakai: user dalam flag dan bentuknya utuh. Selain itu Beranda memakai UI lama.
export function advisorEnabled(dash) {
  return !!(dash && dash.enabled && dash.metrics && Array.isArray(dash.metrics.harian));
}

// Cap waktu §7: "Diperbarui baru saja" (< 5 menit) atau "Diperbarui {jam}" (jam di zona waktu user,
// yang sudah tertulis di generated_at, jadi tidak bergantung zona waktu browser).
export function updatedLabel(generatedAt, now = new Date()) {
  if (!generatedAt) return '';
  const at = new Date(generatedAt);
  if (Number.isNaN(at.getTime())) return '';
  if (now.getTime() - at.getTime() < 5 * 60 * 1000) return 'Diperbarui baru saja';
  const m = /T(\d{2}):(\d{2})/.exec(generatedAt);
  return m ? `Diperbarui ${m[1]}.${m[2]}` : '';
}

// Peredaman §7: bila Beranda punya chip danger atau ≥ 2 chip warn (server: redam_chip),
// chip info/ok tampil redam. Isi popover tetap lengkap.
export function chipLook(insight, redam) {
  if (!insight) return null;
  const tone = ['danger', 'warn', 'info', 'ok'].includes(insight.tone) ? insight.tone : 'info';
  return { tone, muted: !!redam && (tone === 'info' || tone === 'ok'), text: insight.chip || '' };
}

// Paling banyak 2 CTA di popover (01-desain.md, Chip AI).
export const popoverActions = (insight) => (insight?.aksi || []).slice(0, 2);

const KEYAKINAN = { tinggi: 'Keyakinan tinggi', sedang: 'Keyakinan sedang', rendah: 'Keyakinan rendah' };
export function basisLabel(dasar) {
  if (!dasar) return '';
  return [dasar.teks, KEYAKINAN[dasar.keyakinan]].filter(Boolean).join(' · ');
}

// Deret grafik harian dari metrics.harian (S6 §3): batang = belanja variabel, diwarnai `lewat`
// (jatah J0 hari itu); tagihan, penyesuaian, dan belanja luar biasa jadi segmen redup di atasnya,
// tidak dibandingkan dengan jatah. Hari sesudah `today` = batang tipis (belum terjadi).
export function advisorDailySeries(metrics, periodStart, periodEnd, today) {
  const harian = metrics?.harian || [];
  const byDay = {};
  harian.forEach((h) => { byDay[String(h.tanggal).slice(0, 10)] = h; });
  const row = (s) => {
    const h = byDay[s];
    const variabel = num(h?.variabel);
    const redup = num(h?.tagihan) + Math.max(num(h?.penyesuaian), 0) + num(h?.outlier);
    let status;
    if (s > today) status = 'future';
    else if (variabel <= 0 && redup <= 0) status = 'empty';
    else status = h?.lewat ? 'over' : 'ok';
    return {
      day: s, variabel, redup, total: variabel + redup,
      tagihan: num(h?.tagihan), penyesuaian: num(h?.penyesuaian), outlier: num(h?.outlier),
      jatah: h && s <= today ? num(h.jatah) : null,
      status, isToday: s === today,
    };
  };
  if (!periodStart || !periodEnd) return harian.map((h) => row(String(h.tanggal).slice(0, 10)));
  const out = [];
  const end = parseDay(periodEnd);
  for (let d = parseDay(periodStart); d <= end && out.length < 62; d.setDate(d.getDate() + 1)) out.push(row(dayStr(d)));
  return out;
}

// Nilai kartu KPI dari metrik endpoint. Hanya rasio tampilan (lebar batang, persen bulat).
export function advisorKpi(metrics) {
  const m = metrics || {};
  const dana = num(m.dana_belanja);
  const terpakai = num(m.terpakai);
  const hariTotal = num(m.hari_total);
  const waktu = hariTotal > 0 ? Math.min(num(m.hari_ke) / hariTotal, 1) : 0;
  const rt = num(m.pemasukan_rumah_tangga);
  // Fase 5 (S20/S21, 02-aturan §3): angka utama Sisa bebas = dana harian (T3h); amplop bulanan
  // tampil terpisah sebagai "Dicadangkan"; ritme & surplus hanya ditampilkan, tidak dihitung di sini.
  const harian = m.sisa_bebas_harian == null ? num(m.sisa_bebas) : num(m.sisa_bebas_harian);
  return {
    jatah: {
      spent: num(m.belanja_hari_ini), j0: num(m.j0),
      ritme: m.ritme == null ? null : num(m.ritme),
    },
    sisa: {
      value: harian,
      total: num(m.sisa_bebas),
      cadangan: num(m.cadangan_bulanan),
      surplus: num(m.surplus_harian),
      dayLabel: hariTotal > 0 ? `Hari ke-${num(m.hari_ke)} dari ${hariTotal}` : '',
      progress: waktu,
      sisaHari: num(m.sisa_hari),
      j1: m.j1 == null ? null : num(m.j1),
    },
    terpakai: {
      value: terpakai, dana,
      fill: dana > 0 ? terpakai / dana : 0,
      waktu,
      persen: dana > 0 ? Math.round((terpakai / dana) * 100) : null,
      proyeksi: m.proyeksi_akhir == null ? null : num(m.proyeksi_akhir),
    },
    income: {
      value: rt,
      saya: num(m.pemasukan_saya),
      share: rt > 0 ? Math.min(num(m.pemasukan_saya) / rt, 1) : 0,
      kekurangan: m.kekurangan == null ? null : num(m.kekurangan),
    },
  };
}
