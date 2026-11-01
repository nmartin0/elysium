# Heliograph as an Elysium module

This folder is a module of [Elysium](../../docs/research/elysium.md): a manifest, a
hand-written page and, through `heliograph serve`, the server behind it (decision D50).
It was checked against Elysium `dev` at `348414e0`: its loader accepts `module.json`, its
own supervisor starts the server, its proxy forwards signed requests to it, and its five
add-on contract checks pass. What was and was not tried is in
[the slice-1 note](../../docs/research/elysium-slice1.md).

## Install

1. Put the `heliograph` command on the `PATH` Elysium runs with (it passes `PATH` on, and
   nothing else of its environment): `uv tool install` this repository, or start Elysium
   from an environment that has it.
2. List this folder in the deployment's `modules.yaml`:

   ```yaml
   home: /heliograph          # or keep your own home
   modules:
     - /path/to/heliograph/integrations/elysium
   ```

3. Optionally give the server options in `addons.yaml`:

   ```yaml
   heliograph:
     options:
       configs: /path/to/heliograph/examples   # run configurations offered; default none
       data: /path/to/runs-home                # default: the folder Elysium gives it
   ```

4. Grant `module:heliograph:use` (read) and `module:heliograph:operate` (submit backtests,
   keep configurations) to roles. The module is offered to holders of `use`.

## What each file is

- `module.json`: the manifest. Every key is one `core/modules.py` of Elysium accepts; it
  refuses others. Paths start with `/heliograph`, because a path belongs to whichever
  module claims it first; `subject` groups the rail entry (an unknown subject sorts after
  Elysium's own).
- `dist/index.js` and `dist/index.css`: the page. No build step and no Node packages: the
  bare imports (`react`, `@blueprintjs/core`, `@elysium/shell-api/...`) are the page's own
  shared libraries, resolved by Elysium's import map. Elysium serves only this directory.
  Every rule of the stylesheet sits in the `components` layer, as its module API asks.
- The server: `heliograph serve` in add-on mode (`src/heliograph/app/addon.py`). Health is
  `/api/health`, the one path answered without a token. `stopSeconds` is 15 because the
  engine promises to stop within 10.

Tests: `tests/integrations` (the manifest and the page against the engine),
`tests/app/test_addon.py` and `tests/process/test_addon_process.py` (the guard, the settings,
the outbox and the process started as Elysium starts it).
