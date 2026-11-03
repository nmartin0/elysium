import test from 'node:test';
import assert from 'node:assert/strict';
import * as Cesium from 'cesium';
import {
  TERRARIUM_MAX_LEVEL,
  TERRARIUM_TILE_SIZE,
  decodeTerrariumHeight,
  decodeTerrariumPixels,
  heightsToHeightmap,
  expandTileUrl,
  isTerrariumTileAvailable,
  createTerrariumTerrainProvider,
} from './terrariumTerrain.js';
import { createKeylessTerrain, KEYLESS_TERRAIN_STUB } from './terrain.js';
import {
  configureTerrain,
  getTerrainConfig,
  isSelfHostedTerrainOn,
} from './terrainConfig.js';
import {
  registerDataCredits,
  mapterhornCreditHtml,
} from '../data/dataCredits.js';

// SYNTHETIC tiles only: raw RGBA built in the test. No image codec (PNG or
// WebP) is involved, because the decoder takes raw pixels; the browser-only
// path (blob -> ImageBitmap -> canvas) is NOT exercised here.
function tile(size, heightAt) {
  const rgba = new Uint8Array(size * size * 4);
  for (let row = 0; row < size; row += 1)
    for (let col = 0; col < size; col += 1) {
      const v = Math.round((heightAt(row, col) + 32768) * 256);
      const o = (row * size + col) * 4;
      rgba[o] = (v >> 16) & 255;
      rgba[o + 1] = (v >> 8) & 255;
      rgba[o + 2] = v & 255;
      rgba[o + 3] = 255;
    }
  return { rgba, size };
}

test('Terrarium height formula at known values', () => {
  assert.equal(decodeTerrariumHeight(128, 0, 0), 0);
  assert.equal(decodeTerrariumHeight(0, 0, 0), -32768);
  assert.equal(decodeTerrariumHeight(128, 1, 0), 1);
  assert.equal(decodeTerrariumHeight(128, 0, 128), 0.5);
  assert.equal(decodeTerrariumHeight(129, 44, 64), 256 + 44 + 0.25);
  assert.equal(decodeTerrariumHeight(127, 255, 255), -1 / 256);
});

test('decodeTerrariumPixels reads raw RGBA row by row, north first', () => {
  const { rgba, size } = tile(2, (row, col) => row * 100 + col * 10);
  const h = decodeTerrariumPixels(rgba, size);
  assert.deepEqual(Array.from(h), [0, 10, 100, 110]);
  assert.throws(() => decodeTerrariumPixels(new Uint8Array(4), 2));
  assert.equal(TERRARIUM_TILE_SIZE, 512);
});

test('tile to heightmap: corner-aligned bilinear resample', () => {
  // 4x4 pixels, height = 10 * column (a west-to-east ramp).
  const { rgba, size } = tile(4, (row, col) => col * 10);
  const map = heightsToHeightmap(decodeTerrariumPixels(rgba, size), size, 5);
  // Sample i sits at pixel-centre coordinate i - 0.5, clamped to 0..3.
  const row0 = Array.from(map.slice(0, 5));
  assert.deepEqual(row0, [0, 5, 15, 25, 30]);
  // The ramp does not vary by row.
  assert.deepEqual(Array.from(map.slice(20, 25)), row0);
  // North-to-south ramp: row 0 is north.
  const ns = tile(4, (row) => row * 10);
  const m2 = heightsToHeightmap(decodeTerrariumPixels(ns.rgba, 4), 4, 5);
  assert.equal(m2[0], 0);
  assert.equal(m2[20], 30);
});

test('URL template expansion and availability bounds', () => {
  assert.equal(
    expandTileUrl('https://t.example/{z}/{x}/{y}.webp', 3, 5, 2),
    'https://t.example/3/5/2.webp',
  );
  assert.equal(expandTileUrl('/a/{z}/{z}/{x}/{y}', 1, 0, 1), '/a/1/1/0/1');
  assert.equal(TERRARIUM_MAX_LEVEL, 12);
  assert.ok(isTerrariumTileAvailable(0, 0, 0));
  assert.ok(!isTerrariumTileAvailable(1, 0, 0));
  assert.ok(!isTerrariumTileAvailable(0, 1, 0));
  assert.ok(isTerrariumTileAvailable(3, 3, 2));
  assert.ok(!isTerrariumTileAvailable(4, 0, 2));
  assert.ok(!isTerrariumTileAvailable(-1, 0, 2));
  assert.ok(isTerrariumTileAvailable(4095, 4095, 12));
  assert.ok(!isTerrariumTileAvailable(0, 0, 13));
  assert.ok(!isTerrariumTileAvailable(0, 0, -1));
  assert.ok(!isTerrariumTileAvailable(1.5, 0, 3));
  assert.ok(isTerrariumTileAvailable(0, 0, 14, 14), 'maxLevel is a parameter');
});

test('provider: Web Mercator tiling, availability and max level', async () => {
  const urls = [];
  const provider = createTerrariumTerrainProvider({
    urlTemplate: 'https://t.example/{z}/{x}/{y}.webp',
    samples: 5,
    fetchPixels: async (url) => (urls.push(url), tile(4, () => 100)),
  });
  assert.ok(provider.tilingScheme instanceof Cesium.WebMercatorTilingScheme);
  assert.equal(provider.tilingScheme.getNumberOfXTilesAtLevel(0), 1);
  assert.equal(provider.getTileDataAvailable(0, 0, 12), true);
  assert.equal(provider.getTileDataAvailable(0, 0, 13), false);
  assert.equal(provider.getTileDataAvailable(2, 0, 1), false);
  // Out-of-range tiles are not requested.
  const beyond = await provider.requestTileGeometry(0, 0, 13);
  const outside = await provider.requestTileGeometry(9, 0, 2);
  assert.equal(urls.length, 0);
  assert.ok(beyond instanceof Cesium.HeightmapTerrainData);
  assert.ok(outside instanceof Cesium.HeightmapTerrainData);
  // A real tile: only the template is requested; children exist below max.
  const data = await provider.requestTileGeometry(2, 1, 3);
  assert.deepEqual(urls, ['https://t.example/3/2/1.webp']);
  assert.ok(data instanceof Cesium.HeightmapTerrainData);
  assert.equal(data._buffer.length, 25);
  assert.ok(Array.from(data._buffer).every((v) => v === 100));
  assert.equal(data._childTileMask, 15);
  const deepest = await provider.requestTileGeometry(0, 0, 12);
  assert.equal(deepest._childTileMask, 0, 'no children past the max level');
  // Geometric error halves with each level.
  assert.equal(
    provider.getLevelMaximumGeometricError(1) * 2,
    provider.getLevelMaximumGeometricError(0),
  );
});

test('provider: a failed or malformed tile is flat, never throws, no retry', async () => {
  let calls = 0;
  const failing = createTerrariumTerrainProvider({
    urlTemplate: '/t/{z}/{x}/{y}',
    samples: 5,
    fetchPixels: async () => {
      calls += 1;
      throw new Error('404');
    },
  });
  const flat = await failing.requestTileGeometry(0, 0, 1);
  assert.equal(calls, 1);
  assert.ok(flat instanceof Cesium.HeightmapTerrainData);
  assert.ok(Array.from(flat._buffer).every((v) => v === 0));
  assert.equal(flat._childTileMask, 0);
  const bad = createTerrariumTerrainProvider({
    urlTemplate: '/t/{z}/{x}/{y}',
    samples: 5,
    fetchPixels: async () => ({ rgba: new Uint8Array(3), size: 4 }),
  });
  assert.ok(
    Array.from((await bad.requestTileGeometry(0, 0, 1))._buffer).every(
      (v) => v === 0,
    ),
  );
  // Throttled by the request scheduler: ask again later.
  const throttled = createTerrariumTerrainProvider({
    urlTemplate: '/t/{z}/{x}/{y}',
    fetchPixels: async () => undefined,
  });
  assert.equal(await throttled.requestTileGeometry(0, 0, 1), undefined);
});

test('provider: heightOffset shifts every height', async () => {
  const provider = createTerrariumTerrainProvider({
    urlTemplate: '/t/{z}/{x}/{y}',
    samples: 3,
    heightOffset: () => 25,
    fetchPixels: async () => tile(2, () => 10),
  });
  const data = await provider.requestTileGeometry(0, 0, 0);
  assert.ok(Array.from(data._buffer).every((v) => v === 35));
});

test('config: unset keeps flat terrain and makes no request', async () => {
  configureTerrain({});
  assert.equal(isSelfHostedTerrainOn(), false);
  const originalFrom = Cesium.CesiumTerrainProvider.fromUrl;
  Cesium.CesiumTerrainProvider.fromUrl = async () =>
    assert.fail('stubbed terrain must not be requested');
  try {
    assert.equal(KEYLESS_TERRAIN_STUB.stubbed, true);
    const { provider } = await createKeylessTerrain(undefined, {
      fetchPixels: async () => assert.fail('no tile request when unset'),
    });
    assert.ok(provider instanceof Cesium.EllipsoidTerrainProvider);
  } finally {
    Cesium.CesiumTerrainProvider.fromUrl = originalFrom;
  }
});

test('config: set makes the tile provider and requests only the template', async () => {
  try {
    assert.deepEqual(
      configureTerrain({
        tileUrl: 'https://tiles.example.org/{z}/{x}/{y}.webp',
        attributionUrl: 'https://example.org/terrain-credits',
      }),
      {
        tileUrl: 'https://tiles.example.org/{z}/{x}/{y}.webp',
        attributionUrl: 'https://example.org/terrain-credits',
      },
    );
    assert.equal(isSelfHostedTerrainOn(), true);
    const urls = [];
    const originalFrom = Cesium.CesiumTerrainProvider.fromUrl;
    Cesium.CesiumTerrainProvider.fromUrl = async () =>
      assert.fail('Re:Earth must stay off');
    try {
      const { provider } = await createKeylessTerrain(undefined, {
        fetchPixels: async (url) => (urls.push(url), tile(2, () => 1)),
      });
      assert.ok(!(provider instanceof Cesium.EllipsoidTerrainProvider));
      await provider.requestTileGeometry(1, 0, 1);
      assert.deepEqual(urls, ['https://tiles.example.org/1/1/0.webp']);
    } finally {
      Cesium.CesiumTerrainProvider.fromUrl = originalFrom;
    }
  } finally {
    configureTerrain({});
  }
});

test('config: values without {z}/{x}/{y} or a non-http scheme are ignored', () => {
  const warn = console.warn;
  console.warn = () => {};
  try {
    assert.equal(
      configureTerrain({ tileUrl: 'https://a.example/{z}/{x}' }).tileUrl,
      '',
    );
    assert.equal(
      configureTerrain({ tileUrl: 'file:///{z}/{x}/{y}' }).tileUrl,
      '',
    );
    assert.equal(
      configureTerrain({ tileUrl: '/tiles/{z}/{x}/{y}.webp' }).tileUrl,
      '/tiles/{z}/{x}/{y}.webp',
    );
    assert.equal(
      configureTerrain({ attributionUrl: 'javascript:alert(1)' })
        .attributionUrl,
      '',
    );
  } finally {
    console.warn = warn;
    configureTerrain({});
  }
  assert.deepEqual(getTerrainConfig(), { tileUrl: '', attributionUrl: '' });
});

test('terrain credit appears only when the terrain is on', () => {
  const run = (options) => {
    const added = [];
    registerDataCredits(
      { creditDisplay: { addStaticCredit: (c) => added.push(c.html) } },
      [],
      options,
    );
    return added;
  };
  assert.deepEqual(run(undefined), []);
  assert.deepEqual(
    run({ terrainOn: false, terrainAttributionUrl: 'https://x.example/a' }),
    [],
  );
  const [on] = run({
    terrainOn: true,
    terrainAttributionUrl: 'https://x.example/a?b=1&c="2"',
  });
  assert.match(on, /Mapterhorn/);
  assert.match(on, /href="https:\/\/x\.example\/a\?b=1&amp;c=&quot;2&quot;"/);
  assert.doesNotMatch(mapterhornCreditHtml(''), /href/);
  assert.doesNotMatch(mapterhornCreditHtml('javascript:alert(1)'), /href/);
});
