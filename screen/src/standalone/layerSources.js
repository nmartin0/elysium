import { createDirectionsSource } from '../layers/directions/source.js';
import { createRecentImagerySource } from '../layers/recentImagery/source.js';
import {
  createFlightSource,
  createVesselSource,
} from '../sources/live/standalone.js';
import { createTransitSource } from '../layers/transit/source.js';
import { createBikeshareSource } from '../layers/bikeshare/source.js';
import { createSatelliteSource } from '../layers/satellites/source.js';
import { createLaunchSource } from '../layers/launches/source.js';
import { createWeatherSource } from '../layers/weather/source.js';
import { createCycloneSource } from '../layers/cyclones/source.js';
import { createWindSource } from '../layers/wind/source.js';
import { createFirmsSource } from '../layers/firms/source.js';
import { createGhostMapsSource } from '../layers/ghostMaps/source.js';
import { createReferenceSources } from '../sources/reference.js';
export { createReferenceSources as createStandaloneReferenceSources } from '../sources/reference.js';

/** Select standalone providers without starting their acquisition. */
export function createStandaloneLayerSources(overrides = {}) {
  if (!overrides || typeof overrides !== 'object' || Array.isArray(overrides))
    throw new TypeError('Source overrides must be an object');
  const defaults = {
    ...createReferenceSources(),
    directions: createDirectionsSource(),
    'recent-imagery': createRecentImagerySource(),
    flights: createFlightSource(),
    vessels: createVesselSource({
      apiUrl: import.meta.env?.VITE_AIS_LIVE_API_URL || '/api/vessels',
      // Resolved against the document's address, which a panel host may
      // serve from its own scheme.
      origin: () => globalThis.document?.baseURI ?? 'http://localhost',
    }),
    transit: createTransitSource(),
    bikeshare: createBikeshareSource(),
    satellites: createSatelliteSource(),
    launches: createLaunchSource(),
    firms: createFirmsSource(),
    's2-ghostmaps': createGhostMapsSource(),
    wind: createWindSource(),
    weather: createWeatherSource(),
    cyclones: createCycloneSource(),
  };
  for (const name of Object.keys(overrides)) {
    if (!Object.hasOwn(defaults, name))
      throw new TypeError(`Unknown source: ${name}`);
  }
  return { ...defaults, ...overrides };
}
