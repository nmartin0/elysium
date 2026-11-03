import * as Cesium from 'cesium';
export const MAP_STACKS = [
  {
    id: 'photoreal',
    label: 'Google 3D', // i18n-ignore: imagery product name
    shortLabel: '3D',
    kind: 'photoreal',
    requiresIon: false,
  },
  {
    // The keyless default (2 Nov 2026): bundled Natural Earth II, public domain.
    id: 'natural-earth',
    label: 'Natural Earth', // i18n-ignore: imagery product name
    shortLabel: 'NE',
    kind: 'natural-earth',
    requiresIon: false,
  },
  {
    id: 'bing-aerial',
    label: 'Bing Aerial', // i18n-ignore: imagery product name
    shortLabel: 'Aerial',
    kind: 'ion',
    style: Cesium.IonWorldImageryStyle.AERIAL,
    requiresIon: true,
  },
  {
    id: 'bing-labels',
    label: 'Bing Labels', // i18n-ignore: imagery product name
    shortLabel: 'Labels',
    kind: 'ion',
    style: Cesium.IonWorldImageryStyle.AERIAL_WITH_LABELS,
    requiresIon: true,
  },
  {
    id: 'esri-imagery',
    // Not the default: needs the user's own Esri licence (FORK.md, docs/feeds.md).
    label: 'Esri Satellite (own licence)', // i18n-ignore: imagery product name
    shortLabel: 'SAT',
    kind: 'esri-imagery',
    requiresIon: false,
  },
  {
    id: 'osm',
    label: 'OSM', // i18n-ignore: imagery product name
    shortLabel: 'OSM',
    kind: 'osm',
    requiresIon: false,
  },
];
