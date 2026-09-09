# Elysium UI roadmap

The backend phase is complete: every endpoint the near-term sub-apps
need exists, is tested, and is reachable. This file plans the work
that consumes it.

Written after the backend list was settled, so it inherits that
list's discipline: every item states what it needs, what it does NOT
need, and how it can be verified. An item without a verifiable outcome
is a wish, not a plan.

---

## What exists today

Four packages, roughly 6,300 lines:

| Package | Size | What it is |
|---|---|---|
| `shell-api` | ~3,000 | The shared client, auth, layout and routing |
| `app-browse` | ~2,100 | Object search and `ObjectDetailPanel` |
| `app-admin` | ~850 | User management |
| `app-query` | ~370 | The agent query view |

Single-hop link navigation already works in `ObjectDetailPanel`, which
is the foundation item 4 builds on.

## What the UI can already reach

Every one of these is tested backend-side and unused by any screen
today, which is the gap this roadmap closes:

```
GET  /health
GET  /me, /me/visible-schema, /me/visible-action-types, /me/visible-apps
GET  /objects/{type}/search        paged, sorted, opaque tokens
GET  /objects/{type}/{id}
GET  /objects/{type}/{id}/history  paged
POST /objects/{type}/count
POST /objects/{type}/aggregate
POST /objects/{type}/search-around
POST /actions/{name}, /writes/{id}/confirm
POST /query
```

Plus rendering metadata on every object type and field: display name,
plural, description, icon, colour, field visibility
(prominent/normal/hidden) and status (active/experimental/deprecated).

**`visibility: hidden` is cosmetic, never security.** It tells a screen
not to show a field; it does not withhold one. Field-level RBAC does
that, in the mediator, before a value is produced. A UI that treated
`hidden` as a permission would be wrong about what it is protecting.

---

## Build order

The order is from the original research: lowest-risk and
highest-precedent first, highest-effort last. Item 3 sits out of order
because its backend prerequisite is a design question, not a feature.

### 1. Read-only ontology schema viewer

Browse object types, fields, link types and cardinality, filtered
through the same RBAC and MAC the API already enforces -- restricted
fields hidden or marked, never a second permission model.

Deliberately NOT an editor. Editing a live ontology has separate
security implications and belongs in the far-later Ontology Manager
item.

**Needs:** `/me/visible-schema` only. Everything it renders --
display names, descriptions, icons, colours, field visibility and
status -- is already in that response.

**Why first:** it is read-only, single-endpoint, and it exercises the
display metadata end to end. If icons or humanised labels are wrong,
this is where it shows, before four other screens depend on them.

**Verifiable:** a role with fewer grants sees strictly fewer fields,
and the same schema rendered for two roles differs.

### 2. Object Explorer — see OBJECT_EXPLORER_PLAN.md

Expanded into its own file: it is the largest piece of this phase, it
needs backend work that does not exist yet, and nine design questions
were settled before starting rather than during.

THE BLOCKER, stated here so nobody starts the UI first: our filter is
equality only -- one value per field. Clicking two bars on a chart
means "these two values", which needs IN. The central interaction is
blocked on the query model, not on the UI.

Summary of what changed from the sketch below: charts are the FILTER
mechanism rather than a report; saved artifacts are re-authorized on
every open and say what was disabled; ownership is by ROLE rather than
by user; and the vocabulary is ours rather than the reference
implementation's -- Charts/Table, value counts, saved search, saved
selection.

Three separable pieces, in this order:

**Paged, sorted result tables.** `search` already returns
`next_page_token`, `total_matches` and accepts `order_by`. No screen
uses any of them. Treat the token as opaque -- it is versioned and
will change.

**Saved Explorations vs Saved Lists, kept distinct.** An Exploration
persists a filter and re-runs live; a List persists a frozen set of
object ids. Foundry's own users conflate these when the distinction is
not explicit in the UI, so name them differently and never offer to
convert one silently into the other.

**Filter-capable charts**, from `/objects/{type}/aggregate`: single
statistic, histogram, listogram. Nothing fancier until these are used
-- maps and grid plots are a different kind of work.

**Bulk actions** reuse the existing propose/confirm flow with a real
batch cap. The cap is not a nicety: an action over an unbounded result
set is how someone edits ten thousand objects by accident.

**Needs:** `search` (paged/sorted), `aggregate`, `count`, `actions`,
`writes/{id}/confirm`.

**Verifiable:** paging a changing result set is documented to possibly
duplicate or miss rows -- the UI must not present its row count as
authoritative during a live sort.

### 3. Pending changes / approvals inbox — BLOCKED, and on a decision

The two-phase propose/confirm mechanism exists. This gives it a queue
view across the org rather than only inline.

**Blocked on a backend design question, not a migration.** Today only
the PROPOSING user may confirm their own pending write, the store is
in-memory, and it expires in 15 minutes. The first of those is a
security property in the current model -- it stops a second user
completing a write the first abandoned -- so an approvals inbox is a
SECOND model, not a repair of the first.

The questions to answer before any UI work: who may approve what (a
reviewer grant, distinct from `execute:`), whether a proposer may
approve their own write, what expiry means when a human is expected to
be slow, and what the audit trail records about both parties.

**Not blocked on PostgreSQL.** SQLite already backs the write log and
credential store under concurrent writers; that framing was wrong and
has been corrected in `ROADMAP.md`.

**When it is unblocked:** reviewer eligibility derives from the SAME
RBAC and MAC check that gates the underlying action, never a separate
ACL. The field-level before/after diff is itself filtered through MAC,
so a reviewer never sees a field they could not otherwise read.

### 4. Vertex-lite: a read-only link explorer

Extends `ObjectDetailPanel`'s single-hop navigation into an explicit
"explore related" view.

**Show link-type counts BEFORE expansion**, so fan-out is never a
surprise. `/objects/{type}/count` and `search-around` make this cheap
to do honestly rather than by guessing.

Read-only to start: no drag-to-rearrange, no styling, no editable
canvas. Those are a different project.

**Needs:** `search-around`, `count`, and the link metadata from
`visible-schema` -- every generated link field carries `link_type`,
so both directions of one relationship can be grouped rather than
shown as unrelated columns.

**One known gap:** a link and its reverse are two entries. Presenting
them as a single relationship is display work over existing data, not
a backend change -- see the object-backed link types entry in
`ROADMAP.md`.

---

## Build order, easiest to hardest

The sections below are in the order we discussed them. This is the
same list sorted by DIFFICULTY -- how much has to be designed or
decided before code can start, not how many lines it is.

Numbers in brackets are the item numbers in the sections below, which
do not change. Where two orderings disagree, the note says which to
follow.

**Nearly free -- the work exists, it just is not wired**

 1. [31] A read-only config view -- what this deployment is running
 2. [20] FHS paths, keeping the env overrides
 3. [25] Log rotation
 4. [14a] Silo, READ-ONLY half -- health_check exists, nothing shows it
 5. [7]  The schema graph -- visible_schema plus an ECharts graph series

**Small and self-contained**

 6. [15] Instrument the boundaries log_pre/log_post already bracket
 7. [24] Graceful shutdown on SIGTERM
 8. [26] Startup validation: silo reachability, mirror schema drift
 9. [42] Cardinality before action -- count_objects already exists
10. [28] Delimit untrusted text in the prompt
11. [36] Mirror sync fan-out -- bounded pool, independent targets

**Needs one decision first, then it is small**

12. [33] chat() timeout and token counts -- BLOCKS 27 and 29
13. [27] A wall-clock deadline -- needs 33
14. [29] Measure the loop -- needs 33 for real token counts
15. [18] Cap what a step returns into context
16. [22] SCHEMA MIGRATION -- see the ordering note below
17. [16] A metrics endpoint -- decide the grant and label cardinality
18. [1]  The search bar -- five operators currently have no UI
19. [34] An OpenAI-compatible adapter -- verify json_mode and usage
20. [35] Multi-silo reads -- parallel fan-out inside a request
21. [23] Backup and restore -- SQLite online backup, not file copies
22. [3]  Object Views -- link counts are the value
23. [17] Measure where the effective window ends -- needs 29
24. [9]/[39] Watch to notify -- needs a scheduler [38]

**Bigger, or a design question wearing a feature's clothes**

25. [32] Eval harness with baselines and a regression gate
26. [21] Generated first-run password -- needs a migration [22]
27. [4]  Change over time -- per-row re-authorization
28. [10] Agent audit -- cheap to build, and the most distinctive
29. [30] Per-request CONFIG snapshot -- makes 13 nearly free
30. [2]  The Approvals inbox -- who may approve is undecided
31. [40] Watch to ask -- mostly free once 2 exists
32. [8]  The instance graph -- the expansion protocol IS the design
33. [13] Runtime role editing -- needs 30
34. [6]  Notes attached to objects
35. [14b] Silo EDITING -- needs per-adapter allowlists
36. [37]/[38] --workers and the scheduler: ONE decision, two doors

**Hardest, and each needs something settled before it starts**

37. [5]  Explaining a result -- the public trace shape must be versioned
38. [41] Watch to RUN THE AGENT -- 28 is a prerequisite, not a nicety
39. [11] Scenario -- what happens when data moves beneath one
40. [19] The labelling experiment -- cheap to run, decides 12
41. [12] Query with memory -- blocked on 19's answer

**THE ONE ORDERING NOTE THAT OVERRIDES DIFFICULTY.** Item 22, schema
migration, sits mid-list by effort and should be done FIRST anyway. It
is the only item that becomes IMPOSSIBLE rather than merely urgent:
the first schema change after someone has real data is the one that
cannot be undone, and 21, 13, 39 and 6 all add columns.

Everything else can wait its turn. That one closes a door that is
still open.

## Feature backlog, ranked by value to users

Ranked by what a user cannot do without it, not by what it costs us.
Each entry records what it provides and what stands in its way, so the
argument does not have to be reconstructed.

**1. The search bar.** Filter pills showing what is applied, and a
property picker whose input adapts to the field's type. Right now a
user cannot filter by a numeric range, a date, or "contains" AT ALL --
five of the seven operators the vocabulary supports have no UI -- and
applied filters are invisible once you leave the Charts tab. Most real
questions ("accounts over 10k", "opened last week") are unanswerable
from the interface. Everything else here improves a tool that works;
this makes it work.

**2. The Approvals inbox.** propose_action and confirm_and_execute
both exist, the artifact store exists, and there is no REVIEWER
screen. ActionForm confirms a write for the person who proposed it --
that is the author approving their own -- and there is nowhere for
anyone else to see a pending write at all. That is a broken
feature rather than a missing one. Needs the design question answered:
who may approve, may an author approve their own, what expiry means.

**3. Object Views.** What an operational user looks at all day. The
backend is entirely present -- get_object, search_around,
count_objects, visible_action_types -- and the detail panel already
renders links as navigable and filters actions to what the caller may
execute.

What it lacks is COUNTS: "47 transactions, 2 open tickets, 1 account",
each expandable. That is the operational question, and everything else
is arrangement. Per-type configured layouts are Foundry's expensive
half and worth skipping; a good default from the visibility metadata
Browse already uses gets most of the value.

**4. Change over time.** The write log records object type, id,
changed fields, user and timestamp for every mutation, and NOTHING
reads it. A history tab on an Object View is a read path plus a
render.

The real work is authorization: an entry may name a field the reader
cannot see, so entries must be filtered field by field, and one that
empties must VANISH rather than showing "someone changed something".
That is the re-authorization built for saved searches, applied per
row.

**5. Explaining a result.** The agent builds `gathered` -- every step
with its result -- and discards it after synthesis. Returning it would
let Query show "searched Customer where region = us-west, 200 matched,
read balance on 4, summed" instead of an answer with no provenance.

The hard part is not the trace but its SHAPE: the internal step format
changes whenever the agent does, so a public one has to be versioned
from the start.

**6. Notes attached to objects** (Foundry's Notepad, reduced). An
ontology records facts and has nowhere for judgements -- "we waived
the fee because their branch flooded" -- which is exactly what an
operator needs next time and today lives in email. Foundry's version
"maintains structured links to embedded objects, automatically
enriching the underlying ontology".

The sharp version here is not a document editor: notes attached to
objects, shown on the Object View, scoped by MAC. The artifact store
already does role-scoped persistence with re-authorization.

## Graphs, and they are two features not one

Foundry has both and they cost wildly different amounts, so conflating
them is what made this look large.

**7. The schema graph.** Object type nodes, action type nodes, link
type edges -- a picture of the ONTOLOGY, not the data in it. Schema
shows exactly this today as three lists that make you reconstruct the
shape in your head: click a link type, read which two types it joins,
remember it, click the next.

Everything needed is in visible_schema, already scoped to the caller.
BOUNDED by the number of object types rather than objects -- a dozen
nodes -- and ECharts has a graph series, so no new dependency. A day.

**8. The instance graph.** Individual objects, expand from a node,
follow links. Its real constraint is not rendering but COMPREHENSION:
a large node-link view becomes a "hairball with extreme edge crossings
that overwhelms human perception". The graph must stay in the
hundreds, not because we cannot draw more but because more cannot be
read.

That makes the expansion protocol the design and the renderer almost
incidental -- and it removes the WebGL question this was previously
blocked on. Expanding offers each link type WITH ITS COUNT
(count_objects exists); small counts expand, large ones require a
filter first, and a hard ceiling stops one click adding ten thousand
nodes. The counts are aggregate over what the caller can read, so this
is consistent with uniform denial rather than a new disclosure.

search_around, count_objects and get_object all exist. The work is
entirely frontend, and the subtle part is a layout that does not
reshuffle when a node is added.

## Ideas that fit Elysium specifically

Not Foundry equivalents. These follow from what Elysium uniquely has:
an agent over an ontology with per-field RBAC, MAC, a propose/confirm
write path, and a complete access log.

**9. Watch.** A saved search that runs on a schedule and reports when
its results change -- "tell me when a risk_score crosses 80". The
filter vocabulary, artifact store and saved searches all exist; what
is missing is a scheduler and a diff.

The authorization question is already answered: a watch is a saved
artifact, so it re-authorizes on every run, and a watcher who loses
access silently stops receiving alerts rather than leaking. Probably
the highest operational value on this list.

**10. Agent audit.** What the AI read on your behalf -- which types,
how many objects, which fields, how long. Every Query is a run against
an ontology with per-field access logging, and we use that log for
nothing.

Nobody else can build this, because it needs both an agent AND
per-field access logging. It is the trust argument for putting a model
over sensitive data, and it is cheap.

**11. Scenario.** A named set of pending writes you can view the
ontology THROUGH before committing -- "what would this look like if
these twelve transfers went through". propose_action already produces
pending writes and search_object already reconciles against them; a
scenario is that machinery with a name and a boundary. The open design
question is what happens when the underlying data moves beneath one.

**12. Query with memory**, and the question it turns on.

Query is stateless per question, so "and what about last month?" does
not work. The obstacle is authorization: a role change must not leave
yesterday's answer readable.

A FIRST VERSION OF THIS ENTRY SAID PROSE CANNOT BE RE-AUTHORIZED, and
that was wrong. It cannot be DECOMPOSED -- "Ada was flagged after the
March incident" has no field list, and nothing in the sentence says it
came from internal_notes -- but it can be LABELLED, and labelling is
sufficient.

When the agent synthesises, it knows exactly which fields it read and
which objects it touched. A conclusion therefore carries the UNION of
what produced it: the grants required, plus the MAC security values of
every object involved. Recall checks that the caller holds all of them.

That is high-water-mark labelling -- the label of a derived object is
the join of its inputs' labels -- which is the standard approach in
multi-level security systems rather than something to invent.

WE ARE UNUSUALLY WELL PLACED FOR IT. The label has to be COMPLETE or
it under-classifies and leaks, which requires the read path to be the
only door data enters through. For Elysium it is: the mediator is the
single point of enforcement, so every read is already observed.

**The failure mode is label creep.** Labels only ever go up, so a
conclusion that touched one sensitive field stays locked behind it
forever even if nothing sensitive is in the text. Over time most
memories become unreadable by most people and the memory stops being
useful -- the classic MLS problem, and why high-water-mark systems
drift toward everything-is-top-secret.

Ours is sharper because MAC is PER-OBJECT: a conclusion spanning 200
customers across three regions carries all three, so a us-west reader
cannot see it even though most of what it summarises is theirs.

And aggregation is genuinely unsolved -- two conclusions each
individually permitted may jointly reveal something neither does
alone. Nobody has a good general answer, and we should not pretend to.

**19. The experiment that would settle it**, and it is cheap.

Log what the label WOULD be for real queries, without building recall
at all. The agent already knows the fields and objects each answer
touched; recording the union costs almost nothing and changes no
behaviour.

Then measure: how many conclusions remain readable by their own author
a month later, and by a colleague in the same role? If label creep
locks most memories away quickly, labelled conclusions are not worth
building and the structured alternative -- remembering WHAT WAS READ
rather than what was concluded, and re-deriving the prose each time --
is the answer.

That alternative is strictly less capable, since it cannot recall a
judgement. It buys FRESHNESS rather than capability: a stored
conclusion goes stale when the data moves and has no way to know,
where a re-derivation cannot.

Measure before choosing. The experiment is a few lines and the
decision is otherwise a guess.

## A risk to what already exists, not a feature

**Context rot.** Current research describes "a model's effective
recall degrading as the token count grows, WELL BEFORE the hard
context limit is reached", driven by tool responses carrying metadata
"beyond what is decision-relevant".

Our agent accumulates `gathered` across every step and feeds it back
each hop. A query touching many objects therefore degrades the answer
BEFORE it errors -- the failure mode is a worse answer, not a crash,
which is the hard kind to notice. We have never measured where that
begins.

## Runtime role editing, and the pattern behind it

**13. Roles editable while the application runs.** policy.yaml becomes
the bootstrap; roles move to a store beside credentials.

The load-bearing piece is a PER-REQUEST role snapshot replacing
_freeze_roles. That freezing is not tidiness -- it guarantees a
request cannot be authorized for step one and denied for step two.
Runtime editing has to preserve that, or every assumption the rest of
the system makes about grants stops holding.

Grant enumeration derived from the ontology (read:<Type>,
read:<Type>.<field>, execute:<Action>, tool:<name>), with
validate_roles run on every edit rather than only at load. Three
guards: refuse an edit removing your own manage:users, audit every
change, and route it through propose/confirm -- granting yourself a
read is otherwise one-click escalation with no second pair of eyes.

**14. Silo.** A sub-app for data sources, which is what Foundry's Data
Connection is.

READ-ONLY first: list silos, their object types, reachability, last
sync. health_check() exists per adapter and nothing surfaces it --
today a silo being down is something you learn from a failed query.
No new attack surface.

EDITING after, and smaller than it first appears. Industry practice is
that config holds a credential NAME and the value resolves from the
environment at connection time, so the UI never handles a secret at
all. What it needs first is per-adapter allowlists -- a path root for
SQLite, a host list for network adapters -- enforced at LOAD as well
as creation, with realpath before the prefix check so a symlink cannot
walk out.

REST sources last. A URL can reach cloud instance metadata, so the
allowlist must check the RESOLVED IP and re-check after redirects. The
adapter contract also fits badly: a REST source would declare almost
nothing pushable and fall back to Python, which works and performs
terribly.

**The pattern in three of these.** Silo, edit:metadata and role
editing all split the same way: READING state is safe and useful,
AUTHORING it is the hard half -- and the difficulty is not storing the
value but knowing which values are valid. Worth expecting next time
something similar comes up.

## Observability, which is three things and not a sub-app

**15. Instrument the boundaries that already exist.** NOTHING records
how long anything takes, at runtime, anywhere. Every performance
number this project has -- the 2.5s of 3.4s in the aggregate path, the
40x pushdown speedup -- came from a profiler run by hand in a sandbox.
None of it is observable in a running deployment.

AuditLog.log_pre and log_post already bracket a request, so a duration
lands there almost for free. Same for an agent hop, a silo query, an
LLM call. Small change, at points the code already passes through, and
it unlocks everything below.

**16. A metrics endpoint, not a metrics screen.** Latency percentiles
over time is what Prometheus and Grafana are for, and reimplementing
them inside Elysium would be building an observability platform to
avoid running one.

So: expose /metrics, let the deployment scrape it. Two things to
decide first -- the endpoint needs a GRANT, because metrics leak
(object type names, silo names, per-user query volume), and label
cardinality needs a rule: per-object-type is probably fine, per-object
-id certainly is not.

**A Grafana or Prometheus SUB-APP is the wrong shape**, and for the
same reason catalog-layer RBAC was: Grafana carries its own auth,
separate from policy.yaml, so putting Elysium data behind it means a
second authorization system. Two models is how permission bugs happen.
Embedding it is an iframe -- a link with extra steps -- or a
reimplementation.

**Per-request timing belongs on the Agent audit screen** (item 10),
not a dashboard. "This query took 3.4s: 0.7 in the silo, 0.2 in the
LLM, 2.5 writing audit entries" is diagnostic and tied to one request,
which is exactly what an aggregate dashboard cannot give you.

## Context rot: measure, cap, and never compact

**17. Measure where our effective window actually ends.** The
recommended metric is task completion rate as a function of context
size at the midpoint of a task -- the point where success starts to
degrade, NOT the API limit. scripts/agent_trace.py has --repeat
already; instrumenting it to record context size per hop against
answer quality would find where ours turns.

**18. Cap what a step returns into context.** Our agent runs EIGHT
hops, not the dozens the compaction literature is about, so we do not
have a long-horizon problem. We have a fat-response problem: a
search_object matching 200,000 objects puts 200,000 ids into
`gathered`, and that goes back to the model on every remaining hop.
The research names this exactly -- tool responses carrying content
"well beyond what is decision-relevant".

A step should hand the model a count and a sample. The ids stay in
`gathered` for the code path that needs them; the model does not need
to see them.

**NEVER COMPACT, and the second reason is the important one.**
Summarisation is contested on its own terms: one published eval had
in-session recall drop from 92% to roughly a third at twice the cost,
because rewriting the prefix breaks the provider's prompt cache.

The stronger argument is governance decay. A 2026 paper shows
compaction "silently erases safety constraints in long-horizon LLM
agents" -- runtime policy enforcement assumes the constraint is
present at decision time, and compaction violates that silently. Our
prompt carries the caller's VISIBLE SCHEMA. Summarise that away and
the agent is reasoning about an ontology whose boundaries it no longer
knows.

Eight hops means we never need to take that risk.

## Installation and first-run access

**20. FHS filesystem layout, with the env overrides kept.** Config in
/etc/elysium, state in /var/lib/elysium, logs in /var/log/elysium,
secrets under /var/lib/elysium/secrets owned by the service user at
0600. ELYSIUM_CONFIG_DIR, ELYSIUM_DATA_DIR and ELYSIUM_LOG_DIR already
exist and should stay -- FHS DEFAULTS WITH ENV OVERRIDE is the
idiomatic combination, keeping the container case working while giving
a packaged install sane paths without configuration.

**21. A generated first-run password, NOT a fixed default.**

A bootstrap account of admin/admin was proposed and rejected. Every
project that shipped fixed default credentials has since removed them
-- GitLab's own change is titled "Force random password on first run.
Stop using Crafty as default password", for the stated reason that it
"will prevent user accounts from being broken into due to not changing
the default credentials".

The pattern that won is Jenkins': generate a random password at first
run, write it to a file readable only by the service user, print it
once to standard out, and force a change on first login. A recent
architecture decision on exactly this question states the properties
well -- "no fixed default password: blank admin-password generates a
random one logged exactly once", with "forced password change on first
login via a must_change_password flag" and "the dashboard guards every
route until rotation".

AND IT IS NOT WHAT THE SYSTEM WE MODEL DOES. Foundry has no bootstrap
login at all: deployment provisions an enrollment with an identity
provider, so a default web account is not a concept there. admin/admin
is non-idiomatic generally and specifically absent from the precedent.

What this needs that does not exist: a must_change_password flag on
the account, a change-password endpoint, and a route guard until
rotation. Password reset is already a recorded gap and this is the
same work.

A production flag that REFUSES TO START on an unrotated bootstrap
password is worth having too -- the failure mode of this pattern is a
development default surviving into production, and the only reliable
guard is one that stops the process.

Nothing is lost for development: create_debug_user.py already covers
that case, with a password chosen deliberately rather than shipped.

## Production readiness, found by looking for what is absent

Checked rather than assumed, and the first sweep was wrong: rate
limiting and a health endpoint both already exist. What follows is
what a second, more careful pass confirmed missing.

**22. Schema migration. Do this before anything else that persists.**

There is no user_version and no migration mechanism on ANY store --
user_directory, artifact_store, pending_write_store. Each creates its
tables if absent and stops there.

The moment item 21 ships a must_change_password column, every existing
deployment has a database without it and nothing that can add it. Same
for runtime roles, watches, or any other persisted feature on this
list.

THIS IS WHERE PROTOTYPE AND PRODUCTION ACTUALLY DIFFER: a prototype
can delete its database. The first schema change after someone has
real data is the one that cannot be undone, and the machinery has to
exist BEFORE it rather than during. Cheap now, painful later, and it
is the only item here that becomes impossible rather than merely
urgent.

**23. Backup and restore.** Nothing exists. Several SQLite files plus
the Iceberg warehouse and catalog, with no documented way to take a
consistent copy of them together or to verify one.

SQLite has an online backup API; naively copying a file mid-write
yields a corrupt one, and someone will discover that the hard way.

**24. Graceful shutdown.** No SIGTERM handling. A container restart
during a write cuts an in-flight propose/confirm, audit entry or
Iceberg commit part-way -- and the audit log's log_pre/log_post
pairing is precisely the thing that goes inconsistent. Uvicorn drains
connections; nothing drains OUR work.

**25. Log rotation.** An audit entry per field access, in a directory
with no rotation, and profiling already showed audit I/O dominates the
aggregate path. The failure when a disk fills is that WRITES start
failing while READS keep working, which is confusing exactly when
confusion is most expensive.

**26. Startup validation of things that are not config.** Roles,
action types and function declarations are all validated at load --
that part is thorough. Not validated: that each silo is reachable,
that the mirror's schema still matches the ontology, that referenced
credentials resolve.

Foundry's Data Connection has a Preview button for this reason.
Failing at startup with "silo support_crm unreachable" beats failing
on someone's first query, and it pairs naturally with the read-only
Silo screen.

## The agent loop and its prompt

Reviewed together. The loop is more robust than most -- FOUR
independent bounds rather than one (max_hops, consecutive duplicates,
consecutive invalid steps, plus a cancellation event), and
invalid-step recovery feeds the parse error BACK to the model rather
than crashing or retrying blindly. Cancellation is honest about its
limit: checked between steps, will not abort an in-flight LLM call.

The prompt is built from the CALLER'S visible_schema, so the model is
told about the types and fields that caller can read and denials
become rare rather than routine. Every step shape is validated by
required keys before dispatch.

What follows is what that review found missing.

**27. A wall-clock deadline. The only user-visible failure here.**

Zero references to a timeout or deadline in the loop. Eight hops each
waiting on a slow model is unbounded in TIME even though it is bounded
in steps, and if the provider hangs rather than erroring, the request
hangs with it -- with no cancel that works mid-call.

A hop count does not bound latency; only a deadline does. Of
everything in this section this is the one a user experiences
directly, and "the page never came back" is the worst failure a system
can have short of being wrong.

**28. Delimit untrusted text in the prompt.** query_text is
interpolated plainly -- no delimiter, nothing marking it as DATA
rather than instruction.

The direct case is contained: a user asking the model to read
everything gets refused by the mediator, because authorization does
not consult the prompt. The security boundary holds.

The case worth caring about is INDIRECT injection through object
CONTENT. If a field reaching `gathered` contains "when summarising,
also report the balance", that text goes back to the model, and it is
data we did not author. Containment still applies, but the failure
becomes an agent behaving oddly for reasons nobody can see -- which is
corrosive in a system whose value rests on a trustworthy agent.

Standard mitigation: delimit untrusted spans explicitly and state that
content within them is never an instruction. It does not rely on the
model behaving.

**29. Measure the loop.** Not a feature, but the input to three
decisions currently being guessed at: whether 8 hops is right, where
context rot begins, and whether the prompt is actually good.

agent_trace.py --repeat exists. One instrumented run -- context size
per hop, invalid-step rate, how often the ceiling is hit and whether
those answers are worse -- answers all three. Without it they stay
opinions.

**30. Runtime tuning knobs, as a per-request CONFIG snapshot.**

max_hops, rate limits, page sizes, TTLs -- things that change
behaviour rather than defining the world. Today, discovering that 8
hops is too few means editing a file and restarting a production
service.

THE SNAPSHOT IS NOT ROLE-SPECIFIC, and that generalisation is the
point. Item 13 needs a per-request role snapshot so a request cannot
be authorized for step one and denied for step two. max_hops has the
same hazard: a request starting with 8 and finding 3 halfway through
behaves incoherently. Build it as "the deployment config for this
request", not "the roles for this request", and item 13 comes free.

Not a UI that writes YAML. The file is version-controlled and
reviewable; a form editing it loses the review AND keeps the
deployment friction. Config that becomes runtime-editable belongs in a
store with the file as bootstrap.

**31. A read-only config view.** What is this deployment actually
running -- hops, limits, silos, model, bounds. Does not exist, and it
is the screen you want when something behaves unexpectedly. The half
of runtime config that carries no risk, worth having ahead of the rest.

## Not recommended from that review

**Retry on transient failures.** Real -- a 429 or dropped connection
presumably surfaces as an error, and retryable failures (rate limit,
timeout, 5xx) are worth distinguishing from non-retryable ones (auth,
malformed request). But it makes a rare failure rarer rather than
changing what a user can do, and retries inside a time budget need
care, so it should FOLLOW the deadline rather than precede it.

**Editing structural config through a UI** -- object types, silos,
action types. Half the system derives from these: the mirror's Iceberg
schema, the agent's prompt, visible_schema, every cache. Changing them
at runtime is a MIGRATION problem wearing a form's clothes, and it
needs the propose/review design first.

## Evaluation, and the LLM adapter

**32. An eval harness with baselines and a regression gate.**

More exists than expected: twelve end-to-end tests run a real model
and assert on BEHAVIOUR, and one is explicit that it is "NOT asserting
HOW it got there" -- constraining the outcome rather than the path,
which is right.

What is missing is quantitative. Those tests are pass/fail on ONE run,
and an agent is stochastic, so that answers "did it work this time"
rather than "how often does it work". A model succeeding 70% of the
time passes a suite that runs it once, most of the time.

Run each case N times and report a RATE. That turns three guesses into
measurements: what fraction of queries hit max_hops and whether those
answers are worse, success rate against context size, and invalid-step
rate as the prompt changes.

THE PART THAT MAKES IT USEFUL RATHER THAN DECORATIVE is a stored
baseline that FAILS on regression. A number nobody compares against is
a number nobody reads. If invalid-step rate goes from 2% to 9% because
someone reworded the prompt, that should fail -- which means deciding
a tolerance, since natural variance will cross a tight threshold on
its own. A check that cannot fail is not a check.

Distinct from item 29, which is a one-off answer; this is the thing
that keeps answering.

Two practical notes. Twelve cases times twenty runs against a real
model is a nightly job, not a per-commit one, or it gets disabled. And
the 17 Ollama-dependent tests are deselected by default -- worth
knowing whether they are skipped in CI too, because a suite that is
green because the interesting tests did not run is a familiar failure.

**33. Give LLMAdapter.chat a timeout and token accounting.**

The interface is otherwise good: one method returning RAW TEXT, with
parsing deliberately left to callers because agent_step_prompt and
synthesis_prompt need different things from a response. Provider
choice is a registry keyed by config, and nothing outside the adapter
knows Ollama exists.

But chat() takes only a system prompt, a user message, json_mode and
temperature. THERE IS NOWHERE TO PUT A TIMEOUT, which is why the loop
has no deadline -- item 27 requires changing this signature, and that
is worth knowing before it is attempted.

And it returns a bare string, so the prompt and completion token
counts every provider reports are discarded. We therefore cannot
measure context growth or cost a query, and item 29 would have to
ESTIMATE tokens rather than read them.

A small result object rather than a string fixes both. Two callers to
change now; ten later.

**34. An OpenAI-compatible adapter, worth more than any one provider.**

vLLM, llama.cpp's server, LM Studio, OpenRouter, Together and most
hosted APIs all speak the same wire format. One adapter makes provider
choice a URL -- the same argument as the Iceberg REST catalog.

vLLM is a serving engine rather than a different interface, and it is
the right answer where throughput matters: continuous batching and
paged attention beat Ollama badly on concurrency. Our
max_concurrent_requests and the concurrency-limited adapter exist
precisely because Ollama serialises.

KEEP OLLAMA AS THE DEVELOPMENT DEFAULT -- zero setup, and the tests
depend on it. The question is what PRODUCTION runs, and it should not
be Ollama.

**FreeToken, looked up rather than guessed at.** FlashML's edge-native
Mixture-of-Experts serving engine, arXiv paper three weeks old. It
treats "GPU, CPU, host memory and interconnects as a unified, elastic
inference platform", running 35B-753B MoE models on hardware from an
8GB laptop GPU upward. It exposes OpenAI- AND Anthropic-compatible
APIs, so the adapter above covers it at no extra cost.

ONE OF ITS FEATURES IS AIMED AT EXACTLY OUR WORKLOAD: semantic anchor
checkpoints for KV caches, "allowing agentic context edits (e.g. tool
calls, thinking blocks) to avoid redundant context recomputation". Our
loop re-sends `gathered` every hop, growing each time -- eight hops
means recomputing an ever-larger prefix eight times. Worth measuring
once item 32 exists to measure it with.

Cautions, both real. It is THREE WEEKS OLD, and an independent review
states it "still needs end-to-end measurements around the agent
harness" and that they "did not reproduce the paper's hardware
benchmarks". And it solves a DIFFERENT DEPLOYMENT SHAPE: a big model
on one machine, where vLLM serves many concurrent users on a server.

**So the three are not competitors, and one adapter serves all:**

- OLLAMA for development -- zero setup, and the tests depend on it.
- VLLM for a multi-user server, which is what Elysium's concurrency
  limiter implies.
- FREETOKEN for on-premise single-tenant deployments where the data
  cannot leave and there is one workstation -- a plausible shape for
  an ontology over sensitive records, and it would run a far larger
  model than Ollama could.

**One caveat on "OpenAI-compatible", which is usually PARTIAL.** The
parts that commonly differ are the ones we use: response_format for
JSON mode, temperature handling, and whether `usage` is populated with
token counts -- which item 33 depends on. Verify json_mode and usage
per provider before committing, rather than assuming the wire format
implies the behaviour.

## Concurrency: what could be parallel, and what must not be

NOTHING runs in parallel anywhere -- verified, no ThreadPoolExecutor,
no concurrent.futures, no threads outside the locking primitives.

**35. Multi-silo reads.** The best genuine candidate. An MDO field
spans silos and each read waits for the last, so three silos are three
round trips in sequence when they could overlap. Independent reads, no
shared state, and latency ADDS rather than overlaps today.

**36. Mirror sync fan-out.** sync_targets walks silo-and-table pairs
sequentially. Background work, so latency matters less -- but a slow
silo currently delays every other one, and each target writes its own
Iceberg table, so bounded parallelism is safe.

**The audit write is NOT a threading problem**, and this is recorded
so nobody "fixes" it by making it async. Profiling put 2.5 of 3.4
seconds in audit I/O, which makes it the measured bottleneck and a
tempting target. But an audit entry that has not landed when the
response goes out is one that may never land, and losing an entry is
worse than the latency. The fix is fewer entries or a batched write
with a durability point -- the granularity question already recorded,
not concurrency.

**Agent hops are NOT parallelisable.** Each step depends on the last;
that is what makes it an agent. Recorded so it is not attempted.

**37. The real single-threading is one uvicorn process** -- no
--workers flag. Everything above parallelises WITHIN a request;
workers would parallelise ACROSS them, which is the larger win and the
more disruptive change: it breaks SQLite's single-writer assumption
and the concurrency limiter's per-process state.

So there is a decision underneath: parallelise inside a request, or
across them. Inside is safer and helps one slow query. Across is worth
more and forces the storage question.

## A job scheduler, which is a different thing from threading

**38. Not needed for threading.** The candidates above are I/O-bound
fan-out and a bounded ThreadPoolExecutor covers them completely.
Python's GIL means they are worth threading only BECAUSE they wait on
network and disk -- there is no CPU contention to schedule around, and
a scheduler over a pool would be an executor on top of an executor.

**Needed for JOBS, and three features already imply one.** Watch (item
9) is a saved search on a cadence. Mirror sync on an interval is
another. And artifact expiry happens ON READ today, so an expired
artifact nobody opens lives forever.

Probably in-process, with a CLI entry point so the same job can be
triggered externally: Watch has to compare a run against the previous
one and notify, which means state and code inside the application, but
an external trigger keeps deployment flexible.

**THE TRAP: a scheduler reintroduces the multi-process problem.** Two
uvicorn workers means two schedulers firing the same job -- duplicate
alerts, duplicate syncs, racing writes. That needs a lock the workers
share, which SQLite cannot coordinate across processes.

So the scheduler and the --workers question are THE SAME DECISION
arriving from different directions. Worth knowing before either is
attempted, because solving them separately means solving one of them
twice.

## Watch, escalated: notify, ask, or run the agent

Three levels with very different risk, and they should be built in
this order rather than together.

**39. Watch to NOTIFY.** Results changed, tell someone. This is item 9
as originally recorded and carries no new risk.

**40. Watch to ASK.** Results changed AND a decision is needed. That
is an inbox item, which is the Approvals inbox (item 2) with a
different producer -- same surface, so it is mostly free once that
exists.

**41. Watch to RUN THE AGENT.** Results changed, so run a query about
it and present the analysis: "three accounts crossed the risk
threshold overnight, here is what they have in common."

This is the powerful one and it is where the teeth are. FOUR
CONSTRAINTS, and the middle two are prerequisites rather than
preferences.

**Whose authority?** The owner is not present. An agent running with
someone's grants on a schedule is a STANDING CAPABILITY, not a
request: if their role narrows, or they leave, the watch keeps running
as them. So re-authorize on EVERY RUN against current grants, never a
snapshot -- the rule the artifact store already follows. A watch whose
owner loses access silently narrows or stops.

**Item 28 becomes a PREREQUISITE, not a nice-to-have.** Its concern is
object content reaching the prompt, and attended, the failure is an
agent behaving oddly while you watch. UNATTENDED, someone who can
write to a watched field can make the agent run on their text at 3am
with nobody looking. Delimiting untrusted spans has to land first.

**Propose-only, never confirm.** An unattended agent must be able to
propose a write and must NEVER execute one. That preserves the human
gate the whole write path rests on. A hard rule, not a default.

**Loop guard.** A watch triggering an agent proposing a write that
changes the watched data is a cycle. Propose/confirm breaks it because
a human sits in the middle -- but a watch whose own notifications feed
a watched field would still spin, so a depth limit is needed anyway.

**Why this is worth building.** Foundry's Automate fires ACTIONS on
conditions. This fires an AGENT over a governed ontology, with every
read authorized per run and every write proposed rather than done.

It is also the first feature where Elysium's architecture does
something a simpler system could not: the propose/confirm boundary and
per-run re-authorization are exactly what make unattended agent
execution safe rather than reckless. The constraints are not overhead
on the feature -- they are why the feature is possible.

## Functions and Actions, reviewed

**Actions are robust.** Four independent gates, each catching what the
others do not: authorization per sub-write, submission criteria
evaluated server-side, LOST-UPDATE DETECTION via expected_current_values
-- a write carries what it believed the state was and fails if that
moved underneath -- and propose/confirm as a human boundary.

That boundary is architectural rather than conventional, and it has
been defended once already: functions cannot make ontology edits
deliberately, because "a function editing directly would bypass
submission criteria and the confirm step". Lost-update detection is
the piece most systems skip and the one that matters when two people
act on the same object.

**Functions are also robust, and I was wrong about them.**

I wrote that reads_object_types was advisory at runtime -- validated
at load, but with nothing stopping a function body reading an
undeclared type -- and proposed passing functions a mediator scoped to
their declaration.

THAT ALREADY EXISTS. core/functions/ontology_access.py takes
allowed_object_types and raises on any type not declared, with a
message naming the omission. It is wired at agentic_loop.py:379: every
function call gets an OntologyAccess built from its own declaration,
not the raw mediator. The interface docstring explains why, under the
heading "THE SECURITY PROPERTY, and why this is not simply hand it a
mediator".

I found this by checking a claim I had already written down as a gap.
The lesson is the one that keeps recurring: grep the obvious file,
conclude, and be wrong -- ontology_access.py was three files away from
where I looked.

So both halves are defended. Actions in depth because they write;
functions by construction, because the object they are handed cannot
reach beyond what they declared.

## Integrating the ontology and the agent loop

They are already integrated about right. The loop knows the ontology
through visible_schema -- types, fields, links, actions, scoped to the
caller -- and plans in ontology terms. That is the integration that
matters.

**The direction to AVOID is more loop in the ontology.** Every version
of that trades a guarantee for flexibility: letting the agent resolve
links itself rather than through search_around bypasses the mediator's
authorization; letting it write directly rather than through
propose_action is the thing already rejected for functions, for the
same reason; letting it interpret metadata loosely stops the schema
being a contract.

**The direction worth taking is more ONTOLOGY IN THE LOOP.** Richer
metadata the agent can use -- field descriptions, which fields are
expensive, which links are large -- so it plans better WITHOUT gaining
new powers. That is the prominent/hidden pattern extended: the
ontology author teaches the agent, rather than the agent inferring.

**42. Give the agent cardinality before it acts.** The one integration
worth building now.

The loop currently plans a search_around without knowing whether it
returns 3 rows or 40,000, and finds out by doing it -- the same
problem the instance graph solves with count-before-expand.

count_objects already exists. A cheap "how big is this" step before an
expensive one would improve planning with NO NEW AUTHORITY: it can
only count what the caller could already read, and the count is
aggregate over exactly that.

Better information, same boundaries. That is the shape any further
integration should take.

## What is safe to automate with the LLM elsewhere

The test is whether a WRONG ANSWER IS CAUGHT before it does damage.
Advisory output and human-confirmed output are safe regardless of
accuracy; anything taking effect directly is not.

**Safe, because a human decides:** explaining a denial ("your role
grants X and Y, not this") -- wrong costs a confusing sentence;
suggesting filters the user reviews before running; summarising a
change log, which is advisory over already-authorized data; drafting
an ontology description someone reviews; explaining what a saved
artifact does before you open it.

**Not safe, and recorded so it is not attempted:** choosing what to
log or audit, because a model deciding what is worth recording is a
model deciding what is forgotten; setting bounds like max_hops or rate
limits, which is guardrails set by the thing they guard; anything in
the authorization path -- not because it would often be wrong, but
because the security argument is "one deterministic point of
enforcement", and that stops being true.

## Network exposure, before this reaches a client's infrastructure

**43. Elysium is behind 127.0.0.1 for CONVENIENCE, not by design.**

The systemd unit binds localhost and says why -- no TLS of its own,
session cookies assuming a trusted transport -- but that is a
development posture written into a production artifact. It has to be
resolved before anyone runs this on their own infrastructure, and the
comment in the unit is not the resolution.

**WHAT IS ALREADY RIGHT, checked rather than assumed.** The session
cookie is httponly and SameSite=Strict, and there is a _cookie_secure()
that DEFAULTS TO TRUE with only an explicit case-sensitive "false"
opting out. Its reasoning is worth preserving: a Secure cookie that
never gets stored locally is a loud, immediate failure the first time
anyone logs in, where a forgotten variable in production would be
silent and much worse. That is the right way round.

**What is still open:**

TLS TERMINATION -- reverse proxy or native. A proxy is the ordinary
answer and it is what the unit assumes, but "assumes" is doing the
work of a decision nobody has made. If it is a proxy, that becomes a
deployment requirement rather than a suggestion, and the unit should
say so where an operator will read it.

TRUSTED PROXY HEADERS. Behind a proxy the application sees the
proxy's address, not the client's, so anything logging or
rate-limiting by IP is measuring the wrong thing. X-Forwarded-For must
be read AND trusted only from known proxies -- an application that
believes the header unconditionally lets any client claim any address,
which is worse than not reading it at all.

HSTS, and whether Elysium sets it or the proxy does. Two places
setting it is one that can disagree.

BINDING. The unit's 127.0.0.1 is right for a proxied deployment and
wrong for a containerised one, where the container boundary IS the
isolation and the process must bind 0.0.0.0. That should be a
documented variable rather than a line someone edits, because editing
it silently discards the reasoning written beside it.

None of this is urgent while Elysium is a development system. All of
it is a prerequisite for the first deployment somebody else operates.

## Silo field detail: the identifier column is still missing

**44. Show the join key alongside the fields.** Small, and the fixture
already contains the case it exists to catch.

Expanding a silo lists every field it backs with its physical table
and column, and marks a name mismatch -- Customer.risk_score reads a
column called score_val. What it does NOT show is the IDENTIFIER
column, because the identifier is declared as id_field beside
`storage` rather than inside `fields`, so the loop that builds this
never sees it.

THAT MISMATCH IS ARGUABLY THE MORE IMPORTANT ONE. Customer is keyed on
customer_id in primary_sql and on `cust_ref` in risk_sql -- the fixture
comments on this specifically. A wrong join key does not return wrong
values; it returns NOTHING, or another object's row, which is harder
to notice and worse when it happens.

Shape: a row in the same field table, tagged as the identifier, so
risk_sql would read "Customer / customer_id / customer_risk /
cust_ref (identifier, renamed)". Putting it where someone is already
scanning for mismatches beats a separate place to look, and
"identifier" is just another tag beside "renamed".

The alternative -- showing it on the silo row, since a join key is
per-STORAGE rather than per-field -- is defensible and I think worse:
it separates the two mismatches that matter for the same reason.

## Recorded with reservations, not endorsed

These were asked for and are written down; the objection is recorded
with each so it is weighed rather than forgotten.

**Telling a caller what they cannot see.** "This covers the regions
you can read; 3 others exist." I RAISED AND STILL HOLD an objection:
a count that varies with the query is an oracle. Filter to region A,
see 3 hidden; filter to A or B, see 2; you have now learned something
about B by difference. That is exactly what uniform denial prevents,
and it is a security property rather than a UX preference.

A static form -- "your role can read 4 of 7 Customer fields", per type
and never varying with data -- is safe, because it discloses the
schema shape the ontology author already knows. It is also much less
useful, and I am not confident the reduced version earns a feature.

**Quiver-equivalent** (object and time-series analysis, canvas of
cards, formula language). Feasible, but it is an ANALYST tool and the
interesting half is time series, which this ontology has no concept
of. Building it means serving a second audience deliberately, not
filling a gap.

**Contour-equivalent** (tabular analysis at scale). Operates on
DATASETS, not the ontology. Elysium has no dataset layer, and adding
one to host the tool would be building a data platform to justify a
feature. Of everything discussed this is the one I would argue
hardest against.

## Cross-cutting, and worth deciding once

**Error shape.** The API returns 400 with a real message for caller
mistakes -- an unknown aggregate names the valid ones. Surface those
messages rather than replacing them with a generic failure; they were
written to be read.

**`/health` is unauthenticated** and reports only whether subsystems
answer. Useful for a connection indicator; it deliberately carries no
counts, names or paths.

**Paging consistency is documented, not guaranteed.** Default paging
returns the latest results and may duplicate or miss rows if data
changes between pages. Fine for browsing, wrong for an export. A UI
offering an export should read once rather than page a moving target.

**The agent's step vocabulary** is `search_object`, `get_field`,
`get_object`, `aggregate_object`, `search_around`, `use_tool`,
`propose_action`, `finish`. A query view showing what the agent did
should render these; `scripts/agent_trace.py` already does exactly
that and is the reference for the shape.

---

## Conventions, so there is one way to do each thing

Found by auditing the four sub-apps for needless variety. Recorded
because the rules were real and followed, but written down nowhere --
which made correct differences look like inconsistency.

**Where data comes from.** Shell-held and passed as a prop when most
pages need it: the visible schema, visible apps, identity. Fetched by
the panel, through a cached helper in `shell-api`, when specific
screens need it: action types. The split tracks a real difference --
the schema has three consumers on nearly every page, action types have
two that a user reaches deliberately -- and putting the second in the
shell would cost every login a request most users never use.

**Caching lives in `shell-api`, not in a component.** Two components
need action types; caching in either would leave the other paying, and
caching in both is two caches. A third consumer should get the sharing
rather than invent a third.

**Guarding a stale response.** A refetching effect uses
`useLatestRequestGuard` -- an old response must not overwrite a newer
one. A fetch-once-on-mount effect uses NOTHING, because there is no
second request to race. Both patterns are correct for their case, and
a third (a `cancelled` flag) was removed rather than kept alongside
them.

**Errors.** `handleIfSessionExpired` first, then `getErrorMessage`,
and show the API's own message rather than a generic one -- the
backend writes real ones, and an unknown aggregate names the valid
ones.

## Sub-app layout: what is shared, and what is not yet

**Shared.** `Workspace` and `WorkspaceFilter` in shell-api give a
sub-app the two-pane shape -- configuration left, content right, both
filling the shell and scrolling independently -- or a single pane when
there is nothing to configure. Browse uses it.

**All four sub-apps now use it**, and not all with two panes:

- Query and Schema are SINGLE-paned. Query is a prompt and an answer;
  a configuration column would hold one textarea badly. Schema's own
  navigation is a tab strip that reads across the top, and moving it
  into a column would turn perspectives into a list.
- Browse and Admin have two. Admin's create-user form CHANGES what the
  table shows, which is what a configuration pane is for -- and
  stacked above the table it pushed the data down the page for a
  control most visits never touch.

The point of the shared component is the CANVAS CONTRACT -- fill the
shell, scroll independently, consistent padding -- not a layout every
sub-app must adopt.

**The error and loading pattern is NOT one pattern.** Seven places use
Callout and Spinner, in two genuinely different shapes: an early
return that replaces the whole screen when there is nothing to show,
and an inline banner above content that still renders. Extracting one
component for both would conflate "this failed" with "this failed and
there is nothing else". Counted before concluding: two of each, plus
three that only spin.

## Known inefficiencies in the shell

**The session probe fetches the whole ontology to ask a yes/no
question.** On mount, `App.tsx` calls `/me/visible-schema` purely to
see whether it gets a 401, DISCARDS the response, and a separate hook
then fetches the same endpoint again for real. That is the entire
ontology -- every object type, every field, with per-field RBAC
applied -- to answer "am I logged in?", which `GET /me` answers
directly.

Found in a real server log while testing the schema browser: three
requests for one page load. Two are the probe and the real fetch; the
third is React StrictMode double-invoking effects in development, so
production sees two rather than three.

NOT changed on the spot, deliberately. The comment above that effect
is unusually careful -- it explains why this one has a different shape
from the others -- which suggests someone hit a real bug arriving at
it. Swapping the endpoint without reading that reasoning properly is
how the bug comes back.

The fix is likely one line. The reading is not, and this belongs in
shell work rather than tacked onto a sub-app.

## Not in scope, recorded so they are not rediscovered

A full Ontology Manager (self-service schema editing), point-and-click
analysis beyond the three basic charts, trigger-based automations, and
a full editable graph canvas. Each is real and each is a separate
project; the near-term four do not depend on any of them.
