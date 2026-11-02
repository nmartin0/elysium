import assert from 'node:assert/strict';
import test from 'node:test';
import {
  resolveCatalogSources,
  CATALOG_SOURCE_CONTRACTS,
} from './sourceComposition.js';
import { createApplicationCatalog } from './constructCatalog.js';
import { createSurfaceServices } from './surfaceServices.js';
import { createStandaloneLayerSources } from '../standalone/layerSources.js';
import { LayerLifecycle } from '../data/lifecycle.js';

function catalog(sources, t) {
  const lifetime = new AbortController();
  t.after(() => lifetime.abort());
  return createApplicationCatalog({
    sources,
    signal: lifetime.signal,
    surface: createSurfaceServices({
      terrainSource: { getHeights: async () => [] },
      signal: lifetime.signal,
      eventTarget: null,
    }),
  });
}

test('every acquisition source can be omitted without losing catalog membership', (t) => {
  const baseline = catalog(createStandaloneLayerSources(), t);
  for (const name of Object.keys(CATALOG_SOURCE_CONTRACTS)) {
    const sources = createStandaloneLayerSources({ [name]: null });
    const actual = catalog(sources, t);
    assert.deepEqual(actual.metadata, baseline.metadata, name);
    for (const id of CATALOG_SOURCE_CONTRACTS[name].layers) {
      assert.equal(actual.getSourceAvailability(id).available, false, id);
    }
  }
});

test('all acquisition sources may be absent, and enable fails before initializing or fetching', async (t) => {
  const actual = catalog({}, t);
  assert.equal(actual.layers.length, 22);
  const manager = new LayerLifecycle(
    {},
    { getSourceAvailability: actual.getSourceAvailability },
  );
  for (const layer of actual.layers) manager.register(layer);
  for (const { layers: ids } of Object.values(CATALOG_SOURCE_CONTRACTS)) {
    for (const id of ids) {
      assert.equal(await manager.setEnabled(id, true), false, id);
      assert.equal(manager.layers.get(id).initialized, false, id);
      const row = manager.getAll().find((entry) => entry.id === id);
      assert.equal(row.enabled, false);
      assert.equal(row.stats.status, 'unavailable');
      assert.match(row.stats.error, /data source not configured/);
    }
  }
});

test('configured sources retain identity; invalid implementations never become unavailable silently', () => {
  const source = { getSnapshot: async () => [] };
  assert.equal(
    resolveCatalogSources({ earthquakes: source }).sources.earthquakes,
    source,
  );
  for (const name of Object.keys(CATALOG_SOURCE_CONTRACTS)) {
    assert.throws(
      () => resolveCatalogSources({ [name]: {} }),
      /Invalid catalog source/,
    );
  }
  const missing = resolveCatalogSources({}).sources.earthquakes;
  assert.throws(() => missing.getSnapshot(), { code: 'unavailable' });
});

test('standalone defaults allow exact replacements and explicit removal, and reject typos', () => {
  const source = { getSnapshot: async () => [] };
  const sources = createStandaloneLayerSources({
    flights: source,
    launches: null,
  });
  assert.equal(sources.flights, source);
  assert.equal(sources.launches, null);
  assert.throws(
    () => createStandaloneLayerSources({ fligts: source }),
    /Unknown source/,
  );
});

test('GhostMaps obeys source omission, replacement and explicit removal', async (t) => {
  let fetches = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    fetches++;
    throw new Error('Unexpected standalone acquisition');
  });
  const missing = catalog({}, t);
  assert.equal(missing.getSourceAvailability('s2-ghostmaps')?.available, false);
  const manager = new LayerLifecycle(
    {},
    { getSourceAvailability: missing.getSourceAvailability },
  );
  manager.register(missing.get('s2-ghostmaps'));
  assert.equal(await manager.setEnabled('s2-ghostmaps', true), false);
  assert.equal(manager.layers.get('s2-ghostmaps').initialized, false);
  assert.equal(
    createStandaloneLayerSources({ 's2-ghostmaps': null })['s2-ghostmaps'],
    null,
  );

  let reads = 0;
  let subscriptions = 0;
  let unsubscribed = 0;
  const source = {
    getCatalog: async () => {
      reads++;
      return { commit: 'a'.repeat(40), products: [] };
    },
    getFile: async () => {
      throw new Error('Empty catalog must not read files');
    },
    subscribe: () => {
      subscriptions++;
      return () => {
        unsubscribed++;
      };
    },
  };
  const supplied = createStandaloneLayerSources({ 's2-ghostmaps': source });
  assert.equal(supplied['s2-ghostmaps'], source);
  const configured = catalog(supplied, t);
  assert.equal(
    configured.getSourceAvailability('s2-ghostmaps').available,
    true,
  );
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'document');
  globalThis.document = { addEventListener() {}, removeEventListener() {} };
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, 'document', previous);
    else delete globalThis.document;
  });
  const layer = configured.get('s2-ghostmaps');
  t.after(() => layer.destroy());
  layer.init({ scene: { requestRender() {} } });
  layer.enable();
  await layer.update();
  layer.disable();
  assert.equal(reads, 1);
  assert.equal(subscriptions, 1);
  assert.equal(unsubscribed, 1);
  assert.equal(layer.getStats().commit, 'a'.repeat(40));
  assert.equal(fetches, 0);
});

test('availability lookup accepts frozen layers and uses their display names', () => {
  const composition = resolveCatalogSources({});
  const layers = Object.values(CATALOG_SOURCE_CONTRACTS)
    .flatMap(({ layers }) => layers)
    .map((id) =>
      Object.freeze({
        id,
        name: id === 'fire-perimeters' ? 'Fire perimeters' : id,
      }),
    );
  const lookup = composition.createAvailabilityLookup(layers);
  assert.equal(
    lookup('fire-perimeters').reason,
    'Fire perimeters: data source not configured',
  );
  assert.equal(Object.hasOwn(layers[0], 'getSourceAvailability'), false);
  const manager = new LayerLifecycle({}, { getSourceAvailability: lookup });
  manager.register(layers.find(({ id }) => id === 'fire-perimeters'));
  assert.equal(
    manager.getAll()[0].stats.error,
    'Fire perimeters: data source not configured',
  );
});
