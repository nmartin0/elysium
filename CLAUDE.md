# CLAUDE.md

Read this first, then `AGENTS.md` and `PRINCIPLES.md`. Those two hold
the rules; this holds how to work, what to read when, and the things
that have gone wrong repeatedly.

## What to read, in order

1. **`AGENTS.md`** — commands, invariants, commit style, what not to
   hand-edit. Non-negotiable.
2. **`PRINCIPLES.md`** — eleven principles, each learned from a real
   failure. Principle 2 (negative controls) is the one that catches
   the most.
3. **`BACKLOG.md`** — the ONE list of what is open. Five files used to
   carry their own and they drifted apart; the entry marked "blocking
   everything below it" had been fixed weeks earlier and no list said
   so.
4. **`UNIFIED_ROADMAP.md`** — START HERE for what to do next. Nine
   planning documents hold ~8,500 lines between them; each is right
   about its own area and none can say what comes first. This one is
   the ordering, by dependency, and points at the others for detail.
5. **`TRIGGERS_AND_PLUGINS.md`** — two features that need designing
   before building, because both touch the security model and both
   are hard to retrofit. Neither is built.
6. **`QUERY_PLAN.md`** — what the Query sub-app should contain, the
   precedent behind each part, and which parts wait for a model.
7. **`LAKE_METADATA_NOTE.md`** — what the data lake should hold
   besides data, and why the ontology is a COPY there rather than a
   home. Corrects an earlier conclusion in BACKLOG.md.
8. **`ELT_ROADMAP.md`** — the data pipeline plan: bronze, silver,
   a materialised MAC column, DuckDB, MinIO. Phased, with the
   measurements behind each phase.
9. **`UI_ROADMAP.md`**, `ROADMAP.md`, `OBJECT_EXPLORER_PLAN.md`,
   `IDEAS.md` — the REASONING, not the backlog. Why a thing was
   decided, rejected or measured, and what a precedent said. Written
   so a fresh session starts with the decisions made, not
   rediscovered. Read these when BACKLOG.md sends you to one.

**The commit log is documentation.** `git log` carries the reasoning
for every decision, including the ones that were reversed and why.
When something looks odd, read the commit that introduced it before
changing it — several times the odd thing was deliberate and the
comment said so.

## You do not push. The workflow is patches.

You have no credentials. The user applies everything.

```
git format-patch origin/dev..HEAD --stdout \
  > /mnt/user-data/outputs/<name>-<date><suffix>.patch
```

Then `present_files` it. Suffixes run `da`, `db`, `dc`… so successive
patches sort and never collide.

**Always dry-run before presenting:**

```
git branch -D vfy -q 2>/dev/null; git checkout -q -B vfy origin/dev
git am <patch> && git checkout -q dev && git branch -D vfy -q
```

**Clear old patches before generating** — `rm -f
/mnt/user-data/outputs/*.patch`. Otherwise the outputs folder holds
several and the user can apply a stale one.

**Give the user the commands, every time.** They should not have to
remember them:

```bash
cd ~/elysium
git checkout dev && git pull
git am ~/Downloads/<the-patch-file>.patch && git push
```

**And say whether the server needs restarting.** A patch touching
`api/` or `core/` needs `uvicorn` restarted; a frontend-only patch
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
and remote had silently diverged.

## The user runs the application. You do not.

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

    cd ~/elysium && python -m scripts.create_e2e_users \
                        --yes-this-is-development      (once)
        Refuses without the flag, deliberately: known passwords are a
        back door. Creates plainuser and adminuser -- TWO, because the
        nav is supposed to show Admin to one and not the other.

    cd ~/elysium && uvicorn api.app:app
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

**CHANGING A FIELD'S `data_type` NEEDS SILVER DROPPED.** Iceberg
refuses an incompatible column change -- "Cannot change column type:
amount: string -> decimal(38, 9)" -- because it is not a widening, and
it is right to.

BRONZE MAKES THE RECOVERY FREE, which is what bronze is for:

    python -c "..."   # drop the silver table
    python -m scripts.run_sync

Silver rebuilds FROM BRONZE, without re-reading the customer's
database. Verified on the live mirror when `amount` became `decimal`
and `transaction_date` became `date`.

The mirror administration surface (UNIFIED_ROADMAP 0.5.4) should offer
this as a button; today it needs a person with a Python prompt.

**Backend changes need `uvicorn` restarted.** Frontend changes do not
— Vite hot-reloads. A new route returning 404 is almost always a stale
server, and this has caused confusion more than once. Say so when a
patch touches Python.

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
uvicorn api.app:app --port 8000     # terminal 1
cd ui && npm run dev                # terminal 2
```

**`/tmp` is cleared on reboot and has eaten their state twice.**
Recovery:

- `scripts/seed_dev_silos.py` — the three silo databases. Without
  these, every silo reads unreachable, which is CORRECT and the Silos
  screen will tell them so.
- `scripts/create_debug_user.py` — `debug` / `a`, role `debug`.
- `scripts/repair_catalog.py` — repoints a catalog whose metadata
  file was lost to a full disk or a power cut. Reports by default;
  repairs with `--write`. Needed because re-syncing CANNOT fix it, and
  deleting the mirror destroys the changelog.
- `scripts/create_e2e_users.py` — `plainuser` and `adminuser`, the
  two the browser tests log in as. Two, because the nav is supposed
  to show Admin to one and not the other.
- `scripts/create_colleague_user.py` — adds `colleague` / `a` in the
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

**Do not run uvicorn with `--reload` while testing writes.** The
pending-write store is in-process memory, so a restart empties it —
and `--reload` restarts on any watched file change, including the
`policy.yaml` edit someone makes to exercise an approvals flow.
Proposals then vanish between steps and look like a bug in the queue.
Configuration needs no restart anyway: `POST /api/admin/reload`
applies it and deliberately preserves pending writes.
It has been suggested and not done; suggest it again if it bites.

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
   python -m pytest tests/integration/test_api.py -q    # if api/ changed
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

7. **Verify each factual claim** the commit message makes, with a
   command, before writing it. This has caught wrong claims about
   parallelism, about enforcement, and about a script that did not
   exist.
8. **Generate the patch, dry-run it, present it**, and say what to
   look at in the browser.

**Numbers in a commit message are measurements, not estimates.** If
it says 548 frontend tests, that number came from a run in that
session.

## Standing requests from the user

Beyond the synopsis, these were asked for explicitly and apply to
every session.

**Research real precedent before inventing a pattern**, and say what
it says. This project models Foundry, so "what does Palantir do here"
is usually answerable and usually changes the design — relative
timestamps, colour limits, the ontology graph's features, and the
Naked Objects precedent all came from looking rather than reasoning
from first principles. `PRINCIPLES.md` §9 is the rule; the practice
is to quote the source in the commit message so the next reader can
weigh it.

**Prefer extending over rewriting.** Inheritance or composition where
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
— the ThreadPoolExecutor is in `api/`, which the grep did not cover.
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

Build order and per-feature designs are in `UI_ROADMAP.md`. Two
things worth carrying that are not features:

**Query is too slow to use**, which means Agent audit — built, tested,
complete — cannot be verified by hand. Items 27 (a wall-clock
deadline) and 29 (measure the loop) would fix that, and **item 33
blocks both**: `LLMAdapter.chat()` has nowhere to put a timeout and
discards the token counts every provider returns.

**Vertex-lite is not entirely frontend**, despite what an earlier
roadmap entry said. `search_around`'s `total` is the count of what it
already fetched, and `count_objects` has no HTTP route — so
count-before-expand has nothing to count with. That endpoint comes
first. The design record in `UI_ROADMAP.md` has the rest.
