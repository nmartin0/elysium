import test from 'node:test';
import assert from 'node:assert/strict';
import * as Cesium from 'cesium';
import { gstime } from 'satellite.js';
import { createModel } from '../layers/launches/model.js';
import rocketLaunchesLayer, {
  _setRocketMissionOverlayHostForTest,
  _setSelectedRocketMissionForTest,
  bindMissionRosterItemKeyboardPreview,
  captureMissionRosterFocus,
  compactLaunchSiteName,
  createMissionRosterPreviewOwnership,
  createRocketMissionElementOverlayEntry,
  createRocketMissionMarkerOverlayEntry,
  formatMissionEventTime,
  LAUNCH_PAD_ZONE_RADIUS_M,
  launchPadZoneVisible,
  launchStatusAllowsOrbit,
  missionAnchorHorizonVisible,
  missionAnchorVisible,
  missionHoverPreviewRange,
  missionDataCompleteness,
  missionMarkerColor,
  missionPathPresentation,
  missionRosterEntries,
  missionZoomPitch,
  normalizeRocketLaunches,
  parseMissionDurationSeconds,
  resolveMissionRosterPreviewLaunch,
  restoreMissionRosterFocus,
  ROCKET_MISSION_AMBIENT_OVERLAY_COHORT_LIMIT,
  ROCKET_MISSION_AMBIENT_OVERLAY_COLLISION_CAPACITY,
  ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID,
  ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID,
  ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_OPTIONS,
  satelliteParamsAfterSpaceMissions,
  satelliteParamsForSpaceMissions,
  shouldRetryAfterActiveTle,
  selectRocketMissionMarkerOverlayCohort,
} from './rocketLaunches.js';
import {
  findSatelliteOrbitTrackInTle,
  orbitFrameModelMatrix,
  satelliteCatalogModeChanged,
  scoreSatelliteNameMatch,
} from './satellites.js';

const NOW = new Date('2026-07-27T00:00:00Z');

test('mission anchors are hidden behind Earth and restored on the facing hemisphere', () => {
  const camera = Cesium.Cartesian3.fromDegrees(-75, 20, 18000000);
  const front = Cesium.Cartesian3.fromDegrees(-75, 20);
  const rear = Cesium.Cartesian3.fromDegrees(105, -20);
  assert.equal(missionAnchorHorizonVisible(camera, front), true);
  assert.equal(missionAnchorHorizonVisible(camera, rear), false);
});

test('selecting one mission hides every other front-facing launch anchor', () => {
  const camera = Cesium.Cartesian3.fromDegrees(-75, 20, 18000000);
  const first = Cesium.Cartesian3.fromDegrees(-75, 20);
  const second = Cesium.Cartesian3.fromDegrees(-80, 25);

  assert.equal(missionAnchorVisible(camera, first, 'first', null), true);
  assert.equal(missionAnchorVisible(camera, second, 'second', null), true);
  assert.equal(missionAnchorVisible(camera, first, 'first', 'first'), true);
  assert.equal(missionAnchorVisible(camera, second, 'second', 'first'), false);
});

test('transitions selected mission zoom from globe nadir to an oblique site view', () => {
  assert.ok(Math.abs(missionZoomPitch(5000000) - Cesium.Math.toRadians(-90)) < 1e-10);
  assert.ok(Math.abs(missionZoomPitch(180000) - Cesium.Math.toRadians(-42)) < 1e-10);
  const midPitch = Cesium.Math.toDegrees(missionZoomPitch(1000000));
  assert.ok(midPitch < -42 && midPitch > -90);
});

test('restores the complete standalone Satellite style after mission mode', () => {
  const standalone = {
    catalog: 'core',
    showPoints: true,
    showOrbits: true,
    labelDensity: 'operator',
  };
  assert.deepEqual(satelliteParamsForSpaceMissions(standalone), {
    ...standalone,
    catalog: 'dense',
    showPoints: false,
    showOrbits: false,
  });
  assert.deepEqual(satelliteParamsAfterSpaceMissions(standalone), standalone);
  assert.deepEqual(satelliteParamsAfterSpaceMissions(null), {
    catalog: 'core',
    showPoints: true,
    showOrbits: true,
  });
});

test('suppresses every orbital representation for failed launches', () => {
  assert.equal(launchStatusAllowsOrbit('Launch Successful'), true);
  assert.equal(launchStatusAllowsOrbit('Go for Launch'), true);
  assert.equal(launchStatusAllowsOrbit('Launch Failure'), false);
  assert.equal(launchStatusAllowsOrbit('Partial Failure'), false);
  assert.equal(launchStatusAllowsOrbit('Failed'), false);
});

test('keeps failed-launch mission details truthful without inventing paths', () => {
  assert.deepEqual(missionPathPresentation({
    status: 'Launch Failure',
    orbit: { name: 'Geostationary Transfer Orbit' },
    trajectory: [],
  }), {
    orbit: 'PLANNED · Geostationary Transfer Orbit',
    ascent: null,
  });
  assert.deepEqual(missionPathPresentation({
    status: 'Partial Failure',
    orbit: { name: 'Low Earth Orbit' },
    trajectory: [
      { latitude: 28.5, longitude: -80.5 },
      { latitude: 29, longitude: -79.5 },
    ],
  }), {
    orbit: 'PLANNED · Low Earth Orbit',
    ascent: 'SUPPLIED TRAJECTORY POINTS',
  });
});

test('bounds the post-TLE refresh to one resolved-catalog rebuild', () => {
  const base = {
    enabled: true,
    retryCount: 0,
    activeTleText: 'ACTIVE TLE',
    renderedTleText: null,
  };
  assert.equal(shouldRetryAfterActiveTle(base), true);
  assert.equal(shouldRetryAfterActiveTle({ ...base, retryCount: 1 }), false);
  assert.equal(shouldRetryAfterActiveTle({ ...base, activeTleText: null }), false);
  assert.equal(shouldRetryAfterActiveTle({ ...base, renderedTleText: 'ACTIVE TLE' }), false);
  assert.equal(shouldRetryAfterActiveTle({ ...base, enabled: false }), false);
});

test('uses the core GMST frame transform for mission orbit primitives', () => {
  const bakeDate = new Date('2026-07-20T10:00:00Z');
  const nowDate = new Date('2026-07-20T10:10:00Z');
  const gmstAtBake = gstime(bakeDate);
  const matrix = orbitFrameModelMatrix(gmstAtBake, nowDate);
  const actual = Cesium.Matrix4.multiplyByPoint(
    matrix,
    Cesium.Cartesian3.UNIT_X,
    new Cesium.Cartesian3(),
  );
  const expectedAngle = -(gstime(nowDate) - gmstAtBake);
  assert.ok(Math.abs(actual.x - Math.cos(expectedAngle)) < 1e-12);
  assert.ok(Math.abs(actual.y - Math.sin(expectedAngle)) < 1e-12);
  assert.ok(Math.abs(actual.z) < 1e-12);
});

test('treats an already-active Satellite catalog mode as idempotent', () => {
  assert.equal(satelliteCatalogModeChanged('dense', 'dense'), false);
  assert.equal(satelliteCatalogModeChanged('core', 'core'), false);
  assert.equal(satelliteCatalogModeChanged('core', 'dense'), true);
  assert.equal(satelliteCatalogModeChanged('dense', 'core'), true);
  assert.equal(satelliteCatalogModeChanged('core', undefined), false);
});

test('shows launch-pad zone only for the selected close-range mission', () => {
  assert.equal(LAUNCH_PAD_ZONE_RADIUS_M, 500);
  const closeSelected = {
    layerActive: true,
    selectedLaunchId: 'mission-a',
    launchId: 'mission-a',
    cameraHeightM: 12000,
    cameraDistanceM: 14000,
  };
  assert.equal(launchPadZoneVisible(closeSelected), true);
  assert.equal(launchPadZoneVisible({ ...closeSelected, layerActive: false }), false);
  assert.equal(launchPadZoneVisible({ ...closeSelected, selectedLaunchId: 'mission-b' }), false);
  assert.equal(launchPadZoneVisible({ ...closeSelected, cameraHeightM: 120001 }), false);
  assert.equal(launchPadZoneVisible({ ...closeSelected, cameraDistanceM: 180001 }), false);
});

test('orders mission roster newest-first without losing navigation indices', () => {
  const entries = missionRosterEntries([
    { id: 'oldest', launchTime: '2026-07-01T00:00:00Z' },
    { id: 'newest', launchTime: '2026-07-20T00:00:00Z' },
    { id: 'middle', launchTime: '2026-07-10T00:00:00Z' },
  ]);
  assert.deepEqual(entries.map((entry) => entry.launch.id), ['newest', 'middle', 'oldest']);
  assert.deepEqual(entries.map((entry) => entry.index), [1, 2, 0]);
});

test('prioritizes data-rich missions before newer sparse records', () => {
  const entries = missionRosterEntries([
    { id: 'rich', launchTime: '2026-07-01T00:00:00Z', provider: 'Agency', mission: 'Detailed mission', orbit: { name: 'LEO' }, payloads: [{ name: 'Payload' }], timeline: [{ name: 'Liftoff' }] },
    { id: 'sparse-new', launchTime: '2026-07-20T00:00:00Z' },
  ]);
  assert.ok(missionDataCompleteness(entries[0].launch) > missionDataCompleteness(entries[1].launch));
  assert.equal(entries[0].launch.id, 'rich');
});

test('preserves globe scale for roster hover previews', () => {
  assert.equal(missionHoverPreviewRange(18178265), 18178265);
  assert.equal(missionHoverPreviewRange(12000), 180000);
  assert.equal(missionHoverPreviewRange(Number.NaN), 5000000);
});

test('keyboard focus previews roster missions and clears without selecting them', () => {
  const calls = [];
  const ownership = createMissionRosterPreviewOwnership({
    preview: (index) => calls.push(['preview', index]),
    clear: () => calls.push(['clear']),
  });

  ownership.focus(2);
  ownership.blur(3);
  ownership.blur();

  assert.deepEqual(calls, [
    ['preview', 2],
    ['preview', 3],
    ['clear'],
  ]);
});

test('rendered mission row focus and blur drive the preview ownership controller', () => {
  const listeners = new Map();
  const calls = [];
  const button = {
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
  };
  const nextButton = {
    dataset: { missionRosterIndex: '4' },
    closest: () => nextButton,
  };
  const roster = { contains: (candidate) => candidate === nextButton };
  const ownership = {
    pointerEnter: (index) => calls.push(['pointer-enter', index]),
    pointerLeave: () => calls.push(['pointer-leave']),
    focus: (index) => calls.push(['focus', index]),
    blur: (index) => calls.push(['blur', index]),
  };

  bindMissionRosterItemKeyboardPreview(button, 2, ownership, roster);
  listeners.get('mouseenter')();
  listeners.get('mouseleave')();
  listeners.get('focus')();
  listeners.get('blur')({ relatedTarget: nextButton });
  listeners.get('blur')({ relatedTarget: null });

  assert.deepEqual(calls, [
    ['pointer-enter', 2],
    ['pointer-leave'],
    ['focus', 2],
    ['blur', 4],
    ['blur', null],
  ]);
});

test('leaving a hovered row for an internal roster gap restores keyboard preview', () => {
  const calls = [];
  const ownership = createMissionRosterPreviewOwnership({
    preview: (index) => calls.push(['preview', index]),
    clear: () => calls.push(['clear']),
  });

  ownership.focus(1);
  ownership.pointerEnter(0);
  ownership.pointerLeave();

  assert.deepEqual(calls, [
    ['preview', 1],
    ['preview', 0],
    ['preview', 1],
  ]);
});

test('mission roster refresh restores keyboard focus by stable mission identity after reorder', () => {
  const focused = {
    dataset: { missionRosterId: 'mission-b' },
    closest: () => focused,
  };
  let restored = false;
  const replacement = {
    dataset: { missionRosterId: 'mission-b' },
    focus: ({ preventScroll }) => { restored = preventScroll; },
  };
  const list = {
    contains: (candidate) => candidate === focused,
    querySelectorAll: () => [
      { dataset: { missionRosterId: 'mission-c' } },
      replacement,
      { dataset: { missionRosterId: 'mission-a' } },
    ],
  };

  const snapshot = captureMissionRosterFocus(list, focused);
  assert.deepEqual(snapshot, { launchId: 'mission-b' });
  assert.equal(restoreMissionRosterFocus(list, snapshot, null), 'restored');
  assert.equal(restored, true);
});

test('mission roster refresh continues after the list when the focused mission departed', () => {
  const focused = {
    dataset: { missionRosterId: 'departed' },
    closest: () => focused,
  };
  let continuationFocused = false;
  const list = {
    contains: (candidate) => candidate === focused,
    querySelectorAll: () => [{ dataset: { missionRosterId: 'remaining' } }],
  };
  const continuation = {
    focus: ({ preventScroll }) => { continuationFocused = preventScroll; },
  };

  const snapshot = captureMissionRosterFocus(list, focused);
  assert.equal(restoreMissionRosterFocus(list, snapshot, continuation), 'continued');
  assert.equal(continuationFocused, true);
});

test('pending mission preview resolves the current refreshed record by identity', () => {
  const stale = { id: 'mission-a', name: 'Stale' };
  const current = { id: 'mission-a', name: 'Current' };

  assert.equal(resolveMissionRosterPreviewLaunch([current], stale.id), current);
  assert.equal(resolveMissionRosterPreviewLaunch([], stale.id), null);
});

test('latest roster input owns preview and restores the remaining owner on leave', () => {
  const calls = [];
  const ownership = createMissionRosterPreviewOwnership({
    preview: (index) => calls.push(['preview', index]),
    clear: () => calls.push(['clear']),
  });

  ownership.pointerEnter(0);
  ownership.focus(1);
  ownership.blur();
  ownership.pointerLeave();

  assert.deepEqual(calls, [
    ['preview', 0],
    ['preview', 1],
    ['preview', 0],
    ['clear'],
  ]);
});

test('assigns distinct stable colors to mission operators', () => {
  assert.equal(missionMarkerColor({ provider: 'NASA', name: 'Science Flight' }).toCssColorString(), 'rgb(255,159,67)');
  assert.equal(missionMarkerColor({ provider: 'SpaceX', name: 'Starlink Group' }).toCssColorString(), 'rgb(76,201,240)');
  assert.equal(missionMarkerColor({ provider: 'Private Launch Co.', name: 'Test Flight' }).toCssColorString(), 'rgb(192,132,252)');
});

test('normalizes recent launches and preserves supplied trajectory/orbit data', () => {
  const launches = normalizeRocketLaunches({ results: [{
    id: 'recent-1',
    name: 'Test Flight',
    net: '2026-07-20T10:00:00Z',
    status: { name: 'Launch Successful' },
    pad: { name: 'Pad A', location: { name: 'Test Range', coordinates: '12.5,45.5' } },
    trajectory: [{ latitude: 45.5, longitude: 12.5, altitude: 0 }],
    timeline: [{ type: { abbrev: 'SECO-1' }, relative_time: 'PT8M40S' }],
    mission: { description: 'Payload test', orbit: { name: 'LEO' } },
  }] }, NOW);

  assert.equal(launches.length, 1);
  assert.equal(launches[0].lat, 45.5);
  assert.equal(launches[0].lon, 12.5);
  assert.equal(launches[0].orbit.name, 'LEO');
  assert.equal(launches[0].trajectory.length, 1);
  assert.equal(launches[0].timeline[0].offsetSeconds, 520);
});

test('uses Launch Library 2 pad latitude/longitude fields', () => {
  const launches = normalizeRocketLaunches({ results: [{
    id: 'pad-fields',
    net: '2026-07-20T10:00:00Z',
    pad: { latitude: '34.632', longitude: '-120.611', location: { name: 'Vandenberg' } },
  }] }, NOW);
  assert.equal(launches.length, 1);
  assert.equal(launches[0].lat, 34.632);
  assert.equal(launches[0].lon, -120.611);
});

test('null or blank pad coordinates stay unknown instead of becoming 0', () => {
  const base = { net: '2026-07-20T10:00:00Z' };
  for (const blank of [null, '', '  ', false]) {
    assert.deepEqual(
      normalizeRocketLaunches([{ ...base, id: 'blank', pad: { latitude: blank, longitude: blank } }], NOW),
      [],
    );
  }
});

test('null pad coordinates use the location fallback instead of 0,0', () => {
  const base = { net: '2026-07-20T10:00:00Z' };
  const [fallback] = normalizeRocketLaunches([{ ...base, id: 'fallback',
    pad: { latitude: null, longitude: null, location: { coordinates: '-80.6,28.6' } } }], NOW);
  assert.equal(fallback.lat, 28.6);
  assert.equal(fallback.lon, -80.6);
});

test('an undisclosed landing keeps top-level position and stage numbers unknown', () => {
  const base = { net: '2026-07-20T10:00:00Z' };
  const [launch] = normalizeRocketLaunches([{ ...base, id: 'landing', pad: { latitude: 1, longitude: 2 },
    rocket: { launcher_stage: [{ launcher_flight_number: null,
      landing: { attempt: true, latitude: null, longitude: null, downrange_distance: null,
        landing_location: { latitude: null, longitude: null } } }] } }], NOW);
  const [stage] = launch.recoveryStages;
  assert.equal(stage.lat, null);
  assert.equal(stage.lon, null);
  assert.equal(stage.downrangeKm, null);
  assert.equal(stage.flightNumber, null);
});

test('normalizes detailed payload and stage recovery records', () => {
  const launches = normalizeRocketLaunches({ results: [{
    id: 'recovery-details',
    name: 'Falcon 9 | Test Payload',
    net: '2026-07-20T10:00:00Z',
    pad: { latitude: '28.608', longitude: '-80.604', name: 'LC-39A' },
    rocket: {
      payloads: [{
        id: 501,
        destination: 'Low Earth Orbit',
        amount: 2,
        payload: {
          id: 91,
          name: 'TestSat',
          type: { name: 'Earth Observation Satellite' },
          manufacturer: { name: 'Example Space' },
          operator: { name: 'Example Operator' },
          mass: 420,
        },
      }],
      launcher_stage: [{
        id: 77,
        type: 'Core',
        reused: true,
        launcher_flight_number: 8,
        launcher: { serial_number: 'B1099' },
        landing: {
          attempt: true,
          success: true,
          downrange_distance: 610,
          type: { name: 'Autonomous Spaceport Drone Ship' },
          landing_location: {
            name: 'A Shortfall of Gravitas',
            latitude: '30.1',
            longitude: '-76.2',
          },
        },
      }],
    },
    mission: { orbit: { name: 'Low Earth Orbit' } },
  }] }, NOW);

  assert.equal(launches[0].payloads[0].name, 'TestSat');
  assert.equal(launches[0].payloads[0].amount, 2);
  assert.equal(launches[0].payloads[0].massKg, 420);
  assert.equal(launches[0].recoveryStages[0].name, 'Core · B1099');
  assert.equal(launches[0].recoveryStages[0].status, 'RECOVERED');
  assert.equal(launches[0].recoveryStages[0].downrangeKm, 610);
  assert.equal(launches[0].recoveryStages[0].lat, 30.1);
  assert.equal(launches[0].recoveryStages[0].lon, -76.2);
});

test('finiteCoordinate normalizes finite numbers and rejects non-numeric or non-finite inputs', () => {
  const model = createModel({});
  assert.equal(model.finiteCoordinate(42.5), 42.5);
  assert.equal(model.finiteCoordinate('28.5619'), 28.5619);
  assert.equal(model.finiteCoordinate('-80.5772'), -80.5772);
  assert.equal(model.finiteCoordinate(0), 0);
  assert.equal(model.finiteCoordinate('0'), 0);
  assert.equal(model.finiteCoordinate(undefined), null);
  assert.equal(model.finiteCoordinate('invalid'), null);
  assert.equal(model.finiteCoordinate('TBD'), null);
  assert.equal(model.finiteCoordinate(Number.NaN), null);
  assert.equal(model.finiteCoordinate(Number.POSITIVE_INFINITY), null);
  assert.equal(model.finiteCoordinate(Number.NEGATIVE_INFINITY), null);
});

test('normalizes recovery stage coordinates, downrange distance, and flight numbers with non-finite fallbacks', () => {
  const launches = normalizeRocketLaunches(
    {
      results: [
        {
          id: 'recovery-fallbacks',
          name: 'Falcon 9 | Edge Case Stage Normalization',
          net: '2026-07-20T10:00:00Z',
          pad: { latitude: '28.608', longitude: '-80.604' },
          rocket: {
            launcher_stage: [
              {
                id: 88,
                type: { name: 'Booster' },
                launcher_flight_number: 'invalid-flight',
                landing: {
                  attempt: true,
                  success: false,
                  downrange_distance: 'TBD',
                  landing_location: {
                    name: 'Ocean Impact',
                    latitude: 'N/A',
                    longitude: undefined,
                  },
                },
              },
              {
                id: 89,
                type: { name: 'Expended Stage' },
                landing: {
                  attempt: false,
                  type: { name: 'Expendable' },
                },
              },
            ],
          },
        },
      ],
    },
    NOW,
  );

  assert.equal(launches[0].recoveryStages.length, 2);

  const booster = launches[0].recoveryStages[0];
  assert.equal(booster.status, 'LOST');
  assert.equal(booster.success, false);
  assert.equal(booster.attempted, true);
  assert.equal(booster.flightNumber, null);
  assert.equal(booster.downrangeKm, null);
  assert.equal(booster.lat, null);
  assert.equal(booster.lon, null);

  const expendable = launches[0].recoveryStages[1];
  assert.equal(expendable.status, 'EXPENDABLE');
  assert.equal(expendable.attempted, false);
  assert.equal(expendable.success, null);
});

test('normalizes payload amounts and fractional string masses', () => {
  const launches = normalizeRocketLaunches(
    {
      results: [
        {
          id: 'payload-edge-cases',
          name: 'Electron | Mixed Payloads',
          net: '2026-07-20T10:00:00Z',
          pad: { latitude: '-39.26', longitude: '177.86' },
          rocket: {
            payloads: [
              {
                id: 601,
                amount: 'not-a-number',
                payload: { id: 11, name: 'Unknown Amount Payload' },
              },
              {
                id: 602,
                amount: 3,
                payload: { id: 12, name: 'Triple Payload' },
              },
              {
                id: 603,
                payload: {
                  id: 13,
                  name: 'Valid Fractional Mass Payload',
                  mass: '12.75',
                },
              },
            ],
          },
        },
      ],
    },
    NOW,
  );

  // Blank, negative and non-numeric masses are pinned by "missing payload
  // details stay unknown without inventing mass or classification".
  const payloads = launches[0].payloads;
  assert.equal(payloads.length, 3);
  assert.equal(payloads[0].amount, 1);
  assert.equal(payloads[1].amount, 3);
  assert.equal(payloads[2].massKg, 12.75);
});

test('keeps payload and recovery collections empty when LL2 does not disclose them', () => {
  const launches = normalizeRocketLaunches({ results: [{
    id: 'undisclosed',
    net: '2026-07-20T10:00:00Z',
    pad: { latitude: '28.608', longitude: '-80.604' },
    rocket: {},
  }] }, NOW);
  assert.deepEqual(launches[0].payloads, []);
  assert.deepEqual(launches[0].recoveryStages, []);
});

test('excludes launches outside the rolling 30-day window and missing coordinates', () => {
  const launches = normalizeRocketLaunches({ results: [
    { id: 'old', net: '2026-06-26T00:00:00Z', pad: { location: { coordinates: '1,1' } } },
    { id: 'no-coordinates', net: '2026-07-20T00:00:00Z', pad: { location: {} } },
    { id: 'future', net: '2026-07-28T00:00:00Z', pad: { location: { coordinates: '1,1' } } },
  ] }, NOW);

  assert.deepEqual(launches, []);
});

test('accepts an array payload for proxy and fixture flexibility', () => {
  const launches = normalizeRocketLaunches([
    { id: 'array-1', net: '2026-07-01T00:00:00Z', pad: { location: { coordinates: '2,3' } } },
  ], NOW);
  assert.equal(launches[0].id, 'array-1');
});

test('formats the launch epoch for ascent and orbit replay labels', () => {
  assert.equal(
    formatMissionEventTime('2026-06-29T02:25:00Z'),
    '2026-06-29\n02:25:00 UTC',
  );
  assert.equal(formatMissionEventTime(null), 'UNAVAILABLE');
});

test('reduces generic launch-site names to their identifying suffix', () => {
  assert.equal(compactLaunchSiteName('Orbital Launch Pad 2'), '2');
  assert.equal(compactLaunchSiteName('Space Launch Complex 4E'), '4E');
  assert.equal(compactLaunchSiteName('Launch Area 130'), '130');
  assert.equal(
    compactLaunchSiteName('Satish Dhawan Space Centre First Launch Pad'),
    'Satish Dhawan Space Centre First Launch Pad',
  );
  assert.equal(compactLaunchSiteName('Unknown'), null);
});

test('mission overlay factories preserve all four source-formatted label roles and lane policy', () => {
  const position = Cesium.Cartesian3.fromDegrees(-80.604, 28.608);
  const launch = {
    id: 'mission-1',
    name: 'Falcon 9 | Gauntlet Payload',
    launchSite: 'Space Launch Complex 39A',
    launchTime: '2026-07-20T10:00:00Z',
  };
  const ambient = createRocketMissionMarkerOverlayEntry(launch, position);
  assert.deepEqual({
    title: ambient.title,
    details: ambient.details,
    paintLane: ambient.paintLane,
    protected: ambient.protected,
    edgeFade: ambient.edgeFade,
  }, {
    title: 'FALCON 9',
    details: [],
    paintLane: 'ambient-label',
    protected: false,
    edgeFade: 'keyhole',
  });

  const selected = createRocketMissionMarkerOverlayEntry(launch, position, true);
  assert.equal(selected.title, 'FALCON 9');
  assert.deepEqual(selected.details, ['LAUNCH SITE · 39A']);
  assert.equal(selected.paintLane, 'selected');
  assert.equal(selected.protected, true);

  const roles = [
    ['reentry', 'STAGE RE-ENTRY', '#ffd166', ['STAGE RE-ENTRY', []]],
    ['payload', 'EST. ORBIT POSITION\n2026-07-20\n10:00:00 UTC', '#ffd166', [
      'EST. ORBIT POSITION',
      ['2026-07-20', '10:00:00 UTC'],
    ]],
    ['orbit', 'PROJECTED ORBIT', '#c084fc', ['PROJECTED ORBIT', []]],
  ];
  for (const [id, text, accent, [title, details]] of roles) {
    const entry = createRocketMissionElementOverlayEntry({ id, position, text, accent });
    assert.equal(entry.title, title);
    assert.deepEqual(entry.details, details);
    assert.equal(entry.accent, accent);
    assert.equal(entry.paintLane, 'selected');
    assert.equal(entry.protected, true);
    assert.equal(entry.edgeFade, 'keyhole');
  }

  const surplus = Array.from(
    { length: ROCKET_MISSION_AMBIENT_OVERLAY_COHORT_LIMIT + 12 },
    (_, index) => ({ id: `mission-${String(index).padStart(3, '0')}`, priority: index }),
  );
  const cohort = selectRocketMissionMarkerOverlayCohort(surplus);
  assert.equal(cohort.length, ROCKET_MISSION_AMBIENT_OVERLAY_COHORT_LIMIT);
  assert.equal(cohort[0].id, 'mission-059');
  assert.equal(cohort.at(-1).id, 'mission-012');
});

test('parses signed Launch Library timeline durations', () => {
  assert.equal(parseMissionDurationSeconds('PT1H1M46S'), 3706);
  assert.equal(parseMissionDurationSeconds('-PT35M'), -2100);
  assert.equal(parseMissionDurationSeconds('P0D'), 0);
  assert.equal(parseMissionDurationSeconds('unknown'), null);
});

test('matches compact payload identifiers without accepting an arbitrary constellation member', () => {
  assert.ok(scoreSatelliteNameMatch('Sirius SXM-11', 'SXM-11') >= 200);
  assert.ok(scoreSatelliteNameMatch('Starlink Group 17-40', 'STARLINK-1008') < 12);
});

test('finds a newly launched payload in the active TLE fallback catalog', () => {
  const tle = `SXM-11
1 69728U 26148A   26208.65166678  .00000015  00000+0  00000+0 0  9990
2 69728   0.0784 264.9826 0001797 240.4588 273.9506  1.00271527   440`;
  const track = findSatelliteOrbitTrackInTle(tle, 'Sirius SXM-11', {
    launchTime: '2026-06-29T02:25:00Z',
  });
  assert.equal(track?.noradId, 69728);
  assert.equal(track?.name, 'SXM-11');
  assert.ok(track?.orbitPath.length > 100);
  assert.ok(track?.periodSec > 80000);
  assert.ok(track?.current.speedMps > 1000);
  assert.ok(track?.current.speedMps < 12000);
  assert.equal(typeof track?.positionAt, 'function');
});

// A low-orbit element set for the fixture payload. The layer draws an orbit
// only from elements like these; a launch with none gets no orbit.
const GAUNTLET_TLE = `GAUNTLET PAYLOAD
1 69999U 26148A   26208.65166678  .00010000  00000+0  18000-3 0  9990
2 69999  51.6400 264.9826 0005797 240.4588 119.9506 15.50000000  440`;

test('real mission build, select, refresh, deselect, disable, and destroy paths publish no native labels', async () => {
  const realDocument = globalThis.document;
  const realFetch = globalThis.fetch;
  const realHtmlCanvasElement = globalThis.HTMLCanvasElement;
  const realHtmlImageElement = globalThis.HTMLImageElement;
  const realImageBitmap = globalThis.ImageBitmap;
  const realOffscreenCanvas = globalThis.OffscreenCanvas;
  const listeners = new Map();
  const context = {
    strokeStyle: '',
    lineWidth: 1,
    lineCap: '',
    shadowColor: '',
    shadowBlur: 0,
    beginPath() {},
    moveTo() {},
    lineTo() {},
    stroke() {},
  };
  class FakeElement {
    constructor(tagName = 'div') {
      this.tagName = tagName.toUpperCase();
      this.children = [];
      this.parentElement = null;
      this.style = { setProperty() {} };
      this.classList = { add() {}, remove() {}, toggle() {} };
      this.dataset = {};
      this.hidden = false;
      this.clientWidth = 1600;
      this.clientHeight = 900;
      this.width = 1600;
      this.height = 900;
      this.disableRootEvents = false;
    }

    addEventListener(type, handler) { listeners.set(`${this.tagName}:${type}`, handler); }
    removeEventListener(type) { listeners.delete(`${this.tagName}:${type}`); }
    appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
    remove() {
      if (this.parentElement) {
        this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
      }
      this.parentElement = null;
    }
    setAttribute() {}
    // This fixture has no parsed DOM children; it exercises native label
    // ownership, not the replay overlay's separately rendered icon children.
    querySelectorAll() { return []; }
    querySelector() { return null; }
    getBoundingClientRect() { return { left: 0, top: 0, width: 1600, height: 900 }; }
    getContext() { return this.tagName === 'CANVAS' ? context : null; }
  }
  const body = new FakeElement('body');
  const document = {
    body,
    onmousewheel: undefined,
    createElement: (tagName) => new FakeElement(tagName),
    getElementById: () => null,
    addEventListener(type, handler) { listeners.set(`document:${type}`, handler); },
    removeEventListener(type) { listeners.delete(`document:${type}`); },
  };
  const canvas = new FakeElement('canvas');
  const dataSources = [];
  const camera = {
    positionCartographic: null,
    positionWC: Cesium.Cartesian3.fromDegrees(-80.604, 28.608, 18_000_000),
    cancelFlight() {},
    lookAtTransform() {},
  };
  const scene = {
    canvas,
    camera,
    frameState: { frameNumber: 1 },
    postRender: new Cesium.Event(),
    preRender: new Cesium.Event(),
    preUpdate: new Cesium.Event(),
    primitives: { add: (primitive) => primitive, remove: () => true },
    drillPick: () => [],
  };
  const viewer = {
    camera,
    scene,
    dataSources: {
      add(dataSource) { dataSources.push(dataSource); return dataSource; },
      remove(dataSource) {
        const index = dataSources.indexOf(dataSource);
        if (index >= 0) dataSources.splice(index, 1);
        return index >= 0;
      },
    },
    selectedEntity: undefined,
  };
  const hostCalls = [];
  const host = {
    setEntries: (...args) => hostCalls.push(['entries', ...args]),
    setVisible: (...args) => hostCalls.push(['visible', ...args]),
    clearSource: (...args) => hostCalls.push(['clear', ...args]),
  };
  const launchTime = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  let launchName = 'Falcon 9 | Gauntlet Payload';
  const launchPayload = () => ({ results: [{
    id: 'mission-runtime',
    name: launchName,
    net: launchTime,
    status: { name: 'Launch Successful' },
    pad: {
      latitude: '28.608',
      longitude: '-80.604',
      name: 'Space Launch Complex 39A',
    },
    rocket: {
      launcher_stage: [{
        id: 'booster-1',
        type: 'Core',
        landing: {
          attempt: true,
          success: true,
          downrange_distance: 600,
          landing_location: { latitude: '30.1', longitude: '-76.2' },
        },
      }],
    },
    mission: {
      name: 'Gauntlet Payload',
      orbit: { name: 'Low Earth Orbit' },
    },
  }] });
  globalThis.document = document;
  globalThis.HTMLCanvasElement = FakeElement;
  globalThis.HTMLImageElement = class {};
  globalThis.ImageBitmap = class {};
  globalThis.OffscreenCanvas = class {};
  globalThis.fetch = async (url) => {
    if (url === '/api/celestrak/active') {
      return { ok: true, text: async () => GAUNTLET_TLE };
    }
    assert.equal(url, '/api/launches');
    return { ok: true, json: async () => launchPayload() };
  };
  _setRocketMissionOverlayHostForTest(host);
  let initialized = false;
  try {
    rocketLaunchesLayer.init(viewer);
    initialized = true;
    await rocketLaunchesLayer.enable();
    await rocketLaunchesLayer.update();

    const entities = dataSources[0].entities.values;
    assert.ok(entities.length >= 3, 'runtime guard requires the populated mission build path');
    assert.deepEqual(
      entities.map((entity) => entity.id).sort(),
      [
        'rocket-launch:mission-runtime',
        'rocket-recovery-end:mission-runtime:0',
        'rocket-satellite:mission-runtime',
      ],
      'only the pad, the recorded landing endpoint and the propagated satellite are drawn',
    );
    assert.equal(
      entities.some((entity) => /^rocket-(transfer|vehicle|reentry)/.test(entity.id)),
      false,
      'no estimated ascent, vehicle or re-entry path exists',
    );
    assert.ok(entities.every((entity) => entity.label === undefined));
    const ambientPublication = hostCalls.findLast(([type, sourceId]) => (
      type === 'entries' && sourceId === ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID
    ));
    assert.ok(ambientPublication);
    assert.equal(ambientPublication[2].length, 1);
    assert.equal(ambientPublication[2][0].title, 'FALCON 9');
    assert.deepEqual(ambientPublication[3], {
      cohortLimit: ROCKET_MISSION_AMBIENT_OVERLAY_COHORT_LIMIT,
      collisionCapacity: ROCKET_MISSION_AMBIENT_OVERLAY_COLLISION_CAPACITY,
      moving: false,
    });
    const launchEntity = dataSources[0].entities.getById('rocket-launch:mission-runtime');
    assert.deepEqual(
      ambientPublication[2][0].position,
      launchEntity.position.getValue(Cesium.JulianDate.now()),
      'ambient host marker must reuse the entity anchor Cartesian',
    );
    const frameTime = Cesium.JulianDate.now();
    scene.preRender.raiseEvent(scene, frameTime);
    assert.equal(launchEntity.point.show.getValue(frameTime), true);
    camera.positionWC = Cesium.Cartesian3.fromDegrees(99.396, -28.608, 18_000_000);
    scene.preRender.raiseEvent(scene, frameTime);
    assert.equal(
      launchEntity.point.show.getValue(frameTime),
      false,
      'pre-render horizon pass must hide a rear-side depth-free mission dot before draw and pick',
    );
    camera.positionWC = Cesium.Cartesian3.fromDegrees(-80.604, 28.608, 18_000_000);
    scene.preRender.raiseEvent(scene, frameTime);
    assert.equal(
      launchEntity.point.show.getValue(frameTime),
      true,
      'mission dot must return when its surface anchor faces the camera again',
    );

    _setSelectedRocketMissionForTest('mission-runtime');
    const selectedPublication = hostCalls.findLast(([type, sourceId]) => (
      type === 'entries' && sourceId === ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID
    ));
    assert.ok(selectedPublication);
    assert.deepEqual(selectedPublication[3], ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_OPTIONS);
    assert.deepEqual(selectedPublication[2].map(({ title }) => title), [
      'FALCON 9',
      'GAUNTLET PAYLOAD',
      'ORBIT',
    ]);
    assert.deepEqual(selectedPublication[2][0].details, ['LAUNCH SITE · 39A']);
    assert.match(selectedPublication[2][1].details[0], /^\d{4}-\d{2}-\d{2}$/);
    assert.match(selectedPublication[2][1].details[1], /^\d{2}:\d{2}:\d{2} UTC$/);
    assert.ok(selectedPublication[2].every((entry) => (
      entry.selected === true
      && entry.protected === true
      && entry.paintLane === 'selected'
      && entry.edgeFade === 'keyhole'
    )));
    const satelliteEntity = dataSources[0].entities.getById('rocket-satellite:mission-runtime');
    const satellitePosition = satelliteEntity.position.getValue(Cesium.JulianDate.now());
    assert.equal(
      selectedPublication[2][1].position(),
      satellitePosition,
      'payload host getter must return the exact per-frame live-position cache',
    );

    // Jitter regression net: live-state propagation advances at most once per
    // frameNumber, and the host getter is a pure read that never advances it.
    // Without both halves, the host label and the native dot can propagate to
    // different wall-clock instants inside one frame — the documented
    // label-separation jitter class.
    const payloadEntry = selectedPublication[2][1];
    const realDateNow = Date.now;
    try {
      let nowMs = realDateNow();
      Date.now = () => nowMs;
      scene.frameState.frameNumber = 41;
      const frameA = Cesium.Cartesian3.clone(
        satelliteEntity.position.getValue(Cesium.JulianDate.now()),
      );
      nowMs += 30_000;
      assert.deepEqual(
        Cesium.Cartesian3.clone(satelliteEntity.position.getValue(Cesium.JulianDate.now())),
        frameA,
        'a second native read in the same frame must not re-propagate',
      );
      nowMs += 30_000;
      scene.frameState.frameNumber = 42;
      assert.deepEqual(
        Cesium.Cartesian3.clone(payloadEntry.position()),
        frameA,
        'host getter must not advance propagation, even on a new frame',
      );
      const frameB = Cesium.Cartesian3.clone(
        satelliteEntity.position.getValue(Cesium.JulianDate.now()),
      );
      assert.notDeepEqual(frameB, frameA, 'native read on a new frame propagates (non-vacuous)');
      assert.deepEqual(
        Cesium.Cartesian3.clone(payloadEntry.position()),
        frameB,
        'host getter reads the advanced cache after native propagation',
      );
    } finally {
      Date.now = realDateNow;
      scene.frameState.frameNumber = 1;
    }
    assert.ok(
      Cesium.Cartesian3.magnitude(selectedPublication[2][2].position()) > 6_400_000,
      'orbit host label sits on the propagated orbit ring',
    );

    launchName = 'Mission Refresh | Gauntlet Payload';
    await rocketLaunchesLayer.update();
    assert.ok(dataSources[0].entities.values.every((entity) => entity.label === undefined));
    const refreshPublication = hostCalls.findLast(([type, sourceId]) => (
      type === 'entries' && sourceId === ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID
    ));
    assert.equal(refreshPublication[2][0].title, 'MISSION REFRESH');
    assert.deepEqual(refreshPublication[2][0].details, ['LAUNCH SITE · 39A']);

    _setSelectedRocketMissionForTest(null);
    const deselectedPublication = hostCalls.findLast(([type, sourceId]) => (
      type === 'entries' && sourceId === ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID
    ));
    assert.equal(deselectedPublication[2][0].title, 'MISSION REFRESH');
    assert.equal(deselectedPublication[2][0].protected, false);

    await rocketLaunchesLayer.disable();
    assert.deepEqual(hostCalls.slice(-4), [
      ['clear', ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID],
      ['visible', ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID, false],
      ['clear', ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID],
      ['visible', ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID, false],
    ]);
    await rocketLaunchesLayer.destroy(viewer);
    initialized = false;
    assert.equal(dataSources.length, 0);
    assert.deepEqual(hostCalls.slice(-4), [
      ['clear', ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID],
      ['visible', ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID, false],
      ['clear', ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID],
      ['visible', ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID, false],
    ]);
  } finally {
    if (initialized) await rocketLaunchesLayer.destroy(viewer);
    _setRocketMissionOverlayHostForTest();
    globalThis.fetch = realFetch;
    globalThis.document = realDocument;
    globalThis.HTMLCanvasElement = realHtmlCanvasElement;
    globalThis.HTMLImageElement = realHtmlImageElement;
    globalThis.ImageBitmap = realImageBitmap;
    globalThis.OffscreenCanvas = realOffscreenCanvas;
  }
});

test('enable is transactional: a failed satellites dependency rolls the module back and a retry recaptures', async (t) => {
  const calls = [];
  let satellitesEnabled = false;
  let failNextActivation = true;
  const fakeManager = {
    isEnabled: (id) => (id === 'satellites' ? satellitesEnabled : false),
    getLayerParams: () => ({}),
    setLayerParams: () => {},
    setEnabled: (id, enabled) => {
      calls.push(['setEnabled', id, enabled]);
      if (id === 'satellites' && enabled && failNextActivation) {
        return Promise.resolve(false); // activation refused/failed
      }
      if (id === 'satellites') satellitesEnabled = enabled;
      return Promise.resolve(true);
    },
  };
  const priorDocument = globalThis.document;
  globalThis.document = {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  rocketLaunchesLayer.attachDataManager(fakeManager);
  t.after(() => {
    globalThis.document = priorDocument;
    rocketLaunchesLayer.attachDataManager(null);
  });

  // First enable: dependency activation fails -> enable() must reject and the
  // module must roll itself back (satellite snapshot restored AND cleared).
  await assert.rejects(() => rocketLaunchesLayer.enable(), /satellites layer/);
  const restoreCall = calls.filter(([, id, enabled]) => id === 'satellites' && enabled === false);
  assert.ok(restoreCall.length >= 1, 'rollback restored the pre-mission satellites state');

  // Retry with a healthy dependency: capture must run AGAIN (a retained
  // snapshot would skip it) and enable must succeed.
  calls.length = 0;
  failNextActivation = false;
  await rocketLaunchesLayer.enable();
  assert.deepEqual(
    calls.filter(([, id, enabled]) => id === 'satellites' && enabled === true).length >= 1,
    true,
    'retry recaptured the satellites dependency',
  );
  await rocketLaunchesLayer.disable();
});

test('disable reports a semantic failure while restoring the satellites dependency', async (t) => {
  let satellitesEnabled = false;
  let failRestore = false;
  const fakeManager = {
    isEnabled: (id) => (id === 'satellites' ? satellitesEnabled : false),
    isEffectivelyEnabled: (id) => (id === 'satellites' ? satellitesEnabled : false),
    getLayerParams: () => ({}),
    setLayerParams: () => {},
    setEnabled: (id, enabled) => {
      if (id === 'satellites' && !enabled && failRestore) return Promise.resolve(false);
      if (id === 'satellites') satellitesEnabled = enabled;
      return Promise.resolve(true);
    },
  };
  const priorDocument = globalThis.document;
  globalThis.document = {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  rocketLaunchesLayer.attachDataManager(fakeManager);
  t.after(() => {
    globalThis.document = priorDocument;
    rocketLaunchesLayer.attachDataManager(null);
  });

  await rocketLaunchesLayer.enable();
  failRestore = true;
  await assert.rejects(
    () => rocketLaunchesLayer.disable(),
    /could not restore the satellites layer/,
  );
});


test('missing payload details stay unknown without inventing mass or classification', () => {
  for (const [mass, expected] of [[null, null], [undefined, null], ['', null], ['  ', null],
    [false, null], [-1, null], ['invalid', null], [0, 0], ['125', 125]]) {
    const [launch] = normalizeRocketLaunches([{ id: 'mass', pad: { latitude: 1, longitude: 2 }, net: '2026-07-20T10:00:00Z',
      payloads: [{ mass }] }], NOW);
    assert.equal(launch.payloads[0].massKg, expected);
    assert.equal(launch.payloads[0].name, 'Unnamed payload');
  }
  const [launch] = normalizeRocketLaunches([{ id: 'missing', pad: { latitude: 1, longitude: 2 }, net: '2026-07-20T10:00:00Z' }], NOW);
  assert.deepEqual(launch.payloads, []);
});

test('a stage has a landing endpoint only when the record gives coordinates', () => {
  const { landingEndpoint } = createModel({});
  assert.deepEqual(landingEndpoint({ lat: 30.1, lon: -76.2 }), {
    lat: 30.1,
    lon: -76.2,
    accuracy: 'CONFIRMED',
  });
  // Nothing is derived from the pad, the recovery type or the downrange distance.
  assert.equal(
    landingEndpoint({ lat: null, lon: null, recoveryType: 'RTLS', downrangeKm: 600 }),
    null,
  );
  assert.equal(landingEndpoint(null), null);
});
