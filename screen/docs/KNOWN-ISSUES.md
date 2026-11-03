# Known issues

Active runtime issues only. Everything removed from upstream is listed in
[FORK.md](../../FORK.md); issues that only concerned removed features (street
traffic, CCTV, live camera video, the night-vision shader) are gone.

## Open

### Height-datum residuals
Status: open (accepted by upstream's owner, July 2026)

- **Cold-start floor latency:** at a freshly visited airport, grounded or low
  aircraft float low for one or two poll cycles (30 to 60 s) and rise as
  terrain floors resolve; a few stragglers take one more poll.
- **Born-grounded first poll:** a contact first seen on the ground with no
  altitude data renders at the geoid for up to one poll until its floor cell
  warms.
- The check for this is `scripts/qa-floor-verify.mjs`.

### Weather layers: coverage and meaning
Status: open (source limits, by design)

- **Rain radar covers the contiguous United States only.** It shows MRMS
  reflectivity in dBZ, not rainfall rate or a forecast; a gap in coverage does
  not mean no precipitation.
- **Lightning density is a ground-network grid, not GLM flashes.** It is
  NOAA's 15-minute density product derived from Vaisala NLDN/GLD360 on an
  approximately 8 km grid, for the Americas and Pacific only (110 E across the
  dateline to 0, 25 S to 80 N). It is not a live strike counter or an
  all-clear.
- **Cyclone advisories cover NOAA's basins only:** the Atlantic and the
  eastern and central North Pacific (NHC and CPHC). Storms elsewhere do not
  appear. The cone is forecast-centre uncertainty, not storm size.
- **Satellite clouds:** global infrared is hourly with typically 2 to 3 hours
  of source latency. "Clouds only" is a brightness filter, not a cloud mask.
- **Wind is a forecast.** The animation flows through one forecast on an
  approximately 1 degree grid and does not advance forecast time or follow the
  observed-history timeline.
- **History is not shared.** Share links carry the weather layers and their
  settings but open at Latest.
- **3D Tiles detail window during history playback:** when a frame's detail
  image is slow to arrive, the window may fall back to the coarser full-extent
  image until it does.
- The wind and weather renderers have not been verified on native hardware
  GPUs.

### Satellite passes and analyst answers
Status: open (by design)

- Pass predictions search the next 24 hours for satellites in the loaded
  catalogue. Visibility is a geometric estimate (satellite sunlit, observer's
  Sun at or below -6 degrees); it ignores weather, satellite brightness and
  orbital-element age.
- Analyst counts and ranks cover a bounded set of loaded records (by default
  2,000 per layer for satellites, datacenters and dams), so omitted records can
  change a nearest or count answer. Satellite distance is ground distance.

### Leftovers from removal
Status: open (listed so they are not mistaken for features)

- Messages and a few settings still say "add it in Provider Settings"; there
  is no such panel.
- The page title and a title-bar tagline still use upstream's name.
- `package.json` still lists `doctor` and `qa:street-level` scripts whose
  files are gone, and dependencies (`@jtarrio/*`, `mapillary-js`, `hls.js`)
  that no source imports.
- The Cyber sonar and the conflict-map layer `s2-ghostmaps` are still in the
  app, waiting for an owner decision (FORK.md).

## Closed

- **Active fires** are live NASA FIRMS data (needs `FIRMS_MAP_KEY`); the
  bundled snapshot is gone.
- **Weather** (radar, clouds, lightning, wind, cyclones) shipped in September
  2026; limits are above.
