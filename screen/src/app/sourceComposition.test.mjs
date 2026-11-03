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
import { STUBBED_LAYER_IDS } from '../data/layerState.js';

// A stubbed layer is not constructed, so it has no availability row to check.
const constructedIds = (ids) =>
  ids.filter((id) => !STUBBED_LAYER_IDS.includes(id));

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
    for (const id of constructedIds(CATALOG_SOURCE_CONTRACTS[name].layers)) {
      assert.equal(actual.getSourceAvailability(id).available, false, id);
    }
  }
});

test('all acquisition sources may be absent, and enable fails before initializing or fetching', async (t) => {
  const actual = catalog({}, t);
  assert.equal(actual.layers.length, 21);
  const manager = new LayerLifecycle(
    {},
    { getSourceAvailability: actual.getSourceAvailability },
  );
  for (const layer of actual.layers) manager.register(layer);
  for (const { layers: ids } of Object.values(CATALOG_SOURCE_CONTRACTS)) {
    for (const id of constructedIds(ids)) {
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

test('GhostMaps is stubbed: its source contract stays, the layer is not constructed, nothing is fetched', async (t) => {
  let fetches = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    fetches++;
    throw new Error('Unexpected standalone acquisition');
  });
  assert.ok(STUBBED_LAYER_IDS.includes('s2-ghostmaps'));
  assert.ok(CATALOG_SOURCE_CONTRACTS['s2-ghostmaps'], 'contract stays');
  assert.equal(
    createStandaloneLayerSources({ 's2-ghostmaps': null })['s2-ghostmaps'],
    null,
  );
  const stubbed = catalog(createStandaloneLayerSources(), t);
  assert.equal(stubbed.get('s2-ghostmaps'), undefined);
  assert.equal(stubbed.getSourceAvailability('s2-ghostmaps'), undefined);
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
