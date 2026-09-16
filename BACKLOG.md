# Backlog

**The one list.** Everything open, gathered from ROADMAP.md,
UI_ROADMAP.md, IDEAS.md, OBJECT_EXPLORER_PLAN.md and
HOT_RELOAD_PLAN.md, which had accumulated separate lists that drifted
apart.

Those files keep their REASONING -- why a thing was rejected, what
Foundry does, what a measurement showed -- because it has been needed
repeatedly. What they no longer keep is a list of what to do next.
That is here.

**Before starting anything below, check the premise.** Over one long
session, five of eight items checked turned out already done or
overstated, and two "enhancements" were live defects. Counting the call
sites takes one grep; a sentence with no number in it is an estimate
wearing the clothes of a finding.

---

## 0. Found by using the UI, September 15

Raised after a session exploring the running product. Ordered by
whether the thing is BROKEN, merely WRONG, or a DESIGN QUESTION --
because those want different amounts of care and the list should not
pretend otherwise.

### Broken: fix first

**~~Select-all leaves every checkbox unticked.~~ FIXED.** The root
cause was wider than select-all: the same object had a STRING id on
one endpoint and an INTEGER on another, because ObjectDetailResponse
declares `id: str` and FastAPI coerces it while SearchResponse
declares `results: list[dict[str, Any]]` and passes the raw value
through. Search now stringifies at the boundary, where the rest of the
API already said it did.

Nobody noticed because Customer ids are already strings, so every
manual check on the type people reach for first agreed.

**Original report, for the record:** CONFIRMED, and mine.
`/objects/{type}/search` returns `"id": 1` -- an integer for
Transaction -- while `/objects/{type}/matching-ids` returns
`str(object_id)`. So after "Select all 64 matching" the selection set
holds `"1"` and each checkbox asks `has(1)`: the bar says 64 selected
and not one row looks it, so there is nothing to untick.

The tests missed it because they used string ids on both sides. The
fix is to agree on one representation at the boundary and test the
DISAGREEMENT, not the agreement.

**~~Checkboxes sit above their rows~~ FIXED in Browse, and the sweep
found only one instance.** The card is `display: block` deliberately --
Blueprint's CardList gives a direct child Card
`display: flex; align-items: center`, which laid the card's
multi-line content side-by-side instead of stacked -- so the fix is a
flex ROW INSIDE the card rather than flexing the card.

SEARCHED THE WHOLE UI: exactly two Checkbox elements exist, and the
other (the Columns filter) uses Blueprint's own `label` prop and
renders correctly. So either the report was about the Browse one
specifically, or it is about a control I have not recognised as the
same problem.

STILL OPEN: which OTHER screens show it. Worth naming them, because a
sweep for "<Checkbox" found nothing further and I would be guessing at
what else counts.

### Wrong: small, visible, decided

**~~Charts draw a slice per row for identifier-like fields.~~ FIXED**,
as the mirror of the guard that already existed. A distribution needs
FEWER groups than objects and MORE than one -- both failures are the
same mistake from opposite ends, so they are now one function.

Not a ratio or a threshold: "drop it if more than 80% of values are
unique" would need a number nobody can justify and would hide a real
distribution that happened to be sparse.

**Original report:** Browse ->
Customer -> Charts plots `name`, which is unique per customer and
conveys nothing. There is ALREADY a guard for the opposite case -- a
field where every object shares one value is dropped, because "one bar
is not a distribution" -- and this is its mirror: a field whose
distinct count equals its row count is an IDENTIFIER, not a category.

Made worse by the fixture declaring no `prominent` fields, so the
chooser falls back to every non-hidden field.

**~~"All 1 silos are reachable."~~ FIXED**, and the guess that other
count strings had the same problem was right: three did. A shared
`pluralise()` helper now takes the plural rather than deriving it,
because English plurals are irregular and appending "s" would be wrong
often enough to be worse than the bug.

The silos string needed the VERB to agree too, not just the noun, so
it reads "The one silo is reachable" rather than "All 1 silo is".

### Redundant: a modelling decision

**~~RecategorizeTransaction and RecategorizeTransactions differ by one
parameter type.~~ MERGED.** One action taking a list, with
`default_to_current_object` on the list parameter so a detail page
contributes a list of one.

What made it possible rather than merely tidy: the write mediator
expands a list into one sub-write per object, so a list of one and a
single reference produce the SAME write. Verified both paths against
the real deployment -- one object gives one sub-write, four give four.

**Original report:** Foundry keeps single and bulk action types separate
because a "bulk action type" is one "using an object reference list
parameter" -- but that is a MODELLING constraint, not a user-facing
one, and shipping both to a person is redundancy they have to think
about.

Proposed: ONE action taking a list, with the single-object form
sending a list of one. `object_reference` becomes an optimisation for
detail pages rather than a separate action.

### ~~Missing: shift-click range selection~~ DONE

Anchor-based, in its own module so the rules are testable apart from
the panel. Both documented pitfalls avoided deliberately: the anchor
clears when the selection empties (Sentry's ghost-anchor bug), and the
anchor is an ID with the range computed over the DISPLAYED order,
because this list is sorted, filtered and paged and an index would
break under all three.

An anchor that has left the page falls back to a plain toggle, which
is the honest answer -- there is no defensible range between a row you
can see and one you cannot.

**Original report:**

**Anchor-based, which is the established pattern**: the first clicked
row is the anchor; Shift and a second click set every row between them
to the second row's state; the second click becomes the new anchor.

TWO DOCUMENTED PITFALLS, both worth stealing the fix for:

- A STALE ANCHOR. Sentry shipped a bug where deselecting everything
  left the anchor on a ghost row, so the next shift-click extended
  from nowhere. Their fix: clear the anchor when the selection empties.
- INDICES VERSUS IDENTITY. An Angular thread is explicit that `$index`
  breaks under sorting, filtering and paging -- and OUR LIST IS ALL
  THREE. The range must be computed over the currently displayed
  order, never a stored index.

### Needs research before building

**Query is barren.** The one item here that is a design question
rather than a defect. Deserves the treatment the ELT work got:
precedent first, then a plan, then build.

**~~Is the deployment-specific UI actually portable?~~ YES, and now
proved.** A second fixture deployment sharing NO noun with the first --
vessels and port calls, a security attribute called `fleet` rather
than `region`, a role called `fleet_ops` -- plus thirteen tests
asserting the derived surfaces follow it.

Everything passed first time, which is the answer: nothing hardcodes
our ontology's nouns. Controls confirm the tests would CATCH
hardcoding, which matters more than the passes.

The linter taught me two ontology rules while building the fixture,
which is itself evidence they are enforced rather than conventional:
security.via_field must name a LINK, and `write:` is not a real grant
prefix.

**Original question:** Filters and
columns are supposed to derive from `visibleSchema`, so a different
ontology should reshape them with no code change. UNVERIFIED -- and
"mostly right" is not an answer.

The honest test is a SECOND deployment fixture with different object
types and field names, and assertions that the UI follows it. The same
shape as the calibration probes, which exist because this class of
drift is invisible until someone loads a different deployment.

**A plugin API, server and client.** The largest item here and
probably its own design session. The shape: third-party sub-apps and
server-side compute that load INTO Elysium without modifying it, so a
vanilla install can become something domain-specific -- the worked
example being a quantitative trading analysis engine -- while base
Elysium stays untouched and upgradeable.

Both halves have strong precedent and neither should be improvised.

### Visual sweep, not yet run

Everything below was built and unit-tested but has not been seen
working. Each step builds on the last:

1. `python -m scripts.seed_dev_silos --force --bulk 60`
2. Restart `uvicorn` WITHOUT `--reload` -- the pending-write store is
   in-process memory, so a reload empties it mid-test and proposals
   vanish between steps looking like a queue bug.
3. Browse -> Transaction: fixed precision, checkboxes, the selection
   bar, "Select all 64 matching".
4. Actions (64) -> RecategorizeTransactions: propose it.
5. Approvals: confirm it lists all 64.
6. Admin -> Metrics: the five figures, the saturation callout, the
   slowest-routes table.

Step 6 last on purpose: by then there is enough traffic for the
numbers to be non-trivial.

## 0b. Open, as of September 15 -- the consolidated picture

Everything genuinely outstanding, in one place, because the list had
grown long enough that things were being lost in it.

### Can I do it alone, right now

**Make the test suites NAME their failures.** Three unexplained single
-test failures so far -- two frontend, one backend -- none
reproducible, none named. The summary line the retry erases is what
has defeated every attempt to chase them.

`--reporter=verbose` for vitest and `-p no:randomly` for pytest both
name tests as they run. Worth wiring into the default invocation
rather than remembering to add. Small, unglamorous, and the most
valuable thing left that needs nothing from anyone -- because the next
REAL intermittent failure will be read as this one.

**Which other screens show the checkbox-above-the-row problem.** The
sweep found exactly two Checkbox elements and the other renders
correctly, so either the report was about Browse specifically or it is
a control I have not recognised as the same problem.

### Needs research, then a plan, then building

**What Query should contain.** Barren today. The one item that is a
design question rather than a defect, and it deserves the treatment the
ELT work got.

**A plugin API, server and client.** The largest item here and
probably its own session. Third-party sub-apps and server-side compute
that load INTO Elysium without modifying it, so a vanilla install can
become something domain-specific -- the worked example being a
quantitative trading engine -- while base Elysium stays upgradeable.

### Needs a decision from a person

**Per-task approval eligibility.** Foundry scopes a reviewer's action
to the tasks they can review; we approve whole requests.

**Host metrics correlated with hops.** Explicitly not a resource
dashboard. What is worth showing has never been settled.

**The keyboard model's roving-focus half.** GATED rather than
unstarted: the recorded condition is that "nobody has established who
uses Elysium daily", and the precedent sharpens it -- our results are
cards with links, not a grid, so `role="grid"` without the full
keyboard contract would be worse than native semantics.

### Needs a machine with a model

**The prompt-quality measurement session.** Four questions, one
harness, about an hour. Still the highest-value item and the only one
that cannot be done here at all.

### Deferred with the trigger named

**Sync memory batching** -- when a deployment has a table big enough.
Measured at roughly 1.2 KB peak per row.

**The ELT changelog's later phases** -- a current view reading through
the changelog, and a REST catalog if a table outgrows memory.

**Partitioning** -- at a few hundred megabytes of Parquet, which is
roughly a hundred million rows at our widths.

## 0c. Data integrity, and surviving a teardown

Raised September 15. Two related questions, and the second has a
subtlety worth separating out before anyone builds.

### The requirement

Tear Elysium down, preserve the data lake, stand a fresh Elysium up on
top of it, and continue running. Nothing lost that matters.

**THIS IS NOT YET TRUE, and the gap is knowable rather than
mysterious.** What lives in the lake today: bronze, silver, the
changelog, and their Iceberg metadata. What lives OUTSIDE it and would
not survive: `deployment/etc` (the ontology, the policy, the silos,
the LLM settings), `write_log.db`, `credentials.db`,
`config_history.db`, `secrets/`, and `metrics.db`.

A fresh install on a preserved lake would come up with data and no
idea what any of it means.

### Is it idiomatic to put Elysium's metadata in the lake?

**PARTLY, AND THE SPLIT IS THE INTERESTING PART.** The industry
distinction is between a CONTROL PLANE and a DATA PLANE, and the
catalog is the control plane: "the catalog must be the control plane
where security and data quality rules are defined and enforced.
Access control policies should be linked directly to tables, views, or
columns within the catalog itself."

By that standard, some of our config belongs there and some does not:

**BELONGS (it describes the data):**
- `ontology_schema.yaml` -- this IS table metadata. Types, fields,
  links, security declarations. The catalog's own job.
- `data_silos.yaml` -- where each table came from. That is lineage,
  and lineage is canonically catalog-resident.
- `policy.yaml` -- access control, which the guidance puts explicitly
  in the catalog.

**DOES NOT (it describes the application):**
- `config.yaml`'s LLM block -- a model name and a timeout say nothing
  about the data. A second Elysium on the same lake might reasonably
  use a different model.
- `credentials.db` and `secrets/` -- secrets belong in a secret store,
  never in a data lake, and putting them there would make every reader
  of the lake a reader of the credentials.
- `write_log.db` -- transactional state, not description.
- `metrics.db` -- describes the SERVER, not the data. Already
  documented as safe to lose.

**THE GUIDANCE TREATS THESE AS THREE THINGS, not two**: "regularly
backup data, metadata, and configuration settings". So the answer is
not "put everything in the lake" but "put the metadata in the lake,
and have a deliberate story for configuration and secrets".

And the metastore point is the one that makes this urgent: "the data
in a Hive Metastore is just as significant as the data in the data
lake and must be treated as such... its metadata must be kept
permanent, highly accessible, and included in any disaster recovery
configuration." Our catalog is a SQLite file beside the warehouse. If
it is lost, the lake is a directory of Parquet nobody can interpret.

### What would need doing

1. ~~**An integrity check that can be run.**~~ DONE:
   `python -m scripts.check_mirror`. Checks that every silver table has
   a bronze counterpart, that their row counts agree, that every
   declared field has a column, and that the catalog lists every table
   the warehouse holds on disk.

   RUNS WITHOUT AN ONTOLOGY, which is the case it exists for: a lake
   preserved through a teardown, inspected before a new Elysium is
   configured on it. Structural checks still run; ontology-aware ones
   are skipped rather than guessed at.

   STILL UNCHECKED: whether every changelog entry names an object that
   existed. The changelog is append-only history whose row count
   deliberately matches nothing, so it needs its own reasoning rather
   than an extension of these rules.

2. **Decide what the lake holds**, along the split above.

3. ~~**A teardown-and-rebuild test.**~~ DONE, and THE ANSWER IS NO.

   **THE LAKE IS NOT PORTABLE.** An Iceberg lake written by
   pyiceberg's SqlCatalog bakes absolute paths in at three depths: the
   catalog row's metadata_location, the metadata JSON's own `location`
   and every `manifest-list`, and the manifests' references to their
   data files. Copy it anywhere and every read fails with
   FileNotFoundError naming a directory that no longer exists.

   Verified at each depth rather than inferred from the first --
   rewriting the catalog alone leaves three tests failing, and
   rewriting the JSON as well STILL fails, because the manifests are
   Avro and hold their own.

   So the fix cannot be a path-rewriting migration bolted on
   afterwards. It is either RELATIVE LOCATIONS AT WRITE TIME, or a
   CATALOG REBUILT FROM THE WAREHOUSE on load. That is its own piece
   of work and the next thing to do here.

   The tests assert the FAILURE, so fixing it turns them red rather
   than letting the fix land unnoticed.

   What DOES survive, checked in place: the data, bronze, the
   changelog, and provenance stamped on each table. What does not: the
   write log, credentials, config history, metrics -- and the ontology,
   policy and silos, which by the control-plane standard belong in the
   lake and are not there.

4. **Name what deliberately does NOT survive**, because a rebuild that
   silently loses the write log is worse than one that refuses to
   start. `config_history.db` already records which configurations
   have run -- a first step toward this that predates the question.

## 1. Needs a machine with a model

**The prompt-quality measurement session.** Four questions sharing one
harness -- one-shot calls against the real prompt, varying one thing at
a time. About an hour of machine time answers all four:

- Does the agent over-fetch, and would a different example change it?
- Are aggregates chosen when they should be?
- Do the pre-flight action verdicts earn their keep?
- Can a small model work without the schema in the prompt?

ITERATE rather than testing three hand-written prompts; see IDEAS.md's
2026 research entry. Unblocked since aggregate_object became reachable
-- three of the four would have measured the wrong thing while the
parser silently converted those steps into a finish.

Three shipped commits point at this and deliberately do not prejudge
it: the step-prompt examples were made placeholders (nouns only,
structure untouched), and both aggregate entries depend on its
findings.

---

## 2. Product work, buildable here

**Saved Explorations. DONE for Browse**, as a URL plus a name in
per-user browser storage. PERSONAL, NOT SHARED, and the URL work is
why: sharing a view is already solved by sending the link, so what
this answers is "the thing I set up on Tuesday, where did it go".
No permission model, no server store, no ownership rules.

STILL OPEN, and a genuinely different thing: saved SELECTIONS. A set
of chosen OBJECTS rather than a question, and what bulk actions would
operate on. The UI must not conflate the two.

Shared explorations, if ever wanted, are a separate feature with a
permission model rather than a flag on this one.

**Vertex-lite: a read-only link explorer. FIRST HALF DONE.**
link_counts() and its route answer how far each link leads BEFORE
anything expands, and an "Related" section on the object detail page
shows them, each linking through to a filtered Browse view.

ONE HOP AT A TIME, deliberately: no canvas, no layout, no automatic
multi-hop expansion. Those are the "full Vertex" item, and reaching
them by accident is how a read-only explorer becomes something nobody
can reason about on a real ontology.

STILL OPEN: following a link should arguably keep the trail visible --
"Customer cust_001 > its 47 Transactions" -- rather than landing in
Browse with a filter applied and no memory of how you got there. That
is a navigation question worth answering before adding more hops.

**Bulk actions. THE MECHANISM IS DONE**; the UI is not.

`object_reference_list` is a parameter type, and a sub_write whose
object_id resolves to a list expands into one sub-write per object --
each getting its own authorization check, its own submission criteria
and its own place in the ATOMIC batch. Forty objects means forty writes
that all succeed or all fail.

Foundry draws the line identically: a "bulk action type" is one "using
an object reference list parameter". Bulk is a property of the ACTION,
declared and reviewable before anyone runs it, rather than a mode an
application switches into.

STILL OPEN, all of it UI:
- ~~Checkboxes on the results table~~ DONE, with a selection bar that
  states what an action would apply to. The checkbox needs its own
  stacking context: the stretched link covers the whole card, so one
  painted underneath would be visible, unclickable, and would navigate
  instead of selecting. UNTESTABLE IN JSDOM -- no layout is computed,
  so a control removing the z-index broke nothing. Wants a real browser.
- ~~The Actions menu itself~~ DONE, plus a bulk form. The menu offers
  only actions with an object_reference_list parameter of the CURRENT
  object type -- Foundry's rule that "only actions that accept object
  list parameters of the correct type will be shown". Absent rather
  than disabled when nothing qualifies.
- RecategorizeTransactions is declared in the shipped ontology, so the
  path is exercised by a real deployment rather than only by tests.
- ~~"No selection means the whole filtered set"~~ DONE, resolved in the
  panel so the rule lives in one place. Foundry's
  rule: the current set "or all objects, if none are selected".
- ~~Select-all across pages~~ DONE, and the precedent reshaped it.
  Foundry's approvals model settles the design: "a task is an
  individual change in Foundry. All tasks associated with a request
  must be approved for the request to be invoked." A reviewer approves
  SPECIFIC CHANGES, never a rule resolved later -- so the filter is
  resolved at SELECTION time by a server endpoint returning ids, and
  what travels onward is the list. No change to the action contract.

  An explicit "Select all N matching" button rather than an overloaded
  header checkbox, because a checkbox that sometimes means the page
  and sometimes the filter has a meaning nobody can see.

  ~~Old framing, kept because the reasoning still holds for anyone who
  revisits it:~~ Select-all across pages means the FILTER, not the page.
  and now stated honestly rather than falsely: the bar promises "the N
  shown" and says how many more match, because the panel holds one
  PAGE and an action with no selection reaches only that. Foundry's
  select-all "selects all objects matching the applied filters, not
  just the objects on the current page" -- honouring that needs the
  SERVER to accept a filter instead of an id list, which is a real
  change to the action contract.
- ~~A ceiling.~~ DONE: MAX_BULK_OBJECTS is 1000, matching Foundry,
  refused at PROPOSE time so nobody assembles a selection they will
  not be allowed to act on.
- No shipped action declares a list parameter yet, so the path is
  exercised only by tests.

**Per-task approval eligibility.** Foundry scopes a reviewer's action
to the tasks they are eligible for; we approve a whole batch
atomically. Ours is defensible -- partial application of a
multi-object write is a correctness problem -- so these want
reconciling rather than one replacing the other.

---

## 3. UI, none of it urgent

**Fixed precision for numbers. DONE**, and the Foundry precedent
decided it: value formatting is PROPERTY metadata, transforming raw
values "into more readable versions in user applications". So
`decimal_places` sits beside `visibility` and `status` on a field --
all three are things an ontology author knows and an application
cannot infer.

Display only. The stored value, what an action writes, and what a
filter compares against are untouched.

DELIBERATELY NOT BUILT: a format STRING. "%.2f" carries padding,
thousands separators, currency symbols and locale assumptions, and
every one of those is a decision this project has not made. Foundry
separates four concerns -- value formatting, render hints, type
classes and conditional formatting -- and only the first is in scope.

**The keyboard model's roving-focus half. GATED, not merely
unstarted.** I described this as "the accessibility work nobody has
touched" and that was wrong. UI_ROADMAP.md is explicit: the FOCUS-RING
half is the accessibility floor and is unconditional -- it is done,
using :focus-visible so a mouse click leaves no ring. Roving focus is
a POWER-USER feature, and the recorded gate is that "nobody has
established who uses Elysium daily".

That gate has not been met, so building it would be guessing at a user
who may not exist. It wants an answer about usage, not a decision about
scope.

**URL-as-state. DONE for Browse**, which is where a view has parts
worth sharing: the object type, the search, the sort, the chart
filters and the tab. Column choices deliberately stayed a preference.

THIS SHRINKS SAVED EXPLORATIONS considerably. An exploration IS that
URL, so persisting one is storing a string and a name rather than
designing a schema for view state.

**The view-state matrix's other half.** The two empty states shipped,
and LOADING is now one shared component -- three treatments across six
panels, none of which announced to a screen reader. ERROR is now one shared
component too -- the TREATMENT was already consistent across ten
panels, but none of them ANNOUNCED: a danger Callout sets no ARIA
role, so every failure was silent to a screen reader.

PARTIAL IS DONE where it actually occurred: the charts tab loaded six
aggregates with Promise.all, so one failing column replaced every chart
with an error. It now draws what worked and NAMES what did not -- a
quiet partial would be a wrong answer reporting success.

The view-state matrix is complete. No other panel loads more than one
thing at a time, checked rather than assumed, so there is nowhere else
for a partial state to arise today.

---

## 4. Observability

**Calibration probes** -- what else can drift the way the step
vocabulary did, caught by construction rather than by noticing.

FIRST ONE DONE: filter operators, declared in core/filters.py and
handled separately by each adapter. They are ALLOWED to differ --
UnsupportedFilter lets an adapter decline and the mediator then
evaluates in Python -- but an operator that falls off the end of a
clause builder without raising produces a query missing its condition.

SECOND ONE DONE: the sub-app list, declared in five places -- the
package on disk, ui/package.json's dependencies, App.tsx's route, the
rail's VISIBLE_APPS, and appIcons.ts. The dependency check is the one
with a demonstrated failure behind it: the approvals sub-app shipped
with every check passing and rendered a blank page, because the
workspaces glob satisfies the build and the tests while only a real
install needs the explicit dependency.

THIRD ONE DONE: grant verbs, compared both ways between
policy_validation.py and every authorize() call site. A verb the code
asks for and the validator rejects makes a feature unreachable; a verb
the validator accepts and nothing asks for is dead vocabulary a
deployment can write and be approved for. authorize() is a bare
set-membership test, so neither produces an error -- it just never
matches.

FOURTH ONE DONE: field data types, compared across coerce(), the
Arrow mapping and the filter operators' type restrictions. ADDING a
type is the risk rather than removing one -- a fifth entry would pass
every existing test and raise "Unknown field data_type" only when a
real sync first touched a real row.

THE SURFACES OF THIS SHAPE ARE NOW COVERED: step vocabulary, filter
operators, sub-app declarations, grant verbs, field data types. Each
probe also guards ITSELF, because two empty sets agree perfectly and
two of these shipped with a pattern that had stopped reading.

**An admin view of live performance metrics. BACKEND DONE.**

RED -- Rate, Errors, Duration -- at GET /api/admin/metrics, gated on
manage:deployment. One row per request, persisted to SQLite rather than
counted in memory, because in-memory counters reset on every restart
and uvicorn --reload restarts on any file change.

Measured before choosing: one committed row is 0.105 ms against a query
path of several hundred, and ten thousand rows are 192 KB.

SATURATION IS DELIBERATELY ABSENT -- the fourth golden signal is a
property of the HOST, and answering it from inside the process would
mean guessing at limits we do not know.

THE SCREEN IS DONE, as an Admin tab. It names the missing signal
rather than omitting it -- four numbers with no mention of a fifth
reads as the whole picture, and naming the gap is the difference
between an incomplete dashboard and a misleading one.

STILL OPEN: a retention sweep. forget_older_than exists and nothing
calls it, so the table grows without bound. At 192 KB per 10,000
requests that is slow, but it is still unbounded.

**Superseded, for anyone revisiting:**

**Host metrics correlated with hops**, explicitly NOT a resource
analyzer.

---

## 5. The ELT pipeline -- see ELT_ROADMAP.md

A GOVERNANCE project, not a performance one -- and it started as the
latter. Two phases are done and delivered 67x (34.90s to 0.52s) by
fixing N+1 write-log queries and per-row audit writes, with ZERO
architectural change.

That dissolved the original premise. DuckDB and the materialised MAC
column are STRUCK, because the measurements that justified them went
away when the real path was profiled rather than a benchmark.

What remains stands on lineage, history and re-derivation: bronze,
silver from bronze, durable storage, a changelog, and a current view.
Six phases, with the reversibility line named at phase 3.

**Sync memory: batching, when a deployment has a big enough table.**
Measured at roughly 1.2 KB peak per row -- 250,000 rows costs 299 MB, a
million would cost about 1.2 GB. On a two-vCPU host a million-row table
is borderline and ten million would fail.

The sync holds a full table at FOUR points (source read, bronze Arrow
table, bronze read-back, changelog diff), so it is O(table) in memory
by design. Time is not the constraint anywhere.

The trigger is a real table this size; every table we have is four to
seven rows. The first thing to do when someone hits it is RAISE rather
than OOM -- a sync that refuses a table it cannot hold is diagnosable,
one the kernel kills is not. Full reasoning in ELT_ROADMAP.md.

**THREE unexplained test failures now -- two frontend, one backend --
each seen once, none reproducible, none naming the test.**

Three occurrences is past the point where "noise" is a fair
description. The common signature: a single failure in a full-suite
run, clean on every retry, and a summary line that does not say which
test.

WHAT TO DO ABOUT IT, since chasing it after the fact has failed three
times: make the suite name failures as they happen, not only in a
summary that the retry erases. `--reporter=verbose` for vitest and
`-p no:randomly -x` for pytest both do that. Worth wiring into the
default invocation rather than remembering to add.

The alternative -- continuing to shrug -- has a cost: the next REAL
intermittent failure will be read as this one.

A backend run reported `1 failed | 1708 passed` without naming the
test; three subsequent runs, including one with randomisation
disabled, were clean. It appeared on the run immediately after a new
test that calls create_app() with a tmp_path data directory, which is
the obvious suspect for cross-test leakage -- but suspicion is not
evidence and the run did not say.

Capture WHICH test if either recurs: `--tb=short` alone was not enough,
because the summary line does not name a test that passed on retry
within the same run. `-p no:randomly` fixes the order, which is the
other half of reproducing it.

**And one unexplained frontend test failure, seen once.** A full run
reported `1 failed | 701 passed` and did not say which. Six subsequent
runs -- four of app-browse alone, three of the whole suite -- were
clean, so it could not be identified.

Recorded rather than dismissed, because a flaky suite is how the next
real failure gets called noise. If it recurs, the thing to capture is
WHICH test: `npx vitest run --reporter=verbose` names them as they go,
where the default reporter only summarises.

Most likely candidates are the async panel tests, which wait on
mocked promises and have grown a lot this session.

## 6. Architectural questions, not tasks

These want answering before anything is built on them, and neither is
made easier by delay.

**What the LLM decides, and what Python already decides for it.** The
boundary has moved several times without being restated.

**Should the schema be in the prompt at all?** The largest open
question here, and adjacent to the measurement session above.

---

## 7. Optional

**HOT_RELOAD_PLAN.md step 5c**, sync to a branch and validate there.
Optional by design: the generation-swap approach makes branch
validation belt-and-braces rather than load-bearing, which is why
pyiceberg lacking fast_forward_branch never blocked anything.

**Measure the aggregate path**, now that charts made it hot for the
first time.
