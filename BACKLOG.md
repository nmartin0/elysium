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

**Saved Explorations.** A search plus its filters, columns and chart
configuration, persisted and returnable to. Appears independently on
two lists, which is usually a sign of a real need. No backend exists;
ConfigHistory and PendingWriteStore are both precedents for the store.
Saved SELECTIONS are a distinct thing from saved searches and the UI
must not conflate them.

**Vertex-lite: a read-only link explorer.** The largest remaining
feature. The schema already declares link types and cardinality, and
search_around already traverses them, so the backend is mostly there.
Wants its scope discussed before starting rather than guessed.

**Bulk actions**, through the existing propose/confirm flow. Depends on
saved selections above.

**Per-task approval eligibility.** Foundry scopes a reviewer's action
to the tasks they are eligible for; we approve a whole batch
atomically. Ours is defensible -- partial application of a
multi-object write is a correctness problem -- so these want
reconciling rather than one replacing the other.

---

## 3. UI, none of it urgent

**Fixed precision for numbers.** Blocked on a decision rather than
effort: the ontology declares types but not scale, and two decimal
places is wrong for a coordinate and for a count alike.

**The keyboard model's roving-focus half.** The accessibility work
nobody has touched.

**URL-as-state**, so a view can be shared or bookmarked.

**The view-state matrix's other half.** The two empty states shipped;
loading, error and partial are still per-panel choices rather than one
audited set.

---

## 4. Observability

**Calibration probes** -- what else can drift the way the step
vocabulary did, caught by construction rather than by noticing.

**An admin view of live performance metrics.**

**Host metrics correlated with hops**, explicitly NOT a resource
analyzer.

---

## 5. Architectural questions, not tasks

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
