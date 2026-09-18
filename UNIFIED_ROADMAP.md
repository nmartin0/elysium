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

### 3.1 The plugin API

The largest item. Research done; no plan written.

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

That gap is the roadmap.
