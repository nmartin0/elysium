# Slice 1: Heliograph as a read-only Elysium add-on

Written 2026-11-01 against Elysium `dev` at `348414e0` (its working tree held another
worker's uncommitted changes while this was checked; none touch the add-on files read here).
Decision: D50. Background: [elysium.md](elysium.md).

## What runs

| Part | Where | How it follows Elysium's contract |
| --- | --- | --- |
| Manifest | `integrations/elysium/module.json` | only keys of `core/modules.py` `_MANIFEST_KEYS`; `server` has `command`, `health`, `stopSeconds`; declared permissions `use` and `operate`; module offered to `module:heliograph:use`; `api: ^1.0`; `entry` and `styles` in one directory |
| Server | `src/heliograph/app/addon.py`, `server.py` | `PORT` and `ELYSIUM_ADDON_START` read; `X-Elysium-Identity` verified (HS256, fixed algorithm, issuer, audience, `exp`/`iat` with 5 s leeway, permissions list); loopback only; stdin pipe watched; health unsigned |
| Page | `integrations/elysium/dist/index.js` | lists `GET api/backtests`, shows one `.../report`, by `addonRequest("heliograph", ...)`; bare imports only of the shared libraries and three module-API names |
| Inbox | `Outbox` in `addon.py` | `outbox/backtest-<run id>.json`, written as `.name.part` then renamed; `to: everyone` |

Modes: `ELYSIUM_ADDON_START` set is add-on mode; unset, the engine is as it was. In add-on
mode the data folder is `options.data` or the `dataDir` Elysium gives; the port is
`--port`, then `HELIOGRAPH_PORT`, then `PORT`, then the start file's. `PORT` is ignored
outside add-on mode on purpose. The guard answers 401 without a good token, 403 without
`use` (reads) or `operate` (anything else), and closes WebSockets.

Not done on purpose: the two actions. A manifest cannot declare them (below), so the page is
read-only and the engine's POST routes are reachable only with `operate`.

## How it was checked

- Heliograph's own suite and `scripts/check.sh` (counts in the commit message and the
  hand-off report).
- Tokens: `tests/support/elysium.py` signs as Elysium's `sign_identity` does, and a test
  holds a token Elysium itself produced for a fixed input; the guard accepts it and the
  test signer reproduces it byte for byte.
- Elysium's own loader (`core.modules._load_manifest` and `load_modules`, imported
  read-only) accepts the manifest.
- Elysium's own supervisor (`api.addon_servers._Server`) started `heliograph serve`, got it
  healthy, and `forward()` carried signed requests through: 200 with `use`, 403 without,
  403 for a POST with only `use`, health 200, an unsigned request straight to the port 401,
  a stop with status 0.
- Elysium's own `elysium_addon_checks.AddonContract` (health, identity, loopback, SIGTERM
  stop, stdin close): 5 passed. The file was used from Elysium's checkout, not copied in;
  copying it into this repository is the owner's call (same owner, different licence
  default: ideas, not files).
- The page: rendered with Elysium's React, react-dom and real Blueprint under jsdom, with
  `addonRequest`, the host values and `Page` stubbed: it lists a run, selecting it fetches
  and shows the report, and unmounting leaves nothing running. Found and fixed an infinite
  refetch when the host hands a new `onSessionExpired` on every render.

Not verified: the bundle in a real browser through the real shell and import map; Elysium's
conformance suite (`describeModule`) on the page, which needs its Node toolchain and a
checkout we may not edit; the full Elysium HTTP stack (session, CSRF, `/api/addons/...`
route) rather than its `forward()`; Inbox delivery of a notice by a running Elysium
(`deliver_outbox`), only that the file has the documented shape and name; a name collision of
`/heliograph` with another module.

## Can an add-on declare object types and actions today? No.

1. **Manifest.** `_MANIFEST_KEYS` is `id name version permission contributes entry styles
   activationEvents server permissions api`, and unknown keys are refused. `contributes`
   takes `pages nav redirects slots into`. There is no way to contribute an object type, a
   link type, an action type, a silo or a trigger.
2. **Where those live.** Object types, links and action types are in the deployment's
   `ontology_schema.yaml`; silos in `data_silos.yaml`; both are loaded by
   `core/deployment_loader.py` and checked together at load. The adapters a silo may use are
   two hard-coded dicts (`_READ_ADAPTER_REGISTRY`: sqlite, sqlalchemy, csv_folder, rest ...;
   `_WRITE_ADAPTER_REGISTRY`: sqlite only), "exactly the place a future entry-points
   mechanism would replace".
3. **How a source creates objects today.** It does not push. Elysium mirrors rows from a
   declared silo (bronze, silver, gold), read-only except through actions. What Heliograph
   can do now is publish a SQLite file with Signal, Account and Position tables, written
   to a new file and renamed, and the deployment declares it as a silo plus types over it
   (the "optional published-records sink" of D20, still unbuilt). Nothing in the add-on
   server API creates, updates or retracts an object.
4. **How actions are defined and submitted.** `action_types:` in `ontology_schema.yaml`:
   `affected_object_types`, typed `parameters` (`object_reference` names an object by id),
   and `sub_writes` (`create`, `update`, `delete`, each with `mutations`). A mutation value is
   a literal, `parameter.<name>` or `user.security_value`; `user.user_id` is available only in
   submission criteria (four-eyes), not as a value written. A person submits with
   `POST /actions/{name}` (`origin: human`; the agent's path says `agent`), which only
   proposes: a pending write, then `POST /writes/{id}/confirm` applies it, after RBAC
   (`execute:`), per-object MAC and submission criteria. The write goes through the write
   log (log first, then apply to the silo, crash-resumable) and the audit log records who
   proposed and who approved, with `origin`. That is the "Elysium owns approval, audit and
   who decided" the owner wants, and it exists.
5. **What an add-on cannot learn.** When an action on a Heliograph-owned object is applied,
   nothing tells the add-on. There is no callback, subscription or spool toward the add-on
   (timer callbacks and WebSocket pass-through are listed in BLOCKING.md as waiting). The
   Inbox outbox goes only one way and carries text, not objects.

## Design note: how the settled decisions would sit on that

- **Signal**: an Elysium object type, id = Heliograph's signal id (strategy, instrument,
  decision time), fields: strategy, instrument, side, strength, price, valid-until, status
  (`open`, `took`, `skipped`, `expired`), run id, journal pointer. Heliograph is its only
  creator; its journal stays the record for replay.
- **Account, Position**: object types holding current state, written by Heliograph
  (upserted at low rate); the per-run SQLite journal and equity history stay here.
- **Decision**: either fields on Signal set by the action (`status`, `decided_at`), or a
  `Decision` object created by the action with `signal` as a link. The second keeps "who
  decided" out of Heliograph's writable fields, if Elysium cannot stamp the user (ask 5).
- **Actions**: `TookSignal(signal)` and `SkippedSignal(signal)`, `sub_writes` update on Signal
  `status`, with a submission criterion that refuses a signal no longer open, and four-eyes
  off (single user).
- **Market data access (decision 3)**: the bars stay in Parquet. Elysium would hold a
  `Dataset` object per store snapshot with the licence terms as fields; "open this
  dataset" would be an action or a checked read whose audit entry is Elysium's. Not
  investigated beyond noting that no mechanism exists for an add-on to register such a gate.
- **Journal and replay**: unchanged. Elysium's object is current state; replay reads the
  journal.

## Asks of the Elysium lane (concrete, in the order Heliograph needs them)

1. **A module may contribute ontology.** Allow a manifest key (for example `ontology`, a path
   to a YAML fragment inside the module's folder) holding object types, link types and
   action types, namespaced by module id and merged at load with the same cross-checks;
   removed when the module is turned off. Today these are deployment files only.
2. **A way for an add-on to put objects in.** Either an outbox-style spool like the Inbox's
   (`objects/<type>/<id>.json`, upsert, an idempotency key in the name, an `as-of` time and a
   retract marker) or an authenticated route the add-on's start file gives it. Without it the
   only path is a published SQLite silo plus deployment-owned types.
3. **A way to tell the add-on an action ran.** After a confirmed write on a type the module
   owns, deliver the executed action (type, parameters, acting user, approver, time, write
   id) to the add-on: a spool in the other direction (`actions/<write id>.json`), or a
   signed call to the add-on's server with an idempotency key. Heliograph must learn "took
   it" without polling a silo.
4. **A write adapter that is not Elysium's SQLite.** `_WRITE_ADAPTER_REGISTRY` has `sqlite`
   only; if the objects live in a Heliograph-written file, two writers share it and a
   republish would drop Elysium's writes. Elysium-owned storage for module objects (ask 2's
   target) avoids the problem.
5. **Stamp the acting user.** Allow `user.user_id` (and the approver) as a mutation value so
   `decided_by` can be a field of the object, not only an audit entry.
6. **Single-step execution for low-risk actions.** `POST /actions/...` then `/writes/{id}/
   confirm` is two calls and an Approvals item. For a single-user "took it", an action
   declared `confirmation: none` (audit still written, `origin: human`) would make it one
   click; the audit trail is the reason Elysium owns it, so it must stay.
7. **Dataset access as data.** A way for a module to declare a gated resource (a dataset id,
   licence terms as fields) and ask Elysium "may this person open it", with the answer
   audited. Needed for decision 3.
8. **Time series later**, as the owner said; until then Heliograph publishes low-rate
   current-state records only.

Smaller things seen on the way: the bundle's declared `api: ^1.0` is satisfied (page offers
1.1); the Inbox notice is plain text with a 200-character summary, so a notice cannot carry a
"took it / skipped" button, which is a reason for ask 1 and 6 (the action, not the notice,
is the interface); health is polled without a token, so an add-on's health path must stay
unauthenticated and must reveal nothing (Heliograph's returns version, time and the id of the
run in progress).
