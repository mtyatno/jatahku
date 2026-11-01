// Model Beranda (Plugin B2): semua turunan tampilan yang dulu ditulis langsung di Dashboard.jsx,
// dipindah ke satu fungsi murni supaya Beranda lama dan Beranda registry memakai hitungan yang sama
// persis. Tidak ada rumus angka baru: hanya menjumlah baris yang sudah dikirim server dan memilih
// nilai (aturan kerja AI Advisor #4, AGENTS.md "Plugin dan ruang" aturan 6).
//
// Masukan = respons endpoint lama (atau `sumber` dari POST /dashboard/data dengan nama yang sama).
import { dailyMeter, billsProgress } from './kpiCards.js';
import { advisorEnabled, advisorKpi, updatedLabel } from './advisorDashboard.js';

// Uang pecahan terkecil Rp100: jatah harian dan selisihnya dibulatkan ke bawah ke kelipatan Rp100.
export const floorRp100 = (v) => Math.floor((Number(v) || 0) / 100) * 100;

export function sortEnvelopes(envs) {
  return [...envs].sort((a, b) => {
    const aFunded = Number(a.allocated) > 0;
    const bFunded = Number(b.allocated) > 0;
    if (aFunded && !bFunded) return -1;
    if (!aFunded && bFunded) return 1;
    return b.spent_ratio - a.spent_ratio;
  });
}

// Potongan KPI dari POST /dashboard/data: flag aktif dan metrik ada (deret harian sengaja tidak ikut).
export function advisorSliceReady(dash) {
  return !!(dash && dash.enabled && dash.metrics && typeof dash.metrics === 'object');
}

export const isSaving = (e) => e.purpose === 'saving' || e.purpose === 'sinking_fund';

/**
 * @param {object} p
 * @param {Array}  p.envelopes      GET /envelopes/summary (ringkasan_amplop)
 * @param {object} p.prediction     GET /analytics/prediction (prediksi), null untuk periode lalu
 * @param {Array}  p.daily          GET /analytics/daily-spending (harian)
 * @param {object} p.recurringStats GET /recurring/summary/period (tagihan)
 * @param {Array}  p.goals          GET /goals/ (target)
 * @param {object} p.advisorDash    GET /advisor/dashboard (advisor) atau potongannya
 * @param {boolean} p.isCurrentPeriod
 * @param {string} p.today          YYYY-MM-DD menurut jam perangkat (localDateStr)
 * @param {boolean} p.advisorSlice  true = `advisorDash` adalah potongan KPI dari POST /dashboard/data
 *                                  (metrik tanpa deret harian, 04-kontrak-api.md §4)
 */
export function berandaModel({
  envelopes = [], prediction = null, daily = [], recurringStats = null, goals = [],
  advisorDash = null, isCurrentPeriod = true, today, advisorSlice = false,
} = {}) {
  const envs = Array.isArray(envelopes) ? envelopes : [];
  const totalAllocated = envs.reduce((s, e) => s + Number(e.allocated), 0);
  const totalRollover = envs.reduce((s, e) => s + Number(e.rollover || 0), 0);
  const totalSpent = envs.reduce((s, e) => s + Number(e.spent), 0);
  const totalRemaining = envs.reduce((s, e) => s + Number(e.free ?? e.remaining), 0);
  const savingEnvelopes = envs.filter(isSaving);
  const spending = sortEnvelopes(envs.filter(e => !isSaving(e)));
  const totalSaving = savingEnvelopes.reduce((s, e) => s + Number(e.free ?? e.remaining), 0);
  const sharedSaving = savingEnvelopes.filter(e => !e.is_personal).reduce((s, e) => s + Number(e.free ?? e.remaining), 0);
  const personalSaving = totalSaving - sharedSaving;
  const sisaBebas = totalRemaining - totalSaving;

  // Satu-satunya tempat jatah aman per hari dibulatkan (ke bawah, Rp100).
  const safeDaily = floorRp100(prediction?.safe_daily);
  const todayRow = (Array.isArray(daily) ? daily : []).find(d => d.date === today);
  const todaySpent = todayRow?.total || 0;
  const todayCount = todayRow?.count || 0;
  const fundsTotal = totalAllocated + totalRollover;
  const meter = dailyMeter(todaySpent, safeDaily);
  const income = Number(prediction?.total_income) || 0;
  const bills = billsProgress(recurringStats);
  const gls = Array.isArray(goals) ? goals : [];
  const savingGoalCount = gls.filter(g => savingEnvelopes.some(e => e.id === g.envelope_id)).length;

  // Angka kartu & grafik dari metrics endpoint; hanya periode berjalan.
  const adv = !!(isCurrentPeriod && (advisorSlice ? advisorSliceReady(advisorDash) : advisorEnabled(advisorDash)));
  const k = adv ? advisorKpi(advisorDash.metrics) : null;
  const advMeter = adv ? dailyMeter(k.jatah.spent, k.jatah.j0) : null;
  const stamp = adv ? updatedLabel(advisorDash.generated_at) : '';
  // Hari ini menurut zona waktu user (generated_at), bukan jam browser.
  const advToday = (adv && (advisorDash.generated_at || '').slice(0, 10)) || today;

  return {
    totalAllocated, totalRollover, totalSpent, totalRemaining, savingEnvelopes, spending,
    totalSaving, sharedSaving, personalSaving, sisaBebas, safeDaily, todaySpent, todayCount,
    fundsTotal, meter, income, bills, savingGoalCount, adv, k, advMeter, stamp, advToday,
  };
}
