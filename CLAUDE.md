# CLAUDE.md

Read this first, then `AGENTS.md` and `docs/principles.md`. Those two hold
the rules; this holds how to work, what to read when, and the things
that have gone wrong repeatedly.

## What to read, in order

1. **`AGENTS.md`** — commands, invariants, commit style, what not to
   hand-edit. Non-negotiable.
2. **`docs/rules.md`** — the working method as generic rules, distilled
   from this file, `AGENTS.md` and `docs/principles.md`. Read it if you
   want the method without the project's specifics.
3. **`docs/principles.md`** — why the design is the way it is, and the
   reasoning behind decisions that look odd from outside.
4. **`docs/roadmap.md`** — **the one planning file, and the only one.**
   It is organised as: section 1, **how to take a card** (the worker
   brief, the card header, the parallel-execution rules, the conventions);
   section 2, the design philosophy, the design rules (DR1-DR7), the
   production-ready checklist (P1-P13) and the security invariants
   (I1-I8); section 3, the **contracts** every card builds on (C-API,
   C-JOBS and the rest, each with an anchor, including the layout, what
   Elysium reads and produces, and the CLI tree); section 4, **Tier 0**,
   seventeen core-wide items (T0.1, T0.1B, T0.2-T0.6, T0.6B, T0.7-T0.15)
   done one at a time in order, each in numbered one-commit steps; section
   5, **task cards** (MEAS, SEC, API, ADM, CLI, OPS, INS, DOC, CI, QA, REF,
   ADD), each with a header block naming its wave, dependencies and the
   files it owns; section 6, the **waves** (one table of card ids per
   wave); section 7, **blocked on the owner** (the exact question and the
   default meanwhile); section 8, pointers to history. Decisions are in
   **`docs/decisions.md`**, cited by id (B1, D4, N23); measured runs,
   consumed lists and the older plan are in
   `docs/archive/planning-history.md`. Anything that could be built and
   has been built lives in the code; the document it came from has been
   deleted. No deployment exists, so nothing is kept for compatibility;
   read `docs/principles.md` section 8 before you touch a format.
5. **`docs/security/audit-checklist.csv`** — one row per verifiable
   claim, with its source, severity, where to look, and a status.
   Sortable, so "did we cover everything?" is a question a command
   answers rather than a memory.
6. **`docs/security/architecture.md`** — the security model as built.
7. **`docs/install.md`** and **`README.md`** — for running it;
   `docs/README.md` indexes every document.

**THERE USED TO BE THIRTY-FIVE MORE.** They were worked to exhaustion
one at a time: every item checked against the CODE rather than taken
at its word, what could be done done, what could not moved to
`docs/roadmap.md` (section 6) with what would unblock it, and everything else worth
keeping moved into the code it describes — a measured fact in a
deleted file is a measured fact lost.

That last step is the one that cost. `SCALABILITY.md` was cited six
times from `src/elysium/core/`, `src/elysium/adapters/` and `tests/`; `HOT_RELOAD_PLAN.md`
from twenty-six places, all of them by STEP NUMBER. A comment saying
"see step 5h" is worth nothing without the document. A comment saying
"snapshot retention must respect pinned generations" is worth
something on its own.

## Working as a swarm worker

If you were given ONE card or ONE Tier 0 step (a card packet, or
`docs/roadmap.md` section 1 with a card), **section 1 of the roadmap is
your whole brief** and it wins over anything below that seems to differ:
you work in your own git worktree `../elysium-wt/<ID>` on branch
`card/<ID>`, commit only there with the trailers it lists, make no patch,
never push, and hand back the branch and the report. The integrator
merges cards, runs the wave's full suite and turns merged waves into
patches with the scripts below (roadmap section 1.3). Everything else in
this file is background for you and the working method for interactive
sessions and the integrator.

## You do not push. The workflow is patches.

You have no credentials. The user applies everything. (A swarm worker
makes no patch; the integrator makes them from merged waves, one patch
per commit, as below.)

```
scripts/make_patch.sh <name>-<date><suffix> <number-of-commits>
```

It clears old patches, refuses a wrong commit count or a dirty tree, and
dry-runs the patch on a throwaway branch from `origin/dev`, printing
`DRYRUN_OK`. Then `SendUserFile` it. Suffixes run `da`, `db`, `dc`...
(next is `dn`) so successive patches sort and never collide. Why a
script: these checks were paragraphs here, and a paragraph gets
skipped (docs/principles.md section 13). The manual form, if the script is
unavailable, is `git format-patch origin/dev..HEAD --stdout`, a
`grep -c '^From '` count and a dry-run `git am` on a branch.

**Bundles, when work piles up across branches.** Elysium's `dev` and
each sub-app's branch (`astrolabe`, `heliograph`) are developed
together, each in its own worktree: `/home/claude/elysium`,
`../elysium-globe`, `../elysium-heliograph`. Only the Elysium lane edits
core; a sub-app that needs something generic files a request in
`docs/roadmap.md` section 6 and waits. If the user has not applied the last patches,
make ONE bundle of everything not yet applied instead of more patches:

```
scripts/make_bundle.sh <name> dev=<dir>:origin/dev astrolabe=<dir>:<base> heliograph=<dir>:<base>
```

Lanes with nothing new are left out; Elysium comes first so a sub-app
change that needs it applies after it. The user runs
`scripts/apply_bundle.sh ~/Downloads/<name>.tar` from their Elysium
clone; it checks every lane's directory first, then applies and pushes
each lane through `apply_patch.sh`. The base for a lane is what the user
has: `origin/<lane>` once pushed, else the commit they were given.
A lane's first-time setup (a worktree, `import_upstream.sh`) is done by
hand once, with the steps in the message that introduces it.

**Give the user the command, every time.** They should not have to
remember it:

```bash
cd ~/elysium && scripts/apply_patch.sh ~/Downloads/<the-patch-file>.patch
```

`scripts/apply_patch.sh` stops at a leftover `.git/rebase-apply`
(which blocked four rounds on 28 October) and proves at the end that
the remote has the commits. Until the user has the script, the plain
form is `git checkout dev && git pull && git am <patch> && git push`
after `git am --abort` if an earlier apply was interrupted. Always
confirm with `git ls-remote origin dev` before believing "pushed".

**And say whether the server needs restarting.** A patch touching
`src/elysium/api/` or `src/elysium/core/` needs `uvicorn` restarted; a frontend-only patch
does not. Saying "restart uvicorn" beside the commands has prevented
several confused 404 reports.

**Then say what to look at.** Which sub-app, which control, what
should be different. A patch delivered without that is one they will
apply and not verify.

### When the dry-run fails

Two different causes, and the fix differs.

**The user's `dev` moved forward.** `git fetch && git rebase
origin/dev`, resolve, regenerate.

**The user already applied an earlier commit**, under a different
hash — this happens constantly, because `git am` rewrites the commit
id. The patch then carries a commit the remote already has, and the
count is one higher than expected. The fix:

```bash
git rebase --onto origin/dev <your-copy-of-the-applied-commit>
```

**Check the commit count on every patch:**

```bash
grep -c '^From ' <patch>
```

If it is not the number you just committed, one of the two above has
happened. Do not present the patch until it is.

**Start every session with `git fetch origin && git reset --hard
origin/dev`.** Three patches went missing in one session because local
and remote had silently diverged. (Interactive sessions and the
integrator only: a swarm worker never resets; its worktree was made for
it from `dev`.)

## The user runs the application. You do not.

This is about the owner's running instance and the checks they make in a
browser. A swarm worker's gate 7 (roadmap section 1.1) is different and
allowed: it starts its OWN temporary server on a free port with its own
state through `tools/with_server.sh`, run under `tools/heavy.sh`, and
stops it; it never starts, stops or uses the owner's server.

They test in a browser and paste what they see. **Those pastes have
caught more real bugs than the test suite has** — a preview panel
covering the graph, a tag running into text (`customer_ididentifier`),
an action node routing to the wrong catalogue, a count badge on the
wrong rows. None of it was visible from here.

So: **say what to look at and where to click.** "Schema → Overview,
click a diamond" beats "the graph now supports actions". And when they
paste output, read it closely — the bug is often in a detail they did
not flag.

**jsdom computes NO LAYOUT, and that is the biggest gap in what this
project can verify.** No stacking contexts, no hit-testing, no cascade
resolution, no idea whether one element covers another. A whole
session went by shipping UI fixes that passed 786 tests and did not
work, every one found by a person clicking.

`ui/e2e/` holds Playwright tests that CAN see those things:

EVERY LINE STARTS FROM THE REPOSITORY ROOT, and says so. A list
mixing `cd ui && ...` with root-relative commands leaves a reader in
the wrong directory -- which it did, producing "No module named
'scripts'" from a step that looked fine.

    cd ~/elysium/ui && npm run e2e:install     (once)
    cd ~/elysium/ui && npm run build           (tests the BUILT bundle)

    cd ~/elysium && python -m elysium.scripts.create_e2e_users \
                        --yes-this-is-development      (once)
        Refuses without the flag, deliberately: known passwords are a
        back door. Creates plainuser, adminuser and opsuser -- several,
        because the nav is supposed to show Admin to one and not the
        other, and the System sub-app only to opsuser. Re-run it when a
        user is added; it replaces the ones it finds.

    cd ~/elysium && uvicorn elysium.api.app:app
        Serves the UI and the API together. LEAVE A RUNNING ONE ALONE:
        static files are read from disk per request, so a fresh build
        is picked up without a restart.

    cd ~/elysium/ui && npm run e2e

NO DEV SERVER. uvicorn serves both, so the only process needed is the
one already running. The config pointed at Vite's :5173 until every
test failed with ERR_CONNECTION_REFUSED on its first run -- a test
nobody can start is a test nobody runs.

DELIBERATELY NOT PART OF `npm test`, which stays fast and mocked. But
a UI change that is about LAYOUT, HIT-TESTING or the CASCADE has not
been verified until these run. If a fix is for something a person
reported seeing, assume jsdom cannot see it either.

**CHANGING A FIELD'S `data_type` NEEDS A REBUILD.** Iceberg refuses an
incompatible column change -- "Cannot change column type: amount: string
-> decimal(38, 9)" -- because it is not a widening, and it is right to.
Bronze makes the rebuild free: `python -m elysium.scripts.run_sync --rebuild
silo.table` rebuilds silver from bronze without re-reading the source
(the Mirror panel's "Rebuild now" does the same). When no deployment
holds data worth keeping, delete the mirror and sync again. The roadmap
turns this into `elysium sync --rebuild`, or removes it if silver becomes
a transient stage.

**Backend changes need `uvicorn` restarted.** Frontend changes do not
— Vite hot-reloads. Say so when a patch touches Python.

THE SYMPTOM IS NOT ALWAYS A 404, which is what made this recur after
the rule was written. A stale server also shows as:

- a new ROUTE returning 404, the obvious one
- a new response FIELD arriving as `undefined`, which the UI renders
  as its own empty state — so the screen looks like a frontend bug, or
  worse, like the feature working and finding nothing

The second cost a diagnosis: a new "last attempt" column read "not
recorded" on a deployment that had recorded attempts perfectly well,
because the endpoint serving it predated the field. The empty state
was correct, the data was correct, and the server was old.

**SO: if a patch touches `src/elysium/api/` or `src/elysium/core/`, the restart goes in the
instructions with the `git am`, not as something to remember
afterwards.**

**AND DO NOT REACH FOR `/openapi.json` TO CHECK WHAT THE SERVER HAS.**
It is DISABLED -- `openapi_url=None`, with `docs_url` and `redoc_url`,
a considered security decision recorded in src/elysium/api/app.py: FastAPI
registers all three on the app itself, outside the protected router,
so an unauthenticated request could browse the full API surface
including every admin route path.

A `curl` to it returns 404 whatever the server is running, which looks
exactly like a stale process. That cost a round trip: the 404 was in
the log and got read as "old code" rather than "wrong URL".

To check what the CODE has:

    python -c "
    from elysium.api.app import app
    import json
    print(json.dumps(app.openapi()).count('some_new_field'))
    "

To check what the RUNNING SERVER has, use the feature.

## Give a synopsis before working

The user asked for this explicitly. Before a run of tool calls, say
what you are about to build and two or three specifics about how. They
are watching tool calls scroll past and cannot tell what you are
doing.

For anything larger than one commit, get agreement on the shape first.
Twice a design was changed after being proposed and before being
built, which was much cheaper than after.

## The development environment

```
export ELYSIUM_CONFIG_DIR=$HOME/elysium/tests/integration/fixtures
export ELYSIUM_DATA_DIR=/tmp/elysium-dev
export ELYSIUM_LOG_DIR=/tmp/elysium-dev/log
uvicorn elysium.api.app:app --port 8000     # terminal 1
cd ui && npm run dev                # terminal 2
```

**`/tmp` is cleared on reboot and has eaten their state twice.** Nothing
under it is state worth keeping (no deployment exists), so rebuilding the
development state is the whole recovery. These scripts do it today, and the
roadmap folds them into `elysium dev reset`:

- `src/elysium/scripts/seed_dev_silos.py` — the three silo databases. Without
  these, every silo reads unreachable, which is CORRECT and the Silos
  screen will tell them so.
- `src/elysium/scripts/create_debug_user.py` — `debug` / `a`, role `debug`.
- `src/elysium/scripts/repair_catalog.py` — repoints a catalog whose metadata
  file was lost to a full disk or a power cut. Reports by default;
  repairs with `--write`. Needed because re-syncing CANNOT fix it, and
  deleting the mirror destroys the changelog.
- `src/elysium/scripts/create_e2e_users.py` — `plainuser`, `adminuser` and
  `opsuser`, the users the browser tests log in as. Several, because
  the nav is supposed to show Admin to one and not the other, and the
  System sub-app (manage:deployment) only to opsuser.
- `src/elysium/scripts/create_colleague_user.py` — adds `colleague` / `a` in the
  same role, for testing that shared things are shared.
**For volume, `seed_dev_silos.py --bulk N`.** Without it the fixture
schemas hold four customers and seven transactions — enough to
exercise every screen, and not enough to exercise paging, the "and N
more" link cutoff, or a chart with many distinct values. A visual
check of paging was literally unaskable until this existed.

`--bulk 60` adds synthetic transactions on customers the `alice`
development user can see, which takes her past the server's default
page size of 50. The default of 0 leaves the databases identical to
what the tests build, which is deliberate: several tests assert exact
counts, and a seeder that quietly added rows would break them in a
file nobody reads while debugging them. If a feature needs volume,
say so
rather than assuming a script exists; one would have to be written.

Pointing `ELYSIUM_DATA_DIR` somewhere under `$HOME` would end this.

Configuration needs no restart at all: `POST /api/admin/reload` applies it.

## The loop, every change

`AGENTS.md` lists the commands. This is the ORDER, and skipping steps
is how the mistakes below happen.

1. **Read the code that already does this.** Three features on the
   roadmap turned out to exist. Read the response model before
   writing a fixture against it, and read the docstring of anything
   being changed — several were load-bearing and said so.
2. **Write it**, with the reasoning in comments where a later reader
   would otherwise wonder.
3. **`npx tsc --noEmit`** — before any test run. It catches shape
   errors in seconds that a test run finds in minutes, and
   `AGENTS.md`'s command list omits it.
4. **Run the narrow test**, then widen: the one file, then the
   package, then everything.
5. **Write the test, then break the code.** For every guarantee
   claimed, mutate the source so it should fail, and confirm it does.
   Restore from a backup copy, never by hand-editing back.
6. **Full verification before the commit message**, not after:

   ```bash
   ./lint.sh
   python -m pytest tests/ -q -m "not integration"
   python -m pytest tests/integration/test_api.py -q    # if src/elysium/api/ changed
   cd ui && npx vitest run && npm run lint
   ```

   `npm run lint` is now all four frontend tools -- oxlint (with
   `--deny-warnings`), tsc, oxfmt, knip -- stopping at the first
   failure, so it no longer needs a second line beside it. If you run
   `npx oxlint` directly it still exits 0 on warnings; read the count.

   One limit worth knowing rather than rediscovering: knip does not
   report unused exports in a file that is a declared entry point in
   its package's `exports` map, because those are public API to it. A
   new unused export in `shell-api/src/format.ts` passes; the same
   export in `app-schema/src/SchemaGraph.tsx` fails.

   **Done means evidence**: the command and its output, quoted. "I
   believe it works" is not done.

7. **Have a fresh reader review the change before the commit.** Start
   a subagent that has not seen the work, give it the diff and the
   agreed design (the `docs/roadmap.md` tier item or card), and tell it to report
   correctness gaps only and to skip style. Check each finding against
   the code yourself; fix the real ones. The author cannot see its own
   blind spots (docs/principles.md section 13). For a swarm card the
   integrator runs this review after the hand-off (roadmap section 1.5).
   Skip it only for a change
   with no behaviour (a typo, a comment) and say that you did.
   **A rule with no exceptions is a script, not a sentence**: if you
   catch yourself adding "always" to this file, write the script or
   hook and a test for it instead.
   **Build from the written design, not from memory.** After a context
   compaction, re-check any claim in the summary against the code
   before relying on it.
8. **Verify each factual claim** the commit message makes, with a
   command, before writing it. This has caught wrong claims about
   parallelism, about enforcement, and about a script that did not
   exist.
9. **Make the patch with `scripts/make_patch.sh`, present it**, and say what to
   look at in the browser. (A swarm worker stops at the commit on its card
   branch and hands back the branch and its report; roadmap section 1.)

**Numbers in a commit message are measurements, not estimates.** If
it says 548 frontend tests, that number came from a run in that
session.

## Standing requests from the user

Beyond the synopsis, these were asked for explicitly and apply to
every session.

**Research real precedent before inventing a pattern**, and say what
it says. This project models a reference ontology platform, the
precedent, so "what does the precedent do here" is usually answerable and usually changes the design — relative
timestamps, colour limits, the ontology graph's features, and the
Naked Objects precedent all came from looking rather than reasoning
from first principles. `docs/principles.md` §9 is the rule; the practice
is to quote the source in the commit message so the next reader can
weigh it.

**Prefer extending over rewriting**, except during the breaking
refactor (docs/archive/planning-history.md section 8.4, "Converge on precedent"), where the replaced code
is deleted in the same change and nothing is kept beside its replacement
as a shim. Outside it: inheritance or composition where
functionality is being added, rather than changing a signature that
four callers depend on. Use judgement: it was the right call for the
shared UI components and the wrong call for the request context,
where a subclass could not carry per-request state safely — and
saying why it was wrong is part of the answer.

**Write scripts for anything they need to verify by hand.**
`create_colleague_user.py` exists because "notes are shared with the
role" was a claim they could not otherwise check. A script that
prints the steps and says what a failure means is worth more than an
assertion in a suite they never see.

**Say plainly when something cannot be tested**, rather than shipping
a test that passes vacuously. Two guards this project are documented
as untested with the reason written where the test would have been.

**Flag when context is running low**, before starting something that
cannot be finished well. They asked for this directly and it was the
right call twice.

## Failure modes that recur

These are not hypothetical. Each happened this project, most of them
more than once.

**A grep is not proof.** "Nothing runs in parallel anywhere" was wrong
— the ThreadPoolExecutor is in `src/elysium/api/`, which the grep did not cover.
"`reads_object_types` is advisory" was wrong — `OntologyAccess`
enforces it, three files from where the search ran. Before writing a
claim into a commit message, check it in the place it would actually
live, and check the negative case too.

**A fixture that does not match the API is a test that proves
nothing.** The graph shipped a white screen with fifteen passing tests
because every one used a hand-written fixture shaped like an array
while the endpoint returns a record. Read the response model. Mock the
API, not the model.

**A test that cannot fail is not a test.** Several got written this
project — an assertion matching `/[A-Z]{2,5}/` that also matched
"Wed", a check that "Customer" appeared somewhere on a panel where
"Affects: Customer" already did. **The control is the only thing that
catches these.** Break the code deliberately; if the test still
passes, it was never testing that.

When a guarantee genuinely cannot be observed — React 18 made
setState-after-unmount silent — **delete the test and write down
why, where the test would have been.**

**Read before assuming something is missing.** Change-over-time was
recorded as blocked; the endpoint existed and nothing called it.
Scenario was recorded as large; the reconciliation already exists.
`health_check` already existed per adapter. The pattern is strong
enough to expect: check first, and the roadmap entry may be wrong.

**Extract at the second caller, not the first.** `ViewSelector`,
`useFetchOnce` and `AsyncPanel` were all extracted when a second real
caller arrived. A grep for a helper's name once suggested nine
callers; counting the actual shape found three, one of which did not
fit.

## Security rules that are load-bearing

`AGENTS.md` has the full list. Three worth repeating because they
shaped decisions this session:

**Uniform denial.** An empty list, never a 403 that distinguishes "not
found" from "not allowed". Applies to notes, traces, history and
search.

**Names, never contents.** `/config` lists silo and role names and
never their connection details or grants. Silos report a failure KIND
(`FileNotFoundError`), never the message, which would carry a path. An
admin could read the YAML anyway — the point is that a UI which never
carries a path cannot leak it through a screenshot.

**Authorization lives in one place.** Ownership of a request trace is
enforced in the reader, not the route, because the reader is what
every caller goes through. Two places deciding one question is how
they drift.

## Where the work stands

`docs/roadmap.md` is where the work stands. Name a Tier 0 item or a card by
its id (T0.7, ADM-14) and a decision by its number (D4, N9) when writing
about it anywhere else; section titles move, ids do not. Two things worth carrying that are not features:

**Query is slow on this hardware**, and the agent-loop work that
measured it is docs/archive/planning-history.md section 8.3 ("Agent-loop efficiency"; Q-MODEL in section 6). What this
paragraph used to say blocked it -- `LLMAdapter.chat()` having nowhere
to put a timeout and discarding token counts -- is no longer true:
`chat()` takes `deadline=` and `usage=` (src/elysium/core/llm/interface.py), and
`src/elysium/scripts/llm_bench.py` is the measurement.

**Graph-lite IS now entirely frontend, and the paragraph that used to
sit here was an example of the failure mode two sections above.** It
said `count_objects` had no HTTP route, so "that endpoint comes
first". It has one: `POST /api/objects/{object_type}/count`, added by
`f042337` with a `CountResponse` model, a typed client at
`api.ts:1129`, and tests at both levels. Verified rather than
remembered — `app.openapi()` carries the path, and the running server
answers 403 rather than 404.

What remains true is the other half: `search_around`'s `total` is
`len(ids)`, the count of what it already fetched, so count-before-
expand must call `/count` separately rather than read `total`. The
clients for both are built and tested and have **zero UI callers** —
`searchAround` and `countObjects` are referenced nowhere outside
`api.ts` and its own test. `docs/roadmap.md` has what survived of the
rest.

**And the lesson is the one already written above: READ BEFORE
ASSUMING SOMETHING IS MISSING.** This file said an endpoint was the
next thing to build for roughly forty patches after it was built.
