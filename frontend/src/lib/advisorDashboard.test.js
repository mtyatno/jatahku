import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  advisorEnabled, updatedLabel, chipLook, popoverActions, basisLabel, advisorDailySeries, advisorKpi,
} from './advisorDashboard.js';

// Angka contoh §12 (02-aturan.md), sama dengan keluaran susun_dashboard(contoh_15_okt()).
const METRICS = {
  dana_belanja: 11285200, terpakai: 8000000, tagihan_sisa: 1600000, sisa_bebas: 1685200,
  j0: 165100, j1: 153200, laju7: 201014, belanja_hari_ini: 297100, proyeksi_akhir: 11811157,
  kekurangan: 525957, tanggal_habis: '2026-10-24', hari_ke: 19, hari_total: 30, sisa_hari: 11,
  pemasukan_saya: 0, pemasukan_rumah_tangga: 7500000,
  harian: [
    { tanggal: '2026-10-13', variabel: 140000, tagihan: 0, penyesuaian: 0, outlier: 0, jatah: 165800, lewat: false },
    { tanggal: '2026-10-14', variabel: 200000, tagihan: 1600000, penyesuaian: 0, outlier: 0, jatah: 167800, lewat: true },
    { tanggal: '2026-10-15', variabel: 297100, tagihan: 0, penyesuaian: 0, outlier: 137300, jatah: 165100, lewat: true },
  ],
};

test('flag: only a complete enabled payload switches the dashboard', () => {
  assert.equal(advisorEnabled({ enabled: true, metrics: METRICS }), true);
  assert.equal(advisorEnabled({ enabled: false }), false);
  assert.equal(advisorEnabled({ enabled: true }), false);
  assert.equal(advisorEnabled(null), false);
});

test('timestamp: "baru saja" under 5 minutes, otherwise the user-local hour from generated_at', () => {
  const at = '2026-10-15T06:05:00+07:00';
  assert.equal(updatedLabel(at, new Date('2026-10-14T23:08:00Z')), 'Diperbarui baru saja');
  assert.equal(updatedLabel(at, new Date('2026-10-14T23:10:00Z')), 'Diperbarui 06.05');
  assert.equal(updatedLabel(null), '');
  assert.equal(updatedLabel('bukan tanggal'), '');
});

test('chip damping: info/ok muted only when the server says redam_chip', () => {
  assert.deepEqual(chipLook({ tone: 'danger', chip: '1,8× jatah' }, true), { tone: 'danger', muted: false, text: '1,8× jatah' });
  assert.equal(chipLook({ tone: 'warn', chip: 'x' }, true).muted, false);
  assert.equal(chipLook({ tone: 'info', chip: 'Terisi dari Rina' }, true).muted, true);
  assert.equal(chipLook({ tone: 'ok', chip: 'Aman' }, true).muted, true);
  assert.equal(chipLook({ tone: 'info', chip: 'x' }, false).muted, false);
  assert.equal(chipLook({ tone: 'aneh', chip: 'x' }, false).tone, 'info');
  assert.equal(chipLook(null, true), null);
});

test('popover shows at most two actions and a readable basis', () => {
  const ins = { aksi: [{ kind: 'route' }, { kind: 'chat' }, { kind: 'plan' }] };
  assert.deepEqual(popoverActions(ins).map(a => a.kind), ['route', 'chat']);
  assert.deepEqual(popoverActions(null), []);
  assert.equal(basisLabel({ teks: 'Dari 19 hari data', keyakinan: 'sedang' }), 'Dari 19 hari data · Keyakinan sedang');
  assert.equal(basisLabel(null), '');
});

test('chart series: bars are variable spending coloured by lewat; bills/outliers are a dim segment', () => {
  const s = advisorDailySeries(METRICS, '2026-10-12', '2026-10-17', '2026-10-15');
  assert.deepEqual(s.map(r => r.day), ['2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-17']);
  assert.deepEqual(s.map(r => r.status), ['empty', 'ok', 'over', 'over', 'future', 'future']);
  const d14 = s[2];
  assert.equal(d14.variabel, 200000);
  assert.equal(d14.redup, 1600000);
  assert.equal(d14.jatah, 167800);
  const d15 = s[3];
  assert.equal(d15.isToday, true);
  assert.equal(d15.redup, 137300);
  assert.equal(s[4].jatah, null);
  // Rata-rata 7 batang terakhir = laju7: batangnya hanya variabel, tanpa segmen redup.
  assert.equal(s.slice(0, 4).reduce((t, r) => t + r.variabel, 0), 140000 + 200000 + 297100);
});

test('chart series: a day with only a bill payment is not "empty" and never "over"', () => {
  const m = { harian: [{ tanggal: '2026-10-01', variabel: 0, tagihan: 500000, penyesuaian: 0, outlier: 0, jatah: 100000, lewat: false }] };
  const [r] = advisorDailySeries(m, '2026-10-01', '2026-10-01', '2026-10-01');
  assert.equal(r.status, 'ok');
  assert.equal(r.variabel, 0);
  assert.equal(r.redup, 500000);
});

test('KPI values come straight from metrics', () => {
  const k = advisorKpi(METRICS);
  assert.deepEqual(k.jatah, { spent: 297100, j0: 165100 });
  assert.equal(k.sisa.value, 1685200);
  assert.equal(k.sisa.dayLabel, 'Hari ke-19 dari 30');
  assert.equal(k.sisa.j1, 153200);
  assert.equal(k.terpakai.persen, 71);
  assert.equal(Math.round(k.terpakai.waktu * 100), 63);
  assert.equal(k.terpakai.proyeksi, 11811157);
  assert.equal(k.income.value, 7500000);
  assert.equal(k.income.saya, 0);
  assert.equal(k.income.kekurangan, 525957);
});

test('KPI values: null metrics stay null (last day, first two days)', () => {
  const k = advisorKpi({ ...METRICS, j1: null, proyeksi_akhir: null, kekurangan: null, dana_belanja: 0 });
  assert.equal(k.sisa.j1, null);
  assert.equal(k.terpakai.proyeksi, null);
  assert.equal(k.terpakai.persen, null);
  assert.equal(k.terpakai.fill, 0);
  assert.equal(k.income.kekurangan, null);
});
