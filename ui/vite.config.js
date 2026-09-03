import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// During `npm run dev`, requests to any real API path are proxied
// straight through to the backend -- from the BROWSER's perspective,
// everything appears to come from one origin, so this never needs
// CORS configured on the FastAPI side at all. In production, the
// built app is served BY FastAPI itself (see api/app.py), which is
// already the same origin for the same reason -- CORS genuinely never
// enters the picture in either mode.
const API_PROXY_TARGET = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
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
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.js',
    include: ['src/**/*.test.{js,jsx,ts,tsx}', 'packages/*/src/**/*.test.{js,jsx,ts,tsx}'],
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
