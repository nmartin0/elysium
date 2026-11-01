# Feeds: providers, terms, and what we drop at the door

Phase 0's feeds table. Researched 1 November 2026 from each provider's
own pages, by an agent that did not read God's Eye View's code. Quotes
are as fetched; re-check exact legal wording before relying on it in a
contract. "Storage" means keeping a copy in Elysium, which every feed
here does.

## Table

| Provider | Data | Access | Key | Limits | Licence | Storage | Commercial | Attribution |
|---|---|---|---|---|---|---|---|---|
| adsb.lol | Aircraft (readsb JSON) | REST polling | None now; "in the future" by feeding | "dynamic based on the environment load" | ODbL 1.0 | Yes (ODbL; a public derived database must be ODbL) | Yes under ODbL; no separate API terms found | ODbL attribution |
| OpenSky | Aircraft | REST, OAuth2 | Optional | 400-8,000 credits/day | Research-only agreement | **No**: copies expunged when research ends | **No**; "operational" use needs a written licence | Schäfer et al. 2014 |
| airplanes.live | Aircraft, plus /mil /ladd /pia | REST | None | 1 request/s | Terms page did not load | Unknown | Non-commercial | Unknown |
| ADS-B Exchange | Aircraft, "unfiltered, unblocked" | Paid API | Yes | Paid tiers | JetNet terms | Restricted | By contract only | — |
| adsbdb | Aircraft type/registration; routes | REST | None | Not stated | Code MIT; route data restricted | **Routes: No** | Not stated | PlaneBase; routes D. Taylor, J. Mason |
| AISStream.io | Global AIS | WebSocket | Yes, server-side only | 3 connections; 1 subscription update/s; 200 MMSIs per subscription | **None published** | Not stated | **Unknown, treat as no** | Not stated |
| BarentsWatch / Kystverket | Norway-zone AIS | OAuth API / open raw stream (153.44.253.27:5631) | BarentsWatch yes; raw no | Contact them before high traffic | NLOD 2.0 | Yes | Yes | «Data delivered by BarentsWatch» |
| Danish Maritime Authority | AIS history files; live is paid | Files | No | — | Danish PSI act | Yes, if no persons identifiable | Not clear | Not stated |
| CelesTrak | Orbital elements (GP) | REST, `FORMAT=json` | None | New data every 2 h; 50 errors/2 h; >100 MB/day risks a block | None stated | Implied (they suggest caching) | Not stated | Not stated |
| Space-Track | GP, catalogue | REST | Account | <30/min, <300/h | US government user agreement | Yes | Via request process; redistribution needs approval | — |
| Launch Library 2 | Launches | REST | Optional | 15/h without a key | Not found | Not found | Not found | Not found |
| USGS | Earthquakes, GeoJSON | REST, updated every minute | None | Not stated | US public domain | Yes | Yes | "U.S. Geological Survey" |
| NASA FIRMS | Fire detections | REST/CSV | Free MAP_KEY | 5,000 transactions / 10 min | NASA open data (CC0) | Yes | Yes, no implied endorsement | FIRMS acknowledgement |
| NIFC WFIGS | US fire perimeters | ArcGIS FeatureServer | None | Not stated | Disclaimer only | Implied yes | Implied yes | "US DOI Office of Wildland Fire: IRWIN…" |
| NOAA NHC | Tropical storms | JSON | None | Not stated | NWS public domain | Yes | Yes | Name the NWS material; no endorsement |
| NOAA nowCOAST | Satellite clouds, lightning, precipitation | WMS / ArcGIS REST | None | Not found | NWS public domain (assumed) | Yes (assumed) | Yes (assumed) | NOAA (assumed) |
| NOAA GFS (AWS) | Forecast grids | S3 | None | — | "can be used as desired" | Yes | Yes | Citation sentence |
| ECMWF Open Data | Forecast grids | HTTP / cloud mirrors | None | 500-2,000 connections | CC BY 4.0 + ECMWF terms | Yes | Yes | Five-part text (below) |
| GBFS systems | Bike-share | JSON | Varies | Varies | Per system; blank means public domain | Per system | Per system | Per system |
| GTFS-Realtime feeds | Transit vehicles | Protobuf over GET | Per feed | Per feed | Per feed (Mobility Database catalogue CC0) | Per feed | Per feed | Per feed |
| Esri World Imagery | Imagery basemap | Tiles | Subscription under Esri terms | — | Esri Master License | **No** (no harvesting) | **No** without an Esri licence | Esri credit line |
| Mapterhorn | Terrain | Tiles / PMTiles | None | Not stated | Per source (CC BY 4.0, Etalab, DL-DE, OGL…) | PMTiles downloadable | Mostly yes; per source | Per source (`attribution.json`) |
| OSM tile servers | Raster map | Tiles | None; User-Agent required | Best effort | ODbL data | No offline use, no bulk | "access may be withdrawn" | © OpenStreetMap contributors |

## Dropped at the door (rules for our sources)

- **Aircraft (adsb.lol / readsb):** the `dbFlags` bitfield
  (wiedehopf/readsb `README-json.md`): `military = dbFlags & 1`,
  `PIA = dbFlags & 4`, `LADD = dbFlags & 8`; drop all three. Drop
  addresses starting with `~` (non-ICAO, e.g. TIS-B). Drop the `/mil`
  set. Keep an operator blocklist of hex codes. Caveat: the flags come
  from a community database, so unflagged military or privacy aircraft
  can slip through; the blocklist is the backstop.
- **Ships (any AIS):** drop ship type 35 ("engaged in military
  operations") and 55 ("law enforcement"). Ship type arrives in static
  messages, separately from positions, so a vessel's positions are held
  until its type is known. Keep an operator blocklist of MMSIs. No AIS
  privacy opt-out list exists; Norway's feeds already exclude fishing
  vessels under 15 m and recreational craft under 45 m.
- **Satellites (CelesTrak groups):** exclude `gps-ops`, `glo-ops`,
  `gnss` (contains both) and `military`; `active` is a superset, so
  subtract those. `sar` and `radar` are kept (owner, 1 November).
- **Transit (GTFS-Realtime):** drop the vehicle's `license_plate` field.
- **Bike-share (GBFS):** vehicle ids are not persistent by the spec;
  keep it that way (no tracking of individual bikes across rentals).
- **adsbdb routes:** never stored.

## Attribution texts we must show

- USGS: "Credit: U.S. Geological Survey".
- NASA FIRMS: "We acknowledge the use of data and/or imagery from
  NASA's Fire Information for Resource Management System (FIRMS)… part
  of NASA's Earth Science Data and Information System (ESDIS)."
- BarentsWatch: «Data delivered by BarentsWatch», visible, linked.
- NOAA GFS: "NOAA Global Forecast System (GFS) was accessed on DATE
  from https://registry.opendata.aws/noaa-gfs-bdp-pds."
- ECMWF (all five): "This service is based on data and products of the
  European Centre for Medium-Range Weather Forecasts (ECMWF)"; source
  www.ecmwf.int; "This ECMWF data is published under a Creative Commons
  Attribution 4.0 International (CC BY 4.0)" with the licence link; "ECMWF
  does not accept any liability whatsoever for any error or omission in
  the data, their availability, or for any loss or damage arising from
  their use."; an indication of any modifications.
- OpenStreetMap: "© OpenStreetMap contributors".
- adsb.lol: ODbL attribution (no exact wording published).

## Decided (owner, 1 November 2026)

- **Satellites are kept.** Every published orbit originates with the US
  Space Force, but the data is about satellites, not about the military;
  the military, GPS, GLONASS and GNSS groups are dropped. The `sar` and
  `radar` groups are kept.
- **Ships: both feeds.** BarentsWatch/Kystverket (Norway, open terms)
  and AISStream.io (global) marked non-commercial until it publishes
  terms, so one switch removes it.
- **Aircraft: adsb.lol**, with the door rules above.
- **Basemap: a properly licensed one is to be found** (research under
  way); Esri's keyless imagery is not used.

## Recommendation (as researched)

- **Aircraft: adsb.lol**, with the door rules above. Not OpenSky
  (storage forbidden), not ADS-B Exchange (deliberately unfiltered).
- **Ships: BarentsWatch/Kystverket** (open, storable, commercial, but
  Norway only), plus **AISStream.io for global coverage marked
  non-commercial** until it publishes terms.
- **Basemap: not Esri** (keyless use not clearly permitted, no storage)
  and not OSM's own tile servers for anything beyond light use;
  something else is needed (open question).

## Could not verify

adsb.lol's rate-limit figure and whether it filters LADD/PIA itself;
airplanes.live and Launch Library 2 terms pages; ADS-B Exchange block
lists; adsbdb limits and terms; whether OpenSky filters LADD/PIA;
AISStream terms of any kind; the Danish Maritime Authority's commercial
and attribution terms; a CelesTrak User-Agent rule or licence;
nowCOAST's own terms, limits and radar layer names; the Mobility
Database API limits; any provider page for Re:Earth terrain;
Mapterhorn's fair-use policy and full source list; whether keyless Esri
World Imagery is allowed at all.

## Sources

adsb.lol API https://www.adsb.lol/docs/open-data/api and privacy
https://www.adsb.lol/docs/privacy-license; readsb JSON
https://github.com/wiedehopf/readsb/blob/dev/README-json.md; OpenSky
terms https://opensky-network.org/about/terms-of-use and FAQ
https://opensky-network.org/about/faq; airplanes.live
https://airplanes.live/api-guide/; ADS-B Exchange
https://dev.adsbexchange.com/data/; adsbdb
https://github.com/mrjackwills/adsbdb; AISStream
https://aisstream.io/documentation; Kystverket
https://www.kystverket.no/en/sea-transport-and-ports/ais/access-to-ais-data/;
BarentsWatch https://developer.barentswatch.no/docs/AIS/live-ais-api
and https://barentswatch.no/en/articles/api-terms-and-conditions; NLOD
https://data.norge.no/nlod/en/2.0; Danish Maritime Authority
https://www.dma.dk/safety-at-sea/navigational-information/ais-data;
AIS ship types https://www.navcen.uscg.gov/ais-class-a-static-voyage-message-5;
CelesTrak https://celestrak.org/NORAD/documentation/gp-data-formats.php
and https://www.celestrak.org/usage-policy.php; Space-Track
https://www.space-track.org/documentation#/user_agree; Launch Library
https://thespacedevs.com/llapi; USGS
https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php and
https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits;
FIRMS https://firms.modaps.eosdis.nasa.gov/api/map_key/ and
https://www.earthdata.nasa.gov/data/tools/firms; NASA data use
https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance;
NWS https://www.weather.gov/disclaimer; GFS
https://registry.opendata.aws/noaa-gfs-bdp-pds/; ECMWF
https://www.ecmwf.int/en/forecasts/datasets/open-data and
https://apps.ecmwf.int/datasets/licences/general/; GBFS
https://github.com/MobilityData/gbfs; GTFS-Realtime
https://gtfs.org/documentation/realtime/reference/; Mobility Database
https://github.com/MobilityData/mobility-database-catalogs; Esri
https://www.esri.com/content/dam/arcgisonline/docs/tou_summary.pdf;
Mapterhorn https://mapterhorn.com/data-access/; OSM tiles
https://operations.osmfoundation.org/policies/tiles/
