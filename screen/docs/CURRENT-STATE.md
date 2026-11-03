# Current state

What this app does now. It replaces upstream's log of per-change behaviour
notes (about 6,400 lines, mostly about features that no longer exist); the
history stays in git and in [CHANGELOG.md](../CHANGELOG.md). What was removed
is listed in [FORK.md](../../FORK.md). Update this page in the same change as
any change to runtime behaviour.

## What it is

A Cesium globe in the browser, served by a Vite dev or preview server that
also hosts the data routes (`/api/*`, in `server/providers/`). The data does
not come through Elysium yet; see the README. All layers are read-only views
of public feeds ([DATA_SOURCES.md](../DATA_SOURCES.md)). Nothing is simulated
or estimated and shown as if it were observed.

## Layers

The layer ids and names are in `src/ui/layerNames.js`.

- **Aircraft** (`flights`): OpenSky when configured, adsb.lol as fallback.
  Details and route data for the followed aircraft come from adsbdb. Aircraft
  are drawn as 2D icons; there are no 3D models. Military aircraft are not
  a layer; the military registry in `layers/aircraft/classification.js` is an
  inert object that answers false.
- **Vessels** (`ais-live-vessels`): AISStream, server key.
- **Satellites** and **Space Missions (30d)**: CelesTrak orbital elements
  (SGP4 in the browser) and Launch Library 2. Pass predictions are a
  geometric estimate (see KNOWN-ISSUES).
- **Earthquakes (24h)**: USGS.
- **Fires**: NASA FIRMS detections (`FIRMS_MAP_KEY`) and NIFC fire
  perimeters.
- **Weather**: Rain radar, Satellite clouds and Lightning density (NOAA
  nowCOAST), Cyclone advisories (NHC and CPHC), Wind (NOAA GFS or ECMWF
  forecast), Air quality (Environment Canada).
- **GNSS Integrity**: aircraft-reported navigation integrity from adsb.lol.
- **Cities**: Bike Share (GBFS systems) and Transit (GTFS-Realtime vehicle
  feeds, 16 registered regions).
- **Reference**: Data Centers, Dams and Submarine Cables (bundled snapshots),
  Recent Imagery (NASA GIBS) and Directions (OSRM).

A layer that needs a key stays off and says which variable it needs. Polling
pauses while the tab is hidden and runs one overdue update on return.

## Globe and view

- **Map stacks**: Google Photorealistic 3D (needs `GOOGLE_MAPS_API_KEY`),
  Natural Earth (bundled, public domain), Bing aerial and labels (need
  `CESIUM_ION_TOKEN`), Esri imagery (needs your own Esri licence), OpenStreetMap.
  With no key the app starts on Natural Earth with flat terrain (the keyless
  terrain is stubbed off, see FORK.md "Basemap"; an opt-in self-hosted
  Terrarium terrain exists behind `TERRAIN_TILE_URL` but has only been tested
  on synthetic tiles, never on real Mapterhorn data or in a browser). Natural Earth is sharp only
  at low zoom (levels 0 to 2); Recent Imagery still borrows the Esri stack.
- **Visual styles**: Normal, Anime, Noir. Older links that name the removed
  looks open as Normal.
- **HUD**: mode, a deterministic summary line, UTC time, camera latitude,
  longitude and altitude above mean sea level, and sun elevation, plus a
  vessel line. Layouts: Tactical (shown as "Full"), Minimal, Cyber.
- **Detection labels** (D): callouts for aircraft and vessels.
- **Shortcuts**: H HUD, O orbit, V clean view, F layers, D detection.
- **Context panel**: a Contacts mode (aircraft and vessels near you) and a
  Space Missions mode.
- **Search**: place names (Google when keyed, else Photon and Nominatim) and
  coordinates.
- **First run**: a welcome card ("Live aircraft, vessels, satellites and
  earthquakes on one globe") opens on a fresh browser. Note that
  a surface class that never clears means no launcher for that page load, with no timeout: it
  appears when the class (recording or clean view) clears, and
  returns next session either way.

## Drawing and files

The Import control loads GeoJSON, KML, KMZ and GPX files for the session
(`src/data/geoFileImport.js`).

DISPLAY ▸ **Draw**: pick Area, Line or Pin, click the vertices on the globe,
double-click or press Enter to finish, label it. Backspace removes the last
vertex and Esc cancels. A shape holds at most 512 vertices. Marks are draped
on terrain and 3D tiles, and a line is labelled with its length.

## Share links

A share link restores camera, followed object, style, layers and panels. The
format, including every reserved code of a removed feature, is in
[SHARE-LINK-FORMAT.md](SHARE-LINK-FORMAT.md).

## Transit

Transit is off by default. The layer polls registered feeds near the camera.
Only the MBTA feed has short-lived retention of recently observed positions
(up to 15 minutes, in server memory); other feeds have no proxy retention.
Restart clears it.

## Embedding

`?embed=1` is embed mode (`src/embedFlag.js`). The app makes no request to
settings, key-setup or summary routes, and it needs no Google token route.
In a frame without `allow-same-origin` it loads images with `crossOrigin`;
the asset host must send `Access-Control-Allow-Origin: *`.

## Languages

English, German, Spanish, French, Italian, Japanese, Portuguese, Russian,
Ukrainian, Simplified and Traditional Chinese (`src/i18n/locales/`).
