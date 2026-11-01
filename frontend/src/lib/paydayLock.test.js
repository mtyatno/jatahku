import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  PAYDAY_SAVE_DELAY_MS,
  householdPayday,
  parsePaydayDay,
  paydayLockState,
  joinSuccessMessage,
  onboardingProfileBody,
} from './paydayLock.js';

const CONFIRM_RUMAH_ANI =
  'Mengubah tanggal gajian berlaku untuk semua anggota Rumah Ani, dan riwayat anggarannya dihitung ulang. Lanjutkan?';

test('locked member shows owner note', () => {
  const s = paydayLockState({ payday_locked: true, household_payday_day: 25, payday_owner_name: 'Ani' });
  assert.equal(s.locked, true);
  assert.equal(s.note, 'Mengikuti siklus rumah tangga: tanggal 25 (diatur Ani).');
  assert.equal(s.needsConfirm, false);
  assert.equal(s.confirmText, null);
});

test('locked without owner name', () => {
  const expected = 'Mengikuti siklus rumah tangga: tanggal 25.';
  assert.equal(
    paydayLockState({ payday_locked: true, household_payday_day: 25, payday_owner_name: null }).note,
    expected,
  );
  assert.equal(paydayLockState({ payday_locked: true, household_payday_day: 25 }).note, expected);
});

test('locked note uses the household date, falling back to the mirrored payday_day', () => {
  const both = { payday_locked: true, household_payday_day: 25, payday_day: 1, payday_owner_name: 'Ani' };
  assert.equal(paydayLockState(both).note, 'Mengikuti siklus rumah tangga: tanggal 25 (diatur Ani).');
  const mirrorOnly = { payday_locked: true, payday_day: 10 };
  assert.equal(paydayLockState(mirrorOnly).note, 'Mengikuti siklus rumah tangga: tanggal 10.');
});

test('owner of two needs confirm', () => {
  const s = paydayLockState({ payday_locked: false, household_member_count: 2, household_name: 'Rumah Ani' });
  assert.equal(s.locked, false);
  assert.equal(s.note, null);
  assert.equal(s.needsConfirm, true);
  assert.equal(s.confirmText, CONFIRM_RUMAH_ANI);
});

test('confirm text never prints a missing household name', () => {
  const s = paydayLockState({ payday_locked: false, household_member_count: 3, household_name: null });
  assert.equal(s.needsConfirm, true);
  assert.equal(
    s.confirmText,
    'Mengubah tanggal gajian berlaku untuk semua anggota rumah tangga, dan riwayat anggarannya dihitung ulang. Lanjutkan?',
  );
});

test('solo saves directly', () => {
  const s = paydayLockState({ payday_locked: false, household_member_count: 1, household_name: 'Rumah Ani' });
  assert.deepEqual(s, { locked: false, note: null, needsConfirm: false, confirmText: null });
});

test('a locked member never gets the confirm dialog, whatever the member count', () => {
  const s = paydayLockState({ payday_locked: true, household_member_count: 3, household_payday_day: 25, household_name: 'Rumah Ani' });
  assert.equal(s.locked, true);
  assert.equal(s.needsConfirm, false);
  assert.equal(s.confirmText, null);
});

test('old profile without new fields is unlocked solo', () => {
  const s = paydayLockState({ id: 'u1', name: 'Budi', payday_day: 5 });
  assert.deepEqual(s, { locked: false, note: null, needsConfirm: false, confirmText: null });
});

test('no profile at all is unlocked solo', () => {
  const solo = { locked: false, note: null, needsConfirm: false, confirmText: null };
  assert.deepEqual(paydayLockState(null), solo);
  assert.deepEqual(paydayLockState(undefined), solo);
});

test('householdPayday prefers the household date, then the mirror, then 1', () => {
  assert.equal(householdPayday({ household_payday_day: 25, payday_day: 1 }), 25);
  assert.equal(householdPayday({ payday_day: 7 }), 7);
  assert.equal(householdPayday({ household_payday_day: null, payday_day: 7 }), 7);
  assert.equal(householdPayday({}), 1);
  assert.equal(householdPayday(null), 1);
});

test('payday save is debounced by 600 ms', () => {
  assert.equal(PAYDAY_SAVE_DELAY_MS, 600);
});

test('parsePaydayDay accepts whole days 1 to 31, as text or number', () => {
  assert.equal(parsePaydayDay('25'), 25);
  assert.equal(parsePaydayDay(25), 25);
  assert.equal(parsePaydayDay('1'), 1);
  assert.equal(parsePaydayDay('31'), 31);
  assert.equal(parsePaydayDay('05'), 5);
});

test('parsePaydayDay rejects empty, out of range and non-integer input instead of sending NaN', () => {
  for (const raw of ['', ' ', null, undefined, '0', '32', '-3', '2.5', 'abc', NaN]) {
    assert.equal(parsePaydayDay(raw), null, `expected null for ${JSON.stringify(raw)}`);
  }
});

test('joinSuccessMessage with payday names the household cycle', () => {
  assert.equal(
    joinSuccessMessage('Rumah Ani', 25),
    'Berhasil bergabung ke Rumah Ani! Siklus anggaranmu sekarang mengikuti rumah ini: tanggal 25.',
  );
});

test('joinSuccessMessage without payday keeps the old message', () => {
  assert.equal(joinSuccessMessage('Rumah Ani'), 'Berhasil bergabung ke Rumah Ani!');
  assert.equal(joinSuccessMessage('Rumah Ani', null), 'Berhasil bergabung ke Rumah Ani!');
  assert.equal(joinSuccessMessage('Rumah Ani', undefined), 'Berhasil bergabung ke Rumah Ani!');
});

test('onboarding sends payday_day and income_type for an unlocked profile', () => {
  const body = onboardingProfileBody({ payday_locked: false }, { paydayDay: 25, incomeType: 'monthly' });
  assert.deepEqual(body, { payday_day: 25, income_type: 'monthly' });
});

test('onboarding omits payday_day for a locked member so income_type still saves', () => {
  const body = onboardingProfileBody(
    { payday_locked: true, household_payday_day: 25, payday_owner_name: 'Ani' },
    { paydayDay: 1, incomeType: 'weekly' },
  );
  assert.deepEqual(body, { income_type: 'weekly' });
  assert.equal('payday_day' in body, false);
});

test('onboarding omits payday_day for an owner or admin of a household with more members', () => {
  // Onboarding tidak punya dialog konfirmasi; mengubah tanggal rumah berisi >1 anggota menghitung ulang riwayatnya dan
  // memberi tahu semua anggota, jadi itu hanya lewat Settings (Simpan + konfirmasi).
  for (const profile of [
    { payday_locked: false, household_member_count: 2, household_name: 'Rumah Ani', household_payday_day: 25 },
    { payday_locked: false, household_member_count: 5 },
  ]) {
    const body = onboardingProfileBody(profile, { paydayDay: 1, incomeType: 'daily' });
    assert.deepEqual(body, { income_type: 'daily' });
    assert.equal('payday_day' in body, false);
  }
});

test('onboarding still sends payday_day for a solo household', () => {
  const body = onboardingProfileBody(
    { payday_locked: false, household_member_count: 1, household_name: 'Rumah Ani' },
    { paydayDay: 25, incomeType: 'monthly' },
  );
  assert.deepEqual(body, { payday_day: 25, income_type: 'monthly' });
});

test('onboarding keeps the old body when the profile is unknown or old', () => {
  const fields = { paydayDay: 1, incomeType: 'daily' };
  assert.deepEqual(onboardingProfileBody(null, fields), { payday_day: 1, income_type: 'daily' });
  assert.deepEqual(onboardingProfileBody({ payday_day: 5 }, fields), { payday_day: 1, income_type: 'daily' });
});
