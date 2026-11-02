import test from 'node:test';
import assert from 'node:assert/strict';
import { createViewActions } from './viewActions.js';

function fixture({ tracked = [] } = {}) {
  const calls = [];
  const flights = {
    findByQuery: (q) => (q === 'ABC123' ? { icao24: 'abc123' } : null),
    trackById: (id, options) => {
      calls.push(['trackById', id, options.origin]);
      return true;
    },
    getTrackedInfo: () => (tracked.includes('flights') ? {} : null),
    stopTracking: () => {
      calls.push(['stopTracking']);
      return true;
    },
  };
  const enabled = new Set(['flights']);
  const dataManager = {
    layers: new Map([
      ['flights', { module: flights }],
      ['earthquakes', { module: {} }],
    ]),
    isEnabled: (id) => enabled.has(id),
    setEnabled: async (id, on) => {
      if (on) enabled.add(id);
      else enabled.delete(id);
      return true;
    },
    setLayerParams: (id, params) => {
      calls.push(['setLayerParams', id, params]);
      return true;
    },
  };
  const styleManager = {
    runImmediateNavigation: (noun, navigate) => navigate(),
    setStyle: (style) => calls.push(['setStyle', style]),
    setMapStack: async (stack) => ({ ok: true, stack }),
  };
  const annotations = {
    annotate: async (specs) => ({
      drawn: specs.length,
      failed: 0,
      results: [],
    }),
    clear: () => calls.push(['clear']),
  };
  const viewer = { trackedEntity: { id: 'x' } };
  const run = createViewActions({
    viewer,
    dataManager,
    styleManager,
    annotations,
  });
  return { run, calls, enabled, viewer };
}

test('layers are switched through the data manager and verified', async () => {
  const { run, enabled } = fixture();
  assert.equal(
    (
      await run('set_layer_visibility', {
        layerId: 'earthquakes',
        enabled: true,
      })
    ).ok,
    true,
  );
  assert.ok(enabled.has('earthquakes'));
  await assert.rejects(
    run('set_layer_visibility', { layerId: 'nope', enabled: true }),
    /Unknown data layer/,
  );
});

test('an aircraft is found and followed in an enabled layer only', async () => {
  const { run, calls } = fixture();
  const result = await run('track_entity', {
    query: 'ABC123',
    layerId: 'flights',
  });
  assert.equal(result.ok, true);
  assert.deepEqual(calls.at(-1), ['trackById', 'abc123', 'tool']);
  assert.equal((await run('track_entity', { query: 'nothing' })).ok, false);
});

test('stop_tracking releases tracked layers and the viewer', async () => {
  const { run, viewer } = fixture({ tracked: ['flights'] });
  const result = await run('stop_tracking', {});
  assert.equal(result.ok, true);
  assert.deepEqual(result.released, ['flights']);
  assert.equal(viewer.trackedEntity, undefined);
});

test('annotations are bounded and unknown actions are refused', async () => {
  const { run } = fixture();
  assert.equal(
    (
      await run('annotate_map', {
        annotations: [{ type: 'pin', target: 'Paris' }],
      })
    ).drawn,
    1,
  );
  assert.equal(
    (await run('annotate_map', { annotations: new Array(25).fill({}) })).ok,
    false,
  );
  assert.equal((await run('clear_annotations', {})).ok, true);
  await assert.rejects(run('control_cockpit', {}), /Unknown view action/);
});
