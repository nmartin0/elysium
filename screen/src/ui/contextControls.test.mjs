import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ContextControls } from './contextControls.js';

class Button extends EventTarget {
  constructor() {
    super();
    this.attributes = new Map();
  }
  getAttribute(name) {
    return this.attributes.get(name);
  }
  setAttribute(name, value) {
    this.attributes.set(name, value);
  }
}
const turn = () => new Promise((resolve) => setImmediate(resolve));
function fixture(t, elements = {}) {
  const calls = [];
  const controls = new ContextControls({
    elements,
    installations: {},
    actions: {
      getCockpit: () => null,
      claimVisualAuthority: () => calls.push('claim'),
      showToast: () => calls.push('notice'),
      setClearBusy: () => {},
      syncDetection: () => {},
      scheduleLayout: () => {},
      refreshRadio: () => {},
      setPanelCollapsed: () => calls.push('expand'),
    },
  });
  t.after(() => {
    controls.stop();
    controls.disconnect();
  });
  return { controls, calls };
}

test('Context starts with an explicit idle snapshot', (t) => {
  const { controls } = fixture(t);
  assert.deepEqual(controls.getContextModeState(), {
    mode: null,
    active: false,
    changing: false,
    entering: null,
    canContact: true,
    canMission: true,
    snapshotCaptured: false,
  });
});

test('a pending Context tab cannot reopen a disposed panel', async (t) => {
  const tab = new Button();
  const { controls, calls } = fixture(t, { _globalContextFlightsBtn: tab });
  let release;
  controls._selectContextMode = () =>
    new Promise((resolve) => {
      release = resolve;
    });
  tab.dispatchEvent(new Event('click'));
  assert.deepEqual(calls, ['claim']);
  controls.stop();
  release(true);
  await turn();
  tab.dispatchEvent(new Event('click'));
  assert.deepEqual(calls, ['claim']);
});

test('reconnecting and disposal release each manager subscription exactly once', (t) => {
  const { controls } = fixture(t);
  const counts = new Map();
  const manager = (name) =>
    Object.fromEntries(
      [
        'subscribe',
        'subscribeVisibilityRequests',
        'addVisibilityGuard',
        'subscribeBeforeDestroy',
      ].map((method) => [
        method,
        () => () => {
          const key = `${name}:${method}`;
          counts.set(key, (counts.get(key) || 0) + 1);
        },
      ]),
    );
  controls.connect(manager('a'));
  controls.connect(manager('b'));
  assert.equal(counts.size, 4);
  controls.stop();
  controls.disconnect();
  controls.disconnect();
  controls.connect(manager('c'));
  assert.equal(counts.size, 8);
  assert.ok([...counts.values()].every((count) => count === 1));
});

test('a rejected tracked reaction settles without an unhandled rejection', async (t) => {
  const { controls } = fixture(t);
  const failure = new Error('source unavailable');
  const pending = controls._trackContextLayerReaction(Promise.reject(failure));
  await assert.rejects(pending, failure);
  await controls._waitForContextLayerSettlement();
  assert.equal(controls._contextLayerReactionPromises.size, 0);
});
