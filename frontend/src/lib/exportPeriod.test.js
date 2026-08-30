import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  buildExportCsvUrl,
  buildExportPdfUrl,
  getExportFilename,
  getExportButtonLabel,
  resolveActivePeriod,
  findPeriodIndex,
  canGoPrev,
  canGoNext,
  getPrevPeriodIndex,
  getNextPeriodIndex,
} from './exportPeriod.js';

// ── buildExportCsvUrl & buildExportPdfUrl ────────────────────────
test('buildExportCsvUrl: generates /export/csv query URL correctly', () => {
  const url1 = buildExportCsvUrl({ period_start: '2026-08-01', period_end: '2026-08-31' });
  assert.equal(url1, '/export/csv?period_start=2026-08-01&period_end=2026-08-31');

  const url2 = buildExportCsvUrl({ periodStart: '2026-07-01', periodEnd: '2026-07-31' });
  assert.equal(url2, '/export/csv?period_start=2026-07-01&period_end=2026-07-31');

  const url3 = buildExportCsvUrl({ periodStart: '2026-08-01', periodEnd: '2026-08-31', envelopeId: 'env-123' });
  assert.equal(url3, '/export/csv?period_start=2026-08-01&period_end=2026-08-31&envelope_id=env-123');

  assert.equal(buildExportCsvUrl(), '/export/csv');
  assert.equal(buildExportCsvUrl(null), '/export/csv');
});

test('buildExportPdfUrl: generates /export/pdf query URL correctly', () => {
  const url1 = buildExportPdfUrl({ period_start: '2026-08-01', period_end: '2026-08-31' });
  assert.equal(url1, '/export/pdf?period_start=2026-08-01&period_end=2026-08-31');

  const url2 = buildExportPdfUrl({ periodStart: '2026-07-01', periodEnd: '2026-07-31' });
  assert.equal(url2, '/export/pdf?period_start=2026-07-01&period_end=2026-07-31');

  const url3 = buildExportPdfUrl({ period_start: '2026-08-01', period_end: '2026-08-31', envelope_id: 'env-abc' });
  assert.equal(url3, '/export/pdf?period_start=2026-08-01&period_end=2026-08-31&envelope_id=env-abc');

  assert.equal(buildExportPdfUrl(), '/export/pdf');
  assert.equal(buildExportPdfUrl(null), '/export/pdf');
});

// ── getExportFilename ────────────────────────────────────────────
test('getExportFilename: generates formatted filenames for CSV and PDF', () => {
  const period = { period_start: '2026-08-01', period_end: '2026-08-31' };
  assert.equal(getExportFilename('csv', period), 'jatahku_2026-08-01_2026-08-31.csv');
  assert.equal(getExportFilename('pdf', period), 'jatahku_2026-08-01_2026-08-31.pdf');

  const periodCamel = { periodStart: '2026-07-01', periodEnd: '2026-07-31' };
  assert.equal(getExportFilename('csv', periodCamel), 'jatahku_2026-07-01_2026-07-31.csv');
  assert.equal(getExportFilename('pdf', periodCamel), 'jatahku_2026-07-01_2026-07-31.pdf');

  assert.equal(getExportFilename('csv'), 'jatahku_export.csv');
  assert.equal(getExportFilename('pdf', {}), 'jatahku_export.pdf');
});

// ── getExportButtonLabel ─────────────────────────────────────────
test('getExportButtonLabel: prefixes label with "Laporan " avoiding duplication', () => {
  assert.equal(getExportButtonLabel('Agustus 2026'), 'Laporan Agustus 2026');
  assert.equal(getExportButtonLabel('01 Agu – 31 Agu 2026'), 'Laporan 01 Agu – 31 Agu 2026');
  assert.equal(getExportButtonLabel('Laporan Agustus 2026'), 'Laporan Agustus 2026');
  assert.equal(getExportButtonLabel(''), 'Laporan');
  assert.equal(getExportButtonLabel(null), 'Laporan');
  assert.equal(getExportButtonLabel(undefined), 'Laporan');
});

// ── resolveActivePeriod & findPeriodIndex ────────────────────────
test('resolveActivePeriod: matches existing period or defaults to latest or fallback', () => {
  const periods = [
    { period_start: '2026-06-01', period_end: '2026-06-30', label: 'Juni 2026' },
    { period_start: '2026-07-01', period_end: '2026-07-31', label: 'Juli 2026' },
    { period_start: '2026-08-01', period_end: '2026-08-31', label: 'Agustus 2026' },
  ];

  // Match existing period
  const resolved = resolveActivePeriod(periods, { periodStart: '2026-07-01', periodEnd: '2026-07-31' });
  assert.equal(resolved.period_start, '2026-07-01');
  assert.equal(resolved.label, 'Juli 2026');

  // Custom period not in array
  const custom = resolveActivePeriod(periods, {
    periodStart: '2026-05-01',
    periodEnd: '2026-05-31',
    periodLabel: 'Mei 2026',
  });
  assert.equal(custom.period_start, '2026-05-01');
  assert.equal(custom.label, 'Mei 2026');

  // No props provided -> defaults to latest period
  const latest = resolveActivePeriod(periods);
  assert.equal(latest.period_start, '2026-08-01');
  assert.equal(latest.label, 'Agustus 2026');

  // Empty periods array with label
  const fallbackWithLabel = resolveActivePeriod([], { periodLabel: 'Bulan Ini' });
  assert.equal(fallbackWithLabel.label, 'Bulan Ini');

  // Empty periods array without props
  assert.equal(resolveActivePeriod([]), null);
});

test('findPeriodIndex: locates period index in array', () => {
  const periods = [
    { period_start: '2026-06-01', period_end: '2026-06-30', label: 'Juni 2026' },
    { period_start: '2026-07-01', period_end: '2026-07-31', label: 'Juli 2026' },
    { period_start: '2026-08-01', period_end: '2026-08-31', label: 'Agustus 2026' },
  ];

  assert.equal(findPeriodIndex(periods, { period_start: '2026-06-01', period_end: '2026-06-30' }), 0);
  assert.equal(findPeriodIndex(periods, { periodStart: '2026-08-01', periodEnd: '2026-08-31' }), 2);
  assert.equal(findPeriodIndex(periods, { periodStart: '2025-01-01', periodEnd: '2025-01-31' }), -1);
  assert.equal(findPeriodIndex([], { periodStart: '2026-08-01', periodEnd: '2026-08-31' }), -1);
});

// ── Modal Navigation Helpers ─────────────────────────────────────
test('modal navigation helpers: canGoPrev, canGoNext, getPrevPeriodIndex, getNextPeriodIndex', () => {
  const total = 3;

  // At start (index 0)
  assert.equal(canGoPrev(0), false);
  assert.equal(canGoNext(0, total), true);
  assert.equal(getPrevPeriodIndex(0), 0);
  assert.equal(getNextPeriodIndex(0, total), 1);

  // At middle (index 1)
  assert.equal(canGoPrev(1), true);
  assert.equal(canGoNext(1, total), true);
  assert.equal(getPrevPeriodIndex(1), 0);
  assert.equal(getNextPeriodIndex(1, total), 2);

  // At end (index 2)
  assert.equal(canGoPrev(2), true);
  assert.equal(canGoNext(2, total), false);
  assert.equal(getPrevPeriodIndex(2), 1);
  assert.equal(getNextPeriodIndex(2, total), 2);

  // Invalid indices
  assert.equal(canGoPrev(-1), false);
  assert.equal(canGoNext(-1, total), false);
  assert.equal(canGoPrev(null), false);
  assert.equal(canGoNext(null, total), false);
});
