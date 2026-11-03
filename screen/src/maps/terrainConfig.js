/**
 * Opt-in configuration for the self-hosted terrain (no imports, so any
 * package may read it). `main.js` sets it once from the build-time values
 * `TERRAIN_TILE_URL` and `TERRAIN_ATTRIBUTION_URL`; unset means flat terrain
 * on the keyless stacks, exactly as before (FORK.md, "Basemap").
 */

/** A usable tile URL names all three placeholders; http(s) or root-relative. */
export function isValidTileUrlTemplate(value) {
  const text = String(value ?? '').trim();
  if (!text) return false;
  if (!/\{z\}/.test(text) || !/\{x\}/.test(text) || !/\{y\}/.test(text))
    return false;
  return /^https?:\/\//i.test(text) || text.startsWith('/');
}

/** A credit link must be http(s); anything else is ignored. */
export function isValidHttpUrl(value) {
  return /^https?:\/\/\S+$/i.test(String(value ?? '').trim());
}

let config = { tileUrl: '', attributionUrl: '' };

/**
 * @param {{tileUrl?: string, attributionUrl?: string}} [values]
 * @returns {{tileUrl: string, attributionUrl: string}} what was accepted
 */
export function configureTerrain({ tileUrl = '', attributionUrl = '' } = {}) {
  const url = String(tileUrl ?? '').trim();
  if (url && !isValidTileUrlTemplate(url))
    console.warn(
      '[MapStack] TERRAIN_TILE_URL ignored: it needs {z}, {x} and {y} and must start with http(s):// or /',
    );
  const link = String(attributionUrl ?? '').trim();
  config = {
    tileUrl: isValidTileUrlTemplate(url) ? url : '',
    attributionUrl: isValidHttpUrl(link) ? link : '',
  };
  return getTerrainConfig();
}

export function getTerrainConfig() {
  return { ...config };
}

/** True when the owner has switched the self-hosted terrain on. */
export function isSelfHostedTerrainOn() {
  return config.tileUrl !== '';
}
