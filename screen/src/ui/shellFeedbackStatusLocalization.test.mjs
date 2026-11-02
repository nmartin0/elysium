// The global loading chip in the UI language: the status vocabulary, the ALPR
// retry prefix and every mapped-site failure reason.
import test from 'node:test';
import assert from 'node:assert/strict';
import { setLocale, t } from '../i18n/index.js';
import {
  aggregateLayerLoading,
  createLoadingFeedbackState,
  presentLoadingFeedback,
  reduceLoadingFeedback,
} from '../loadingFeedback.js';

const elements = {
  'global-loading-status': { hidden: true, dataset: {} },
  'global-loading-detail': { textContent: '' },
};
globalThis.document ??= {
  getElementById: (id) => elements[id] ?? null,
  addEventListener() {},
  removeEventListener() {},
  hidden: false,
};
const { ShellFeedback, localizeLoadingPresentation } =
  await import('./shellFeedback.js');

test.afterEach(() => setLocale('en'));

test('English presentation passes through unchanged', () => {
  setLocale('en');
  for (const label of [
    'OVERPASS TEMPORARILY UNAVAILABLE',
    'OVERPASS RATE-LIMITED',
    'OVERPASS TIMED OUT',
    'OVERPASS COULD NOT COMPLETE THE QUERY',
    'MAP TILES TEMPORARILY UNAVAILABLE',
    'MAPPED NAMES TEMPORARILY UNAVAILABLE',
  ]) {
    assert.deepEqual(
      localizeLoadingPresentation({
        state: 'retry',
        label,
        detail: 'retrying in 12s',
      }),
      { state: 'retry', label, detail: 'retrying in 12s' },
    );
  }
});

for (const locale of ['es', 'ru']) {
  test(`${locale}: every mapped-site retry label is translated with its detail`, () => {
    setLocale(locale);
    for (const label of [
      'OVERPASS TEMPORARILY UNAVAILABLE',
      'OVERPASS RATE-LIMITED',
      'OVERPASS TIMED OUT',
      'OVERPASS COULD NOT COMPLETE THE QUERY',
      'MAP TILES TEMPORARILY UNAVAILABLE',
      'MAPPED NAMES TEMPORARILY UNAVAILABLE',
    ]) {
      const localized = localizeLoadingPresentation({
        state: 'retry',
        label,
        detail: 'retrying in 12s',
      });
      assert.notEqual(localized.label, label, `label stays English: ${label}`);
      assert.notEqual(localized.detail, 'retrying in 12s');
    }
  });

  test(`${locale}: a live provider error label passes through verbatim`, () => {
    setLocale(locale);
    const localized = localizeLoadingPresentation({
      state: 'retry',
      label: 'HTTP 503 FROM OVERPASS-API.DE',
      detail: 'retry pending',
    });
    assert.equal(localized.label, 'HTTP 503 FROM OVERPASS-API.DE');
    assert.notEqual(localized.detail, 'retry pending');
  });
}
