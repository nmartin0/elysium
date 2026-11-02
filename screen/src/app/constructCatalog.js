import { resolveCatalogSources } from './sourceComposition.js';
import { createWeatherClock } from '../layers/weather/clock.js';
import { createWeatherLayer } from '../layers/weather/index.js';
import { createCyclonesLayer } from '../layers/cyclones/index.js';
import { createWindLayer } from '../layers/wind/index.js';
import { createLayerCatalog } from './catalog.js';
import { createLayerStubs } from './layerStubs.js';
import { LAYER_STATE_REGISTRY } from '../data/layerState.js';
import { createMilitaryRegistry } from '../layers/aircraft/classification.js';
import { createApplicationFlights } from './layers/flights.js';
import { createApplicationVessels } from './layers/aisLiveVessels.js';
import { createApplicationBikeshare } from './layers/bikeshare.js';
import { createApplicationDirections } from './layers/directions.js';
import { createApplicationRecentImagery } from './layers/recentImagery.js';
import { createApplicationTransit } from './layers/transit.js';
import { createApplicationSatellites } from './layers/satellites.js';
import { createApplicationLaunches } from './layers/rocketLaunches.js';
import { createApplicationFirms } from './layers/firms.js';
import { createApplicationEarthquakes } from './layers/earthquakes.js';
import { createApplicationAirQuality } from './layers/airQuality.js';
import { createApplicationFirePerimeters } from './layers/perimeters.js';
import { createApplicationGnssIntegrity } from './layers/gnss.js';
import { createApplicationGhostMaps } from './layers/ghostMaps.js';
import { createApplicationCables } from './layers/submarineCables.js';
import { createInfrastructureLayers } from '../data/infrastructure.js';
import { localGeoJsonServices } from './localGeojsonServices.js';

/**
 * Layers that never enter share links or stored layer state. The fork has none
 * (the hardware receiver layer, the only one, was removed).
 */
export const LOCAL_ONLY_LAYER_METADATA = Object.freeze([]);

/** Serialization metadata for every layer the application catalog constructs. */
export const APPLICATION_LAYER_METADATA = Object.freeze([
  ...LAYER_STATE_REGISTRY,
  ...LOCAL_ONLY_LAYER_METADATA,
]);

/** Construct the current catalog without choosing any source provider.
 * Scene engines remain page-owned; layers and classification have this app's lifetime.
 * The manager owns layer destruction, while abort releases classification even if startup fails.
 */
export function createApplicationCatalog({
  surface,
  sources,
  signal,
  metadata = APPLICATION_LAYER_METADATA,
  vesselOptions,
  resolveAsset,
}) {
  if (!signal?.addEventListener)
    throw new TypeError('An application lifetime signal is required');
  signal.throwIfAborted();
  if (!surface?.groundFloor || !surface?.terrain)
    throw new TypeError('Application surface services are required');

  const sourceComposition = resolveCatalogSources(sources);
  sources = sourceComposition.sources;
  const militaryRegistry = createMilitaryRegistry();
  const weatherClock = createWeatherClock();
  const dispose = () => {
    signal.removeEventListener('abort', dispose);
    militaryRegistry.dispose();
    weatherClock.destroy();
  };
  signal.addEventListener('abort', dispose, { once: true });
  try {
    const flights = createApplicationFlights({
      surface,
      source: sources.flights,
      militaryRegistry,
      resolveAsset,
    });
    const vessels = createApplicationVessels({
      source: sources.vessels,
      options: vesselOptions,
    });
    const satellites = createApplicationSatellites({
      source: sources.satellites,
    });
    const catalog = createLayerCatalog(
      [
        flights,
        createApplicationEarthquakes({ source: sources.earthquakes }),
        createApplicationAirQuality({ source: sources['air-quality'] }),
        createApplicationFirePerimeters({
          source: sources['fire-perimeters'],
        }),
        createApplicationGnssIntegrity({
          source: sources['gnss-integrity'],
          windowMs: sources['gnss-integrity'].windowMs,
        }),
        createApplicationGhostMaps({ source: sources['s2-ghostmaps'] }),
        satellites,
        createApplicationLaunches({ source: sources.launches, satellites }),
        createApplicationTransit({ surface, source: sources.transit }),
        createApplicationBikeshare({ source: sources.bikeshare }),
        createApplicationDirections({ source: sources.directions }),
        createApplicationRecentImagery({ source: sources['recent-imagery'] }),
        vessels,
        createWindLayer({ feed: sources.wind, clock: weatherClock }),
        createWeatherLayer({
          feed: sources.weather,
          id: 'weather-radar',
          clock: weatherClock,
        }),
        createWeatherLayer({
          feed: sources.weather,
          id: 'weather-satellite',
          clock: weatherClock,
        }),
        createWeatherLayer({
          feed: sources.weather,
          id: 'weather-lightning',
          clock: weatherClock,
        }),
        createCyclonesLayer({ feed: sources.cyclones }),
        ...createInfrastructureLayers(localGeoJsonServices),
        createApplicationCables({ source: sources.cables }),
        createApplicationFirms({
          surface,
          id: 'local-firms',
          name: 'FIRMS Active Fires',
          icon: '▲',
          source: 'NASA FIRMS · LIVE',
          feed: sources.firms,
        }),
      ],
      metadata,
      createLayerStubs(),
    );
    return Object.freeze({
      ...catalog,
      getSourceAvailability: sourceComposition.createAvailabilityLookup(
        catalog.layers,
      ),
      militaryRegistry,
      surface,
      weatherClock,
    });
  } catch (error) {
    dispose();
    throw error;
  }
}
