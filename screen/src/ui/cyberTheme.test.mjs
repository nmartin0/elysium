import { getScopeMaskFeather, isScopeMaskEnabled, setScopeMaskEnabled, setScopeMaskFeather } from '../scopeMask.js';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  applyHudUiTheme,
  CYBER_VISUAL_DEFAULTS,
  cyberVisualDefaultsForHudTransition,
  HUD_LAYOUTS,
  normalizeHudLayout,
} from '../hudLayouts.js';
import { VisualSettings } from './visualSettings.js';
import { STYLES } from './visualPresets.js';

function styleOwner(t, initialVariant = 'cyber') {
  const previous = { document: globalThis.document, window: globalThis.window };
  const root = { dataset: {} };
  globalThis.document = { documentElement: root, querySelectorAll: () => [] };
  globalThis.window = { dispatchEvent() {} };
  t.after(() => Object.assign(globalThis, previous));
  let variant = initialVariant;
  const calls = [];
  const hud = {
    getVariant: () => variant,
    setVariant: (value) => {
      // Normalize like the real HUD so retired layouts fall back.
      variant = normalizeHudLayout(value);
      applyHudUiTheme(root, variant);
    },
    setMode: (value) => calls.push(['mode', value]),
    onStyleChange: (value) => calls.push(['style', value]),
  };
  hud.setVariant(initialVariant);
  const owner = Object.create(VisualSettings.prototype);
  Object.assign(owner, {
    activeStyle: 'normal',
    readHud: () => hud,
    readShareLinks: () => ({ onStyleChange() {} }),
    _visualEffects: {
      stages: Object.fromEntries(
        Object.entries(STYLES).map(([name, config]) => [
          name,
          { uniforms: { ...config.uniforms, intensity: 0 } },
        ]),
      ),
    },
    services: { governorRequestRender() {}, setDetectionStyle() {} },
    _hudLayoutSelect: { value: initialVariant },
    _styleIndicator: {},
    _setBloomEnabled: (value) => calls.push(['bloom', value]),
    _setSharpenEnabled: (value) => calls.push(['sharpen', value]),
    _applyDetectionPreset: (value) => calls.push(['detection', value]),
    _syncShareState: () => calls.push(['share', variant]),
  });
  for (const name of [
    'setCelestialRingEnabled',
    '_startTransition',
    '_updateStyleMiniStatus',
    '_updateSliderPanel',
    '_updateHudButtonState',
    '_syncIrBoost',
    '_syncCyberSonarControl',
    '_scheduleAdaptivePanelLayout',
    '_applyDetectionFadeFromUi',
  ])
    owner[name] = () => {};
  return { owner, hud, root, calls };
}

test('visual styles retain Cyber through real preset application without dropping other defaults', (t) => {
  const { owner, hud, root, calls } = styleOwner(t);
  for (const style of ['noir', 'anime', 'normal']) {
    owner.setStyle(style);
    assert.equal(owner.activeStyle, style);
    assert.equal(hud.getVariant(), 'cyber');
    assert.equal(root.dataset.uiTheme, 'cyber');
    assert.equal(owner._hudLayoutSelect.value, 'cyber');
    assert.deepEqual(calls.at(-1), ['share', 'cyber']);
  }
  // No look carries a preset any more, so none changes detection or post.
  assert.equal(calls.filter(([name]) => name === 'detection').length, 0);
});

test('non-Cyber style presets and explicit HUD choices remain authoritative', (t) => {
  const { owner, hud, root } = styleOwner(t);
  for (const variant of ['tactical', 'minimal']) {
    owner._setHudVariant(variant);
    assert.equal(hud.getVariant(), variant);
    assert.equal(root.dataset.uiTheme, undefined);
    owner.setStyle('normal');
    owner.setStyle('noir');
    assert.equal(hud.getVariant(), variant);
  }
});

test('leaving Cyber without a preset choice restores the prior visual preset', (t) => {
  const { owner, hud } = styleOwner(t, 'tactical');
  owner.setStyle('noir');

  owner._setHudVariant('cyber', { applyVisualDefaults: true });
  assert.equal(owner.activeStyle, 'normal');
  assert.equal(owner._preCyberStyle, 'noir');
  assert.equal(owner._cyberStyleUserSelected, false);

  owner._setHudVariant('minimal', { applyVisualDefaults: true });
  assert.equal(hud.getVariant(), 'minimal');
  assert.equal(owner.activeStyle, 'noir');
  assert.equal(owner._preCyberStyle, null);
  assert.equal(owner._cyberStyleUserSelected, false);
});

test('a preset explicitly selected in Cyber survives exit and resets for re-entry', (t) => {
  const { owner, hud } = styleOwner(t, 'tactical');
  owner.setStyle('noir');

  owner._setHudVariant('cyber', { applyVisualDefaults: true });
  owner.setStyle('anime', { userInitiated: true });
  assert.equal(owner.activeStyle, 'anime');
  assert.equal(owner._preCyberStyle, 'noir');
  assert.equal(owner._cyberStyleUserSelected, true);

  // Reselecting the active mode must not erase the user's preset intent.
  owner._setHudVariant('cyber', { applyVisualDefaults: true });
  assert.equal(owner._preCyberStyle, 'noir');
  owner._setHudVariant('minimal', { applyVisualDefaults: true });
  assert.equal(hud.getVariant(), 'minimal');
  assert.equal(owner.activeStyle, 'anime');
  assert.equal(owner._preCyberStyle, null);
  assert.equal(owner._cyberStyleUserSelected, false);

  // A later untouched Cyber round trip restores the new pre-Cyber preset.
  owner._setHudVariant('cyber', { applyVisualDefaults: true });
  assert.equal(owner.activeStyle, 'normal');
  assert.equal(owner._preCyberStyle, 'anime');
  owner._setHudVariant('minimal', { applyVisualDefaults: true });
  assert.equal(owner.activeStyle, 'anime');
});

test('an explicit same-value Normal choice is preserved on Cyber exit', (t) => {
  const { owner } = styleOwner(t, 'tactical');
  owner.setStyle('noir');
  owner._setHudVariant('cyber', { applyVisualDefaults: true });

  owner.setStyle('normal', { userInitiated: true });
  assert.equal(owner.activeStyle, 'normal');
  assert.equal(owner._cyberStyleUserSelected, true);
  owner._setHudVariant('minimal', { applyVisualDefaults: true });
  assert.equal(owner.activeStyle, 'normal');
});

test('an authoritative same-Cyber reset clears local preset ownership', (t) => {
  const { owner } = styleOwner(t, 'tactical');
  owner.setStyle('noir');
  owner._setHudVariant('cyber', { applyVisualDefaults: true });
  owner.setStyle('anime', { userInitiated: true });
  assert.equal(owner._cyberStyleUserSelected, true);

  owner._setHudVariant('cyber');
  assert.equal(owner.activeStyle, 'anime');
  assert.equal(owner._preCyberStyle, null);
  assert.equal(owner._cyberStyleUserSelected, false);
  owner._setHudVariant('minimal', { applyVisualDefaults: true });
  assert.equal(owner.activeStyle, 'anime');
});

test('scope choice and expanded feather survive every HUD layout and both restore paths', async (t) => {
  const { owner } = styleOwner(t, 'tactical');
  const previous = { enabled: isScopeMaskEnabled(), feather: getScopeMaskFeather() };
  t.after(() => { setScopeMaskEnabled(previous.enabled); setScopeMaskFeather(previous.feather); });
  Object.assign(owner.services, { setScopeMaskEnabled, setScopeMaskFeather });
  owner._scopeBtn = { checked: true };
  owner._scopeFeatherSlider = { value: '11', disabled: false };
  owner._scopeFeatherValue = {};
  await owner.restoreShareState({ scopeEnabled: false, scopeFeatherPct: 200 });
  assert.equal(owner._scopeBtn.checked, false);
  assert.equal(owner._scopeFeatherSlider.disabled, true);
  assert.equal(owner._scopeFeatherSlider.value, '200');
  for (const layout of ['minimal', 'cyber', 'tactical']) {
    owner._setHudVariant(layout, { applyVisualDefaults: true });
    assert.equal(isScopeMaskEnabled(), false, layout);
    assert.equal(getScopeMaskFeather(), 2, layout);
    assert.equal(owner._scopeBtn.checked, false, layout);
  }
  await owner.applyVisualState({ scope: { enabled: true, featherPct: 175 } });
  assert.equal(isScopeMaskEnabled(), true);
  assert.equal(getScopeMaskFeather(), 1.75);
  assert.equal(owner._scopeBtn.checked, true);
  assert.equal(owner._scopeFeatherSlider.disabled, false);
  assert.equal(owner._scopeFeatherValue.textContent, '175%');
  await owner.applyVisualState({ scope: { featherPct: 500 } });
  assert.equal(getScopeMaskFeather(), 2);
  assert.equal(owner._scopeFeatherSlider.value, '200');
});

test('a scene shot saved with the retired Snow style plays on Normal', async (t) => {
  const { owner } = styleOwner(t, 'tactical');
  owner.setStyle('noir');
  await owner.applyVisualState({ style: 'snow' });
  assert.equal(owner.activeStyle, 'normal');
});

test('scene and share HUD transitions do not restore a local pre-Cyber preset', async (t) => {
  const { owner, hud } = styleOwner(t, 'tactical');
  owner.setStyle('noir');
  owner._setHudVariant('cyber', { applyVisualDefaults: true });
  owner.setStyle('anime', { userInitiated: true });
  assert.equal(owner._cyberStyleUserSelected, true);

  await owner.applyVisualState({ style: 'noir', hud: { variant: 'cyber' } });
  assert.equal(hud.getVariant(), 'cyber');
  assert.equal(owner.activeStyle, 'noir');
  assert.equal(owner._preCyberStyle, null);
  assert.equal(owner._cyberStyleUserSelected, false);
  owner._setHudVariant('minimal', { applyVisualDefaults: true });
  assert.equal(owner.activeStyle, 'noir');

  owner.setStyle('anime');
  owner._setHudVariant('cyber', { applyVisualDefaults: true });
  assert.equal(owner._preCyberStyle, 'anime');
  owner.setStyle('anime', { userInitiated: true });
  await owner.restoreShareState({
    style: 'noir',
    hudVariant: 'cyber',
  });
  assert.equal(hud.getVariant(), 'cyber');
  assert.equal(owner.activeStyle, 'noir');
  assert.equal(owner._preCyberStyle, null);
  assert.equal(owner._cyberStyleUserSelected, false);
  owner._setHudVariant('tactical', { applyVisualDefaults: true });
  assert.equal(owner.activeStyle, 'noir');
  assert.equal(owner._preCyberStyle, null);
});

test('scene and share restoration override Cyber', async (t) => {
  const { owner, hud } = styleOwner(t);
  await owner.applyVisualState({ style: 'noir', hud: { variant: 'minimal' } });
  assert.equal(hud.getVariant(), 'minimal');
  owner._setHudVariant('cyber');
  await owner.restoreShareState({
    style: 'anime',
    hudVariant: 'operator',
  });
  // A link saved with the retired Operator layout restores as Tactical.
  assert.equal(hud.getVariant(), 'tactical');
  await owner.restoreShareState({
    style: 'noir',
    hudVariant: 'cyber',
  });
  assert.equal(hud.getVariant(), 'cyber');
  assert.equal(owner.activeStyle, 'noir');
});

const read = (relative) =>
  readFileSync(new URL(relative, import.meta.url), 'utf8');

test('Cyber setup uses a compact toolbar icon and highlights the north-up letter', () => {
  const css = read('./styles/cyber.css');
  assert.match(
    css,
    /#top-center-actions #key-setup-chip\s*\{[^}]*inset: auto;[^}]*width: 36px;/,
  );
  assert.match(css, /#key-setup-chip\[hidden\]\s*\{\s*display: none;/);
  assert.match(
    css,
    /#north-up-view\[data-north-up='true'\]\s+\.camera-compass-n\s*\{[^}]*color: var\(--cyber-red-bright\)/,
  );
});
const cyberStyles = read('./styles/cyber.css');

// Source guards supplement rendered popup/hit-target checks. Inspect one rule
// at a time so a safe declaration on a child cannot excuse a clipped ancestor.
function cssRuleBody(styles, selector) {
  const match = styles.match(new RegExp(`${selector.source}\\s*\\{([^}]+)\\}`));
  assert.ok(match, `Missing CSS rule: ${selector.source}`);
  return match[1];
}

test('Cyber Voice clips its decoration without clipping descendant help and errors', () => {
  const owner = cssRuleBody(
    cyberStyles,
    /:root\[data-ui-theme='cyber'\] #command-dock > #gev-voice-control/,
  );
  assert.match(owner, /isolation:\s*isolate;/);
  assert.match(owner, /overflow:\s*visible;/);
  assert.match(owner, /clip-path:\s*none;/);

  const decoration = cssRuleBody(
    cyberStyles,
    /:root\[data-ui-theme='cyber'\] #command-dock > #gev-voice-control::before/,
  );
  assert.match(decoration, /clip-path:\s*polygon\(/);
  assert.match(decoration, /pointer-events:\s*none;/);
  assert.match(decoration, /inset:\s*0;/);
  assert.match(decoration, /z-index:\s*-1;/);
});

test('Cyber dock pins escape the tray mask and its decoration overrides the legacy arrow geometry', () => {
  const owner = cssRuleBody(
    cyberStyles,
    /:root\[data-ui-theme='cyber'\] #command-dock \.dock-popover-content/,
  );
  assert.match(owner, /clip-path:\s*none;/);
  assert.match(owner, /isolation:\s*isolate;/);

  // Including the tray owners beats #control-panel's more specific old
  // ::after arrow positioning. Otherwise left:auto can collapse the frame.
  const decoration = cssRuleBody(
    cyberStyles,
    /:root\[data-ui-theme='cyber'\]\s+#command-dock\s+:is\(#location-bar, #control-panel\)\s+\.dock-popover-content::after/,
  );
  assert.match(decoration, /inset:\s*0;/);
  assert.match(decoration, /width:\s*auto;/);
  assert.match(decoration, /height:\s*auto;/);
  assert.match(decoration, /transform:\s*none;/);
  assert.match(decoration, /clip-path:\s*var\(--cyber-panel-frame\);/);
  assert.match(decoration, /pointer-events:\s*none;/);
});

test('Cyber lower-left telemetry tracks the credit anchor with clearance for its logo row', () => {
  const telemetry = cssRuleBody(
    cyberStyles,
    /#intel-hud\[data-variant='cyber'\] \.hud-bottom-left/,
  );
  const offset = telemetry.match(/bottom:\s*calc\(2vh \+ ([\d.]+)rem\);/);
  assert.ok(offset, 'telemetry must retain the attribution viewport anchor');
  const credits = read('./styles/command-dock-trays.css');
  const creditOffsets = [
    ...credits.matchAll(
      /#cesium-credits\s*\{[^}]*bottom:\s*calc\(2vh \+ ([\d.]+)rem\);/g,
    ),
  ];
  assert.ok(creditOffsets.length > 0);
  for (const credit of creditOffsets) {
    assert.ok(
      Number(offset[1]) - Number(credit[1]) >= 2.75,
      'reserve the 28px logo row, baseline descent and 12px clearance at the 16px root size',
    );
  }
  assert.doesNotMatch(cyberStyles, /\.hud-bottom-left\s*\{\s*bottom:\s*60px;/);
});

test('shared panel hooks affect only opted-in rail surfaces without overriding disclosure and concealment', () => {
  const styles = read('./styles/panel-surfaces.css');
  const rail = cssRuleBody(
    styles,
    /:is\(#left-panel-stack, #right-context-rail\)\s+> \[data-panel-id\]:has\(> \[data-panel-surface\]\)/,
  );
  assert.match(rail, /pointer-events:\s*auto;/);
  assert.doesNotMatch(rail, /(?:display|visibility):/);
  assert.doesNotMatch(
    styles,
    /:is\(#left-panel-stack, #right-context-rail\)\s*> \[data-panel-id\]\s*\{/,
  );
  assert.match(
    styles,
    /\[data-panel-surface\]:not\(\[hidden\]\):not\(dialog:not\(\[open\]\)\)\s*\{\s*display: flex;/,
  );
  assert.match(
    styles,
    /dialog\[data-panel-surface\]:not\(\[open\]\)\s*\{\s*display: none !important;/,
  );
  assert.match(
    styles,
    /body:is\(\.ui-clean-view, \.recording-mode\)[^{]+\{[^}]*visibility: hidden !important;[^}]*pointer-events: none !important;/,
  );
});

test('Cyber clipped expand controls retain an inset keyboard-focus outline', () => {
  assert.match(
    cyberStyles,
    /:root\[data-ui-theme='cyber'\]\s+\.panel-collapse-btn:focus-visible\s*\{[^}]*outline: 2px solid var\(--cyber-red-bright\) !important;[^}]*outline-offset: -3px;[^}]*box-shadow: none;/,
  );
  assert.match(
    cyberStyles,
    /:root\[data-ui-theme='cyber'\]\s+\.panel-collapse-btn:is\(:hover, :focus-visible\)\s*\{[^}]*border-color: var\(--cyber-red-bright\);/,
  );
});

test('Cyber Radio retains upstream nested Context ownership', () => {
  assert.doesNotMatch(cyberStyles, /#right-context-rail\s*>\s*#radio-panel/);
});

test('Cyber side panels share one width and one framed surface material', () => {
  assert.match(cyberStyles, /--cyber-panel-width: 272px;/);
  assert.match(cyberStyles, /--cyber-right-panel-width: 312px;/);
  assert.match(cyberStyles, /--cyber-panel-collapsed-width: 200px;/);
  assert.match(cyberStyles, /--cyber-panel-control-size: 30px;/);
  assert.match(
    cyberStyles,
    /--cyber-panel-surface: rgba\(18, 24, 27, 0\.92\);/,
  );
  assert.match(
    cyberStyles,
    /#left-panel-stack\s*> :is\(#data-panel, #scene-panel\)\.collapsed \{\s*width: var\(--cyber-panel-collapsed-width\);/,
  );
  assert.match(
    cyberStyles,
    /:is\(#data-panel, #scene-panel\)\.collapsed\s+:is\(\.data-panel-inner, \.scene-panel-inner\) \{[\s\S]*?height: 50px;[\s\S]*?min-height: 50px;/,
  );
  assert.match(
    cyberStyles,
    /#pp-toggles\s*> \.pp-header-row\s+\.pp-collapse-btn \{[\s\S]*?width: var\(--cyber-panel-control-size\);[\s\S]*?height: var\(--cyber-panel-control-size\);/,
  );
  assert.match(
    cyberStyles,
    /#right-context-rail\s+:is\(\s*\.cctv-panel-inner,\s*\.weather-panel-inner,\s*\.recent-imagery-panel-inner,\s*\.street-level-panel-inner,\s*\.global-context-panel-inner\s*\) \{\s*padding-right: 8px;/,
  );
  assert.match(
    cyberStyles,
    /#right-context-rail[\s\S]*?:is\(\s*#cctv-panel,\s*#weather-panel,\s*#recent-imagery-panel,\s*#street-level-panel,\s*#global-context-panel\s*\)\.collapsed[\s\S]*?> \.panel-header \{[\s\S]*?height: 48px;[\s\S]*?padding: 0 10px 0 14px;/,
  );
});

test('Cyber is a canonical HUD layout with a safe Tactical fallback', () => {
  assert.deepEqual(HUD_LAYOUTS, ['tactical', 'minimal', 'cyber']);
  assert.equal(normalizeHudLayout('CYBER'), 'cyber');
  assert.equal(normalizeHudLayout('operator'), 'tactical');
  assert.equal(normalizeHudLayout('unknown'), 'tactical');
});

test('the Cyber HUD owns the global shell skin and leaving it restores defaults', () => {
  const root = { dataset: { unrelated: 'preserved' } };
  assert.equal(applyHudUiTheme(root, 'cyber'), 'cyber');
  assert.equal(root.dataset.uiTheme, 'cyber');
  assert.equal(applyHudUiTheme(root, 'minimal'), null);
  assert.equal(root.dataset.uiTheme, undefined);
  assert.equal(root.dataset.unrelated, 'preserved');
});

test('an explicit transition into Cyber selects Normal once', () => {
  assert.deepEqual(CYBER_VISUAL_DEFAULTS, { style: 'normal' });
  assert.equal(
    cyberVisualDefaultsForHudTransition('tactical', 'cyber', {
      explicit: true,
    }),
    CYBER_VISUAL_DEFAULTS,
  );
  assert.equal(
    cyberVisualDefaultsForHudTransition('cyber', 'cyber', {
      explicit: true,
    }),
    null,
  );
  assert.equal(cyberVisualDefaultsForHudTransition('tactical', 'cyber'), null);
  assert.equal(
    cyberVisualDefaultsForHudTransition('cyber', 'minimal', {
      explicit: true,
    }),
    null,
  );
});

test('Cyber visual defaults update the style and render state', () => {
  const calls = [];
  const owner = {
    services: {
      governorRequestRender: (reason) => calls.push(['render', reason]),
    },
    setStyle: (style, options) => calls.push(['style', style, options]),
  };

  VisualSettings.prototype._applyCyberVisualDefaults.call(
    owner,
    CYBER_VISUAL_DEFAULTS,
  );

  assert.deepEqual(calls, [
    [
      'style',
      'normal',
      {
        applyPreset: false,
        revealParameters: false,
        preserveCyberRestore: true,
      },
    ],
    ['render', 'cyber-visual-defaults'],
  ]);
});

test('Cyber voice telemetry renders a live scan scope without replacing audio ownership', () => {
  assert.match(
    cyberStyles,
    /#gev-voice-control\s*\{[\s\S]*?--cyber-voice-wave:/,
  );
  assert.match(cyberStyles, /\.gev-voice-visualizer::before/);
  assert.match(cyberStyles, /\.gev-voice-visualizer::after/);
  assert.match(cyberStyles, /@keyframes gev-cyber-voice-scan/);
  assert.match(cyberStyles, /@keyframes gev-cyber-voice-lock/);
  assert.match(cyberStyles, /\[data-speaker='user'\]/);
  assert.match(cyberStyles, /\[data-speaker='ai'\]/);
  assert.match(
    cyberStyles,
    /prefers-reduced-motion: reduce[\s\S]*?gev-voice-visualizer::after[\s\S]*?animation: none/,
  );
});

test('Cyber right panels preserve intrinsic sizing and the shared rail allocation', () => {
  assert.doesNotMatch(
    cyberStyles.slice(cyberStyles.indexOf(":root[data-ui-theme='cyber'] {")),
    /#right-context-rail\s*>[^{}]+\{[^{}]*\b(?:flex|height|max-height):/,
  );
});

test('Cyber panels retain clean edges without the added footer band', () => {
  assert.doesNotMatch(cyberStyles, /--cyber-panel-foot-/);
  assert.doesNotMatch(cyberStyles, /border-bottom: 24px solid transparent/);
});

test('Cyber keeps Sonar on/off without the removed CSS effect switch or dimmer', () => {
  const template = readFileSync(
    new URL('./templates/display-controls.html', import.meta.url),
    'utf8',
  );
  assert.match(template, /id="cyber-sonar-toggle"/);
  assert.doesNotMatch(template, /data-sonar-mode|cyber-sonar-mode-row/);
  assert.doesNotMatch(cyberStyles, /cyber-scene-dimmer|data-cyber-sonar-mode/);
});

test('Cyber Display uses a red title without a panel-specific center tab', () => {
  assert.match(
    cyberStyles,
    /#pp-toggles \.pp-header-label\s*\{\s*color: var\(--cyber-red-bright\);/,
  );
  assert.doesNotMatch(cyberStyles, /#pp-toggles[^,{]*::after\s*\{/);
  assert.match(cyberStyles, /isolation: isolate;\s*clip-path: none;/);
  assert.match(cyberStyles, /#pp-toggles:not\(\.collapsed\)::before/);
});

test('the HUD has no classification, system id or edge strips', () => {
  assert.doesNotMatch(
    cyberStyles,
    /hud-classification|hud-system|hud-bracket|hud-left-edge|hud-right-edge/,
  );
});
