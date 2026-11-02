// Refusals and failures that source modules produce in English reach
// the page translated — through a placeholder at the point of display, or
// through a catalog entry when the text is stored as data.
import assert from 'node:assert/strict';
import test from 'node:test';
import { setLocale, t, translateKnown } from '../i18n/index.js';
import { createWeatherSource } from '../layers/weather/source.js';
import { presentRoutingFailure } from '../layers/directions/index.js';
import { translateFeedError } from './statusText.js';

for (const locale of ['es', 'ru']) {
  test(`${locale}: the route proxy's refusals are shown translated`, () => {
    setLocale(locale);
    try {
      // Directions stores these in English; the Layers panel shows them
      // through translateFeedError.
      const shown = translateFeedError('Routing failed: route leg too long');
      assert.equal(
        shown,
        t('Routing failed: {error}', { error: t('route leg too long') }),
      );
      assert.doesNotMatch(shown, /route leg too long/);
      const limited = presentRoutingFailure(
        Object.assign(new Error('rate limited — try again in a moment'), {
          status: 429,
          refusal: 'rate limited',
        }),
      );
      assert.equal(limited, 'rate limited — try again in a moment');
      assert.doesNotMatch(
        translateFeedError(limited),
        /rate limited|try again in a moment/,
      );
      const http = presentRoutingFailure(
        Object.assign(new Error('Routing unavailable (HTTP 503)'), {
          status: 503,
        }),
      );
      assert.equal(http, 'Routing unavailable (HTTP 503)');
      assert.notEqual(translateFeedError(http), http);
      assert.match(translateFeedError(http), /503/);
      // A text the proxy never sends is shown as given.
      assert.equal(
        translateFeedError('Routing failed: something else'),
        t('Routing failed: {error}', { error: 'something else' }),
      );
      // Every refusal the proxy sends (server/providers/places/routes.js),
      // and "rate limited" after "Routing failed:", which the feed pattern
      // "<source> rate limited" would otherwise take.
      for (const [english, shown] of [
        [
          'routing busy — too many routes at once — try again in a moment',
          t('{error} — try again in a moment', {
            error: t('routing busy — too many routes at once'),
          }),
        ],
        [
          'Routing failed: route proxy error',
          t('Routing failed: {error}', { error: t('route proxy error') }),
        ],
        [
          'Routing failed: rate limited',
          t('Routing failed: {error}', { error: t('rate limited') }),
        ],
      ]) {
        assert.equal(translateFeedError(english), shown);
        assert.doesNotMatch(shown, /routing busy|route proxy|rate limited/);
      }
    } finally {
      setLocale('en');
    }
  });

  test(`${locale}: a weather manifest timeout is shown translated`, async () => {
    const source = createWeatherSource({
      fetchImpl: (_url, { signal }) =>
        new Promise((_resolve, reject) =>
          signal.addEventListener('abort', () => reject(signal.reason)),
        ),
      timeoutMs: 10,
    });
    let message = null;
    try {
      await source.getSnapshot({ product: 'radar' });
    } catch (error) {
      message = error.message;
    }
    assert.equal(message, 'Weather request timed out', 'stored in English');
    setLocale(locale);
    try {
      // The layer shows `t(problem)` (weather/index.js presentWeatherProblem).
      assert.notEqual(t(message), message, 'should be translated');
      assert.notEqual(translateKnown(message), message);
    } finally {
      setLocale('en');
    }
  });
}
