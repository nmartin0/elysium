import { createSurfaceServices } from './surfaceServices.js';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createApplicationCatalog } from './constructCatalog.js';
import { createStandaloneLayerSources } from '../standalone/layerSources.js';
import { catalogControlServices } from './catalog.js';
import { LayerLifecycle } from '../data/lifecycle.js';

function fixtureSources() {
  return createStandaloneLayerSources();
}

test('catalogs construct distinct layers and classification from their supplied source', async (t) => {
  const a = new AbortController();
  const b = new AbortController();
  t.after(() => {
    a.abort();
    b.abort();
  });
  const first = createApplicationCatalog({
    sources: fixtureSources(),
    signal: a.signal,
    surface: fixtureSurface(a.signal),
  });
  const second = createApplicationCatalog({
    sources: fixtureSources(),
    signal: b.signal,
    surface: fixtureSurface(b.signal),
  });
  assert.equal(first.layers.length, 22);
  for (const id of ['military', 'cctv', 'local-adsb'])
    assert.equal(
      first.layers.some((layer) => layer.id === id),
      false,
      id,
    );
  assert.notEqual(first.weatherClock, second.weatherClock);
  await first.weatherClock.setTarget('2026-09-21T12:00:00.000Z');
  assert.match(
    first.get('wind').getRowControls().info,
    /Forecast · does not follow history/,
  );
  assert.equal(second.get('wind').getRowControls().summary.status, null);
  for (const id of ['weather-radar', 'weather-satellite', 'weather-lightning'])
    assert.equal(
      first.get(id).getDiagnostics().clock.target,
      '2026-09-21T12:00:00.000Z',
    );
  assert.ok(first.get('fire-perimeters'));
  assert.ok(first.get('gnss-integrity'));
  assert.ok(first.get('s2-ghostmaps'));
  assert.ok(first.get('transit'));
  const order = first.layers.map(({ id }) => id);
  assert.deepEqual(
    order.slice(order.indexOf('transit'), order.indexOf('directions') + 1),
    ['transit', 'bikeshare', 'directions'],
  );
  const lifecycle = new LayerLifecycle({});
  for (const layer of first.layers) lifecycle.register(layer);
  const rows = lifecycle.getAll();
  assert.equal(
    rows.find((row) => row.id === 'flights')?.showInTogglePanel,
    true,
    'ordinary data layer entries remain visible',
  );
  assert.deepEqual(
    first.layers.map(({ id }) => id),
    second.layers.map(({ id }) => id),
  );
  for (const layer of first.layers)
    assert.notEqual(layer, second.get(layer.id));
  assert.equal(
    catalogControlServices(first).satellitesLayer,
    first.get('satellites'),
  );
  a.abort();
  assert.equal(
    await first.weatherClock.setTarget('2026-09-21T13:00:00.000Z'),
    false,
  );
});

test('invalid or already cancelled construction fails before classification can acquire', () => {
  const lifetime = new AbortController();
  assert.throws(
    () =>
      createApplicationCatalog({
        sources: { flights: {} },
        signal: lifetime.signal,
        surface: fixtureSurface(lifetime.signal),
      }),
    /catalog source/,
  );
  lifetime.abort();
  assert.throws(
    () =>
      createApplicationCatalog({
        sources: createStandaloneLayerSources(),
        signal: lifetime.signal,
      }),
    { name: 'AbortError' },
  );
});

function fixtureSurface(signal) {
  return createSurfaceServices({
    terrainSource: { getHeights: async () => [] },
    signal,
    eventTarget: null,
  });
}

test('a GNSS integrity source can set the layer evidence window', (t) => {
  const lifetime = new AbortController();
  t.after(() => lifetime.abort());
  const gnssLayer = (descriptor) => {
    const sources = fixtureSources([], []);
    sources['gnss-integrity'] = {
      getSnapshot: async () => ({}),
      ...descriptor,
    };
    return createApplicationCatalog({
      sources,
      signal: lifetime.signal,
      surface: fixtureSurface(lifetime.signal),
    }).get('gnss-integrity');
  };
  const shows = (layer, minutes) => {
    assert.equal(layer.provenance.window.minutes, minutes);
    const { info, legend } = layer.getRowControls();
    assert.match(info, new RegExp(`visited views over ${minutes} min`));
    assert.match(legend[0].blurb, new RegExp(`over ${minutes} minutes`));
  };
  shows(gnssLayer({ windowMs: 65 * 60_000 }), 65);
  shows(gnssLayer({}), 30);
  for (const windowMs of [
    undefined,
    null,
    NaN,
    Infinity,
    0,
    -60_000,
    '3600000',
  ])
    assert.equal(
      gnssLayer({ windowMs }).provenance.window.minutes,
      30,
      `${String(windowMs)} falls back to the default`,
    );
});
