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

## The plan

### Phase 1 — DuckDB, over what we already have

Brought forward, because the changelog diff needs it. Wire DuckDB over
the existing mirror for filtering and aggregation, keeping the Python
path as the fallback for operators it cannot express -- the same
`UnsupportedFilter` contract the adapters already use.

Independently worth it: measured 8.9x on grouping 200,000 rows.

### Phase 2 — bronze, and two-snapshot retention

Sync writes every column the source has, not only the declared ones.
`columns_present()` already reports them -- built for drift detection,
exactly what bronze needs.

Retention becomes explicit here: keep two snapshots, expire the rest.
Foundry's primary rule governs: "retention policies will never delete
transactions that are in the latest view of any branch", and overriding
it is "very dangerous".

### Phase 3 — the changelog

Diff bronze's current snapshot against its previous, by primary key,
and APPEND the result to silver with `_change_type` and an ordering
column.

Deletions must be INFERRED, since our sources do not report them --
Foundry says so for this case: "if the source data does not include
explicit deletion information, you may need to implement logic to infer
deletions (for example, by comparing consecutive snapshots)."

STEAL THEIR `>=` RULE: their incremental comparison is "greater than or
equal to... so that no data is omitted", accepting that "duplicate
values may appear", which "should be removed as a first step in the
data transformation pipeline". Prefer duplicates over omissions, and
dedupe downstream.

### Phase 4 — the current view

Latest row per primary key, with a deletion column. Foundry's ordering:
"duplicate primary keys are resolved BEFORE the deletion column is used
to exclude rows. Therefore, only the value of the deletion column in
the latest row for a given primary key matters."

This is what the ontology reads, and the point at which the pipeline
replaces today's mirror.

### Phase 5 — materialise the security value

Silver or current gains a resolved MAC column for every object type,
including those whose security is declared `via_field`. The link is
followed ONCE at transform time rather than per query.

**The load-bearing phase, and the dangerous one.** Sixteen
`check_access` calls assume per-object resolution. A stale security
column is a disclosure, not a slow query. It must be rebuilt whenever
either side changes, and the audit must say when it was computed.

### Phase 6 — MinIO, and only when there is a second process

Iceberg uses `SqlCatalog` over SQLite with a local-filesystem
warehouse: correct for one host, wrong for anything else.

Deliberately last. It buys nothing until more than one process reads
the mirror, and the `--reload` model assumes one.

## What makes this tractable

The mirror is 1,307 lines across five files, and `deployment_loader` is
the only thing outside `core/mirror/` that wires it. `sync_targets.py`
already derives what to sync from the ontology alone, so bronze needs
no new configuration.

## What makes it risky

**Phase 3 touches security.** Sixteen `check_access` calls assume
per-object resolution today. A materialised MAC column that goes stale
is a disclosure, not a slow query, and that is the phase to be slowest
and most suspicious on.

**Phases 1 and 2 are cheap to reverse; 4 and 5 are not.** Phase 1 is
additive with a fallback, phase 2 is storage only. Once the ontology
reads the current view (phase 4) there is no quick way back.

**Stop points, deliberately named.** After phase 1 if DuckDB does not
reproduce its measured margin on real queries. After phase 3 if the
changelog does not stay meaningfully smaller than the table -- which it
will not, for a source that rewrites every row nightly, and that is
worth knowing before phase 4 depends on it.

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
