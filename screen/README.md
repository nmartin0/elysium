# Astrolabe screen

The browser app of **Astrolabe**, a live 3D globe that is an add-on for
Elysium. It shows aircraft, vessels, satellites, launches, earthquakes,
fires, storms, weather, bike-share and transit vehicles on a Cesium globe.

This directory is a fork of **God's Eye View** by **Bilawal Sidhu**
(<https://github.com/bilawalsidhu/gods-eye-view>), MIT licensed, imported from
upstream commit `8978801dfd2a`. The licence text is in [LICENSE](LICENSE) and
must travel with this code. The fork removed a large part of upstream; the
list of every change is [FORK.md](../FORK.md), and the plan is
[ROADMAP.md](../ROADMAP.md). The package is still named `gods-eye-view` and the
page title still says "God's Eye View" (not renamed yet).

## Where data comes from today

Not from Elysium yet. This screen still serves its own `/api/*` routes from
middleware inside the Vite dev and preview server (`server/providers/`), and
those routes call the public feeds listed in
[DATA_SOURCES.md](DATA_SOURCES.md). The plan is that every feed reaches the
globe through Elysium instead (see [ROADMAP.md](../ROADMAP.md), phases 2 to 4);
the feed terms and what is dropped at the door are in
[../docs/feeds.md](../docs/feeds.md).

`?embed=1` (or the `GEV_EMBED_INLINE` global) puts the app in embed mode, for a
host page that frames it. In a frame without `allow-same-origin` the app loads
images with `crossOrigin` (`src/app/opaqueOrigin.js`).

## Run it

Needs Node 24.14 or newer (`engines` in `package.json`).

```bash
cd screen
npm install
npm run dev        # http://localhost:4173 ; set HOST and PORT to change
```

`npm run build` makes a production bundle and `npm run preview` serves it.
Settings come from a `.env` file in `screen/` (copy `.env.example`; note that
file still lists keys for features that were removed, only those below are
read). There is no in-app key setup: a missing key leaves its layer or map
source switched off with a note.

| Variable | Used for | Without it |
| --- | --- | --- |
| `GOOGLE_MAPS_API_KEY` | Photorealistic 3D Tiles, Google place search | Starts on Esri World Imagery; search falls back to Photon and Nominatim |
| `CESIUM_ION_TOKEN` | Bing map stacks, Cesium world terrain | Those stacks are off; keyless terrain |
| `AISSTREAM_API_KEY` | Live vessels | Vessel layer off |
| `FIRMS_MAP_KEY` | Active fires (NASA FIRMS) | Fire layer off |
| `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` | OpenSky aircraft ([docs/opensky-auth.md](docs/opensky-auth.md)) | adsb.lol fallback |
| `LL2_API_TOKEN` | Launch Library 2 (optional) | Anonymous rate limit |

Other server settings: `PORT`, `HOST`, `GEV_ALLOWED_HOSTS`,
`GEV_EMBED_FRAME_ANCESTORS`, `OVERPASS_UPSTREAMS` and the `AISSTREAM_*`
tuning variables.

## What is in the app

- **Map stacks**: Google Photorealistic 3D, Bing aerial and labels, Esri
  imagery, OpenStreetMap (`src/maps/catalog.js`), with terrain and a
  recent-imagery layer and compare tools.
- **Layers** (`src/ui/layerNames.js`): Live Flights, Live Vessels, Satellites,
  Space Missions (30d), Earthquakes (24h), Active Fires (FIRMS), Fire
  Perimeters, Cyclone advisories, Rain radar, Satellite clouds, Lightning
  density, Wind, Air quality, GNSS Integrity, Bike Share, Transit, Recent
  Imagery, Data Centers, Dams, Submarine Cables, Directions, and S2 GhostMaps
  (a conflict-map layer upstream shipped; flagged for an owner decision in
  FORK.md).
- **Visual styles**: Normal, Anime, Noir.
- **HUD** (H), detection labels for aircraft and vessels (D), clean view (V),
  orbit (O), layers (F).
- **Search** by place name or coordinates, and a **share link** that restores
  camera, followed object, style, layers and panels
  ([docs/SHARE-LINK-FORMAT.md](docs/SHARE-LINK-FORMAT.md)).
- **Imported files**: GeoJSON, KML, KMZ or GPX files can be imported for the
  session.
- **Annotations**: DISPLAY ▸ **Draw** lets you pick Area, Line or Pin, click
  the vertices on the globe and label the shape; it drapes on terrain and 3D
  tiles.
- **Languages**: English, German, Spanish, French, Italian, Japanese,
  Portuguese, Russian, Ukrainian, Simplified and Traditional Chinese
  ([docs/I18N.md](docs/I18N.md)).

## Removed from upstream

Cockpit view, voice and AI features, in-app key setup, the MCP server, 3D
aircraft models, the CRT, night-vision and FLIR looks, the military HUD
styling, military, police, ALPR and CCTV layers, internet radio, local
receivers, street-level imagery, simulated traffic, the director and demo
scenes, news briefs, and the Pinokio and Docker launchers. Old share links
that name them still open, as Normal where a style is gone (the codes stay
reserved).

## Docs

[docs/CURRENT-STATE.md](docs/CURRENT-STATE.md) (what the app does now),
[docs/PERFORMANCE.md](docs/PERFORMANCE.md), [docs/KNOWN-ISSUES.md](docs/KNOWN-ISSUES.md),
[DATA_SOURCES.md](DATA_SOURCES.md) (sources, licences, attribution),
[CONTRIBUTING.md](CONTRIBUTING.md), [TESTING.md](TESTING.md),
[SECURITY.md](SECURITY.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Licence and credit

Code: MIT, copyright (c) 2026 Bilawal Sidhu (see [LICENSE](LICENSE)). The MIT
grant covers source code only; bundled datasets and runtime feeds keep their
own terms ([DATA_SOURCES.md](DATA_SOURCES.md)). God's Eye View was created by
Bilawal Sidhu, and its code is the base of this screen.
