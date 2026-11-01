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

## Changes versus upstream 8978801dfd2a

| File | What | Why |
| --- | --- | --- |
| `screen/src/app/opaqueOrigin.js` (new) | `installOpaqueOriginImageLoading(Cesium)`: when `globalThis.origin === 'null'` (a frame sandboxed without `allow-same-origin`), wraps `Cesium.Resource._Implementations.createImage` so every http(s) image is loaded with `crossOrigin`. Returns false and does nothing in any other origin. | Cesium's `isCrossOriginUrl` compares the URL with `window.location`, which in an opaque origin says "same host", so same-host images (the Milky Way skybox) load without `crossOrigin` and `texImage2D` throws a SecurityError that stops rendering. `isCrossOriginUrl` is not configurable (cannot be replaced); the image loader it feeds can. The asset host must send `Access-Control-Allow-Origin: *`. Roadmap R1 and the sandbox spike. |
| `screen/src/app/scene.js` | Imports and calls `installOpaqueOriginImageLoading(Cesium)` once, just before the viewer is created (before the first image is requested). | Where Cesium is first configured. |
| `screen/src/standalone/application.js` | In embed mode (`isEmbedded()`), `googleTokens` is `null` instead of `createGoogleTokenSource()`. | That source GETs `/api/google/tiles-token` from the app's own host. Embedded, the host is ours and has no such route. |
| `screen/src/standalone/startupChrome.js` | In embed mode `initializeSettings` is left out, so `initKeySetup` does not run. | `initKeySetup` GETs `/api/setup/status`. An embedded globe has no key setup. |
| `screen/src/voice/realtimeDiagnostics.js` | `postDebugLog` returns at once in embed mode. | It sent a credentialed `sendBeacon` / `fetch` to `/api/realtime/debug-log` on the app's own host. |
| `screen/src/services/requests.js` | `summary.configured()` resolves `false` in embed mode, without a request. | It probed `/api/openai/hud-summary/status`; `false` means the app never offers a summary and never calls `/api/openai/hud-summary`. |
| `screen/src/layers/localAdsb/feeds.js` | The feed's `request()` throws "local receiver route unavailable" in embed mode, before any fetch. | It polled `/api/local-receivers/aircraft`. A missing route already leads to the same state (`configured: false`, not polling), so behaviour is the same without the request. |

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

## To remove next (inventory)

Read-only list: nothing below has been removed. Paths are under `screen/`.
Line numbers are for upstream 8978801dfd2a plus the changes above (only
`standalone/application.js`, `standalone/startupChrome.js`,
`services/requests.js`, `voice/realtimeDiagnostics.js` and
`layers/localAdsb/feeds.js` have shifted by a few lines).

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

**Pinokio**
- `pinokio/` (`pinokio.js`, `install.js`, `start.js`, `update.js`, `reset.js`,
  `_ENVIRONMENT`), `scripts/pinokio-*.mjs` (environment, install, preflight,
  reset, start, update), `src/pinokio*.test.mjs` (4 test files),
  `src/dockerLauncher.test.mjs`, `Dockerfile` / `compose.yaml` (launchers).
- Not imported by any runtime code. Mentioned in comments in
  `src/keySetup.js`, `src/keySetupCore.mjs`, `server/standalone/key-setup.js`,
  `server/providers/places/google.js`, `server/providers/openai/rate-limit.js`,
  and in `SECURITY.md`, `.dockerignore`, `.prettierignore`.

**MCP**
- `server/mcp/` (`server.js`, `stdio.js`, `plugin.js`, `panelKey.js`,
  `services.js`), `src/tools/mcp/`, `package.json:56` (`mcp` script) and
  `package.json:282` (`./tools/mcp` export), `docs/MCP_SETUP.md`,
  `src/tools/mcpPanelKey.test.mjs`. `src/tools/` (the tool catalog:
  `catalog.js`, `queries/`, `services.js`) is shared with the voice code and
  the panel build, so only `mcp/` and `server/mcp/` are independent;
  `tools/services.js` builds a source for every ruled-out layer (lines 11-85).

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
