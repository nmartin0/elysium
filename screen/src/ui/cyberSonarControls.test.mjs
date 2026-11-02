import test from 'node:test';
import assert from 'node:assert/strict';
import {
  getCyberSonarControlState,
  setCyberSonarControls,
} from './cyberSonarControls.js';
import { readFileSync } from 'node:fs';

function fixture(theme = 'cyber') {
  const root = {
    dataset: { uiTheme: theme, cyberSonarGpu: 'supported' },
    style: { setProperty() {} },
  };
  const flags = new Set();
  const hudFlags = new Set(['active']);
  const doc = {
    documentElement: root,
    body: { classList: { contains: (name) => flags.has(name) } },
    getElementById: () => ({
      classList: { contains: (name) => hudFlags.has(name) },
    }),
  };
  const calls = [];
  const owner = {
    hud: { getVariant: () => theme },
    _setCyberSonarSetting(name, value) {
      calls.push([name, value]);
      const suffix = name[0].toUpperCase() + name.slice(1);
      root.dataset['cyberSonar' + suffix] = String(value);
    },
    _setCyberSonarEnabled(value) {
      calls.push(['enabled', value]);
      root.dataset.cyberSonar = value ? 'on' : 'off';
    },
  };
  return { doc, owner, calls, flags, hudFlags, root };
}

test('native sonar sliders represent every accepted integer without browser snapping', () => {
  const html = readFileSync(new URL('./templates/display-controls.html', import.meta.url), 'utf8');
  for (const name of ['rings', 'range', 'intensity', 'opacity', 'sector']) {
    assert.match(html, new RegExp(`id="cyber-sonar-${name}"[^>]*step="1"`));
  }
});

test('maps all settings to the slider owner and reads actual state, including zero', () => {
  const f = fixture();
  const result = setCyberSonarControls(f.owner, {
    enabled: false, rings: 6, rangePct: 80,
    intensityPct: 0, opacityPct: 90, sectorDeg: 30,
  }, f.doc);
  assert.equal(result.ok, true);
  assert.deepEqual(f.calls, [
    ['rings', 6], ['range', 80], ['intensity', 0],
    ['opacity', 90], ['sector', 30], ['enabled', false],
  ]);
  assert.equal(result.sonar.enabled, false);
  assert.equal(result.sonar.intensityPct, 0);
  assert.equal(result.sonar.contactSweepActive, false);
  assert.deepEqual(result.sonar, getCyberSonarControlState(f.doc));
});

test('rejects the whole invalid request before any mutation', () => {
  for (const request of [
    {}, null, [], { enabled: 'false' }, { rings: 2 }, { rangePct: 121 },
    { opacityPct: NaN }, { intensityPct: Infinity }, { sectorDeg: 8.5 },
    { intensityPct: '50' }, { enabled: false, unknown: 1 },
    { rings: 6, sectorDeg: 61 },
  ]) {
    const f = fixture();
    assert.equal(setCyberSonarControls(f.owner, request, f.doc).ok, false);
    assert.deepEqual(f.calls, []);
  }
});

test('requires Cyber and preserves off state and every omitted setting', () => {
  for (const theme of ['tactical', 'minimal']) {
    const f = fixture(theme);
    assert.equal(setCyberSonarControls(f.owner, { enabled: true }, f.doc).ok, false);
    assert.deepEqual(f.calls, []);
  }
  const f = fixture();
  f.root.dataset.cyberSonar = 'off';
  const before = getCyberSonarControlState(f.doc);
  const result = setCyberSonarControls(f.owner, { rings: 12 }, f.doc);
  assert.deepEqual(result.sonar, { ...before, rings: 12 });
  assert.deepEqual(f.calls, [['rings', 12]]);
});

test('reports inactive map effects in Cockpit, hidden HUD, unsupported and uninitialized GPU', () => {
  const f = fixture();
  f.flags.add('cockpit-mode');
  assert.equal(getCyberSonarControlState(f.doc).mapSweepActive, false);
  f.flags.clear();
  f.hudFlags.clear();
  assert.equal(getCyberSonarControlState(f.doc).contactSweepActive, false);
  f.hudFlags.add('active');
  for (const value of ['unsupported', undefined]) {
    if (value === undefined) delete f.root.dataset.cyberSonarGpu;
    else f.root.dataset.cyberSonarGpu = value;
    assert.equal(getCyberSonarControlState(f.doc).contactSweepActive, false);
  }
});
