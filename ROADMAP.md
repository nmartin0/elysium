# Astrolabe: a live world view as an Elysium sub app

**Astrolabe** (named 31 October 2026). A sub app for Elysium that shows live, real
data on a 3D globe for a human operator, with every piece of that data
coming in through Elysium: its pipeline, its grants, its audit, its
triggers and actions. The screen is a fork of God's Eye View (MIT, by
Bilawal Sidhu); everything behind the screen is our own design.

Two goals, equal weight:

1. **A useful operator tool**: see what is moving and happening, follow
   a contact, be alerted when something matters, act on it.
2. **A real test of Elysium**: live streaming data, large datasets
   (tens of thousands of moving contacts), security that holds per
   layer and per area, and acting in real time.

This file is the subproject's own plan. Elysium's planning file is
still `BLOCKING.md` on `dev`: anything here that Elysium itself should
support is proposed there, item by item, once agreed (see "What belongs
in Elysium" below).

## Decisions (owner, 31 October 2026)

- **The name is Astrolabe**, after the instrument for finding where
  things are in the sky and on Earth. "Meridian", the first choice, was
  taken in this exact field: a.i. solutions sells Meridian for satellite
  mission operations, ThothX Meridian tracks objects in geostationary
  orbit, and HPE Aruba sells Meridian maps. The "Astrolabe" products
  found are in unrelated fields (a cytometry platform, a photography
  app). A web search, not a trademark clearance.

- **No military, police or ALPR data, and nothing ABOUT a government
  agency**, even when public: no military aircraft feeds, no
  installations, no agency-run cameras. Science data merely PUBLISHED
  by an agency (earthquakes, weather, storms, fire detections, orbits)
  is kept.
- **No "game" parts.** Nothing simulated or estimated is shown as if
  real, and nothing a human operator does not need: no simulated
  traffic, estimated camera poses or launch trajectories, visual
  reskins, military-style HUD, fake detection boxes, cockpit view, 3D
  aircraft models, cinematic director, demo scenes, news briefs, or the
  app's own voice and AI features.
- **The screen is a fork, authorized.** Modifying third-party code is
  forbidden by PRINCIPLES.md section 11 without explicit authorization;
  the owner gave it for this fork. The MIT notice is kept, and every
  change to their files is listed in `FORK.md`.
- **Our backend is clean-room** (see "The clean-room rule").
- **Where it lives**: a branch of its own, `astrolabe`, in the Elysium
  repository for convenience, sharing no history with `dev`. It is
  meant to become a separate repository, an Elysium add-on module like
  Heliograph, depending only on Elysium's module API.
- **Feeds in the first version**: aircraft and ships; space
  (satellites and launches); earth events (earthquakes, fires, storms,
  weather); cities (bike-share, transit vehicles).
- **Non-commercial use for now.** Feeds whose terms allow only
  non-commercial use are permitted, each marked so it can be switched
  off or replaced when that changes.
- **Global scale, every contact** the feeds give.
- **How long positions are kept is configurable**, per object type.
- **Privacy-blocked contacts are never ingested.** Whether a source
  drops such records at the door or ingests them under a label is a
  setting of the source, in the adapter interface; for this project it
  is "drop".
- **Acting in real time**: alerts on conditions, automatic actions run
  by triggers as a named identity, and operator actions on the globe.
  Replay over history is not in scope.
- **Who sees what is decided by permissions on objects, and nothing
  else.** Grants per layer (some roles see ships and not aircraft) and
  per object, through Elysium's normal grants. A contact's live data is
  never visible to someone who may not see the object itself, on the
  globe or anywhere else. Where a contact is does not change who may
  see it.
- **Everything on the globe is an object in the ontology.** Every
  record a live feed delivers is mapped onto its object (an aircraft by
  its transponder hex code, a ship by its MMSI). When a source sees a
  contact for the first time, it creates the object, then attaches the
  live data to it. A record that cannot be mapped to an object is
  thrown away at the door.
- **The assistant answers questions about live data**, in a later
  phase.
- **Satellites**: GPS and GLONASS are left out (both run by militaries);
  Galileo, stations, visible, geostationary and commercial groups are
  kept.
- **Fire perimeters** keep the fire itself (name, size, containment,
  cause, shape) and drop the fields about the agencies' response
  (personnel, cost, complexity, InciWeb links).
- **Public transit is kept**: vehicle positions are a public service,
  even where the operator is an agency.
- **Weather imagery and grids are map layers, not objects** (radar,
  clouds, wind). Each is a named layer with its own grant (such as
  `read:layer:weather-radar`), served by our backend, every request
  audited. The precedents do the same: Foundry's Map separates object
  layers from base, raster-tile and vector-tile layers, and keeps raster
  data as media sets; ArcGIS makes an imagery layer an item with its own
  sharing. Storms, earthquakes and fires stay objects.

## What the Reader found (31 October)

The Reader's first report is `docs/reader-report-1.md`. What it changes:

- **Civil only has to be enforced at the door.** Their aircraft feed
  mixes military aircraft in, and their screen only tints them using a
  separate military list. Our sources drop military-flagged aircraft
  before anything is stored, and store nothing about them.
- **Privacy is ours to add.** Their code has no notion of privacy-
  blocked contacts. Our sources drop them at the door using the feed's
  own flags (to be verified against the provider's documentation),
  anonymous addresses, and an operator blocklist of hex codes and MMSIs.
- **The fork is real work, but bounded.** Their control surface fails to
  start without eight specific layers, three of them excluded (military,
  installations, camera feeds); the nearby-contacts list we keep is
  built as their military "awareness" layer; aircraft labels are drawn
  by the detection-box code; estimated launch paths are woven into the
  launches layer; and the flood demo is hard-registered. Each change is
  listed in `FORK.md`.
- **The screen wants a page of its own.** About 556 KB of global CSS
  that assumes it owns the page, keyboard shortcuts in about fifteen
  modules, and constant writes to the address bar. It has an embed mode
  (globe only, driven by the host page through messages). So it runs
  isolated, in a frame inside the module page, not merged into the
  shell.
- **Security policy conflict (E10).** CesiumJS's ready-made widgets need
  `unsafe-eval` and start web workers from `blob:` addresses. Elysium
  should not allow `unsafe-eval` anywhere. The fork uses Cesium's bare
  widget, which does not need it; the `blob:` workers need a policy
  scoped to Astrolabe's frame only.
- **The screen polls and checks shapes strictly.** It asks every 15 s
  to 60 s per layer, and checks some formats exactly (aircraft rows as
  fixed-position arrays, the wind grid's address and byte count). Our
  backend answers in those shapes first; streaming comes after.
- **One switch in the fork points every data request at our backend.**
  The screen calls its own `/api/...`; the fork prefixes them all.
  Earthquakes, which it fetched straight from the provider, go through
  Elysium too, since every quake is an object.
- **Volumes, as their screen expects them**: about 10,000 aircraft and
  12,000 ships drawn (50,000 ships held), several thousand satellites
  (about 9,000 more in Starlink's dense mode), and up to about 130,000
  fire detections in a day.

## The clean-room rule

Owner's rule: anyone reading their code for ideas for OUR code must not
be the one who writes our code. So there are four roles:

- **Reader**: an agent that reads their repository and reports IDEAS
  and INTERFACE FACTS only: the routes and fields the screen needs,
  units, cadences, behaviours, providers, licences. Never code, never
  internal names, never statement-level descriptions.
- **Writer**: an agent that has never seen their code. It writes our
  backend and any Elysium changes from the Reader's report and the
  agreed design.
- **Coordinator**: plans, briefs and verifies. The coordinator of this
  first session read their `src/sources/live/contract.js` and part of
  `standalone.js` before the rule existed, so it does not write backend
  code and passes on only the Reader's reports, not its own memory of
  their code.
- **Reviewer**: an independent agent that checks the Writer's code for
  correctness, and a separate check that compares our code against
  theirs and reports only whether anything looks copied, and where,
  without passing any of their code back.

The fork is different: editing their screen means reading it, so the
agent doing fork edits may read their code, and works only inside the
fork's own files.

## What belongs in Elysium, and what belongs to Astrolabe

The test for each piece: would another sub app, with other data, want
it? If yes, it is Elysium's, built on `dev`, proposed in `BLOCKING.md`,
designed generically, and Astrolabe is its first user. If no, it stays
here.

### Elysium (generic)

- **E1. Observations (time series).** An object has a series of
  timestamped observations (position, speed, heading, a reading),
  stored apart from the lake's per-sync copy, because the lake is built
  for records that change occasionally, not for positions every few
  seconds. Foundry splits it the same way: objects in the ontology,
  tracks in a separate geotemporal series store referenced from the
  object. **An observation always belongs to an object and has no
  permissions of its own**: it is readable exactly when its object and
  those fields are, so a person who may not see an aircraft sees none
  of its positions, anywhere. Retention is set per object type. This is
  the roadmap's "time series" item.
- **E2. Streaming and high-cadence sources** in the adapter interface:
  sources polled every few seconds and sources that push. Contacts come
  and go constantly, so absence means "stale", not "deleted", and the
  sync's mass-deletion guard must not fire on ordinary churn.
- **E3. Rules at the door.** Each live record is mapped onto its
  object by a declared identity (an aircraft's hex code, a ship's
  MMSI); the source creates the object the first time it sees a
  contact; a record with no identity is thrown away before anything is
  stored. Each source can also declare records to drop, or to ingest
  under a label (privacy-blocked contacts, for this project, are
  dropped).
- **E4. Live push to screens.** A screen subscribes to an object type
  within an area and receives changes as they arrive, each recipient
  seeing only what their grants allow. Built on the existing event
  stream.
- **E5. Geography.** A location as a declared concept (latitude and
  longitude), queries by area (box, radius), conditions "within this
  distance" and "inside this area" for triggers and action criteria,
  and an index that makes them fast.
- **E6. Triggers on arriving data.** Conditions evaluated as
  observations arrive, not only at sync time, with "once per contact
  per entry" so a contact sitting in an area does not alert every few
  seconds.
- **E7. Large results.** Tens of thousands of objects in one view:
  compact transfer, paging or streaming, filtering to what is on
  screen. Measured, not assumed.
- **E8. Source terms as data.** Each source declares its licence and
  attribution; every object it produces carries that, like a label, so
  a screen can show attribution and one switch can remove every
  non-commercial source.
- **E9. Feed health on screen.** Whether a source is fresh, stale or
  down, shown wherever its objects appear and in the assistant's
  answers. Ties to the agreed object states (live, rebuilding,
  unavailable).
- **E10. Module pages that host a large existing app.** A module page
  that mounts a non-React application with its own web workers,
  WebAssembly and large static assets, isolated from the shell's
  styles and keyboard shortcuts, within Elysium's content security
  policy.
- **E11. One permission check for objects and their live data.** Live
  push (E4), area queries (E5), triggers on arrival (E6) and the
  assistant all ask the same question Elysium already answers for an
  object, so live data cannot become a second path around it.
  Location never decides access (owner, 31 October).
- **E12. Map layers that are not objects.** Imagery and grids (radar,
  clouds, wind) as named layers, each with its own grant and audited
  requests, served to any screen; the basemap stays ungated scenery.
- **E13. Audit for live data.** One entry per subscription (who, which
  type, which area, from when to when), not per position, so live data
  is audited without drowning the log (R2).
- **E14. Lifecycle for objects a source created.** Retire objects not
  seen for a set time, per object type: keep, mark inactive, or remove
  (R3).

### Astrolabe (specific)

- **G1.** The forked screen, with the game parts removed and the kept
  layers pointed at Elysium.
- **G2.** Packaging as an Elysium module: manifest, page, bundle.
- **G3.** The bridge (R1): the module page asks Elysium's API with the
  person's session and passes the frame what it may draw, in the shapes
  the screen expects; the fork's data adapters ask the page through
  messages, never the network.
- **G4.** Source configurations for each provider, using Elysium's
  generic adapters wherever they fit (the REST adapter for the slow
  feeds), and new generic adapters on `dev` where they do not.
- **G5.** Object types: Aircraft, Vessel, Satellite, Launch,
  Earthquake, Fire, Storm, Bike station, Transit vehicle; and the
  operator's own: Area, Watchlist, Incident.
- **G6.** Actions: flag a contact, add it to a watchlist, add a note,
  create an Incident, draw an Area.
- **G7.** Triggers: emergency transponder code, a contact entering an
  Area, an earthquake or fire near an Area, a watched contact going
  silent.
- **G8.** Satellite positions computed in the browser from the stored
  orbits (orbits change daily; positions every frame).
- **G9.** Basemap and terrain choices, and their attribution.

## Gaps found on review (31 October)

What the first draft missed, each now placed in a phase.

- **R1. The fork must never hold the person's session.** It is about
  240,000 lines of someone else's JavaScript. Run on Elysium's origin,
  it could call any part of Elysium's API as the person using it. So it
  runs in a SANDBOXED frame with an origin of its own, and never talks
  to Elysium directly: the module page around it (our code) asks
  Elysium, with the person's session and permissions, and hands the
  frame only the data it may draw, through messages. The fork's data
  adapters ask the page, not the network. This also settles where the
  screen's data layer runs (it was an open question). It has costs to
  measure in Phase 1: a sandboxed frame has no localStorage (their
  screen keeps settings there), its tile requests carry no origin, and
  web workers must still start.
- **R2. Audit at live volume.** Elysium audits reads. Ten thousand
  contacts refreshed every few seconds would write millions of entries
  a day if each read were one entry. The audit needs a shape for live
  data: one entry per subscription (who, what type, which area, from
  when to when), not per position. Generic: E13.
- **R3. Objects created on first sight need a lifecycle.** An aircraft
  seen once and never again would stay an object forever. Objects a
  source created may need to be retired after a quiet period (kept,
  marked inactive, or removed), set per object type. Generic: E14.
- **R4. Provider keys stay in Elysium.** Their screen bakes keys into
  its bundle at build time. Ours holds no keys at all: providers are
  read by Elysium's sources, using Elysium's secret references, and
  the basemap and terrain are keyless ones (Esri imagery, Re:Earth
  terrain). No Google or Cesium ion keys in the first version.
- **R5. Third-party tile hosts see where the operator is looking.** The
  browser fetches basemap and terrain tiles straight from their hosts,
  which learn the viewport. Acceptable for public basemaps now; a tile
  proxy through Elysium is possible later. Recorded, not built.
- **R6. Keeping the fork current.** Their repository moves (it was
  trending). The fork is pinned to one upstream commit, imported
  untouched in one commit, with our changes on top; taking upstream
  changes is a deliberate step (a new import, our changes replayed),
  never automatic.
- **R7. Testing.** Their own unit tests keep running in the fork, so a
  removed feature that breaks a kept one shows. The frame, the
  messages and permissions are tested with Elysium's browser tests
  (jsdom cannot see a frame or a globe). Elysium-side work is tested as
  any `dev` change. Each phase lists what a person clicks to check it.
- **R8. Size.** The built screen with Cesium is large. A budget is set
  once measured in Phase 1, and the excluded bundled data (about 19 MB
  in their data folder, the 3D models, the demo events) is removed in
  the fork.
- **R9. Patches for a branch with no history.** `scripts/make_patch.sh`
  assumes `dev`. Until it gains a root mode (a small change on `dev`),
  this branch's patches are made by hand with the same checks: count,
  trailers, a dry run onto an empty branch.
- **R10. Their visual language.** Their screen is dark, dense and styled
  as a "cockpit". Phase 1 keeps it; a pass toward Elysium's own look
  comes after the data works, and only where an operator would gain.

## Phases

Each phase ends with something a person can click and check.

**Phase 0: groundwork.** This branch and this plan agreed; the Reader's
report on their screen's interface and feeds; a feeds table (provider,
terms, commercial or not, privacy handling), verified against each
provider's own pages; a script that imports their repository at a
pinned commit, untouched, as one commit; the generic items E1-E14
proposed in `BLOCKING.md`, one at a time, as each is designed.

**Phase 1: the screen inside Elysium.** Their screen imported, with its
MIT notice; game parts and excluded layers removed (listed in
`FORK.md`); Cesium's bare widget, so no `unsafe-eval`; packaged as an
Elysium module page that hosts it in a sandboxed frame (R1); a globe
with basemap and terrain and no data yet. First, a spike: does their
screen run in a sandboxed frame (settings storage, workers, tiles), and
what must the fork change for it to. Needs E10. Checked in a real
browser, and the size measured (R8).

**Phase 2: slow data through today's Elysium.** Earthquakes, fires,
storms, launches, satellites and bike-share as object types, fed by the
REST adapter through the normal pipeline, and drawn on the globe from
Elysium's API. Grants by layer. A first trigger and action: an
earthquake near an Area creates an Incident and notifies. Proves the
whole loop with what Elysium has now.

**Phase 3: Elysium's live data (on `dev`).** E1 observations, E2
streaming sources, E3 rules at the door, E4 live push, E5 geography,
E6 triggers on arriving data, E12 map layers (radar, clouds, wind). Designed generically, through the normal
patch workflow, with independent review.

**Phase 4: aircraft and ships.** On top of phase 3: global contacts,
each an object created on first sight, privacy-blocked and unmappable
records dropped at the door, trails, click to track, operator actions
on the globe, triggers on arrival, and the check that a person without
permission on an object sees none of it or its live data.

**Phase 5: scale.** E7 and measurement: the simulator pushing volume
beyond what the feeds give, until something breaks; the numbers written
down.

**Phase 6: the assistant over live data.** Questions such as "how many
ships are within 50 km of Rotterdam now", through the assistant's
existing read-only tools and permission checks.

**Phase 7: commercial switch.** E8 in use: non-commercial feeds
replaced or switched off in one place.

## Open questions

1. **Which basemap**: Esri's keyless imagery is not clearly permitted
   and may not be stored; a properly licensed one is being researched.
2. **Whether their screen runs in a sandboxed frame** without large
   changes: settled by the Phase 1 spike (R1).

Settled: where the screen's data layer runs (R1); patches for this
branch (R9); which feeds, and what each drops at the door
(`docs/feeds.md`, owner's choices of 1 November).

## Sources

- God's Eye View: https://github.com/bilawalsidhu/gods-eye-view
  (code MIT; data under each provider's own terms, `DATA_SOURCES.md`)
- Foundry geotemporal series:
  https://palantir.com/docs/foundry/geotemporal-series/overview and
  https://www.palantir.com/docs/foundry/geospatial/integrate-geotemporal-series-with-the-ontology/
