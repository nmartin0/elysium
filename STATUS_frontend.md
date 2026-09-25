# STATUS_frontend.md -- LLM4, the front end

Worktree `~/elysium-frontend`, branch `frontend`, based on `dev` at
`f6c5a0b` ("Set up four agents to work at once, safely").

Baseline on arrival, measured rather than assumed: **920 tests in 68
files pass, `npm run lint` exits 0** (oxlint `--deny-warnings`, tsc
`--noEmit`, oxfmt, knip), and `npm run build` succeeds.

---

## Landed

### `f41115a` -- 10-S1-01..04, ui/README.md

The four documentation defects, plus `ui/src/readme.test.ts` as the
guard. Full reasoning is in the commit; the short version is that the
README named 4 of 7 packages, enumerated 4 of shell-api's 23 modules
and 2 of app-browse's 14 components, denied having a design system
while depending on Blueprint, and claimed five checks two lines above
"all four run".

Five negative controls, each failing its own assertion and nothing
else. **The guard caught my own fix**: the correction paragraph first
quoted the phrase it was disowning, and the test cannot tell a claim
from a quotation of one, so the phrase is now banned outright.

Gates after: `npm run lint` exit 0, **924 tests in 69 files**.

---

## Already fixed before I arrived -- three of my four named starting items

Reported because the work list says otherwise, and because
`RULES.md` §1's corollary ("your own notes decay") is the reason to
re-measure rather than build from a note.

**CSS-S3-01 -- FIXED.** The brief says the duplicate-selector test
sees 101 of 148 selectors and no compound selector at all. It no
longer uses a regex: `theme.test.ts`'s `cssRules()` is a brace-walk
that classifies each `{` by what precedes it, tracks enclosing
at-rules as context, and splits selector lists on top-level commas
only. Measured on the current stylesheet with an independent
reimplementation: **201 rule blocks, 59 of them compound.** The file
also carries `it('sees every rule, not a fraction of them')`, which
asserts >200 selectors and requires a compound one, a `bp6-` override
and a media-query rule to be present.

**CSS-S1-01 -- FIXED.** `.app-frame--sidebar-collapsed .app__sidebar`
is defined **once**, at `index.css:1271`. The dead first copy is gone.

**The React plugin -- ON.** `.oxlintrc.json` lists
`"plugins": ["react", "typescript", "unicorn", "oxc"]` with
`react/rules-of-hooks: error` and `react/exhaustive-deps: warn`. Not
taken on trust: `src/lintRules.test.ts` runs the real oxlint binary
with this project's own config over a planted conditional `useState`
and a planted missing dependency, asserts each is reported, and
includes a third case asserting correct code still passes -- so a
linter broken in any way cannot make the first two pass vacuously.
All 3 tests pass.

**The React work that IS open is different, and is a real task.** Two
rules the plugin enables by default are switched `off` in
`.oxlintrc.json`, with `UNIFIED_ROADMAP.md` B0 as the recorded reason:
`react/set-state-in-effect` (**10 sites** -- RolesPanel x2,
WatchDialog x2, ApprovalsPanel, NotificationsPanel, WatchList,
LinkTrail, SavedViews, ExploreRelated) and `react/refs` (**2 sites**,
both in the custom hooks `useFetchOnce` and `useDeferredValue`, and
possibly intentional). Each fix changes a component's behaviour --
derive the state, or reset with a key -- so each needs its own review
and tests. This is the piece of work the brief describes; the plugin
being off is not.

---

## Open, each verified against this base

Measured, not copied from the checklist.

| Item | State |
| --- | --- |
| CSS-S2-01 | **4 dead class selectors** confirmed: `.object-search__controls`, `.object-search__empty`, `.action-form__field`, `.schema-panel__toolbar`. None appears in any `.tsx`/`.ts`/`.html`. |
| CSS-S2-02 | **3 unread custom properties** confirmed: `--border-control`, `--text-on-danger`, `--three-column-min`. |
| CSS-S3-03 | Confirmed and narrowed. Two adjacent comment blocks explain the same dvh/vh reasoning, and the first says "the vh line above" when the `vh` line is *below* it, at `:138`. It is a leftover from when the viewport lock sat on a different element. |
| UI-S2-01 | No `<noscript>` in `ui/index.html`. |
| UI-S2-02 | Confirmed **empirically**, not by reading. Reproduced the real serving path (FastAPI 0.141.1, the same `app.frontend("/", fallback="index.html")` line, against the real `dist/`): a browser's automatic favicon request, with Chrome's actual `Accept: image/avif,...` header, returns **404**. The same path with a navigation `Accept` returns `index.html`, so the fallback discriminates on `Accept` exactly as `api/app.py`'s comment claims. No favicon asset exists anywhere in the repo. |
| F-31 | `ObjectNotes.tsx` has no session-expiry handling at all -- no `handleIfSessionExpired`, no 401 path. |
| F-32 | `api.ts:246`, `body.detail` read off an untyped `response.json()`. |
| E-19 | All three parts verified: log rotation **ships** (`deployment/logrotate/elysium`, installed at `install.sh:166`); an ad-hoc migration mechanism **exists** (`add_column_if_missing`, used by four stores); `user_version` appears **nowhere**, so the narrow true gap is exactly as E-19 states. `UI_ROADMAP.md` is mine to correct. |
| GOLD-3d (display half) | Backend confirmed ready: `quarantined_rows`/`quarantine_reason` at `api/routes.py:2142`, the `/health` quarantine key, `/data-freshness`, `published_at`. UI side untouched -- **zero references to quarantine or `published_at` anywhere in `ui/`**, and `getDataFreshness` appears only in test mocks. Real display work, not wiring. |

---

## Found while measuring, and not in my work list

**A fifth dead CSS rule.** `button.danger` (`index.css:884`) has no
markup: nothing renders a `danger` class, having moved to Blueprint's
`intent="danger"`. The comment at `:732` claims `.danger` "went with"
the removed element rules -- it did not. It drags `--fill-danger` and
`--text-on-danger` with it, which likely collapses two of
CSS-S2-02's three tokens into that one deletion.

**My first dead-class guard was fooled by it**, which is why it is
worth recording: a word-boundary match on `danger` matched
`intent="danger"` in the components. A guard whose match is weaker
than the thing it guards is the same defect as CSS-S3-01, one layer
up.

**`UNIFIED_ROADMAP.md` B4 carries three UI items my brief omits** --
the specificity-stacked Blueprint overrides that can be simplified now
that layers are genuinely in use: `.app__nav.bp6-menu` (`:277`),
`.user-menu__trigger.bp6-button.bp6-minimal` (`:340`), and
`.object-search__results.bp6-card-list > .object-search__result.bp6-card`
(`:930`, the audit's `:959`). All three still present.

**B4 also says the converse token assertion belongs in
`tokens.test.ts`**, not where I had first drafted it. Will follow B4.

---

## CSS-S1-02: the premise no longer holds

The brief says the cascade-layer architecture is declared and never
used -- six of seven layers empty, every rule unlayered -- and that
migration must be one pass or not at all. It also says to re-measure
before acting, which was right.

**Measured against the built CSS, not the source**: `npm run build`,
then a walk over every emitted stylesheet. **Zero unlayered rules in
the entire build.** 2,954 rules in `vendor`, 205 in `components`, 2 in
`tokens`. Four layers are empty -- `base`, `layout`, `utilities`,
`overrides` -- and `layers.css` itself says `overrides` *should* stay
empty.

So the half-migrated cascade the audit feared does not exist. My
recommendation is **not** to migrate further: `utilities` and
`overrides` are documented placeholders, `base`/`layout` content sits
fine in `components`, and inventing rules to fill them is the
speculative code PRINCIPLES §7 forbids. What is worth adding is the
assertion nothing currently makes -- that the build contains no
unlayered rule -- which is the property that actually matters and the
test that would catch a regression. Flagged rather than done, because
it changes a recorded audit finding.

---

## Stopped, not worked around

Nothing yet. No three-attempt loops, no files outside `ui/**` touched.

## Requests

None open. `REQUESTS_frontend.md` not created -- nothing has needed
the backend, security or agentloop agents so far.

## Not checked

**Playwright has not been run.** It needs `npm run e2e:install`,
`create_e2e_users.py` and a live uvicorn on 8001. `CLAUDE.md` is
explicit that jsdom computes no layout, so nothing verified so far
says anything about stacking, hit-testing or the cascade as rendered.
Everything above is node-side measurement of files and one reproduced
HTTP behaviour.
