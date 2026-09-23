# Where we reinvented a wheel, and where we should not

Audited September 23, after the owner said canonical libraries are
welcome: "we can leverage canonical libraries instead of reinventing
functionality."

The audit went looking for hand-written code that a well-known library
already does, and for places the NEXT work would tempt us to write one.
Each finding is measured or read, not guessed.

---

# Part 1. Reinvented, and worth replacing

## 1.1 SnapshotCache -> cachetools.LRUCache (52 lines, confident)

core/mirror/snapshot_cache.py hand-rolls a byte-bounded LRU over an
OrderedDict: 52 lines of eviction, accounting and
too-large-to-cache handling.

VERIFIED: `cachetools.LRUCache(maxsize=..., getsizeof=...)` is exactly
this, byte-bounded eviction included -- installed and run, an entry of
60 bytes evicted by one of 50 against a 100-byte bound.

WHAT WE KEEP EITHER WAY: the DECISION of what to cache and when to
refuse (E-10's measurement, 200,000 rows), which is ours and is not in
any library. What goes is the eviction bookkeeping.

## 1.2 _percentile -> statistics.quantiles (stdlib, trivial)

core/request_metrics.py computes p50 and p99 by indexing a sorted
list. The standard library has done this since 3.8. The one behaviour
worth preserving is the docstring's: None rather than zero when there
is nothing to measure, "because zero would read as instantaneous".

## 1.3 TWO SQL ADAPTERS, one hand-built (628 lines, and the real one)

adapters/sqlite_adapter.py builds SQL by string interpolation -- 50
sites of `f"SELECT {id_column} FROM {table} WHERE ..."` -- while
adapters/sqlalchemy_adapter.py uses SQLAlchemy's expression API for
the same job. SQLAlchemy supports SQLite natively, so one of these is
a library doing the work and the other is us doing it.

WHY IT IS NOT A ONE-LINE DELETION, and why it is recorded rather than
done here:
  - the SQLite adapter also WRITES (create_object, write_fields); the
    SQLAlchemy one is read-only today, so consolidating means adding
    a write path to it, and the write path is the part of this system
    where a mistake reaches the customer's database;
  - 75 files reference the SQLite adapter, most of them tests using it
    as the cheap real database;
  - identifier quoting is the specific risk being carried: every
    f-string that interpolates a table or column name is a place where
    a declared schema controls SQL text. It is configuration rather
    than user input, which is why it has not bitten -- but a library
    that quotes identifiers correctly is the right answer to a class
    of bug rather than to its instances.

RECOMMENDED: fold SQLite into the SQLAlchemy adapter as a dialect,
write-path first, with the existing tests as the parity check.

---

# Part 2. NOT reinvention, and worth saying why

## 2.1 The changelog diff stays hand-written

core/mirror/changelog.py diffs two snapshots in 146 lines. DuckDB
would do it in SQL, and D5 accepted DuckDB for exactly this.

MEASURED FIRST (GOLD-4): the Python diff takes 377 ms for 200,000
rows against DuckDB's 76. It runs once per publication, beside a sync
that takes seconds. Adding a dependency to save 300 ms once a night is
not leverage, it is weight -- and the pure function has no backend to
be unavailable, which matters in the one place this system claims to
be a system of record.

## 2.2 Aggregates stay in Python

mediator.aggregate_by_field sums and counts over rows IN PYTHON. That
looks like a job for pandas until you notice WHICH rows: the ones the
caller is already authorised to see, resolved per object by MAC. A
dataframe would have to be built per request from an already-filtered
set, which is the expensive half of pandas for none of its benefit.

## 2.3 Metrics stay in SQLite, not prometheus_client

request_metrics persists to SQLite deliberately -- "in-memory counters
reset on every restart", which is what a Prometheus client gives you
between scrapes. Different requirement, not a missing library.

## 2.4 Standardisation, hashing and coercion stay as they are

unicodedata and hashlib ARE the canonical libraries here. And
coerce() is deliberately STRICTER than dateutil: it refuses
'2026-2-1' rather than guessing, because a mirror whose types are
wrong is worse than one that fails loudly. A permissive parser would
be a regression dressed as a dependency.

---

# Part 3. What the NEXT work would tempt us to write, and must not

## 3.1 Identity matching -> Splink (decided, GOLD-6)

Fellegi-Sunter, m and u probabilities, blocking, calibrated weights.
Writing that is a research project, not a feature. Decided in
FUSION_AND_IDENTITY.md, as an optional extra.

## 3.2 Clustering matched pairs into entities -> igraph or networkx

Turning pairwise matches into entities is connected components, and
every engineer's instinct is to hand-roll union-find in twenty lines.
igraph SHIPS WITH SPLINK (16 MB, already counted), and Splink's own
`cluster_pairwise_predictions_at_threshold` uses it. Use that.

## 3.3 Fuzzy comparison, if the deterministic matcher ever needs it
    -> rapidfuzz or jellyfish, never a hand-written Levenshtein

None exists today, which is the right amount. If a declared join ever
needs "these names are close enough", that is a library call.

## 3.4 The YAML round trip -> ruamel.yaml (already decided)

CONFIG_ROUND_TRIP_AND_UI_KIT.md measured it: PyYAML keeps 0 of 104
comments, ruamel keeps all and round-trips byte-identically.

## 3.5 And the honest counterweight

A dependency is not free even when it is canonical. Splink's 186 MB
across seven packages is the measured example. The test is not "is
there a library" but "does the library do the part we would get
WRONG": statistics, string distance, graph algorithms, date handling,
SQL generation -- yes. Diffing two lists of dicts, summing a column we
already hold in memory -- no.
