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
- Select-all across pages means the FILTER, not the page.
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

**An admin view of live performance metrics.**

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

**One unexplained frontend test failure, seen once.** A full run
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

## 6. Optional

**HOT_RELOAD_PLAN.md step 5c**, sync to a branch and validate there.
Optional by design: the generation-swap approach makes branch
validation belt-and-braces rather than load-bearing, which is why
pyiceberg lacking fast_forward_branch never blocked anything.

**Measure the aggregate path**, now that charts made it hot for the
first time.
