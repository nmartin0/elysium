# ELT roadmap — a raw layer, a clean layer, and a query engine

**The shape we want**, which is Foundry's and which we half have:

    silo  ->  BRONZE (raw, as-is)  ->  SILVER (clean)  ->  ontology
               ^ missing              ^ exists, in the wrong place

**What Foundry does and why**, since it decided most of this. Their
first rule is to ingest without transforming: data should be ingested
"as-is from its most raw source, with no external preprocessing". The
reason is not tidiness — "if all transformations happen inside Foundry,
every Ontology property value traces back to a specific row in a
specific raw file. End-to-end data lineage".

---

## WHAT THIS IS NOW, after two phases dissolved its original premise

**This started as a performance project and is no longer one.** It
began because aggregation was slow, and I attributed that to the
storage architecture: no raw layer, Python grouping, no query engine.

None of that was the problem. 34.90s became 0.52s -- roughly 67x --
from fixing two implementation bugs, with ZERO architectural change:

  N+1 write-log queries        34.90s -> 1.45s   (phase 0)
  per-row audit writes          1.45s -> 0.52s   (phase 0b)

Re-profiled afterwards: what remains is four SQLite reads. Grouping
does not appear in the profile at all, and security resolution is
0.165s of 0.85s and already cache-backed.

**So the speed argument is spent.** What remains is a CAPABILITY AND
GOVERNANCE project, and it should be judged on those terms:

  LINEAGE -- "every Ontology property value traces back to a specific
  row in a specific raw file". We cannot do this, and adding an
  ontology field currently requires RE-READING THE SOURCE rather than
  re-transforming what we hold.

  HISTORY -- a source database holds "now". It has no record of what a
  value used to be. If that matters, only we can keep it.

  RE-DERIVATION -- changing how data is cleaned should not mean asking
  the customer's database for everything again.

Those are real and unaffected by the measurements. They were also never
the reasons I originally gave, which is worth being plain about.

## What was struck, and why

**Phase 1, DuckDB over the mirror. STRUCK.** Justified by a synthetic
benchmark showing 8.9x on grouping. The real path does not group
measurably -- that benchmark measured a component in isolation rather
than the path a query takes. If a future workload makes grouping
visible in a profile, revive it then, with that profile as the
argument.

**The MAC-column half of phase 3. STRUCK.** I claimed it was "what
makes MAC pushable" and implied a large win. Measured: security
resolution is 0.165s of 0.85s and already cached. Materialising it
might save a fraction of a fraction. The transform stage still stands;
the security column no longer justifies itself.

**A wider lesson, recorded because it produced both mistakes.** The
literature warned: "start with replica before committing to CDC. Let
the performance pain drive that conversation rather than trying to
anticipate it in a room without evidence." I built a seven-phase plan
on a benchmark. The fix, both times, was running the real thing on
realistic data -- which took one probe.

## What we have today, checked rather than assumed

**Extract and Load are real.** Adapters read silos; `iceberg_sync`
writes Iceberg.

**A transform stage exists** — `core/mirror/transform.py` — and its own
docstring already names it "the middle stage of the three-stage
pipeline Foundry's own architecture uses, and which Elysium previously
skipped: raw -> clean -> ontology". Someone reached this conclusion
before and implemented half of it.

**But it runs IN FLIGHT.** In `sync_table`: `raw_rows` ->
`transform_rows` -> Arrow -> one Iceberg table. The raw rows exist only
in memory. There is no bronze layer, only a silver one we call the
mirror.

**So we do ETL, not ELT**, and that is the concrete problem. The sync
selects only the columns the ontology declares and coerces their types
before writing, so:

- a column the ontology does not declare is never stored;
- **adding a field means re-reading the source**, not re-transforming
  what we already hold;
- if a value looks wrong there is nothing to compare against except
  the source, which may since have changed.

---

## Measurements taken before planning

**A bronze layer costs about 1.8x storage.** 20,000 rows, three
declared columns versus all six: 177KB -> 327KB. Sync time was NOT
dominated by column count — the source read dominates — so the cost is
storage, not latency.

**DuckDB is 8.9x faster than our Python grouping**, on 200,000 rows,
same answer: 0.314s -> 0.035s. `aggregate_by_field` currently reads
every matching row into Python and groups with a loop.

**THE TWO ARE THE SAME PROBLEM, which I did not expect.** Aggregation
cannot be pushed down today because MAC is not always a column.
`Customer` declares `field: region` — pushable. `Transaction` declares
`via_field: customer_id` — its security value is DERIVED by following
a link, so no engine can filter on it.

A silver layer is what fixes that: materialising the resolved security
value as a real column is exactly the kind of work a transform stage is
for. **The bronze/silver split is the prerequisite for the DuckDB
win**, not an independent nicety.

---

## What the research settled

**Our sources offer no way to detect change.** `customers` has no
timestamp at all; `transactions` has `transaction_date`, a BUSINESS
date that does not move when a row is edited. The adapter interface
exposes only `read_all_rows`. So Foundry's primary mechanism -- a
stateful high-water mark, "import rows when a single field is greater
than or equal to the largest value already imported" -- is unavailable
to us. Not "not yet": the columns do not exist.

They are candid about this case: "ideally, the incremental field should
be a monotonically increasing value; however, it is not always possible
to find such a field."

**Which puts us in a case they document.** A user asked them exactly
this: "my source system sends a full snapshot every sync. My transforms
apply CDC to detect inserts, updates, and deletes, then write only the
changes as APPEND transactions." That is our shape.

**incremental_append_scan does NOT help**, tested rather than assumed.
Because overwrite() replaces every data file, the "appended" files are
the whole table: a scan between two snapshots returned 1,001 rows when
2 had changed. It reports what was WRITTEN, not what DIFFERED.

**Iceberg's own changelog procedure is Spark-side.** pyiceberg has no
`create_changelog_view`. So we compute the diff ourselves -- which
Foundry describes in two modes, and we qualify for the better one:
"identifier changelog (recommended): one or more identifier columns
provided", which is "more performant" and gives "richer semantics,
including update-before and update-after records". Every object type in
our ontology already declares an `id_field`.

**And the diff is cheap. MEASURED: 76ms to compare 200,000 rows against
200,000 rows**, exact answer including deletions, via a DuckDB
anti-join. That moves DuckDB from a late optimisation to an early
dependency.

**Storage today is worse than I first said.** Iceberg's copy-on-write
means the WRITER copies: "every update recreates entire data files".
Measured on our own sync -- one row changed out of 20,000, five syncs:
177KB -> 839KB. Linear growth at full table size per sync. Snapshots of
an overwrite are full copies, so "keep history via snapshots" buys
unbounded growth and no real history.

---

## The shape, which is four layers not three

    source -> BRONZE -> SILVER changelog -> CURRENT -> ontology

**BRONZE is the bounded layer**, which inverts what the first draft of
this roadmap assumed. It holds the source as it is now, overwritten
each sync, retaining exactly TWO snapshots -- current and previous,
which is all a diff needs. Bounded at roughly 2x table size.

**SILVER is the history.** An append-only changelog, growing only with
ACTUAL changes. This is where "full history" becomes affordable rather
than merely possible, and where age-based expiry is the release valve.

**CURRENT is what Elysium reads.** Latest row per primary key. Needed
because the read path cannot scan a changelog that grows without bound
-- which is Foundry's own warning: "implementing edit semantics on
append-only transactions may allow the row count to grow without
bounds, making transforms performance increasingly worse."

Their resolution rule is the one to copy: "most recent transaction
wins... if the dataset contains more than one row for the same primary
key, the data of the row in the most recent transaction will be present
in the Ontology."

---

## Durability, and when the mirror stops being derived data

**TODAY THE MIRROR IS DERIVABLE, and that is why MinIO is not urgent
yet.** Everything in it came from the silos and can be read again. The
things that genuinely cannot be rebuilt -- write_log.db,
credentials.db, config_history.db, secrets/ -- are NOT in the mirror.
They are ordinary files needing ordinary backup, MinIO or no MinIO.

If the Elysium host dies today: reinstall, restore those four, re-sync.
Nothing is lost that the organisation's own databases do not still
hold. Object storage would make that faster, not safer.

**AFTER THE CHANGELOG EXISTS, THAT STOPS BEING TRUE.** A source
database holds "now". It has no record that a customer's region was
us-west last March. Once we append a changelog, losing it loses
everything the sources have since overwritten, and no re-sync recovers
it.

That is the moment the mirror stops being DERIVED DATA and becomes a
SYSTEM OF RECORD -- and the literature says it in a phrase quoted above
and not followed through: "bronze should act as a historical record". A
historical record that cannot be rebuilt is one that must be able to be
restored.

**SO THE CHANGELOG AND DURABLE STORAGE ARE ONE DECISION, NOT TWO.**
Shipping a changelog on a single machine's local disk would let an
organisation accumulate two years of history it believes is safe, lose
one host, and lose all of it. Either we build the history and make it
survive, or we do not build it yet.

**A REST CATALOG IS A SEPARATE AXIS AGAIN**, and an earlier draft of
this file wrongly coupled it to MinIO. pyiceberg's CatalogType is REST,
HIVE, GLUE, DYNAMODB, SQL, IN_MEMORY, BIGQUERY; storage is chosen
independently through FileIO. All four combinations are possible, and
we are SQL-plus-local today.

What a REST catalog unlocks is DuckDB's ATTACH, and its trigger is
MEMORY rather than deployment: the pyiceberg-to-Arrow-to-DuckDB path
materialises a scan before DuckDB sees it, which is fine until a table
does not fit. Different trigger, different phase, neither due yet.

## The plan

**Re-derived from the dependencies rather than from the original
guess.** Three constraints drive the order, and none of them was
visible when this file was first written:

- The changelog diff NEEDS a query engine. It is an anti-join.
- The changelog NEEDS durable storage, because it becomes a system of
  record the moment it exists.
- A materialised MAC column NEEDS somewhere to put it, which is the
  transform stage.

### Phase 0 — find out what is actually slow. DONE.

**MEASURED, AND IT IS NOT THE GROUPING.** Counting 50,000 transactions
by category through the real `aggregate_by_field` takes **35 seconds**.
A synthetic benchmark groups 200,000 rows in 0.3s, so the grouping was
never the problem.

Profiled: **200,023 SQLite connections opened, executed and closed** --
four per object. 34 of the 41 seconds is connection churn, and
`_read_field_with_log_check` accounts for 38.7s of cumulative
time across 50,004 calls.

The cause is per-object write-log consultation. Every field read asks
the write log two questions -- is this object deleted, does it have a
pending change -- and each question opens its own connection.

**DuckDB WOULD HAVE OPTIMISED THE 0.24s AND LEFT THE 38.7s ALONE.**
That is the whole reason this phase exists: the measurement that
justified phase 1 was real but measured the wrong thing, because it
measured grouping in isolation rather than the path a query takes.

DONE, and MEASURED AFTER: 34.90s to 1.29s, a 27x improvement on
the real path, same 43 groups. Batched the write-log lookups: one
query for "which of these objects have pending changes", one for
"which are deleted",
instead of two per object. The write log already has the object ids;
nothing new is needed but a different shape of question.

**Expect this to dwarf everything else in this file.** A change from
200,023 connections to 2 is not an optimisation, it is a different
program -- and it is worth knowing whether the remaining time even
justifies DuckDB before building on it.

### Phase 0b — audit at the granularity of the event. DONE.

The profile after phase 0 was dominated by something else entirely:
**50,007 audit writes, 1.08 of the remaining 1.45 seconds**, of which
49,997 were identical grants.

NIST SP 800-92 settles the granularity: log "events that involve a
state change or a SECURITY DECISION". A bulk read makes ONE decision --
may this user read this type -- and applies it many times.

One record per read now, and it is FINER than what it replaced. The six
questions a defensible trail answers -- who, what, when, where, why,
what outcome -- are all answered, where the per-object records answered
three. It additionally names which FIELDS were read and which SECURITY
PARTITIONS were touched, neither of which was ever captured.

**Denials are never summarised**: "sample strategically for
non-security telemetry ONLY". Every denial keeps its own record and is
named in the bulk one.

**34.90s -> 1.45s -> 0.52s.** Roughly 67x from where this started, and
4 audit records instead of 50,007.

Rejected: asynchronous logging, the standard speed answer. It trades
durability for speed, and this project already rejected persistent file
handles for the same class of reason.

### ~~Phase 1 — DuckDB over the existing mirror.~~ STRUCK

See "What was struck, and why". Grouping does not appear in the profile
of the real path. Revive only with a profile that shows it.

### Phase 1 — bronze, with retention. DONE.

**Depends on nothing. The strongest remaining case.**

Sync writes every column the source has, not only the declared ones;
`columns_present()` already reports them, having been built for drift
detection.

**Justified by lineage, not speed, and always was.** Today a value that
looks wrong has nothing to compare against except a source that may
since have changed, and adding an ontology field means re-reading the
silo rather than re-transforming what we hold.

**RETENTION IS DECLARED, NOT ENFORCED, and that distinction matters.**
pyiceberg 0.12 has no snapshot expiry at all -- no expire_snapshots, no
ExpireSnapshots, and ManageSnapshots offers only branches, tags and
rollback. So nothing reclaims space today.

What IS declared are the standard Iceberg property names --
history.expire.min-snapshots-to-keep=2 and
history.expire.max-snapshot-age-ms=7 days -- so the intent travels with
the table rather than living in a runbook, and any engine that does
implement expiry reads them.

The existing snapshot-retention guard fired when this landed, which is
what it was written for: "this fails the moment expiry appears, which
is exactly when the decision needs making".

STILL OUTSTANDING, therefore: actual reclamation. "Bronze bloat"
is the most commonly cited failure of this pattern, and Iceberg's
copy-on-write makes each retained snapshot a full copy -- measured,
177KB to 839KB over five syncs of a table where one row changed. Bronze
now doubles that rate, since it stores every column rather than the
declared ones.

WHAT LANDED: every column stored as a string, unaltered; provenance in
table properties (silo, table, layer) and the snapshot's own timestamp;
and a bronze failure that warns without failing the sync -- losing
lineage costs explicability, losing the sync costs the deployment its
data.

**Nothing reads bronze.** "Bronze should act as a historical record,
not a source of truth."

### Phase 2 — silver derived from bronze. DONE.

**Depends on 1.** `transform_rows` moves out of `sync_table` and
becomes a pass from bronze to silver, so re-deriving silver stops
touching the silo.

**MEASURED, AND THE FIRST ANSWER WAS NO.** Bronze was storing only the
DECLARED columns, so adding a field still required re-reading the silo
-- the source-read count did not drop at all. Fixed: bronze now stores
every column `columns_present()` reports.

**THE HONEST RESULT.** A normal sync still reads the source exactly
once, because sync_table refreshes bronze every run. What changed is
that the data needed to REBUILD silver is held locally -- proved by
renaming the source away and re-deriving a column the ontology never
declared.

Making a rebuild SKIP the refresh is a separate change with its own
question: when is bronze stale enough to re-read. Not answered here.

The MAC column that used to live here is struck -- see above. What
remains is the transform stage itself, which every later phase needs.

### Phase 3 — durable storage, BEFORE any history exists. DONE.

**Depends on nothing technically; depends on phase 4 morally.**

MinIO or S3 replaces the local-filesystem warehouse. Nothing before
this needs it -- everything in the mirror is derivable from the silos,
and the things that are not (write_log.db, credentials.db,
config_history.db, secrets/) are ordinary files needing ordinary
backup.

**The next phase creates data that cannot be rebuilt**, and doing this
after would leave a window in which an organisation accumulates history
on one machine's disk and believes it is safe.

WHAT LANDED: the warehouse location and its storage options are
configurable, local remains the default, and both bronze and silver
follow the setting. Verified end to end against a real S3 endpoint --
an Iceberg warehouse written to and read back from object storage, not
merely options passed along.

THE CATALOG STAYS LOCAL, deliberately: catalog type and storage backend
are separate axes, and moving the warehouse does not require moving the
catalog.

### The precondition, measured. THE CHANGELOG IS NOT NEXT.

The roadmap demanded evidence before phase 4: "measure the full-reload
cost on a realistic table first". Measured:

    10,000 rows   full reload 0.19s
    100,000 rows  full reload 0.68s

A nightly sync of a million rows would take under ten seconds. **There
is no performance pain**, which is precisely the condition the
literature warned about: "let the performance pain on the source system
drive that conversation rather than trying to anticipate it in a room
without evidence".

**THE REAL COST IS STORAGE, AND IT IS NOT WHAT THE CHANGELOG FIXES.**
Thirty nightly syncs of a 50,000-row table, one row changed per night:

    after  1 sync    1.0 MB
    after 10 syncs  10.1 MB
    after 30 syncs  31.6 MB

Linear at full table size, because Iceberg's copy-on-write makes every
snapshot a complete copy and NOTHING EXPIRES THEM. pyiceberg 0.12 has
no expiry, so the retention policy declared in phase 1 is a statement
of intent that nothing enforces.

A changelog would store 30 rows instead of 30 full copies -- but so
would working expiry, and expiry is the smaller change. Building a
changelog to solve a problem that unenforced retention causes would be
treating the symptom.

**FIRST STEP TAKEN, AND IT WAS NOT EXPIRY.** A sync that finds nothing
changed now writes nothing -- for both bronze and silver. Measured:
thirty identical syncs of a 50,000-row table went from 27.2 MB across
65 snapshots to 0.9 MB across 1.

Not creating a snapshot is both cheaper and SAFER than reclaiming one:
writing nothing is never wrong, where deleting can be. It is also
idempotency, which the literature names as a core pipeline pattern --
"produces the same result regardless of how many times it is executed
with the same input".

## The storage thread ends here, and the reason is scale

Three commits chased the cost of a changing table: the unchanged-sync
skip (which worked, 27.2 MB to 0.9 MB), then transactions and upsert
(which did not), then partitioning.

Partitioning is the documented answer and we should NOT do it. A
million-row table is 4.9 MB of Parquet; the guidance targets 128 MB to
1 GB per partition. We are two orders of magnitude below the point
where the technique starts helping, and applying it anyway would create
the small-files problem the same sources call the worst outcome.

**THE HONEST SUMMARY: the remaining storage cost is not worth
engineering against at our scale.** Thirty nightly syncs of a changing
50,000-row table cost 31.6 MB. The cheap, safe win is taken; everything
further is a technique for tables a hundred times larger.

What follows is kept for the deployment that eventually has one.

## Why a CHANGING table still costs a full copy, and what would fix it

Measured after the unchanged-sync skip, since that only helps tables
nobody edited. Three approaches tried, none of which helped:

**TWO SNAPSHOTS PER SYNC, NOT ONE.** pyiceberg's `overwrite()` is a
delete followed by an append internally -- read in its source, not
guessed -- so every changing table produces two snapshots per sync.
Wrapping the call in an explicit transaction does not merge them.

**`upsert()` IS NO CHEAPER.** 20,000 rows with ONE changed: overwrite
added 111.4 KB, upsert added 116.7 KB, and both produced the same
snapshot count. It rewrites the whole file regardless, because all the
rows live in one Parquet file.

**THAT IS THE ACTUAL CAUSE**, and it is not a pyiceberg limitation. A
table written as a single Parquet file has no smaller unit to rewrite,
so any change rewrites everything. The documented answer is
partitioning -- "if updates are localized to specific partitions,
optimize storage by partitioning effectively" -- which makes a change
rewrite only the affected partition.

**AND WE SHOULD NOT DO IT, at our scale.** Researched and then
measured, in that order, which reversed the conclusion.

The guidance is consistent about sizing: target "128 MB - 1 GB per
partition", with a minimum of "1GB - 10GB" and a warning that files
"< 100MB in size will cause all query engines to experience
performance problems at scale".

Measured against that:

    50,000 rows    ->  0.72 MB of Parquet
    1,000,000 rows ->  4.90 MB of Parquet

**A MILLION-ROW TABLE IS FIVE MEGABYTES.** Partitioning it into three
regions would give three 1.6 MB partitions -- two orders of magnitude
below the smallest recommended size. That is textbook over-partitioning:
creating the small-files problem, which the same sources call "the
worst-case outcome", to solve a problem we do not have.

The storage arithmetic says the same thing. Thirty nightly syncs of a
changing 50,000-row table cost 31.6 MB. That is not a problem worth
risking a partition layout for.

**WHEN IT WOULD BECOME RIGHT**, recorded so the decision is not
re-litigated from scratch: a table whose Parquet exceeds a few hundred
megabytes, which is roughly a hundred million rows at the widths we
see. The partition key should then come from "the columns that appear
in WHERE clauses most frequently" -- and for us that is the SECURITY
field, since MAC filters every read by it. Low cardinality, in every
query, and already declared in the ontology.

Partition evolution is metadata-only -- "existing data retains its
original layout; new writes use the new spec" -- so choosing later
costs nothing that choosing now would save.

**EXPIRY IS STILL WANTED**, for tables that genuinely change
nightly. Either pyiceberg
gains it, or we reclaim snapshots ourselves under the two rules already
recorded: never delete what is current, and age out the rest beyond a
margin that exceeds the longest request by an order of magnitude.

The changelog's remaining justification is HISTORY -- a source holds
"now" and cannot tell you what a value used to be. That is a real thing
to want and a different argument from storage or speed. It should be
made on its own terms, by someone who wants the history, rather than
inferred from a plan.

### Phase 4 — the changelog

**Depends on 1 (two snapshots to diff), 3 (somewhere it survives), and
a query engine for the diff itself** -- which is the one thing the
struck DuckDB phase was genuinely needed for. An anti-join over two
snapshots measured 76ms for 200,000 rows against 200,000; doing it in
Python would not be free.

Diff bronze's current snapshot against its previous by primary key, and
APPEND the result with a change type and an ordering column. Deletions
must be INFERRED, since our sources do not report them.

WHAT LANDED: a diff between bronze's stored rows and the incoming ones,
appended as INSERT/UPDATE/DELETE with the time we noticed. Identifier
mode, which we qualify for since every object type declares an
id_field, so an edit reads as one UPDATE rather than an unconnected
delete and insert.

PLAIN PYTHON, NOT DUCKDB. Measured: 0.984s against 0.050s for 200,000
rows a side. At our scale that is under a second in a nightly job, and
a dependency saving under a second is not worth its failure modes.

A PARTIAL-READ GUARD, because deletions are INFERRED -- a sync that
returned half the rows would otherwise record half the table as
deleted, and the changelog is the one thing a re-sync cannot repair.

STILL OPEN: nothing READS it. The current view that would resolve
latest-row-per-key is deliberately separate, so the changelog can be
verified for weeks before anything depends on its growth rate.

**Its precondition was evidence.** Measure the full-reload cost on a
realistic table first. If a nightly full sync is cheap, this buys
HISTORY rather than performance -- which is a real thing to want, and a
different argument from the one this file originally made.

### Phase 5 — the current view reads from the changelog

**Depends on 4.** Latest row per primary key, resolved before the
deletion column is applied.

Separated from phase 4 deliberately: the changelog can exist and be
verified for weeks before anything reads it, which is the cheapest way
to learn whether its growth rate is survivable.

### Phase 6 — a REST catalog, if a table outgrows memory

**Conditional, not scheduled.** The pyiceberg-to-Arrow path
materialises a scan before anything queries it. When a table stops
fitting, `ATTACH` is the answer and it needs REST.

Independent of phase 3: catalog type and storage backend are separate
axes.

## The reversibility line is phase 3

Everything up to and including phase 2 leaves the mirror fully
derivable from the silos: if it turns out wrong, delete it and re-sync.
Phases 1 and 2 cost time and nothing else.

From phase 4 onward the changelog holds history no source can return,
and phase 3 exists precisely to make that survivable.

So the question to ask before phase 3 is not "is this working" but
**"are we committing to hold data nobody else holds"**. Everything
before it is an optimisation. Everything after it is a custodial
responsibility.

## Gotchas the wider literature warns about

Read AFTER the plan above was drafted, and one of them challenges it
directly. Recorded here rather than quietly absorbed.

**"START WITH REPLICA BEFORE COMMITTING TO CDC. Let the performance
pain on the source system drive that conversation rather than trying to
anticipate it in a room without evidence."**

That is exactly what phases 4 and 5 do -- anticipate. We have no
evidence of source-system pain: our silos are SQLite files read by a
nightly sync. The same guidance elsewhere: CDC's "trade-off is
operational complexity... so for small tables or infrequent loads, a
simple batch reload is often the better choice."

**We are currently a small table with an infrequent load.** The
changelog is the right destination and may be the wrong next step.

**"If those layers don't clearly add value, you're not doing medallion
architecture. You're just stacking complexity."** And: "not all data
requires three transformation stages, yet the framework encourages
unnecessary processing." Each layer has to earn itself.

**"Bronze should act as a historical record, not a source of truth."**
Nothing should read bronze to answer a question. That matches our plan
and is worth stating so it stays true.

**Bronze bloat is the most commonly cited fixable problem** -- "tackle
bronze bloat first. Add retention policies, partitioning, and regular
maintenance." Our two-snapshot rule addresses it, and must be in place
from the first commit rather than added later.

**Access control across layers is a named pitfall**: "if roles,
privileges, or access patterns aren't carefully designed, downstream
layers may encounter failures or unauthorized access." This is phase
5's risk stated by someone else, independently.

**IDEMPOTENCY is the pattern to design for from the start**: a pipeline
"produces the same result regardless of how many times it is executed
with the same input". Achieved with MERGE/upsert on a primary key, and
the reason it matters here is that a failed sync must be safe to rerun.

**And the classic SCD2 failure**: "setting incorrect unique keys causes
the most serious problems... the unique key must stay the same over
time and identify each business entity clearly." Our `id_field` is
declared per object type and validated, so we are better placed than
most -- but a source whose primary key is reused would corrupt the
changelog silently.

**Polyglot persistence supports the DuckDB decision** from the other
direction: the medallion pattern "assumes technological homogeneity...
one engine is optimal for real-time streaming, graph traversals,
full-text search". Using DuckDB for analytics over Iceberg storage is
the idiomatic answer, not a workaround.

## A correction to the plan, from that reading

**BRONZE STANDS; DUCKDB DID NOT.** Bronze is justified by lineage -- a
correctness argument, not a performance one, which is why the
measurements that killed phase 1 left it untouched.

**The changelog needs evidence it does not yet have.** Building it
to avoid source load we have never observed is anticipating in a room
without evidence, which is the named mistake.

So the changelog gains a precondition: **measure the full-reload cost
on a realistic table first.** If a nightly full sync is cheap, the
changelog buys history rather than performance -- still worth having
for lineage, but a much weaker case, and one that should be argued on
its own terms rather than smuggled in as an optimisation.

## What is NOT in this plan, and why

**A high-water-mark sync.** Foundry's preferred mechanism, unavailable
to us because the source columns do not exist. If a future silo offers
a modification timestamp, that silo should use it -- it is strictly
cheaper than diffing, since it never reads unchanged rows at all.

**Streaming or CDC feeds from the source.** Foundry supports them and
they are better than diffing, but they require the SOURCE to produce a
changelog. Ours are ordinary databases we read over JDBC-equivalent
adapters.

**Compaction of the changelog.** Foundry warns the row count "may grow
without bounds" and answers with projections and compaction. We should
expect to need it, and should not build it before the changelog exists
and its real growth rate is measured.
