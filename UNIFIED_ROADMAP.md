# The unified roadmap

**Why this exists.** Nine planning documents hold roughly 8,500 lines
between them. Each is right about its own area and none can say what
to do next, because the answer depends on the others. This file is the
ordering; the detail stays where it is, and each item names its home.

**How it is ordered.** By dependency and by what would stop a
deployment, not by size or by interest. An item appears after
everything it needs and before everything that needs it.

**What this is not.** It is not a schedule and it does not estimate.
Several items below are a day and several are a month, and saying
which would be a guess presented as a plan.

---

## Phase 0 — Elysium cannot read a customer's data

Everything in this phase is a blocker for any commercial use. None of
it is interesting and all of it is required.

### 0.1 An adapter for a real database

**THE SINGLE LARGEST GAP.** `_LLM_ADAPTER_REGISTRY`'s sibling holds
exactly one read adapter: `sqlite`. There is no PostgreSQL, MySQL,
Snowflake, REST or object-store adapter. The ontology is genuinely
silo-agnostic and the mirror is Iceberg — and there is nothing to
connect to a customer's actual data.

ROADMAP.md discusses PostgreSQL at length, but as ELYSIUM'S OWN STORE,
which is a different question and correctly deferred. Reading a
customer's PostgreSQL is mentioned once, in passing, and planned
nowhere.

**Blocks:** every commercial conversation. A prospect's first question
is whether it reads their warehouse.

**Depends on:** nothing. The adapter interface already exists and has
two implementations (`sqlite`, `inmemory`) — which is the two-reference
test a plugin surface is supposed to pass.

### 0.2 A row limit that reaches the query

`search_object` takes no limit. It returns every matching id, MAC
filtering happens after the fetch, and the adapter's read is a bare
`fetchall()`. API paging is cut in Python from a `total` already in
memory.

A ten-million-row table is therefore a ten-million-row fetch into
Python, per request, before filtering. Invisible on the dev fixtures;
an OOM on the first real query.

**Blocks:** 0.1 being usable. An adapter for a real database without
this makes the failure worse, not better, because real databases hold
real volumes.

### 0.3 A bound on the security cache

`_security_value_cache` and `_security_link_cache` are per-generation,
cleared only at the start of a bulk prefetch, and otherwise accumulate
one entry per object ever security-checked. One mediator lives until a
configuration reload.

A long-running deployment reading many distinct objects grows memory
monotonically. Invisible in testing, fatal in production.

**Blocks:** any deployment that stays up for a week.

### 0.4 A silo query timeout

No adapter sets one. A slow or hung source blocks a worker
indefinitely, and there is ONE worker process — so a few hung queries
stop the service entirely.

**Depends on:** 0.1 in practice. SQLite on local disk rarely hangs; a
network database routinely does.

---

## Phase 0.5 — The mirror becomes the read path

**DECIDED:** `read_from_mirror` defaults to TRUE, and direct silo reads
become a secondary option on the way to deprecation. The mirror was
always meant to be the default; it shipped as opt-in and commented out.

This phase sits here because a PostgreSQL adapter that feeds an
opt-out mirror is a different piece of work from one that feeds the
only read path.

**WHAT THE PIPELINE IS**, verified rather than assumed: the sync reads
the source and writes BRONZE as strings, unaltered -- "the one
representation that cannot lose information it was given". SILVER
reads BRONZE, not the source, and coerces to the declared types.
Elysium reads silver.

That matches the medallion pattern exactly: bronze preserves
everything and transforms nothing, silver is where type casting
happens, and each boundary is a contract that should be explicit.

### 0.5.1 ~~Flip the default, and say what an empty mirror means~~ DONE

`read_from_mirror` defaults to TRUE. Browse distinguishes a
never-synced mirror from an empty one -- "Not synced yet", naming
run_sync -- using a signal the server already sent and only the
freshness line used.

**WHAT THE FLIP BROKE, all one cause:** 279 errors, every test
deployment failing with "unable to open database file". The read path
builds a SqlCatalog against a directory that may not exist, which was
harmless when mirror reads were opt-in. Created on demand now.

The integration fixture declares `read_from_mirror: false` EXPLICITLY:
those tests predate the mirror and assert against real silo data
without syncing. When the live path is deprecated, that line is the
list of what has to change.

### 0.5.2 A `decimal` type, alongside `number`

**MEASURED LOSS.** `coerce()` sends `number` through `float()`, so
`'1234.56789012345678901'` becomes `1234.567890123457`. Money silently
becomes a different amount.

Bronze holds the string, so a corrected silver can be rebuilt WITHOUT
re-reading the customer's database -- which is what bronze is for. The
loss is recoverable, not permanent, and that is the only reason this
is not an emergency.

ALONGSIDE, NOT INSTEAD, following every layer we touch: Foundry has
Double and Decimal as separate base types, Iceberg has `double` and
`decimal(P,S)`, PostgreSQL has `double precision` and `numeric`. They
answer different questions -- a decimal needs a declared precision and
scale, a float does not. Floats for measurement, decimals for money.

`pyarrow.decimal128(P, S)` round-trips exactly; verified.

**AND A LINTER NOTE**, in the spirit of the `title_field` one: warn
when a field named like money -- amount, price, total, balance -- is
declared `number`. The mistake is cheap to make and expensive to find.

### 0.5.3 Dates are strings, and range filters on them are wrong

**A BUG, NOT A MISSING FEATURE.** The ontology has no date type;
`field_types.py` defers it deliberately and names the reasons
(timezone handling, parse-failure behaviour, format declaration). The
reasons are good. The consequence is not.

Dates stored as strings compare lexically. ISO-8601 sorts correctly BY
LUCK. Everything else does not, measured:

    '2026-1-5'  sorts AFTER '2026-02-03'   (unpadded month)
    '01/05/2026' sorts before '02/03/2026' (year ignored entirely)

So a `date_range` filter for "after February" returns a January row
and nobody is told.

`core/filters.py` already has a `date_range` operator restricted to
strings, with a validator -- but it validates the FILTER's bounds with
`fromisoformat`, never the STORED data. A well-formed filter still
compares against malformed values.

What a real type needs to answer, which is why it was deferred: what
timezone a naive timestamp means, what a parse failure does (drift, on
this project's own precedent), and whether a format is declared or
inferred.

**DECIDED: THREE TYPES, MIRRORING ICEBERG.**

- `date` -- no time, no zone, NEVER converted. A birthday is not an
  instant, and "converting" it is the classic bug where someone's
  birthday moves a day for users in Auckland. Arrow `date32`.
- `timestamp` -- a wall-clock reading with no zone, stored exactly as
  given. The literature calls these "local observations of time
  recorded in an unspecified time zone", and disambiguating them "a
  common data cleaning problem".
- `timestamptz` -- a true instant, stored UTC. Iceberg's spec:
  "values are stored as UTC and do not retain a source time zone".
  PostgreSQL's reason for timestamptz is the same -- it "guarantees
  that the precise moment in time is stored... in UTC", which
  "eliminates many time arithmetic problems, and ensures portability".

**A NAIVE TIMESTAMP IS NOT PROMOTED BY GUESSING.** Assuming UTC is a
guess; assuming the server's zone is worse, because it makes the same
data mean different things on two machines -- the exact coupling
storing UTC is meant to remove. A field may OPTIONALLY declare its
source zone (`timezone: "America/New_York"`) to be promoted to an
instant. Declared, never inferred.

**THE CHAIN ALREADY SUPPORTS THIS**, verified rather than assumed:

- All 22 `datetime.now()` calls in core/, api/ and scripts/ pass UTC.
  Not one naive timestamp.
- The sync's timestamp is `fromtimestamp(..., tz=UTC)`, explicit.
- `isoformat()` puts the offset on the wire: `...+00:00`.
- Bronze stringifies with `str()`, which PRESERVES the distinction:
  a date has no time, a naive timestamp has no offset, an instant
  carries one. Measured.

**AND THE SOURCES DIFFER IN A WAY THE ONTOLOGY ALREADY HANDLES.**
SQLite has no date type and returns strings for all three shapes,
indistinguishable. psycopg returns `date`, naive `datetime`, and
UTC-aware `datetime` respectively. The ontology's declaration is the
authority either way, which is what it was designed to be.

**THE UI NEEDS TWO FORMATTERS, and has neither.** `formatTimestamp`
renders RELATIVE time ("3 minutes ago"), which is timezone-independent
by construction and sidesteps conversion entirely. The moment an
absolute date is shown -- a transaction date, a contract start -- a
`date` must render as-is and a `timestamptz` must convert to the
viewer's zone. Two formatters, built when the types land, so the UI
cannot accidentally convert a birthday.

**DISPLAY CONVERSION BELONGS IN THE UI, NOT THE MIRROR.** If the
mirror converted, what is stored would depend on who is looking.

### 0.5.35 Record what the SOURCE said its types were

**A GAP FOUND BY ASKING, then measured.** Coercion asks only "can this
value become the declared type?" -- never "is the source still saying
what it used to say?". So a source change that still coerces passes
silently. Three, measured:

    timestamptz -> timestamp    '...14:30:00+00:00' becomes
                                '...14:30:00'. The offset vanishes and
                                both coerce as strings. A DIFFERENT
                                KIND OF FACT, not a different value.
    numeric -> float            '10.50' becomes '10.5'. Both are valid
                                decimals; the scale changed.
    integer -> text             ' 42' still passes int(). Formatting
                                changed invisibly.

What we ARE protected against is a change that makes values
UNCOERCIBLE -- that fails loudly, silver holds, bronze keeps the
evidence. That covers most schema accidents. These three are the
remainder.

**THE PRECEDENT IS DEBEZIUM'S SCHEMA HISTORY.** It keeps "a log of
every DDL statement it has observed" and "for each change event...
records the schema version that was active when that event was
captured", so "consumers can reconstruct the exact schema for any
event by replaying the schema history".

The problem has a name and a reputation: "undetected schema drift is
one of the top causes of pipeline failures and silent data corruption
-- a column type change can cause data truncation or loss without any
error". The standard remedy is to compare "current schemas against
baselines" and alert.

**AND ELYSIUM ALREADY HAS THIS PATTERN, ON ONE SIDE ONLY.**
`config_history` exists precisely because a generation recorded WHICH
load it was and not WHAT IT SAID -- so "what did generation 7 contain"
had no answer. That is the same question, asked of our ontology.
Nothing asks it of the source.

**PER COLUMN, PER SYNC -- NOT PER VALUE.** Per-value type tags double
bronze's size to record a property of the COLUMN, and a row that
disagrees with its column is the drift already caught. Column types
belong beside `elysium.source_silo` and `elysium.source_table` in
bronze's table properties, which already exist for provenance.

**IT NEEDS AN ADAPTER METHOD THAT DOES NOT EXIST.** `columns_present`
returns names only. So this lands with the PostgreSQL work, where the
driver exposes types cleanly and a second implementation proves the
interface is not SQLite-shaped.

**SQLITE CAN ONLY ANSWER WEAKLY**, and that is honest rather than
disqualifying. `PRAGMA table_info` gives the DECLARED type, which
SQLite treats as advisory -- a column declared INTEGER can hold
'banana'. Recording "the source said INTEGER" still detects someone
altering the table, which is the case being caught.

**A NOTE ON POSTGRESQL**, from the same research: Debezium cannot get
DDL events from PostgreSQL's logical decoding at all -- "schema change
events are not separately published. Instead, any schema modifications
are only reflected as part of the data change events themselves". So
polling the catalog at sync time is not a shortcut; it is what the
established tool has to do too.

### 0.5.4 ~~A mirror administration surface~~ FIRST HALF DONE

**WE BUILT AN INTEGRITY GUARANTEE AND LEFT IT INVISIBLE.** Proven
behaviour: a value that cannot be coerced fails the whole table's
sync, silver keeps its previous snapshot untouched, and bronze accepts
the bad value anyway so it can be diagnosed. Exactly right.

The only trace is stderr on whatever ran the sync. A user sees data
three days stale and an administrator cannot find out why from inside
the product.

Admin has Users, Silos, Deployment Config and Metrics. Nothing shows
the mirror. What it should show:

- Per table: last successful sync, bronze and silver row counts. A
  divergence between those two IS the drift state.
- The last failure, with the offending column and value -- already
  computed and currently discarded.
- Snapshot history, which Iceberg records anyway, making "roll back to
  yesterday" a visible option rather than surgery.
- Sync now, so recovery does not need shell access.
- `check_mirror` and `repair_catalog` results.

**BUILT:** Admin -> Mirror. Per table: last synced, rows SERVED
(silver) and rows FETCHED (bronze), with the divergence NAMED rather
than left as two numbers to compare -- "fetched but not served, the
last sync was refused". Integrity problems from check_mirror above the
table. A live deployment says so rather than showing a blank page.

**AND THE LAST ATTEMPT, which the panel's own first run demanded.**
Snapshots record when data CHANGED, so a sync that ran and was refused
leaves exactly what a sync that ran and found nothing leaves. A table
refusing every sync since Tuesday looked identical to one whose source
had not changed since Tuesday.

`core/mirror/sync_attempts.py` records one row per table per attempt
-- synced or refused, with the full drift report on a refusal -- and
the panel shows it beside the change date, with the reason above the
table.

**STILL OPEN:** snapshot history and roll-back, and a Sync now button.
Both need endpoints that DO something rather than report, which is a
larger security question than reading.

**THE GENERAL POINT:** operational tooling here is all scripts
requiring a terminal on the host -- check_mirror, repair_catalog,
run_sync, measure_prompts. For a commercial product that is a support
burden, and the workaround audit should have caught it. This closes
the reading half of check_mirror only.

### 0.5.5 ~~Report every drifted column at once~~ IT ALREADY DID

**THE ENTRY WAS WRONG.** It was written from reading `drift[0]` in the
raise, without checking what `describe_drift` does with the rest --
which is name every one, with the offending value and the rows
checked. Measured with three bad columns: all three reported.

What was actually wrong was smaller. The HEADLINE named one column
when several were affected, inviting someone to fix that column,
re-run, and discover the next a full read of the source later. It now
says how many others, with the verb agreeing.

**A reminder that a roadmap entry is a claim like any other.** This one
had been recorded twice and would have cost an afternoon building
something that existed.

### 0.5.6 Pin one mirror snapshot per request — OPEN QUESTION

Iceberg gives snapshot isolation and Elysium gets it free: verified
that a reader holding an old scan keeps seeing its own version while a
new reader sees the sync's result. Both served correctly, at once.

**UNVERIFIED:** whether one HTTP request pins ONE snapshot for its
whole duration. A request reading Customer then Transaction, with a
sync landing between, could see two generations of the mirror.
Elysium already pins the CONFIGURATION generation per request for
exactly this reason; the data equivalent may not be.

---

## Recorded for later: what a snapshot sync cannot recover

**CURRENT STATE IS NEVER MISSED.** Elysium is snapshot-only, so a sync
after any amount of downtime picks up whatever the source holds now.
Measured: offline while a row changed twice and two rows were added --
all three rows present afterwards.

**INTERMEDIATE STATES ARE LOST.** A row that went new -> in_progress
-> done while Elysium was away is recorded as new -> done. The
changelog records what the mirror OBSERVED, not what happened.

**AND THAT IS NOT ELYSIUM DISCARDING SOMETHING RECOVERABLE.** A normal
SQL table does not keep its own history either; `in_progress` is gone
from the source too. Retrieving it needs the source's WAL or binlog,
which is what CDC exists for -- the same conclusion the schema-drift
work reached from the other direction.

**SO "ELYSIUM IS IN SYNC" IS TRUE OF STATE AND FALSE OF HISTORY**, and
nothing says so. Worth stating before a customer assumes otherwise.

### And the measured case for snapshot has a gap in the measurement

ROADMAP.md closed incremental syncs with numbers -- 500,000 rows in
2.46 seconds, linear, ten million about a minute -- and with the
better argument that SNAPSHOT propagates deletes while APPEND cannot
see a deleted row at all.

**THOSE NUMBERS MEASURE ELYSIUM'S TIME, NOT THE SOURCE'S LOAD.** They
were taken against local SQLite. Reading 500,000 rows from a
customer's production database every five minutes is a real cost to
THEM, and nothing here has measured it.

That does not make APPEND correct. It makes the honest position:
snapshot is right, its true cost is borne by the source, and CDC is
the answer that is both incremental and delete-aware.

## Recorded for later: a diagnostic sweep

**THE PIECES EXIST AND ARE SCATTERED.** Adapter reachability is in the
Silos panel, bronze and silver in check_mirror, integrity in
check_mirror and repair_catalog, subsystem liveness in /health,
provenance in read_manifests.

**WHAT IS MISSING IS TRACING ONE ROW END TO END** -- silo, bronze,
silver, mirror, ontology -- and asserting it is the same row. That is
a different check from "each layer looks fine", and it is the one that
catches a pipeline whose layers are individually healthy and
collectively wrong.

**SHOWN AS THE PIPELINE ITSELF**, each stage lighting up as it is
checked, rather than as a list. A break between two ticks says where
to look without reading anything. The progress matters too: a sweep
that shows what it is doing is a sweep people run.

**AND THE HELP ASSISTANT CLOSES IT.** "bronze holds 7, silver holds
67" is only useful to somebody who already knows what that means.

## Recorded for later: read-through with background refresh

Not for now, and worth not losing. A read could trigger a fresh source
read so data is never stale -- but done naively it makes read latency
depend on SOURCE latency, which is the property the mirror exists to
remove. One slow source and every reader waits.

The established shape: serve the mirror immediately, trigger the
refresh in the BACKGROUND, let the next read get the newer data. Fast
reads and catch-up both.

This is where the live-read path earns its keep after deprecation as a
primary mode -- as the refresh mechanism rather than the serving one.


## Phase 1 — A deployment that survives its own operation

### 1.1 Persist the pending write store

In-process memory, stated plainly in its own docstring. A restart
loses every approval awaiting decision.

For a product whose pitch is that writes are mediated and approved,
losing the queue on deploy is the worst fit between claim and
behaviour. ROADMAP.md establishes SQLite suffices and that the rebuild
is blocked on its DESIGN — who may see a queued write across a
restart, and what a reload does to one proposed under an older
generation — not on storage.

**Depends on:** nothing technical. Needs the design decision made.

### 1.2 fsync before the catalog pointer swap

Researched. pyiceberg writes metadata through an unsynced path while
SQLite fsyncs its own commit — so the POINTER is durable and the thing
it points to is not, which is exactly backwards and precisely why a
crash strands a table rather than losing a commit.

Two fsyncs, not one: the file, then its parent directory, or the
directory entry may not survive. Cost is 1–4ms each on an SSD without
power-loss protection, which is nothing against a sync's normal
duration. Never retry a failed fsync. Consumer SSDs may acknowledge a
flush before committing to NAND, so this narrows the window rather
than closing it — worth stating in the code.

`scripts/repair_catalog.py` already makes the damage survivable.

### 1.3 Backup and restore

Five SQLite databases — credentials, write_log, config_history,
metrics, artifacts — plus an Iceberg warehouse, and no script that
captures them consistently. Copying them while running tears across a
write.

**THE CHANGELOG IS THE ONE THING THAT CANNOT BE REBUILT.** Bronze and
silver derive from the silos; history does not.

**Depends on:** 1.2, so that what is captured is itself consistent.

### 1.4 Secret indirection in configuration

`data_silos.yaml` holds hosts and credentials with no `${ENV_VAR}`
expansion or secret-store reference. Anyone pointing Elysium at a real
database puts that password in a config file — and the manifest work
means it can now reach the lake.

**Depends on:** 0.1, which is when real credentials first exist.

---

## Phase 2 — Decisions already made, waiting to be built

### 2.1 Query's two buildable parts

QUERY_PLAN.md. Deployment-stated example questions, and keeping the
last question in the box so refining one clause is the default.

The deployment ALREADY states good questions, in
`example_queries.yaml`, and nothing in the web UI reads it. It needs a
display-safe subset rather than straight reuse, because its entries
are user-paired for the CLI runner.

### 2.2 The measurement session's remaining questions

Two of four answered. Aggregates ARE chosen correctly. The one-hop
failure was a wildcard field name, now refused.

Outstanding: whether the pre-flight verdicts earn their keep, and
whether a small model can work without the schema in the prompt. Both
need a re-run; neither was reached.

**AND A MODEL LARGE ENOUGH TO ANSWER THEM.** phi4-mini is ~3.8B, below
the threshold where multi-step tool use works reliably — the observed
duplicate-spiral after a rejection is the documented failure mode of
that model class, not only a prompt defect.

### 2.3 json_each for the write log

Deferred by decision, not forgotten. Removes two `S608` suppressions,
the chunking loop and the variable limit, in exchange for a minimum
SQLite of 3.38 (2022). Verified working.

### 2.4 The remaining UI halves

Vertex-lite's second half, the view-state matrix's other half, and
which other screens show the checkbox-above-the-row problem. Each
small, each verifiable now that browser tests exist.

---

## Phase 3 — Needs research, then a plan, then building

### 3.0 Triggers -- a condition on data, an effect when it is met

**DESIGNED, NOT BUILT** -- see TRIGGERS_AND_PLUGINS.md.

Elysium has none. Foundry's Automate is condition + effect, and the
conditions are ontology-shaped: objects added to, removed from, or
modified in a SET. A set is a saved search, and Elysium already has
saved explorations.

**THE PERMISSION SPLIT IS THE PART TO COPY EXACTLY.** Conditions
evaluate as the owner; action effects execute as the owner;
NOTIFICATION EFFECTS USE EACH RECIPIENT'S OWN PERMISSIONS. With MAC
that is not a nicety -- a notification counting matching rows must
count differently for someone who can see less.

**NOT A FLAW WE HAVE:** an earlier framing asked whether proposing
rather than executing weakens us against Foundry. `auto_execute`
already exists per action type, defaulting to confirmation, enforced
in Python. An automation uses the action's own setting.

**THE REAL RISKS ARE VOLUME:** MAX_SUB_WRITES is 20 and the queue TTL
is 15 minutes, so an automation across a thousand objects floods or
expires. And four-eyes means an owner cannot approve their own
automation's proposal.

### 3.1 The plugin API

The largest item. Research done; no plan written.

**DESIGNED -- see TRIGGERS_AND_PLUGINS.md.** The UI boundary already
exists: five sub-apps importing only from `@elysium/shell-api`, 113
imports across three modules, each lazy-loaded. The work is hardening
a boundary rather than inventing one.

**DECLARE THE CURRENT BOUNDARY THE API, THEN FIND WHERE THE SUB-APPS
CHEAT.** That list is discoverable today; building first and
converting afterwards finds the same list later and more expensively.

**A PLUGIN MUST NOT GET A PRIVATE CHANNEL TO THE AGENT.** It extends
the ONTOLOGY through existing mechanisms -- object types, actions,
functions -- so agent awareness comes free and MAC, submission
criteria, approvals and audit all keep applying.

**THE HONEST SMALL VERSION FIRST:** the adapter registry already IS a
plugin point, loading implementations by name. Formalising THAT —
versioning the contract separately from the app, a manifest declaring
which contract it needs — is much smaller than designing a new surface
and is testable against a second implementation, which 0.1 supplies.

Superset is the closest analogue and instructively modest: extensions
off by default, running in-process, sandboxing planned rather than
shipped, administrators responsible for vetting.

**Depends on:** 0.1, which produces the second adapter that proves the
abstraction is not single-use.

### 3.2 Multiple workers, and the storage question under it

UI_ROADMAP.md states it: `--workers` breaks SQLite's single-writer
assumption and the concurrency limiter's per-process state. One
uvicorn, one core, no horizontal scale, and a deploy is downtime.

The decision underneath is parallelising inside a request or across
them. Across is worth more and forces the storage question.

**Depends on:** 1.1, which is the first piece of state that has to
move anyway.

### 3.25 A help assistant, separate from Query

**DESIGNED -- see TRIGGERS_AND_PLUGINS.md part three.** A chat that
answers questions ABOUT ELYSIUM rather than about a deployment's data.

Precedent is AIP Assist, and the security property is the whole
design: Palantir state it "does not access your data". No MAC, no
submission criteria, no audit of data access, no per-recipient
evaluation.

**A DIFFERENT SUB-APP, NOT A MODE OF QUERY**, because a different
threat model one wrong branch away from leaking is not a mode.

Context without data: knowing which SCREEN a user is on, never which
object. A deployment may register its own runbooks as additional
content, as Foundry allows custom content sources.

**IT MATTERS MORE THAN IT LOOKS.** Elysium's operational surface is
scripts needing a terminal and knowledge of when to use them. An
assistant that can answer "the mirror is stale, what do I do" is the
difference between a product an administrator can run and one they
need us for.

### 3.3 Schema migrations

`CREATE TABLE IF NOT EXISTS` plus hand-written migration functions.
Fine for five tables; a liability the first time a customer holds data
across a version boundary.

---

## Deliberately not doing

Recorded so each is a decision rather than an omission.

**Clarifying questions before answering** — an extra model call per
question, on a system where the model is already the slow part, for a
problem nobody has reported.

**A conversation thread in Query** — Elysium answers questions about
an ontology; the trace beats a transcript, and threading makes "which
generation answered this" much harder to state.

**Roving focus** — results are cards with links, not a grid. Adopting
`role="grid"` without the full keyboard contract would be worse than
the native semantics it replaces.

**Multi-tenancy** — single-tenant by construction, stated in the code.
A business-model decision rather than a defect, but it means one
deployment per customer and that shapes pricing.

---

## Waiting on a trigger, with the trigger named

Sync memory batching (a table too big to hold). The changelog's later
phases (a current view reading through it). Partitioning (a few
hundred megabytes of Parquet). Snapshot expiry (a warehouse whose
history costs more than it is worth).

None of these triggers is met, and building ahead of them would be
guessing at a shape the data has not yet taken.

---

## What the ordering says

Phase 0 is four items, none of them interesting, all of them blocking.
Elysium's ontology, security model, approvals, audit and lake work are
substantially ahead of its ability to read anything a customer owns.

Phase 0.5 is the other half of the same gap. The mirror is the right
architecture, it is built, it is PROVEN correct on the two properties
that matter -- an unsafe value cannot reach a reader, and a sync
cannot disturb one in progress -- and it ships turned off with no way
to see it working.

**THE PATTERN ACROSS BOTH:** what Elysium reasons about is ahead of
what it can reach and what it can show. The ontology, the approvals,
the audit trail and the lake are the hard parts and they are largely
done. Connecting to a database, bounding a query, typing a date, and
letting an administrator see any of it are the ordinary parts, and
they are where the work is.

That gap is the roadmap.
