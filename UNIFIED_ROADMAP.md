# The unified roadmap

**Why this exists.** Nineteen planning documents hold roughly 12,700
lines between them -- nine and 8,500 when this file was first written.
Each is right about its own area and none can say what to do next,
because the answer depends on the others. This file is the ordering;
the detail stays where it is, and each item names its home.

**How it is ordered.** By dependency and by what would stop a
deployment, not by size or by interest. An item appears after
everything it needs and before everything that needs it.

**What this is not.** It is not a schedule and it does not estimate.
Several items below are a day and several are a month, and saying
which would be a guess presented as a plan.

---

## Where this stands, September 19

**PHASES 0, 1 AND 3.5 ARE COMPLETE.** The four blockers the commercial
audit named -- no real database adapter, unbounded search, unbounded
cache, no query timeout -- are closed, along with the live-read
coercion that had to precede them and the four items of phase 0.5.

    0.0  live reads honour the declared type        DONE
    0.1  an adapter for a real database             DONE
    0.2  a row limit that reaches the query         DONE
    0.3  a bound on the security cache              was already bounded
    0.4  a silo query timeout                       DONE
    0.5  the mirror becomes the read path           DONE
    1.1  persist the pending write store            DONE
    1.2  fsync before the catalog pointer swap      DONE
    1.3  backup and restore                         DONE
    1.4  secret indirection                         DONE

    3.5  non-user-derived constraints               DONE
         trace id, write-down check, attenuation,
         and the grant algebra as universal tests

**FOUR ENTRIES WERE WRONG ON INSPECTION** and are corrected in place
rather than deleted, because the mistake is more useful than the
absence:

    0.3    the caches were already bounded
    0.5.5  the sync already reported every drifted column
    3.5    "ordered or incomparable" was a false choice -- a
           Bell-LaPadula label has BOTH, and Elysium's values are
           compartments
    3.5    "intersection for action authority" had nothing to
           intersect: an action declares no authority of its own

**ALL FOUR WERE WRONG IN THE SAME DIRECTION** -- describing a defect
that reading the code carefully would have ruled out. That is a
prior worth carrying into the remaining design documents.

**WHAT REMAINS IS ORDERED BY DEPENDENCY BELOW.** Phase 2 needs
nothing. Phase 3 needs research. Phases 3.5 and 3.6 are designed and
unbuilt. The items in "Found on review" have no phase yet and are
placed where their dependencies put them.

---

## Phase 0 — Elysium cannot read a customer's data

Everything in this phase is a blocker for any commercial use. None of
it is interesting and all of it is required.

### 0.0 ~~Live reads honour the declared type~~ DONE

**THE PRE-POSTGRES COMMIT**, measured: the same field and ontology
returned `Decimal('49.990000000')` from the mirror and `49.99` as a
FLOAT from the silo. The sync coerces into silver; a live read handed
back whatever the driver produced.

It comes BEFORE 0.1 because psycopg returns Decimal, datetime, date
and UUID objects -- none of which the ontology's vocabulary names --
so an adapter would have widened this gap rather than revealed it.

**A FAILURE IS REPORTED AND SERVED.** The sync can refuse a whole
table because a refused sync leaves the previous snapshot standing; a
read has no previous value, and refusing would turn a type
disagreement into an unreadable object.

**THE SECURITY-VALUE PATH IS DELIBERATELY EXCLUDED** -- it is compared
for equality against the user's own, and changing the representation
of one side of the comparison that decides authorization is not worth
tidying a region name for.

**ONE HONEST DIFFERENCE REMAINS:** the mirror returns a decimal at
storage scale (`49.990000000`), the live path at source scale
(`49.99`). Numerically equal, and `decimal_places` governs display, so
the two agree everywhere a user looks -- but `str()` differs.

### 0.1 ~~An adapter for a real database~~ DONE

**ON SQLALCHEMY CORE, NOT A NATIVE DRIVER.** Our queries are simple --
no joins, no subqueries, no window functions -- so almost everything
that differs between engines is what Core's dialects handle:
placeholder style, identifier quoting, row-limit syntax, and schema
introspection.

**THE LAST DECIDED IT.** The schema-drift work needs to know what a
source says its column types are, and hand-writing that means
information_schema, PRAGMA, ALL_TAB_COLUMNS and sys.columns -- four
dialects of one question. Core's Inspector answers it once.

**Airflow is the precedent:** SQLAlchemy underneath, with
per-database overrides where they matter.

**THE SQLITE ADAPTER IS UNTOUCHED**, serving Elysium's own storage on
the stdlib module. Two mechanisms, divided on a real line: embedded
fixture storage against a customer's real database.

**VERIFIED AGAINST A REAL POSTGRESQL 16.2**, not a mock. `pgserver`
ships the server as a wheel, so the adapter's 19 tests exercise a
genuine engine -- which is what removed the objection that an untested
database adapter would be the largest unverified thing here.

### 0.1 (original note)

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

### 0.2 A row limit that reaches the query -- MAC PUSHDOWN DONE

**THE FIRST HALF IS BUILT.** A `field:` security declaration is now
pushed into the query as a condition, so the database returns only
rows the user may see. The canonical name is PREDICATE PUSHDOWN; what
cannot be pushed is the RESIDUAL predicate.

**MEASURED BEFORE:** 200,000 rows cost 0.70s and 66MB, extrapolating
to ~35s and ~3.3GB for ten million -- per request, before filtering.

**`via_field:` CANNOT BE PUSHED** and ontology_schema.yaml now says
so, because it is a schema choice with a performance consequence. A
known hazard rather than a local limitation: the row-level-security
field guidance is "keep predicates join-free", and Databricks'
SecureView barrier forces full scans for the same reason.

**AND THE LIMIT IS BUILT.** `find_ids` takes one, SQLite emits
`LIMIT n`, and pyiceberg takes a limit natively so the mirror stops
reading rather than trimming. `MAX_SEARCH_SCAN` is 10,000 -- far above
the API's own MAX_PAGE_SIZE of 500, far below where the fetch hurts.

**MEASURED:** 200,000 rows went from 858ms and 66MB to 49ms and
3.2MB, on a table twenty times smaller than the one that would have
exhausted memory.

**ONE MORE THAN THE CEILING IS READ**, which is how "we stopped
looking" is distinguished from "that was all of them" without a second
query.

**AND THE CALLER IS TOLD.** `scan_truncated` on the search response,
and a Browse banner saying the search STOPPED rather than that there
is more -- because where MAC is residual the ceiling bounds a scan
whose survivors are filtered, so the rows beyond it might all have
been invisible anyway.

**THE FREE-TEXT PATH WAS UNCAPPED**, which is the route Browse
actually uses: the first ceiling only reached `search_object`. Both of
its fetches are capped now.

**0.2 IS DONE.**

### 0.2 (original note)

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

### 0.3 ~~A bound on the security cache~~ THE ENTRY WAS WRONG

It said the caches "accumulate one entry per object ever
security-checked" and that a long-running deployment "grows memory
monotonically".

**MEASURED, AND THEY DO NOT.** Twenty-one identical searches leave the
cache exactly as one search does, and a search of a different type
REPLACES its contents. Both writes live inside
`_prefetch_security_values`, which CLEARS FIRST -- the words "cleared
only at the start of a bulk prefetch" were in the entry, and I read
them as a weakness rather than as the bound.

**SO THE BOUND IS ONE SEARCH'S CANDIDATE SET**, which 0.2 capped.
Verified against a patched ceiling: 2 gives 3 entries, 1 gives 2.

**PINNED ANYWAY, because the bound is INCIDENTAL.** Nothing declared
it, and a write added outside the prefetch would restore the growth
the entry feared with no test objecting. A source-level tripwire now
asserts every write happens where the clearing does.

**THE SECOND ROADMAP ENTRY THIS WEEK TO BE WRONG ON INSPECTION**, and
both were wrong in the same direction: describing a defect that
reading the code carefully would have ruled out.

**Blocks:** any deployment that stays up for a week.

### 0.4 ~~A silo query timeout~~ DONE

**THE ENTRY WAS RIGHT, this time.** No adapter set one, verified
before building.

`set_progress_handler` is SQLite's own mechanism -- a callback every
10,000 virtual-machine instructions, returning non-zero aborts with
OperationalError("interrupted"). Measured: a runaway query stops at
0.20s against a 0.2s deadline, and an ordinary one runs in 0.1ms
untouched.

**WRITES TOO**, inherited from the read adapter. Verified that an
aborted write leaves NOTHING behind -- zero rows -- because a
half-applied write would be far worse than a slow one.

**30 SECONDS BY DEFAULT**, per silo overridable, 0 to disable.
Documented in data_silos.yaml.

**BUILT BEFORE THE ADAPTER THAT NEEDS IT**, deliberately: a timeout
added alongside the first network adapter would be a timeout nobody
had ever watched fire.

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

**STILL OPEN:** roll-back. History and Sync now are built;
rolling BACK to a snapshot is a write, and a different question.
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

### 1.1 ~~Persist the pending write store~~ DONE

In-process memory, stated plainly in its own docstring. A restart
loses every approval awaiting decision.

For a product whose pitch is that writes are mediated and approved,
losing the queue on deploy is the worst fit between claim and
behaviour. ROADMAP.md establishes SQLite suffices and that the rebuild
is blocked on its DESIGN — who may see a queued write across a
restart, and what a reload does to one proposed under an older
generation — not on storage.

**THE DESIGN DECISION IS MADE.** Both questions turned out to be
answered by code that already exists.

**WHO MAY SEE A QUEUED WRITE ACROSS A RESTART:** whoever the CURRENT
grants say. Nothing about eligibility is stored. `confirm` authorises
against `_generation(request).config.roles`, and MAC and the
submission criteria are evaluated inside `confirm_and_execute()`
against the objects actually touched -- "duplicating them here would
be a second, weaker copy". Authority is re-evaluated at the point of
use, which is this project's rule everywhere else too.

**WHAT A RELOAD DOES TO ONE PROPOSED UNDER AN OLDER GENERATION:** this
is the real question, and it is about MEANING rather than authority. A
PendingWrite holds RESOLVED `sub_writes` -- the old ontology's
interpretation of what the action does. Re-authorising those under new
grants would check the new rules against the old meaning.

**AND A CHECK FOR IT ALREADY EXISTS.** `PendingWrite` carries
`proposed_under_generation`, and `confirm_and_execute()` calls
`_fields_no_longer_declared()` -- refusing a write whose target fields
the current ontology lacks, naming both generations and writing
`log_write_unapplyable`.

I began building a `source_digest` pin and backed it out: that refuses
whenever ANY configuration changed, where the existing check refuses
only when THIS WRITE can no longer be applied. Cruder, and a
duplicate.

**THE RESIDUAL GAP, narrower than first framed:** the existing check
asks whether the target FIELDS still exist. It does not ask whether
the ACTION still means what it meant -- an action whose sub-writes
were redefined leaves a stored write holding the old computation
against a field that is still perfectly present.

That is a real hole and a small one. Worth fixing when the action
definition itself can be compared, not by refusing every write that
outlived a config change.

**Depends on:** nothing. SQLite suffices, and the design is settled --
authority re-evaluated at use, meaning checked by the guard that
exists, with the narrow residual gap recorded.

### 1.2 ~~fsync before the catalog pointer swap~~ DONE

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

### 1.3 ~~Backup and restore~~ BACKUP DONE

**THE INVENTORY WAS WRONG: SEVEN, NOT FIVE.** The entry named
credentials, write_log, config_history, metrics and artifacts, and
missed the mirror's own `catalog.db`; `sync_attempts.db` did not exist
when it was written. Verified against the live deployment.

`scripts/backup_deployment.py` uses `sqlite3.Connection.backup()`,
which takes a CONSISTENT snapshot of a database being written to --
`cp` tears across a write, and a torn credentials database is one
nobody can log into.

**THE SILOS ARE DELIBERATELY EXCLUDED**, and the manifest says so.
`dev_fixtures/` stands in for a CUSTOMER'S databases; backing them up
would copy data Elysium does not own into a directory the customer did
not choose.

**VERIFIED BY RESTORING:** a backup copied into a fresh directory,
pointed at the silos, built a generation and served four transactions
with its mirror timestamp intact.

**AND RESTORE IS A SCRIPT NOW**, whose value is the CHECKING rather
than the copying. Every database must open AND hold tables --
`sqlite3.connect()` succeeds on a file that is not a database at all,
failing only when something reads.

**EVERY PROBLEM IS REPORTED, NOT THE FIRST.** Somebody fixing a backup
one error at a time, with a restore between each, gives up before the
third.

**A MISSING credentials.db IS NAMED SPECIFICALLY**, because that
backup restores silently and then nobody can log in -- which looks
like a different failure entirely.

**Verified end to end:** a restored backup, pointed at the silos,
builds a generation and serves four transactions.

**THE CHANGELOG IS THE ONE THING THAT CANNOT BE REBUILT.** Bronze and
silver derive from the silos; history does not.

**Depends on:** 1.2, so that what is captured is itself consistent.

### 1.4 ~~Secret indirection in configuration~~ DONE

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

### 2.3 ~~json_each for the write log~~ DONE

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

**SAVED VIEWS ARE NOT SERVER-SIDE**, which an earlier version of this
entry got wrong. `SavedView` is `{name, url}` in a browser's
localStorage, so nothing scheduled can reference one. Moving them
server-side is the real prerequisite for object-set conditions --
which is a second reason mirror health goes first, since it needs
none.

**AND PER-RECIPIENT EVALUATION IS NOT NOVEL WORK.**
`search_object(user_record, ...)` already takes a user, so evaluating
a condition as the owner and then as each recipient is one existing
function called with a different first argument. No second permission
path to get wrong.

**THE REAL RISKS ARE VOLUME:** MAX_SUB_WRITES is 20 and the queue TTL
is 15 minutes, so an automation across a thousand objects floods or
expires. And four-eyes means an owner cannot approve their own
automation's proposal.

### 3.1 The plugin API

**DESIGNED UNDER A STRICTER PREMISE -- see
THIRD_PARTY_EXTENSIONS.md.** Every component untrusted, first-party
included. Module federation is DISQUALIFIED; a third-party adapter is
a SILO; the channel comes before the boundary.

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

## Phase 3.5 — ~~Non-user-derived constraints~~ DONE

**ALL FOUR PIECES.** Trace id (built earlier), the write-down check
(compartments, levels deferred following Foundry), attenuation (found
already true and pinned), and the grant algebra -- now four UNIVERSAL
tests that fail when a NEW mechanism appears rather than when an
existing one breaks.

**THREE OF THE FOUR WERE SMALLER THAN WRITTEN.** Recorded in
SECURITY_ARCHITECTURE.md in place rather than deleted.

**ASSESSED, NOT BUILT -- see SECURITY_ARCHITECTURE.md.**

**ONE REAL HOLE.** Every MAC check compares an object to the USER's
security value; nothing compares two objects to each other. So an
analyst cleared for two partitions can run an action that reads one
and writes the other, and data crosses a boundary with every check
passing.

That is Bell-LaPadula's \*-property -- no write down. Elysium enforces
its partner (no read up) and not it, and neither term appears in the
codebase: not a decision, an omission.

**BUILD ORDER:** a request-scoped trace id first (smallest, and it
makes the rest observable); then the write-down check; then
intersection for action authority; then the grant algebra, once there
is something worth specifying.

**WHAT NOT TO BUILD:** actions carrying authority their caller lacks,
which is a confused deputy. Attenuation only.

## Phase 3.6 — Fusion and identity

**DESIGNED, NOT BUILT -- see FUSION_AND_IDENTITY.md.** Elysium follows
links someone wrote down and infers none. The precedent says identity
resolution is a PIPELINE problem, which places it in the GOLD layer
Elysium does not have.

**THE PERMISSIONS FEAR DISSOLVES:** column-wise MDO already exists, so
a merged subject is one object whose FIELDS keep the classification of
their source. No write-down. What does NOT dissolve is the
classification of the identity link itself.

**HAND-WRITTEN JOINS ARE THE PRIMARY PATH**, working with zero
inference. Inference is off by default and its proposals always go
through the approvals queue -- which answers unresolution natively,
since un-merging is another write.

## FIRST, NEXT SESSION: the pending-write store is not multi-process safe

**FOUND WHILE WIRING TRIGGER ACTIONS, and it blocks them.** Recorded
before anything else so it is the first thing picked up.

### The problem

`PendingWriteStore` keeps writes in a locked dict and MIRRORS them to
`pending_writes.db`. The API reads that file ONCE, at startup
(`_restore_locked`), and every read after answers from memory.

The sync runs as a SEPARATE PROCESS when cron starts it. So a trigger
firing during a cron-run sync would propose a write into
`pending_writes.db` -- and the running API would never see it until
restarted. The proposal would sit on disk, absent from Approvals.

"Sync now" is unaffected: it runs the sync on a thread INSIDE the API
process. The cron path is the one that breaks, and it is the one that
matters for anything happening while everybody is asleep.

### What precedent says, and it says my design was backwards

Every SQLite-backed queue researched states it the same way: "the
database is still the source of truth. The queue only stores candidate
job IDs", with "the claim logic checks the database before starting a
job and skips anything that is no longer pending". A queue library
explaining what multi-process support would require names it
directly: "removal of the in memory caches".

**`PendingWriteStore` INVERTS THIS.** Memory is the truth and SQLite
is a mirror, which is exactly why a second process cannot be seen.

Its concurrency was described in this project as "getting it right".
That was true of THREADS in one process. It was never multi-process
safe, and nothing said so.

### The fix

**MAKE THE DATABASE AUTHORITATIVE.** Reads come from SQLite; the dict
goes. WAL mode lets the API read while the sync writes -- readers get
snapshots that are not blocked by the writer.

**RESERVING BECOMES A DATABASE-BACKED CLAIM:** `UPDATE ... SET
reserved = 1 WHERE write_id = ? AND reserved = 0`, which either claims
the row atomically or matches nothing because somebody else did.
SQLite serialises writers, so that is safe across processes by
construction.

### What it dissolves

The obvious patch -- have `awaiting()` merge in rows another process
added -- would need a TOMBSTONE set: deciding a write removes it from
memory and then deletes the row best-effort, so a failed delete would
bring a DECIDED write back. A zombie approval somebody already acted on
is worse than a missing one.

**WITH THE DATABASE AUTHORITATIVE, THAT CANNOT HAPPEN.** Deciding
deletes the row, and there is no second copy to disagree with. The
complexity the merge needed was a symptom of the inversion, not a
property of the problem.

### Why it is a session of its own

It rewrites the store under the approvals queue, where a mistake loses
or duplicates DECISIONS. It deserves its own commit, its own controls,
and a concurrency test that runs two real processes rather than two
threads -- the test that would have caught this in the first place.

### What is parked behind it

Trigger ACTION effects, step 1 of four. Built, tested and discarded
rather than committed inert, because it called `pending_store.store()`
and that call changes with this fix. What it was, for redoing:

    triggers table   action_type, action_parameter, action_values
                     columns, added through add_column_if_missing so
                     a triggers.db from patch 271 survives -- verified
    evaluator        proposes ONLY when `told` is non-zero, so never
                     on a baseline or a suppressed repeat; as the
                     owner; never raising, so a refused proposal costs
                     one trigger its action

Still to do after it: the endpoint validating an action config, role
recipients, YAML triggers naming an owner (which may be a service
user), and the UI for the first two.

---

## What to build next, in dependency order

The phases above are grouped by SUBJECT. This is the same work grouped
by WHAT BLOCKS WHAT, which is the more useful question once several
phases are half-done.

**Rewritten September 19, after phases 0, 1 and 3.5 closed.** The
previous version had become a list of DONE markers, which is a record
rather than a plan.

### Ready now — nothing blocks these

    R3    runtime role editing   UNBLOCKED: 3.5 is done, and its
                                 question -- whether a grant edit
                                 should itself pass through the
                                 approvals queue -- is now answerable
                                 against a settled model
    2.4   the remaining UI       vertex-lite's second half, the
          halves                 view-state matrix, and which screens
                                 show the checkbox-above-the-row
                                 problem. Each small, each verifiable
                                 now that browser tests exist
    1.3   restore verification   the script checks an inventory; only
                                 a real restore into a stopped
                                 deployment proves one

### Ready, but each needs ONE decision from a person

    R2    the context-rot fix    MEASURED: the loop can exceed its own
                                 4096-token window at HOP FOUR. Three
                                 paths -- summarise older hops, cap
                                 what enters `gathered`, raise the
                                 window -- with different costs
    3.0   triggers               mirror health first, notification
                                 effects only, because that condition
                                 admits no action effect. Needs a
                                 DELIVERY CHANNEL, which does not
                                 exist at all
    2.1   Query's starters       DEFERRED on a leak: a starter naming
                                 an id says it exists. The shape of an
                                 answer is in QUERY_PLAN.md

### Blocked on something genuinely absent

    2.2   the measurement        A MODEL. phi4-mini is ~3.8B, and the
          session's questions    published floor for reliable
                                 multi-step tool use is 14B -- or a
                                 small model with real tool-call
                                 training (Qwen 3.5 4B scored 97.5%)
    3.0   object-set conditions  SAVED VIEWS SERVER-SIDE. They are
                                 {name, url} in a browser today, where
                                 nothing scheduled can reach them
    3.6   fusion                 THE GOLD LAYER, which nothing has
    3.2   multiple workers       closer than it was -- pending writes
                                 now persist -- but still a storage
                                 question

### Designed, unbuilt, and worth VERIFYING before building

    3.1   the plugin API         THIRD_PARTY_EXTENSIONS.md
    3.6   fusion and identity    FUSION_AND_IDENTITY.md
    3.3   schema migrations      no design yet

**THE REASON THAT LAST GROUP IS SEPARATE:** of the last several design
entries picked up and built, MOST WERE SMALLER THAN WRITTEN -- 0.3's
cache bound, 0.5.5's drift report, 3.5's ordered-vs-incomparable
question, and 3.5's intersection item. Each described a defect that
reading the code carefully ruled out.

So a design document is a claim like any other. Verify it against the
code before building from it, and expect the work to be smaller.

**THE HONEST READING:** three items are ready now, three need one
decision each, and four are blocked on something real. Nothing in the
first group depends on anything in the last.

The largest single unlock is **saved views server-side** -- it is the
prerequisite for object-set triggers, and the same machinery is what a
notification's per-recipient evaluation would run.

## Found on review, September 19 — four things no phase held

Re-read of the nineteen planning documents against this roadmap. Four
real items had no entry, and they are placed by what they depend on
rather than by how interesting they are.

### R1. ~~`search_around` is not capped~~ DONE

**THE FRONT DOOR IS SHUT AND THIS ONE IS OPEN.** Phase 0.2 capped
`search_object` and `search_object_free_text` at MAX_SEARCH_SCAN.
`search_around` -- the link traversal -- has no limit at all.

That matters because it is the exact path ROADMAP.md profiled:

    _io.open      1.21s   (200,006 calls -- audit logging)
    file close    0.71s
    SQL query     0.66s
    json encode   0.56s

**A 200,000-object traversal writes 200,006 audit lines.** Authorization
was fixed, the engine was never the problem, and what remains is the
audit trail's own volume. The entry in ROADMAP.md has "been wrong
twice, each time because a fix moved the bottleneck somewhere the
previous profile could not see" -- and phase 0.2 moved it again,
without touching this path.

**CAPPED ON THE TARGETS, NOT THE SOURCES.** Capping sources further
would answer a different question wrongly -- somebody asking about ten
customers with a hundred transactions each wants all thousand, and the
limit that matters is on what comes back.

**MEASURED BEFORE BUILDING:** an audit line costs about 11
microseconds, so a million-target traversal spends ELEVEN SECONDS
writing its own trail before any data reaches the caller.

**AND IT REPORTS**, through the same `scan_truncated` the searches
use.

### R2. ~~Context rot in the agent loop~~ MEASURED

UI_ROADMAP names it as "a risk to what already exists, not a feature":
current research describes "a model's effective recall degrading as
the token count grows, WELL BEFORE the hard context limit is reached".

**Our agent accumulates `gathered` across every step and feeds it back
each hop.** A query touching many objects degrades the ANSWER before
it errors -- "the failure mode is a worse answer, not a crash, which
is the hard kind to notice. We have never measured where that begins."

**MEASURED, on the shipped deployment with num_ctx 4096:**

    system prompt alone          ~1,138 tokens    28% of the window
    + one heavy hop              ~2,030            50%
    + four heavy hops            ~4,664           114%  OVERFLOWS
    + eight (default max_hops)   ~8,176           200%

**THE LOOP CAN EXCEED ITS OWN CONFIGURED WINDOW AT HOP FOUR**, well
before it stops on its own. `MAX_OBJECT_IDS` of 20 and `max_hops` of 8
were chosen for other reasons and do not bound this.

**A WARNING AT 80% IS BUILT**, which is AWS's published threshold for
exactly this. Past the window the server TRUNCATES rather than
failing, so the warning says that -- a note that a prompt is large
reads as a performance remark.

**STILL OPEN: what to DO about it.** Summarise older hops, cap what
enters `gathered`, or raise the window. That is a separate decision,
and it needed this measurement first -- a fix without one is a guess
about a threshold nobody had found.

### R3. Runtime role editing — DEPENDS ON HOT RELOAD, WHICH EXISTS

UI_ROADMAP item 13: policy.yaml becomes editable while the
application runs. The reload machinery it needs is built and has its
own plan document.

**NOT SCHEDULED HERE**, because it is a UI feature with a security
question attached -- who may edit grants, and whether a grant edit
should itself pass through the approvals queue. That question belongs
with phase 3.5's work on non-user-derived constraints rather than
before it.

### R4. ~~A restore script~~ DONE

The backup exists; restore is `cp -a`. Honest for a stopped
deployment, and it leaves the inventory unchecked: the backup NAMES
what was absent, and nothing verifies a restore is complete before
somebody depends on it.

Small, and the natural completion of 1.3.

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
