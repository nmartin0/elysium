import * as Cesium from 'cesium';
import { createTerrainRetryPolicy } from './terrainRetry.js';
import { getTerrainConfig } from './terrainConfig.js';
import { createTerrariumTerrainProvider } from './terrariumTerrain.js';

/** Re:Earth / Mapterhorn ellipsoidal quantized mesh, CC BY 4.0. */
export const KEYLESS_TERRAIN_URL =
  'https://terrain.reearth.land/cesium-mesh/ellipsoid';

/**
 * STUBBED (owner, 2 Nov 2026): the hosted Re:Earth endpoint is a third party's
 * service whose terms nobody here could read, and the owner's plan is terrain
 * self-hosted from Mapterhorn. While `stubbed` is true the keyless stacks get
 * flat ellipsoid terrain and make no terrain request. Set it to false to turn
 * the Re:Earth terrain back on (the tests lift it themselves).
 */
export const KEYLESS_TERRAIN_STUB = { stubbed: true };

/** These factories are lazy: a hidden globe must not trigger terrain loading. */
export async function createWorldTerrain(accessToken, { signal } = {}) {
  accessToken = String(accessToken || '').trim();
  if (!accessToken)
    throw new Error('World terrain requires an explicit ion token');
  signal?.throwIfAborted();
  const resource = await Cesium.IonResource.fromAssetId(1, { accessToken });
  signal?.throwIfAborted();
  return {
    provider: await Cesium.CesiumTerrainProvider.fromUrl(resource, {
      requestVertexNormals: true,
      requestWaterMask: false,
      ellipsoid: Cesium.Ellipsoid.WGS84,
    }),
  };
}

function logThrottle({ statusCode, delayMs, inWindow }) {
  // One line per cooldown window, not per tile: a burst throttles dozens.
  if (inWindow !== 1) return;
  console.warn(
    `[MapStack] Re:Earth terrain answered ${statusCode}; retrying throttled tiles after ${Math.round(delayMs)} ms`,
  );
}

/**
 * The Re:Earth resource with the tile retry policy attached. Cesium copies
 * `retryCallback`/`retryAttempts` onto every derived resource, so layer.json
 * and each `{z}/{x}/{y}.terrain` fetch inherit it (see `terrainRetry.js`).
 * @param {ReturnType<typeof createTerrainRetryPolicy>} [policy]
 * @returns {Cesium.Resource}
 */
export function createKeylessTerrainResource(
  policy = createTerrainRetryPolicy({ onThrottle: logThrottle }),
) {
  return new Cesium.Resource({
    url: KEYLESS_TERRAIN_URL,
    retryCallback: policy.retryCallback,
    retryAttempts: policy.retryAttempts,
  });
}

/**
 * @param {object} [request] unused (the factory contract passes `{signal}`)
 * @param {object} [options] test seam: `config` replaces the terrain config,
 *   `fetchPixels` replaces the tile loader
 */
export async function createKeylessTerrain(
  request,
  { config = getTerrainConfig(), fetchPixels } = {},
) {
  // Opt-in self-hosted Mapterhorn terrain (TERRAIN_TILE_URL). Unset: flat.
  if (config.tileUrl)
    return {
      provider: createTerrariumTerrainProvider({
        urlTemplate: config.tileUrl,
        ...(fetchPixels ? { fetchPixels } : {}),
      }),
    };
  if (KEYLESS_TERRAIN_STUB.stubbed)
    return { provider: new Cesium.EllipsoidTerrainProvider() };
  try {
    return {
      provider: await Cesium.CesiumTerrainProvider.fromUrl(
        createKeylessTerrainResource(),
      ),
    };
  } catch (error) {
    console.warn(
      '[MapStack] Re:Earth terrain unavailable, falling back to flat ellipsoid terrain:',
      error,
    );
    return { provider: new Cesium.EllipsoidTerrainProvider(), fallback: true };
  }
}
