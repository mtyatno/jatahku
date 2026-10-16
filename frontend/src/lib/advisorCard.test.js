import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  dismissOptions, visibleItems, badgeCount, overflowLabel, primaryAction, askChips, askAction,
} from './advisorCard.js';

// Bentuk `advisor` dari susun_dashboard(contoh_15_okt()) dengan aturan S4 (02-aturan.md §12).
const TAG01 = {
  id: 'TAG-01:kpr', aturan: 'TAG-01', tone: 'danger', judul: 'Lunasi KPR Rumah — telat 9 hari',
  isi: 'Rp1.600.000, jatuh tempo 6 Okt.',
  aksi: [{ kind: 'pay', label: 'Bayar sekarang', payload: { recurring_id: 'kpr' } }],
  dismiss: { kunci: 'TAG-01:kpr', pilihan: ['nanti', 'periode', 'tidak_relevan'] },
};
const PER01 = {
  id: 'PER-01:2026-09-27', aturan: 'PER-01', tone: 'warn', judul: 'Rem belanja harian ke Rp153 rb',
  aksi: [{ kind: 'chat', label: 'Tanya di chat', payload: { teks: 'Kenapa dana belanja kurang?' } }],
  dismiss: { kunci: 'PER-01:2026-09-27', pilihan: ['nanti', 'periode'] },
  rincian: [{ id: 'HAR-01:2026-10-15', aturan: 'HAR-01', judul: 'Belanja hari ini 1,8× jatah', isi: '…' }],
};
const DAT05 = {
  id: 'DAT-05:x', aturan: 'DAT-05', tone: 'info', judul: 'Klasifikasikan 1 amplop',
  aksi: [{ kind: 'route', label: 'Klasifikasikan', payload: { path: '/envelopes' } }],
  dismiss: { kunci: 'DAT-05:x' },
};
const ADVISOR = {
  items: [TAG01, PER01, DAT05],
  sisa: [{ id: 'TAB-01:darurat', judul_pendek: 'Dana Darurat baru 4%' }],
  total: 4, aman: null,
};

test('dismiss options follow the server list, labels from §9', () => {
  assert.deepEqual(dismissOptions(TAG01).map(o => o.label), ['Nanti', 'Sembunyikan periode ini', 'Tidak relevan']);
  assert.deepEqual(dismissOptions(PER01).map(o => o.pilihan), ['nanti', 'periode']);
  assert.equal(dismissOptions(DAT05).length, 3);
  assert.deepEqual(dismissOptions({ id: 'x' }), []);
});

test('hidden items drop out of the list and the badge until the reload arrives', () => {
  assert.equal(visibleItems(ADVISOR).length, 3);
  assert.equal(badgeCount(ADVISOR), 4);
  assert.deepEqual(visibleItems(ADVISOR, ['TAG-01:kpr']).map(i => i.aturan), ['PER-01', 'DAT-05']);
  assert.equal(badgeCount(ADVISOR, ['TAG-01:kpr']), 3);
  assert.equal(badgeCount(ADVISOR, ['TAB-01:darurat']), 4); // sisa tidak bisa disembunyikan dari kartu
  assert.equal(badgeCount({ items: [TAG01], sisa: [] }), 1);
  assert.deepEqual(visibleItems(null), []);
});

test('overflow names at most two short titles', () => {
  assert.equal(overflowLabel(ADVISOR.sisa), '+1 saran lain: Dana Darurat baru 4%');
  assert.equal(overflowLabel([{ judul_pendek: 'A' }, { judul_pendek: 'B' }, { judul_pendek: 'C' }]), '+3 saran lain: A · B · +1');
  assert.equal(overflowLabel([]), '');
  assert.equal(overflowLabel(undefined), '');
});

test('primary action is the first server action', () => {
  assert.equal(primaryAction(TAG01).kind, 'pay');
  assert.equal(primaryAction({ aksi: [] }), null);
});

test('ask chips: questions from active insights first, then fixed intents, max 4, no duplicates', () => {
  const dash = {
    advisor: ADVISOR,
    kpi: {
      jatah: { aksi: [{ kind: 'chat', payload: { teks: 'Kenapa belanja hari ini lewat jatah?' } }] },
      sisa_bebas: PER01, // pertanyaan sama dengan item daftar
      tagihan: null,
    },
  };
  const chips = askChips(dash);
  assert.deepEqual(chips.map(c => c.text), [
    'Kenapa dana belanja kurang?', 'Kenapa belanja hari ini lewat jatah?', 'kapan habis', 'limit harian',
  ]);
  assert.equal(chips[2].label, 'Kapan habis?');
  assert.equal(askChips({}).length, 4);
  assert.equal(askChips(dash, 3).length, 3);
});

test('ask action sends the tapped chip and keeps the rest in the chat', () => {
  const chips = askChips({ advisor: ADVISOR });
  const a = askAction(chips, chips[0]);
  assert.equal(a.kind, 'chat');
  assert.equal(a.payload.teks, 'Kenapa dana belanja kurang?');
  assert.equal(a.payload.kirim, true);
  assert.equal(a.payload.chip.length, chips.length - 1);
  assert.deepEqual(askAction(chips, null), { kind: 'chat', payload: { chip: chips } });
});
