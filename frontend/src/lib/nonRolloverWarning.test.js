import { test } from 'node:test';
import assert from 'node:assert/strict';
import { nonRolloverWarning } from './nonRolloverWarning.js';

const RESET = { is_rollover: false };

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

// Teks lengkap untuk `tgl` ("24 Nov") dan `sisa` ("3 hari lagi" / "hari ini").
const text = (tgl, sisa) =>
  `Amplop ini tidak membawa sisa ke periode berikutnya. Yang tidak terpakai di-reset ${tgl} (${sisa}).`;

// Jalankan `fn(tz)` di beberapa zona waktu (UTC, WIB, DST AS, ekstrem +14 / -11) seperti receiptScan.test.js,
// supaya tes zona tetap bermakna meski mesin/CI berzona UTC. Objek Date harus dibuat di dalam `fn`.
function inZones(fn) {
  const saved = process.env.TZ;
  try {
    for (const tz of ['UTC', 'Asia/Jakarta', 'America/New_York', 'Pacific/Kiritimati', 'Pacific/Pago_Pago']) {
      process.env.TZ = tz;
      fn(tz);
    }
  } finally {
    if (saved === undefined) delete process.env.TZ;
    else process.env.TZ = saved;
  }
}

test('rollover envelope never warns', () => {
  assert.equal(nonRolloverWarning({ is_rollover: true }, '2026-11-24', '2026-11-21', 100000), null);
  assert.equal(nonRolloverWarning({ is_rollover: true }, '2026-11-24', '2026-11-24', 100000), null);
});

test('non-rollover 3 days before end', () => {
  assert.equal(
    nonRolloverWarning({ is_rollover: false }, '2026-11-24', '2026-11-21', 100000),
    'Amplop ini tidak membawa sisa ke periode berikutnya. Yang tidak terpakai di-reset 24 Nov (3 hari lagi).',
  );
});

test('on the last day says hari ini', () => {
  assert.equal(
    nonRolloverWarning(RESET, '2026-11-24', '2026-11-24', 100000),
    'Amplop ini tidak membawa sisa ke periode berikutnya. Yang tidak terpakai di-reset 24 Nov (hari ini).',
  );
});

test('8 days before end is silent', () => {
  assert.equal(nonRolloverWarning(RESET, '2026-11-24', '2026-11-16', 100000), null);
});

test('zero amount is silent', () => {
  assert.equal(nonRolloverWarning(RESET, '2026-11-24', '2026-11-21', 0), null);
  // Apa pun yang bukan jumlah positif: kosong, negatif, bukan angka.
  for (const amount of [undefined, null, '', -5, NaN, 'abc']) {
    assert.equal(nonRolloverWarning(RESET, '2026-11-24', '2026-11-21', amount), null, `amount=${String(amount)}`);
  }
});

test('missing is_rollover field is silent', () => {
  assert.equal(nonRolloverWarning({}, '2026-11-24', '2026-11-21', 100000), null);
  assert.equal(nonRolloverWarning(undefined, '2026-11-24', '2026-11-21', 100000), null);
});

test('month names', () => {
  assert.equal(nonRolloverWarning(RESET, '2026-08-31', '2026-08-30', 100000), text('31 Agu', '1 hari lagi'));
  MONTHS.forEach((bln, i) => {
    const mm = String(i + 1).padStart(2, '0');
    assert.equal(nonRolloverWarning(RESET, `2026-${mm}-15`, `2026-${mm}-14`, 1), text(`15 ${bln}`, '1 hari lagi'));
  });
});

// --- Batas dan masukan yang tidak tercakup tujuh tes di atas ---

test('7 days before end is the first day that warns', () => {
  assert.equal(nonRolloverWarning(RESET, '2026-11-24', '2026-11-17', 100000), text('24 Nov', '7 hari lagi'));
});

test('after the period end is silent', () => {
  assert.equal(nonRolloverWarning(RESET, '2026-11-24', '2026-11-25', 100000), null);
});

test('day of month is not zero-padded', () => {
  assert.equal(nonRolloverWarning(RESET, '2026-12-05', '2026-12-02', 100000), text('5 Des', '3 hari lagi'));
});

test('amount typed as numeric text still counts', () => {
  assert.equal(nonRolloverWarning(RESET, '2026-11-24', '2026-11-21', '100000'), text('24 Nov', '3 hari lagi'));
});

test('no period end is silent', () => {
  for (const periodEnd of [undefined, null, '']) {
    assert.equal(nonRolloverWarning(RESET, periodEnd, '2026-11-21', 100000), null, `periodEnd=${String(periodEnd)}`);
  }
});

test('unparseable dates are silent, never "NaN hari lagi"', () => {
  assert.equal(nonRolloverWarning(RESET, 'besok', '2026-11-21', 100000), null);
  assert.equal(nonRolloverWarning(RESET, '2026-13-45', '2026-11-21', 100000), null);
  assert.equal(nonRolloverWarning(RESET, '2026-02-30', '2026-02-27', 100000), null);
  assert.equal(nonRolloverWarning(RESET, '2026-11-24', 'kemarin', 100000), null);
  assert.equal(nonRolloverWarning(RESET, '2026-11-24', new Date('x'), 100000), null);
  assert.equal(nonRolloverWarning(RESET, '2026-11-24', undefined, 100000), null);
});

test('a Date today counts its local calendar day, early morning or late night, in any time zone', () => {
  // Dibangun dari komponen lokal: hari kalendernya tetap 21 Nov di zona mana pun; implementasi yang
  // lewat toISOString()/UTC meleset sehari di zona di depan atau di belakang UTC.
  inZones(tz => {
    for (const today of [new Date(2026, 10, 21, 0, 5), new Date(2026, 10, 21, 12, 0), new Date(2026, 10, 21, 23, 55)]) {
      assert.equal(nonRolloverWarning(RESET, '2026-11-24', today, 100000), text('24 Nov', '3 hari lagi'), tz);
    }
    assert.equal(nonRolloverWarning(RESET, '2026-11-24', new Date(2026, 10, 24, 23, 55), 100000), text('24 Nov', 'hari ini'), tz);
  });
});

test('counts calendar days across month, year, leap-day and DST boundaries, in any time zone', () => {
  const sisa = (end, today) => nonRolloverWarning(RESET, end, today, 1)?.match(/\(([^)]+)\)\.$/)?.[1];
  inZones(tz => {
    assert.equal(sisa('2026-12-02', '2026-11-28'), '4 hari lagi', tz); // pergantian bulan
    assert.equal(sisa('2027-01-02', '2026-12-30'), '3 hari lagi', tz); // pergantian tahun
    assert.equal(sisa('2028-03-02', '2028-02-27'), '4 hari lagi', tz); // Februari kabisat: 28, 29, 1, 2 Mar
    assert.equal(sisa('2027-03-02', '2027-02-27'), '3 hari lagi', tz); // Februari biasa: 28, 1, 2 Mar
    assert.equal(sisa('2026-03-09', '2026-03-06'), '3 hari lagi', tz); // lintas DST AS maju (8 Mar): hari itu hanya 23 jam
    assert.equal(sisa('2026-11-02', '2026-10-30'), '3 hari lagi', tz); // lintas DST AS mundur (1 Nov): hari itu 25 jam
    // Date lokal lintas DST: 6 Mar 23.55 -> 9 Mar, selisih jam dinding bukan kelipatan 24 jam
    assert.equal(
      nonRolloverWarning(RESET, '2026-03-09', new Date(2026, 2, 6, 23, 55), 1),
      text('9 Mar', '3 hari lagi'),
      tz,
    );
  });
});
