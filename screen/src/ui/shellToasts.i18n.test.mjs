// Shell toasts, prompts and launcher labels: pin that they are marked in the
// code, present in every shipped catalog, and that no bare literal is left at
// the call sites (`window.prompt/confirm` and constants are invisible to the
// unmarked-text checker).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  extractMessages,
  readCatalog,
  shippedLocales,
} from '../../scripts/i18n.mjs';

const KEYS = [
  'Tilted view',
  'Straight-down view',
  'North up',
  'Detailed outline unavailable',
];

const messages = extractMessages();

for (const key of KEYS) {
  test(`marked for translation: ${key}`, () => {
    assert.ok(messages.has(key), `not marked with t()/msg(): ${key}`);
  });
  for (const locale of shippedLocales()) {
    test(`${locale} catalog translates: ${key}`, () => {
      const value = readCatalog(locale)[key];
      assert.ok(value, `missing in ${locale}.json`);
      assert.notEqual(value, key);
    });
  }
}

test('no bare literal reaches showToast in the orientation and navigation code', () => {
  for (const file of [
    '../ui/cameraOrientationControls.js',
    '../navigationPolicy.js',
    '../ui/locationNavigation.js',
    '../ui/panelPositionControls.js',
  ]) {
    const source = readFileSync(
      fileURLToPath(new URL(file, import.meta.url)),
      'utf8',
    );
    assert.doesNotMatch(
      source,
      /_?showToast\??\.?\(\s*['"`]/,
      `${file} passes a bare literal to showToast`,
    );
  }
});
