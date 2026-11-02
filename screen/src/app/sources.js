import flights from '../data/flights.js';
import vessels from '../data/aisLiveVessels.js';
import { configureBikeshareSource } from '../data/bikeshare.js';
import { configureSatelliteSource } from '../data/satellites.js';
import { configureLaunchSource } from '../data/rocketLaunches.js';
import { configureFirmsSource } from '../data/firmsHeatmap.js';
import { configureWindSource } from '../data/wind.js';
const configure = {
  bikeshare: configureBikeshareSource,
  satellites: configureSatelliteSource,
  launches: configureLaunchSource,
  firms: configureFirmsSource,
  wind: configureWindSource,
};
/** Configure sources before any registration or state restoration starts. */
export function configureApplicationSources({ layers = {}, live = {}, defer }) {
  for (const [name, source] of Object.entries(layers)) {
    if (!configure[name]) throw new TypeError(`Unknown layer source: ${name}`);
    defer(configure[name](source));
  }
  if (live.flights) flights.setSource(live.flights);
  if (live.vessels) vessels.setSource(live.vessels);
}
export const liveLayers = Object.freeze({ flights, vessels });
