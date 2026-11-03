import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import {
  LAYER_STATE_REGISTRY,
  LAYER_STATE_TOKEN_RESERVATIONS,
  REGISTERED_LAYER_IDS,
  STUBBED_LAYER_IDS,
  createDefaultLayerState,
  decodeLayerStateParams,
  parseStoredLayerState,
} from '../data/layerState.js';
import { decodeBase64Url, encodeBase64Url, crc8 } from '../share/wire.js';
import { decodeShareView, encodeShareView } from '../share/viewCodec.js';
import { registerDataCredits } from '../data/dataCredits.js';
import { localProviderPlugins } from '../../server/providers/local.js';
import { createApplicationCatalog } from './constructCatalog.js';
import { createSurfaceServices } from './surfaceServices.js';
import { createStandaloneLayerSources } from '../standalone/layerSources.js';
import { LayerLifecycle } from '../data/lifecycle.js';

// Owner decision, 2 November 2026: the S2 GhostMaps layer is STUBBED. These
// tests prove each way it could appear or reach the network stays shut.
const ID = 's2-ghostmaps';
const TOKEN = '5';

test('the switch names the layer and its token stays reserved forever', () => {
  assert.deepEqual([...STUBBED_LAYER_IDS], [ID]);
  assert.equal(LAYER_STATE_TOKEN_RESERVATIONS[ID], TOKEN);
  assert.equal(REGISTERED_LAYER_IDS.includes(ID), false);
  assert.equal(
    LAYER_STATE_REGISTRY.some((entry) => entry.token === TOKEN),
    false,
    'no live layer may take the stubbed layer token',
  );
});

test('the layer is not in the catalog, the panel rows or the lifecycle, and nothing is requested', async (t) => {
  let requests = 0;
  const eventSources = [];
  t.mock.method(globalThis, 'fetch', async () => {
    requests++;
    throw new Error('GhostMaps must make no request');
  });
  const previousEventSource = globalThis.EventSource;
  globalThis.EventSource = class {
    constructor(url) {
      eventSources.push(url);
    }
  };
  t.after(() => {
    if (previousEventSource) globalThis.EventSource = previousEventSource;
    else delete globalThis.EventSource;
  });
  const lifetime = new AbortController();
  t.after(() => lifetime.abort());
  const catalog = createApplicationCatalog({
    sources: createStandaloneLayerSources(),
    signal: lifetime.signal,
    surface: createSurfaceServices({
      terrainSource: { getHeights: async () => [] },
      signal: lifetime.signal,
      eventTarget: null,
    }),
  });
  assert.equal(catalog.get(ID), undefined);
  assert.equal(
    catalog.layers.some((layer) => layer.id === ID),
    false,
  );
  assert.equal(
    catalog.metadata.some((entry) => entry.id === ID),
    false,
  );
  const manager = new LayerLifecycle({});
  for (const layer of catalog.layers) manager.register(layer);
  assert.equal(
    manager.getAll().some((row) => row.id === ID),
    false,
    'not a row in the layer panel',
  );
  assert.notEqual(await manager.setEnabled(ID, true), true);
  assert.equal(requests, 0);
  assert.deepEqual(eventSources, []);
});

test('saved state and the legacy share parameters never turn it on, and still decode', () => {
  const stored = JSON.stringify({ v: 2, l: [ID, 'flights'], o: {} });
  assert.deepEqual(parseStoredLayerState(stored)?.enabledLayerIds, ['flights']);
  const params = new URLSearchParams([
    ['v', '2'],
    ['l', `f.${TOKEN}`],
  ]);
  const decoded = decodeLayerStateParams(params);
  assert.ok(decoded, 'an old link carrying the token still decodes');
  assert.deepEqual(decoded.enabledLayerIds, ['flights']);
  const only = decodeLayerStateParams(
    new URLSearchParams([
      ['v', '2'],
      ['l', TOKEN],
    ]),
  );
  assert.deepEqual(only?.enabledLayerIds, []);
});

test('a binary share link with the layer bit set decodes, ignores it and reports nothing unknown', () => {
  const layerState = createDefaultLayerState();
  layerState.enabledLayerIds = ['recent-imagery']; // token 1: bit 1 of byte 0
  const sealed = decodeBase64Url(encodeShareView({ layerState }));
  const bytes = [...sealed.slice(0, -1)];
  let patched = 0;
  for (let i = 1; i < bytes.length - 1; i += 1) {
    if (bytes[i] === 1 && bytes[i + 1] === 0x02) {
      bytes[i + 1] |= 1 << Number(TOKEN);
      patched += 1;
    }
  }
  assert.equal(patched, 1, 'found the one layer bitset to patch');
  const result = decodeShareView(encodeBase64Url([...bytes, crc8(bytes)]));
  assert.equal(result.ok, true, result.reason);
  assert.deepEqual(result.state.layerState.enabledLayerIds, ['recent-imagery']);
  assert.equal(result.unknownFields, undefined);
});

test('its credit line is not registered', () => {
  const credits = [];
  registerDataCredits({
    creditDisplay: { addStaticCredit: (credit) => credits.push(credit) },
  });
  assert.ok(credits.length > 0);
  assert.equal(
    credits.some((credit) => /GhostMaps|S2 Underground/.test(credit.html)),
    false,
  );
});

test('the server does not mount /api/ghostmaps, so nothing can poll GitHub', () => {
  assert.equal(
    localProviderPlugins().some(({ name }) => name === 'ghostmaps'),
    false,
  );
  const source = readFileSync(
    new URL('../../server/providers/local.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /STUBBED_LAYER_IDS\.includes\('s2-ghostmaps'\)/);
});
