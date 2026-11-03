# FORK.md: changes to God's Eye View in `screen/`

`screen/` is a fork of God's Eye View by Bilawal Sidhu, imported from
upstream commit `8978801dfd2a` (see `c2f5923b`, which imported it untouched).

**Licence.** God's Eye View is MIT licensed, copyright (c) 2026 Bilawal Sidhu.
`screen/LICENSE` is the licence text and must travel with this code wherever
it goes (a copy, a separate repository, a built bundle's notices). The
modifications below are made under the owner's authorization (PRINCIPLES.md
section 11) and are covered by the same licence.

Rule: every later change to a file under `screen/` is appended to the table
below (file, what, why). A change that is not listed here is a bug.

## Stub, don't delete (owner, 2 November 2026)

The web UI from God's Eye View stays as upstream has it, so that upstream
updates keep merging with few conflicts. From now on, unused or unwanted
features are STUBBED (switched off, made inert, hidden from the UI, or
cut at a single seam) and not deleted, and upstream's text, branding,
build config, dependencies and settings strings are left alone unless
they break an owner rule or the app.

- Slices 1 to 5 already deleted a lot (see their tables). Those deletions
  stay; they are the reason a merge of upstream changes to those files
  needs a hand-resolve. New work does not add to that list.
- STUBBED on 2 November 2026 (owner): the `s2-ghostmaps` conflict-map layer
  and the Cyber sonar. See "Stubbed, with how to turn back on" below. The
  same day the keyless default basemap moved off Esri imagery and the keyless
  terrain was switched off (see "Basemap", below).
- Left as upstream, on purpose: the "God's Eye View" page title and
  title bar, the "Provider Settings" wording, `.env.example` (its
  OpenAI, Gemini and Mapillary keys are inert in this fork), the
  `unsafe-eval` and `maps.googleapis.com` allowances in the build's CSP,
  and package.json dependencies no source imports.
- The README is explicit that data does not yet come through Elysium:
  the screen still serves its own `/api/*` routes until the Elysium
  module page and data path exist.

### Stubbed, with how to turn back on

Both are switched off and hidden. All their code, tests and data files stay.

- **`s2-ghostmaps`** (S2 GhostMaps conflict-map layer). The switch is one
  list: `STUBBED_LAYER_IDS = ['s2-ghostmaps']` in
  `screen/src/data/layerState.js`. While the id is in it:
  `LAYER_STATE_REGISTRY` omits the layer (so it is not restored, not saved,
  and never turns on from stored state); `constructCatalog.js` does not
  construct it (so it is not in the layer panel, which is built from the
  catalog); `sourceComposition.js` skips its availability row;
  `registerDataCredits` skips its credit line; and `server/providers/local.js`
  does not mount `ghostMapsProxy()`, so `/api/ghostmaps` is a 404 and nothing
  polls GitHub. The client source is built but makes no request until a layer
  uses it. Its share-link token `5` stays reserved for ever (the ledger is
  unchanged): old links that carry it decode, the layer is ignored, and the
  token is not reported as unknown. Never reassign `5`. To turn it back on,
  empty the list (`[]`); the tests in `ghostMapsStub.test.mjs` and the count
  assertions (21 layers, `layerState.test.mjs`, `constructCatalog.test.mjs`,
  `sourceComposition.test.mjs`) then need the reverse edit. The `PANEL_GROUPS`
  entry, `layerNames.js` names and translations were left in place.
- **Cyber sonar.** The switch is `CYBER_SONAR_STUB = { stubbed: true }` in
  `screen/src/cyberSonar.js`: `isCyberSonarEnabled()` returns false, so the
  sweep, contact dimming and render cadence never run, and the shell's
  `setCyberSonar` tool cannot enable it. Two CSS lines hide the UI: the
  `.cyber-sonar-control` rules in `ui/styles/controls.css` (the Sonar toggle,
  sliders, status and tooltip) and `.hud-sonar` in `ui/styles/cyber.css` are
  `display: none`, each with a "STUBBED" comment giving the old value
  (`flex` and `block`). The Cyber layout itself, its theme and the
  `cyberSonar*.js` files stay. To turn it back on, set `stubbed: false` and
  restore those two `display` values; the engine tests
  (`cyberSonar.test.mjs`, `cyberSonarScene.test.mjs`) lift the stub
  themselves, and `cyberTheme.test.mjs` pins the two CSS lines.

### Basemap (owner, 2 November 2026)

The basemap is the free open set (docs/feeds.md, "Basemap build plan"). Only
the first slice is built: the low-zoom layer.

- **Default stack.** With no Google key the app now starts on the new
  `natural-earth` stack (`src/maps/catalog.js`, `defaultSources.js`,
  `app/scene.js`), not Esri. It is Natural Earth II (public domain), levels 0
  to 2 (about 5.7 px per degree at level 2), 465 KB (475,959 bytes; 42 JPEG tiles and the tile map file) in
  `screen/public/basemap/natural-earth-ii/`, copied from the `cesium` npm
  package (`Assets/Textures/NaturalEarthII`) and read by
  `Cesium.TileMapServiceImageryProvider`. Beyond level 2 Cesium stretches
  it, so close up it is blurry; WorldCover is the planned fix.
- **Esri stays, not the default.** The `esri-imagery` stack, its chip and its
  fallbacks are unchanged, but the chip reads "Esri Satellite (own licence)"
  and the credit says "needs your own Esri licence". The id is also kept in
  the share-link enum (`natural-earth` is appended there; codes are
  permanent). Still on Esri: the Recent Imagery layer borrows the Esri stack
  when a day is shown (`maps/imageryComparison.js`, `IMAGERY_COMPARISON_STACK_ID`).
  That is left as upstream for now and is the next thing to move.
- **Keyless terrain stubbed.** `KEYLESS_TERRAIN_STUB = { stubbed: true }` in
  `src/maps/terrain.js`: `createKeylessTerrain()` returns flat ellipsoid
  terrain and makes no request, and `registerDataCredits` skips the
  Re:Earth credit (its own mirror flag `REEARTH_TERRAIN_CREDIT_STUBBED` in
  `data/dataCredits.js`; flip both). Why: the hosted Re:Earth endpoint is a third party's
  service and its terms could not be read here; the owner's plan is terrain
  self-hosted from Mapterhorn. To turn it back on set `stubbed: false`
  (the two tests in `sourceFactories.test.mjs` lift it themselves).
- **Self-hosted terrain (opt-in, added 3 November 2026).** The switch is one
  value, `TERRAIN_TILE_URL`, in `screen/.env` or the environment (same route as
  `GOOGLE_MAPS_API_KEY`: `server/standalone/vite.config.js` -> `build/vite.js`
  `define` -> `main.js` -> `configureTerrain()` in `src/maps/terrainConfig.js`).
  It is a URL template with `{z}`, `{x}` and `{y}` that starts with `https://`,
  `http://` or `/`; anything else is ignored with a console warning. Unset (the
  default) changes nothing: flat terrain, no request. Set, `createKeylessTerrain()`
  returns `createTerrariumTerrainProvider()` (`src/maps/terrariumTerrain.js`)
  instead of flat ellipsoid; Re:Earth stays off. The provider reads Terrarium
  tiles (height = R * 256 + G + B / 256 - 32768, 512 px), uses Web Mercator
  tiling, builds a 129 by 129 `HeightmapTerrainData` per tile, requests only
  levels 0 to `TERRARIUM_MAX_LEVEL` (12, one constant, from the Mapterhorn
  facts in docs/feeds.md: `planet.pmtiles` is zoom 0 to 12) and never requests
  a tile outside the pyramid. A missing or failed tile is flat with no children
  asked for (no throw, no retry loop); 429 and 5xx replies use the existing
  backoff in `terrainRetry.js`. `TERRAIN_ATTRIBUTION_URL` (optional) is the
  link in the Data attribution lightbox, shown only while the terrain is on
  (`registerDataCredits` third argument); without it the credit is plain text.
  Known limits, all untried: (1) tested only on synthetic tiles
  (`terrariumTerrain.test.mjs`), not on real Mapterhorn data or in a browser,
  and the blob-to-pixels path (`createImageBitmap`, canvas) has no test;
  (2) Web Mercator stops at about 85.05 degrees, so the globe has no terrain
  surface at the poles while this is on; (3) the height datum is unverified:
  Re:Earth's Mapterhorn build was labelled "ellipsoid", which suggests the tile
  heights are above the geoid, so terrain may sit up to about 100 m off the
  ellipsoid (the provider has a `heightOffset` hook, not wired; `src/data/geoid.js`
  has EGM96); (4) neighbouring tiles can differ by one source pixel on a shared
  edge; (5) deeper than zoom 12 is not requested.
  Hosting (the owner's job, nothing here is hosted): serve the tiles as
  `{z}/{x}/{y}.webp` from any static host with CORS (`Access-Control-Allow-Origin`)
  and caching. Either extract the zoom 0 to 12 tiles from `planet.pmtiles` into
  files (for example with the go-pmtiles `pmtiles extract` / a tile-export tool;
  command line unverified), or run a PMTiles server that answers
  `/{z}/{x}/{y}.webp` (unverified which); the app itself reads plain tile
  URLs, not a `.pmtiles` file with range requests, so a bare static
  `planet.pmtiles` is not enough. Also publish a page built from
  `attribution.json` and set `TERRAIN_ATTRIBUTION_URL` to it. To try it: set
  both values in `.env`, restart, and watch the network tab for requests to
  your template only.
- Files: `src/maps/{catalog,defaultSources,imagery,terrain,terrainConfig,terrariumTerrain}.js`,
  `app/scene.js`, `mapStackChips.js`, `view/index.js`, `share/viewCodec.js`
  (enum appended), `data/dataCredits.js` (new `natural-earth-basemap` entry,
  Re:Earth skipped while stubbed), their tests, `public/basemap/`.

## Changes versus upstream 8978801dfd2a

| File | What | Why |
| --- | --- | --- |
| `screen/src/app/opaqueOrigin.js` (new) | `installOpaqueOriginImageLoading(Cesium)`: when `globalThis.origin === 'null'` (a frame sandboxed without `allow-same-origin`), wraps `Cesium.Resource._Implementations.createImage` so every http(s) image is loaded with `crossOrigin`. Returns false and does nothing in any other origin. | Cesium's `isCrossOriginUrl` compares the URL with `window.location`, which in an opaque origin says "same host", so same-host images (the Milky Way skybox) load without `crossOrigin` and `texImage2D` throws a SecurityError that stops rendering. `isCrossOriginUrl` is not configurable (cannot be replaced); the image loader it feeds can. The asset host must send `Access-Control-Allow-Origin: *`. Roadmap R1 and the sandbox spike. |
| `screen/src/app/scene.js` | Imports and calls `installOpaqueOriginImageLoading(Cesium)` once, just before the viewer is created (before the first image is requested). | Where Cesium is first configured. |
| `screen/src/standalone/application.js` | In embed mode (`isEmbedded()`), `googleTokens` is `null` instead of `createGoogleTokenSource()`. Superseded in slice 4: the token source, route and server fallback are gone for every mode. | That source GETs `/api/google/tiles-token` from the app's own host. Embedded, the host is ours and has no such route. |
| `screen/src/standalone/startupChrome.js` (simplified in `8165f0e1`: `initializeSettings` and `initKeySetup` are gone for every mode) | In embed mode `initializeSettings` is left out, so `initKeySetup` does not run. | `initKeySetup` GETs `/api/setup/status`. An embedded globe has no key setup. |
| `screen/src/voice/realtimeDiagnostics.js` (deleted in `8165f0e1`) | `postDebugLog` returns at once in embed mode. | It sent a credentialed `sendBeacon` / `fetch` to `/api/realtime/debug-log` on the app's own host. |
| `screen/src/services/requests.js` (summary service deleted in `8165f0e1`) | `summary.configured()` resolves `false` in embed mode, without a request. | It probed `/api/openai/hud-summary/status`; `false` means the app never offers a summary and never calls `/api/openai/hud-summary`. |
| `screen/src/layers/localAdsb/feeds.js` (deleted in `ea95db5f`) | The feed's `request()` throws "local receiver route unavailable" in embed mode, before any fetch. | It polled `/api/local-receivers/aircraft`. A missing route already leads to the same state (`configured: false`, not polling), so behaviour is the same without the request. |

Embed mode is the existing flag `isEmbedded()` (`?embed=1`, or
`globalThis.GEV_EMBED_INLINE`, which the inline panel runtime sets and whose
host answers `/api/*` itself, so the gates also apply there). It now lives in
`screen/src/embedFlag.js`, a module with no imports, and `app/embed.js`
re-exports it; the gated modules import the light module so that Cesium is not
pulled into them (`app/embed.js` imports `cesium`). It sits outside the
renderer directories because `services/requests.js` is a portable entry that
`check-import-directions` keeps away from them. `screen/scripts/package-boundaries.json`
lists `src/embedFlag.js` in six groups and `src/app/opaqueOrigin.js` in
`application-components`. With the flag off, none of the gates changes anything. `/api/google/nearby-places` is never called at
startup; it is only reached by a user action (the search and tools code), so it
is not gated yet.

Not gated, and not yet checked: any layer a view or share link switches on
(flights, vessels, FIRMS, launches, cyclones, transit, earthquakes, weather
and others) calls the app's own host `/api` when it loads; the embed-mode
default layer set is not established. Replacing those routes is the data
adapters' job.

Note for whoever adds an adapter next: these gates stop the app calling its own
host. The data adapters that replace its routes (R1) are a separate change.

### Content policy for the frame

Measured with the changes above, in a frame with `sandbox="allow-scripts"`:
`script-src 'self' 'wasm-unsafe-eval' blob:; worker-src 'self' blob:` works;
`unsafe-eval` is not needed. Cesium does try `eval` once at startup
(`Cesium.js:66`, reported as a `securitypolicyviolation` event, twice) and
carries on; no page error follows.

## Slice 2: what was removed, and how

The owner ruled out anything run by or about a government agency (military,
police or agency cameras, ALPR) and every "game" part. Paths
are under `screen/`. One commit per group, each with the gates
(`check-package-boundaries`, `check-import-directions`) passing, except
`b0b0c05b`, which left them failing (missing imports to the military and
awareness modules) until the next commit, `8427f8dc`, deleted those callers.

| Commit | Group | Removed | Kept or changed | Why |
| --- | --- | --- | --- | --- |
| `f90f7557` | MCP | `server/mcp/`, `src/tools/mcp/`, `docs/MCP_SETUP.md`, the `mcp` script and `./tools/mcp` export, the Vite plugin, their tests | `package-boundaries.json` group `tools-mcp` dropped | "MCP" is on the ruled-out list. |
| `8165f0e1` | Voice and AI, key setup, tool catalog, inline panel build | `src/voice/`, `src/agent/`, `src/tools/` (the AI tool catalog), `src/keySetup.js`, `server/providers/openai*`, `gemini*`, `server/standalone/voiceTools.js`, `key-setup*`, `provider-settings` html and css, `voice-card.css`, `voice-cost.css`, `globePanelRuntime`, `build/panel.js`, `scripts/build-panel.mjs`, voice and setup scripts, tests | New `src/app/viewActions.js` holds the seven embed view actions (`set_visual_style`, `set_map_stack`, `set_layer_visibility`, `track_entity`, `stop_tracking`, `annotate_map`, `clear_annotations`, origin `tool`) extracted from `voice/gevActions.js`; `keySetupCore.mjs` is reduced to the key registry and `keySetupRequirementEnvVars`; `hud.js` keeps its deterministic summary line and drops the AI one; `IntelHUD` takes only the viewer; the `summary` request service and its embed gate are gone | Its own voice and AI, key setup flows. `gev:view` still needs the action runner, so it was extracted first. Judgment call: the whole `src/tools/` catalog and the MCP-Apps panel build went too, since their only users were voice, MCP and the panel. |
| `4c7a4d54` | Pinokio and Docker | `pinokio/`, `scripts/pinokio-*.mjs`, `docker-start.mjs`, `Dockerfile`, `compose.yaml`, `.dockerignore`, their tests | `.prettierignore` and `ci.yml` lines | Pinokio is on the list; the Docker files were its launchers. |
| `671c6230` | Director, scenes, flood demo | `src/director/`, `src/scenes/`, scene UI, `data/bhoteKoshi*`, `public/events/`, `docs/DIRECTOR*`, `SCENE-DOCUMENT.md`, director scripts, `scenes.css`, `bhote-koshi.css`, the scene panel template | Generic panel-layout rules from `scenes.css` moved to `panel-layout.css`; the page reset from `bhote-koshi.css` moved to `base.css`; `bhote-koshi-2026` and `bhote-koshi-locator` removed from the catalog and layer-state registry (tokens `h`, `z` stay reserved); CSP drops YouTube, Facebook and X frame hosts; `SHARE_VIEW_PANELS` keeps `scene-panel` (permanent numbering) | Director and demo scenes, including the flood demo. |
| `3baad307`, `940911db` | Cockpit | `src/ui/cockpit*.js`, `cockpitCoordinator`, `cockpitTracking`, `cockpitUtilityLayout`, `cockpitVisionPolicy`, `cockpitCloudEffects`, `cockpit.html`, `cockpit.css`, `qa-cockpit-*`, tests; `cockpitAirLod.js` and `cockpitContactDot.js` are kept (layers import them) | New `src/ui/inertCockpit.js`: `createInertCockpit()` answers the cockpit hooks (`cockpitView` null, state "inactive", control refused); `getAircraftTrackingTarget()` returns null | Cockpit is on the list. A stub, not a deletion of the call sites, because the shell, panels and locale code still call it. |
| `20bb3acb` | News briefs | `data/regionalBrief.js`, the `regional-brief` and `weather-effects` endpoints, server regional news and weather services, the `regional` and `weather` request slots | `regionalModel.js` trimmed to `normalizeRegionalPlace` (used by `nominatim.js`); Open-Meteo, Google News and GDELT credits removed | News briefs are on the list. |
| `d98bc2e3` | Fake detection boxes | Corner and transit bracket painting, CRT scanlines, the sparse focus ring, `detectionPresentation.js`, the bracket helpers in `detectionDraw.js` | The callout (label) lane for aircraft and vessels is unchanged and detection is still on by default | The boxes were fake; the labels carry real data. |
| `ffa4273c` | ALPR | `layers/alpr`, `app/layers/alprCameras.js`, `data/alprCameras.js`, the source contract, panel id, layer-state entry (token `p` stays reserved), CSS, fixture | Retry-chip strings for ALPR in `shellFeedback` were left | Licence-plate readers are ruled out. |
| `b0b0c05b` | Stubs | none | New `src/app/layerStubs.js`; `createLayerCatalog(layers, metadata, stubs)`; the eight stubs are not in `catalog.layers` | See "Stubs" below. |
| `8427f8dc` | Military, installations, awareness, traffic | `layers/military`, `awareness`, `installations`, `traffic` and their `app/layers`, `data/military*`, `installation*`, `traffic*`, `tomtom*`, server `military-installations`, `traffic.js`, `aircraft/adsb-lol.js` (the adsb.lol military proxy), the `/api/military/track` route, `sources/openFreeMap`, `vectorTiles`, `militaryTileGeometry`, QA scripts | `layers/aircraft/classification.js`: the military registry is now an inert object that answers false and fetches nothing, so `flights` no longer depends on the military layer; `adsbLolFallbackAnchor` kept (civil fallback) | Military, anything about a government agency, simulated traffic. |
| `ea95db5f` | CCTV, radio, local ADS-B, street level | `layers/cctv`, `radio`, `localAdsb`, `streetLevel` (except `view.js` and `tileMath.js`, which `ghostMaps` imports), `src/sdr/`, their UI, data, server providers (`cctv`, `radio`, `mapillary`, local receivers), `config/cctv_sources.*`, street-level fixtures, `docs/LOCAL-RECEIVERS.md`, `overlays/worldOverlayAllocation.worker.mjs` (a benchmark) | `testSupport/rayCamera.mjs` (the ray helper `view.test` needed); the cctv and street-level template blocks, the radio and SDR section of `context.html`, the sync chip; `mobileShell` Cameras sheet is now `['recent-imagery-panel']`; the `c` CCTV hotkey is gone | Agency and private camera feeds, estimated camera poses, internet radio, hardware receiver. |
| `29b4a8a9` | Fix to the above | none | New `src/ui/styles/layer-rows.css`: the generic layer toggle row, status chip, sub-control and list rules that sat inside `radio.css` (base lines 612-1045) | `radio.css` held them; deleting it unstyled the layer panel. Found by `english-css-parity.test`. |
| `015d0b27` | 3D aircraft models | `public/models/` (all glb files and the README), the 3D toggle in `display-controls.html`, tests that read the models | `MODELS_3D_AVAILABLE = false` in `layers/flights/policy.js`; `_modelRegimeActive()` and `_trackedModelRegimeActive()` return false at once | 3D aircraft models are on the list. |
| `b99d4dd2` | CRT, night vision, FLIR | `styles/retro.js`, `surveillance.js`, `thermal.js`, their shader imports and presets, hotkeys 2-4, three dock buttons | `RETIRED_STYLES` gains `snow`, `retro`, `surveillance`, `thermal`, `crt`, `nvg`, `flir` (old links open as Normal); `SHARE_VIEW_ENUMS` and `SHARE_VIEW_STYLE_PARAMS` keep their reserved codes; `CYBER_VISUAL_DEFAULTS` is `{ style: 'normal' }` (entering Cyber used to select FLIR); `STYLE_PRESET_DEFAULTS = {}`; `view/index.js` style list is normal, anime, noir | Military HUD styling. |
| `9996f0e8`, `0ecf56b4` | Tests, i18n | tests that named removed things; 1427 unused catalog entries per locale | `npm run i18n -- --prune` run once | The i18n catalog test fails while entries are stale. |

Files edited rather than deleted (file, what, why):

| File | What | Why |
| --- | --- | --- |
| `src/app/layerStubs.js` (new) | `createLayerStub(id)` returns a frozen inert object (`inert: true`, `enabled: false`, `isEnabled`, `beginWorldJump`, `endWorldJump`, `stopTracking`, `cancelPendingTrackingRestore`, `releaseCameraOwnership`, `attachNavigation`, `getTrackedInfo`, `getTrackedSubject`, `getContextSnapshot` returning null, `getUIState` returning `{}`); `STUBBED_LAYER_IDS` lists the eight ids | The callers use those hooks without null checks. |
| `src/app/catalog.js` | `createLayerCatalog(layers, metadata, stubs = [])`; `get(id)` falls back to the stubs | `catalogControlServices` throws for a missing control layer id. |
| `src/app/constructCatalog.js`, `standalone/catalog.js`, `app/application.js` | Layers removed, `LOCAL_ONLY_LAYER_METADATA` is empty, `streetLevelProviders` plumbing removed, catalog built with `createLayerStubs()` | The stubs are outside `catalog.layers`, so the data manager never registers them. |
| `src/data/layerState.js` | Registry entries and option groups for `cctv`, `military`, `military-awareness`, `military-installations`, `radio`, `street-level`, `traffic` removed. Tokens stay in `LEGACY_LAYER_STATE_TOKENS` and the ledger | Stubs have no share-link state. A link that names a removed token is rejected whole, as any unknown token is. |
| `src/app/sourceComposition.js`, `standalone/layerSources.js`, `app/sources.js` | Source contracts and sources for the removed layers removed | Each contract lists layers that must be registered. |
| `src/ui/layerPanel.js`, `layerNames.js`, `panelChrome.js`, `panelLayoutController.js`, `mobileShell.js`, `hudLayouts.js`, `worldOverlay.js` | Ids of the removed layers and panels removed | Lists of ids. |
| `src/ui/applicationShell.js`, `shellFacade.js`, `displayBindings.js`, `layerBindings.js`, `contextBindings.js`, `applicationShortcuts.js`, `shellElements.js` | Cctv, street level, radio, local SDR, installations and cockpit wiring removed; the detection layer list is flights and satellites; style keys 2-4 gone | Callers of removed code. |
| `src/layers/flights/*` | Model branches gated by `MODELS_3D_AVAILABLE`; flights no longer reads the military registry | See 3D models. |
| `scripts/package-boundaries.json`, `scripts/format-scope.json`, `scripts/check-import-directions.mjs`, `package.json` | Entries for deleted files and exports removed; `inertCockpit.js`, `layerStubs.js`, `viewActions.js` added to their groups | The two repo gates. |

### Stubs

Eight layers are hard-required (`CONTROL_LAYER_IDS`): `military`,
`military-awareness`, `military-installations`, `traffic`, `cctv`,
`street-level`, `radio`, `local-adsb`. Each is replaced by the inert object
above. A stub is not a catalog layer, has no source contract, no panel id and
no layer-state entry, and no list, panel, search or share link shows it. All
their implementation files were deleted because nothing else imports them (the
import-direction gate agrees). The ALPR layer needed no stub and was deleted.

### Left in place on purpose (inert residue)

After slice 3. Each item says why it stays.

- `military`, `military-awareness`, `military-installations`, `traffic`, `cctv`,
  `street-level`, `radio`, `local-adsb`: the eight stubs in
  `app/layerStubs.js`. `catalog.js` (`CONTROL_LAYER_IDS`), `sourceComposition.js`
  and `constructCatalog.js` still require a layer object for each id.
- `selectedMilitaryTrackingId` (token `u` in the flights options),
  `SHARE_TRACKING_RESTORE_POLICIES.military`, the `military_aircraft` entity
  kind in the view codec and `view/index.js`, and the layer tokens of the
  removed layers: permanent share-link codes. A code is reserved, never
  reused, and the token ledger test enforces it.
- (Slice 5: the dead 3D-model code is deleted, see Slice 5.)
- The Contacts mode of the Context panel (the CONTACTS tab, `contextMode ===
  'flights'`, the first-run "Live contacts" tile). It is not inert: it turns on
  the real `flights` and `ais-live-vessels` layers and owns detection through
  `contactsDetectionPolicy`. Decision (slice 4): it stays; its copy was fixed.
  The name "Contacts" and the `radar` icon are listed under the doubtful
  words below.
- `viewCodec` panel numbering and style enums (permanent).
- The `tactical` HUD variant and Cyber theme (the Cyber theme no longer
  selects a look), detection themes.
- `layers/streetLevel/view.js` and `tileMath.js` (`ghostMaps` imports them);
  the `.scene-btn` rule in `panel-layout.css`.
- (Slice 5: the QA scripts for removed features are deleted or fixed.)
- Comments and test names that still say "cockpit" (about 60, in `flights`,
  `iconOrientation`, `motionModel`, `localGeojson*`, `contactsDetectionPolicy`
  and tests). No code path reads the word.

### Slice 3: commits

Each commit passes `check-import-directions` and `check-package-boundaries`.

| Commit | What | Why |
| --- | --- | --- |
| `06e142a4` | Estimated launch trajectories: `launches/paths.js`, `replay.js`, `camera.js` deleted; ascent, replay marker, replay camera, projected orbit and estimated landings removed from `rendering`, `overlays`, `orbitRendering`, `selection`, `model`, `panel`, `policy*`, `state`, `index`, `lifecycle`, `ingestion`; `data/rocketLaunches.js` no longer builds a trajectory. | Owner rule: no estimated trajectories or poses. Kept: the orbit drawn from real TLEs by the satellites layer, supplied trajectory points, landing endpoints the record gives. |
| `158ca0c9` | Cockpit plumbing: `ui/inertCockpit.js`, `cockpitAirLod.js`, `cockpitContactDot.js`, the flights cockpit contact mode, `cockpit-mode` class checks, `follow.cockpit` in `view/index.js`, all cockpit CSS, `COCKPIT_REFUSAL_NOUNS`, the `gev:cockpit-mode-changed` listeners. The phone-shell tab is now "Imagery" (sheet `imagery`). | No cockpit. A tab named Cameras that opens one imagery panel said something false. |
| `22868be1` | TR-3B easter egg: `tr3bRegistry`, the two sprites, the reclassify button and CSS, every flights branch. Empty `#military-awareness-panel` and the Contacts view body removed. | No game parts; nothing filled the panel. |
| `cbd5dc25` | Traffic and cctv sync chips (template, CSS, `shellFeedback`, reducer in `loadingFeedback.js`), ALPR, mapped-site, vector-tile and Overpass chip strings, radio filter codec in `layerState.js`, `data/idSwitches.js`. The 500 ms loading poll stays, renamed `_startLoadingPollTicker`. | Their layers are stubs; nothing can set these states. |
| `2dd514e4`, `ac83006d` | `i18n --prune` (71, then 1 entry per catalog) and the layer-panel group "Cameras" renamed "Imagery". | Catalogs match the code. |
| `79cd9e85` | Two tests that pinned removed radio and mapped-site paths updated. | |

Judgment calls beyond the brief: the traffic and cctv sync chips and
their CSS were removed whole, not only their strings (they had no data source);
`idSwitches.js` was deleted with the radio helpers (its only importer);
`tr3b`-only CSS and sprites went with the registry; the cyber CSS rules that
styled `.panel-collapse-btn` together with a cockpit selector were restored
for `.panel-collapse-btn` alone after the first cleanup dropped them. Rules
written as `body:not(.cockpit-mode) ...` lost that class's specificity.

### Not done

- 3D-model residue (see above).
- `selectedMilitaryTrackingId` and the `military_aircraft` follow kind: kept
  for permanent codes.

### Verification

Measured in a scratch copy of the final tree (`vite build`, then the sandbox
harness from the Astrolabe fork notes, with Esri and terrain tiles stubbed):

- Gates: `check-package-boundaries` and `check-import-directions` both exit 0.
- Unit tests: the full `node --test` run (per file, over `src` and `server`)
  on the tree at `0ecf56b4` had one failing file, `cssContentCaption.test`,
  fixed in the commit that adds this section and re-run alone (passes). The
  full run was not repeated after that fix.
- `dist/`: 46 MB before this slice, 32 MB after (`du -sh`; `cesium/` 14 MB,
  `assets/` 19 MB). `vite build` takes 7 s.
- Sandboxed frame (`sandbox="allow-scripts"`, CSP `script-src 'self'
  'wasm-unsafe-eval' blob:`, `?embed=1`): `gev:ready` after 1901 ms;
  `gev:view-applied` with `ok: true` (steps `stop_tracking`,
  `clear_annotations`, `camera` all ok); 0 page errors; 0 failed and 0 bad
  responses; 0 requests to the app's own `/api`; 0 console errors; 0 Cesium
  render errors; imagery tiles 14 READY, 0 FAILED at the snapshot (34 still
  transitioning); the globe draws (screenshot: stub checkerboard, 827
  distinct colours).
- Plain control (no sandbox, same build, same page): `gev:ready` after
  1723 ms; `gev:view-applied` `ok: true`; 0 page errors; 0 requests to `/api`;
  imagery tiles 39 READY, 0 FAILED.

Not verified:

- Only the embed view was run in a browser. The full application chrome (layer
  panel, dock, hotkeys, Cyber layout, phone shell, share-link restore in a real
  page) was not, so the stubs and removed panels are checked by the unit tests,
  the gates and a bundle build, not by clicking.
- `globe.tilesLoaded` is false in both runs, as in the runs before this slice:
  the stub tile server does not make Cesium declare the whole set loaded.
- Old share links that name a removed layer token (`c`, `m`, `g`, `i`, `r`,
  `t`, `p`, `h`, `z`) are rejected whole by the layer-state decoder, as any
  unknown token is; the retired looks open as Normal. Only the unit tests
  cover this.
- Commit `b0b0c05b` alone does not pass the gates; the commits after it do.
  Not every intermediate commit was run against the full test suite; the
  full suite was run on the tree at `0ecf56b4` only. The test fixes for the
  3D-model and look-retirement commits are in `b99d4dd2` and `9996f0e8`, so
  `015d0b27` and `b99d4dd2` alone leave some tests failing.

### Verification, slice 3

Scratch copy of the tree at `79cd9e85` (Node 22, `nice -n 10`, one run at a time):

- Gates: `check-import-directions` (576 modules) and `check-package-boundaries`
  exit 0, run after each commit.
- Unit tests, not the whole suite. The 32 test files changed in this slice: 653
  tests, 0 failed. `src/*.test.mjs` at the root: 880 pass. `ui/`,
  `layers/launches`, `layers/flights`, `share`, `view`, `app`, `data/layer*`,
  `data/flights*`, `data/aircraft*` (89 files): 791 tests; 3 failed
  (one radio and two mapped-site assertions on removed code), the two files were
  fixed and re-run (7 pass). `i18n/*.test.mjs` and `materialSymbolsSubset`: 111
  pass. Not run: `server/`, and `src/services/requests.test.mjs`, three of whose
  tests are cancelled on Node 22 even at the base. The suite as a whole was not
  run, so a file that imports a changed module and is outside those sets could
  still fail.
- `dist/`: 32,174,916 bytes before (`index-*.js` 2,564,535), 32,039,874 after
  (`index-*.js` 2,459,269): 135 KB less, 105 KB of it the main chunk.
  `assets/` 19.1 MB, `cesium/` 12.8 MB. `vite build` 6.4 s.
- Sandboxed embed frame (`allow-scripts`, `?embed=1`, CSP with
  `wasm-unsafe-eval`): `gev:ready` at 3068 ms; `gev:view-applied` `ok: true`
  (`stop_tracking`, `clear_annotations`, `camera`); 0 page errors, 0 failed
  and 0 bad responses, 0 console errors, 0 requests to `/api`; 825 distinct
  colours on the screenshot.
- Full app (not embed), Chromium with Esri and terrain stubbed, offline:
  0 page errors in every run. Desktop 1440x900: the Data Layers panel lists
  22 rows in the groups Movement, Imagery, Infrastructure, Events, Weather,
  Utilities; toggling Earthquakes and Satellites worked (both then show
  UNAVAILABLE, because the stub server has no USGS or CelesTrak). The Context
  panel opens with two tabs, CONTACTS and SPACE MISSIONS. Phone 390x844: the
  shell is on, no horizontal overflow, five tabs (Layers, Imagery, Context,
  Search, More) each open their sheet; the Imagery sheet shows the Recent
  Imagery panel once that layer is on and is empty before (as the Cameras sheet
  was). Share links built from a link the app made: unchanged opens with
  Satellites on; with removed tokens `c.z` added, or `c.z` alone, the link is
  rejected whole and Satellites stays off, no error.
- Seen: the full app asks its own `/api/google/tiles-token` at startup
  (`maps/googleTokens.js`; removed in slice 4) and `/api/celestrak/*` when
  Satellites is on. The embed view does neither.

Not exercised: a real device or touch input, the Material Symbols and Google
fonts (blocked in the harness, so icon names show as text), real tile and
feed data, keyboard navigation of the Context tabs, voice, the Cyber theme
switch, recording and clean view, hotkeys, and a share link with a removed
token that also carries camera and style fields from another app version.

## Slice 4: HUD readouts, copy, startup request

Each commit passes `check-import-directions` and `check-package-boundaries`.

| Commit | What | Why |
| --- | --- | --- |
| `a40399b6` | `hud.js` and its CSS: removed the "TOP SECRET // SI-TK // NOFORN" line, the random `KH11-nnnn` and `OPS-nnnn` ids, the random orbit and pass numbers, the REC dot, MGRS, GSD and NIIRS (a made-up sensor model), COLL, ONA (also from the summary line), BAND/BITS/LVL, the corner brackets and the two edge strips; dead CRT, NVG and FLIR entries; the `mgrs` import. Kept: mode, summary, UTC time, camera lat/lon, altitude above mean sea level, sun elevation, the vessel line and the bottom line (now lat/lon only). Tests that stubbed `mgrs` or read the removed ids updated; the Cyber CSS test now asserts the removed classes are absent. | No military look, no fake data. What stays is read from the camera and the app. |
| `bd3a3c87` | Copy. First-run line is now "Live aircraft, vessels, satellites and earthquakes on one globe — from public sources, shown as they are."; kicker "MISSION CONTROL · FIRST LAUNCH" is "WELCOME"; Contacts tile "Aircraft and vessels near you"; HUD button "Telemetry HUD (H)"; layout label "Tactical" is "Full" (the id `tactical` is unchanged, it is in share links); "Visible map targets" is "Visible map objects"; Contacts tab tooltip no longer names installations; Context standby text loses "sites" in all ten locales; "Scanning active events" is "Loading active events", "scanning nearby systems" is "looking for nearby systems"; web manifest description. The Contacts mode itself stays. Catalogs: new text translated by hand into the ten locales (the tool has no English fallback), then `i18n --prune`. | Plain, truthful copy. |
| `dbed6196` | Removed `maps/googleTokens.js`, the `google-token` route in `maps/google3d.js`, the `googleTokens` argument of `app/scene.js` and `standalone/application.js`, `server/standalone/google-token-unavailable.js` and its plugin entry, their tests. `mapStartup.test.mjs` pins that no token route exists. | The full app asked its own `/api/google/tiles-token` at startup. All data goes through Elysium and there is no key setup, so the request is gone in every mode (the embed gate from slice 1 is superseded). With no key it starts on the keyless globe. |

Judgment calls: the copy changes for tasks 2, 3 and 5 are one commit because
they touch the same catalog entries. The Cyber sonar (see below) was not
removed. `mgrs` is still in `package.json` and the lockfile (no importer left;
not removed because it needs a lockfile rewrite).

### Words checked in user-visible strings (slice 4)

Searched every English catalog key and the templates for intel, classified,
mission, sensor, recon, tactical, hostile, target, radar, surveillance,
cockpit, operator, strike, drone, military, detect and similar. Fixed: the
clear hits above. Left, listed here for the owner:

- Conflict-map layer `s2-ghostmaps` (live, in the Events group): product names
  "Kinetic 30d", "Border Crisis", "Iran Picture", "Iran Kinetic", "Yemen FLOT",
  "Intel Picture", "Latest Drop", from S2 Underground KMZ files on GitHub. This
  was the one real military-flavoured feed in the app. Not touched in slice 4;
  STUBBED off on 2 November 2026 (see "Stubbed, with how to turn back on").
- Cyber sonar: the "Sonar" toggle and its rings, range, intensity, sector and
  opacity sliders, the "Cyber sonar contact scanner" tooltip, `cyberSonar*.js`,
  `detection.js` integration and the `.hud-sonar` sweep element (visible only in
  the Cyber layout). It dims real contacts between sweeps; it detects nothing,
  but it looks like a naval sonar. STUBBED off on 2 November 2026.
- "Detection overlay (D)" and the "DETECT" button, `contactsDetectionPolicy`:
  the labels and callouts overlay for real objects.
- "Contacts" / "LIVE CONTACTS" as the name of the mode (sonar and military
  jargon), the Chinese catalogs' "目标"/"目標" for it (means target), and the
  `radar` icon on the Contacts tab, the first-run tile and the phone Context tab
  (the `radar` glyph is in the icon subset; a swap needs `index.html` too).
- Vessel types "MILITARY" and "DIVE OPS" (AIS ship-type codes 35 and 34, real
  data labels), aircraft class "Drone", the layer name "Military aircraft" and the
  "Shared military flight ..." messages (permanent share-link kinds).
- "SPACE MISSIONS", "Select {mission}" and the mission roster: real launches and
  spacecraft, kept.
- Title bar tagline "NO PLACE LEFT BEHIND" under "GOD'S EYE VIEW" (upstream
  branding; reads as surveillance).
- "sensor n/a" (satellite fire sensor), "UNSPECIFIED OPERATOR" (spacecraft
  operator), "Acquired {time}" (imagery date): real data terms, kept.
- CSS comments and the `first-run-scanline` decoration on the first-run card
  (cosmetic; the word "mission" in cyber.css comments).

### Verification, slice 4

Scratch copy of the tree after the last commit (Node 22, `nice -n 10`, one run
at a time):

- Gates: both exit 0 after each commit (574 modules after the token removal).
  `i18n` check: all ten catalogs complete, 1232 messages.
- Unit tests, focused: the seven test files changed or added to in this slice
  (`hudAltitudeDatum`, `hudDms`, `hudPageVisibility`, `cyberTheme`,
  `firstRunExperience`, `mapStartup`, `viteBuild`): 88 tests, 0 failed. The
  files that import or read what changed, run in three groups: 49 (hud tests,
  `hudLocality`, `cyberTheme`), 477 (22 files that name `hud.js`, the panel
  layout controller or the changed CSS, plus `src/i18n/*.test.mjs`), 582 (29
  files that read the welcome, context and display templates, `firstRunExperience`,
  `bikeshare`, `applicationShell` or `worldOverlay`, plus the i18n tests), and 77
  plus 21 for the map startup, vite config and standalone files: all pass, 0
  failed. Not run: the whole suite, `server/`, and `requests.test.mjs`.
- `dist/`: 32,039,874 bytes before, 32,028,458 after (`index-*.js` 2,459,269 to
  2,449,525). `vite build` 8.4 s.
- Sandboxed embed frame (`allow-scripts`, `?embed=1`, CSP with
  `wasm-unsafe-eval`): `gev:ready` at 2744 ms; `gev:view-applied` `ok: true`;
  0 page errors, 0 failed, 0 bad responses, 0 console errors, 0 requests to
  `/api`; 838 distinct colours on the screenshot.
- Full app (not embed), 1440x900, Esri and terrain stubbed, offline: nine
  seconds after load the app had made 0 requests to its own `/api` (before
  slice 4 it asked `/api/google/tiles-token`); 0 page errors, 0 console errors.
  First-run card text reads the new copy. With the HUD on it shows only
  `NORMAL`, the summary line, the UTC time, lat/lon, `ALT` and `SUN`, and
  `AIS: --`. The HUD button title reads "Telemetry HUD (H)", the layout list
  Full, Minimal, Cyber. The Context panel standby text reads "CONTACTS —
  nearest planes · vessels / SPACE MISSIONS — launches & orbital assets". The
  earlier full-app run (desktop, phone 390x844) also had 0 page errors, no
  horizontal overflow and the five tabs; its only `/api` calls were
  `/api/celestrak/*` after Satellites was switched on.

Not exercised: the HUD in the Minimal and Cyber layouts in a browser (CSS
and the tests only), the HUD on the phone shell (it hides the corner blocks),
a real device, real tile and feed data.

## Slice 5: dead model code, mgrs, QA scripts, self-audit

Each commit passes `check-import-directions` and `check-package-boundaries`.

| Commit | What |
| --- | --- |
| `581c21e1` | Deleted all 3D aircraft model code: `MODELS_3D_AVAILABLE`, `modelSpec.js`, `data/modelEligibility.js`, `aircraftModelLighting.js`, `modelVisualAnchor.js`, `trackedModelRegime.js`, `groundSnap` (service and data), `ui/aircraftDisplay.js`, model loading and handoff in `rendering.js`, `tracking.js`, `motion.js`, `lifecycle.js`, the model test seams and their tests. Share links that carry `models3d` (`e`) or `models3dMode` (`m`) still decode; the value is dropped silently (`RETIRED_LAYER_OPTION_TOKENS` in `layerState.js`, checked in `viewCodec.js`); they are no longer encoded. Tokens stay reserved. `docs/SHARE-LINK-FORMAT.md` says so. |
| `87ca82b7` | Removed the unused `mgrs` dependency with npm (worked; lockfile rewritten) and from `package-boundaries.json`. |
| `49dc42fc` | Deleted 15 QA scripts that drove removed features (`qa-alpr-journey`, `qa-camera-controls`, `qa-action-buttons`, `qa-scene-controls`, `qa-scene-dialog-file-drop`, `qa-status-badges`, `qa-form-fields`, `qa-sky-model-lighting`, `qa-heading-b3`, `qa-sprites-b5`, `qa-context-arrivals`, `qa-l9-matrix` with its verdict test, `qa-firstrun-mutations`, `qa-emergency-squawk`, `track-regression` with `test:track`); fixed the `qa-layer-token-twochar` injection marker; removed `test:track` from CONTRIBUTING, TESTING, README, the PR template and the maintainer workflow. |
| `3bde47d3` | Self-audit fixes: a leftover `_groundSnap.forget` call in `tracking.js` (a bug from the first commit, in the military-purge path), and `qa-floor-hold` and `qa-segmented-controls` no longer use the model controls. |

Judgment calls: `qa-l9-matrix` was deleted whole (it orchestrated the deleted
scripts). The other `qa-*` scripts were kept; they need a live server and were
only syntax-checked, except as noted below. The conflict-map layer
(`s2-ghostmaps`) and the Cyber sonar were not touched.

### Self-audit (slice 3 to 5 deletions)

- Imports of deleted modules: none (both gates agree; grep for the module names finds only comments).
- CSS: no selector for an id or class removed from the templates since slice 1.
- i18n: `npm run i18n` check, all ten catalogs complete, 1232 messages; nothing written.
- Dead exports: knip is not installed and was not fetched; not done.
- Still open (not fixed, owner to decide): the irBoost fog code in
  `visualSettings.js` (`_syncIrBoost`, `releaseIrBoost`, and the facade
  forwarders) is dead since the retired styles; a few comments mention
  `groundSnap` or 3D models (`meshFloorSampler.js`, `groundFloor.js`); `README.md`
  (Cockpit, voice, 3D hangar, CRT and military HUD lines, whole sections) and
  `docs/CURRENT-STATE.md`, `docs/PERFORMANCE.md` (3D model and Cockpit rows) are
  upstream text that still describes removed features and need a rewrite, not a
  patch; `package.json` has no remaining `test:track`.

### Verification, slice 5

Scratch copy (Node 22, `nice -n 10`, one run at a time). Three tests in
`src/services/requests.test.mjs` are cancelled on Node 22 even at the base;
ignored.

- Gates: both exit 0 after each commit.
- Unit tests, focused (the flights parts, `layerState`, `viewCodec`, aircraft
  data tests; 13 files, 141 tests, 0 failed), plus the files changed in the
  first commit run earlier. Not run: the whole suite, `server/`.
- `dist/`: 32,028,458 bytes before, 32,001,419 after (`index-*.js` 2,449,525 to
  2,422,521). `vite build` 6.3 s.
- Sandboxed embed (`allow-scripts`, `?embed=1`, CSP with `wasm-unsafe-eval`):
  `gev:ready` at 2835 ms; `gev:view-applied` ok; 0 page errors, 0 failed, 0 bad
  responses, 0 console errors, 0 requests to `/api`.
- Full app, desktop and phone, offline stubs: 0 page errors, 0 console errors,
  no horizontal overflow, five tabs; no `/api` calls until Satellites was
  switched on (then only `/api/celestrak/*`). Old share codes with removed
  tokens load without errors.

Not exercised: the `qa-*` scripts against a live server, real feeds.

## Slice 6: documentation

Docs only; no source, test or package file was touched.

| File | What | Why |
| --- | --- | --- |
| `screen/README.md`, `screen/docs/CURRENT-STATE.md`, `screen/docs/PERFORMANCE.md`, `screen/docs/KNOWN-ISSUES.md`, `screen/SECURITY.md`, `screen/TESTING.md`, `screen/CONTRIBUTING.md`, `screen/docs/CODE-BOUNDARIES.md` | Rewritten to describe only what the app is now. `CURRENT-STATE.md` went from about 6,400 lines of per-change notes to a short page (the old text is in git); `PERFORMANCE.md` keeps only the upstream rows for things that still exist and says they were not measured on this fork. | They described Cockpit, voice and AI, key setup, 3D models, the removed looks and layers, MCP, Pinokio and Docker. The MIT notice and credit to Bilawal Sidhu are kept in the README. |
| `screen/DATA_SOURCES.md` | Rows, notes and sections for CCTV, Street Level, Mapillary, KartaView, Panoramax, Google Street View, radio, local receivers, TomTom, ALPR, military names, Overture, OpenFreeMap, Open-Meteo, Google News, GDELT, Kartverket and the Bhote Koshi pack removed. Everything else, including licences, is unchanged. | Sources of removed features. |
| `screen/docs/SHARE-LINK-FORMAT.md` | Retired styles and panels marked, the military entity kind marked reserved, a list of the codes that stay reserved. No code or number changed. | Keep the format document true; permanent tokens stay reserved. |
| `screen/docs/APPLICATION.md`, `UI-OWNERSHIP.md`, `panel-surfaces.md`, `I18N.md`, `TRANSLATORS.md`, `opensky-auth.md`, `THIRD_PARTY_NOTICES.md`, `src/data/local_data/natural_earth/README.md`, `.github/pull_request_template.md`, `changelog.d/*` | Lines about voice, Cockpit, radio, CCTV, Pinokio and similar edited out; five changelog fragments reworded. | Removed features. |
| Deleted: `screen/docs/VOICE-OWNERSHIP.md`, `TOOLS.md` (AI tool catalogue and MCP), `MAINTAINER_WORKFLOW.md`, `PR_REVIEW_SANDBOX.md`, `docs/media/` (demo GIFs of voice, Cockpit, 3D models, removed layers), `scripts/fixtures/voice/README.md`, `.agents/skills/community-pr/`, four changelog fragments (director, authoring panel, A22 webcams, HUD AI summary) | Deleted. | Only about removed features, or upstream's maintainer workflow. |

Left stale on purpose (owner to decide): the per-language glossaries in
`screen/docs/translations/` still use removed terms as examples;
`screen/CHANGELOG.md` is upstream history; `screen/tools/README.md` describes
the imagery CLI scripts; `docs/reader-report-1.md` is the Reader's report on
upstream and is a record, not a description of this app.

## Inventory (status after slice 2)

The list as written before slice 2, with a **Status** line added above each
entry. Paths are under `screen/`. Line numbers are upstream's (8978801dfd2a);
the code they point at is deleted or has moved, so do not use them to find
current code. Entries marked DONE are covered by the table above.

### How the app makes a layer "required" (read this first)

Four independent checks tie the app to specific layer ids. Deleting a layer
without handling all four stops the app starting.

1. `src/app/catalog.js:1-16` `CONTROL_LAYER_IDS` lists 14 ids the control
   surface needs; `catalogControlServices` (line 50-60) throws
   `Control layer missing from catalog: <id>` for any that is not registered.
   Of the owner's ruled-out layers this includes **military**
   (`militaryFlightsLayer`), **military-awareness**, **military-installations**,
   **traffic**, **cctv**, **street-level**, **radio** and **local-adsb**. The
   resulting objects are passed to `src/ui/applicationShell.js` as
   `services.<role>` (destructured at lines 98-107) and then to cockpit,
   layer panels, voice and context code, which call methods on them without
   null checks on the layer object itself (for example `cockpitContext.js:30`,
   `cockpitTrackingController.js:14,44,92`; `locationNavigation.js:176-188`
   calls `trafficLayer.beginWorldJump?.()` / `endWorldJump?.()`, optional
   method calls on an object that is not itself checked).
2. `src/app/sourceComposition.js:8-45` `CATALOG_SOURCE_CONTRACTS` lists the
   layer ids each source feeds; `createAvailabilityLookup` (line 99) throws
   `Missing source consumer: <id>` if a listed id is not registered. Entries
   naming ruled-out layers: `military` (15), `cctv` (16-19), `radio` (21),
   `traffic` (22-31), `installations` (33-36), `alpr` (39).
3. `src/app/catalog.js:20-45` `createLayerCatalog` throws if the metadata list
   and the layer list do not match one to one ("Unmatched or duplicate catalog
   metadata", "Catalog metadata is incomplete"). The metadata is
   `LAYER_STATE_REGISTRY` (`src/data/layerState.js:567-717`, one entry per
   layer id with its share-link token, also used by `src/share/viewCodec.js:20,782`
   and `src/data/layerStateCoordinator.js:372-433`) plus
   `LOCAL_ONLY_LAYER_METADATA` (`src/app/constructCatalog.js:42-44`, which is
   only `local-adsb`).
4. `src/app/constructCatalog.js:74-77` always creates the
   `militaryRegistry`, and `flights` is built with it (lines 85-90): see
   "military" below.

An omitted data source does not need a stub: `resolveCatalogSources`
(`sourceComposition.js:55-77`) replaces a missing source with an object whose
methods throw `SourceUnavailableError`, and the layer reports "data source not
configured". So the cheapest first step for a hard-required layer is to drop
its entry from `src/standalone/layerSources.js:33-61` (and from
`src/app/sources.js:16-21`), not to delete its code.

Other places that enumerate layer ids and must be edited together with the
above: `src/ui/layerPanel.js:41-96` (`PANEL_GROUPS`),
`src/data/layerState.js:481-505` (token table), `src/voice/layerManifest.js`
(voice only), `src/ui/layerNames.js:53`, `src/ui/styles/cyber.css:634,669`,
and `src/app/embed.js:24` / `src/view/index.js:53-54` (`military_aircraft` as
a follow target).

### Layers

**Status:** STUBBED (`b0b0c05b`), implementation DELETED (`8427f8dc`). The aircraft classification registry is an inert object.

**military** (layer id `military`; flights marked military)
- Code: `src/layers/military/` (whole directory), `src/app/layers/militaryFlights.js`,
  `src/data/militaryFlights.js`, `src/data/militaryRegistry.js`,
  `src/layers/aircraft/classification.js`, `src/data/militaryNames.js`,
  `src/sources/militaryTileGeometry.js`, `scripts/build-military-names.py`,
  `scripts/military-names-*`, `server/providers/aircraft/`, `/api/military`
  calls at `src/sources/live/standalone.js:133,143` and
  `src/tools/services.js:55`.
- Hard-required: yes, checks 1, 2 and 3 above (`catalog.js:4`,
  `sourceComposition.js:15`, `layerState.js:626`, `constructCatalog.js:91-96`).
  Stub, do not delete.
- What else depends on it:
  - `flights` is built with the military registry: `constructCatalog.js:74-90`,
    `src/app/layers/flights.js:19,33`, `src/layers/flights/index.js:35`,
    `lifecycle.js:17`, `queries.js:29`, `rendering.js:49`,
    `snapshotRenderer.js:15-44`, `tracking.js:47`. `isMilitaryIcao` is called
    in the render path of civil flights; the registry has to stay as a
    function that answers false (or those calls be removed).
  - `src/app/sources.js:14,39-41` configures the registry from the military
    source.
  - Cockpit, context and voice: `ui/cockpitCoordinator.js:36-96,199-311`,
    `cockpitSignals.js:126-157`, `cockpitInstruments.js:158`,
    `cockpitTrackingController.js:14-44`, `ui/aircraftDisplay.js:23`,
    `ui/layerBindings.js:202`, `ui/navigationController.js:96`,
    `ui/contextLayerChanges.js:235,254`, `ui/visualSettings.js:390,1721`
    (`irBoost`), `data/layerState.js:461-466` (tracking option owner),
    `data/layerState.js:919-920`.
  - `layers/awareness` (below) reads it.
  - Our rule is to drop military aircraft at the door in our own source, so
    nothing in this layer is needed; the layer id only has to exist.

**Status:** STUBBED, DELETED (`8427f8dc`).

**military-installations** (`military-installations`)
- Code: `src/layers/installations/`, `src/app/layers/militaryInstallations.js`,
  `src/data/militaryInstallations.js`, `src/data/militaryInstallationData.js`,
  `src/data/installationFeedback.js`, `server/providers/military-installations*`,
  `/api/military-installations` at `src/layers/installations/source.js:215`
  and `/api/google/text-search` at line 261, `scripts/qa-installation-*.mjs`.
- Hard-required: yes, checks 1, 2 and 3 (`catalog.js:13`,
  `sourceComposition.js:33-36`, `layerState.js:637`,
  `constructCatalog.js:101-104,153`). Stub.
- Imported by: `src/standalone/layerSources.js:14,49`,
  `src/tools/services.js:18,85`, `src/ui/applicationShell.js:1000-1011`
  (passed into the context panel as `installations`),
  `layers/awareness/` (it is one of the four inputs,
  `constructCatalog.js:149-154`), `src/ui/styles/cyber.css:669`.

**Status:** STUBBED, DELETED (`8427f8dc`).

**military-awareness** (`military-awareness`): not in the owner's list, but it
is the "nearby contacts" layer that Roadmap says we keep and feed from our own
data; listed because it is built from `military` and `installations`.
- Code: `src/layers/awareness/`, `src/app/layers/militaryAwareness.js`,
  `src/data/militaryAwareness.js`.
- Hard-required: yes (`catalog.js:11`, `layerState.js:632`,
  `constructCatalog.js:149`). It takes `flights, military, vessels,
  installations` as constructor inputs, so the constructor call has to change
  when those do. Used by `ui/cockpitContext.js:30`, `cockpitCoordinator.js:114-211`,
  `cockpitSignals.js:208`, `cockpitTrackingController.js:92`.

**Status:** STUBBED, DELETED (`ea95db5f`), with the cameras panel, focus, gizmo and sources.

**cctv** (`cctv`; agency and private camera feeds)
- Code: `src/layers/cctv/` (whole directory), `src/app/layers/cctv.js`,
  `src/data/cctv.js`, `src/data/cctvFootprint.js`, `src/sources/cctvTypes.js`,
  `src/cctvFocusPolicy.js`, `src/cctvFocusRequest.js`, `src/ui/cctv*.js`
  (`cctv.js`, `cctvBindings.js`, `cctvCalibration.js`, `cctvControls.js`,
  `cctvFrames.js`, `cctvPresentation.js`, `cctvVideo.js`),
  `src/ui/styles/cctv.css`, `server/providers/cctv*`,
  `config/cctv_sources.*.json`, `scripts/dev-cctv.sh`,
  `scripts/precompute-cctv-heights.mjs`, routes `/api/cctv/*`
  (`layers/cctv/source.js:53-56`, `sourcePolicy.js:1-3`).
- Hard-required: yes, checks 1, 2 and 3 (`catalog.js:6`,
  `sourceComposition.js:16-19`, `layerState.js:595-600`,
  `constructCatalog.js:141`). Stub.
- Imported by: `src/standalone/layerSources.js:9,44`,
  `src/tools/services.js:14,61`, `src/ui/applicationShell.js:280,499,743,
  1171-1247` (panel and shortcut wiring), `src/ui/layerBindings.js:67`,
  `src/voice/gevActions.js:1295,1634-1784`, `src/voice/layerManifest.js:322`,
  `src/data/layerState.js:386-411` (option set), and `layerPanel.js:56`.
- Estimated camera poses are part of this layer: `layers/cctv/calibration.js`,
  `headingConfidence.js` (the "HDG ... (ESTIMATED)" token and dashed wireframe),
  `geometry.js`, `ground.js`, `modelSpecs.js` (camera hardware specs that
  replace an estimated field of view), `ui/cctvCalibration.js`. They go with
  the layer; no separate stub is needed.

**Status:** STUBBED, DELETED (`8427f8dc`), with the TomTom proxy.

**traffic** (`traffic`; simulated vehicles over road geometry, plus TomTom flow)
- Code: `src/layers/traffic/` (whole directory; the moving dots are produced
  by `animation.js`, `model.js`, `retention.js`, with `flow*.js` fetching
  real flow tiles), `src/app/layers/traffic.js`, `src/data/traffic.js`,
  `src/data/traffic*.js`, `src/data/tomtomTiles.js`, `server/providers/traffic.js`,
  routes `/api/tomtom/*` (`layers/traffic/source.js:219`, `flowSource.js:7`),
  `scripts/qa-traffic-*.mjs`, `scripts/traffic-fixtures.mjs`.
- Hard-required: yes, checks 1, 2 and 3 (`catalog.js:2`, `sourceComposition.js:22-31`,
  `layerState.js:301`, `constructCatalog.js:140`). Stub. A stub must still
  answer `beginWorldJump` / `endWorldJump` (`ui/locationNavigation.js:176-188`).
- Imported by: `src/standalone/layerSources.js:12,46`,
  `src/tools/services.js:26,70`, `src/ui/shellFeedback.js:169`,
  `src/ui/applicationShell.js:98,327,494`, `layerPanel.js:49`,
  `src/voice/layerManifest.js:286`.
- Transit vehicles (`layers/transit`) are real and stay; they share no code
  with `traffic` except `app/layers/transit.js:5` using the same overlay host.

**Status:** STUBBED, DELETED (`ea95db5f`), with the radio panel and the SDR card.

**radio** (`radio`; internet radio stations, plays audio)
- Code: `src/layers/radio/`, `src/app/layers/radio.js`, `src/data/radio.js`,
  `src/sources/radioBrowser.js`, `src/ui/radioBindings.js`,
  `src/ui/styles/radio.css`, `src/voice/realtimeRadio.js`,
  `server/providers/radio*`, routes `/api/radio/*`
  (`layers/radio/policy.js:3`, `source.js:22`), `scripts/qa-radio.mjs`.
- Hard-required: yes, checks 1, 2 and 3 (`catalog.js:7`, `sourceComposition.js:21`,
  `layerState.js:433`, `constructCatalog.js:142`). Stub.
- Imported by: `src/standalone/layerSources.js:10,45`, `src/tools/services.js:21,62`,
  `src/ui/applicationShell.js:1000-1104` (radio panel, the local-SDR panel
  also takes `radio`), `src/ui/contextLayerChanges.js:32`,
  `src/voice/gevActions.js:416,1928-2264`, `voice/realtimeTurns.js`,
  `voice/geminiSession.js`, `voice/sessionCommands.js:64`.

**Status:** STUBBED, DELETED (`ea95db5f`); `view.js` and `tileMath.js` stay for `ghostMaps`.

**street-level** (`street-level`; Mapillary and Panoramax photo coverage)
- Code: `src/layers/streetLevel/` (whole directory including `providers/`),
  `src/app/layers/streetLevel.js`, `src/ui/streetLevelControls.js`,
  `src/ui/streetLevelPresentation.js`, `src/ui/styles/street-level.css`,
  `server/providers/mapillary*`, routes `/api/mapillary/*`
  (`providers/mapillary/source.js:63-64`).
- Hard-required: yes, check 1 (`catalog.js:6`) and 3 (`layerState.js:412,670`,
  `constructCatalog.js:133`). It is not in `CATALOG_SOURCE_CONTRACTS`. Stub.
- Imported by: `src/standalone/layerSources.js:23,58`,
  `src/ui/applicationShell.js:1134-1161,1787`, `src/ui/layerNames.js:53`,
  `src/voice/layerManifest.js:354`, `src/testSupport/streetLevelFakes.mjs`.

**Status:** STUBBED, DELETED (`ea95db5f`), with `src/sdr/` and the local-receivers route.

**local-adsb** (`local-adsb`; hardware receiver on the operator's machine)
- Code: `src/layers/localAdsb/`, `src/app/layers/localAdsb.js`, `src/sdr/`,
  `src/ui/localSdr*.js`, `docs/LOCAL-RECEIVERS.md`,
  `server/providers/local-receivers.js`, route
  `/api/local-receivers/aircraft` (`layers/localAdsb/feeds.js:7`; the
  request is already gated off in embed mode, see the table above).
- Hard-required: yes, check 1 (`catalog.js:14`); registered with
  `LOCAL_ONLY_LAYER_METADATA` (`constructCatalog.js:42-44`) instead of the
  share-link registry, and built at `constructCatalog.js:116-121` from
  `flights.getParams()`. Stub.
- Imported by: `src/ui/localSdrPresentation.js:1`,
  `src/ui/applicationShell.js:107,497,1098-1104`, `layerPanel.js:47`,
  `src/sdr/adsbDecoder.js:5-6,344,458` (reads its policy).

**Status:** DELETED (`ffa4273c`); no stub needed.

**alpr-cameras** (`alpr-cameras`; licence-plate readers; ruled out by the
Roadmap decision on police data, not named in the task list but found in the
same group): `src/layers/alpr/`, `src/app/layers/alprCameras.js`,
`src/data/alprCameras.js`, `server/providers/overpass*` (shared), route
`/api/overpass` (`layers/alpr/policy.js:9`). Registered at
`constructCatalog.js:132`, contract `sourceComposition.js:39`,
`layerState.js:579`. Check 2 applies (a contract names it), but it is not in
`CONTROL_LAYER_IDS`, so it can be deleted outright once the contract entry,
the panel id (`layerPanel.js:61`),
the layer-state entry and `standalone/layerSources.js:17,52`,
`tools/services.js:11,76` are removed.

### Parts

**Status:** DONE (`015d0b27`): models and toggle deleted, code gated off. Dead model data remains (see residue).

**3D aircraft models**
- `public/models/*.glb` (airplane, atr72, b789, bell206, c172, citation2,
  jet, mq9; `public/models/README.md`), loaded by URL at
  `layers/flights/policy.js:42` (`PLANE_MODEL_URL`),
  `layers/military/policy.js:68,132`, `layers/flights/modelSpec.js`,
  `layers/flights/rendering.js:416`, `layers/flights/state.js:17-21`,
  `layers/localAdsb/models.js`, `app/layers/flights.js` and
  `app/constructCatalog.js:85-90` (the `resolveAsset` argument that maps
  model URLs to the asset host).
- Not hard-required by the catalog: flights also draws icons
  (`data/aircraftIcons.js`); the models appear at close range. Removing the
  models means removing the close-range model branch in
  `layers/flights/rendering.js` and the `resolveAsset` plumbing. Also the
  size budget (R8): `public/models` is the largest binary payload.

**Status:** NOT DONE (see "Not done"). Camera poses estimated for cameras went with the CCTV layer.

**Estimated launch trajectories**
- `layers/launches/paths.js` (`reconstructedAscentPath` at 215, used at 479;
  exported at 578), `layers/launches/replay.js`, `layers/launches/camera.js`
  (replay camera), `layers/launches/overlays.js:162-653` (trajectory labels
  and replay marker), `layers/launches/orbitRendering.js`,
  `layers/launches/model.js:171,214` (carries a `trajectory` field only when
  the provider supplies one), `layers/launches/index.js:81-88`.
- The layer `rocket-launches` itself stays (`catalog.js:13` requires it).
  The estimated parts are woven into it; `launches/ingestion.js:164` and
  `app/constructCatalog.js:139` also tie it to the `satellites` layer (the
  replay restores satellites), so `createApplicationLaunches({ satellites })`
  has to change with the replay.

**Status:** DONE (`06e142a4`).

**Director and demo scenes**
- `src/director/` (document, playback, timeline, packs, sharing),
  `src/scenes/` (director, recipes, packs, `nepalEvidencePack.js`),
  `src/data/scenePick.js`, `src/data/bhoteKoshi*.js`
  (flood demo, 3700+ lines in `bhoteKoshiEvent.js`),
  `public/events/bhote-koshi-2026/`, `src/ui/styles/scenes.css`,
  `src/ui/styles/bhote-koshi.css`, `docs/DIRECTOR*.md`, `docs/SCENE-DOCUMENT.md`,
  `scripts/qa-director-*.mjs`, `scripts/build-admin-packs.mjs`.
- Hard-registered: the flood demo layers `bhote-koshi-2026` and
  `bhote-koshi-locator` are built unconditionally at
  `constructCatalog.js:110-114` and listed in the layer-state registry
  (`layerState.js:584-592`). They are not in `CONTROL_LAYER_IDS`, so deleting
  them needs only the catalog entries, those two registry entries, the
  imports at `constructCatalog.js:35-36`, and
  `app/tools.js:42-43` (`attachSceneController`).
- `SceneDirector` is constructed unconditionally at `app/tools.js:1,36-45`
  and passed to the voice runner (`tools.js:171,194`) and to
  `agent/worldPacket.js:101,148`. `standalone/tools.js:1,6-17` builds the
  scene data pack source. `app/application.js` exposes `onSceneDirector`.

**Status:** DONE (`20bb3acb`); the NEWS tab went with the cockpit (`3baad307`).

**News briefs**
- `ui/cockpitBriefing.js` (the NEWS tab, `ACQUIRING REGIONAL NEWS`, lines
  91-308), `ui/cockpitPresentation.js:38-56`, `ui/cockpitController.js:178-179`,
  `ui/cockpitInstruments.js`, `server/providers/regional*` (Google News RSS;
  credit entry `data/dataCredits.js:195`), route `/api/regional-brief`
  (`services/requests.js:24,162-168`), `tools/queries/brief.js`,
  `overlays/worldOverlayAllocation.worker.mjs:1022-1041` (draws "NEWS" tags
  on overlays).
- Not required by the catalog; part of cockpit. `services.regional` is built
  in `services/requests.js` and consumed by `cockpitBriefing.js:152-175`
  (`regionalDistanceM`).

**Status:** DONE (`8165f0e1`), after extracting the view actions to `src/app/viewActions.js`.

**Its own voice and AI (OpenAI, Gemini; hud-summary)**
- `src/voice/` (whole directory), `src/agent/`, `src/ui/styles/voice-card.css`,
  `voice-cost.css`, `server/providers/openai*`, `server/providers/gemini*`,
  `server/standalone/voiceTools.js`, `server/mcp/panelKey.js`,
  `src/localRequestGate.mjs`, `scripts/voice-bench/`, `scripts/qa-voice-*.mjs`.
  Routes: `/api/realtime/*`, `/api/gemini/token` (`voice/geminiSession.js:146`),
  `/api/openai/hud-summary` (`services/requests.js:26,178-203`,
  used by `hud.js:882` and `tools/queries/brief.js:235`).
- **Do not delete `src/voice/gevActions.js` blindly:** embed views are
  applied through its action runner. `app/tools.js:184-208` builds
  `initGevVoiceCommands` and hands `voiceCommands.runner` to
  `installViews` (`app/embed.js:247-312`), which runs `track_entity`,
  `annotate_map`, `stop_tracking` etc. through it
  (`embed.js:182,221,262`). The `gev:view` message of the screen's API
  depends on that, so the runner must be extracted before the rest of
  `voice/` goes. It also reads layer ids `cctv`/`radio`/`military`
  (`gevActions.js:160,416,541,1295,1634,1928`).
- Registered unconditionally in `app/tools.js:7,184-202`; the
  `voice: { supportedProviders, panel, toolCatalog }` options come from
  `standalone/tools.js:18-24`, `standalone/toolCatalog.js`.
- `src/voice/layerManifest.js` enumerates layer ids for voice only.
  `src/search/` (place search, `/api/google/*`) is separate and is kept.

**Status:** DONE (`8165f0e1`); `keySetupCore.mjs` kept as the key registry only.

**Key setup flows**
- `src/keySetup.js` (calls `/api/setup/status`, `/api/setup/keys`,
  `/api/realtime/oauth-*`, lines 178, 416, 521, 615, 642),
  `src/keySetupCore.mjs`, `src/ui/keyGuidance.js`,
  `src/ui/templates/provider-settings.html`, `src/ui/styles/provider-settings.css`,
  `server/standalone/key-setup*.js`, `scripts/setup-doctor.mjs`,
  `scripts/google-server-key.mjs`, `src/maps/googleTokens.js`
  (now skipped in embed mode).
- `startupChrome.js` already skips it in embed mode (table above); removing
  it means dropping `initializeSettings` in `app/startupChrome.js:10,38-44`
  and `standalone/startupChrome.js`.
- **Imported elsewhere:** `keySetupCore.mjs` is imported by
  `maps/availability.js:1`, `maps/defaultSources.js:3` and `mapStackChips.js:13`
  for `keySetupRequirementEnvVars` (which map stacks need which key), so
  that file must be kept or its one function moved. `ui/layerPanel.js` and
  `ui/streetLevelPresentation.js` also reference key guidance.

**Status:** DONE (`4c7a4d54`).

**Pinokio**
- `pinokio/` (`pinokio.js`, `install.js`, `start.js`, `update.js`, `reset.js`,
  `_ENVIRONMENT`), `scripts/pinokio-*.mjs` (environment, install, preflight,
  reset, start, update), `src/pinokio*.test.mjs` (4 test files),
  `src/dockerLauncher.test.mjs`, `Dockerfile` / `compose.yaml` (launchers).
- Not imported by any runtime code. Mentioned in comments in
  `src/keySetup.js`, `src/keySetupCore.mjs`, `server/standalone/key-setup.js`,
  `server/providers/places/google.js`, `server/providers/openai/rate-limit.js`,
  and in `SECURITY.md`, `.dockerignore`, `.prettierignore`.

**Status:** DONE (`f90f7557`); the rest of `src/tools/` went in `8165f0e1`.

**MCP**
- `server/mcp/` (`server.js`, `stdio.js`, `plugin.js`, `panelKey.js`,
  `services.js`), `src/tools/mcp/`, `package.json:56` (`mcp` script) and
  `package.json:282` (`./tools/mcp` export), `docs/MCP_SETUP.md`,
  `src/tools/mcpPanelKey.test.mjs`. `src/tools/` (the tool catalog:
  `catalog.js`, `queries/`, `services.js`) is shared with the voice code and
  the panel build, so only `mcp/` and `server/mcp/` are independent;
  `tools/services.js` builds a source for every ruled-out layer (lines 11-85).

**Status:** DONE (`3baad307`) as an inert stand-in, `src/ui/inertCockpit.js`; the stand-in and the plumbing that fed it were removed in slice 3 (`158ca0c9`).

**Cockpit** (first-person aircraft view and its briefing, instruments, vision)
- `src/ui/cockpit*.js` (about 14 files: `cockpit.js`, `cockpitBriefing.js`,
  `cockpitCamera.js`, `cockpitContext.js`, `cockpitController.js`,
  `cockpitCoordinator.js`, `cockpitDisplayPortal.js`, `cockpitInput.js`,
  `cockpitInstruments.js`, `cockpitLayout.js`, `cockpitPresentation.js`,
  `cockpitSignals.js`, `cockpitTrackingController.js`), `src/cockpitMath.js`,
  `src/cockpitTracking.js`, `src/cockpitUtilityLayout.js`,
  `src/cockpitVisionPolicy.js`, `src/cockpitCloudEffects.js`,
  `src/ui/templates/cockpit.html`, `src/ui/styles/cockpit.css`,
  `scripts/qa-cockpit-*.mjs`.
- Not hard-required by the catalog. Wired unconditionally:
  `ui/applicationShell.js:16,35,128,156,261,319,349,376-417`
  (`CockpitCoordinator`, `cockpitView`), `ui/visualSettings.js`
  (`_setCockpitVision`, lines 702-707 in the shell), `app/controls.js:4,45-58`
  (`initCockpitCloudEffects`, also returned and used by `app/tools.js:21`),
  `layers/awareness/rendering.js`. Cockpit reads `militaryFlightsLayer`
  and `militaryAwarenessLayer` (see military), so remove it before or with
  them.

**Status:** DONE (`d98bc2e3`): boxes, scanlines and focus ring removed; labels kept.

**Fake detection boxes** (the "DETECT" brackets and boxes drawn around
contacts, with density and mode settings)
- `src/data/detection.js` (1662 lines), `detectionDraw.js`,
  `detectionCohort.js`, `detectionPolicy.js`, `detectionPresentation.js`,
  `detectionRenderDemand.js`, `src/contactsDetectionPolicy.js`,
  `src/overlays/worldOverlay*.js` (the overlay canvas and its paint lanes),
  `src/ui/displayBindings.js:5`, `src/ui/visualSettings.js:28,38`,
  `src/ui/effects.js`.
- **Not removable as such:** the aircraft and vessel labels are drawn by this
  code. `app/layers/flights.js:7`, `aisLiveVessels.js:6`,
  `militaryFlights.js:7` import `data/detectionDraw.js` as `labels`;
  `app/layerPresentation.js:3` and `app/layers/localAdsb.js:9` call
  `markDetectionSourcesChanged`; `data/labelArbiter.js:5`,
  `share/viewCodec.js:31` and `sharelink.js:6` read `detectionPolicy.js`
  (the share-link codec carries detection mode and density). Nearly every
  layer's `app/layers/*.js` registers with `overlays/worldOverlay.js`
  (`radio.js:3`, `transit.js:5`, `cctv.js:5`, `bikeshare.js:5`,
  `rocketLaunches.js:3`, `firms.js:7`, `ghostMaps.js:4`, `perimeters.js:8`,
  `satellites.js:5`, `alprCameras.js:6`, `overlayHost.js:3-6`), so the overlay
  host stays; what goes is the box and bracket painting and the labels'
  dependency on it.
- **Surprising default:** the first-load baseline turns detection on at
  75% density (`ui/visualPresets.js:46,59-60`, `MILITARY_DETECTION_PRESET`
  at line 37) and Contacts mode forces it on
  (`contactsDetectionPolicy.js` header). Embed mode shows no boxes because
  there are no contacts, but they will appear as soon as there are.

**Status:** DONE for CRT, night vision and FLIR (`b99d4dd2`). The `tactical` HUD variant and the Cyber theme stay; Cyber no longer selects a look.

**Military HUD styling**
- `src/hud.js` (1121 lines; `MILITARY_STYLES` at 141, auto-activation at
  1004, layout variants `tactical`, `minimal`, `cyber` at 12, 1056-1059),
  `src/hudLayouts.js`, `src/hudLayoutPolicy.js`, `src/hudLocality*.js`,
  `src/hudPlaceLookup.js`, `src/hudSummaryResponse.js`,
  `src/styles/{retro,surveillance,thermal,noir,anime}.js` (post-process
  shaders: CRT, night vision, FLIR, noir, anime), `src/ui/visualPresets.js`
  (`STYLES` at 12-18; `hudVariant: 'tactical'` at 46, 79, 94, 109;
  `MILITARY_DETECTION_PRESET`), `src/ui/visualSettings.js` (1730 lines),
  `src/ui/visualEffects.js`, `src/cyberSonar*.js` (3 files, `ui/cyberSonarControls.js`),
  `src/bloom.js`, `src/ui/styles/cyber.css`, `src/scopeMask*.js`,
  `src/ui/templates/display-controls.html`, `src/ui/templates/hud-loading.html`.
- Not hard-required by the catalog. Consumers: `ui/composition.js:35-90`
  (initDetection and HUD), `app/controls.js` (`styleManager`, created by
  `standalone/controls.js`), `app/tools.js:21-24`, `embed.js` (`shell.setCleanView`,
  line 267, hides the HUD for embedding; `ui/styles/embed.css`).
  `hud.js:882` also calls the OpenAI summary (see voice).
