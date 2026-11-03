# Contributing

This is the screen of Astrolabe, a fork of God's Eye View by Bilawal Sidhu
(MIT; see [LICENSE](LICENSE)). Read the root [FORK.md](../FORK.md) first: it
lists everything removed and every change to upstream files, and the rule is
that **every change to a file under `screen/` is appended there** (file, what,
why). A change that is not listed is a bug. The plan is
[ROADMAP.md](../ROADMAP.md). Do not add features that were ruled out: nothing
military, police, ALPR or agency-run, no voice or AI features, no simulated or
estimated data shown as real.

## Setup

Node 24.14 or newer (`engines` in `package.json`).

```bash
cd screen
npm install
npm run dev          # http://localhost:4173
```

No key is needed to start (Esri World Imagery and keyless terrain). Keys go in
a `.env` file; the ones that are read are listed in [README.md](README.md).

## Checks before a change is done

```bash
npm test                    # unit tests (scripts/run-unit-tests.mjs)
npm run format:check
npm run check:boundaries    # import directions and package boundaries
npm run layer-token:check   # share-link layer tokens are never reused
npm run i18n                # all user-visible text is translatable
npm run build
```

Feature gates live under `scripts/qa-*.mjs`; they drive the real app in a
browser and most need a dev server. Read the header of the one that covers
what you touched. See [TESTING.md](TESTING.md).

`npm run doctor` and `npm run qa:street-level` are in `package.json` but their
scripts no longer exist.

## Rules

- ES modules, two-space indent, single quotes, semicolons; match the
  surrounding code. Run `npm run format` first.
- User-visible text goes through `t()`, `tn()` or `msg()`, or a `data-i18n*`
  attribute ([docs/I18N.md](docs/I18N.md)).
- Secrets stay on the server ([SECURITY.md](SECURITY.md)).
- A new or changed data source updates [DATA_SOURCES.md](DATA_SOURCES.md) with
  its licence and attribution, and the credit in `src/data/dataCredits.js`.
  Do not bundle data you cannot redistribute.
- A new layer needs a permanent share-link token (`npm run layer-token:next`);
  tokens and codes are never reused ([docs/SHARE-LINK-FORMAT.md](docs/SHARE-LINK-FORMAT.md)).
  The layer panel groups are in `PANEL_GROUPS` in `src/ui/layerPanel.js`.
- A change to runtime behaviour updates [docs/CURRENT-STATE.md](docs/CURRENT-STATE.md)
  and adds a `changelog.d/<number>-<slug>.md` fragment
  ([changelog.d/README.md](changelog.d/README.md)).
- Module ownership and the formatting scope: [docs/CODE-BOUNDARIES.md](docs/CODE-BOUNDARIES.md).

By contributing you agree your contributions are licensed under the MIT
License in [LICENSE](LICENSE).
