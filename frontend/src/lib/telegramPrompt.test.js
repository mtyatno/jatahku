import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldShowTelegramPrompt } from './telegramPrompt.js';

const DAY = 24 * 60 * 60 * 1000;
const NOW = Date.UTC(2026, 9, 2, 12, 0, 0);
const base = {
  telegramLinked: false,
  whatsappLinked: false,
  hasEnvelopes: true,
  justOnboarded: false,
  lastShownAt: null,
  now: NOW,
};

test('shown right after onboarding even if shown earlier today', () => {
  assert.equal(shouldShowTelegramPrompt({ ...base, justOnboarded: true, lastShownAt: NOW - DAY / 24 }), true);
});

test('never shown once Telegram is linked', () => {
  assert.equal(shouldShowTelegramPrompt({ ...base, justOnboarded: true, telegramLinked: true }), false);
});

test('never shown once WhatsApp is linked', () => {
  assert.equal(shouldShowTelegramPrompt({ ...base, justOnboarded: true, whatsappLinked: true }), false);
});

test('not shown before onboarding is done', () => {
  assert.equal(shouldShowTelegramPrompt({ ...base, hasEnvelopes: false }), false);
});

test('shown to an onboarded user who has never seen it', () => {
  assert.equal(shouldShowTelegramPrompt({ ...base }), true);
});

test('not shown again two days after the last time', () => {
  assert.equal(shouldShowTelegramPrompt({ ...base, lastShownAt: NOW - 2 * DAY }), false);
});

test('shown again eight days after the last time', () => {
  assert.equal(shouldShowTelegramPrompt({ ...base, lastShownAt: NOW - 8 * DAY }), true);
});
