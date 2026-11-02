import test from 'node:test';
import assert from 'node:assert/strict';
import { promises as fsp } from 'node:fs';
import { terrainHeightsProxy } from 'gods-eye-view/server/providers/terrain';
import { firmsProxy } from 'gods-eye-view/server/providers/firms';
import { gbfsProxy } from 'gods-eye-view/server/providers/gbfs';
import { localProviderPlugins } from '../../server/providers/local.js';
function install(plugin, hook = 'configureServer') {
  const routes = new Map();
  assert.equal(typeof plugin[hook], 'function', `${hook} is available`);
  plugin[hook]({
    middlewares: {
      use(route, handler) {
        routes.set(route, handler);
      },
    },
  });
  assert.equal(routes.size, 1);
  return async (url = '/', method = 'GET', headers = {}) => {
    const res = {
      headersSent: false,
      headers: {},
      set statusCode(status) {
        this.status = status;
      },
      setHeader(name, value) {
        this.headers[name.toLowerCase()] = value;
      },
      writeHead(status, headers) {
        Object.assign(this, { status, headers, headersSent: true });
      },
      end(body) {
        this.body = body;
      },
    };
    await [...routes.values()][0]({ url, method, headers, socket: {} }, res);
    return res;
  };
}
function isolate(t, env = {}) {
  for (const [name, value] of Object.entries(env)) {
    const previous = process.env[name];
    t.after(() => {
      if (previous === undefined) delete process.env[name];
      else process.env[name] = previous;
    });
    process.env[name] = value;
  }
  t.mock.method(fsp, 'readFile', async () => {
    throw Error('no disk cache');
  });
  t.mock.method(fsp, 'stat', async () => {
    throw Error('no disk cache');
  });
  t.mock.method(fsp, 'mkdir', async () => {});
  t.mock.method(fsp, 'writeFile', async () => {});
  t.mock.method(globalThis, 'setInterval', () => ({ unref() {} }));
  t.mock.method(console, 'warn', () => {});
}
const json = (res) => JSON.parse(res.body);

/** A response that streams 1 MiB chunks of `text` well past every cap, then ends. */
test('terrain middleware bounds missing points and reconstructs repeated/reordered requests from cache', async (t) => {
  isolate(t);
  let calls = 0;
  const sizes = [];
  t.mock.method(globalThis, 'fetch', async (raw) => {
    calls++;
    const url = new URL(raw);
    assert.equal(url.origin, 'https://terrain.reearth.land');
    const points = url.searchParams
      .get('points')
      .split(';')
      .map((p) => p.split(',').map(Number));
    sizes.push(points.length);
    return Response.json({
      results: points.map(([lon]) => ({ ellipsoid: lon + 100 })),
    });
  });
  const request = install(terrainHeightsProxy());
  const points = Array.from({ length: 64 }, (_, i) => `${i / 100},1`);
  const res = await request('/?points=' + points.join(';'));
  assert.equal(res.status, 200);
  assert.deepEqual(sizes, [64]);
  const reordered = await request('/?points=0.63,1;0,1;0.63,1');
  assert.deepEqual(json(reordered), {
    results: [{ ellipsoid: 100.63 }, { ellipsoid: 100 }, { ellipsoid: 100.63 }],
  });
  // One bounded batch; the reordered request is fully cached.
  assert.equal(calls, 1);
  assert.equal((await request('/?points=invalid')).status, 400);
  assert.equal(
    (await request('/?points=' + Array(2001).fill('0,1').join(';'))).status,
    413,
  );
  // Rejected requests add no upstream calls.
  assert.equal(calls, 1);
});

test('terrain middleware migrates valid legacy disk points without fabricating omitted heights', async (t) => {
  isolate(t);
  t.mock.method(fsp, 'readFile', async () =>
    JSON.stringify({
      '1,2;3,4': { at: Date.now(), results: [{ ellipsoid: 77 }] },
    }),
  );
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async (raw) => {
    calls++;
    assert.equal(new URL(raw).searchParams.get('points'), '3.00000,4.00000');
    return Response.json({ results: [{ ellipsoid: 88 }] });
  });
  const res = await install(terrainHeightsProxy())('/?points=3,4;1,2');
  assert.deepEqual(json(res), {
    results: [{ ellipsoid: 88 }, { ellipsoid: 77 }],
  });
  assert.equal(calls, 1);
});

test('FIRMS retains a large successful source during partial failure and filters stale data at serve time', async (t) => {
  isolate(t, { FIRMS_MAP_KEY: '' });
  let now = Date.UTC(2026, 8, 12, 12);
  t.mock.method(Date, 'now', () => now);
  let calls = 0;
  const header = 'latitude,longitude,acq_date,acq_time,confidence,frp\n';
  const csv = header + '30,-97,2026-09-12,1200,h,10\n'.repeat(130001);
  t.mock.method(globalThis, 'fetch', async (raw) => {
    calls++;
    const url = new URL(raw);
    assert.equal(url.hostname, 'firms.modaps.eosdis.nasa.gov');
    if (url.pathname.includes('mapkey_status'))
      return Response.json({
        current_transactions: 3,
        transaction_limit: 5000,
      });
    return url.pathname.includes('VIIRS_NOAA20')
      ? new Response(csv)
      : new Response('offline', { status: 503 });
  });
  const request = install(firmsProxy());
  assert.equal((await request()).status, 503);
  assert.equal(json(await request('/status')).hasKey, false);
  assert.equal(calls, 0);
  process.env.FIRMS_MAP_KEY = 'fixture-key';
  const first = json(await request());
  assert.equal(first.count, 130001);
  assert.equal(first.sources.filter((s) => s.ok).length, 1);
  assert.equal(calls, 4);
  assert.equal(json(await request()).count, 130001);
  assert.equal(calls, 4);
  assert.deepEqual(json(await request('/status')).transactions, {
    used: 3,
    limit: 5000,
  });
  now += 25 * 3600000;
  t.mock.method(
    globalThis,
    'fetch',
    async () => new Response('offline', { status: 503 }),
  );
  const stale = json(await request());
  assert.equal(stale.stale, true);
  assert.equal(stale.count, 0);
});

test('GBFS keeps host/path/method guards, response caps and distinct information/status cache headers', async (t) => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async (raw) => {
    calls++;
    assert.equal(new URL(raw).hostname, 'gbfs.lyft.com');
    return Response.json({ data: { stations: [] } });
  });
  const request = install(gbfsProxy());
  const target = (p) => '/' + encodeURIComponent('https://gbfs.lyft.com/' + p);
  assert.equal(
    (await request(target('station_status.json'), 'POST')).status,
    405,
  );
  assert.equal(
    (
      await request(
        '/' + encodeURIComponent('https://example.com/station_status.json'),
      )
    ).status,
    403,
  );
  assert.equal((await request(target('gbfs.json'))).status, 400);
  assert.equal((await request('/%zz')).status, 400);
  assert.equal(calls, 0);
  assert.equal(
    (await request(target('station_information.json'))).headers[
      'Cache-Control'
    ],
    'public, max-age=300',
  );
  assert.equal(
    (await request(target('station_status.json'))).headers['Cache-Control'],
    'no-store',
  );
  t.mock.method(
    globalThis,
    'fetch',
    async () =>
      new Response('x', {
        headers: { 'content-length': String(6 * 1024 * 1024) },
      }),
  );
  assert.equal((await request(target('station_status.json'))).status, 502);
});

test('terrain middleware retains successful chunks around a failure and retries only missing points', async (t) => {
  isolate(t);
  const requests = [];
  let fail = true;
  t.mock.method(globalThis, 'fetch', async (raw) => {
    const points = new URL(raw).searchParams
      .get('points')
      .split(';')
      .map((p) => p.split(',').map(Number));
    requests.push(points);
    if (fail && points[0][0] === 0.64) return new Response('', { status: 400 });
    return Response.json({
      results: points.map(([lon]) => ({ ellipsoid: lon + 100 })),
    });
  });
  const request = install(terrainHeightsProxy());
  const points = Array.from({ length: 130 }, (_, i) => `${i / 100},1`);
  const urls = [0, 64, 128].map(
    (start) => '/?points=' + points.slice(start, start + 64).join(';'),
  );
  assert.deepEqual(
    await Promise.all(urls.map(async (url) => (await request(url)).status)),
    [200, 502, 200],
  );
  assert.deepEqual(
    requests.map((p) => p.length).sort((a, b) => a - b),
    [2, 64, 64],
  );
  fail = false;
  const recovered = await Promise.all(urls.map((url) => request(url)));
  assert.ok(recovered.every((response) => response.status === 200));
  assert.deepEqual(
    requests[3],
    Array.from({ length: 64 }, (_, i) => [(i + 64) / 100, 1]),
  );
  assert.deepEqual(
    recovered.flatMap((response) => json(response).results),
    Array.from({ length: 130 }, (_, i) => ({ ellipsoid: i / 100 + 100 })),
  );
  assert.equal(requests.length, 4);
});

test('after a 429 the terrain proxy leaves the upstream alone and logs once', async (t) => {
  isolate(t);
  const warnings = [];
  t.mock.method(console, 'warn', (...args) => warnings.push(args.join(' ')));
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    calls += 1;
    return new Response('', { status: 429 });
  });
  t.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: 1_000_000 });
  const request = install(terrainHeightsProxy());
  // The retries' backoff runs on mocked time.
  let settled = false;
  const first = request('/?points=1,2').then(() => {
    settled = true;
  });
  for (let step = 0; step < 60 && !settled; step += 1) {
    await new Promise((resolve) => setImmediate(resolve));
    t.mock.timers.tick(1_000);
  }
  assert.ok(settled, 'the first request settles within its retry budget');
  await first;
  const afterFirst = calls;
  assert.ok(afterFirst >= 1);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /HTTP 429; pausing upstream for 60 s/);
  // New points during the pause: no upstream call, no new log line.
  const paused = await request('/?points=3,4');
  assert.equal(calls, afterFirst);
  assert.equal(paused.status, 502);
  assert.equal(warnings.length, 1);
});

test('a far-off Retry-After pauses the terrain upstream for at most 10 minutes', async (t) => {
  isolate(t);
  t.mock.method(console, 'warn', () => {});
  t.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: 1_000_000 });
  let limited = true;
  t.mock.method(globalThis, 'fetch', async () =>
    limited
      ? new Response('', { status: 429, headers: { 'retry-after': '86400' } })
      : Response.json({ results: [{ ellipsoid: 100 }] }),
  );
  const request = install(terrainHeightsProxy());
  // The first request spends its retry budget on 429s, then the pause begins.
  let settled = false;
  const first = request('/?points=1,2').then((res) => {
    settled = true;
    return res;
  });
  // Bounded: the retry budget is 10 s, so 60 simulated seconds is plenty.
  for (let step = 0; step < 60 && !settled; step += 1) {
    await new Promise((resolve) => setImmediate(resolve));
    t.mock.timers.tick(1_000);
  }
  assert.ok(settled, 'the first request settles within its retry budget');
  assert.equal((await first).status, 502);
  limited = false;
  const pausedAt = Date.now();
  t.mock.timers.setTime(pausedAt + 9 * 60_000);
  assert.equal((await request('/?points=3,4')).status, 502, 'still paused');
  t.mock.timers.setTime(pausedAt + 10 * 60_000 + 1);
  assert.equal((await request('/?points=3,4')).status, 200, 'pause over');
});

/** Drive mocked timers until `promise` settles; the retry budget is 10 s. */
async function settleOnMockedTime(t, promise) {
  let settled = false;
  const tracked = promise.finally(() => {
    settled = true;
  });
  for (let step = 0; step < 60 && !settled; step += 1) {
    await new Promise((resolve) => setImmediate(resolve));
    t.mock.timers.tick(1_000);
  }
  assert.ok(settled, 'the request settles within its retry budget');
  return tracked;
}

test('during a terrain 429 pause fully cached points, even stale ones, are still served', async (t) => {
  isolate(t);
  t.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: 1_000_000 });
  let calls = 0;
  let limited = false;
  t.mock.method(globalThis, 'fetch', async () => {
    calls += 1;
    return limited
      ? new Response('', { status: 429, headers: { 'retry-after': '300' } })
      : Response.json({ results: [{ ellipsoid: 100 }] });
  });
  const request = install(terrainHeightsProxy());
  assert.equal((await request('/?points=5,6')).status, 200);
  // Past the 30-day TTL, so 5,6 is stale and would normally be refreshed.
  t.mock.timers.setTime(Date.now() + 31 * 24 * 3600_000);
  limited = true;
  const first = await settleOnMockedTime(t, request('/?points=1,2'));
  assert.equal(first.status, 502);
  assert.equal(calls, 2, 'a Retry-After past the budget is not retried');
  const stale = await request('/?points=5,6');
  assert.equal(stale.status, 200);
  assert.deepEqual(json(stale).results, [{ ellipsoid: 100 }]);
  assert.equal((await request('/?points=5,6;7,8')).status, 502);
  assert.equal(calls, 2, 'no upstream call during the pause');
});

test('a terrain upstream failure other than 429 does not pause later requests', async (t) => {
  isolate(t);
  t.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: 1_000_000 });
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    calls += 1;
    return new Response('', { status: 503 });
  });
  const request = install(terrainHeightsProxy());
  const first = await settleOnMockedTime(t, request('/?points=1,2'));
  assert.equal(first.status, 502);
  const afterFirst = calls;
  const second = await settleOnMockedTime(t, request('/?points=3,4'));
  assert.equal(second.status, 502);
  assert.ok(calls > afterFirst, 'new points still go upstream after a 503');
});

test('a shorter concurrent Retry-After never cuts a terrain 429 pause short', async (t) => {
  isolate(t);
  t.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: 1_000_000 });
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async (raw) => {
    calls += 1;
    const points = new URL(raw).searchParams.get('points');
    if (points.startsWith('0.'))
      return Response.json({ results: [{ ellipsoid: 1 }] });
    const retryAfter = points.startsWith('1.') ? '300' : '30';
    return new Response('', {
      status: 429,
      headers: { 'retry-after': retryAfter },
    });
  });
  const request = install(terrainHeightsProxy());
  // Load the disk cache first so both requests below reach the upstream in
  // order: the 300 s answer lands first, the 30 s answer after it.
  assert.equal((await request('/?points=0,0')).status, 200);
  const [long, short] = await settleOnMockedTime(
    t,
    Promise.all([request('/?points=1,2'), request('/?points=3,4')]),
  );
  assert.equal(long.status, 502);
  assert.equal(short.status, 502);
  const afterBoth = calls;
  t.mock.timers.setTime(Date.now() + 120_000);
  assert.equal((await request('/?points=5,6')).status, 502);
  assert.equal(calls, afterBoth, 'still paused by the 300 s Retry-After');
});

test('standalone composition mounts every extracted provider exactly once without acquisition', (t) => {
  t.mock.method(globalThis, 'fetch', () => {
    throw Error('construction must not fetch');
  });
  const plugins = localProviderPlugins();
  for (const factory of [terrainHeightsProxy, firmsProxy, gbfsProxy])
    assert.equal(plugins.filter((p) => p.name === factory().name).length, 1);
});
