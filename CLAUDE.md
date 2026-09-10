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
   cd ui && npx vitest run && npx tsc --noEmit && npm run lint
   ```

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
