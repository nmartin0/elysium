// TypeScript knows the `test` field below from the `vitest/config` import
// (configDefaults): importing the module brings its augmentation of
// Vite's config with it. It used to need a triple-slash reference, which
// oxlint refuses once a plain import does the same job.
import { existsSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { builtModules } from '@shell/build/moduleBuild'
import { moduleTestConfig } from '@shell/build/testPreset'
import { sharedLibraries } from '@shell/build/sharedLibraries'
import react from '@vitejs/plugin-react'
import { defineConfig, searchForWorkspaceRoot } from 'vite'
import { configDefaults } from 'vitest/config'
import { SHARED_LIBRARIES, SHARED_PACKAGES } from '@elysium/shell-api/sharedLibraries'

// During `npm run dev`, requests to any real API path are proxied
// straight through to the backend -- from the BROWSER's perspective,
// everything appears to come from one origin, so this never needs
// CORS configured on the FastAPI side at all. In production, the
// built app is served BY FastAPI itself (see api/app.py), which is
// already the same origin for the same reason -- CORS genuinely never
// enters the picture in either mode.
const API_PROXY_TARGET = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

// THE SUB-APPS WITH BUNDLES OF THEIR OWN (BLOCKING.md item 3, step 1.2):
// any package with a vite.config.ts of its own. `npm run build` builds
// each after the page; `npm run dev` rebuilds each on save, so development
// loads a module the way production does.
const PACKAGES = join(import.meta.dirname, 'packages')
const MODULE_BUILDS = readdirSync(PACKAGES)
  .map((name) => join(PACKAGES, name, 'vite.config.ts'))
  .filter((config) => existsSync(config))
// ...and those with tests configured by themselves: a vitest.config.ts.
const MODULE_TESTS = readdirSync(PACKAGES)
  .filter((name) => existsSync(join(PACKAGES, name, 'vitest.config.ts')))
  .map((name) => `packages/${name}`)

export default defineConfig({
  plugins: [
    react(),
    sharedLibraries({ libraries: SHARED_LIBRARIES, packages: SHARED_PACKAGES }),
    builtModules({ configs: MODULE_BUILDS }),
  ],
  // ONE REACT. `@shell/core` (../shell, BLOCKING.md item 3) is linked
  // in by `file:`, and its own node_modules holds a React for its own
  // tests; a second copy in the bundle would give the shell's routes a
  // different React -- and a different router context -- from the
  // page's, and every hook in them would throw. Shared libraries are
  // the page's, fixed once (the import-map decision in item 3).
  resolve: { dedupe: ['react', 'react-dom', 'react-router-dom'] },
  server: {
    // THE GENERIC SHELL LIVES BESIDE THIS PROJECT, in ../shell, linked in
    // by `file:`. Vite serves nothing outside its workspace by default,
    // so `npm run dev` answered 403 for every @shell/* file and the app
    // never loaded -- shipped that way in the commit adding @shell/core,
    // because a production build reads the files directly and jsdom
    // never asks the dev server. Found by requesting the file from a
    // running dev server (21 October).
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), '../shell'] },
    proxy: {
      // ONE entry, deliberately -- every real backend path lives
      // under /api (see api/app.py's own include_router() call, and
      // this file's own AI-notes below for the real bug that made
      // this a structural requirement, not a style choice). A plain
      // browser page navigation to any client-side react-router-dom
      // route -- /query, /browse, /objects/Customer/cust_001, a
      // future route not yet written -- can NEVER be mistaken for a
      // real API path by this proxy, because no client-side route is
      // ever allowed to start with /api. No case-by-case prefix list
      // to keep in sync by hand as new routes and endpoints are added
      // on either side.
      '/api': API_PROXY_TARGET,
    },
  },
  // Vitest shares this SAME config file rather than a separate one --
  // one source of truth for how this app builds AND how it's tested,
  // not two files that could quietly drift apart. Discovers tests
  // across the whole workspace (root src/ AND every packages/*/src/)
  // in one run -- matches how this is still one build/one deploy, not
  // per-package test runs.
  // THE SAME PRESET EVERY MODULE INHERITS (@shell/build/testPreset): the
  // time zone, pool and timeouts, with the reasons for each, live there,
  // so the page and its modules cannot drift apart. The setup file is
  // the provider's (@elysium/testing/setup).
  //
  // PROJECTS, one run: the page and the sub-apps still inside it are one
  // project; a sub-app with a vitest.config.ts of its own -- a MODULE,
  // built and tested apart -- is its own project, configured by its own
  // file and run alongside. `npx vitest run` still runs everything.
  test: {
    ...moduleTestConfig({ setupFiles: ['@elysium/testing/setup'] }),
    projects: [
      {
        extends: true,
        test: {
          name: 'elysium',
          include: ['src/**/*.test.{js,jsx,ts,tsx}', 'packages/*/src/**/*.test.{js,jsx,ts,tsx}'],
          exclude: [...configDefaults.exclude, ...MODULE_TESTS.map((folder) => `${folder}/**`)],
        },
      },
      ...MODULE_TESTS,
    ],
  },
})

// =============================================================================
// AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
// later) that lacks this conversation's history. Update this section
// whenever something genuinely open, deferred, or rejected comes up here.
// =============================================================================
//
// RESOLVED (kept for history):
// - A real, user-found bug, in TWO parts, both from the SAME root
//   cause: this proxy list used to be an explicit, per-prefix
//   allowlist (/login, /objects, /me, ...), matched against ANY
//   request starting with a listed prefix -- including a plain
//   BROWSER PAGE NAVIGATION (pasting a URL, hitting enter), not just
//   this app's own fetch() calls. Stage 2's Object View originally
//   used a client-side route at /objects/:type/:id -- the SAME path
//   as the real backend API -- so a raw navigation to a bookmarked
//   object URL hit the backend directly, with no auth header
//   (browsers don't attach bearer tokens to page navigations),
//   producing the backend's own raw 401 JSON on screen instead of
//   this app ever loading. A first fix (renaming the client-side
//   route to /browse/:type/:id) closed THAT specific collision but
//   was explicitly, honestly judged not idiomatic or fully safe on
//   its own -- it required catching each collision by hand, and a
//   SECOND one (/query, both a real frontend route AND a real proxy
//   entry) was found sitting there, unfixed, the same day, confirmed
//   directly with a real curl request returning a genuine 502.
//
//   The REAL, structural fix: every backend route moved under /api
//   (api/app.py's own include_router(router, prefix="/api")) -- see
//   the official FastAPI docs (fastapi.tiangolo.com/tutorial/bigger-
//   applications/) for the documented, idiomatic prefix mechanism
//   this uses. This proxy list collapsed from 8 individual entries to
//   this ONE, and the client-side route that motivated all of this
//   was reverted back to the more natural /objects/:type/:id (see
//   App.jsx's own comment) -- no longer needing to avoid a collision
//   that is now structurally impossible.
//
//   A SEPARATE, second real bug was found and fixed in the SAME pass,
//   NOT caused by this proxy config at all: FastAPI's own production-
//   mode static serving (app.mount(StaticFiles(html=True)), the old
//   mechanism) never actually provided genuine SPA-fallback routing
//   for arbitrary client-side paths -- only for a real root/directory
//   path. A fresh GET to /browse (an existing, already-shipped,
//   uncontroversial route, nothing to do with the /api collision)
//   404'd against a real, production-mode server, confirmed directly.
//   Replaced with app.frontend() -- FastAPI's own real, native,
//   documented SPA-serving mechanism (0.138.0+) -- see api/app.py's
//   own comment for the fuller reasoning.
// - Converted from vite.config.js to vite.config.ts, alongside the
//   rest of this project's own real JS-to-TS hardening pass -- the
//   last two remaining .js files in the whole repo (this one and
//   playwright.config.js), confirmed via a fresh, whole-repo search,
//   not assumed to be the only ones left.
