/**
 * Which environment variable each provider key lives in.
 *
 * Fork: this is all that is left of the "POWER UP" key setup. The panel, its
 * dev-server endpoints and the .env writer were removed; the map code and the
 * layer panel still name the variable a missing key would come from
 * (keySetupRequirementEnvVars), and ui/keyGuidance.js reads the titles.
 */

const key = (id, title, envVars, extra = {}) =>
  Object.freeze({
    id,
    title,
    envVars: Object.freeze(envVars),
    ...extra,
  });

/** Provider credentials the remaining layers and map stacks can name. */
export const KEY_SETUP_KEYS = Object.freeze([
  key('google-maps', 'GOOGLE MAPS', ['GOOGLE_MAPS_API_KEY']), // i18n-ignore: provider product name
  key(
    'google-maps-server',
    'GOOGLE MAPS — SERVER',
    ['GOOGLE_MAPS_SERVER_API_KEY'],
    { hidden: true },
  ), // i18n-ignore: provider product name
  key('aisstream', 'AISSTREAM', ['AISSTREAM_API_KEY']), // i18n-ignore: provider product name
  key('firms', 'NASA FIRMS', ['FIRMS_MAP_KEY']), // i18n-ignore: provider product name
  key('cesium-ion', 'CESIUM ION', ['CESIUM_ION_TOKEN']), // i18n-ignore: provider product name
  key('opensky', 'OPENSKY', ['OPENSKY_CLIENT_ID', 'OPENSKY_CLIENT_SECRET']), // i18n-ignore: provider product name
  key('launch-library', 'LAUNCH LIBRARY', ['LL2_API_TOKEN']), // i18n-ignore: provider product name
]);

/**
 * Env-var names a registry entry needs, joined with ' + ', for callers that
 * build the guidance sentence in the UI language (src/ui/keyGuidance.js).
 * @param {string} id Registry entry id.
 * @returns {string|null} null for an unknown or hidden entry.
 */
export function keySetupRequirementEnvVars(id) {
  const entry = KEY_SETUP_KEYS.find((candidate) => candidate.id === id);
  if (!entry || entry.hidden) return null;
  return entry.envVars.join(' + ');
}
