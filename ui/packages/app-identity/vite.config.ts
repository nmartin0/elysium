// The Identity review's own bundle (BLOCKING.md item 3, step 3): built
// apart from Elysium's page, leaving the page's shared libraries as bare
// imports. Built by `npm run build` and rebuilt on save by `npm run dev`
// (ui/vite.config.ts, builtModules); served from dist/ by Elysium's
// server at /api/modules/identity/files/.
import { moduleConfig } from '@shell/build/moduleBuild'
import { defineConfig } from 'vite'
import { SHARED_LIBRARIES, SHARED_PACKAGES } from '@elysium/shell-api/sharedLibraries'

export default defineConfig(
  moduleConfig({
    root: import.meta.dirname,
    entry: 'src/module.tsx',
    libraries: SHARED_LIBRARIES,
    packages: SHARED_PACKAGES,
  }),
)
