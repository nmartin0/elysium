// The simulator's control panel's bundle (BLOCKING.md item 3, step 2.3).
// Its source and its built bundle live with the simulator, in sim/panel;
// this config lives here because it builds with this page's tools and
// against this page's shared libraries (@shell/build, the kit's list), so
// the simulator carries no Node packages of its own. Built by
// `npm run build` and on save by `npm run dev` (vite.config.ts), served
// by Elysium from sim/panel/dist like any module's bundle.
import { join } from 'node:path'
import { moduleConfig } from '@shell/build/moduleBuild'
import { defineConfig } from 'vite'
import { SHARED_LIBRARIES, SHARED_PACKAGES } from '@elysium/shell-api/sharedLibraries'

export default defineConfig(
  moduleConfig({
    root: join(import.meta.dirname, '..', '..', 'sim', 'panel', 'web'),
    entry: 'src/module.tsx',
    libraries: SHARED_LIBRARIES,
    packages: SHARED_PACKAGES,
    outDir: '../dist',
  }),
)
