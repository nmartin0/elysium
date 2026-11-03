# Data Sources & Attribution

God's Eye View's **code** is [MIT](LICENSE)-licensed. **The MIT grant covers the source code only — it does NOT extend to third-party data or visual assets.** Every third-party source keeps its own license and terms. This file documents the live and bundled data sources.

How to read this:

- **The non-permissive datasets are carved out, not omitted.** Some bundled data (e.g. TeleGeography, CC BY-NC-SA) isn't MIT-compatible. Rather than hide it, we **bundle it with a clear license carve-out** so the app works out of the box — but it stays under the provider's terms.
- **If your use doesn't fit a dataset's license, remove that dataset.** Most importantly: TeleGeography is **NonCommercial** — commercial users must delete it (or license it from TeleGeography). It's one self-contained folder.
- **Attribution is shown in-app** and listed here. Keep it intact. The required Google/Cesium credit renders on the on-globe credit line (bottom-left, `#cesium-credits`), and every per-layer credit below is registered into the expandable **"Data attribution"** lightbox on that line (`src/data/dataCredits.js` → `viewer.creditDisplay.addStaticCredit`). Both stay visible in clean-view and recording modes.

---

## Live sources (fetched at runtime — not stored in this repo)

| Source                                                                | Used for                                                                                                                            | License / terms                                                                                                                                                                                                                                                                                                                                       | Attribution                                                                                                                                 |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **NOAA GFS (wind)** (`noaa-gfs-bdp-pds.s3.amazonaws.com`) | Global 10 m wind, optional 2 m temperature and mean sea-level pressure for Wind. Keyless; latest 6-hourly 0.25° cycle, byte-range GRIB2 reads, cached for an hour | U.S. public domain (NOAA); keyless via NOAA Open Data on AWS | "NOAA Global Forecast System (GFS)" (courtesy; not an endorsement) |
| **ECMWF IFS (wind)** (`data.ecmwf.int/forecasts`, ECMWF Open Data) | The alternative Wind model: 10 m wind, optional 2 m temperature and mean sea-level pressure. Keyless; latest 6-hourly 0.25° run, byte-range GRIB2 reads, cached for an hour | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) plus the [ECMWF Terms of Use](https://apps.ecmwf.int/datasets/licences/general/) | "This service is based on data and products of the European Centre for Medium-Range Weather Forecasts (ECMWF)", with the CC BY 4.0 link, the modification notice and ECMWF's liability disclaimer — shown in-app |
| **NOAA nowCOAST observed weather** (`nowcoast.noaa.gov/geoserver/observations/{weather_radar,satellite}/ows`, WMS 1.1.1) | Rain radar (MRMS base reflectivity, contiguous US, about 4-minute updates) and Satellite clouds (GOES-19/18 Band 14 regional infrared, about 5-minute updates; global infrared mosaic, hourly). Keyless; layer metadata refreshed every 2 minutes, exact-time images cached for up to 24 hours | [NOAA disclaimer](https://oceanservice.noaa.gov/disclaimer.html) | "NOAA nowCOAST · NWS/OAR MRMS radar; NESDIS GOES and global satellite partners" |
| **NOAA nowCOAST lightning density** (`nowcoast.noaa.gov/geoserver/observations/lightning_detection/ows`) | Lightning density: 15-minute accumulated strike density on an approximately 8 km grid, Americas and Pacific. Keyless; layer metadata refreshed every 10 minutes, exact-time images cached for up to 24 hours | NOAA Level-5 derived product from Vaisala NLDN/GLD360; the [product description](https://ocean.weather.gov/lightning/lightning_pdd.php) permits public distribution of this density product, not of raw Vaisala detections | "NOAA/NWS nowCOAST; derived from Vaisala NLDN/GLD360" |
| **NOAA NHC / CPHC advisories** (`www.nhc.noaa.gov/CurrentStorms.json` + the `mapservices.weather.noaa.gov` tropical weather summary MapServer) | Cyclone advisories: storm positions, forecast tracks, points and cones for the Atlantic and eastern/central North Pacific. Keyless through `/api/cyclones`; cached for 5 minutes | [NWS public-data terms](https://www.weather.gov/disclaimer); no endorsement implied | "NOAA/NWS NHC / CPHC" |
| **OpenStreetMap** | Map and place data (roads, place search, outlines); via bundled data, Nominatim and optional self-configured Overpass | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) | © OpenStreetMap contributors |
| **Google Map Tiles API** (Photorealistic 3D Tiles) + Places/Geocoding | The 3D globe, place search and geocoding                                                         | Google Maps Platform ToS (proprietary, your own key + billing)                                                                                                                                                                                                                                                                                        | "Google" / "Google Maps" logo — **shown in-app**, required                                                                                  |
| **OpenSky Network**                                                   | Primary worldwide live-flight snapshot                                                                                              | Non-commercial research/education license                                                                                                                                                                                                                                                                                                             | Schäfer et al., _"Bringing Up OpenSky"_, IPSN 2014 + opensky-network.org                                                                    |
| **adsb.lol point API**                                                | Bounded live-flight fallback when OpenSky has no usable snapshot; GNSS Integrity layer (aircraft-reported NIC/NACp and GPS-loss integrity facts, via `/api/gnss-integrity`, 60 s server cache)                                                                    | ODbL 1.0                                                                                                                                                                                                                                                                                                                                              | adsb.lol contributors; `api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{radius}`                                                                  |
| **adsb.lol**                                                          | Aircraft traces and the civil fallback                                                                                                  | ODbL 1.0                                                                                                                                                                                                                                                                                                                                              | "adsb.lol" (ODbL)                                                                                                                           |
| **adsbdb** (`api.adsbdb.com`) | Aircraft type, model name and registration by ICAO hex for enriched flights; airline and origin/destination airports for the tracked flight's callsign | No licence or rate limit is published for the service. Its own credits: aircraft data from PlaneBase, ICAO-to-N-number conversion by Guillaume Michel, and flight route data that "is the work of David Taylor, Edinburgh and Jim Mason, Glasgow, and may not be copied, published, or incorporated into other databases without the explicit permission of David J Taylor, Edinburgh" | "adsbdb — api.adsbdb.com" (courtesy); route data credited to David Taylor, Edinburgh, and Jim Mason, Glasgow |
| **AISStream.io**                                                      | Live vessels (AIS)                                                                                                                  | Free, beta, no formal ToS; AIS is a public broadcast                                                                                                                                                                                                                                                                                                  | "AISStream.io" (courtesy)                                                                                                                   |
| **CelesTrak**                                                         | Satellite TLEs (SGP4)                                                                                                               | US-government-origin data, no license; citation requested                                                                                                                                                                                                                                                                                             | "CelesTrak (celestrak.org), Dr. T.S. Kelso"                                                                                                 |
| **The Space Devs — Launch Library 2 v2.3**                            | Recent launch, payload, stage, and recovery metadata for Space Missions (30d)                                                       | [The Space Devs terms of use](https://github.com/TheSpaceDevs/Tutorials/blob/main/faqs/faq_TSD.md#terms-of-use): data may be used and shared in any form; avoid forwarding it without added value; attribution is encouraged (not mandatory). [Official API limits](https://ll.thespacedevs.com/docs/): 15 unauthenticated calls/hour; optional token | "Launch Library 2 — The Space Devs" (courtesy attribution)                                                                                  |
| **Esri World Imagery** (ArcGIS Online tile service)                   | The keyless satellite basemap — the default landing when no Google/ion credential is configured, and the "Esri Satellite" map stack | [Esri Master Agreement](https://www.esri.com/en-us/legal/terms/full-master-agreement): the public World Imagery service is usable in public-facing apps with attribution; no key is required for this classic endpoint, but Esri governs and can change access — an app at scale should review current ArcGIS Location Platform terms                 | "Powered by Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community" (provider carries the service's own credit line) |
| **USGS**                                                              | Earthquakes                                                                                                                         | U.S. public domain                                                                                                                                                                                                                                                                                                                                    | "Data courtesy of the U.S. Geological Survey"                                                                                               |
| **Environment and Climate Change Canada** (MSC GeoMet OGC API) | Air quality (AQHI) — Canadian station observations | [ECCC Data Servers End-use Licence](https://eccc-msc.github.io/open-data/licence/readme_en/) (open, attribution required, no endorsement implied) | "Contains information licensed under the Environment and Climate Change Canada Data Servers End-use Licence" |
| **NASA GIBS** (WMTS tiles + Worldview Snapshots) and **NASA CMR** (granule catalog) | Recent Imagery layer: HLS S30/L30 (Sentinel-2, Landsat 8/9) and VIIRS true-colour tiles draped on the map, per-day thumbnails and PNG exports; the HLS granule catalog (dates, cloud, footprints) for a selected box | U.S. public domain (NASA data); keyless, browser-direct (CORS `*`); no bulk use — one 30-day catalog query per box, tiles bounded to the box, six tile requests in flight | "We acknowledge the use of imagery provided by services from NASA's Global Imagery Browse Services (GIBS), part of NASA's Earth Science Data and Information System (ESDIS)." — [gibs.earthdata.nasa.gov](https://gibs.earthdata.nasa.gov), [HLS](https://lpdaac.usgs.gov/products/hlss30v002/) |
| **NIFC WFIGS** (Wildland Fire Interagency Geospatial Services, ArcGIS feature service) | Fire Perimeters layer: current interagency wildfire incident perimeters, containment, and incident facts | U.S. public domain (interagency wildland-fire data published through the [NIFC Open Data portal](https://data-nifc.opendata.arcgis.com/)); fetched keyless through `/api/fire-perimeters` (5-minute server cache) with `exceededTransferLimit` paging | "Wildfire perimeters: National Interagency Fire Center (WFIGS)" |
| **InciWeb** (inciweb.wildfire.gov)                                    | Per-incident "InciWeb ↗" card links to official incident pages (narratives, evacuation/closure notices) | U.S. government public incident information. Links are matched best-effort by incident name and state, with incident page origin and update times checked on selection. Same-origin `/api/fire-perimeters/inciweb` routes cache the catalog for 1 hour and publication metadata for 30 minutes; linked pages remain InciWeb content | "Incident information: InciWeb (inciweb.wildfire.gov)" |
| **S2 Underground GhostMaps** (`github.com/s2underground/GhostMaps`) | S2 GhostMaps layer: the current edition of S2's KMZ intel products (Common Intelligence Picture, 30-day kinetic pull, Border Crisis Map, Iran and Yemen products, newest incident drop). Keyless. `/api/ghostmaps` reads the branch head from git's ref advertisement every 15 s (`GHOSTMAPS_POLL_SECONDS`, minimum 5 s), lists the tree through the GitHub REST API only when the head changes (optional `GITHUB_TOKEN`), downloads files by commit-pinned raw URLs into `.gev-cache/ghostmaps/` and pushes new catalogs to browsers over server-sent events | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) (repository README: "S2 Underground © 2025 by S2A1"); non-commercial, attribution required; files are fetched at runtime, never stored in this repository | "S2 GhostMaps intel products: S2 Underground © by S2A1, CC BY-NC-SA 4.0" — shown in-app |
| **Photon** (komoot)                                                   | Keyless place search — the fallback when no Google Maps key is configured, or when Google declines the Geocoding request            | Service: free public instance, [fair use](https://photon.komoot.io) (no bulk/heavy use); underlying data: **ODbL 1.0**                                                                                                                                                                                                                                | "Photon (komoot)"                                                                                          |
| **GBFS (Lyft / BCycle / Social Bicycles / PBSC)**                     | Bikeshare availability                                                                                                              | Per-feed (attribution-only)                                                                                                                                                                                                                                                                                                                           | Credit the operator (e.g. Austin BCycle) + its `license_url`                                                                                                   |
| **Bike Share Toronto** (`toronto.publicbikesystem.net`) | Bikeshare station availability, Toronto | Operator GBFS feed. No licence is published: the City's open-data package declares none and the feed has no `license_url`. Attribution is given to the operator. | "Bike Share Toronto (Toronto Parking Authority)" |
| **Bike Itaú / Tembici** (`*.publicbikesystem.net`, seven Brazilian cities, Santiago and Bogotá) | Bikeshare station availability: São Paulo, Rio de Janeiro, Salvador, Recife, Porto Alegre, Brasília, Curitiba, Santiago de Chile and Bogotá | Operator GBFS feeds. No licence is published: the feeds' `system_information.json` carries no `license_url`, operator or attribution fields. Attribution is given to the operator. | "Bike Itaú (Tembici)"; "Tembici Bogotá" |
| **Bicing** (`barcelona.publicbikesystem.net`) | Bikeshare station availability, Barcelona | Operator GBFS feed (PBSC), keyless. The feed publishes no licence; the City's own open-data copy of the same station data is CC BY 4.0 but needs a token. Attribution is given to the operator. | "Bicing, Barcelona City Council (B:SM)" |
| **BiciMAD** (`madrid.publicbikesystem.net`) | Bikeshare station availability, Madrid | Operator GBFS feed (PBSC), keyless. Madrid's open-data catalogue publishes this feed (`datos.madrid.es`, dataset `900021-0-bicimad-gbfs`, owner EMT Madrid) under [EMT's open-data terms](https://mobilitylabs.emtmadrid.es/sip/terms-of-use): commercial and non-commercial reuse, with attribution REQUIRED (section 5.2). | "Powered by EMT de Madrid", linking to `https://www.emtmadrid.es` |
| **Spanish city bikes on PBSC** (`*.publicbikesystem.net`: Zaragoza, Valladolid, A Coruña, Donostia-San Sebastián, Bilbao, Rivas-Vaciamadrid) | Bikeshare station availability: Bizi Zaragoza, BIKI, BiciCoruña, Dbizi, Bilbao Bizi, BicinRivas | Operator GBFS feeds, keyless. The feeds' `system_information.json` carries no `license_url`, and no operator or city publishes a licence for them; MobilityData's catalogue lists CC BY 4.0 without naming a source. Attribution is given to the operator. | "Bizi Zaragoza"; "BIKI, AUVASA (Valladolid)"; "BiciCoruña"; "Dbizi (Donostia-San Sebastián)"; "Bilbao Bizi, Bilbao City Council"; "BicinRivas, Rivas-Vaciamadrid City Council" |
| **AMBici** (nextbike, `gbfs.nextbike.net`) | Bikeshare station availability, Barcelona metropolitan area (e-bikes) | Operator GBFS feed, keyless. `system_information.license_id` is **CC0-1.0**; no attribution required, given anyway. | "AMBici, Àrea Metropolitana de Barcelona, operated by nextbike" |
| **Oslo / Bergen / Trondheim Bysykkel** (Urban Sharing, `gbfs.urbansharing.com`) | Bikeshare availability, Oslo, Bergen and Trondheim city bikes. Keyless GBFS; the proxy sends the `Client-Identifier` header the operators ask for | [NLOD 2.0](https://data.norge.no/nlod/en/2.0) — attribution REQUIRED ([Oslo](https://oslobysykkel.no/en/open-data/realtime), [Bergen](https://bergenbysykkel.no/en/apne-data/sanntid), [Trondheim](https://trondheimbysykkel.no/en/open-data/realtime)) | "Contains data under the Norwegian licence for Open Government data (NLOD) made available by Oslo Bysykkel, Bergen Bysykkel and Trondheim Bysykkel" |
| **Kolumbus / Farte Bysykkel** (Entur Mobility, `api.entur.io/mobility/v2/gbfs`) | Bikeshare availability, Kolumbus Bysykkel (Stavanger/Nord-Jæren) and Farte Bysykkel (Skien/Porsgrunn). Keyless GBFS; the proxy sends the `ET-Client-Name` header Entur requires and is limited to Entur's GBFS paths | [NLOD](https://data.norge.no/nlod/en/2.0) per the [Entur Mobility API docs](https://developer.entur.org/pages-mobility-docs-mobility-v2) — attribution REQUIRED | "Contains data under the Norwegian licence for Open Government data (NLOD) made available by Entur (Kolumbus Bysykkel, Farte Bysykkel)" |
| **JCDecaux Cyclocity** (`api.cyclocity.fr`) | Bikeshare availability: Bysykkel Lillestrøm, Valenbisi (Valencia) and Sevici (Seville). Keyless GBFS; the proxy is limited to JCDecaux contract paths | [Licence Ouverte / Etalab](https://developer.jcdecaux.com/files/Open-Licence-fr.pdf) (each feed's `license_url`) — attribution REQUIRED | "Bysykkel Lillestrøm, Valenbisi, Sevici: JCDecaux, Licence Ouverte" |
| **MBTA / MassDOT** (cdn.mbta.com) | Transit layer live vehicles and up to 15 minutes of recently observed positions, Greater Boston | MBTA / MassDOT open realtime vehicle data, used for the live view and up to fifteen minutes of recently observed positions; published for developer use and not against their use. | Attribution to MBTA / MassDOT (courtesy text) |
| **CapMetro** (data.texas.gov) | Transit layer live vehicles, Austin TX | CapMetro open realtime vehicle data, used for the live view; published for developer use and not against their use. | Attribution to CapMetro (courtesy text) |
| **Metro Transit** (Metropolitan Council) | Transit layer live vehicles, Minneapolis–St Paul | Metro Transit / Metropolitan Council open realtime vehicle data, used for the live view; published for developer use and not against their use. | Attribution to Metro Transit / Metropolitan Council (courtesy text) |
| **OVapi / Stichting OpenGeo** | Transit layer live vehicles, Netherlands | OVapi / Stichting OpenGeo open realtime vehicle data, used for the live view; published for developer use and not against their use. The client sends a User-Agent and conditional requests. | Attribution to OVapi / Stichting OpenGeo (courtesy text) |
| **Entur** (api.entur.io) | Transit layer live vehicles, Norway | Entur open realtime vehicle data, used for the live view; published for developer use and not against their use. The client sends the `ET-Client-Name` identifying header. | Attribution to Entur (courtesy text) |
| **TransLink** (Queensland Government) | Transit layer live vehicles, South East Queensland | TransLink / Queensland Government open realtime vehicle data, used for the live view; published for developer use and not against their use. | Attribution to TransLink / Queensland Government (courtesy text) |
| **HSL** (realtime.hsl.fi) | Transit layer live vehicles, Helsinki | HSL (Helsinki Region Transport) open realtime vehicle data, used for the live view; published for developer use and not against their use. | Attribution to HSL (Helsinki Region Transport) (courtesy text) |
| **TTC** (bustime.ttc.ca) | Transit layer live vehicles, Toronto — surface vehicles (buses and streetcars) only | Toronto Transit Commission BusTime open realtime vehicle data, published through City of Toronto Open Data and used for the live view. The subway publishes no vehicle positions, so Lines 1/2/4 are absent rather than inferred. | Attribution to Toronto Transit Commission — City of Toronto Open Data, under the Open Government Licence – Toronto |
| **MiWay** (miapp.ca) | Transit layer live vehicles, Mississauga ON | MiWay open realtime vehicle data, published by the City of Mississauga under its Open Data Terms of Use, used for the live view. The licence is revocable and asks that the Terms of Use link travel with the data. | Attribution to MiWay — City of Mississauga Open Data, linked to the Terms of Use |
| **Hamilton HSR** (opendata.hamilton.ca) | Transit layer live vehicles, Hamilton ON | Hamilton Street Railway open realtime vehicle data, published by the City of Hamilton for commercial and non-commercial use. Not one of its 80 route ids is the number on the bus, so the route-number table in `src/data/transitFeeds.js` is derived from the City’s own published GTFS `routes.txt` under the same licence; two generations of id run at once and both are listed. | "Contains public sector Data made available under the City of Hamilton’s Open Data Licence" — wording prescribed by the licence |
| **Durham Region Transit** (drtonline.durhamregiontransit.com) | Transit layer live vehicles, Durham Region ON | Durham Region Transit open realtime vehicle data, published under the Region of Durham Open Data Licence v.1.0, which permits commercial use. | "Contains public sector information made available under The Regional Municipality of Durham's Open Data Licence" |
| **Guelph Transit** (glphtrpcloud.com) | Transit layer live vehicles, Guelph ON | Guelph Transit open realtime vehicle data, published by the City of Guelph on its open-data developer page and used for the live view. Its route ids are internal database keys, so the 33-row route-number table in `src/data/transitFeeds.js` is derived from the City’s own published GTFS `routes.txt` under the same licence. | "Contains information licensed under the Open Government Licence – City of Guelph" — wording prescribed by the licence |
| **Kingston Transit** (api.cityofkingston.ca) | Transit layer live vehicles, Kingston ON | Kingston Transit open realtime vehicle data, catalogued by the City of Kingston as open data and used for the live view. | "Contains information licensed under the Open Data Licence – City of Kingston" — wording prescribed by the licence |
| **Barrie Transit** (myridebarrie.ca) | Transit layer live vehicles, Barrie ON | Barrie Transit realtime data, published by the City of Barrie under a licence accepted by use of the data. The licence is revocable and requires no attribution. | Courtesy credit to the City of Barrie (the licence requires none, and its trademark clause is broad) |
| **YRT/Viva** (rtu.york.ca) | Transit layer live vehicles, York Region ON | York Region Transit realtime data, first-party York Region infrastructure under the YRT Open Data Licence v2.0, which permits commercial use and makes attribution optional. Viva route ids are named by colour from York Region’s published GTFS. | "Contains public transit Information made available under YRT’s Open Data Licence" — the licence’s own wording, given though not required |
| **Burlington Transit** (opendata.burlington.ca) | Transit layer live vehicles, Burlington ON | Burlington Transit realtime data under the City of Burlington Open Data Terms of Use, which permit any lawful purpose. The terms are revocable and must travel with the data, so the credit links them. Route ids are internal keys and are joined to the City’s published GTFS. | Credit to the City of Burlington plus a link to its Open Data Terms of Use, which the licence requires |
| **Re:Earth Terrain** (Mapterhorn)                                     | Terrain (keyless globe stacks — OSM etc. — + `/api/terrain/heights` ellipsoidal-height lookups)                                     | Terrain mesh: CC BY 4.0; geoid: EGM2008 (NGA, public domain)                                                                                                                                                                                                                                                                                          | "Terrain (keyless globe stacks): Re:Earth Terrain / Mapterhorn (CC BY 4.0) / EGM2008 (NGA)"                                                 |
| **OSRM on the FOSSGIS routing servers** (`routing.openstreetmap.de`) | Street-following routes for the Directions layer, via `/api/route` | [FOSSGIS routing usage policy](https://routing.openstreetmap.de/about.html): "Display the required attribution and display a link to 'fix the map'", "Use a valid user agent and, if applicable, a correct referrer", "One request per second max", "No scraping, no heavy usage". The full policy is the German [FOSSGIS Nutzungsbedingungen](https://www.fossgis.de/arbeitsgruppen/osm-server/nutzungsbedingungen/); FOSSGIS also states that the server may be embedded in your own pages but "eine gewerbliche Nutzung ist nur mit Einschränkungen erlaubt" (commercial use only with restrictions). Route data derives from OpenStreetMap (ODbL 1.0) | "Routing: OSRM on the FOSSGIS servers" + a "fix the map" link — shown in the Data attribution popover |

### Notes on the live sources

- **Air quality (ECCC AQHI).** Keyless. Read from the MSC GeoMet OGC API (`api.weather.gc.ca`): the `aqhi-stations` catalog plus `aqhi-observations-realtime`. **Coverage is Canada only** — ECCC is the single registered provider, and the layer row and readout card both say so. Roughly 134 stations across ECCC's five administrative zones (Atlantic, Quebec, Ontario, Prairies & North, Pacific & Yukon). AQHI publishes hourly, so readings poll every 20 minutes and the station catalog, which changes a few times a year, is refetched only every 12 hours. Observations are requested with `latest=true`; without it the collection returns the full history, roughly 2,000 rows nationally. Readings older than six hours are dropped rather than displayed as current.

  Readings are stored as `{ provider, scale, value, band }` rather than a bare number, because air-quality indices are not interchangeable: AQHI runs 1-10+ on health risk, the US AQI runs 0-500 on concentration breakpoints, and Europe's EAQI is a five-step category. Naming the index a value belongs to is what lets another network be added later without inventing a shared numeric meaning that does not exist.

  AQHI is reported by ECCC as an integer from 1 to 10 with an open-ended "10+" above that. The API returns the underlying decimal (1.08, 2.32); the layer rounds to the published form rather than displaying a precision the index does not claim.

  **Quebec is thinly represented**, and that is upstream rather than a filter here: the province runs its own Info-Smog program, so only a handful of Quebec stations appear in ECCC's national feed. The reporting station count also varies hour to hour as stations report or fall silent.


- **Google Maps Platform.** You supply your own API key and are bound by [Google's ToS](https://cloud.google.com/maps-platform/terms). Google Maps Content (tiles, geocodes, places) **may not be cached, stored, rehosted, or committed** — this app only ever uses it live, which is the compliant pattern. The "Google" attribution is displayed on the globe and must stay visible. Restrict your key (see [SECURITY.md](SECURITY.md)).
- **OpenSky Network.** Its license is **non-commercial**, and operational use of the REST API in a live product can require a prior written agreement with OpenSky — even for non-profit/government use. If you deploy this commercially, contact OpenSky for your own terms. The flights layer is a toggle and runs anonymously by default.
- **adsb.lol flight fallback.** When OpenSky is unavailable and no last-good OpenSky response exists, the server requests a cached, capped 250 nm adsb.lol point snapshot around the current camera subpoint. This is regional observed context, not worldwide completeness; provenance is exposed in the Flights stats/context row.
<a id="gnss-integrity"></a>

- **GNSS integrity (adsb.lol).** A separate keyless point request samples a 250 nm
  circle around the screen centre, snapped once to whole degrees. This does not
  reuse the Flights fallback cache. Cache lifetime is 60 s; 429 backoff is capped
  at one hour and other upstream failures cool down for 15 s. Future access may
  require feeder keys under the [API terms](https://github.com/adsblol/api).
  Airborne decoded ADS-B v1/v2 aircraft with a known 0–60 s position age qualify,
  including MLAT-positioned aircraft still broadcasting their own quality.
  TIS-B/MLAT-derived NIC and NACp are ignored. GPS-loss evidence uses
  `gpsOkLat/gpsOkLon` when present, otherwise the current known position.
  The proxy strips identity metadata and tags its response with classifier
  `gev-nic-nacp-v2`; rows carry only integrity facts.

  The method has three separately attributed parts:
  1. **GEV classifier (unvalidated):** GPS-loss flag, aircraft-reported NACp < 8,
     or aircraft-reported NIC < 7 except NIC 0 with NACp ≥ 10 (unknown containment).
     The numerical minima come from US 14 CFR 91.227(c), not a published jamming
     classifier. Readsb's [JSON contract](https://github.com/wiedehopf/readsb/blob/dev/README-json.md)
     describes the quality field origins and GPS-loss flag.
  2. **GPSJAM aggregation:** score = `100 × max(0, bad − 1) / total`, with percent
     bands < 2, 2–10, > 10. One bad aircraft is discounted. This is not the raw
     share of bad aircraft. See the [GPSJAM FAQ](https://gpsjam.org/faq).
  3. **GEV window:** 30 minutes over visited views, at least three aircraft per
     0.5° cell. These bands were developed for daily totals; with fewer than ten
     observations a cell can skip the middle band. Source timestamps date evidence
     even through cache replays, and degraded evidence expires independently.

  Medium/high cells report navigation-integrity anomalies. Interference is one
  possible explanation, not a detected or located emitter. Avionics faults and
  manoeuvring military trainers can also lower reported accuracy. Blank areas
  can be outside coverage or lack enough observations. Attribution: adsb.lol
  contributors, ODbL 1.0; GPSJAM for aggregation only.


- **adsbdb enrichment.** `/api/adsbdb` resolves an ICAO hex to aircraft type, model name and registration, and the tracked flight's callsign to an airline and an origin/destination pair. Fan-out is deliberately small because adsbdb is a free community API that publishes no quota: at most 4 requests in flight, dispatches dripped to roughly 5/s, and each key asked for at most once per session, with route lookups reserved for the tracked aircraft. The dev-server proxy caches each key for 24 hours in `.gev-cache/adsbdb.json`, negative answers included, so fresh entries survive server restarts. That gitignored cache remains local to the deployment and is not bundled with this repo. adsbdb publishes no general service license; its README says the route data may not be copied, published, or incorporated into other databases without the explicit permission of David J Taylor, Edinburgh. Deployers are responsible for obtaining any permission their use requires. Enrichment is best-effort and fail-silent — a flight that gets no answer keeps what the flight feed already gave it.
- **Launch Library 2.** `/api/launches` makes a server-side rolling-30-day query against the supported v2.3 detailed launch endpoint, caches successful responses for 15 minutes in memory and on disk, and serves the last successful response during a throttle or transient outage. Anonymous access is limited to 15 calls/hour; deployments can provide `LL2_API_TOKEN` for authenticated access. The Space Devs' published terms permit using and sharing the API data in any form, ask users not to forward it without adding value, disclaim complete accuracy, and encourage—but do not require—attribution. This app keeps a courtesy credit. Payload and stage/recovery records are shown only when supplied. Failed launches expose their source status and never receive fallback orbit geometry or a live/estimated marker. LL2 supplies launch context and event timing, not continuous ascent telemetry or live orbital state.
- **Transit (GTFS-Realtime).** The proxy requests only registered operator feeds, validates redirects, bounds responses, and uses conditional requests, short snapshot caching and failure backoff. All sixteen registered regions are live-enabled; each can be disabled independently. Vehicles use delayed playback between reports, with report age and waiting states shown separately. Session-local selected trails are available for every feed. MBTA additionally retains up to 15 minutes of recently observed positions in the running proxy, so available history can survive a browser reload; server restart clears it. History reads never fetch upstream, and other feeds have no proxy retention. Nothing is archived to disk or collected in the background. Operator text credits are included as a courtesy and do not imply endorsement. Heights are aligned to work with Google 3D tiles; subway markers are shown at street level because these feeds do not supply depth. The TTC feed is BusTime, the surface system: it carries buses and streetcars and no subway at all. About four in ten of its vehicles report no route at all (unassigned or deadheading), and those are shown with the feed default rather than a route-established mode. It sends no ETag or Last-Modified, so its conditional requests fall through to the ordinary snapshot cache. Three Golden Horseshoe neighbours run alongside it — MiWay, Hamilton HSR and Durham Region Transit — each bus-only and each polled only near its own region. Durham Region Transit publishes no bearing on any vehicle, so those sprites take their heading from observed movement like any other feed that omits it. Guelph, Kingston and Barrie extend the same pattern eastward and north. Hamilton, Guelph, Burlington and YRT publish route ids that are not the number on the vehicle, so those entries carry a route-name table taken from each operator’s own published GTFS; any id missing from a table renders unchanged rather than blank. A label is never invented: YRT runs a route `9101` that appears nowhere in its published routes, so it stays as the feed sends it. Burlington’s is the one that cannot be shortcut: `351` is route 1 while `3510` is route 10, so the table is a real join rather than a trimmed prefix. GO Transit / Metrolinx is deliberately absent: its REALTIME feed requires an API key issued by manual review, which the keyless admission rule excludes (its static schedule download is keyless, but carries no vehicle positions). Barrie and YRT/Viva each invite acceptance of their licence through a form, and each licence also states that using the data is itself acceptance; this deployment relies on that clause, which is recorded in both entries. Grand River Transit in Waterloo is absent for a different reason: it answers, but its feed header was months stale and it publishes no per-vehicle timestamps, so it would render vehicles that look live and are not. Ottawa’s OC Transpo falls to the same keyless admission rule as GO Transit — its realtime feed requires an API key. London Transit and Thunder Bay Transit publish vehicle positions over plain HTTP with no HTTPS endpoint available. Every other Ontario system — Brampton, Oakville, Niagara, Milton, Windsor, Greater Sudbury, UP Express and a dozen smaller operators — publishes static GTFS schedules only, with no realtime vehicle positions to register. Between the nine included and these exclusions, every Ontario realtime vehicle-position feed catalogued in the Mobility Database is accounted for.
- **Routing (OSRM / FOSSGIS).** `/api/route` proxies the public OSRM instances FOSSGIS e.V. runs for the OpenStreetMap community (car, bike, foot profiles). They are keyless and intended for fair, interactive use — the proxy rate-limits clients (60/min, 200/min total), caps route span and response size, caches each route for 10 minutes, and identifies itself in the User-Agent. Heavy or automated use must run its own OSRM. Routes are computed from OpenStreetMap data (ODbL); the Directions layer and voice routes never redistribute them. A route the router cannot find is reported as such; the Directions layer draws nothing in that case, and voice routes fall back to a clearly labeled straight line.
- **Re:Earth Terrain.** Keyless (no API key). Used two ways: (1) `src/mapStackController.js` swaps in a `Cesium.CesiumTerrainProvider` pointed at Re:Earth's `cesium-mesh/ellipsoid` quantized-mesh endpoint for globe stacks without a Cesium ion token (e.g. OSM), replacing a flat `EllipsoidTerrainProvider`; falls back to the flat provider if the endpoint can't be reached. (2) The server-side `/api/terrain/heights` proxy (disk-cached, serve-stale) resolves per-point ellipsoidal ground height for entity placement. Both are best-effort with a keyless-safe fallback (bundled EGM96 geoid math) if Re:Earth is unreachable.
- **OSRM on the FOSSGIS routing servers.** Keyless (no API key). Every route is requested by a person: clicking A and B in the Directions layer. The server-side `/api/route` proxy sends an identifying `User-Agent`, pins the upstream host, accepts 2-12 coordinates, rejects any leg over 600 km or a total over 2,500 km, caps the buffered response at 8 MB, times the upstream out at 12 s, rate-limits per client, caches each route for 10 minutes, and coalesces identical requests that are in flight at the same time. Turn-by-turn maneuvers are asked for only when a caller wants them (`steps=1`), so the callers that do not read them send the smaller request. The "fix the map" link the policy asks for is in the Data attribution popover beside the OpenStreetMap credit.
- **Place search.** Named-place fly-to uses Google Geocoding when a Maps key is configured, then Photon's public instance, then `/api/geocode` (Nominatim search) when neither answers. `/api/geocode` uses the shared Nominatim forward-search queue at no more than one request per second, sends an identifying `User-Agent` and `Referer`, caches answers for five minutes, shares one upstream call between identical searches already in flight, bounds the queue so a burst is refused rather than held, and drops a queued search whose caller has given up. It asks for one result per search and is not used for systematic or bulk queries.

---

## Bundled snapshots

Static datasets shipped in the repo for an out-of-the-box experience. **None are MIT** — each keeps its own license (see the carve-out in [LICENSE](LICENSE)). Each folder also has its own provenance README.

| Dataset                                                                     | Folder                            | License                                                                                                   | Commercial use?                                  | Attribution                                                                 |
| --------------------------------------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------- |
| **Datacenters** (4,351) | `datacenters/` | **ODbL 1.0** (OpenStreetMap extract) | ✅ (attribution + share-alike on data) | © OpenStreetMap contributors (shared credit) |
| **Dams** (704) | `dams/` | **ODbL 1.0** (OpenInfraMap / OSM extract) | ✅ (attribution + share-alike on data) | © OpenStreetMap contributors (shared credit) + Open Infrastructure Map |
| **TeleGeography Submarine Cable Map** (712 cables + 1,917 landing points)   | `telegeography_submarine_cables/` | **CC BY-NC-SA 3.0**                                                                                       | ❌ **NonCommercial — remove for commercial use** | "© TeleGeography — submarinecablemap.com"                                   |
| **Natural Earth physical regions** (1,046 land + 292 marine named polygons) | `natural_earth/`                  | **Public domain**                                                                                         | ✅ (no restrictions)                             | "Made with Natural Earth" (courtesy credit — not legally required)          |
| **DataSF Analysis Neighborhoods** (41 SF neighborhood polygons)             | `neighborhoods/`                  | **PDDL 1.0** (public domain)                                                                              | ✅ (no restrictions)                             | "City & County of San Francisco — DataSF" (courtesy — not legally required) |
| **Natural Earth countries, states and provinces** (260 admin-0/map units + 4,587 admin-1 polygons)             | `natural_earth/`                  | **Public domain**                                                                                         | ✅ (no restrictions)                             | "Made with Natural Earth" (courtesy credit — not legally required)          |
| **US Census Bureau counties** (3,235 county polygons)                       | `us_census_counties/`             | **Public domain**                                                                                         | ✅ (no restrictions)                             | "U.S. Census Bureau" (courtesy — not legally required)                      |
| **Yale Bright Star Catalogue** (9,096 stars, sky background)                | `sky/`                            | **Public domain**                                                                                         | ✅ (no restrictions)                             | "Yale Bright Star Catalogue (Hoffleit & Warren, via CDS)" (courtesy credit) |
| **ESO Milky Way panorama** (eso0932a, blurred cube map, sky background)     | `sky/`                            | **CC BY 4.0**                                                                                             | ✅ (attribution; changes stated)                 | "ESO/S. Brunier"                                                            |

### ⚠️ TeleGeography is bundled but NonCommercial

The submarine-cable GeoJSON is **CC BY-NC-SA 3.0** (Attribution-**NonCommercial**-**ShareAlike**). It is bundled so the cables layer works out of the box, but it is **not covered by this project's MIT license**. CC BY-NC-SA permits redistribution with attribution and share-alike — which is exactly how it ships here — but the **NonCommercial** clause means:

> If you use God's Eye View commercially, delete `src/data/local_data/telegeography_submarine_cables/` (or obtain a commercial license from TeleGeography). It is one self-contained folder; the rest of the app runs without it.

The richer structured dataset is licensed separately/commercially by TeleGeography.

### Bundled OpenStreetMap data

Bundled OSM-derived data is distributed under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/), separately from the MIT code: [datacenters](src/data/local_data/datacenters/), [dams](src/data/local_data/dams/) (via Open Infrastructure Map), and [OSM test fixtures](src/data/fixtures/). Keep © OpenStreetMap contributors and offer modified databases under ODbL.

### NASA FIRMS acknowledgement

> We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource Management System (FIRMS) (https://earthdata.nasa.gov/firms), part of NASA's Earth Observing System Data and Information System (EOSDIS).

FIRMS active fires are **fetched live at runtime** (CC0 / U.S. public domain data): the
`/api/firms` server-side proxy merges the three VIIRS NRT sources (NOAA-20, NOAA-21,
Suomi-NPP) and MODIS NRT (Terra + Aqua), clamped to the trailing 24 h, cached 30 min to respect the shared MAP_KEY
transaction quota. Requires a free `FIRMS_MAP_KEY`
(https://firms.modaps.eosdis.nasa.gov/api/map_key/); the layer is empty without it.
The former bundled 2026-05-25 snapshot was removed 2026-07-16.

### Natural Earth physical regions (`natural_earth/`)

Curated from the **Natural Earth 10m physical vectors** (https://www.naturalearthdata.com/ —
fetched from the canonical `nvkelso/natural-earth-vector` GitHub repo, commit
`ca96624a56bd078437bca8184e78163e5039ad19`, 2026-07-28): `ne_10m_geography_regions_polys`
(mountain ranges, deserts, plateaus, peninsulas, islands, …) → `regions.json` and
`ne_10m_geography_marine_polys` (seas, gulfs, straits, bays) → `marine.json`. They back the
annotation resolver's named-natural-region lookup (`src/data/naturalEarthRegions.js`),
so "outline the Alps" draws the real range polygon offline.

Curation (provenance in each file's `meta` header): named features only, outer rings only,
Douglas-Peucker simplified at ~0.01° with coordinates rounded to 3 decimals, sub-20 km²
MultiPolygon crumbs and zero-area sliver artifacts dropped (7.3 MB source → 2.5 MB pack).

Natural Earth is **public domain** (no permission needed, no attribution legally required —
https://www.naturalearthdata.com/about/terms-of-use/). We credit anyway: "Made with Natural
Earth". Registration in the in-app `dataCredits.js` attribution list ships with the resolver
wiring (see below).

### Sky background (`sky/`)

Sources, licences, the changes CC BY asks to state, hashes and build commands
are in [`sky/README.md`](src/data/local_data/sky/README.md).

### DataSF Analysis Neighborhoods (`neighborhoods/`)

`neighborhoods/san-francisco.json` bundles the City & County of San Francisco's official
**"Analysis Neighborhoods"** dataset (41 neighborhood polygons; DataSF dataset `j2bu-swwd`,
catalog map view
[`p5b7-5n3h`](https://data.sfgov.org/Geographic-Locations-and-Boundaries/Analysis-Neighborhoods-Map/p5b7-5n3h)).
It backs the annotation resolver's offline neighborhood-boundary lookup
(`src/data/neighborhoodPolygons.js`), so "outline Chinatown" draws the city's real
boundary polygon with no network dependency.

The dataset is licensed **PDDL 1.0** (Open Data Commons Public Domain Dedication and
License — public domain; the DataSF metadata declares `licenseId: "PDDL"`). No attribution
is legally required; we note the source here and in the folder's `SOURCE.md`, which records
the retrieval date (2026-07-30), exact download URL, license evidence, and the
deterministic transform (`scripts/build-sf-neighborhoods.mjs`: `nhood` → `name`, ~2 m
Douglas-Peucker simplification, 6-decimal rounding).

---

## Weather sources

### ECMWF IFS wind

Wind also offers ECMWF IFS 10 m forecasts from the keyless [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data) service. The proxy reads its JSON Lines inventory and byte-range fetches 10u/10v GRIB messages, optionally adding 2t (2 m temperature) or msl (mean sea-level pressure) from the same run and forecast time. It resamples these fields to the approximately 1° display grid. Data is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The [ECMWF Terms of Use](https://apps.ecmwf.int/datasets/licences/general/) also apply. In-app attribution identifies this service as based on ECMWF data and products, links the CC BY 4.0 licence, identifies resampling and animation as modifications, and retains the required ECMWF liability disclaimer. Both model issue time and the selected forecast valid time appear in the WEATHER panel. These are model forecasts, not observations.

### NOAA GFS wind

The optional **Wind** layer animates the global 10 m wind field from NOAA's
Global Forecast System (GFS). The `/api/wind` server-side proxy selects the
latest available 0.25° cycle, reads its `.idx` inventory, byte-range fetches only
the `UGRD`/`VGRD` 10 m GRIB2 messages, optionally adding `TMP` at 2 m or
`PRMSL` at mean sea level from the same run and forecast time. It decodes the
selected messages with ecCodes (WASM), resamples to a compact grid (1° by
default), and serves a manifest plus Float32 U/V and optional scalar values. It is keyless, cached
per cycle for an hour, and is a **forecast, not an observation**: the particles
show model flow, not measured wind. The renderer bakes bounded curves through
the sampled field and animates their phase on the GPU, with a canvas fallback.
Any display lift is a visual aid and does not change the forecast's 10 m level.
NOAA GFS data is U.S. public domain; the credit above is a courtesy and does not
imply endorsement.

For both models, optional temperature is normalized from K to °C and pressure
from Pa to hPa before delivery. A missing, malformed or timed-out companion field
does not discard valid wind: the manifest marks that field unavailable, and the
UI retains wind without inventing scalar values. The proxy caches by model and
requested field, with bounded current/previous grids and shared in-flight loads.
Wind speed shading is computed locally from U/V and needs no companion download.
The legend and map-center reading explain units and forecast validity; the
animation is a visual flow through one forecast, not advancing forecast time.
Optional globe relief uses existing terrain vertex normals for view lighting;
without those normals it shades global globe curvature only, not local terrain
relief. Neither mode represents measured sunlight or a new elevation source.
This Wind prototype adds no cloud-volume or radar data. Mapped.earth's public
bundles were studied for rendering ideas, but
no code or assets were reused and no application licence granting reuse was
found. Its presentation is not a weather-data source for this implementation.

### Observed weather: NOAA nowCOAST

The Weather section provides keyless, observed **MRMS radar reflectivity** for the
contiguous United States and **infrared satellite imagery**. Fixed upstream WMS
services: `https://nowcoast.noaa.gov/geoserver/observations/weather_radar/ows` and
`https://nowcoast.noaa.gov/geoserver/observations/satellite/ows`.

- `conus_base_reflectivity_mosaic`: approximately 1 km, usually 4-minute updates.
  dBZ measures radar reflectivity, not rainfall rate, probability or future rain.
  Coverage gaps do not mean no precipitation. The numeric legend follows NOAA's
  `weather_radar_base_reflectivity` style.
- `goes_longwave_imagery`: GOES-19/18 Band 14, approximately 2 km, 5-minute updates,
  regional North America. **Clouds only** softly dims pixels with a linear
  brightness ramp from 0.40 to 0.70; **Full image** retains source alpha. This
  is a display filter, not a cloud mask or measured cloud volume.
- `global_longwave_imagery_mosaic`: approximately 3 km, hourly, nominal 60°S–60°N
  coverage and typically 2–3-hour latency. It is slower global context.

The UI displays the exact advertised observation time separately from acquisition;
latest means the newest available observation, not zero-delay real time. Up to 13
recent advertised frames can be replayed as history. No nowcast is synthesized.
Tiles use WMS 1.1.1 EPSG:4326 longitude/latitude bounds; Cesium's geographic 2×1
root grid is capped at level 6 for radar and regional GOES. Global infrared uses
one fixed 2048×1024 geographic image on both hosts: the source's request-dependent
contrast otherwise creates brightness seams between tiles. The browser decodes
and filters it once, then crops 256 px tiles bounded to the manifest extent at
maximum level 3. This broad context view has a coarser display resolution than
its 3 km source. No browser reprojection is used. Browser imagery owns a displayed
frame and a staging frame, retaining the outgoing layer for one render after
admission.

On Google 3D Tiles each observed product is instead a raised shell showing one
whole-extent image per frame (up to 4096×2048; global infrared 2048×1024). Every
product except global infrared also draws a 4096×2048 detail window around the
view, requested with a 2:1 `bbox` inside the product bounds, rounded to 0.25°.
The proxy has an 8-request concurrency budget and a 12-second deadline; tiles
(256, 512 or 1024 px) are capped at 1 MiB or 4 bytes per pixel plus 64 KiB,
whichever is larger, and whole-extent and detail images at 16 MiB. Its shared
cache holds up to 128 images and 16 MiB, each exact-time image for at most 24
hours.
Metadata refreshes every two minutes with explicitly stale last-good fallback.
No key, new dependency, image reprojection job, or full-disk image download is needed.

Credit: NOAA nowCOAST, NWS/OAR MRMS, NESDIS GOES and global satellite partners.
[NOAA disclaimer](https://oceanservice.noaa.gov/disclaimer.html).
Community context: [#85](https://github.com/bilawalsidhu/gods-eye-view/issues/85),
[#588 radar](https://github.com/bilawalsidhu/gods-eye-view/pull/588), and
[#457 clouds](https://github.com/bilawalsidhu/gods-eye-view/pull/457).
This implementation is original; those contributions have not been merged here.


### Weather: NHC/CPHC cyclone advisories

- **Sources:** [NHC current tropical cyclone status](https://www.nhc.noaa.gov/CurrentStorms.json) and
  [NOAA tropical weather summary GIS](https://mapservices.weather.noaa.gov/tropical/rest/services/tropical/NHC_tropical_weather_summary/MapServer).
- **Rights/credit:** NOAA/NWS National Hurricane Center / Central Pacific Hurricane Center;
  [NWS public-data terms](https://www.weather.gov/disclaimer). Fetch official products at runtime;
  no bundled advisory archive and no NOAA endorsement implied.
- **Coverage/meaning:** Atlantic and eastern/central North Pacific, not global cyclone coverage.
  Status position time and advisory issue time remain separate. Forecast track, points and cone
  require matching advisory numbers across all GIS parts. Cone means uncertainty in the
  forecast center track, not storm size or a complete hazard boundary.
- **Delivery:** keyless same-origin `/api/cyclones`, five-minute singleflight cache,
  fixed upstream endpoints, bounded bodies/geometry/deadline, explicit unavailable/stale states.
  Direct status fetching is unsuitable in browsers because NHC does not advertise CORS.

### Weather: observed lightning density

- **Source:** [NOAA nowCOAST lightning detection WMS](https://nowcoast.noaa.gov/geoserver/observations/lightning_detection/ows),
  fixed `ldn_lightning_strike_density` layer and `lightning_density` style.
- **Rights/credit:** NOAA/NWS nowCOAST; derived from Vaisala NLDN/GLD360.
  [Official product description and public distribution terms](https://ocean.weather.gov/lightning/lightning_pdd.php)
  permit distribution of this NOAA Level-5 derived product, not raw Vaisala detections.
- **Meaning:** 15-minute accumulated density on an approximately 8 km grid;
  source color scale is strikes per km² per minute ×10³. Not individual GLM optical flashes,
  a live ground-strike counter, an all-clear indication, or global coverage.
- **Coverage:** 110°E across the Pacific/Americas to 0°, 25°S–80°N. Display exact advertised
  observations; ten-minute metadata refresh, source-matched colors, bounded shared imagery cache.

### Community weather prior art

The weather design builds on Gustavo Beneduzi's retained GFS/ECMWF contribution
commits ([#459](https://github.com/bilawalsidhu/gods-eye-view/pull/459),
[#464](https://github.com/bilawalsidhu/gods-eye-view/pull/464)). Related community
proposals informed the observed-weather experience: Sandiv D's on-demand radar
and imagery controls ([#588](https://github.com/bilawalsidhu/gods-eye-view/pull/588));
Gustavo Beneduzi's GOES and GLM source work
([#457](https://github.com/bilawalsidhu/gods-eye-view/pull/457),
[#458](https://github.com/bilawalsidhu/gods-eye-view/pull/458)); and HadiMuhammed's
NOAA hazard provenance and freshness work
([#414](https://github.com/bilawalsidhu/gods-eye-view/pull/414)).
The fixed nowCOAST imagery and NHC advisory implementations are original maintainer
work; this acknowledgement does not represent merging those four PRs or equate
NOAA density imagery with the raw GLM product.

---

## In-app attribution

The required Google Maps / Cesium credit renders on the on-globe credit line (`#cesium-credits`, bottom-left) and must stay visible — including in clean-view and recording modes (the whole line, logo + "Google Maps" + the "Data attribution" link, stays on screen; only the GEV panels/HUD fade). The layer-specific credits (adsb.lol, adsbdb, TeleGeography, OSM datacenters/dams/roads, NASA FIRMS, CelesTrak, USGS, GBFS, OpenSky, AISStream) are registered into the expandable **"Data attribution"** popover on that credit line via `viewer.creditDisplay.addStaticCredit(new Cesium.Credit(html, /* showOnScreen */ false))` — see `src/data/dataCredits.js`. When you add a new data source, add its license and attribution to this file **and** append an entry to `DATA_CREDITS` in `src/data/dataCredits.js` so it surfaces in the app.
