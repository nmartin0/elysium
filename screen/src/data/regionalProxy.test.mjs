import { test } from 'node:test';
import assert from 'node:assert/strict';
import createViteConfig, {
  adsbLolFallbackAnchor,
  coalesceProxyRequest,
  launchLibraryRequestHeaders,
  keylessGooglePlacesResponse,
  LL2_CACHE_TTL_MS,
  readResponseJsonCapped,
} from '../../vite.config.js';

test('missing Google place context is a quiet keyless capability, not a 503', () => {
  assert.deepEqual(keylessGooglePlacesResponse(undefined), {
    statusCode: 200,
    payload: { configured: false, error: null, places: [] },
  });
  assert.deepEqual(keylessGooglePlacesResponse('   '), {
    statusCode: 200,
    payload: { configured: false, error: null, places: [] },
  });
  assert.equal(keylessGooglePlacesResponse('configured-key'), null);
});

test('adjacent proxy validators also require every coordinate explicitly', () => {
  assert.equal(adsbLolFallbackAnchor({ url: '?lat=12.5' }), null);
  assert.equal(adsbLolFallbackAnchor({ url: '?lon=12.5' }), null);
});

test('new data proxies install the same routes in dev and preview servers', () => {
  const config = createViteConfig({ mode: 'test' });
  const byName = new Map(config.plugins.map((plugin) => [plugin.name, plugin]));
  for (const name of ['rocket-launches-proxy']) {
    assert.equal(typeof byName.get(name)?.configureServer, 'function', `${name} dev hook`);
    assert.equal(typeof byName.get(name)?.configurePreviewServer, 'function', `${name} preview hook`);
  }
});

test('Launch Library uses a 15-minute cache and optional server-side token header', () => {
  assert.equal(LL2_CACHE_TTL_MS, 15 * 60_000);
  const headers = {
    Accept: 'application/json',
    'User-Agent': 'gods-eye-view-launch-library-proxy/1.0 (+https://github.com/bilawalsidhu/gods-eye-view)',
  };
  assert.deepEqual(launchLibraryRequestHeaders(''), headers);
  assert.deepEqual(launchLibraryRequestHeaders(' secret '), {
    ...headers,
    Authorization: 'Token secret',
  });
});

test('proxy request coalescing shares one per-key refresh and clears it after settlement', async () => {
  const inFlight = new Map();
  let refreshCount = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const first = coalesceProxyRequest(inFlight, 'cell', async () => {
    refreshCount += 1;
    await gate;
    return 'fresh';
  });
  const second = coalesceProxyRequest(inFlight, 'cell', () => {
    refreshCount += 1;
    return 'duplicate';
  });
  assert.equal(first.shared, false);
  assert.equal(second.shared, true);
  assert.equal(first.promise, second.promise);
  release();
  assert.equal(await second.promise, 'fresh');
  assert.equal(refreshCount, 1);
  assert.equal(inFlight.size, 0);
});

test('bounded JSON reader rejects oversized upstream bodies', async () => {
  assert.deepEqual(await readResponseJsonCapped(new Response('{"ok":true}'), 32), { ok: true });
  await assert.rejects(
    readResponseJsonCapped(new Response(JSON.stringify({ value: 'x'.repeat(64) })), 32),
    (error) => error?.code === 'RESPONSE_TOO_LARGE',
  );
});

