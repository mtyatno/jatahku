import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeAction, safeRoute, parseTransactionsQuery, periodIndexFor, parseAllocateQuery,
  incomePrefill, recurringPrefill, chatDraft, kebutuhanTotal, rencanaTotal, excludedSources,
  toggleRow, executeBody, newClientRef, isIsoDate, dismissNotice,
} from './advisorAction.js';

test('normalizeAction: string lama tetap jalan', () => {
  assert.deepEqual(normalizeAction('balance'), { kind: 'balance', payload: {} });
  assert.deepEqual(normalizeAction('chat'), { kind: 'chat', payload: {} });
  assert.equal(normalizeAction('hapus-semua'), null);
});

test('normalizeAction: objek {kind, payload}', () => {
  assert.deepEqual(normalizeAction({ kind: 'pay', label: 'Bayar', payload: { recurring_id: 'r1' } }),
    { kind: 'pay', payload: { recurring_id: 'r1' }, label: 'Bayar' });
  assert.deepEqual(normalizeAction({ kind: 'route' }), { kind: 'route', payload: {} });
  assert.deepEqual(normalizeAction({ kind: 'income', payload: 'x' }), { kind: 'income', payload: {} });
  assert.equal(normalizeAction({ kind: 'eval' }), null);
  assert.equal(normalizeAction(null), null);
  assert.equal(normalizeAction(42), null);
});

test('safeRoute hanya path dalam app', () => {
  assert.equal(safeRoute('/transactions?date=2026-10-12&envelope=e1'), '/transactions?date=2026-10-12&envelope=e1');
  assert.equal(safeRoute('/allocate/?new=1'), '/allocate?new=1');
  assert.equal(safeRoute('/'), '/');
  assert.equal(safeRoute('//evil.com/transactions'), null);
  assert.equal(safeRoute('https://evil.com/transactions'), null);
  assert.equal(safeRoute('javascript:alert(1)'), null);
  assert.equal(safeRoute('/admin'), null);
  assert.equal(safeRoute(undefined), null);
});

test('parseTransactionsQuery memvalidasi tanggal', () => {
  assert.deepEqual(parseTransactionsQuery('?date=2026-10-12&envelope=e1'), { envelope: 'e1', date: '2026-10-12' });
  assert.deepEqual(parseTransactionsQuery('?date=kemarin'), { envelope: null, date: null });
  assert.deepEqual(parseTransactionsQuery(''), { envelope: null, date: null });
  assert.equal(isIsoDate('2026-13-45'), false);
});

test('periodIndexFor memilih periode yang memuat tanggal', () => {
  const periods = [
    { period_start: '2026-08-25', period_end: '2026-09-24' },
    { period_start: '2026-09-25', period_end: '2026-10-24' },
  ];
  assert.equal(periodIndexFor(periods, '2026-09-25'), 1);
  assert.equal(periodIndexFor(periods, '2026-09-24'), 0);
  assert.equal(periodIndexFor(periods, '2025-01-01'), null);
  assert.equal(periodIndexFor(periods, null), null);
});

test('parseAllocateQuery', () => {
  assert.deepEqual(parseAllocateQuery('?new=1&amount=7500000&source=Gaji%20Okt'), { open: true, amount: 7500000, source: 'Gaji Okt' });
  assert.deepEqual(parseAllocateQuery('?amount=-5'), { open: false, amount: null, source: null });
});

test('incomePrefill & recurringPrefill', () => {
  assert.deepEqual(incomePrefill({ jumlah: 525957.4, sumber: 'Bonus' }), { amount: '525957', source: 'Bonus', envelopeId: null });
  assert.deepEqual(incomePrefill(), { amount: '', source: 'Gaji', envelopeId: null });
  assert.deepEqual(
    recurringPrefill({ deskripsi: 'Spotify', jumlah: 54990, frekuensi: 'monthly', amplop_id: 'e2', next_run: '2026-11-03' }),
    { description: 'Spotify', amount: '54990', frequency: 'monthly', envelopeId: 'e2', nextRun: '2026-11-03' },
  );
  assert.equal(recurringPrefill({ frekuensi: 'daily' }).frequency, 'monthly');
  assert.equal(recurringPrefill({ next_run: 'besok' }).nextRun, null);
});

test('chatDraft: teks + chip', () => {
  const d = chatDraft({ teks: 'kenapa boros?', chip: ['sisa', { label: 'Kapan habis?', text: 'kapan habis' }, { label: '' }] });
  assert.equal(d.text, 'kenapa boros?');
  assert.deepEqual(d.chips, [{ label: 'sisa', text: 'sisa' }, { label: 'Kapan habis?', text: 'kapan habis' }]);
  assert.equal(d.send, false);
  assert.equal(chatDraft({ text: 'sisa', send: true }).send, true);
});

test('lembar rencana: total, lepas centang, body execute', () => {
  const rencana = [
    { dari_id: 'a', jumlah: 453000, tercentang: true },
    { dari_id: 'b', jumlah: 1410000, tercentang: true, tingkat: 'c' },
    { dari_id: 'c', jumlah: 145174, tercentang: false },
  ];
  assert.equal(kebutuhanTotal([{ jumlah: 2008174 }]), 2008174);
  assert.equal(rencanaTotal(rencana), 1863000);
  const off = toggleRow(rencana, 'b');
  assert.equal(rencanaTotal(off), 453000);
  assert.equal(rencana[1].tercentang, true, 'tidak memutasi');
  assert.deepEqual(excludedSources(off, ['z']), ['z', 'b', 'c']);
  const body = executeBody({ rencana, bayar: [{ recurring_id: 'r', jumlah: 1 }], saldo_versi: 'h' }, 'ref1');
  assert.deepEqual(body.rencana.map(r => r.dari_id), ['a', 'b']);
  assert.deepEqual(body.bayar, [{ recurring_id: 'r', jumlah: 1 }]);
  assert.equal(body.saldo_versi, 'h');
  assert.equal(body.client_ref, 'ref1');
  assert.equal(body.kebutuhan, undefined);
});

test('executeBody mengirim balik kebutuhan & kecuali untuk rencana_baru', () => {
  const kebutuhan = [{ tujuan_id: 't', jumlah: 5 }];
  const body = executeBody({ rencana: [], bayar: [], saldo_versi: 'h', kebutuhan, kecuali: ['x'], sertakan: [] }, 'r');
  assert.deepEqual(body.kebutuhan, kebutuhan);
  assert.deepEqual(body.kecuali, ['x']);
  assert.equal(body.sertakan, undefined);
});

test('newClientRef unik', () => {
  assert.notEqual(newClientRef(), newClientRef());
});

test('undismiss & teks toast dismiss (#91)', () => {
  assert.deepEqual(normalizeAction({ kind: 'undismiss', payload: { kunci: 'HAR-01:2026-10-17' } }),
    { kind: 'undismiss', payload: { kunci: 'HAR-01:2026-10-17' } });
  assert.equal(dismissNotice('dismiss', 'nanti'), 'Disembunyikan sampai besok 05.00');
  assert.equal(dismissNotice('dismiss', 'periode'), 'Disembunyikan sampai akhir periode');
  assert.equal(dismissNotice('dismiss', 'tidak_relevan'), 'Ditandai tidak relevan');
  assert.equal(dismissNotice('dismiss', undefined), 'Disembunyikan sampai besok 05.00');
  assert.equal(dismissNotice('not_duplicate', 'tidak_relevan'), 'Ditandai bukan dobel');
});
