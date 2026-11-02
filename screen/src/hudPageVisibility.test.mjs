// The HUD's 250 ms telemetry readout skips ticks in a hidden page, except in
// an inline panel, whose host may report it hidden while it is on screen.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { IntelHUD } = await import('./hud.js');

function installHiddenPage() {
  const elements = new Map(
    ['hud-alt', 'hud-summary', 'hud-latlon', 'hud-bottom-line', 'hud-mode']
      .map((id) => [id, { textContent: '' }]),
  );
  const previousDocument = globalThis.document;
  globalThis.document = {
    hidden: true,
    visibilityState: 'hidden',
    getElementById: (id) => elements.get(id) ?? null,
    querySelectorAll: () => [],
    addEventListener() {},
    removeEventListener() {},
  };
  const viewer = {
    camera: {
      pitch: -Math.PI / 2,
      positionCartographic: { latitude: 0.7, longitude: -1.2, height: 500 },
      computeViewRectangle: () => undefined,
      moveStart: { addEventListener() {}, removeEventListener() {} },
      moveEnd: { addEventListener() {}, removeEventListener() {} },
    },
  };
  return {
    alt: () => elements.get('hud-alt').textContent,
    viewer,
    restore() {
      if (previousDocument === undefined) delete globalThis.document;
      else globalThis.document = previousDocument;
    },
  };
}

test('the HUD readout pauses in a hidden page but keeps updating in an inline panel', (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const page = installHiddenPage();
  let hud;
  try {
    hud = new IntelHUD(page.viewer);
    hud._visible = true;

    t.mock.timers.tick(250);
    assert.equal(page.alt(), '', 'a hidden page skips the telemetry tick');

    globalThis.GEV_EMBED_INLINE = true;
    t.mock.timers.tick(250);
    assert.match(
      page.alt(),
      /^ALT: 500m/,
      'an inline panel reported hidden keeps its readout updating',
    );
  } finally {
    delete globalThis.GEV_EMBED_INLINE;
    hud?.destroy();
    page.restore();
  }
});
