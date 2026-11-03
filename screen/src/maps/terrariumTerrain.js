import * as Cesium from 'cesium';
import { createTerrainRetryPolicy } from './terrainRetry.js';

/**
 * Cesium terrain provider for self-hosted Terrarium elevation tiles.
 *
 * ONLY TESTED ON SYNTHETIC TILES (terrariumTerrain.test.mjs). It has not been
 * run against real Mapterhorn data or in a browser.
 *
 * Verified in docs/feeds.md ("Basemap build plan", read from the
 * mapterhorn/mapterhorn repository): Terrarium-encoded RGB, WebP, 512 px
 * tiles, Web Mercator, `planet.pmtiles` holding zoom 0 to 12.
 * Not verified: the height datum (the Re:Earth build was labelled
 * "ellipsoid", which suggests the source heights are above the geoid, so
 * terrain may sit tens of metres off the WGS84 ellipsoid; `heightOffset`
 * below is the hook to correct that), whether every tile of z0-12 exists
 * (a missing one degrades to flat), and bathymetry (assumed absent).
 */

/** planet.pmtiles covers zoom 0 to 12 (Mapterhorn facts in docs/feeds.md). */
export const TERRARIUM_MAX_LEVEL = 12;
/** Tile edge in pixels (Mapterhorn facts in docs/feeds.md). */
export const TERRARIUM_TILE_SIZE = 512;
/**
 * Heights per heightmap edge. A choice, not a verified optimum: 129 samples
 * (a 4 px stride) keeps each mesh cheap. Cesium wants 2^n + 1.
 */
export const TERRARIUM_HEIGHTMAP_SAMPLES = 129;

/** Terrarium: metres = R * 256 + G + B / 256 - 32768. */
export function decodeTerrariumHeight(r, g, b) {
  return r * 256 + g + b / 256 - 32768;
}

/**
 * @param {Uint8Array|Uint8ClampedArray} rgba size * size * 4 bytes
 * @param {number} size tile edge in pixels
 * @returns {Float32Array} size * size heights in metres, row 0 = north
 */
export function decodeTerrariumPixels(rgba, size = TERRARIUM_TILE_SIZE) {
  if (!rgba || rgba.length < size * size * 4)
    throw new Error('Terrarium tile has too few pixels');
  const heights = new Float32Array(size * size);
  for (let i = 0; i < heights.length; i += 1) {
    const o = i * 4;
    heights[i] = decodeTerrariumHeight(rgba[o], rgba[o + 1], rgba[o + 2]);
  }
  return heights;
}

/**
 * Resamples pixel-centred heights onto a corner-aligned grid of
 * `samples` x `samples` points (sample 0 on the tile's west/north edge,
 * sample samples-1 on its east/south edge), bilinear, clamped at the edges.
 * Neighbouring tiles then agree to within one source pixel on the shared edge
 * (each clamps to its own edge pixel), which can leave a hairline seam.
 * @returns {Float32Array} samples * samples heights, row 0 = north
 */
export function heightsToHeightmap(
  heights,
  size = TERRARIUM_TILE_SIZE,
  samples = TERRARIUM_HEIGHTMAP_SAMPLES,
) {
  const out = new Float32Array(samples * samples);
  const last = size - 1;
  const at = (i) => {
    const c = (i * size) / (samples - 1) - 0.5; // pixel-centre coordinate
    const clamped = Math.min(last, Math.max(0, c));
    const i0 = Math.min(Math.max(last - 1, 0), Math.floor(clamped));
    return [i0, Math.min(last, i0 + 1), clamped - i0];
  };
  const axis = Array.from({ length: samples }, (_, i) => at(i));
  for (let row = 0; row < samples; row += 1) {
    const [r0, r1, fy] = axis[row];
    for (let col = 0; col < samples; col += 1) {
      const [c0, c1, fx] = axis[col];
      const top =
        heights[r0 * size + c0] * (1 - fx) + heights[r0 * size + c1] * fx;
      const bottom =
        heights[r1 * size + c0] * (1 - fx) + heights[r1 * size + c1] * fx;
      out[row * samples + col] = top * (1 - fy) + bottom * fy;
    }
  }
  return out;
}

/** Fills {z}, {x} and {y} in the owner's URL template. */
export function expandTileUrl(template, z, x, y) {
  return String(template)
    .replaceAll('{z}', String(z))
    .replaceAll('{x}', String(x))
    .replaceAll('{y}', String(y));
}

/** A tile exists only inside the pyramid: z in [0, maxLevel], x and y in [0, 2^z). */
export function isTerrariumTileAvailable(
  x,
  y,
  level,
  maxLevel = TERRARIUM_MAX_LEVEL,
) {
  if (![x, y, level].every(Number.isInteger)) return false;
  if (level < 0 || level > maxLevel) return false;
  const n = 2 ** level;
  return x >= 0 && y >= 0 && x < n && y < n;
}

/**
 * Default pixel fetch: Cesium Resource (throttled by the request scheduler,
 * retry policy attached) -> blob -> ImageBitmap -> canvas -> RGBA. Resolves
 * undefined when the request scheduler throttled the request (try later).
 * Needs a browser (createImageBitmap, canvas); not exercised in node tests.
 */
export function createFetchPixels({ retryPolicy } = {}) {
  return async function fetchPixels(url) {
    const resource = new Cesium.Resource({
      url,
      request: new Cesium.Request({
        throttle: true,
        throttleByServer: true,
        type: Cesium.RequestType.TERRAIN,
      }),
      retryCallback: retryPolicy?.retryCallback,
      retryAttempts: retryPolicy?.retryAttempts,
    });
    const promise = resource.fetchBlob();
    if (!promise) return undefined;
    const blob = await promise;
    const bitmap = await createImageBitmap(blob, {
      premultiplyAlpha: 'none',
      colorSpaceConversion: 'none',
    });
    try {
      const canvas =
        typeof OffscreenCanvas === 'function'
          ? new OffscreenCanvas(bitmap.width, bitmap.height)
          : Object.assign(document.createElement('canvas'), {
              width: bitmap.width,
              height: bitmap.height,
            });
      const context = canvas.getContext('2d', { willReadFrequently: true });
      context.drawImage(bitmap, 0, 0);
      const { data } = context.getImageData(0, 0, bitmap.width, bitmap.height);
      return { rgba: data, size: bitmap.width };
    } finally {
      bitmap.close?.();
    }
  };
}

/**
 * Builds the provider. Web Mercator tiling, so a Terrarium tile (z, x, y) is
 * Cesium tile (level z, x, y) with no reprojection. KNOWN LIMIT: Web Mercator
 * stops at about 85.05 degrees, so with this provider the globe has no terrain
 * surface (a hole) beyond that at the poles.
 *
 * @param {object} options
 * @param {string} options.urlTemplate owner's template with {z}/{x}/{y}
 * @param {number} [options.maxLevel] deepest zoom requested
 * @param {number} [options.samples] heightmap edge, 2^n + 1
 * @param {(url: string) => Promise<{rgba: ArrayLike<number>, size: number}|undefined>}
 *   [options.fetchPixels] tile loader; injectable for tests
 * @param {(latDeg: number, lonDeg: number) => number} [options.heightOffset]
 *   metres added to every height (datum correction), evaluated at the tile centre
 */
export function createTerrariumTerrainProvider({
  urlTemplate,
  maxLevel = TERRARIUM_MAX_LEVEL,
  samples = TERRARIUM_HEIGHTMAP_SAMPLES,
  fetchPixels = createFetchPixels({
    retryPolicy: createTerrainRetryPolicy(),
  }),
  heightOffset = null,
} = {}) {
  if (!urlTemplate) throw new Error('Terrarium terrain needs a URL template');
  const tilingScheme = new Cesium.WebMercatorTilingScheme();
  const errorEvent = new Cesium.Event();
  const levelZeroError =
    Cesium.TerrainProvider.getEstimatedLevelZeroGeometricErrorForAHeightmap(
      tilingScheme.ellipsoid,
      samples,
      tilingScheme.getNumberOfXTilesAtLevel(0),
    );

  const flat = (mask) =>
    new Cesium.HeightmapTerrainData({
      buffer: new Float32Array(samples * samples),
      width: samples,
      height: samples,
      childTileMask: mask,
    });
  const childMask = (level) => (level + 1 <= maxLevel ? 15 : 0);

  return {
    tilingScheme,
    errorEvent,
    credit: undefined,
    ready: true,
    hasWaterMask: false,
    hasVertexNormals: false,
    availability: undefined,
    maxLevel,
    getLevelMaximumGeometricError(level) {
      return levelZeroError / (1 << level);
    },
    getTileDataAvailable(x, y, level) {
      return isTerrariumTileAvailable(x, y, level, maxLevel);
    },
    loadTileDataAvailability() {
      return undefined;
    },
    /**
     * Resolves a HeightmapTerrainData; undefined means "throttled, ask again".
     * Never rejects: a missing or failed tile is flat with no children asked
     * for, so one bad tile cannot cause a subtree of requests.
     */
    async requestTileGeometry(x, y, level) {
      if (!isTerrariumTileAvailable(x, y, level, maxLevel)) return flat(0);
      try {
        const tile = await fetchPixels(expandTileUrl(urlTemplate, level, x, y));
        if (tile === undefined) return undefined;
        const heights = decodeTerrariumPixels(tile.rgba, tile.size);
        const map = heightsToHeightmap(heights, tile.size, samples);
        if (typeof heightOffset === 'function') {
          const rect = tilingScheme.tileXYToRectangle(x, y, level);
          const offset = heightOffset(
            Cesium.Math.toDegrees(Cesium.Rectangle.center(rect).latitude),
            Cesium.Math.toDegrees(Cesium.Rectangle.center(rect).longitude),
          );
          if (Number.isFinite(offset) && offset !== 0)
            for (let i = 0; i < map.length; i += 1) map[i] += offset;
        }
        return new Cesium.HeightmapTerrainData({
          buffer: map,
          width: samples,
          height: samples,
          childTileMask: childMask(level),
        });
      } catch {
        return flat(0);
      }
    },
  };
}
