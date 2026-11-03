# Testing

## Automated

Run from `screen/`. None of these needs a key.

| Command | What it checks |
| --- | --- |
| `npm test` | Unit tests (`scripts/run-unit-tests.mjs`, `src/**/*.test.mjs` and `server/**`) |
| `npm run check:boundaries` | Import directions and package boundaries ([docs/CODE-BOUNDARIES.md](docs/CODE-BOUNDARIES.md)) |
| `npm run format:check` | Formatting scope |
| `npm run layer-token:check` | Share-link layer tokens are never reused or reassigned |
| `npm run i18n` | Every user-visible string is translatable and every locale is complete |
| `npm run changelog:check` | Changelog fragments are well formed |
| `npm run build` | The production bundle builds |

CI (`.github/workflows/ci.yml`) runs formatting, boundaries, the layer-token
check, tests and the build.

## Browser gates

`scripts/qa-*.mjs` drive the real app in a headless browser (Puppeteer) and
assert one feature's contract, for example `qa-firms`, `qa-wind-canvas`,
`qa-transit`, `qa-vessel-cards`, `qa-draw-tool` and `qa-layer-panel`. Most
need a running dev server; some need a provider key or a port. The header of
each script says what it proves and how to run it. Two have an `npm run`
alias: `qa:map-source-tray` and `qa:transit`.

Harnesses that need a GPU pick Metal on macOS and SwiftShader elsewhere.

## By hand

Start the app (`npm run dev`, `http://localhost:4173`), check the console is
clean, then:

1. Turn on Live Flights and Satellites; aircraft and satellites appear on the globe.
2. Search a place; the camera flies there. Make a share link, open it in a new
   tab, and the same view restores.
3. DISPLAY ▸ Draw: place an Area, a Line and a Pin; each appears on the
   terrain and survives a style change.
4. Switch the style between Normal, Anime and Noir.
5. Switch the language; the page reloads in it.
