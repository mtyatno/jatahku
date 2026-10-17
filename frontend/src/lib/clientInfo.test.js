import test from 'node:test';
import assert from 'node:assert/strict';
import { CLIENT, CLIENT_HEADER, CLIENT_HEADER_VALUE, clientHeaderValue, withClientHeader } from './clientInfo.js';

test('format header platform/versi/build', () => {
  assert.equal(clientHeaderValue({ platform: 'android', version: '1.2.0', build: '37' }), 'android/1.2.0/37');
  assert.equal(clientHeaderValue({ platform: 'web', version: '0.1.0', build: '46a22cc' }), 'web/0.1.0/46a22cc');
});

test('nilai rusak diganti aman', () => {
  assert.equal(clientHeaderValue({ platform: 'desktop', version: 'v1', build: 'a/b' }), 'web/0.0.0/dev');
  assert.equal(clientHeaderValue(), 'web/0.0.0/dev');
});

test('tanpa konstanta build (node --test) klien adalah web', () => {
  assert.equal(CLIENT.platform, 'web');
  assert.match(CLIENT_HEADER_VALUE, /^web\//);
});

test('withClientHeader menambah header tanpa menimpa milik pemanggil', () => {
  assert.equal(CLIENT_HEADER, 'X-Jatahku-Client');
  const h = withClientHeader({ 'Content-Type': 'application/json' });
  assert.equal(h['Content-Type'], 'application/json');
  assert.equal(h[CLIENT_HEADER], CLIENT_HEADER_VALUE);
  assert.equal(withClientHeader({ [CLIENT_HEADER]: 'ios/1.0.0/1' })[CLIENT_HEADER], 'ios/1.0.0/1');
  assert.equal(withClientHeader(undefined)[CLIENT_HEADER], CLIENT_HEADER_VALUE);
});
