import { readShellSource } from '../testSupport/readShellSource.mjs';
import { expandApplicationHtml } from '../../build/application-html.js';
import { readLayerSource } from '../testSupport/readLayerSource.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';

import { DataLayerManager } from './manager.js';
import {
  LEGACY_LAYER_STATE_TOKENS,
  LAYER_STATE_REGISTRY,
  LAYER_STATE_STORAGE_KEY,
  LAYER_STATE_TOKEN_ALPHABET,
  LAYER_STATE_TOKEN_RESERVATIONS,
  REGISTERED_LAYER_IDS,
  RETIRED_LAYER_OPTION_TOKENS,
  SHARE_TRACKING_RESTORE_POLICIES,
  createDefaultLayerState,
  decodeLayerStateParams,
  encodeLayerStateParams,
  isRetiredLayerOption,
  nextLayerStateToken,
  normalizeLayerState,
  optionSpecs,
  parseStoredLayerState,
  serializeStoredLayerState,
  validateLayerStateAllocations,
  validateLayerStateRegistry,
} from './layerState.js';
import { LayerStateCoordinator } from './layerStateCoordinator.js';
import { stampInitialShareGesture } from '../navigationPolicy.js';
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function paramsForLayer(id) {
  if (id === 'flights' || id === 'military') {
    return { irBoost: true };
  }
  if (id === 'satellites')
    return { catalog: 'core', showPoints: false, showOrbits: false };
  if (id === 'cctv') {
    return {
      coverageMode: 'on',
      showProjection: true,
      autoHop: false,
      autoHopSec: 22,
      selectedCameraId: 'secret-camera',
      calibrationMode: true,
      calibration: { cameraId: 'secret-camera', values: { heading: 12 } },
    };
  }
  if (id === 'radio') {
    return {
      filter: 'all',
      volume: 0.8,
      selectedStationId: 'private-station',
      audioState: 'playing',
      voiceDucked: true,
    };
  }
  return null;
}

function fakeLayer(id, hooks = {}) {
  let params = paramsForLayer(id);
  return {
    id,
    name: id,
    icon: '',
    source: 'test',
    async init() {
      return hooks.init ? hooks.init() : true;
    },
    async enable() {
      return hooks.enable ? hooks.enable() : true;
    },
    async update() {
      return hooks.update ? hooks.update() : true;
    },
    async disable() {
      return hooks.disable ? hooks.disable() : true;
    },
    ...(hooks.resolveTrackingRestoreTarget
      ? {
          async resolveTrackingRestoreTarget(targetId, options) {
            return hooks.resolveTrackingRestoreTarget(targetId, options);
          },
        }
      : {}),
    ...(params
      ? {
          setParams(next = {}, options = {}) {
            if (hooks.setParams) {
              const result = hooks.setParams(next, options);
              if (result === false) return false;
              // 'defer' models the production tracking latch: the layer ACCEPTS the
              // request and holds it pending, but getParams() keeps reporting the
              // previous (still-untracked) value until the subject really arrives.
              if (result === 'defer') return true;
            }
            params = { ...params, ...next };
            return true;
          },
          /** Test seam: a deferred subject finally arrives on a later poll. */
          _arrive(next) {
            params = { ...params, ...next };
          },
          getParams() {
            return { ...params };
          },
          ...(hooks.cancelPendingTrackingRestore
            ? {
                cancelPendingTrackingRestore(options) {
                  hooks.cancelPendingTrackingRestore(options);
                },
              }
            : {}),
        }
      : {}),
  };
}

function productionManager(hooksById = {}) {
  const manager = new DataLayerManager({});
  for (const id of REGISTERED_LAYER_IDS)
    manager.register(fakeLayer(id, hooksById[id] || {}));
  manager.finalizeRegistrations(LAYER_STATE_REGISTRY);
  return manager;
}

/**
 * Deterministic clock + timer queue for the pending-tracking window, so the
 * 90 s / 45 s / 300 s expiries are provable without sleeping.
 */
function manualTimers(startMs = 0) {
  let nowMs = startMs;
  let queued = null;
  return {
    now: () => nowMs,
    setTimer: (fn, ms) => {
      queued = { fn, ms };
      return queued;
    },
    clearTimer: (handle) => {
      if (queued === handle) queued = null;
    },
    /** Fire queued polls, advancing the clock, until nothing re-arms. */
    runUntilIdle(maxTicks = 2_000) {
      for (let tick = 0; tick < maxTicks; tick += 1) {
        const pending = queued;
        if (!pending) return;
        queued = null;
        nowMs += pending.ms;
        pending.fn();
      }
      throw new Error('pending-tracking watch never settled');
    },
  };
}

function memoryStorage(initial = null) {
  const values = new Map();
  if (initial !== null) values.set(LAYER_STATE_STORAGE_KEY, initial);
  return {
    writes: [],
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, value);
      this.writes.push([key, value]);
    },
  };
}

function shareSink() {
  return {
    provider: null,
    updates: 0,
    setLayerStateProvider(provider) {
      this.provider = provider;
    },
    onLayerStateChange() {
      this.updates += 1;
    },
  };
}

function encode(state) {
  const params = new URLSearchParams([['v', '2']]);
  encodeLayerStateParams(params, state);
  return params.toString();
}

test('production registry is exact, canonical, and rejects incomplete contracts', async () => {
  assert.equal(validateLayerStateRegistry(), true);
  assert.equal(REGISTERED_LAYER_IDS.length, 21);
  assert.equal(new Set(REGISTERED_LAYER_IDS).size, 21);
  assert.equal(REGISTERED_LAYER_IDS.includes('s2-ghostmaps'), false);
  assert.ok(REGISTERED_LAYER_IDS.includes('transit'));
  assert.deepEqual(REGISTERED_LAYER_IDS, [...REGISTERED_LAYER_IDS].sort());
  assert.deepEqual(LEGACY_LAYER_STATE_TOKENS, {
    'ais-live-vessels': 'a',
    'alpr-cameras': 'p',
    'bhote-koshi-2026': 'h',
    'bhote-koshi-locator': 'z',
    bikeshare: 'b',
    cctv: 'c',
    directions: 'n',
    earthquakes: 'e',
    'fire-perimeters': '2',
    flights: 'f',
    'local-dams': 'q',
    'local-datacenters': 'd',
    'local-firms': 'w',
    military: 'm',
    'military-awareness': 'g',
    'military-installations': 'i',
    radio: 'r',
    'recent-imagery': '1',
    'rocket-launches': 'x',
    satellites: 's',
    'telegeography-submarine-cables': 'u',
    traffic: 't',
    transit: 'j',
    'weather-cyclones': 'y',
    'weather-lightning': 'l',
    'weather-radar': 'v',
    'weather-satellite': 'o',
    wind: 'k',
  });
  for (const { id, token } of LAYER_STATE_REGISTRY) {
    assert.equal(LAYER_STATE_TOKEN_RESERVATIONS[id], token);
  }
  for (const [id, token] of Object.entries(LEGACY_LAYER_STATE_TOKENS)) {
    assert.equal(LAYER_STATE_TOKEN_RESERVATIONS[id], token);
  }
  assert.equal(nextLayerStateToken(), '6');
  assert.equal(
    nextLayerStateToken({
      ...LAYER_STATE_TOKEN_RESERVATIONS,
      alpha: '6',
      bravo: '7',
    }),
    '8',
  );
  const digitsExhausted = {
    ...LAYER_STATE_TOKEN_RESERVATIONS,
    ...Object.fromEntries(
      [...'6789'].map((digit) => [`prior-${digit}`, digit]),
    ),
  };
  assert.equal(nextLayerStateToken(digitsExhausted), '00');
  assert.equal(
    nextLayerStateToken({ ...digitsExhausted, retired: '00', used: '01' }),
    '02',
  );
  assert.equal(
    nextLayerStateToken({
      ...digitsExhausted,
      ...Object.fromEntries(
        [...LAYER_STATE_TOKEN_ALPHABET].map((second) => [
          `pair-0${second}`,
          `0${second}`,
        ]),
      ),
    }),
    '10',
  );
  assert.throws(
    () =>
      nextLayerStateToken(
        Object.fromEntries(
          [
            ...'0123456789',
            ...[...LAYER_STATE_TOKEN_ALPHABET].flatMap((first) =>
              [...LAYER_STATE_TOKEN_ALPHABET].map(
                (second) => `${first}${second}`,
              ),
            ),
          ].map((token, index) => [`occupied-${index}`, token]),
        ),
      ),
    /namespace exhausted/,
  );
  assert.equal(
    validateLayerStateRegistry(
      [{ id: 'future-layer', token: '0', disposition: 'enabled-only' }],
      { 'future-layer': '0' },
    ),
    true,
  );
  assert.equal(
    validateLayerStateRegistry(
      [{ id: 'future-layer', token: '01', disposition: 'enabled-only' }],
      { retired: '00', 'future-layer': '01' },
    ),
    true,
  );
  assert.equal(
    validateLayerStateAllocations(LAYER_STATE_TOKEN_RESERVATIONS, {
      ...LAYER_STATE_TOKEN_RESERVATIONS,
      future: '6',
      next: '7',
    }),
    true,
  );
  assert.throws(
    () =>
      validateLayerStateAllocations(LAYER_STATE_TOKEN_RESERVATIONS, {
        ...LAYER_STATE_TOKEN_RESERVATIONS,
        future: '00',
      }),
    /next free token 6/,
  );
  const beforeLastDigit = { ...digitsExhausted };
  delete beforeLastDigit['prior-9'];
  assert.equal(
    validateLayerStateAllocations(beforeLastDigit, {
      ...beforeLastDigit,
      futurePair: '00',
      futureDigit: '9',
    }),
    true,
  );
  assert.equal(
    validateLayerStateAllocations(digitsExhausted, {
      ...digitsExhausted,
      pairB: '01',
      pairA: '00',
    }),
    true,
  );
  assert.throws(
    () =>
      validateLayerStateAllocations(
        { ...LAYER_STATE_TOKEN_RESERVATIONS, merged: '6' },
        { ...LAYER_STATE_TOKEN_RESERVATIONS, merged: '6', competing: '6' },
      ),
    /next free token 7/,
  );
  assert.throws(
    () => validateLayerStateAllocations({ future: '00' }, { future: '01' }),
    /changed or removed/,
  );
  assert.throws(
    () => validateLayerStateAllocations({ retired: '00' }, { newcomer: '00' }),
    /changed or removed/,
  );
  assert.throws(
    () =>
      validateLayerStateRegistry([
        ...LAYER_STATE_REGISTRY,
        LAYER_STATE_REGISTRY[0],
      ]),
    /Duplicate layer-state id/,
  );
  assert.throws(
    () =>
      validateLayerStateRegistry(
        [{ id: 'future-layer', token: '000', disposition: 'enabled-only' }],
        { 'future-layer': '000' },
      ),
    /Invalid layer-state token reservation/,
  );
  assert.throws(
    () =>
      validateLayerStateRegistry(
        [{ id: 'future-layer', token: 'a', disposition: 'enabled-only' }],
        { 'future-layer': 'a' },
      ),
    /Legacy layer-state token is immutable/,
  );
  assert.throws(
    () =>
      validateLayerStateRegistry(
        [{ id: 'flights', token: '0', disposition: 'enabled-only' }],
        { flights: '0' },
      ),
    /Legacy layer-state token is immutable/,
  );

  const manager = new DataLayerManager({});
  manager.register(fakeLayer('earthquakes'));
  assert.throws(
    () => manager.register(fakeLayer('earthquakes')),
    /Duplicate data-layer id/,
  );
  await assert.rejects(
    manager.restoreLayerState('earthquakes', { enabled: true }),
    /finalized/,
  );
  assert.throws(() => manager.finalizeRegistrations([]), /registry mismatch/);
  assert.throws(
    () =>
      manager.finalizeRegistrations([
        { id: 'earthquakes', disposition: 'default' },
      ]),
    /Invalid layer serialization disposition/,
  );
  assert.equal(
    manager.finalizeRegistrations([
      { id: 'earthquakes', disposition: 'enabled-only' },
    ]),
    true,
  );
  assert.throws(() => manager.register(fakeLayer('radio')), /finalized/);
  assert.throws(
    () => manager.registerForQa(fakeLayer('radio')),
    /not authorized/,
  );
  const qaManager = new DataLayerManager({}, { allowQaRegistration: true });
  qaManager.register(fakeLayer('earthquakes'));
  qaManager.finalizeRegistrations([
    { id: 'earthquakes', disposition: 'enabled-only' },
  ]);
  qaManager.registerForQa(fakeLayer('radio'));
  assert.equal(qaManager.layers.has('radio'), true);
  assert.equal(await qaManager.unregisterForQa('radio'), true);
  assert.equal(qaManager.layers.has('radio'), false);
});

test('v2 codec distinguishes absent from empty and keeps canonical deterministic ordering', () => {
  assert.equal(
    decodeLayerStateParams(new URLSearchParams('lat=1&lon=2')),
    null,
  );
  assert.equal(decodeLayerStateParams(new URLSearchParams('v=1&l=e')), null);
  assert.equal(decodeLayerStateParams(new URLSearchParams('v=3&l=e')), null);
  assert.equal(decodeLayerStateParams(new URLSearchParams('v=2')), null);

  const empty = decodeLayerStateParams(new URLSearchParams('v=2&l='));
  assert.deepEqual(empty.enabledLayerIds, []);
  assert.equal(empty.options.cctv, undefined, 'retired layers carry no options');

  const first = normalizeLayerState({
    enabledLayerIds: ['transit', 'wind', 'earthquakes', 'wind'],
    options: {
      wind: { units: 'mph', paused: true },
      satellites: { catalog: 'dense' },
    },
  });
  const second = normalizeLayerState({
    enabledLayerIds: ['earthquakes', 'wind', 'transit'],
    options: {
      satellites: { catalog: 'dense' },
      wind: { paused: true, units: 'mph' },
    },
  });
  assert.equal(encode(first), encode(second));
  assert.deepEqual(
    decodeLayerStateParams(new URLSearchParams(encode(first))),
    first,
  );
});

test('all production layers and options round-trip through a v2 share URL', () => {
  const allEnabled = normalizeLayerState({
    enabledLayerIds: REGISTERED_LAYER_IDS,
    options: {
      wind: { units: 'mph', paused: true },
      satellites: { catalog: 'dense' },
    },
  });
  const shareUrl = new URL('https://example.invalid/');
  shareUrl.hash = encode(allEnabled);
  const params = new URLSearchParams(shareUrl.hash.slice(1));
  const restored = decodeLayerStateParams(params);

  assert.equal(params.get('l')?.split('.').length, REGISTERED_LAYER_IDS.length);
  assert.deepEqual(restored?.enabledLayerIds, REGISTERED_LAYER_IDS);
  assert.deepEqual(restored?.options, allEnabled.options);
});

test('unknown enabled-layer tokens reject the payload instead of becoming an empty set', () => {
  assert.equal(
    decodeLayerStateParams(new URLSearchParams('v=2&l=unknown')),
    null,
  );
  assert.equal(
    decodeLayerStateParams(new URLSearchParams('v=2&l=c.unknown')),
    null,
  );
});

test('malformed enabled-layer lists reject the entire payload', () => {
  for (const value of ['.k', 'k.', 'k..e', 'k.k', '00', 'k.00']) {
    assert.equal(
      decodeLayerStateParams(new URLSearchParams(`v=2&l=${value}`)),
      null,
      `l=${value}`,
    );
  }
  assert.deepEqual(
    decodeLayerStateParams(new URLSearchParams('v=2&l=e.k')).enabledLayerIds,
    ['earthquakes', 'wind'],
  );
  for (const fields of ['l=f&l=f', 'l=f&l=unknown', 'l=&l=f']) {
    assert.equal(
      decodeLayerStateParams(new URLSearchParams(`v=2&${fields}`)),
      null,
      fields,
    );
  }
});

test('unknown and forbidden option fields are ignored while missing options use codec defaults', () => {
  const decoded = decodeLayerStateParams(
    new URLSearchParams(
      'v=2&l=e.k&lo=z.c.1_f.e.1_f.m.a',
    ),
  );
  assert.deepEqual(decoded.enabledLayerIds, ['earthquakes', 'wind']);
  assert.deepEqual(decoded.options.flights, {
    selectedFlightsTrackingId: null,
    selectedMilitaryTrackingId: null,
  });

  const raw = normalizeLayerState({
    enabledLayerIds: ['wind', 'unknown-layer'],
    options: {
      flights: { irBoost: true },
      satellites: { catalog: 'dense', showPoints: false, showOrbits: false },
    },
  });
  const serialized = `${encode(raw)} ${serializeStoredLayerState(raw)}`;
  for (const forbidden of [
    'private-camera',
    'calibration',
    'autoHopSec',
    'irBoost',
    'showPoints',
    'showOrbits',
    'private-station',
    'audioState',
    'voiceDucked',
    'secret',
  ])
    assert.equal(serialized.includes(forbidden), false, forbidden);
});

test('compact URL omits absent-meaning option state and still resolves to it', () => {
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['flights', 'satellites'];
  // Spelled out rather than reused from createDefaultLayerState() on purpose:
  // this is the ledger of what an OMITTED token means, so changing any of these
  // fails HERE and forces the change to be acknowledged.
  //
  state.options.flights = {
    selectedFlightsTrackingId: null,
    selectedMilitaryTrackingId: null,
  };
  state.options.satellites = {
    catalog: 'core',
    showPoints: true,
    showOrbits: true,
    selectedSatTrackingId: null,
  };
  state.options.wind.overlay = 'speed'; // Frozen v2 omitted-token meaning; new boots use trails.
  const params = encodeLayerStateParams(new URLSearchParams('v=2'), state);
  assert.equal(params.has('lo'), false);
  const roundTrip = decodeLayerStateParams(params);
  assert.deepEqual(roundTrip.options.flights.selectedFlightsTrackingId, null);
  assert.deepEqual(roundTrip.options.flights.selectedMilitaryTrackingId, null);
  assert.deepEqual(roundTrip.options.satellites.selectedSatTrackingId, null);
});

test('links written while the 3D aircraft models existed still open, and the retired options are dropped', () => {
  // `e` (models3d) and `m` (models3dMode) were written by every flights link of
  // that era, in both the on and off spellings. They are permanent tokens: the
  // decoder recognizes them and ignores the value, the encoder never writes them.
  const defaults = {
    selectedFlightsTrackingId: null,
    selectedMilitaryTrackingId: null,
  };
  for (const link of [
    'v=2&l=f',
    'v=2&l=f&lo=f.e.1',
    'v=2&l=f&lo=f.e.0',
    'v=2&l=f&lo=f.m.a',
    'v=2&l=f&lo=f.e.1_f.m.a',
  ]) {
    const decoded = decodeLayerStateParams(new URLSearchParams(link));
    assert.deepEqual(decoded.enabledLayerIds, ['flights'], link);
    assert.deepEqual(decoded.options.flights, defaults, link);
  }

  // The rest of the payload survives next to a retired token.
  const withTracking = decodeLayerStateParams(
    new URLSearchParams('v=2&l=f&lo=f.e.1_f.t.abc123_f.m.a'),
  );
  assert.equal(
    withTracking.options.flights.selectedFlightsTrackingId,
    'abc123',
  );

  assert.deepEqual(RETIRED_LAYER_OPTION_TOKENS.flights, {
    e: 'models3d',
    m: 'models3dMode',
  });
  assert.equal(isRetiredLayerOption('flights', 'e'), true);
  assert.equal(isRetiredLayerOption('flights', 'm'), true);
  assert.equal(isRetiredLayerOption('flights', 't'), false);
  assert.equal(isRetiredLayerOption('satellites', 'e'), false);
  // No live flights option may reuse a retired token.
  for (const spec of optionSpecs('flights'))
    assert.equal(isRetiredLayerOption('flights', spec.token), false, spec.key);

  const state = createDefaultLayerState();
  state.enabledLayerIds = ['flights'];
  assert.doesNotMatch(encode(state), /f\.[em]\./);
});

test('explicit navigation tracking clear removes the active durable ID from the generated hash', async () => {
  const manager = productionManager();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage: memoryStorage(),
  });
  await coordinator.start();
  await manager.setEnabled('flights', true, { origin: 'user' });
  manager.setLayerParams(
    'flights',
    { selectedFlightsTrackingId: 'abc123' },
    { origin: 'user' },
  );
  assert.equal(
    coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    'abc123',
  );
  assert.equal(encode(coordinator.getDurableState()).includes('abc123'), true);
  manager.setLayerParams(
    'flights',
    { selectedFlightsTrackingId: null },
    { origin: 'tool' },
  );
  assert.equal(
    coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    null,
  );
  assert.equal(encode(coordinator.getDurableState()).includes('abc123'), false);
  coordinator.destroy();
});

test('a direct Context selection promotes its owned tracker layer before persisting the ID', async () => {
  const manager = productionManager();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage: memoryStorage(),
  });
  await coordinator.start();
  await manager.setEnabled('flights', true, { origin: 'programmatic' });
  manager.setLayerParams(
    'flights',
    { selectedFlightsTrackingId: 'context-flight' },
    { origin: 'programmatic' },
  );
  assert.equal(
    manager.adoptLayerVisibility('flights', true, {
      origin: 'user',
      adoptedFromSelection: true,
    }),
    true,
  );
  assert.equal(
    manager.adoptLayerParams(
      'flights',
      { selectedFlightsTrackingId: 'context-flight' },
      { origin: 'user' },
    ),
    true,
  );
  const durable = coordinator.getDurableState();
  assert.equal(durable.enabledLayerIds.includes('flights'), true);
  assert.equal(
    durable.options.flights.selectedFlightsTrackingId,
    'context-flight',
  );
  assert.equal(encode(durable).includes('context-flight'), true);
  coordinator.destroy();
});

test('explicit Flight to Satellite replacement keeps the new Satellite ID durable', async () => {
  const manager = productionManager();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage: memoryStorage(),
  });
  await coordinator.start();
  await manager.setEnabled('flights', true, { origin: 'user' });
  await manager.setEnabled('satellites', true, { origin: 'user' });
  manager.setLayerParams(
    'flights',
    { selectedFlightsTrackingId: 'abc123' },
    { origin: 'user' },
  );
  assert.equal(
    coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    'abc123',
  );

  // UI replacement ordering clears the prior family before a direct tracker
  // publishes its already-applied selection through adoptLayerParams().
  manager.setLayerParams(
    'flights',
    { selectedFlightsTrackingId: null },
    { origin: 'user' },
  );
  manager.setLayerParams(
    'satellites',
    { selectedSatTrackingId: 25544 },
    { origin: 'programmatic' },
  );
  assert.equal(
    manager.adoptLayerParams(
      'satellites',
      { selectedSatTrackingId: 25544 },
      { origin: 'user' },
    ),
    true,
  );

  const durable = coordinator.getDurableState();
  assert.equal(durable.options.flights.selectedFlightsTrackingId, null);
  assert.equal(durable.options.flights.selectedMilitaryTrackingId, null);
  assert.equal(durable.options.satellites.selectedSatTrackingId, 25544);
  assert.equal(
    new URLSearchParams(encode(durable)).get('lo')?.includes('s.t.25544'),
    true,
  );
  coordinator.destroy();
});

test('explicit layer OFF clears its durable selected entity and prevents later resurrection', async () => {
  const manager = productionManager();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage: memoryStorage(),
  });
  await coordinator.start();
  await manager.setEnabled('flights', true, { origin: 'user' });
  manager.setLayerParams(
    'flights',
    { selectedFlightsTrackingId: 'abc123' },
    { origin: 'user' },
  );
  assert.equal(
    coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    'abc123',
  );
  await manager.setEnabled('flights', false, { origin: 'user' });
  assert.equal(
    coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    null,
  );
  assert.equal(
    Boolean(
      new URLSearchParams(encode(coordinator.getDurableState()))
        .get('lo')
        ?.includes('f.t.'),
    ),
    false,
  );
  coordinator.destroy();
});

test('unrelated explicit params retain the family live active ID while cancelling only pending state', async () => {
  const manager = productionManager();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage: memoryStorage(),
  });
  await coordinator.start();
  assert.equal(
    manager.setLayerParams(
      'flights',
      {
        selectedFlightsTrackingId: 'active001',
      },
      { origin: 'programmatic' },
    ),
    true,
  );
  await manager.setEnabled('flights', true, { origin: 'user' });
  assert.equal(
    manager.setLayerParams(
      'flights',
      { irBoost: true },
      { origin: 'user' },
    ),
    true,
  );
  assert.equal(
    coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    'active001',
  );
  coordinator.destroy();
});

test('stored state is deterministic, rejects other versions, and stays within a tested URL bound', () => {
  const state = createDefaultLayerState();
  state.enabledLayerIds = [...REGISTERED_LAYER_IDS].reverse();
  state.options.satellites = { catalog: 'dense' };
  state.options.cctv = {
    coverageMode: 'viewshed',
    showProjection: false,
    autoHop: true,
  };
  state.options.radio = { filter: 'genre:experimental-ambient', volume: 1 };
  const stored = serializeStoredLayerState(state);
  assert.deepEqual(parseStoredLayerState(stored), normalizeLayerState(state));
  assert.equal(parseStoredLayerState('{"v":1,"l":[]}'), null);
  assert.ok(encode(state).length < 420, encode(state));
});

test('restore applies sanitized params after init and before enable', async () => {
  const order = [];
  const manager = productionManager({
    flights: {
      init: () => {
        order.push('init');
        return true;
      },
      setParams: () => {
        order.push('params');
        return true;
      },
      enable: () => {
        order.push('enable');
        return true;
      },
      update: () => {
        order.push('update');
        return true;
      },
    },
  });
  const outcome = await manager.restoreLayerState(
    'flights',
    {
      enabled: true,
      params: { irBoost: true },
    },
    { origin: 'share-restore' },
  );
  assert.deepEqual(order, ['init', 'params', 'enable', 'update']);
  assert.equal(outcome.succeeded, true);
  assert.equal(outcome.persistenceWrite, false);
  assert.deepEqual(outcome.appliedOptions, { irBoost: true });
});

test('manager forwards passive restore origin into module parameter application', async () => {
  const seen = [];
  const manager = productionManager({
    flights: {
      setParams: (_params, options) => {
        seen.push(options);
      },
    },
  });
  await manager.restoreLayerState(
    'flights',
    {
      enabled: false,
      params: { selectedFlightsTrackingId: 'abc123' },
    },
    { origin: 'share-restore' },
  );
  assert.deepEqual(seen, [{ origin: 'share-restore', paramsIntentEpoch: 1 }]);
});

test('explicit manager params and visibility revoke module-owned pending tracking restore', async () => {
  const cancellations = [];
  const manager = productionManager({
    flights: {
      cancelPendingTrackingRestore: (options) => {
        cancellations.push(options);
      },
    },
  });

  await manager.restoreLayerState(
    'flights',
    {
      enabled: false,
      params: { selectedFlightsTrackingId: 'late001' },
    },
    { origin: 'share-restore' },
  );
  assert.deepEqual(
    cancellations,
    [],
    'passive restoration cannot cancel itself',
  );

  manager.setLayerParams('flights', { irBoost: true }, { origin: 'voice' });
  await manager.setEnabled('flights', false, { origin: 'user' });
  assert.deepEqual(cancellations, [
    { origin: 'voice', reason: 'explicit-params' },
    { origin: 'user', reason: 'explicit-visibility' },
  ]);
});

test('share payload wins over local, passive restore writes nothing, and explicit success persists', async () => {
  const local = createDefaultLayerState();
  local.enabledLayerIds = ['bikeshare'];
  const storage = memoryStorage(serializeStoredLayerState(local));
  const manager = productionManager();
  const share = shareSink();
  const coordinator = new LayerStateCoordinator(manager, share, { storage });
  const explicitEmpty = createDefaultLayerState();
  await coordinator.start({ shareLayerState: explicitEmpty });

  assert.equal(coordinator.source, 'share');
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, []);
  assert.deepEqual(storage.writes, []);
  assert.equal(share.provider().enabledLayerIds.length, 0);

  await manager.setEnabled('earthquakes', true, { origin: 'user' });
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, [
    'earthquakes',
  ]);
  assert.equal(storage.writes.length, 1);

  await manager.setEnabled('bikeshare', true, { origin: 'scene' });
  assert.equal(storage.writes.length, 1);
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, [
    'earthquakes',
  ]);

  await manager.setEnabled('bikeshare', true, { origin: 'tool' });
  assert.equal(storage.writes.length, 2);
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, [
    'bikeshare',
    'earthquakes',
  ]);

  manager.setLayerParams(
    'satellites',
    { showPoints: true },
    { origin: 'user' },
  );
  assert.equal(storage.writes.length, 2);
  assert.deepEqual(coordinator.getDurableState().options.satellites, {
    catalog: 'core',
    selectedSatTrackingId: null,
  });

  manager.setLayerParams('satellites', { catalog: 'dense' }, { origin: 'scene' });
  assert.equal(storage.writes.length, 2);
  assert.equal(coordinator.getDurableState().options.satellites.catalog, 'core');

  manager.setLayerParams(
    'satellites',
    { catalog: 'dense' },
    { origin: 'voice' },
  );
  assert.equal(storage.writes.length, 3);
  assert.equal(coordinator.getDurableState().options.satellites.catalog, 'dense');
  coordinator.destroy();
});

test('absent share payload restores local state without rewriting it', async () => {
  const local = createDefaultLayerState();
  local.enabledLayerIds = ['earthquakes', 'satellites'];
  local.options.satellites = { catalog: 'dense', selectedSatTrackingId: null };
  const storage = memoryStorage(serializeStoredLayerState(local));
  const manager = productionManager();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage,
  });
  const results = await coordinator.start();
  assert.equal(coordinator.source, 'local');
  assert.equal(manager.isEnabled('earthquakes'), true);
  assert.equal(manager.isEnabled('satellites'), true);
  assert.deepEqual(manager.getLayerParams('satellites'), {
    catalog: 'dense',
    selectedSatTrackingId: null,
    showPoints: false,
    showOrbits: false,
  });
  assert.equal(
    results.every((result) => result.persistenceWrite === false),
    true,
  );
  assert.deepEqual(storage.writes, []);
  coordinator.destroy();
});

test('historical share payload suppresses unrelated local layer preferences', async () => {
  const local = createDefaultLayerState();
  local.enabledLayerIds = ['bikeshare', 'transit'];
  const storage = memoryStorage(serializeStoredLayerState(local));
  const manager = productionManager();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage,
  });
  await coordinator.start({ allowLocalState: false });
  assert.equal(coordinator.source, 'legacy-share');
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, []);
  assert.equal(manager.getEnabledLayerIds().size, 0);
  assert.deepEqual(storage.writes, []);
  coordinator.destroy();
});

test('one layer failure is isolated from sibling restoration', async () => {
  const manager = productionManager({
    directions: {
      init: () => {
        throw new Error('missing key');
      },
    },
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['directions', 'earthquakes'];
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage: memoryStorage(),
  });
  const results = await coordinator.start({ shareLayerState: state });
  assert.equal(manager.isEnabled('directions'), false);
  assert.equal(manager.isEnabled('earthquakes'), true);
  const failed = results.find((result) => result.layerId === 'directions');
  assert.equal(failed.succeeded, false);
  assert.equal(failed.phase, 'init');
  assert.equal(failed.errorClass, 'Error');
  assert.equal(failed.error, 'missing key');
  assert.equal(
    results.find((result) => result.layerId === 'earthquakes').succeeded,
    true,
  );
  coordinator.destroy();
});

test('later explicit visibility during delayed restore wins for that layer only', async () => {
  const gate = deferred();
  const manager = productionManager();
  const storage = memoryStorage();
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['transit', 'earthquakes'];
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage,
    restoreGate: gate.promise,
  });
  const restore = coordinator.start({ shareLayerState: state });
  await manager.setEnabled('transit', false, { origin: 'user' });
  gate.resolve();
  const results = await restore;
  assert.equal(manager.isEnabled('transit'), false);
  assert.equal(manager.isEnabled('earthquakes'), true);
  assert.equal(
    results.find((result) => result.layerId === 'transit').cancellationReason,
    'superseded',
  );
  assert.equal(storage.writes.length, 1);
  coordinator.destroy();
});

test('share restore waits for a superseding same-target visibility successor', async () => {
  const firstUpdateStarted = deferred();
  const releaseFirstUpdate = deferred();
  const secondUpdateStarted = deferred();
  const releaseSecondUpdate = deferred();
  let updateCount = 0;
  const manager = productionManager({
    transit: {
      update: async () => {
        updateCount += 1;
        if (updateCount === 1) {
          firstUpdateStarted.resolve();
          await releaseFirstUpdate.promise;
        } else if (updateCount === 2) {
          secondUpdateStarted.resolve();
          await releaseSecondUpdate.promise;
        }
        return true;
      },
    },
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['transit'];
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage: memoryStorage(),
  });

  let restoreSettled = false;
  const restore = coordinator
    .start({ shareLayerState: state })
    .then((result) => {
      restoreSettled = true;
      return result;
    });
  await firstUpdateStarted.promise;
  let successorSettled = false;
  const explicitOn = manager
    .setEnabled('transit', true, { origin: 'user' })
    .then((result) => {
      successorSettled = true;
      return result;
    });
  releaseFirstUpdate.resolve();
  await secondUpdateStarted.promise;
  await Promise.resolve();
  assert.equal(
    restoreSettled,
    false,
    'aggregate must wait for the authoritative successor',
  );
  assert.equal(successorSettled, false);

  releaseSecondUpdate.resolve();
  assert.equal(await explicitOn, true);
  const results = await restore;
  const transit = results.find((result) => result.layerId === 'transit');
  assert.equal(transit.cancellationReason, 'superseded');
  assert.equal(transit.successorEnabled, true);
  assert.equal(transit.authoritativeIntentEpoch, transit.successorIntentEpoch);
  assert.equal(transit.authoritativeEnabled, true);
  assert.equal(transit.succeeded, true);
  assert.equal(
    manager.getLayerLifecycleState('transit').lifecycleState,
    'enabled',
  );
  coordinator.destroy();
});

test('share restore waits for a superseding opposite-target visibility successor', async () => {
  const updateStarted = deferred();
  const releaseUpdate = deferred();
  const disableStarted = deferred();
  const releaseDisable = deferred();
  const manager = productionManager({
    transit: {
      update: async () => {
        updateStarted.resolve();
        await releaseUpdate.promise;
        return true;
      },
      disable: async () => {
        disableStarted.resolve();
        await releaseDisable.promise;
        return true;
      },
    },
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['transit'];
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage: memoryStorage(),
  });

  let restoreSettled = false;
  const restore = coordinator
    .start({ shareLayerState: state })
    .then((result) => {
      restoreSettled = true;
      return result;
    });
  await updateStarted.promise;
  const explicitOff = manager.setEnabled('transit', false, { origin: 'user' });
  releaseUpdate.resolve();
  await disableStarted.promise;
  await Promise.resolve();
  assert.equal(
    restoreSettled,
    false,
    'aggregate must wait for the OFF successor to settle',
  );

  releaseDisable.resolve();
  assert.equal(await explicitOff, true);
  const results = await restore;
  const transit = results.find((result) => result.layerId === 'transit');
  assert.equal(transit.cancellationReason, 'superseded');
  assert.equal(transit.successorEnabled, false);
  assert.equal(transit.authoritativeIntentEpoch, transit.successorIntentEpoch);
  assert.equal(transit.authoritativeEnabled, false);
  assert.equal(
    transit.succeeded,
    false,
    'the newer OFF must not count as successful shared ON',
  );
  assert.equal(
    manager.getLayerLifecycleState('transit').lifecycleState,
    'disabled',
  );
  coordinator.destroy();
});

test('later explicit params during init replace options without cancelling visibility', async () => {
  const initGate = deferred();
  const initStarted = deferred();
  const manager = productionManager({
    flights: {
      init: async () => {
        initStarted.resolve();
        await initGate.promise;
        return true;
      },
    },
  });
  const storage = memoryStorage();
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['flights'];
  state.options.flights = {
    selectedFlightsTrackingId: 'late001',
  };
  const share = shareSink();
  const coordinator = new LayerStateCoordinator(manager, share, { storage });
  const restore = coordinator.start({ shareLayerState: state });
  await initStarted.promise;
  assert.equal(
    manager.setLayerParams(
      'flights',
      { irBoost: false },
      { origin: 'user' },
    ),
    true,
  );
  initGate.resolve();
  const results = await restore;
  assert.equal(manager.isEnabled('flights'), true);
  assert.deepEqual(coordinator.getDurableState().options.flights, {
    selectedFlightsTrackingId: null,
    selectedMilitaryTrackingId: null,
  });
  assert.equal(
    results.find((result) => result.layerId === 'flights').succeeded,
    true,
  );
  assert.equal(storage.writes.length, 1);
  assert.equal(
    new URLSearchParams(encode(share.provider()))
      .get('lo')
      ?.includes('f.t.late001') || false,
    false,
  );
  coordinator.destroy();
});

test('explicit navigation preserves unrelated visibility and option restoration', async () => {
  const initGate = deferred();
  const initStarted = deferred();
  const paramsCalls = [];
  const manager = productionManager({
    flights: {
      init: async () => {
        initStarted.resolve();
        await initGate.promise;
        return true;
      },
      setParams: (params) => {
        paramsCalls.push(params);
        return true;
      },
    },
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['flights'];
  state.options.flights = {
    selectedFlightsTrackingId: 'stale-flight',
    selectedMilitaryTrackingId: null,
  };
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage: memoryStorage(),
  });
  const restore = coordinator.start({ shareLayerState: state });
  await initStarted.promise;
  // Navigation owns only camera and pending entity selection. It must not
  // revoke the layer visibility or unrelated display-option lanes.
  initGate.resolve();
  const results = await restore;
  assert.equal(manager.isEnabled('flights'), true);
  assert.deepEqual(paramsCalls, []);
  assert.equal(
    results.find((result) => result.layerId === 'flights').succeeded,
    true,
  );
  coordinator.destroy();
});

test('startup gesture clears passive Follow but preserves slow layer and display options', async () => {
  const flightsInit = deferred();
  const flightsStarted = deferred();
  const radioInit = deferred();
  const radioStarted = deferred();
  const manager = productionManager({
    flights: {
      init: async () => {
        flightsStarted.resolve();
        await flightsInit.promise;
        return true;
      },
    },
    satellites: {
      init: async () => {
        radioStarted.resolve();
        await radioInit.promise;
        return true;
      },
    },
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['flights', 'satellites'];
  state.options.flights = {
    selectedFlightsTrackingId: 'late-share',
    selectedMilitaryTrackingId: null,
  };
  state.options.satellites = { catalog: 'dense', selectedSatTrackingId: null };
  const storage = memoryStorage();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage,
  });
  const restore = coordinator.start({ shareLayerState: state });
  await Promise.all([flightsStarted.promise, radioStarted.promise]);

  let cameraGeneration = 0;
  stampInitialShareGesture(({ cancelPendingSelection }) => {
    cameraGeneration += 1;
    if (cancelPendingSelection) {
      coordinator.cancelPendingShareTracking('startup-gesture', {
        clearSelection: true,
      });
    }
  });
  flightsInit.resolve();
  radioInit.resolve();
  const results = await restore;

  assert.equal(cameraGeneration, 1);
  assert.equal(manager.isEnabled('flights'), true);
  assert.equal(manager.isEnabled('satellites'), true);
  assert.deepEqual(manager.getLayerParams('flights'), {
    irBoost: true,
    selectedFlightsTrackingId: null,
  });
  assert.deepEqual(manager.getLayerParams('satellites'), {
    catalog: 'dense',
    showPoints: false,
    showOrbits: false,
  });
  assert.equal(
    results.find((result) => result.layerId === 'flights').succeeded,
    true,
  );
  assert.equal(
    results.find((result) => result.layerId === 'satellites').succeeded,
    true,
  );
  assert.deepEqual(storage.writes, []);
  coordinator.destroy();
});

test('tracking restore refreshes the destination feed before the module resolves Follow', async () => {
  const order = [];
  const manager = productionManager({
    flights: {
      update: () => {
        order.push('refresh');
        return true;
      },
      resolveTrackingRestoreTarget: (targetId, options) => {
        order.push(`resolve:${targetId}:${options.origin}`);
        return { status: 'found', source: 'test' };
      },
    },
  });
  await manager.setEnabled('flights', true, { origin: 'scene' });
  order.length = 0;
  const result = await manager.resolveLayerTrackingTarget('flights', 'abc123', {
    origin: 'share-restore',
  });
  assert.deepEqual(order, ['refresh', 'resolve:abc123:share-restore']);
  assert.equal(result.status, 'found');
  assert.equal(result.refreshSucceeded, true);
});

test('shared flight selection is deferred until destination refresh and then follows', async () => {
  const storage = memoryStorage();
  const statuses = [];
  const paramsCalls = [];
  const manager = productionManager({
    flights: {
      setParams: (params) => {
        paramsCalls.push({ ...params });
        return true;
      },
      resolveTrackingRestoreTarget: (targetId) => ({
        status: 'found',
        targetId,
      }),
    },
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['flights'];
  state.options.flights = {
    ...state.options.flights,
    selectedFlightsTrackingId: 'abc123',
  };
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage,
    onTrackingRestoreStatus: (status) => statuses.push(status),
  });
  await coordinator.start({ shareLayerState: state, shareCreatedAtMs: 1_000 });
  assert.deepEqual(paramsCalls, []);

  const result = await coordinator.restoreShareTrackingSelection();
  assert.equal(result.status, 'found');
  assert.equal(result.classification, 'followed');
  assert.equal(result.cleared, false);
  assert.equal(statuses.length, 1);
  assert.equal(
    coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    'abc123',
  );
  assert.deepEqual(storage.writes, []);
  coordinator.destroy();
});

test('authoritative missing target clears only the passive ID and uses strict expiry boundary', async () => {
  const run = async ({ nowMs, copiedAtMs }) => {
    const storage = memoryStorage();
    const manager = productionManager({
      flights: {
        resolveTrackingRestoreTarget: () => ({ status: 'missing' }),
        setParams: (next) =>
          Object.hasOwn(next, 'selectedFlightsTrackingId') &&
          next.selectedFlightsTrackingId
            ? 'defer'
            : true,
      },
    });
    const state = createDefaultLayerState();
    state.enabledLayerIds = ['flights'];
    state.options.flights = {
      ...state.options.flights,
      selectedFlightsTrackingId: 'gone001',
    };
    // The subject is absent, so the verdict now lands only after the pending
    // window has genuinely expired. Drive that window synchronously.
    const timers = manualTimers(nowMs);
    const statuses = [];
    const coordinator = new LayerStateCoordinator(manager, shareSink(), {
      storage,
      now: timers.now,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
      onTrackingRestoreStatus: (status) => statuses.push(status),
    });
    await coordinator.start({
      shareLayerState: state,
      shareCreatedAtMs: copiedAtMs,
    });
    const pending = await coordinator.restoreShareTrackingSelection();
    assert.equal(
      pending.classification,
      'pending',
      'absence must first be held pending',
    );
    assert.equal(
      statuses.length,
      1,
      'pending is published for soft progress feedback',
    );
    assert.equal(statuses[0].classification, 'pending');
    timers.runUntilIdle();
    const result = statuses.at(-1);
    const durable = coordinator.getDurableState();
    coordinator.destroy();
    return { result, durable, writes: storage.writes };
  };

  const boundary = await run({ nowMs: 190_000, copiedAtMs: 100_000 });
  assert.equal(boundary.result.classification, 'unavailable');
  assert.equal(boundary.result.cleared, true);
  assert.equal(
    boundary.durable.options.flights.selectedFlightsTrackingId,
    null,
  );
  assert.deepEqual(boundary.writes, []);

  const expired = await run({ nowMs: 190_001, copiedAtMs: 100_000 });
  assert.equal(expired.result.classification, 'expired');
});

test('feed failure is not misreported as target absence and malformed time never says expired', async () => {
  const storage = memoryStorage();
  const statuses = [];
  const manager = productionManager({
    satellites: {
      resolveTrackingRestoreTarget: () => ({
        status: 'source-unavailable',
        reason: 'partial catalog',
      }),
      setParams: (next) =>
        Object.hasOwn(next, 'selectedSatTrackingId') &&
        next.selectedSatTrackingId
          ? 'defer'
          : true,
    },
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['satellites'];
  state.options.satellites = {
    ...state.options.satellites,
    selectedSatTrackingId: 25544,
  };
  const timers = manualTimers();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage,
    now: timers.now,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    onTrackingRestoreStatus: (status) => statuses.push(status),
  });
  await coordinator.start({ shareLayerState: state, shareCreatedAtMs: null });
  const pending = await coordinator.restoreShareTrackingSelection();
  // A partial catalog is a "not here YET" too — hold it, do not announce.
  assert.equal(pending.classification, 'pending');
  assert.equal(statuses.length, 1);
  assert.equal(statuses[0].classification, 'pending');
  timers.runUntilIdle();
  const result = statuses.at(-1);
  assert.equal(result.status, 'source-unavailable');
  assert.equal(result.classification, 'source-unavailable');
  assert.equal(result.cleared, true);
  assert.equal(statuses.length, 2);
  assert.deepEqual(storage.writes, []);
  coordinator.destroy();
});

// ---------------------------------------------------------------------------
// Share restore must be as resilient as reload-from-local.
//
// Reload-from-local arms the layer's own deferred-restore latch, which
// re-attempts on every later poll, so a contact that misses the first refresh
// is still picked up. The shared path used to decide on that single refresh:
// it cleared the subject from durable state AND the URL and posted a failure
// notice seconds into startup, so the SAME link healed on reload but never on
// the share. These pin both directions.
// ---------------------------------------------------------------------------

function pendingTrackingFixture({
  resolveStatus = 'missing',
  copiedAtMs = null,
} = {}) {
  const storage = memoryStorage();
  const statuses = [];
  const paramsCalls = [];
  const cancellations = [];
  const manager = productionManager({
    flights: {
      resolveTrackingRestoreTarget: () => ({ status: resolveStatus }),
      setParams: (next, options) => {
        paramsCalls.push({ params: { ...next }, origin: options?.origin });
        // Production holds the id pending; getParams keeps reporting untracked
        // until the subject actually arrives on a later poll.
        return Object.hasOwn(next, 'selectedFlightsTrackingId') &&
          next.selectedFlightsTrackingId
          ? 'defer'
          : true;
      },
      cancelPendingTrackingRestore: (options) => cancellations.push(options),
    },
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['flights'];
  state.options.flights = {
    ...state.options.flights,
    selectedFlightsTrackingId: 'late007',
  };
  const timers = manualTimers();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage,
    now: timers.now,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    onTrackingRestoreStatus: (status) => statuses.push(status),
  });
  return {
    manager,
    coordinator,
    statuses,
    storage,
    timers,
    state,
    copiedAtMs,
    paramsCalls,
    cancellations,
  };
}

test('share tracking policies pin each owner, key, label, and acquisition deadline', () => {
  assert.deepEqual(SHARE_TRACKING_RESTORE_POLICIES, {
    flights: {
      optionOwner: 'flights',
      optionKey: 'selectedFlightsTrackingId',
      expiryWindowMs: 90_000,
      label: 'flight',
    },
    military: {
      optionOwner: 'flights',
      optionKey: 'selectedMilitaryTrackingId',
      expiryWindowMs: 45_000,
      label: 'military flight',
    },
    satellites: {
      optionOwner: 'satellites',
      optionKey: 'selectedSatTrackingId',
      expiryWindowMs: 300_000,
      label: 'satellite',
    },
  });
});

test('a shared subject that has not arrived yet is held pending, never declared gone', async () => {
  const f = pendingTrackingFixture();
  await f.coordinator.start({
    shareLayerState: f.state,
    shareCreatedAtMs: f.copiedAtMs,
  });
  const pending = await f.coordinator.restoreShareTrackingSelection();

  assert.equal(pending.status, 'pending');
  assert.equal(pending.classification, 'pending');
  assert.equal(pending.cleared, false);
  // No notice, and the subject survives in durable state AND in the URL.
  assert.equal(
    f.statuses.length,
    1,
    'a not-yet-arrived subject publishes progress',
  );
  assert.equal(f.statuses[0].classification, 'pending');
  assert.equal(
    f.coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    'late007',
    'the shared subject must not be cleared while it is still pending',
  );
  // The layer's own deferred-restore latch was armed, under the passive origin.
  const armed = f.paramsCalls.filter(
    (call) => call.params.selectedFlightsTrackingId === 'late007',
  );
  assert.equal(armed.length, 1, 'the layer latch is armed exactly once');
  assert.equal(armed[0].origin, 'share-restore', 'arming must stay passive');
  assert.deepEqual(
    f.storage.writes,
    [],
    'recipient preferences are never written',
  );
  f.coordinator.destroy();
});

test('a pending shared subject latches on when it arrives on a later poll', async () => {
  const f = pendingTrackingFixture();
  await f.coordinator.start({
    shareLayerState: f.state,
    shareCreatedAtMs: f.copiedAtMs,
  });
  await f.coordinator.restoreShareTrackingSelection();
  assert.equal(f.statuses.length, 1);
  assert.equal(f.statuses[0].classification, 'pending');

  // The contact shows up on a later feed poll, exactly as the layer latch would.
  f.manager.layers
    .get('flights')
    .module._arrive({ selectedFlightsTrackingId: 'late007' });
  f.timers.runUntilIdle();

  assert.equal(f.statuses.length, 2);
  assert.equal(f.statuses[1].classification, 'followed');
  assert.equal(f.statuses[1].cleared, false);
  assert.equal(
    f.coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    'late007',
  );
  assert.deepEqual(f.storage.writes, []);
  f.coordinator.destroy();
});

test('caller abort after pending handoff revokes the watch and layer latch exactly once', async () => {
  const f = pendingTrackingFixture();
  const caller = new AbortController();
  await f.coordinator.start({
    shareLayerState: f.state,
    shareCreatedAtMs: f.copiedAtMs,
  });
  const pending = await f.coordinator.restoreShareTrackingSelection({
    signal: caller.signal,
  });
  assert.equal(pending.classification, 'pending');

  caller.abort('caller-cancelled');
  f.timers.runUntilIdle();
  caller.abort('late-repeat');

  assert.deepEqual(
    f.statuses.map((status) => status.classification),
    ['pending', 'cancelled'],
  );
  assert.equal(f.statuses[1].reason, 'caller-cancelled');
  assert.equal(
    f.cancellations.length,
    1,
    'the module latch is revoked exactly once',
  );
  assert.equal(f.cancellations[0].reason, 'caller-cancelled');
  assert.equal(
    f.coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    'late007',
    'cancellation does not rewrite recipient state',
  );
  f.coordinator.destroy();
});

test('a failed deferred-latch arm publishes one terminal failure and never ACQUIRING', async () => {
  for (const armFailure of [
    () => false,
    () => Promise.reject(new Error('async latch rejection')),
    () => {
      throw new Error('sync latch throw');
    },
  ]) {
    const f = pendingTrackingFixture();
    await f.coordinator.start({
      shareLayerState: f.state,
      shareCreatedAtMs: f.copiedAtMs,
    });
    const setLayerParams = f.manager.setLayerParams.bind(f.manager);
    f.manager.setLayerParams = (layerId, params, options) =>
      params?.selectedFlightsTrackingId
        ? armFailure()
        : setLayerParams(layerId, params, options);

    const result = await f.coordinator.restoreShareTrackingSelection();
    f.timers.runUntilIdle();

    assert.equal(result.status, 'source-unavailable');
    assert.equal(result.classification, 'source-unavailable');
    assert.equal(result.cleared, true);
    assert.deepEqual(
      f.statuses.map((status) => status.classification),
      ['source-unavailable'],
      'a rejected latch never publishes pending progress',
    );
    assert.equal(
      f.coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
      null,
    );
    f.coordinator.destroy();
  }
});

test('same-target supersession cancels the old acquisition before publishing the successor', async () => {
  const f = pendingTrackingFixture();
  await f.coordinator.start({
    shareLayerState: f.state,
    shareCreatedAtMs: f.copiedAtMs,
  });
  await f.coordinator.restoreShareTrackingSelection();
  await f.coordinator.restoreShareTrackingSelection();

  assert.deepEqual(
    f.statuses.map((status) => status.classification),
    ['pending', 'cancelled', 'pending'],
  );
  assert.equal(f.cancellations.length, 1);
  f.coordinator.cancelPendingShareTracking('test-complete');
  f.coordinator.destroy();
});

test('destroying or superseding the coordinator clears pending progress explicitly', async () => {
  for (const teardown of [
    (coordinator) => coordinator.destroy(),
    (coordinator) =>
      coordinator.cancelPendingShareTracking('explicit-navigation'),
    (coordinator) => coordinator.cancelPendingRestores('explicit-navigation'),
  ]) {
    const f = pendingTrackingFixture();
    await f.coordinator.start({
      shareLayerState: f.state,
      shareCreatedAtMs: f.copiedAtMs,
    });
    await f.coordinator.restoreShareTrackingSelection();
    teardown(f.coordinator);
    f.timers.runUntilIdle();
    assert.deepEqual(
      f.statuses.map((status) => status.classification),
      ['pending', 'cancelled'],
      'an abandoned pending watch publishes the clear event exactly once',
    );
    f.coordinator.destroy();
  }
});

test('tracking resolver false and rejection stay source-unavailable while AbortError stays cancelled', async () => {
  const run = async (resolveTrackingRestoreTarget, { signal = null } = {}) => {
    const manager = productionManager({
      flights: { resolveTrackingRestoreTarget },
    });
    await manager.setEnabled('flights', true, { origin: 'scene' });
    return manager.resolveLayerTrackingTarget('flights', 'abc123', {
      origin: 'share-restore',
      signal,
    });
  };

  const semanticFalse = await run(() => false);
  assert.equal(semanticFalse.status, 'source-unavailable');

  const rejected = await run(() =>
    Promise.reject(new Error('feed unavailable')),
  );
  assert.equal(rejected.status, 'source-unavailable');
  assert.equal(rejected.reason, 'feed unavailable');

  const abortError = new Error('restore cancelled');
  abortError.name = 'AbortError';
  const cancelled = await run(() => Promise.reject(abortError));
  assert.equal(cancelled.status, 'cancelled');
  assert.equal(cancelled.errorClass, 'AbortError');
});

test('late target resolution after coordinator destroy cannot clear state or publish status', async () => {
  const resolution = deferred();
  const statuses = [];
  const storage = memoryStorage();
  const manager = productionManager({
    flights: {
      resolveTrackingRestoreTarget: () => resolution.promise,
    },
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['flights'];
  state.options.flights = {
    ...state.options.flights,
    selectedFlightsTrackingId: 'stale001',
  };
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage,
    onTrackingRestoreStatus: (status) => statuses.push(status),
  });
  await coordinator.start({ shareLayerState: state });
  const restore = coordinator.restoreShareTrackingSelection();
  coordinator.destroy();
  resolution.resolve({ status: 'missing' });
  const result = await restore;

  assert.equal(result.status, 'cancelled');
  assert.equal(statuses.length, 0);
  assert.equal(storage.writes.length, 0);
});

test('newer explicit tracked target cancels stale shared resolution without clearing the winner', async () => {
  const resolution = deferred();
  const storage = memoryStorage();
  const manager = productionManager({
    flights: {
      resolveTrackingRestoreTarget: async () => resolution.promise,
    },
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['flights'];
  state.options.flights = {
    ...state.options.flights,
    selectedFlightsTrackingId: 'stale001',
  };
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage,
  });
  await coordinator.start({ shareLayerState: state });
  const restore = coordinator.restoreShareTrackingSelection();
  manager.setLayerParams(
    'flights',
    {
      selectedFlightsTrackingId: 'newer002',
    },
    { origin: 'user' },
  );
  resolution.resolve({ status: 'missing' });
  const result = await restore;
  assert.equal(result.status, 'cancelled');
  assert.equal(
    coordinator.getDurableState().options.flights.selectedFlightsTrackingId,
    'newer002',
  );
  assert.equal(storage.writes.length, 1);
  coordinator.destroy();
});

// ---------------------------------------------------------------------------
// Share IDs and payloads are untrusted input and must be BOUNDED.
//
// A tracking ID is a transponder address, not free text. Identity is never
// truncated to fit: half an address is a different aircraft, not a shorter name
// for the same one, so an out-of-grammar ID is rejected outright and an
// oversized payload fails closed exactly like an unknown layer token.
// ---------------------------------------------------------------------------

test('oversized and out-of-grammar tracking IDs are rejected, never truncated', () => {
  const huge = 'a'.repeat(100_000);

  // Normalization (the durable-state door).
  const normalized = normalizeLayerState({
    enabledLayerIds: ['flights'],
    options: { flights: { selectedFlightsTrackingId: huge } },
  });
  assert.equal(
    normalized.options.flights.selectedFlightsTrackingId,
    null,
    'a 100k-char ID must be rejected, not stored',
  );

  // Decoding (the untrusted-URL door).
  const decoded = decodeLayerStateParams(
    new URLSearchParams([
      ['v', '2'],
      ['l', 'f'],
      ['lo', `f.t.${huge}`],
    ]),
  );
  assert.equal(decoded, null, 'an oversized lo payload fails closed');

  // A merely long-but-under-cap ID is still out of grammar, and rejected
  // WITHOUT taking the rest of the payload down with it.
  const longish = decodeLayerStateParams(
    new URLSearchParams([
      ['v', '2'],
      ['l', 'f'],
      ['lo', `f.e.1_f.t.${'b'.repeat(40)}`],
    ]),
  );
  assert.deepEqual(longish.enabledLayerIds, ['flights']);
  assert.equal(longish.options.flights.selectedFlightsTrackingId, null);

  for (const bad of [
    'ab cd',
    'ab/cd',
    '../../etc',
    'a'.repeat(17),
    '<script>',
    '',
  ]) {
    assert.equal(
      normalizeLayerState({
        enabledLayerIds: ['flights'],
        options: { flights: { selectedFlightsTrackingId: bad } },
      }).options.flights.selectedFlightsTrackingId,
      null,
      `out-of-grammar ID rejected: ${JSON.stringify(bad)}`,
    );
  }

  // Real addresses still round-trip untouched, including TIS-B forms.
  for (const good of ['aaa001', 'ae1fa4', '~ab1234', 'A1B2C3']) {
    const state = normalizeLayerState({
      enabledLayerIds: ['flights'],
      options: { flights: { selectedFlightsTrackingId: good } },
    });
    assert.equal(
      state.options.flights.selectedFlightsTrackingId,
      good.toLowerCase(),
    );
    const params = new URLSearchParams([['v', '2']]);
    encodeLayerStateParams(params, state);
    assert.equal(
      decodeLayerStateParams(params).options.flights.selectedFlightsTrackingId,
      good.toLowerCase(),
      `round-trip preserved: ${good}`,
    );
  }
});

test('an oversized enabled-layer field fails closed instead of decoding a prefix', () => {
  assert.equal(
    decodeLayerStateParams(
      new URLSearchParams([
        ['v', '2'],
        ['l', 'f.'.repeat(5_000)],
      ]),
    ),
    null,
  );
});

// ---------------------------------------------------------------------------
// The pending watch and the LAYER's deferred-restore latch are two halves of
// one mechanism and must die together.
//
// Aborting only the restore controller was a no-op by the time the watch
// existed (the controller has already settled), so the orphaned timer went on
// to announce "Shared … unavailable" at its deadline — a verdict about work
// nothing was attempting any more. Both paths below cancel the module latch in
// production: an explicit parameter replacement, and the owner layer going
// away (at any origin, including a programmatic disable).
// ---------------------------------------------------------------------------

test('an explicit parameter change revokes the pending watch, not just its controller', async () => {
  const f = pendingTrackingFixture();
  await f.coordinator.start({
    shareLayerState: f.state,
    shareCreatedAtMs: f.copiedAtMs,
  });
  await f.coordinator.restoreShareTrackingSelection();
  assert.deepEqual(
    f.statuses.map((status) => status.classification),
    ['pending'],
  );

  // The operator changes an unrelated Flights option. Production cancels the
  // module latch on exactly this event, so nothing is restoring any more.
  await f.manager.setLayerParams(
    'flights',
    { irBoost: true },
    { origin: 'user' },
  );
  f.timers.runUntilIdle();

  assert.deepEqual(
    f.statuses.map((status) => status.classification),
    ['pending', 'cancelled'],
    'a revoked restore clears progress without announcing a terminal failure',
  );
  f.coordinator.destroy();
});

test('the owner layer going away revokes the pending watch at any origin', async () => {
  for (const origin of ['programmatic', 'user']) {
    const f = pendingTrackingFixture();
    await f.coordinator.start({
      shareLayerState: f.state,
      shareCreatedAtMs: f.copiedAtMs,
    });
    await f.coordinator.restoreShareTrackingSelection();
    assert.deepEqual(
      f.statuses.map((status) => status.classification),
      ['pending'],
    );

    await f.manager.setEnabled('flights', false, { origin });
    f.timers.runUntilIdle();

    assert.deepEqual(
      f.statuses.map((status) => status.classification),
      ['pending', 'cancelled'],
      `a disabled owner layer clears progress without a terminal failure (origin=${origin})`,
    );
    f.coordinator.destroy();
  }
});

test('wind appearance shares round trip while old links retain weather defaults', () => {
  const state = normalizeLayerState({
    enabledLayerIds: ['wind'],
    options: {
      wind: { model: 'ifs', overlay: 'pressure', units: 'mph', paused: true },
    },
  });
  assert.deepEqual(
    decodeLayerStateParams(new URLSearchParams(encode(state))).options.wind,
    { model: 'ifs', overlay: 'pressure', units: 'mph', paused: true },
  );
  const defaults = createDefaultLayerState().options.wind;
  assert.deepEqual(defaults, {
    model: 'gfs',
    overlay: 'none',
    units: 'km/h',
    paused: false,
  });
  const legacy = decodeLayerStateParams(new URLSearchParams('v=2&l=k'));
  assert.equal(
    legacy.options.wind.overlay,
    'speed',
    'old links retain their authored field',
  );
  assert.equal(
    decodeLayerStateParams(
      new URLSearchParams(encode(createDefaultLayerState())),
    ).options.wind.overlay,
    'none',
    'new default is encoded explicitly',
  );
  const old = normalizeLayerState({ options: { wind: { model: 'ifs' } } });
  assert.deepEqual(old.options.wind, { ...defaults, model: 'ifs' });
  const invalid = normalizeLayerState({
    options: {
      wind: {
        model: 'unknown',
        overlay: 'clouds',
        units: '<script>',
        paused: 'yes',
      },
    },
  });
  assert.deepEqual(invalid.options.wind, defaults);
});

test('observed weather round trips product and presets without persisting historical playback', () => {
  const state = normalizeLayerState({
    enabledLayerIds: ['weather-radar', 'weather-satellite'],
    options: {
      'weather-radar': { opacity: 'light', play: true },
      'weather-satellite': {
        product: 'clouds',
        opacity: 'light',
        infrared: 'filtered',
        step: -1,
      },
    },
  });
  const params = new URLSearchParams(encode(state));
  const decoded = decodeLayerStateParams(params);
  assert.deepEqual(decoded, state);
  assert.equal(state.options['weather-satellite'].product, 'clouds');
  assert.equal(state.options['weather-satellite'].opacity, 'light');
  assert.equal(state.options['weather-satellite'].infrared, 100);
  assert.equal(Object.hasOwn(state.options['weather-radar'], 'play'), false);
});

test('satellite filter strength percentages round-trip and legacy mode codes remain readable', () => {
  const state = normalizeLayerState({
    enabledLayerIds: ['weather-satellite'],
    options: { 'weather-satellite': { infrared: 53, opacity: 'light' } },
  });
  const params = encodeLayerStateParams(
    new URLSearchParams([['v', '2']]),
    state,
  );
  assert.deepEqual(decodeLayerStateParams(params), state);
  assert.equal(state.options['weather-satellite'].infrared, 53);
  assert.equal(state.options['weather-satellite'].opacity, 'light');
  for (const [legacy, expected] of [
    ['f', 100],
    ['a', 0],
  ]) {
    const decoded = decodeLayerStateParams(
      new URLSearchParams(`v=2&l=o&lo=o.i.${legacy}`),
    );
    assert.equal(decoded.options['weather-satellite'].infrared, expected);
  }
  for (const [legacy, expected] of [
    ['filtered', 100],
    ['full', 0],
  ]) {
    const normalized = normalizeLayerState({
      enabledLayerIds: ['weather-satellite'],
      options: { 'weather-satellite': { infrared: legacy } },
    });
    assert.equal(normalized.options['weather-satellite'].infrared, expected);
  }
  const invalid = normalizeLayerState({
    enabledLayerIds: ['weather-satellite'],
    options: { 'weather-satellite': { infrared: 101 } },
  });
  assert.equal(invalid.options['weather-satellite'].infrared, 100);
});

test('satellite cloud filter round trips and invalid or absent values default to Clouds only', () => {
  for (const [infrared, expected] of [
    ['full', 0],
    ['filtered', 100],
    [53, 53],
    [undefined, 100],
    ['invalid', 100],
  ]) {
    const state = normalizeLayerState({
      enabledLayerIds: ['weather-satellite'],
      options: {
        'weather-satellite': {
          infrared,
          product: 'clouds',
          step: -1,
          play: true,
        },
      },
    });
    assert.deepEqual(
      decodeLayerStateParams(new URLSearchParams(encode(state))),
      state,
    );
    assert.equal(state.options['weather-satellite'].infrared, expected);
    assert.equal(
      Object.hasOwn(state.options['weather-satellite'], 'step'),
      false,
    );
    assert.equal(
      Object.hasOwn(state.options['weather-satellite'], 'play'),
      false,
    );
  }
});

// Recent Imagery (`1`): the box travels as four integers at degrees × 100000,
// the two days as product letter + compact date, the split as a percent.
const imageryOptions = (lo) =>
  decodeLayerStateParams(
    new URLSearchParams([
      ['v', '2'],
      ['l', '1'],
      ['lo', lo],
    ]),
  ).options['recent-imagery'];

test('recent-imagery box, days, mode, split and overview toggle round-trip under token 1; defaults stay out of the URL', () => {
  const entry = LAYER_STATE_REGISTRY.find((row) => row.id === 'recent-imagery');
  assert.deepEqual(
    [entry.token, entry.disposition, entry.optionOwner],
    ['1', 'enabled+options', 'recent-imagery'],
  );
  assert.deepEqual(createDefaultLayerState().options['recent-imagery'], {
    west: null,
    south: null,
    east: null,
    north: null,
    a: null,
    b: null,
    mode: 0,
    split: 50,
    viirs: false,
  });
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['recent-imagery', 'flights'];
  state.options['recent-imagery'] = {
    west: -9781235,
    south: -3020000,
    east: -9770000,
    north: 3040000,
    a: 'S30:2026-09-18',
    b: 'L30:2026-09-10',
    mode: 2,
    split: 37,
    viirs: true,
  };
  const encoded = encode(state);
  assert.ok(
    encoded.includes(
      '1.w.-9781235_1.s.-3020000_1.e.-9770000_1.n.3040000_1.a.S20260918_1.b.L20260910_1.m.2_1.p.37_1.v.1',
    ),
    encoded,
  );
  const decoded = decodeLayerStateParams(new URLSearchParams(encoded));
  assert.deepEqual(
    decoded.options['recent-imagery'],
    state.options['recent-imagery'],
  );
  assert.deepEqual(decoded.options.flights, state.options.flights);
  const bare = createDefaultLayerState();
  bare.enabledLayerIds = ['recent-imagery'];
  assert.doesNotMatch(
    new URLSearchParams(encode(bare)).get('lo') || '',
    /(^|_)1\./,
  );
  // The codec is calendar-only: a link decodes the same whenever it is opened.
  assert.equal(imageryOptions('1.a.L19991231').a, 'L30:1999-12-31');
  assert.equal(imageryOptions('1.b.V20991231').b, 'VIIRS:2099-12-31');
});

test('recent-imagery rejects impossible days and out-of-range edges instead of rolling or clamping them', () => {
  for (const bad of [
    'S20260230',
    'L20261301',
    'S20260900',
    'X20260918',
    's20260918',
    'S2026091',
    'S30:2026-09-18',
  ])
    assert.equal(imageryOptions(`1.a.${bad}`).a, null, bad);
  assert.equal(
    imageryOptions('1.b.S20240229').b,
    'S30:2024-02-29',
    'a real leap day',
  );
  assert.equal(imageryOptions('1.b.S20230229').b, null);
  const mixed = imageryOptions('1.a.S20260230_1.b.V20260921_1.p.80');
  assert.deepEqual(
    [mixed.a, mixed.b, mixed.split],
    [null, 'VIIRS:2026-09-21', 80],
  );
  for (const bad of [
    '1.w.18000001',
    '1.n.8505111',
    '1.s.-8505111',
    '1.w.1.5',
    '1.w.abc',
    '1.w.1234567890',
  ]) {
    const field = { w: 'west', s: 'south', n: 'north' }[bad.split('.')[1]];
    assert.equal(imageryOptions(bad)[field], null, bad);
  }
  assert.equal(imageryOptions('1.w.18000000').west, 18000000);
  assert.equal(imageryOptions('1.p.101').split, 50);
  assert.equal(imageryOptions('1.m.1').mode, 1);
  for (const bad of ['1.m.3', '1.m.-1', '1.m.x'])
    assert.equal(imageryOptions(bad).mode, 0, bad);
  assert.deepEqual(
    normalizeLayerState({
      enabledLayerIds: ['recent-imagery'],
      options: {
        'recent-imagery': {
          a: 'S30:2026-02-30',
          b: ' L30:2026-09-10 ',
          split: 150,
          west: 'abc',
          north: -8505110,
        },
      },
    }).options['recent-imagery'],
    {
      west: null,
      south: null,
      east: null,
      north: -8505110,
      a: null,
      b: 'L30:2026-09-10',
      mode: 0,
      split: 50,
      viirs: false,
    },
  );
  // An oversized payload fails closed at the shared 512-character cap.
  const long = '1.a.S20260918_'.repeat(40);
  assert.ok(imageryOptions(long.slice(0, 512)));
  assert.equal(
    decodeLayerStateParams(
      new URLSearchParams([
        ['v', '2'],
        ['l', '1'],
        ['lo', long.slice(0, 513)],
      ]),
    ),
    null,
  );
});

test('the recent-imagery split is share-link only: never stored locally, and a stored value reads as the default', () => {
  const state = createDefaultLayerState();
  state.enabledLayerIds = ['recent-imagery'];
  state.options['recent-imagery'] = {
    a: 'S30:2026-09-18',
    split: 8,
    viirs: true,
  };
  assert.ok(encode(state).includes('1.p.8'));
  const stored = JSON.parse(serializeStoredLayerState(state)).o[
    'recent-imagery'
  ];
  assert.deepEqual(
    [stored.split, stored.a, stored.viirs],
    [50, 'S30:2026-09-18', true],
  );
  const previous = JSON.stringify({
    v: 2,
    l: ['recent-imagery'],
    o: { 'recent-imagery': { split: 8 } },
  });
  assert.equal(
    parseStoredLayerState(previous).options['recent-imagery'].split,
    50,
  );
});

test('GNSS interference uses digit 3 without colliding with other digit tokens', () => {
  const decoded = decodeLayerStateParams(new URLSearchParams('v=2&l=3.2.1'));
  assert.deepEqual(decoded.enabledLayerIds, [
    'fire-perimeters',
    'gnss-integrity',
    'recent-imagery',
  ]);
  assert.equal(
    LAYER_STATE_REGISTRY.find(({ id }) => id === 'gnss-integrity').token,
    '3',
  );
  assert.deepEqual(
    decodeLayerStateParams(new URLSearchParams(encode(decoded))),
    decoded,
  );
});

test('fire perimeters uses digit 2 without colliding with wind or recent imagery', () => {
  const decoded = decodeLayerStateParams(new URLSearchParams('v=2&l=2.k.1'));
  assert.deepEqual(decoded.enabledLayerIds, [
    'fire-perimeters',
    'recent-imagery',
    'wind',
  ]);
  assert.equal(
    LAYER_STATE_REGISTRY.find(({ id }) => id === 'fire-perimeters').token,
    '2',
  );
  assert.deepEqual(
    decodeLayerStateParams(new URLSearchParams(encode(decoded))),
    decoded,
  );
});

function enabledLayerParam(sink) {
  return new URLSearchParams(encode(sink.provider())).get('l');
}

test('Clear All drops a saved layer a context mode had already switched off', async () => {
  const manager = productionManager();
  const storage = memoryStorage();
  const sink = shareSink();
  const coordinator = new LayerStateCoordinator(manager, sink, { storage });
  await coordinator.start();
  await manager.setEnabled('earthquakes', true, { origin: 'user' });
  await manager.setEnabled('flights', true, { origin: 'user' });
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, [
    'earthquakes',
    'flights',
  ]);
  // Context isolation is a temporary, passive takeover: the saved choice stays.
  await manager.setEnabled('earthquakes', false, { origin: 'programmatic' });
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, [
    'earthquakes',
    'flights',
  ]);

  const updatesBefore = sink.updates;
  const result = await manager.clearSelectedLayers({ origin: 'user' });
  assert.deepEqual(result.targetIds, ['flights']);
  assert.ok(sink.updates > updatesBefore, 'the URL is told to refresh');
  assert.deepEqual([...manager.getEnabledLayerIds()], []);
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, []);
  assert.equal(enabledLayerParam(sink), '', 'the URL carries no layers');
  assert.deepEqual(
    parseStoredLayerState(storage.getItem(LAYER_STATE_STORAGE_KEY))
      .enabledLayerIds,
    [],
    'a reload restores nothing',
  );
  coordinator.destroy();
});

test('Clear All drops a saved layer a dependency release superseded mid-batch', async () => {
  let manager;
  manager = productionManager({
    // Contacts-style owner: its own teardown releases a borrowed dependency
    // without awaiting it, which supersedes Clear All's turn for that layer.
    'satellites': {
      disable() {
        void manager.setEnabled('flights', false, { origin: 'programmatic' });
        return true;
      },
    },
  });
  const storage = memoryStorage();
  const sink = shareSink();
  const coordinator = new LayerStateCoordinator(manager, sink, { storage });
  await coordinator.start();
  await manager.setEnabled('earthquakes', true, { origin: 'user' });
  await manager.setEnabled('flights', true, { origin: 'user' });
  await manager.setEnabled('satellites', true, { origin: 'user' });

  const result = await manager.clearSelectedLayers({ origin: 'user' });
  assert.equal(
    result.items.find((item) => item.id === 'flights')?.superseded,
    true,
    'the fixture reproduces the superseded flights turn',
  );
  assert.deepEqual([...manager.getEnabledLayerIds()], []);
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, []);
  assert.equal(enabledLayerParam(sink), '');
  coordinator.destroy();
});

test('Clear All keeps a layer a newer explicit request turned back on', async () => {
  const manager = productionManager();
  const sink = shareSink();
  const coordinator = new LayerStateCoordinator(manager, sink, {
    storage: memoryStorage(),
  });
  await coordinator.start();
  await manager.setEnabled('earthquakes', true, { origin: 'user' });
  await manager.setEnabled('flights', true, { origin: 'user' });
  const clearing = manager.clearSelectedLayers({ origin: 'user' });
  // A direct request issued during the batch owns its layer.
  const reenable = manager.setEnabled('earthquakes', true, { origin: 'user' });
  await Promise.all([clearing, reenable]);
  assert.deepEqual([...manager.getEnabledLayerIds()], ['earthquakes']);
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, [
    'earthquakes',
  ]);
  assert.equal(enabledLayerParam(sink), 'e');
  coordinator.destroy();
});

test('a passive clear never rewrites saved layers', async () => {
  const manager = productionManager();
  const storage = memoryStorage();
  const coordinator = new LayerStateCoordinator(manager, shareSink(), {
    storage,
  });
  await coordinator.start();
  await manager.setEnabled('flights', true, { origin: 'user' });
  await manager.setEnabled('flights', false, { origin: 'programmatic' });
  const writes = storage.writes.length;
  await manager.clearSelectedLayers({ origin: 'programmatic' });
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, ['flights']);
  assert.equal(storage.writes.length, writes);
  coordinator.destroy();
});

test('Clear All cancels a saved restore still waiting to start', async () => {
  const gate = deferred();
  const manager = productionManager();
  const sink = shareSink();
  const coordinator = new LayerStateCoordinator(manager, sink, {
    storage: memoryStorage(),
    restoreGate: gate.promise,
  });
  const params = new URLSearchParams('v=2&l=e.f');
  const restore = coordinator.start({
    shareLayerState: decodeLayerStateParams(params),
  });
  await manager.clearSelectedLayers({ origin: 'user' });
  assert.deepEqual(coordinator.getDurableState().enabledLayerIds, []);
  gate.resolve();
  const results = await restore;
  for (const id of ['earthquakes', 'flights']) {
    assert.equal(results.find((result) => result.layerId === id).succeeded, false);
  }
  assert.deepEqual([...manager.getEnabledLayerIds()], []);
  assert.equal(enabledLayerParam(sink), '');
  coordinator.destroy();
});
