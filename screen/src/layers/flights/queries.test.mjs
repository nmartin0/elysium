import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as Cesium from 'cesium';
import { createQueries } from './queries.js';
import { createRendering } from './rendering.js';

function fixture() {
  const info = {
    callsign: ' TEST123 ',
    registration: ' N123 ',
    altitude: 1000,
  };
  const bb = { show: true, position: new Cesium.Cartesian3(1, 2, 3) };
  const flightState = {
    feed: {},
    _billboardCollection: { show: true },
    _billboards: new Map([['abc123', bb]]),
    _detectionObjects: new Map(),
    records: { data: new Map([['abc123', info]]) },
  };
  let formats = 0;
  const services = {
    militaryRegistry: {},
    camera: {},
    focus: {},
    recession: {},
    labels: {
      formatFlightLevel: (altitude) => {
        formats++;
        return String(altitude);
      },
    },
  };
  const parts = {
    testing: {},
    tracking: {},
    motion: { _trackedDisplayCached: () => null },
  };
  parts.rendering = createRendering({ flightState, services, parts });
  const queries = createQueries({ flightState, services, parts }).methods;
  return { flightState, info, bb, parts, queries, formats: () => formats };
}

test('candidate text follows in-place enrichment without freezing identity or positions', () => {
  const f = fixture();
  const [first] = f.queries.getDetectableObjects();
  assert.equal(first.id, 'TEST123');
  assert.equal(first.sourceId, 'abc123');
  f.bb.position = new Cesium.Cartesian3(4, 5, 6);
  assert.equal(f.queries.getDetectableObjects()[0], first);
  assert.equal(first.position, f.bb.position);
  assert.equal(f.formats(), 1);
  f.info.callsign = ' NEW456 ';
  assert.equal(f.queries.getDetectableObjects()[0].id, 'NEW456');
  f.info.callsign = '   ';
  assert.equal(f.queries.getDetectableObjects()[0].id, 'N123');
  f.info.registration = ' N456 ';
  f.info.altitude = 2000;
  assert.equal(f.queries.getDetectableObjects()[0].id, 'N456');
  assert.equal(first.metric, '2000');
  assert.equal(f.formats(), 2);
  f.flightState.records.data.set('abc123', { ...f.info });
  assert.equal(f.queries.getDetectableObjects()[0], first);
  f.flightState.records.data.delete('abc123');
  assert.equal(f.queries.getDetectableObjects()[0].id, 'abc123');
  assert.equal(first.sourceId, 'abc123');
});

test('unchanged candidate text is normalized once across paints', (t) => {
  const f = fixture();
  const trim = String.prototype.trim;
  let calls = 0;
  t.mock.method(String.prototype, 'trim', function () {
    if (String(this) === ' TEST123 ') calls++;
    return trim.call(this);
  });
  for (let i = 0; i < 20; i++) f.queries.getDetectableObjects();
  assert.equal(calls, 1);
});

test('a hidden sprite is not a candidate until it is shown again', () => {
  const f = fixture();
  const [candidate] = f.queries.getDetectableObjects();
  f.bb.show = false;
  assert.deepEqual(f.queries.getDetectableObjects(), []);
  f.bb.show = true;
  assert.equal(f.queries.getDetectableObjects()[0], candidate);
  assert.equal(candidate.position, f.bb.position);
});

test('the tracked candidate follows the cached display position and skips its label', () => {
  const f = fixture();
  f.flightState._trackedIcao = 'abc123';
  let anchor = new Cesium.Cartesian3(10, 20, 30);
  f.parts.motion._trackedDisplayCached = () => anchor;
  f.bb.show = false;
  const [candidate] = f.queries.getDetectableObjects();
  assert.equal(candidate.position, anchor);
  assert.equal(candidate.skipLabel, true);
  anchor = new Cesium.Cartesian3(40, 50, 60);
  assert.equal(f.queries.getDetectableObjects()[0].position, anchor);
  f.parts.motion._trackedDisplayCached = () => null;
  assert.equal(f.queries.getDetectableObjects()[0].position, f.bb.position);
});
