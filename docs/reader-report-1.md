# Reader report 1: God's Eye View, interface and ideas

Written 31 October 2026 by the clean-room Reader (an agent that read
the God's Eye View repository and reports ideas and interface facts
only). No code and no internal identifiers; file paths only say where a
feature lives, for the fork. This is the input the Writer works from.

Scope given to the Reader: keep aircraft (civil), ships, satellites,
launches, earthquakes, fires, storms, weather, bike-share, transit and
the globe basics; exclude military, police, ALPR, installations,
agency-run cameras, anything about government agencies, and the "game"
parts; never ingest privacy-blocked contacts.

## 0. Architecture facts

- There is no separate backend: every `/api/*` route is middleware
  inside the Vite dev/preview server (`server/providers/*`, wired in
  `server/providers/local.js` and `server/standalone/vite.config.js`).
  Anything under `/api` gets `Content-Security-Policy: default-src
  'none'; sandbox` and `X-Content-Type-Options: nosniff`; an unknown
  `/api/*` path gets a JSON 404.
- The browser takes all data same-origin from `/api/...`, except
  earthquakes (fetched straight from USGS).
- Cache state is reported in response headers with no single
  convention: `X-GEV-Cache`, `x-tle-cache`, `X-Feed-Cache`,
  `X-Data-Stale`, `X-OpenSky-*`; values HIT, MISS, INFLIGHT,
  STALE-ERROR, STALE, NONE.
- Times are mostly Unix ms; OpenSky-shaped fields are Unix seconds;
  some are ISO strings (noted per route).
- Polling pauses while the tab is hidden and catches up on return; each
  layer declares its own interval.

## 1. Kept layers

### 1a. Aircraft (civil)

`GET /api/flights?lat=&lon=` (optional, 4 decimals; the camera's
subpoint).

- Response: an OpenSky "state vectors" body: `{ time: <unix s>,
  states: [[...], ...], emergencyByIcao?: { <hex>: "<status>" } }`.
  Each state is a positional array:
  0 icao24 hex (lowercase); 1 callsign; 2 origin country; 3 time of
  position (s); 4 last contact (s); 5 lon; 6 lat; 7 barometric altitude
  (m); 8 on ground (bool); 9 ground speed (m/s); 10 true track (deg);
  11 vertical rate (m/s); 12 sensors (null); 13 geometric altitude (m);
  14 squawk; 15 spi (bool); 16 position source; 17 emitter category
  (0-15, OpenSky numbering).
- A row with null lon and lat is "known but unpositioned": kept, and
  the snapshot is not counted incomplete.
- Headers read: `X-Flight-Source` or `X-Feed-Source` (provider name
  shown); `X-Flight-Coverage` (e.g. "worldwide upstream snapshot",
  "250nm regional fallback"); `X-OpenSky-Auth`,
  `X-OpenSky-Auth-Mode-Used`, `X-OpenSky-Auth-Reason` (only to word
  401/403/429 messages).
- Staleness computed from `time`: older than 120 s is stale.
- Browser polls every 30 s; a contact is dropped after 3 missed polls
  (1 if it had landed); contacts render on a ~30 s delayed playback
  buffer with dead reckoning between fixes.
- Errors: 429 is "rate limited", 401/403 "denied"; back off 45 s for
  those, 20 s otherwise.
- Their server, as an idea: one global upstream snapshot shared by all
  clients, cached ~9 s, stretching to 30/90/300 s as daily credit
  shrinks; on 429 honour retry-after (clamped 30 s - 30 min) and serve
  the last good body as 200; if the data is older than 120 s or
  missing, fall back to a regional adsb.lol query (250 nm, snapped to
  0.25 degrees, cached 12 s) converted to the same shape.

`GET /api/flights/track?icao24=<6 hex>`: `{ path: [[t_s, lat, lon,
baro_alt_m, track_deg, on_ground], ...] }`; cached 60 s per aircraft;
404 and 429 passed through. The browser treats it as partial history
and appends its own trail (up to 400 points).

`GET /api/adsbdb/type/<hex>` gives `{found, typeCode, typeName,
registration}`; `GET /api/adsbdb/route/<CALLSIGN>` gives `{found,
airline, origin:{code,name,lat,lon}, destination:{...}}`. Cached 24 h
including "not found"; the browser sends at most 4 at once, ~5/s, each
key once per session; route lookups only for the tracked aircraft.

Providers and terms: OpenSky Network, non-commercial research and
education (operational use may need a written agreement); adsb.lol,
ODbL 1.0 (commercial use with attribution and share-alike; future
access may need feeder keys); adsbdb, no licence published, and its
route data "may not be copied, published, or incorporated into other
databases" without permission (treat as not usable for storage).

Military entanglement: the civil layer polls `GET /api/military`
every 60 s (adsb.lol `/v2/mil`, `{ac:[{hex,...}]}`) only to learn which
identities are military, to tint or hide them. The civil feed itself is
NOT filtered. A civil-only backend must remove military aircraft from
the flights data itself. The screen tolerates the military source being
absent.

### 1b. Ships

`GET /api/vessels?maxRows=<n>[&lat=&lon=&radius_km=]` (maxRows default
12000, clamped to 50000). Area parameters only when the camera is at or
below 450 km; radius roughly the camera height, at least 10 km; the
browser re-asks when the radius changes by 25% or the centre moves 25%
of it. Their server ignores the area and returns newest first; the
browser allows that.

- Response: `{ rows:[...], source, status, error, refreshing (true when
  status is not 'live'), newestPositionAt (ISO), lastMessageAt,
  silentForMs, reconnectAttempt, nextAttemptAt (ms), staleAfterMs,
  watchdog }`; `status` one of live, connecting, reconnecting, idle,
  silent, stale, down, error, closed, missing-key, auth-failed,
  unsupported.
- Rows: `mmsi`, `lat`, `lon`, `name` (falls back to "MMSI n"), `imo`,
  `type` (or `type_specific`), `destination`, `speed` (knots), `course`
  (deg), `heading` (deg; 511 is unknown and removed),
  `last_position_UTC` (ISO), `last_position_epoch` (s). Times are the
  AIS report time, not receipt time.
- 503 with `status:"missing-key"` when no key; 502 with `rows:[]` on
  error.
- Browser polls every 60 s, `cache: no-store`; renders up to 12000
  vessels and 900 labels. The URL can be replaced at build time
  (`VITE_AIS_LIVE_API_URL`).

`GET /api/vessels/track?mmsi=<5-10 digits>`: `{mmsi,
samples:[{lat,lon,t (s)}], source, retainedSec}`; up to 64 thinned
samples (at least 30 s and 25 m apart), kept 30 min.

Upstream: AISStream.io, one server-side WebSocket for the whole world,
private key, one connection per key, no browser CORS; reconnect backoff
5 s, 15 s, 60 s, 5 min, then every 15 min; silent after 2 min with no
messages. Terms: "free, beta, no formal ToS"; commercial use unclear.

### 1c. Satellites

`GET /api/celestrak/<group>` (stations, visual, gps-ops, glo-ops,
galileo, geo; optional starlink): plain-text three-line TLE. Headers
`x-tle-cache` (MISS, HIT, STALE-ERROR, NONE), `X-TLE-Cached-At` (ISO),
`Retry-After` while cooling down. Cached 6 h in memory and on disk,
stale served on failure, 502 only with no copy.

Positions are computed in the browser with SGP4 (satellite.js) at about
1 Hz; dense Starlink round-robin; catalog re-read about every 5 min.
CelesTrak: US-government-origin data, no licence, citation requested;
blocks bulk fetches without a descriptive User-Agent. (Coordinator's note: some of the
groups are agency-operated constellations; whether to keep them is the
owner's call under the government-data rule.)

### 1d. Launches

`GET /api/launches`: the raw Launch Library 2 v2.3 detailed list,
`{ results:[...] }` (a bare array accepted); trailing 30 days,
`limit=100&mode=detailed`. Fields used: `id`, `slug`, `name`, `net`,
`window_start`, `status.name`, `launch_service_provider.name`,
`rocket`, `pad.location.name`, pad lat/lon, `mission.name`,
`mission.description`, `mission.orbit`, payloads, `timeline`. Headers
`X-GEV-Cache` (STALE-ERROR checked), `X-GEV-Cached-At`. Cached 15 min;
browser polls every 5 min. `GET /api/celestrak/active` (full active
catalog, ~2.7 MB) shows payload orbits. The Space Devs: use and share
in any form, attribution encouraged, 15 anonymous calls/hour.

### 1e. Earthquakes

No route: the browser fetches
`https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson`
every 60 s, using `feature.id`, coordinates `[lon, lat, depth_km]`,
`properties.mag`, `properties.place`, `properties.time` (ms). USGS,
public domain.

### 1f. Fires

`GET /api/firms`: `{fetchedAt (ms), stale, ttlMs, sources:[{source,
count, ok}], count, fires:[...]}`; fire fields `lat`, `lon`, `frp`
(MW), `confidence` (l/n/h or 0-100), `brightness`, `brightnessTi5` (K),
`daynight`, `acqDate` (YYYY-MM-DD), `acqTime` (unpadded HHMM UTC),
`satellite`, `instrument`. Trailing 24 h from VIIRS (NOAA-20, NOAA-21,
S-NPP) and MODIS; can be tens of thousands of points (about 131k seen).
503 `{error:"no_key"}` without a key; 502 with nothing cached. 30 min
cache; browser polls every 10 min. NASA FIRMS: free MAP_KEY, 5000
transactions per 10 min, public domain with acknowledgement.

`GET /api/fire-perimeters`: `{fetchedAt (ms), rows:[...], stale?}`;
`X-Data-Stale: true` when serving last good. Rows: `stableId`, `name`,
`acres`, `containedPct`, `state`, `category`, `discoveredTime`,
`updatedTime` (ms), `cause`, `behavior`, `personnel`, `county`,
`costToDate`, `complexity`, `complexName`, `polygons` (array of
polygons, each an array of rings of `[lon, lat]`). 429 with Retry-After
60; 502 `{error:"fire_perimeters_unavailable"}`. 5 min cache, stale up
to 24 h; browser polls every 5 min. Optional InciWeb sub-routes
(`/inciweb/index`, `/inciweb/publication/<id>`). NIFC WFIGS and
InciWeb, public domain. (Coordinator's note: fields such as personnel and cost describe an
agency's response; whether they are "about a government agency" is the
owner's call.)

### 1g. Storms

`GET /api/cyclones`: `{schemaVersion:1, source, attribution, coverage,
fetchedAt, stale, unavailable, reason, storms:[...]}`; storm fields
`id`, `name`, `classification`, `basin`, `position {latitude,
longitude}`, `positionAt` (ISO), `advisoryNumber`, `issuedAt` (ISO),
`windKt`, `pressureHpa`, `movement {directionDegrees, speedKt}`,
`advisoryUrl`, `outlookUrl`, `geometryStatus`
(pending/current/unavailable), `geometryAdvisoryNumber`,
`forecastPoints:[{position, tauHours, windKt, gustKt}]`, `track`
(GeoJSON line), `cone` (GeoJSON polygon); geometry attached only when
its advisory matches the storm's. 429 `cyclone_busy` with Retry-After
2; failures still 200 with `unavailable` or `stale`. 5 min cache, one
upstream attempt per 60 s; browser polls every 5 min. NHC and NOAA,
public; Atlantic and east/central Pacific only.

### 1h. Weather (radar, clouds, lightning)

`GET /api/weather/manifest?product=<radar|clouds|clouds-regional|lightning>`:
`{schemaVersion:1, product, title, coverage, description, source,
attribution, bounds {west, south, east, north}, times:[ISO...] (up to
13), latest, time, observedAt, fetchedAt, stale, unavailable, reason,
tileSize:256, maxLevel:6, tilingScheme:"geographic", tileTemplate,
imageUrl, imageSize}`; only listed parameters, each once.

`GET /api/weather/tile?product=&time=&z=&x=&y=[&size=256|512|1024]` and
`GET /api/weather/image?product=&time=[&size=1024x512|2048x1024|4096x2048][&bbox=w,s,e,n]`:
PNG, bbox snapped to 0.25 degrees, `public, max-age=86400, immutable`;
400/429/503 with JSON. Metadata refreshed every 2 min (lightning 10);
at most 8 upstream requests at once, 12 s deadline, 128 images / 16 MiB
cache. NOAA nowCOAST WMS, public; lightning is a derived Vaisala
product, only the density product may be redistributed.

### 1i. Wind

`GET /api/wind/manifest?model=<gfs|ifs>[&overlay=temperature|pressure]`:
`{schemaVersion:1, model, cycle {date YYYYMMDD, hour, forecastHour,
runIso, validIso}, overlay?, scalar? {kind, units "°C"|"hPa", level},
scalarError?, fetchedAt, level "10 m above ground", units "m/s", grid
{nx, ny, lo1, la1, dx, dy}, stale, unavailable, reason, gridUrl}`.
`GET <gridUrl>` (`/api/wind/grid/<model>-<id>.bin?model=...[&overlay=...]`):
little-endian Float32, U then V then optional scalar, each nx by ny,
north to south from la1 = 90, east from lo1 = 0; 1 degree (360 by 181);
immutable for 1 h. The browser checks strictly: the gridUrl pattern,
nx times dx equals 360, exact byte count. Previous grid kept across a
rollover; at most one attempt a minute; browser polls hourly. NOAA GFS
(public domain) and ECMWF Open Data (CC BY 4.0 plus ECMWF terms:
specific attribution, modification notice, liability disclaimer). GRIB
decoded server-side.

### 1j. Bike-share

`GET /api/gbfs/<url-encoded https upstream GBFS URL>`: a pass-through;
the browser holds the registry (49 systems, each a centre and ~100 km
load radius) and builds upstream URLs; the server allowlists host and
path. Standard GBFS `station_information` and `station_status`.
Headers `X-GBFS-Upstream`, `X-GBFS-Cache`; `public, max-age=300` for
station information, otherwise `no-store`; 120 requests/min per IP, 429
with Retry-After 10; redirects refused; `Client-Identifier` and
`ET-Client-Name` sent for the Norwegian operators. Status every 60 s
per city in range. Licences vary per feed; several publish none.

### 1k. Transit

`GET /api/transit/feeds`: `{feeds:[{id, name, operator, region,
center, loadRadiusKm, license, licenseUrl, attribution,
historyRetention}]}`, cacheable 1 h.

`GET /api/transit/vehicles/<feedId>`: server decodes GTFS-Realtime
VehiclePositions (the browser never parses protobuf). `{feedId, name,
fetchedAt (ms), feedTimestamp (s), version, entityCount, truncated,
count, vehicles:[{id, lat, lon, bearing, speedMps, timestamp (s),
timestampSource ('vehicle'|'header'|'fetch' = guessed), routeId,
tripId, directionId, label, stopId, status, occupancy}]}`. Headers
`X-GEV-Cache`, `X-Transit-Contact` (ms of the operator's last real
answer, 304 counts), `X-Transit-Upstream`; 503 with `Retry-After` and
`X-Transit-Backoff` (cooldown or rate-limited), body `{error, feedId,
retryInSec}`. Differential feeds refused.

`GET /api/transit/trail/<feedId>/<vehicleId>`: `{version:1, feedId,
vehicleId, oldestT, newestT, truncated, epochs:[{id, trip, route,
mode}], fixes:[[t, lat, lon, flags, epochId]]}`, up to 15 min, only
some feeds.

15 s cache per feed, stale up to 10 min; 8 requests per feed per minute
and 40 overall; conditional requests; browser polls each in-range feed
every 15 s and drops a vehicle after 2 missed polls. 16 operators
(MBTA, CapMetro, Metro Transit, OVapi, Entur, TransLink QLD, HSL, TTC,
MiWay, Hamilton, Durham, Guelph, Kingston, Barrie, YRT, Burlington),
mostly open data; several revocable or needing a terms link to travel
with the data. (Coordinator's note: transit operators are often public agencies; vehicle
positions are service data, not data about the agency, but it is the
owner's call.)

### 1l. Globe basics

- Terrain loaded by the browser from
  `terrain.reearth.land/cesium-mesh/ellipsoid` (CC BY 4.0), flat
  ellipsoid fallback. `GET /api/terrain/heights?points=lon,lat;...`
  (at most 64): `{results:[{ellipsoid: <m>, ...}]}` in request order;
  400/413/429 (90/min per client)/502.
- Basemap fetched by the browser: Esri World Imagery (default, no key),
  OSM tiles (restrictive policy for production), Bing via Cesium ion
  (token), Google Photorealistic 3D Tiles (browser key or
  `GET /api/google/tiles-token` giving `{accessToken, expiresAt}`, 204
  when not offered; may not be cached), OpenFreeMap vector tiles.
- Search: coordinates or `geo:` URIs, bundled names, Google, Photon,
  then Nominatim. `GET /api/google/geocode?address=&bounds=...`
  (Google-style `{status, results}`); Photon direct; `GET
  /api/geocode?q=&bounds=` (Nominatim, Google-like results, one per
  query, paced 1/s, cached 5 min, 429/503).
- Share links: long form in `location.hash` (`#lat=&lon=&alt=&heading=&pitch=&map=&...`),
  short form `/share/<code>` decoded in the browser; the host must serve
  the app for `/share/*`.
- Click to track, north-up and tilt, reset and the nearby-contacts list
  are browser-only.

## 2. How the screen's data layer is organised (ideas)

- A source per family offers a "snapshot" (query in, records out) and
  optionally a "track" (opaque reference in, history out). A snapshot
  carries provider label, coverage, completeness, freshness (current,
  stale, unknown, with observed-at and age), transport status and the
  count of rejected rows. A snapshot is all or nothing: a non-empty,
  wholly invalid feed is "unavailable", never empty. Errors are limited,
  denied, unavailable, malformed or unsupported, each with a retry
  delay.
- Units normalised in the browser: WGS84 degrees, metres, m/s, Unix ms;
  barometric and ellipsoidal altitude kept separate; a missing time is
  unknown, never "now".
- The app is composed from a registry of named sources; a source left
  out shows "data source not configured", never empty.
- Areas: aircraft global (the camera point only steers the fallback);
  vessels by a radius tied to camera height; bike-share and transit
  only systems within ~100 km; weather by tiles or one clipped image;
  the contacts list 250 km around the view, widening if empty.
- Volumes: ~10k aircraft (OpenSky ~0.8 MB); up to 12k vessels rendered,
  50k held; several thousand satellites plus ~8-9k Starlink; tens of
  thousands of fire points; hundreds of transit vehicles per feed.
- Thousands of moving objects: delayed playback (~30 s) with dead
  reckoning every ~80 ms; heading changes limited to 60 deg/s; label
  budgets and per-cell display budgets; sprite and billboard
  collections rather than one entity each; visibility and level of
  detail on short timers; fixed history buffers per contact, trails
  capped at 400 points; enrichment paced by a token bucket.

## 3. Excluded parts: where they live, how entangled

- Military aircraft: `src/layers/military/`,
  `src/app/layers/militaryFlights.js`, `src/data/military*.js`, the
  military registry in `src/layers/aircraft/`, `/api/military` and
  `/api/military/track`. The civil layer uses the registry for tint and
  suppression; the contacts list depends on it; the control surface
  requires a layer with id `military` and fails at start without one.
- Military installations: `src/layers/installations/`,
  `src/app/layers/militaryInstallations.js`,
  `server/providers/military-installations*`, `server/providers/overpass*`
  (also used for boundaries and annotations), bundled
  `src/data/local_data/osm_military_names/`. Required by the control
  surface; the contacts list includes "sites".
- **The nearby-contacts list (kept) IS the layer with id
  "military-awareness"**: `src/layers/awareness/`,
  `src/app/layers/militaryAwareness.js`,
  `src/data/militaryAwarenessEngine.js`; it combines flights, military,
  vessels and installations.
- Police: no feature found.
- ALPR: `src/layers/alpr/`, `src/data/alprCameras.js`,
  `src/app/layers/alprCameras.js`, tiles from
  `tiles.dontgetflocked.com`; removable cleanly.
- CCTV: `src/layers/cctv/`, `src/data/cctv*.js`, `src/cctv*.js`,
  `src/ui/cctv*.js`, `server/providers/cctv*`, `config/cctv_sources.*`,
  `src/data/local_data/cctv_ground_heights/`, `/api/cctv*`,
  `/api/webcams/`; includes estimated camera poses. Required by the
  control surface; the `c` key toggles it; referenced by search and
  focus.
- S2 GhostMaps: `src/layers/ghostMaps/`, `server/providers/ghostMaps.js`;
  CC BY-NC-SA; removable.
- Other layers not kept: GNSS integrity, air quality, recent imagery,
  street level, radio, local ADS-B and SDR (web worker, WebUSB),
  directions, submarine cables (TeleGeography, non-commercial),
  datacenters and dams, traffic (simulated plus TomTom). The control
  surface also hard-requires `traffic`, `radio`, `street-level` and
  `local-adsb`.
- Game parts:
  - Visual reskins: `src/styles/*`, `src/visualStylePolicy.js`,
    `src/bloom.js`, `src/cyberSonar*.js`, `src/ui/visualEffects.js`,
    `src/ui/visualPresets.js`, `style=` share parameter; "normal" is
    the default.
  - Military HUD: `src/hud*.js`, `h` key, `hud=` parameter.
  - Detection boxes: `src/data/detection*.js`,
    `src/contactsDetectionPolicy.js`, `src/overlays/`; **woven in: the
    flights layer draws its labels with the detection label drawer**;
    `d` key; `dm=`, `dd=`, `da=` parameters.
  - Cockpit: `src/cockpit*.js`, `src/ui/cockpit*.js`,
    `src/ui/templates/cockpit.html`; regional briefing and
    weather-effects routes serve only it.
  - 3D models: `public/models/` (3 MB), model-spec, lighting and
    eligibility modules, and an easter-egg registry
    (`src/data/tr3bRegistry.js`) wired into flights; a per-layer switch
    turns models off.
  - Estimated launch trajectories: `src/layers/launches/` (`paths.js`,
    `replay.js`, `orbitRendering.js`, `launchPad.js`), **woven into the
    launches layer**.
  - Director and scenes: `src/director/`, `src/scenes/`,
    `src/ui/scenes.js`, `src/ui/sceneControls.js`,
    `src/ui/templates/scene-chrome.html`; Bhote Koshi flood
    (`src/data/bhoteKoshi*.js`, `public/events/`, CC BY-NC) is
    **hard-registered in the catalog**.
  - News and briefs: `server/providers/regional/*`.
  - Voice and AI: `src/voice/`, `src/agent/`, `src/tools/`,
    `src/annotations/`, `server/providers/openai*`, `gemini*`,
    `/api/realtime/*`, `/api/openai/hud-summary`.
  - Key setup: `src/keySetup*.js`, `server/standalone/key-setup*`,
    `/api/setup/*`.
  - Pinokio: `pinokio/`. MCP: `server/mcp/`, `src/tools/mcp`,
    `src/tools/globePanel.js`, `build/panel.js`.
- Existing switches: leave a source out of the registry (layer shows
  "not configured"); server environment flags (CCTV packs, keys,
  `GEV_EMBED_FRAME_ANCESTORS`); per-feed `defaultEnabled` for transit;
  per-layer runtime parameters (3D models, dense satellites); **embed
  mode `?embed=1`**: globe only, no HUD, welcome or setup screens,
  driven by the parent page through postMessage (`gev:view`,
  `gev:view-applied`, `gev:ready`). There is no general layer-disable
  setting, and the control surface requires 8 specific layer ids.

## 4. What a host page must allow

- CesiumJS brings web workers and WASM decoders; the built app starts
  workers from `blob:` URLs. **The CSP needs `'unsafe-eval'`
  (Knockout, inside Cesium's widgets)** and `blob:` in script-src,
  worker-src and child-src; connect-src https, wss, ws; img-src and
  media-src blob:, data:, https.
- Hosts fetched directly: tile.googleapis.com, maps.googleapis.com,
  api.cesium.com, assets.ion.cesium.com, assets.cesium.com,
  dev.virtualearth.net, ecn.t0-t3.tiles.virtualearth.net,
  services.arcgisonline.com, server.arcgisonline.com,
  tile.openstreetmap.org, tiles.openfreemap.org, terrain.reearth.land,
  photon.komoot.io, earthquake.usgs.gov, fonts.googleapis.com,
  fonts.gstatic.com.
- Global CSS: ~35 sheets, ~556 KB, `:root` variables and a universal
  `*` reset, assumes it owns the whole page (dark, #0a0a0f); HTML
  templates injected into `<body>`.
- Document-level keyboard handlers in about 15 modules (Escape, h, o,
  v, f, d, c, and per-layer selection).
- Writes the URL hash constantly, listens for hashchange and popstate,
  reads `?embed=1` and `?lang`, needs SPA fallback for `/share/<code>`.
- localStorage for layer state, panel positions, visual settings,
  first-run state, locale.
- Framing denied by default; only embed-mode documents can be framed,
  with an operator allowlist.
- Build-time keys baked into the bundle (Google Maps, Cesium ion,
  Mapillary).
- Bundle size not stated; chunk warning raised to 1500 kB; bundled data
  19 MB (`src/data/local_data`), `public/` 5.4 MB (mostly excluded
  models and events).
- Node `>=24.14.0 <25` or `>=26 <27`; Vite 6.

## 5. Privacy-blocked contacts

- The code has no concept of privacy-blocked aircraft or vessels; it
  reads no flags field and keeps no "do not show" list.
- From the Reader's own knowledge, NOT from this code, to verify: feeds
  in the readsb format (adsb.lol) carry a per-aircraft database-flags
  bitfield marking military, and LADD and PIA (privacy) aircraft;
  non-ICAO and anonymous addresses start with `~`.
- So our backend must filter at ingestion, before anything is stored,
  cached, trailed or enriched, and may keep an operator blocklist of
  hex codes and MMSIs.

## 6. Ideas for our backend

- One snapshot shape for every family: source, coverage, observed-at,
  fetched-at, stale, unavailable, reason, complete, records, in
  normalised units; freshness in the body and one consistent header
  family. Keep the screen's existing routes and headers as a
  compatibility layer, because the screen checks them strictly (the
  wind grid URL pattern, OpenSky array positions, `x-tle-cache`,
  `X-GEV-Cache`, `X-Transit-Contact`).
- Caching: one upstream poll per feed shared by all clients, single
  flight, last good within a maximum stale age, disk for slow feeds;
  lifetimes tuned per upstream (aircraft 10-30 s, transit 15 s, vessels
  continuous, weather metadata 2 min, storms and perimeters 5 min,
  fires 30 min, orbits 6 h, wind 1 h); immutable assets cached as
  immutable.
- Rate limits: per-upstream budgets honouring Retry-After within
  bounds; lifetimes that stretch as a quota runs low; admission limits
  per client and overall; serve last good with `stale:true` when
  throttled; never pass a 429 to the browser while holding data.
- Viewport queries (bbox or point and radius) on aircraft, vessels and
  fires with a spatial index and a row cap; a coverage string;
  snapped keys so caches are shared.
- Freshness: "upstream last answered" separate from "data observed
  at"; guessed timestamps marked; a per-feed health endpoint.
- Privacy and policy once, at ingestion.
- A licence profile per provider; non-commercial providers refused in
  commercial mode.
- Optional streaming of deltas for aircraft and ships alongside polling
  (the screen only polls today).
- Proxying USGS would remove one direct browser host.

## Open questions the Reader could not answer

1. Does OpenSky's worldwide snapshot already leave out privacy-blocked
   aircraft?
2. The exact meaning of the readsb flag bits in adsb.lol responses.
3. AISStream's position on commercial use.
4. The built bundle size.
5. What the terrain heights result holds beyond `ellipsoid`.
6. The meaning of the flags integer in transit trail fixes.
7. Whether the control surface's required layers can be empty stubs
   without side effects.
8. Whether passing null for a source reliably marks it "not
   configured".
9. Whether the bike-share feeds with no licence permit reuse.
10. Whether coordinate readouts the operator expects live in the
    excluded HUD.
