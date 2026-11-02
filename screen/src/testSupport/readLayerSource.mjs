import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Read actual component owners for structural regression assertions. */
export function readLayerSource(file) {
  const path = file instanceof URL ? fileURLToPath(file) : file;
  if (
    ![
      'flights.js',
      'aisLiveVessels.js',
      'firmsHeatmap.js',
      'satellites.js',
      'rocketLaunches.js',
      'bikeshare.js',
      'cctv.js',
    ].includes(basename(path))
  )
    return readFileSync(path, 'utf8');
  const directory = join(
    dirname(path),
    basename(path) === 'flights.js'
      ? '../layers/flights'
      : basename(path) === 'firmsHeatmap.js'
        ? '../layers/firms'
        : basename(path) === 'satellites.js'
          ? '../layers/satellites'
          : basename(path) === 'rocketLaunches.js'
            ? '../layers/launches'
            : basename(path) === 'bikeshare.js'
              ? '../layers/bikeshare'
              : basename(path) === 'cctv.js'
                ? '../layers/cctv'
                : '../layers/vessels',
  );
  return readdirSync(directory)
    .filter((name) => name.endsWith('.js'))
    .sort()
    .map((name) => readFileSync(join(directory, name), 'utf8'))
    .join('\n');
}
