import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldShowTelegramPrompt, isLinkCodeUsable, telegramPromptMode } from './telegramPrompt.js';

const DAY = 24 * 60 * 60 * 1000;
const NOW = Date.UTC(2026, 9, 2, 12, 0, 0);
const base = {
  telegramLinked: false,
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

const SEC = 1000;

test('link code made a minute ago is usable', () => {
  assert.equal(isLinkCodeUsable(NOW - 60 * SEC, NOW), true);
});

test('link code is dead after the 5-minute backend TTL', () => {
  assert.equal(isLinkCodeUsable(NOW - 301 * SEC, NOW), false);
});

test('a code about to die is refreshed before opening Telegram', () => {
  assert.equal(isLinkCodeUsable(NOW - 290 * SEC, NOW, 15 * SEC), false);
});

test('no code yet is not usable', () => {
  assert.equal(isLinkCodeUsable(0, NOW), false);
});

test('user from the bot who just onboarded is sent back to Telegram', () => {
  assert.equal(telegramPromptMode({ ...base, telegramLinked: true, justOnboarded: true }), 'return');
});

test('user from the bot sees nothing on a normal visit', () => {
  assert.equal(telegramPromptMode({ ...base, telegramLinked: true }), null);
});

test('web user who just onboarded is asked to connect Telegram', () => {
  assert.equal(telegramPromptMode({ ...base, justOnboarded: true }), 'connect');
});
