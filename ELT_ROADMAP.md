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

## The plan

### Phase 1 — bronze: store what we read

Sync writes TWO tables per source table: `bronze.<silo>.<table>` (every
column the source has, types as they arrived) and the existing clean
table, now `silver.<silo>.<table>`.

`columns_present()` already exists and already tells us every column a
source has — it was built for drift detection and is exactly what
bronze needs.

Nothing reads bronze yet. This phase is inert on purpose: the same
shape as the permission ladder's first commit, so the storage decision
lands before anything depends on it.

**Open question to settle first:** retention. Bronze grows without
bound if every sync appends, and Iceberg snapshots already have a
retention policy we wrote for the silver tables. Reuse it or diverge?

### Phase 2 — silver: transform bronze, not the source

`transform_rows` moves out of `sync_table` and becomes a pass FROM
bronze TO silver. Re-deriving silver no longer touches the silo.

The payoff is immediate and testable: **adding an ontology field
becomes a silver rebuild rather than a full re-sync.** That is the
first thing worth measuring afterwards.

### Phase 3 — materialise the security value

Silver gains a resolved MAC column for every object type, including
those whose security is declared `via_field`. The link is followed
ONCE, at transform time, rather than per query.

**This is the load-bearing phase.** It is what makes MAC a predicate,
and it wants care: a stale security column is a leak, so it must be
rebuilt whenever either side changes, and the audit has to say when it
was computed.

### Phase 4 — DuckDB over silver

Aggregation and filtering push down to DuckDB with the MAC column in
the WHERE clause. Expect something near the measured 8.9x; verify
rather than assume, and keep the Python path as the fallback for
operators DuckDB cannot express — the same `UnsupportedFilter` contract
the adapters already use.

### Phase 5 — MinIO, and only when there is a second process

Iceberg currently uses `SqlCatalog` over SQLite with a local-filesystem
warehouse. That is correct for one host and wrong for anything else.
MinIO or S3 is what makes the mirror survive the machine.

**Deliberately last.** It buys nothing until more than one process
reads the mirror, and the `--reload` model we shipped assumes one. Doing
it earlier would be infrastructure for a deployment that does not exist.

---

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

**Phases 1 and 2 are cheap to reverse; 3 and 4 are not.** Stop after 2
if the field-addition measurement does not justify continuing.
