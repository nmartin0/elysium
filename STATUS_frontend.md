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

## The work list, audited 2026-09-25

Every item below was re-measured on this base (`f6c5a0b`). The two
commits since `2aebe3b` touch no file under `ui/`, confirmed by
`git diff --stat`, so earlier measurements carried over rather than
being re-taken on faith.

The audit merged three items into one, split one into two, moved two
assertions, and deferred two. Net: **thirteen findings, eight
commits.**

### Tier A -- verifiable here, in order

**A1. Dead CSS and the tokens it orphans** (CSS-S2-01, CSS-S2-02, and
`button.danger`) -- ONE commit, because they cannot be separated.
`button.danger` (`index.css:882`) is the ONLY user of `--fill-danger`
(`tokens.css:133`), and `--text-on-danger` sits in the same token
block. Delete the rule and the token is orphaned; delete the token
first and the rule breaks. Touching the same lines twice to keep them
"one change each" would be worse than one coherent deletion.

    5 dead rules    .object-search__controls, .object-search__empty,
                    .action-form__field, .schema-panel__toolbar,
                    button.danger
    3 unread tokens --border-control, --text-on-danger,
                    --three-column-min
    1 orphaned by the above: --fill-danger

THE GUARD MUST MATCH IN CLASS-ATTRIBUTE POSITION, not by word.
Measured: a whole-word search of production source finds **4** of the
5, because `danger` legitimately appears in real code as a Blueprint
intent value (`SchemaPanel.tsx:80` returns `'danger'`). Extracting the
class tokens actually rendered -- from `className=`/`class=`
attributes -- finds **5, with zero false positives** across 156
classes. A guard whose match is weaker than the thing it guards is
CSS-S3-01 one layer up, which is the whole reason this one is worth
getting right.

THE TOKEN ASSERTION GOES IN `tokens.test.ts`, not `theme.test.ts`.
B4 says so and B4 is right: `tokens.test.ts:88` already computes the
`defined` and `used` sets for the FORWARD direction ("every token a
stylesheet references is defined"). The converse is two lines beside
it, and splitting the pair across two files would be the drift both
tests exist to prevent.

**A2. The stale dvh comment** (CSS-S3-03). Separate from A1: a comment
correction is a different change, and doing it after A1 avoids
re-editing the same region. Narrowed from the audit's "a duplicated
comment block": two adjacent blocks explain the same dvh/vh reasoning,
and the first says "the vh line above" when the `vh` line is **below**
it at `:138`. It is a leftover from when the viewport lock sat on a
different element, which the second block states correctly.

**A3. The HTML shell** (UI-S2-01, UI-S2-02) -- one commit, one file,
one finding in two halves. The favicon needs an actual asset; there
are zero SVGs in `ui/` today, so this is a small deliberate choice
rather than a link tag.

**A4. `F-32`** -- `apiFetchOrThrow` reads `body.detail` off an untyped
`response.json()` at `api.ts:246`, against the file's own stated
policy. Shell-api, and everything else depends on it, so it goes
before F-31.

**A5. `F-31`** -- `ObjectNotes.tsx` has no session-expiry handling at
all. Comparator measured rather than assumed: **6 other panels in
`app-browse` call `handleIfSessionExpired`**, so "the only error
handler ignoring session expiry" holds.

**A6. `E-19`** -- correct `UI_ROADMAP.md` items 22 and 25 to the
narrow true statement. All three parts verified against the backend's
code (read-only): rotation ships, ad-hoc migrations exist,
`user_version` appears nowhere.

**A7. `CSS-S1-02`, as a guard rather than a migration.** Recommending
NOT to migrate further -- see the section below -- and instead adding
the assertion nothing currently makes: the built CSS contains no
unlayered rule. That is the property that actually matters and the one
that would catch a regression.

**A8. `B0`, the React rules -- SPLIT IN TWO.** Measured by turning
both rules on and reading the real output: **12 errors across 10 files
in 5 packages**, exactly matching B0's recorded counts (the one note
in this repository that has not decayed). They split on a real
boundary, not an arbitrary one:

    react/refs               2 sites, and BOTH are in the shared hooks
                             useFetchOnce and useDeferredValue, which
                             every package consumes. Highest blast
                             radius, possibly intentional, and it
                             needs a decision before a fix. Its own
                             commit, first and alone.
    react/set-state-in-effect  10 sites, per-component: RolesPanel x2,
                             WatchDialog x2, ApprovalsPanel,
                             NotificationsPanel, WatchList, LinkTrail,
                             SavedViews, ExploreRelated. Each is a
                             behavioural change -- derive the state, or
                             reset with a key -- so each needs its own
                             review and tests.

Ordered last in Tier A because it is the only item that changes
runtime behaviour rather than text, dead code or a guard.

### Tier B -- blocked on a running stack, and honestly so

Neither can be verified here, and `CLAUDE.md` is explicit that
shipping UI fixes which pass jsdom and do not work is a failure this
project has already had.

**B1. The three Blueprint overrides** (UNIFIED_ROADMAP B4, absent from
my brief) -- `.app__nav.bp6-menu` (`:277`),
`.user-menu__trigger.bp6-button.bp6-minimal` (`:340`), and
`.object-search__results.bp6-card-list > .object-search__result.bp6-card`
(`:930`). B4 says the specificity stacking can go now layers are real.
It is **purely a cascade question, which jsdom cannot see at all** --
removing specificity and trusting layer order is exactly the change a
green unit suite would wave through and a browser would catch.

**B2. GOLD-3d, the display half.** Backend confirmed ready. The logic
is jsdom-testable; whether quarantine counts and a publication time
read correctly beside the silo panel is not.

### What blocks Tier B

`npm run e2e` needs a real uvicorn serving the built bundle, plus
`plainuser` and `adminuser` from `scripts/create_e2e_users.py`.
Measured in this container: **`pyiceberg`, `argon2`, `ruamel.yaml` and
`sqlalchemy` are all missing**, so the backend cannot start without
installing the full requirement set. Also worth noting before anyone
tries: `playwright.config.ts` defaults `baseURL` to `:8000`, and my
assigned port is **8001**, so it needs `E2E_BASE_URL` set.

This is environment setup rather than a code change, and it is not
mine to decide how much of the backend's dependency tree to install in
a front-end worktree. Flagging rather than doing.

### Dropped

**The pre-coordination stash**, superseded on three counts: its guard
matched by word and so missed `button.danger`; it put the token
assertion in `theme.test.ts` rather than `tokens.test.ts`; and it did
not delete the fifth rule. Deleting it rather than keeping it, for the
same reason `CLAUDE.md` says to clear old patches -- a stale artefact
that can still be applied is a trap.


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
