# Formatting and component boundaries

Run `npm run format` to format the files in `scripts/format-scope.json` plus
automatically discovered runtime JavaScript in `scripts/format-runtime.json`, and
`npm run format:check` to check that same list without writing. CI checks the
combined scope on Linux and Windows. Prettier is pinned in the development
dependencies; use the installed version so local and CI output agree. The shared
configuration specifies two spaces, single quotes, semicolons and LF endings.

Owned runtime modules are discovered automatically; add their tests and other
non-runtime files to the explicit list as they are adopted.
Keep mechanical formatting in its own commit after behavior is stable. Existing
source-text regression assertions still apply; investigate failures and preserve
their behavioral coverage when a move or line wrap changes a tested shape.
Files outside the runtime roots and explicit list retain their surrounding style
until deliberately adopted.
Generated output, local configuration, browser evidence and bundled datasets are
excluded. The formatter validates every entry before writing any file.

New world text labels must use the world-overlay host; Cesium text labels are forbidden.

## Component ownership

Package imports use `gods-eye-view`; `package.json` is the authoritative
export inventory. Use declared exports rather than reaching into internal files.

| Owner                  | Responsibility and lifetime                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------------- |
| `src/app/`             | Construct supplied components, share request services, cancel startup and dispose the application      |
| `src/standalone/`      | Select the default catalog, local sources and chrome                                                    |
| `src/ui/`              | Navigation generations, restoration, visual state, panel snapshots and their subscriptions              |
| `src/data/`            | Lifecycle, context and feed state; legacy default-layer facades                                         |
| `src/layers/<family>/` | Source acquisition, records and Cesium resources with explicit controller/renderer owners               |
| `src/sources/`         | Portable protocols and source contracts; request state belongs to each factory instance                 |
| `src/services/`        | Supplied application operations (boundaries, terrain, features) with their own caches and cancellation  |
| `server/providers/`    | Node route factories, process-scoped provider caches and shutdown cleanup                               |
| `server/standalone/`   | Vite server composition, the unknown-`/api` 404 and cache-directory watching                            |
| `build/`               | Vite configuration, CSP and headers, host allowlist, embed framing                                      |

See [application construction](APPLICATION.md), the
[infrastructure contract](INFRASTRUCTURE-LAYERS.md), [UI ownership](UI-OWNERSHIP.md)
and [panel surfaces](panel-surfaces.md) for the interfaces.

## Import direction gates

`npm run check:boundaries` runs two complementary checks:

1. `scripts/check-import-directions.mjs` parses every runtime JS/MJS/CJS file in
   `src/` and `server/`, including files unused by the current bundle. Static,
   literal dynamic and re-export edges are checked; computed module imports and
   CommonJS `require` are rejected. Browser graphs cannot reach Node, server or
   test modules through helpers. Reusable modules cannot select standalone setup,
   and provider modules cannot import application/rendering modules.
2. `scripts/check-package-boundaries.mjs` builds every declared export without
   app Vite configuration or environment files. `scripts/package-boundaries.json`
   assigns each export exactly once and lists its owned modules and external
   dependencies. Unused imports still count. Node exports have only a `node`
   condition; browser groups cannot use build-only dependency exceptions.

Portable source graphs cannot reach application/rendering, Node, Cesium or
browser globals. This includes `sources/*`, dedicated `layers/*/source` exports,
flight and vessel record and ingestion exports, lifecycle and feed state. The browser-global rule reserves platform
names such as `document` and `window` in these modules; it is an architectural
check, not a JavaScript sandbox. Negative fixtures cover indirect helpers,
self-package imports, symlinks and unreachable files.

Source-only factories use dedicated `layers/<family>/source` exports where
available, preserving the same factory implementation without loading rendering.
Record normalization and endpoint policies have plain owners separate from
geometry/cards. Source exports do not start acquisition at import time.

Other layer `ingestion.js` files may still coordinate Cesium resources; the
portable contract applies to the explicitly reviewed graphs above. Their layer
controller remains the owner of rendering/cleanup until a focused extraction
moves it. Do not label all ingestion modules platform-independent by filename.


## Compatibility entries

| Retained entry                                      | Owner and current reason                                                                                           |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `src/data/manager.js`                               | Lifecycle/panel compatibility and existing tests; normal assembly constructs lifecycle and presentation separately |
| `src/data/<layer>.js`                               | Legacy default instances; new assembly calls layer factories with supplied sources                                 |
| `src/app/sources.js`, `src/services/application.js` | Existing default/override API; current application construction supplies its own instances                         |
| `server/providers/local.js`                         | Existing Node composition barrel and provider helper re-exports                                                    |
| `src/app/layerStubs.js`                             | Inert objects that stand in for the eight removed layers that the catalog still requires (FORK.md)                 |

## Build

`gods-eye-view/build/vite` is a separate Node-only export. `build/vite.js`
creates the Cesium/Vite browser settings from explicit inputs (plugins, the
browser keys, host, port, allowed hosts); it discovers no environment and
constructs no provider middleware. `server/standalone/vite.config.js` loads
the environment and passes those inputs, with the provider plugins from
`server/providers/local.js`.

## Share-link layer tokens

Layer tokens and codes are permanent (`src/data/layerStateTokenReservations.json`,
checked by `npm run layer-token:check`). A removed layer keeps its token.
