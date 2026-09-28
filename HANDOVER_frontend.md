# HANDOVER_frontend.md — LLM4

Branch `frontend`, rebased onto `dev`. Everything below was measured on
this tree, not read from a document; where I could not measure
something I say so rather than leaving it implied.

---

## 1. Finished, and how to verify it

```bash
cd ui && npm ci && npm run lint && npm test && npm run build
```

Expect **lint exit 0** (oxlint `--deny-warnings`, `tsc --noEmit`,
oxfmt, knip), **1008 tests across 74 files**, build exit 0.

> The consolidation note quotes 978 across 73 from the merged tree.
> Both are right: `dev` has 28 of my commits, this branch has 35. The
> difference is the seven rebased on top.

**Read the exit code, not the summary.** A run on the owner's machine
printed `Test Files 71 passed` and looked green while two files never
ran — a jsdom worker died under load. vitest sets a non-zero exit for
unhandled errors (`_checkUnhandledErrors`, confirmed in its source),
so the gate caught it; the summary line did not say so.

### The browser suite

```bash
python -m scripts.seed_dev_silos
python -m scripts.run_sync
python -m scripts.create_e2e_users --yes-this-is-development
python -m scripts.create_debug_user --yes-this-is-development
cd ui && npm run build
python -m uvicorn api.app:app --port 8001      # in another shell
cd ui && npm run e2e:install && E2E_BASE_URL=http://localhost:8001 npm run e2e
```

**16 tests, and they pass twice in a row** — which matters, because
`layout.spec.ts` writes a real saved view and used to leave it behind,
so the second run behaved differently from the first.

### What was delivered

Sixteen audit rows closed or reclassified; GOLD-3d's three
UI-side thirds; B0 and B4; the config identity and history panels; and
guards for the things that had none — dead CSS, unlayered rules,
README drift, session expiry, panel dependencies, the Blueprint
surface, and act() warnings.

---

## 2. Unfinished — what needs a live stack, and what it costs

**Tier B is no longer blocked.** My earlier STATUS said it was; that is
now out of date and this section replaces it. The stack runs here, the
e2e suite runs, and both remaining Tier B items were finished and
verified in a browser.

What IS still blocked is different, and worth stating precisely:

### e2e does not run in CI

`.github/workflows/ci.yml` runs `npm ci`, `npm run lint`, `npm test`
and `npm run build` for `ui/`. It runs **no playwright**. So the 16
browser tests only ever run when a person runs them.

That matters most for **B4**: three Blueprint overrides were simplified
to rely on cascade layer order instead of stacked selectors, and the
three e2e assertions on computed style are the *only* thing protecting
them. jsdom cannot see a cascade.

**To unblock:** the backend CI job already installs the Python lock
file and runs pytest, so seeding, syncing and starting uvicorn is a few
lines. `cdn.playwright.dev` is blocked in MY environment, not on a
GitHub runner. `.github/` is not mine — this is a request.

### The browser I verified in is not the browser anyone ships

`cdn.playwright.dev` is not in this environment's egress allowlist, so
I ran **Chromium 1194 aliased as the 1234** the toolchain expects,
via a symlink tree.

- Colour and `display` assertions: safe across Chrome builds.
- The nine **geometry** assertions (`boundingBox`, "sits beside its
  row", "nothing covers it"): genuinely unverified on a correct build,
  and B4 now leans on them.

The first CI run on a real browser settles it. Until then, a layout
failure should be **investigated**, not assumed to be a regression.

### Eighteen act() warnings, triaged but not fixed

`src/setupTests.ts` fails any NEW act warning from our own components
and carries a per-file list with counts and reasons. Twenty-five
existed; seven are fixed. The eighteen left split two ways:

- **Transient-state tests (4)** — "shows Loading… before listUsers
  resolves" cannot await the thing whose absence it asserts. The fix is
  settling before the test *ends*, not before the assertion. A
  different edit, and lumping it with the others would silently delete
  what those tests check.
- **Not yet read (14)** — probably the same mount-fetch race
  PendingWriteCard had.

### Item 8, the instance graph — four open questions

`searchAround` and `countObjects` now exist as client functions and are
verified against the running server. Nothing else can proceed without
answers to:

1. Where does it live, and what happens to `ExploreRelated`? Two
   screens answering "what is related to this" will diverge.
2. The ceilings, as **numbers**: expand-freely-below, require-a-filter-
   above, total-node hard stop. The entry says "small" and "large".
3. Does graph state belong in the URL? Everything else in Browse is
   URL-driven.
4. **Is layout stability on insert worth a scaffold?** This is the one
   I could not answer. `SchemaGraph` renders **pixel-identically across
   two loads** (measured, same screenshot hash), so deterministic
   seeding works for stability BETWEEN VISITS. Whether adding a node
   disturbs placed ones is unanswered: `echarts` is bundled not global,
   so `page.evaluate` cannot reach it, and it renders to canvas so
   there are no DOM nodes to measure. My hypothesis — supplied `x`/`y`
   are initial positions under `layout: 'force'` and need `fixed: true`
   to pin — is a hypothesis. I did not build on it.

### The UI-KIT migration

Not started, deliberately. `ui/packages/ui-kit` does not exist.

**The plan's central measurement has decayed** and I corrected it in
place: "49 import sites, 22 distinct components" is now **48 sites, 33
components**. Two of the ten additions are worse than widgets —
`Classes` is Blueprint's CSS class constants, `OverlaysProvider` is
app-level infrastructure in `Shell.tsx`. Neither is "a button with a
class name", which is what the whole proposal rests on.

`src/blueprintSurface.test.ts` now pins the set, so it cannot widen
further unnoticed. The migration itself is four steps and the plan is
explicit that the behavioural components are "where a mistake is
invisible until a keyboard user hits it".

---

## 3. Bugs found and not fixed

### The error shape — F-32, and what I would want

`apiFetchOrThrow` read `body.detail` off an untyped `response.json()`.
On a 422 the server returns `detail` as a **list** of objects, so
`ApiError` carried an array as its `message: string` and the screen
showed the literal text `[object Object]`. A login with an empty
username reached that path.

Fixed in the client by narrowing: a string passes through, a validation
list renders as `username: Field required`, anything else falls back to
the generic message. `QueryPanel` got the same treatment.

**What I would ask for, if the contract is ever revisited:** a single
declared error envelope. Today the shape is `{"detail": string}` for 66
`HTTPException` sites and `{"detail": [{msg, loc, type}]}` for
validation, and the client can only discover that by reading the
server. It is not urgent — the narrowing handles both and is tested
against bodies missing every field — but every new client will
rediscover it.

### gold_history was never written — FIXED by the backend

Found by running the pipeline twice. `record_publication` raised
`'NoneType' object is not iterable` on every sync, was swallowed into a
warning, and the sync reported success. I filed it as an observation
rather than a diagnosis; the fix (`f12cd7a`) found the real cause was
worse — the streaming path never materialises rows, so **every
publication after the first recorded no history for every streamed
type**, and no test caught it because a first publication has no
history by definition. It needed a *second* sync to show.

### Quarantine records appear to persist after their cause is removed

Observed, not diagnosed. After removing a constraint and re-syncing,
`quarantined_rows` stayed at 1 for that table. It may be deliberate —
a quarantine record is history — or stale. `core/mirror/` is not mine
and I did not chase it. Reproduce by declaring a constraint, syncing,
removing it, syncing again.

### batch_id is unreadable by any UI

`EditHistoryEntryResponse.batch_id` is unread, and should stay that
way until the server changes. Every write goes through `_apply_batch`
so every entry has one, meaning its presence distinguishes nothing; a
batch spans OBJECTS while Object History shows ONE; and `batch_id`
appears exactly once in `api/routes.py` — as the field. **No endpoint
resolves a batch or filters by it.** A UI needs a server change first.

---

## 4. This week's pipeline changes — what the operator can see

Measured against the running stack, not read.

| change | visible? | what is needed |
| --- | --- | --- |
| Two opt-in text rules producing quarantine | **YES, already** | nothing |
| `unchanged` as a sync outcome | **NO** | small UI change |
| Per-type gold skipping with a named reason | **NO** | server change first |
| A run id on every layer | **NO** | does not exist yet |

**The text rules already work, verified end to end.** I planted a
zero-width space in a customer name, declared
`no_invisible_characters: true` with `on_violation: quarantine`, and
synced: gold published 3 rows instead of 4, and the mirror panel showed
the count and this reason —

> reads as 'Ada Okafor' but holds 1 invisible character(s): a
> zero-width character. A person reviewing this row cannot see them;
> anything reading the text can.

That works because the rules reuse the existing violation policy, as
`constraints.py` says: "this adds a rule and no new machinery." The
quarantine display I built for GOLD-3d surfaces them for free.

**`unchanged` reaches the API and the UI ignores it.** Confirmed by
syncing twice: `last_attempt_outcome` is `'unchanged'`.
`MirrorPanel.tsx:207` branches only on `'refused'`; every other outcome
renders as a plain timestamp. So a table that wrote nothing looks
identical to one that wrote rows — and the file already carries a
comment about an operator being misled by exactly this class of
confusion. **This is the highest-value small UI job left.**

**Gold skipping never reaches the UI.** `core/mirror/gold.py:78` has
`skipped: str | None` with a real reason at `:364` ("resolves identity
across sources, and their rows were not supplied"). `skipped` appears
**nowhere in `api/routes.py`**. A type silently absent from gold is the
"absence reads as loss" problem GOLD-3d exists to solve, one layer up.
Needs the server to expose it — that is a joint item, not a UI one.

**`run_id` does not exist.** Zero occurrences across `core/` and
`api/`. Nothing to show yet.

---

## 5. What I could not check

- **Geometry in a correct browser.** See §2.
- **Whether the pipeline's own behaviour is right.** I verified what
  the UI *shows*; `core/mirror/` is not mine.
- **The 18 remaining act warnings**, beyond classifying them.
- **Layout stability on node insert** — needs a scaffold.
- **Whether each screen I marked "built" is GOOD.** My roadmap audit
  was an existence check: an entry saying "X does not exist" is false
  when X exists, and that is all it asserts. I got that wrong once
  already — I closed item 8 on the strength of `SchemaGraph.tsx`, which
  is item 7. Corrected, but the method was matching names, and the
  other nine were closed the same way.
- **Anything behind `manage:deployment` as a non-debug user.**
  `adminuser` lacks the grant; everything admin-side was verified as
  `debug`.
- **A real multi-user deployment.** Every MAC observation comes from
  one seeded fixture where `debug` sees 2 of 4 customers.

---

## One thing worth carrying forward

The two most valuable findings in this work — the freshness display
rendering **nowhere** because `DataFreshness` declared
`'live' | 'mirror'` while the server sent `"gold"`, and gold history
never being written — were on no list. Both needed the stack
**running**, and one needed it running **twice**.

The e2e suite existed the whole time and went unrun because standing up
a server looked like setup rather than work. The sweep that found the
first (compare every response model field against every line of client
source) is cheap and repeatable, and it is how §4 above was answered
too.
