import assert from 'node:assert/strict';
import test from 'node:test';
import { Readable } from 'node:stream';
import {
  makeCostRateLimiter,
  resolvePerMinuteCap,
} from '../server/providers/common/rate-limit.js';
import {
  googlePlacesContextProxy,
  GOOGLE_DEFAULT_PER_MIN,
} from '../server/providers/places/google.js';

// Both limiters are cached at module scope on first use, so the env value that
// matters is the one in place when a route is first exercised — restoring the
// variable afterwards does not rebuild the limiter. Each route is therefore
// driven by exactly one test here; a second test wanting a different cap would
// need its own process, not just a different env value.

/** Set an env var for one test and put the old value back afterwards. */
function env(t, name, value) {
  const old = process.env[name];
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
  t.after(() => {
    if (old === undefined) delete process.env[name];
    else process.env[name] = old;
  });
}

function install(plugin) {
  const routes = new Map();
  plugin.configureServer({
    middlewares: { use: (route, handler) => routes.set(route, handler) },
    restart: async () => {},
  });
  return routes;
}

function request(
  handler,
  { url = '/', method = 'POST', remoteAddress = '127.0.0.1' } = {},
) {
  return new Promise((resolve, reject) => {
    const req = Readable.from([]);
    Object.assign(req, {
      method,
      url,
      headers: { host: 'localhost:4173', 'content-type': 'application/json' },
      socket: { remoteAddress },
    });
    const headers = {};
    const res = {
      statusCode: 200,
      setHeader(name, value) {
        headers[name.toLowerCase()] = value;
      },
      end(body = '') {
        resolve({ status: this.statusCode, headers, body: String(body) });
      },
    };
    Promise.resolve(handler(req, res)).catch(reject);
  });
}

test('an unset throttle resolves to the documented default, not to unlimited', () => {
  // The defect #16 reports: the cap was opt-in, so an unconfigured server let
  // anyone who could reach it mint tokens on the operator's key without bound.
  assert.equal(resolvePerMinuteCap(undefined, 30), 30);
  assert.equal(resolvePerMinuteCap('', 30), 30);
  assert.equal(resolvePerMinuteCap('   ', 30), 30);
  assert.ok(
    typeof makeCostRateLimiter(undefined, 30) === 'function',
    'an unconfigured cost endpoint must still be throttled',
  );
});

test('an explicit 0 is the documented way to run unthrottled', () => {
  assert.equal(resolvePerMinuteCap('0', 30), 0);
  assert.equal(
    makeCostRateLimiter('0', 30),
    null,
    'operators who mean "no throttle" must still be able to say so',
  );
});

test('a configured value wins, and a fractional one floors', () => {
  assert.equal(resolvePerMinuteCap('45', 30), 45);
  assert.equal(resolvePerMinuteCap(45, 30), 45);
  assert.equal(resolvePerMinuteCap('30.7', 30), 30);
});

test('a positive fraction keeps the guard rather than flooring to unlimited', () => {
  for (const fraction of ['0.5', '0.99', 0.01, '1e-9']) {
    assert.equal(resolvePerMinuteCap(fraction, 30), 1, String(fraction));
    assert.equal(
      typeof makeCostRateLimiter(fraction, 30),
      'function',
      `${fraction} must still throttle`,
    );
  }
  // Only an explicit zero turns the limiter off.
  assert.equal(makeCostRateLimiter('0', 30), null);
  assert.equal(makeCostRateLimiter('0.0', 30), null);
});

test('an unreadable value keeps the guard instead of removing it', () => {
  // `3O` (letter O) and `60/min` are the shapes a hand-edited .env produces.
  // Reading either as "unlimited" would disarm the spend guard on a typo —
  // the opposite of what the operator was reaching for when they typed it.
  for (const typo of ['3O', '60/min', 'thirty', '-5', 'NaN']) {
    assert.equal(
      resolvePerMinuteCap(typo, 30),
      30,
      `${typo} must fall back to the default, not to unlimited`,
    );
  }
});

test('the Google places route throttles by default and keeps its places[] contract', async (t) => {
  env(t, 'GEV_RATELIMIT_GOOGLE_PER_MIN', undefined);
  let upstreamCalls = 0;
  const handler = install(
    googlePlacesContextProxy({
      resolveApiKey: () => 'fixture-google-server-key',
      fetchImpl: async () => {
        upstreamCalls += 1;
        return Response.json({ places: [] });
      },
    }),
  ).get('/api/google/nearby-places');

  const url = '/?lat=37.77493&lon=-122.41942';
  const statuses = [];
  for (let i = 0; i < GOOGLE_DEFAULT_PER_MIN; i += 1) {
    statuses.push((await request(handler, { url, method: 'GET' })).status);
  }
  assert.ok(
    statuses.every((s) => s === 200),
    'the default must not throttle ordinary use',
  );

  const overLimit = await request(handler, { url, method: 'GET' });
  assert.equal(overLimit.status, 429);
  assert.equal(overLimit.headers['retry-after'], '5');
  // Every error response on this route carries places[]; the client reads it
  // unconditionally, so a throttled reply must not be the one shape that omits it.
  assert.deepEqual(JSON.parse(overLimit.body).places, []);
  assert.equal(
    upstreamCalls,
    GOOGLE_DEFAULT_PER_MIN,
    'a throttled request must be refused before it reaches Google, or it still costs money',
  );
});
