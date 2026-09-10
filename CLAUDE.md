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
3. **`UI_ROADMAP.md`** — the backlog, the build order, the sub-app
   plan, and per-feature design records. Written so a fresh session
   starts with the decisions made, not rediscovered.
4. `ROADMAP.md`, `OBJECT_EXPLORER_PLAN.md` — architecture and the
   Object Explorer plan.

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

If `git am` fails, the user's `dev` has moved. `git fetch && git
rebase origin/dev`, resolve, regenerate. Check the patch contains the
number of commits you expect — a patch with two commits when you made
one means the user already applied the first.

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
- `scripts/create_colleague_user.py` — adds `colleague` / `a` in the
  same role, for testing that shared things are shared.
There is **no volume seeder**. `seed_dev_silos.py` builds the fixture
schemas, which hold four customers — enough to exercise every screen
and not enough to exercise paging, the "and N more" link cutoff, or a
chart with many distinct values. If a feature needs volume, say so
rather than assuming a script exists; one would have to be written.

Pointing `ELYSIUM_DATA_DIR` somewhere under `$HOME` would end this.
It has been suggested and not done; suggest it again if it bites.

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
