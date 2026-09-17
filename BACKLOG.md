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

~~SEARCHED THE WHOLE UI and found one instance.~~ WRONG, and I looked
in the wrong place. The cause was in SHARED CSS, not in any component:
`.workspace__filter > label` matched every direct child label, and
Blueprint's Checkbox IS a label -- so every checkbox in the Columns
filter got the filter-heading treatment, stacked with the box above
its own text. A sweep for "<Checkbox" could never have found it.

~~STILL OPEN: which OTHER screens show it.~~ FOUND, and it was not a
component at all: `.workspace__filter > label` styled EVERY direct
child label, and Blueprint's Checkbox IS a label. So every checkbox in
a filter pane got the heading treatment -- uppercase, bold, stacked
above its own text.

That is why a sweep for `<Checkbox` found nothing: the fault was in
shared CSS, and the selector was written before any filter contained a
control that happened to be a label.

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

~~**Make the test suites NAME their failures.**~~ THEY ALREADY DO,
and this entry was the mistake rather than the tooling.

pytest prints `FAILED path::test - AssertionError...` and vitest
prints `FAIL file > describe > it`. Verified by forcing a failure in
each. The three flakes were unidentifiable because I read the output
through `tail -1` and `grep -oE "Tests .*"`, which discard exactly
that line.

The rule is in AGENTS.md: do not truncate the output you are
diagnosing from.

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

~~**What Query should contain.**~~ RESEARCHED AND PLANNED -- see
QUERY_PLAN.md. Four parts, ordered by what they depend on.

INPUT DISCOVERABILITY IS THE NAMED PROBLEM: "a long standing
challenge for NLIs", answered by contextual suggestions beside the
results rather than a help page.

AND THE DEPLOYMENT ALREADY STATES GOOD QUESTIONS --
example_queries.yaml -- which NOTHING IN THE WEB UI READS. It is
loaded only by scripts/run_deployment.py, and its entries are
user-paired for that runner, so it needs a display-safe subset
rather than straight reuse.

BUILDABLE NOW: deployment-stated examples, and keeping the last
question in the box so refining one clause is the default.

WAITS FOR THE MEASUREMENT SESSION: reading the question back as the
agent understood it, and generated follow-on suggestions. Both need
a model to design against.

DELIBERATELY NOT BUILDING: clarifying questions before answering
(an extra model call per question for a problem nobody has
reported), and a conversation thread (Elysium answers questions
about an ontology; the trace beats a transcript).

**A plugin API, server and client.** The largest item here and
probably its own session. Third-party sub-apps and server-side compute
that load INTO Elysium without modifying it, so a vanilla install can
become something domain-specific -- the worked example being a
quantitative trading engine -- while base Elysium stays upgradeable.

### Needs a decision from a person

~~**Per-task approval eligibility.**~~ SETTLED -- see section 0e for
the design and the four-step build order. Partial APPROVAL with atomic
EXECUTION, which is how Foundry separates the two.

~~**Host metrics correlated with hops.**~~ SETTLED -- see section 0e.
Three specific questions replace the vague goal, and all three need
agent traces, so they belong to the measurement session.

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

2. ~~**Decide what the lake holds.**~~ RESEARCHED -- see
   LAKE_METADATA_NOTE.md, which CORRECTS the split above.

   I reasoned from the control-plane argument and concluded the
   ontology, policy and silos BELONG in the lake. That over-read it: a
   catalog's control plane governs TABLES -- schemas, locations,
   snapshots, column access. Our ontology is a SEMANTIC MODEL, and
   those have their own precedent pointing elsewhere: dbt and Cube
   both keep them in version control, for governance reasons rather
   than convenience.

   But core/config_history.py already found the limit of that, and its
   reasoning is better than mine: "this project's own configuration
   happens to live in a repository; a DEPLOYED Elysium has
   /etc/elysium on an operator's machine and no relationship to any
   repository."

   THE SHAPE IS THREE ROLES, not two: AUTHORED in version control,
   LOADED from /etc/elysium, and PUBLISHED alongside the data as a
   COPY. The copy is not a source of truth -- it records what was true
   when those tables were written, which is exactly what bronze is for
   rows.

   Secrets stay out absolutely: a lake reader must not become a
   credential reader.

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

   **AND THE FIX ALREADY EXISTS.** The problem was never that Iceberg
   bakes in absolute paths -- it is that `file:///var/lib/mirror/...`
   is HOST-SPECIFIC while `s3://elysium/warehouse/...` is not. The
   same string resolves from any machine, container or mount, so
   nothing needs rewriting when the lake moves: as far as the lake is
   concerned it has not moved.

   Proved end to end: sync into object storage, DELETE THE ENTIRE
   INSTALLATION, preserve only the catalog, read the data from
   somewhere else. Passes. The identical teardown against a file://
   warehouse fails, which is the control.

   THAT REFRAMES THE DURABLE-STORAGE PHASE. It was justified as "the
   mirror should survive the machine" -- true, and incomplete. Object
   storage is also what makes a preserved lake REBUILDABLE ON.

   THE CATALOG MUST STILL BE PRESERVED. Its contents are now portable,
   but losing the file still leaves a bucket nobody can interpret.

   The tests assert the FAILURE, so fixing it turns them red rather
   than letting the fix land unnoticed.

   What DOES survive, checked in place: the data, bronze, the
   changelog, and provenance stamped on each table. What does not: the
   write log, credentials, config history, metrics -- and the ontology,
   policy and silos, which by the control-plane standard belong in the
   lake and are not there.

4. ~~**Name what deliberately does NOT survive.**~~ DONE, in two
   places: the teardown tests assert what is gone, and every published
   manifest carries a `withheld` list so a reader finding three files
   where the deployment had four knows that was deliberate.

   THE MANIFEST IS BUILT. `scripts/run_sync` publishes one per
   configuration generation to `_elysium/manifest-N.json` beside the
   data, and `scripts/check_mirror` reports it. An ALLOW-LIST decides
   what goes: the ontology, the silos and the policy. The LLM settings
   and every secret are withheld, and an unknown file is withheld by
   DEFAULT -- an exclusion list fails open the day someone adds one.

   READ AND REPORTED, never loaded. A manifest describing types the
   running ontology lacks is a mismatch worth telling someone about;
   loading it would make a copy into a second source of truth, and
   refusing to start over it would turn a stale copy into an outage.

   STILL OPEN: bootstrapping a new deployment FROM a manifest.
   Deliberately deferred -- see LAKE_METADATA_NOTE.md.

## 0d. Is our Blueprint usage idiomatic? -- investigated

Asked after two checkbox bugs in a row whether we had accreted our own
functionality onto Blueprint instead of using it as intended.

**THE ANSWER IS MOSTLY NO, AND THE REAL PROBLEM IS NARROWER AND
SHARPER THAN THAT.**

### What is actually well done

Blueprint IS imported, via an `@import ... layer(vendor)` in
ui/src/layers.css -- and that file's reasoning is careful. It declares
a seven-layer cascade order so that "sitting beside Blueprint stops
requiring ever-more-specific selectors, and `!important` stops being
the escape hatch". There are ZERO `!important` declarations in this
UI.

It even names the trap it was avoiding: importing Blueprint unlayered
would let it beat everything, and "nothing in this repository can catch
that: there are no computed-style assertions and no screenshot tests".

Only 12 rules reach into Blueprint's own classes at all, across ~1,900
lines. That is not accretion.

### The actual defect

**NONE OF OUR OWN STYLESHEETS ARE IN A LAYER.** index.css, tokens.css
and SchemaPanel.css declare no `@layer` at all, so they are
UNLAYERED -- and unlayered styles beat every layer.

The intended outcome (our styles win) happens, but by the wrong
mechanism, and with a consequence nobody chose: a BARE ELEMENT
SELECTOR in our CSS now beats Blueprint's component classes regardless
of specificity. `label` outranks `.bp6-control`.

That is exactly how
`label { display: flex; flex-direction: column }` stacked every
checkbox in the app above its own text, and why a sweep for
`<Checkbox` found nothing: no component was at fault.

The seven declared layers are also inert -- nothing is in them.

### Is it feasibly fixable

YES, AND IT IS SMALL: wrap each stylesheet's contents in the layer it
belongs to. But it MUST NOT be done blind. Moving our CSS from
unlayered into `components` changes which rules win against Blueprint
everywhere at once, and layers.css says plainly that this repository
cannot detect the result -- no computed styles, no screenshots.

So the order is: a way to SEE the change first, then the change.
Options, cheapest first:

- A handful of computed-style assertions at the known-fragile points
  (a checkbox, a menu item, a card in a card list). jsdom cannot do
  this; it needs a real browser.
- Or accept the current state and keep the tripwire below, which is
  where this landed for now.

### Shipped instead, as the proportionate step

A test listing every bare element selector in index.css, so that
ADDING one is a decision someone makes deliberately rather than a
change that silently outranks a vendor component. Five are currently
allowed, each reviewed.

## 0e. Decided September 15, and what each needs

### Approvals: per-task approval, atomic invocation

**FOUNDRY HAS BOTH, AT DIFFERENT LAYERS, and that dissolves the
trade-off I posed.** Approval is per task and partial by eligibility:
"an eligible reviewer can either Approve or Reject the task...
alternatively, use the Approve all or Reject all button... to approve
or reject all tasks in the request THAT YOU ARE ELIGIBLE TO REVIEW."

Invocation is not: "all tasks associated with a request must be
approved for the request to be invoked and requested changes to be
applied."

So a reviewer approves the 47 they can; the other 3 wait; nothing
applies until every task is approved, and then everything applies
together. Partial APPROVAL, atomic EXECUTION.

**THE GROUPING INTO A REQUEST IS THE DEPENDENCY DECLARATION.** A
delivery that requires a warehouse shipment to make space is two tasks
in ONE request -- both approved or neither happens. Genuinely
independent work is two requests, each invoking as soon as it is
approved. No per-action flag is needed; how work is bundled says it.

**WE CANNOT EXPRESS ANY OF THIS TODAY.** PendingWrite holds the
proposer, the sub-writes and when it was proposed. There is NO
approval state: confirm_and_execute() is one person saying yes or no,
once, and there is nowhere to record that Alice approved while Bob has
not. Three roles each signing off is not partially supported -- it is
absent.

What the submission-criteria vocabulary CAN already say is "the
approver must not be the proposer", which is four-eyes. What it cannot
say is "these three roles must each sign off".

Build order, with the atomic batch untouched at the end:

1. ~~Per-task approval records~~ DONE. PendingWriteStore holds a
   TaskApproval per sub-write index: who decided, what, and when.
   `is_fully_approved()` is the invocation gate and is strict --
   undecided and rejected both mean not ready. NOTHING CALLS IT
   YET; confirm_and_execute still takes one decision from one
   person, which is step 2.
2. ~~A request that knows whether it is fully approved, and invokes
   only then.~~ DONE. The confirm route records a decision per task
   and asks `is_fully_approved()` before executing.

   EVERY TASK, FOR NOW, because eligibility does not exist yet: one
   reviewer decides all of them and the gate opens immediately, so
   behaviour is unchanged and the integration suite confirms it. The
   mechanism is real -- when eligibility lands, a reviewer approves
   their subset and this same gate holds the request.

   The awaiting-other-reviewers branch is written but unreachable
   today, deliberately: a gate that silently passes is one step 3
   has to remember to add.
3. ~~Eligibility: which tasks a given reviewer may act on.~~ DONE.
   `eligible_task_indexes()` on WriteMediator, built on the existing
   `check_access()` so it cannot drift from eligibility elsewhere.

   WHAT DIFFERS BETWEEN TASKS IS THE OBJECT. Every task shares the
   request's action type, so the execute: grant is identical across
   all of them; MAC separates them. A reviewer in one security
   partition decides the tasks touching it and leaves the rest.

   A create has no object to check, so it falls back to the action
   grant alone -- the same answer the request-level check gives.

   The awaiting-other-reviewers response is now REACHABLE: a
   reviewer who can see part of a request approves their part and is
   told the rest is still waiting.
4. ~~An inbox showing a reviewer their eligible tasks.~~ THE DATA IS
   DONE: /writes/awaiting now returns tasks_total,
   tasks_you_may_decide and tasks_approved per request.

   COUNTS, NOT THE TASKS THEMSELVES. A listing showing fifty task
   rows per request would bury the requests, and the response model
   is the security guard -- a test pins its exact field set so that
   widening it is a deliberate act. Counts carry no object values.

   APPROVED, NOT DECIDED: a rejected task is not progress toward
   invocation, and counting it as such would show a request as
   nearly ready when it is permanently blocked.

   THE UI SHOWS THEM. ApprovalsPanel renders "12 of 50 tasks are
   yours to decide" when a reviewer's share differs from the whole
   request, and "38 of 50 approved so far" while others are still
   deciding. Both hidden in the ordinary case -- one task, wholly
   this reviewer's -- because a count on every row is noise by the
   time it matters.

   Approve was ALREADY scoped: the route records decisions only for
   eligible tasks (step 3), so the button covers this reviewer's
   share and the gate holds the rest. What was missing was saying so.

Foundry backs the same guarantee at the storage layer -- their Iceberg
catalog "extends standard Iceberg with all-or-nothing transaction
semantics... all writes either succeed together or are fully
discarded" -- which is what our atomic batch already does.

### Host metrics: three questions, not a dashboard

The old entry said "correlated with hops", which is not a well-formed
goal. Replaced with what would actually be worth knowing:

1. **Which queries fail, and at which hop.** An agent dying on hop 5
   of 8 is a different problem from one returning a bad answer.
2. **Hops per query, as a distribution.** If most take 2 and some take
   9, the 9s hold the cost and the failures.
3. **Time per hop, split by model call versus ontology read.** Whether
   a slow query is a slow model or a slow silo -- completely different
   fixes.

All three need agent traces, so all three belong to the measurement
session rather than to a decision.

### Browser-based tests, as their own item

**STARTED, and the foundation already existed.** `ui/e2e/` holds
Playwright tests with a config and four shell tests -- but NO npm
script, nothing in CLAUDE.md, and so no part in anyone's routine.
Added `npm run e2e`, `npm run e2e:install`, and a CLAUDE.md section
saying plainly that jsdom computes no layout.

`ui/e2e/layout.spec.ts` is new: computed geometry, hit-testing and
repeated real clicks -- the three things that would have caught this
session's failures.

**RUN, AND SEVEN OF ELEVEN PASS.** The browser has now confirmed what
nothing here could see: the checkbox sits beside its row rather than
above it, nothing covers it, a plain click selects without navigating,
ten clicks in a row all toggle, and Blueprint's controls keep their
own inline layout.

Remaining failures, none of them assertions about layout:

- `shift-click selects the range` -- fixed here; it clicked the third
  row of a two-row fixture.
- Three in shell.spec.ts, which predate this work: an Admin nav item,
  a click-through to a detail page, and a logout. The first two now
  have usable accounts; whether they pass is unknown.

**SUPERSEDED NOTE:** The container cannot
download a browser (cdn.playwright.dev is not in its network
allowlist), so every assertion is a claim awaiting its first
execution. Expect selector fixes on the first run.

**BOTH DONE.** Eleven of eleven browser tests pass, and the last
failure turned out to be a real defect -- no object type declared a
title_field, so every result card showed a raw id.

The stylesheets are now in their declared layers. **THIS DOES NOT MAKE
BARE ELEMENT SELECTORS SAFE**, and it would be easy to read it as
though it did: `components` beats `vendor` REGARDLESS of specificity,
exactly as unlayered did. The `:not(.bp6-control)` guards and the
tripwire test remain load-bearing.

What it buys is smaller and real: the declared order is now the actual
order, so `utilities` and `overrides` will work when something needs
them, and nothing silently outranks a layer added later.

It would have caught the checkbox layout, the labels stacked above
their text, and probably the stretched-link problem. Six attempts at
one checkbox, none caught by 786 tests, all found by a person
clicking.

Worth doing for itself. And once it exists, moving our stylesheets
into the declared cascade layers -- currently unlayered, so every bare
element selector silently outranks Blueprint -- becomes a safe, small
change instead of an unverifiable one.

### An audit for workarounds

**A WORKAROUND THAT WORKS IS STILL THE WRONG ANSWER**, and this
session produced several before landing on the right one each time: a
timing window to tell a real click from a browser-forwarded one, a
tripwire listing bare element selectors instead of layering the CSS, a
path-rewriting helper for a lake that simply needed a different URI
scheme.

Each was plausible, each passed its tests, and each was a way of
living with a problem rather than removing it. The pattern to look for
is code that compensates for a structure rather than changing it.

FIRST PASS DONE, over the four recorded candidates. Two were real
workarounds and are gone; one was never a workaround; one is still
load-bearing and now says so.

- ~~pyiceberg privates~~ NOT A WORKAROUND. `catalog.properties` is a
  public instance attribute and `load_file_io` a documented function.
  My comment claiming "private access, deliberately" was wrong --
  inferred from the CLASS, where `properties` does not appear because
  it is set in __init__. Corrected.
- ~~The manifest probe loop~~ REPLACED BY LISTING. FileIO has no list
  operation, which is why I guessed generation numbers -- but it
  exposes the FILESYSTEM through parse_location and fs_by_scheme, and
  that lists fine. Verified against both a local warehouse and S3. The
  gap constant and upper bound the guessing needed are gone with it.
- ~~Three `noqa: SLF001` on `sync._catalog`~~ FIXED by adding the
  accessor that was missing. A suppression repeated three times is not
  three exceptions.
- **The bare-element-selector tripwire STAYS.** Layering the CSS did
  not supersede it: `components` beats `vendor` regardless of
  specificity, so a bare `label` still outranks `.bp6-control`. The
  entry that called it superseded was wrong.

SECOND PASS DONE, over every `noqa` in the codebase -- sixteen of
them, which is the whole population rather than a sample.

- ~~Five `E402` from `sys.path` inserts~~ REMOVED. Three scripts
  manipulated sys.path so they could run as `python scripts/foo.py`,
  and every documented invocation is `python -m scripts.foo`, which
  needs no such thing. A workaround for a usage nobody is told to use.
  All four scripts verified still working.
- ~~One `BLE001` in create_e2e_users~~ NARROWED. An absent user raises
  ValueError specifically; the broad catch would have swallowed a
  permissions error and still printed "created".
- **Two `B024` STAY, and nearly did not.** `ABC` with no abstract
  methods looks like it enforces nothing -- but it supplies the
  ABCMeta that makes TWELVE `@abstractmethod`s in a subclass actually
  enforced. Verified directly: a plain base leaves them unenforced and
  an incomplete subclass instantiates silently. The comment now says
  so.
- **Two `S608` STAY** -- generated placeholders, every value
  parameterised. But see the open item below.
- **The remaining `BLE001` stay, on one condition each: they must
  REPORT.** api/reload.py uses logger.exception, the metrics
  middleware warns, integrity.py records a finding. Two in
  iceberg_sync.py returned False -- the safe direction -- and said
  NOTHING, so a persistent fault would rewrite every unchanged table
  forever, silently defeating the skip that took 27.2 MB to 0.9, and
  look like normal operation. Now logged at debug.

**A RULE WORTH KEEPING:** a broad catch is acceptable where any
failure means the same thing to the caller, and only when it reports.
A broad catch that stays quiet is a workaround.

STILL OPEN, AND A JUDGEMENT CALL RATHER THAN A DEFECT: the write log
chunks id lists into batches of 500 and builds an `IN (?,?,?)` clause,
which is why the two `S608` exist. SQLite's `json_each` takes the whole
list as ONE parameter -- no dynamic SQL, no chunking, no variable
limit. Verified working. It trades two suppressions and a constant for
a minimum SQLite version (3.38, 2022), which is a real trade and not
mine to make alone.

STILL TO AUDIT, since suppressions are only where workarounds ADMIT
themselves:

**THE RULE:** a broad catch is acceptable where any failure means the
same thing to the caller, and only when it REPORTS. One that stays
quiet is a workaround.

DEFERRED BY THE USER, not forgotten: replacing the write log's
chunked `IN (?,?,?)` with SQLite's `json_each`, which removes two
`S608`, the chunking and the variable limit, in exchange for a minimum
SQLite version of 3.38. Verified working.

## A CATALOG COMMIT AND ITS METADATA WRITE ARE NOT ATOMIC

Found by scripts/check_mirror during this audit, on a real mirror, and
it is the most serious thing the audit turned up.

The disk filled during this session. A sync running then updated the
catalog row to point at metadata file 00008 and never wrote it -- only
00007 exists. Every read of that table then failed with
FileNotFoundError.

**RE-SYNCING DOES NOT REPAIR IT.** 0 of 2 tables synced: every write
begins by reading the current snapshot, and the current snapshot is
the file that is missing. The only recovery found was deleting the
mirror and rebuilding from source -- which works only because bronze
and silver are derivable. THE CHANGELOG IS NOT. A deployment losing a
changelog table this way loses history no re-sync can rebuild.

RESEARCHED, AND THE MECHANISM IS KNOWN.

**THE ORDER IS CORRECT.** pyiceberg's SqlCatalog.commit_table calls
_write_metadata BEFORE opening its database session -- read directly,
not assumed -- which matches the spec's guarantee that a crash "costs
orphan data files rather than a broken table".

**THE GAP IS DURABILITY, NOT ORDER.** The metadata is written through
`filesystem.open_output_stream(...)` and closed. There is NO fsync
anywhere in that path -- checked. A close() flushes to the operating
system; it does not force data to disk. On a full disk or a power
loss, the kernel can fail the writeback AFTER close() returned, so the
catalog commits a pointer to content that never landed.

A REST catalog would NOT fix this. It moves the pointer swap to a
server with real CAS, which solves concurrent writers -- a different
problem. The metadata file is still written by the client, through the
same unsynced path.

**IT IS REPAIRABLE, WHICH CHANGES THE SEVERITY.** Pointing the catalog
at the newest surviving metadata file restores the table, losing only
the commits recorded in the missing file. `scripts/repair_catalog`
does this: reports by default, repairs with --write.

That matters because deleting and re-syncing -- the obvious recovery
-- destroys THE CHANGELOG, the one layer nothing can rebuild.

STILL OPEN:

- Fail the SYNC when the catalog and warehouse disagree, rather than
  reporting 0/2 with no explanation.
- Whether to fsync metadata before the pointer swap. pyiceberg offers
  no hook, so this would mean a custom FileIO or a post-write sync of
  the metadata directory, and it costs a real fsync per commit.


ALSO FIXED: check_mirror named the SILVER identifier whichever of the
pair could not be read, so a broken bronze table was reported as a
broken silver one -- and the first thing anyone does with that message
is look at the wrong table.


STILL TO AUDIT, since four candidates were only a starting point:

Known candidates, to start from rather than to limit the search:

- The bare-element-selector tripwire, superseded by layering the CSS.
- Anything reaching into Blueprint's internals by class name.
- `_warehouse_root()` and `_file_io()` reaching into pyiceberg
  privates -- possibly unavoidable, worth confirming.
- The manifest probe loop, which guesses generation numbers because
  FileIO has no list operation.

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

**THREE SINGLE-TEST FAILURES, none of them reproduced -- and the
reason they were never identified was how I read the output.**

Both suites name a failing test. I read their output through
`tail -1`, which prints only the count. Each time I concluded the
name had not been written, recorded the flake as unidentifiable, and
twice proposed adding a verbose reporter that already exists.

STILL OPEN, but a much smaller thing: the failures themselves were
real and are still unexplained. If one recurs, the name will be in
the output -- read it without a pipe.

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
