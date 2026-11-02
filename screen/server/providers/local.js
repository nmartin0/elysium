import { openSkyProxy } from './aircraft/opensky.js';
import { celestrakProxy, rocketLaunchesProxy } from './space.js';
import { firmsProxy } from './firms.js';
import { terrainHeightsProxy } from './terrain.js';
import { adsbdbProxy } from './aircraft/enrichment.js';
import { overpassProxy } from './overpass.js';
import { geocodeProxy } from './regional/place.js';
import { gbfsProxy } from './gbfs.js';
import { transitProxy } from './transit.js';
import { aisLiveProxy } from './vessels/ais-live.js';
import { trackBackfillProxies } from './aircraft/tracks.js';
import { googlePlacesContextProxy } from './places.js';
import { weatherProxy } from './weather.js';
import { firePerimetersProxy } from './firePerimeters.js';
import { gnssIntegrityProxy } from './gnssIntegrity.js';
import { ghostMapsProxy } from './ghostMaps.js';
import { cycloneProxy } from './cyclones.js';
import { windProxy } from './wind.js';

/** Construct the local provider plugins in their established order. */
function localProviderPlugins() {
  return [
    openSkyProxy(),
    celestrakProxy(),
    firmsProxy(),
    rocketLaunchesProxy(),
    terrainHeightsProxy(),
    adsbdbProxy(),
    overpassProxy(),
    geocodeProxy(),
    gbfsProxy(),
    transitProxy(),
    aisLiveProxy(),
    trackBackfillProxies(),
    googlePlacesContextProxy(),
    windProxy(),
    weatherProxy(),
    cycloneProxy(),
    firePerimetersProxy(),
    gnssIntegrityProxy(),
    ghostMapsProxy(),
  ];
}

export { localProviderPlugins };

export { LL2_CACHE_TTL_MS, launchLibraryRequestHeaders } from './space.js';
export { googlePlacesContextProxy } from './places.js';
export { googleServerApiKey } from './places.js';
export { keylessGooglePlacesResponse } from './places.js';
export { keylessGoogleGeocodeResponse } from './places.js';
export { validateGeocodeAddress } from './places.js';
export { geocodeBounds } from './places.js';
export { adsbLolFallbackAnchor } from './aircraft/opensky.js';
export { readResponseTextCapped } from './common/http.js';
export { readResponseJsonCapped } from './common/http.js';
export { coalesceProxyRequest } from './common/http.js';
export { requiredFiniteQueryNumber } from './common/query.js';
export { isOverpassBoundaryQuery } from './overpass/query.js';
export { simplifyOverpassPayloadBody } from './overpass/geometry.js';
export { readOverpassDisk } from './overpass/cache.js';
export { resolveOverpassPreflight } from './overpass/cache.js';
export { overpassPayloadIsData } from './overpass/transport.js';
export { fetchOverpassPayload } from './overpass/transport.js';
export { validRegionalPoint } from './regional/query.js';
