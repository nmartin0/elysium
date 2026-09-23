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

---

# Part 4. When to take a dependency -- the framework, read properly

Added September 23, after the owner observed that the criteria in
Parts 1-3 were assembled on the spot. They were. The canonical
treatment is Russ Cox's "Our Software Dependency Problem" (2019,
later in CACM as "Surviving Software Dependencies"), and reading it
CORRECTS TWO OF MY CRITERIA AND ADDS THREE I DID NOT HAVE.

## 4.1 The cost model, which decides how much care is due

"The cost of adopting a bad dependency can be viewed as the sum, over
all possible bad outcomes, of the cost of each bad outcome multiplied
by its probability of happening." And the context sets the cost: a
hobby project's is near zero, while for "production software that must
be maintained for years ... servers may go down, sensitive data may be
divulged, customers may be harmed".

ELYSIUM IS THE SECOND KIND, and holds the customer's data under a
mandatory access control model. So the bar is not "is this library
popular" -- it is inspection, and the inspection is specified.

## 4.2 The inspection, which I was doing by vibes

Cox's checklist, and it is the thing to actually run before adding
anything:

  DESIGN        is the documentation clear? "If the authors can
                explain the package's API and its design well to you,
                the user ... that increases the likelihood they have
                explained the implementation well to the computer."
  CODE QUALITY  read some. "Does it look like code you'd want to
                debug? You may need to."
  TESTING       "Does the code have tests? Can you run them? Do they
                pass?" -- and if not, "that's a serious red flag".
  DEBUGGING     the issue tracker: many open bugs, long open, is bad;
                bugs "rarely found and promptly fixed" is great.
  MAINTENANCE   how long, how many people, still active.
  USAGE         many dependants means bugs found by others first, and
                is "a hedge against the question of continued
                maintenance".
  SECURITY      "Will you be processing untrusted inputs with the
                package?" and its NVD history.
  LICENSING     acceptable, and actually present.
  DEPENDENCIES  "Flaws in indirect dependencies are just as bad ...
                A package with many dependencies incurs additional
                inspection work."

## 4.3 What I got WRONG in Parts 1-3

**I used INSTALL SIZE as the headline argument.** 186 MB was the first
number I reported about Splink. Size appears NOWHERE in Cox's risk
framework, and rightly: it is a distribution constraint, not a risk.
It matters here only because some deployments are air-gapped, which
argues for an optional extra -- the conclusion was right, the stated
reason was not. The reasons that should have led are maintenance (an
active government team), licence (MIT), tests, and the seven
transitive packages each needing their own inspection.

**I dismissed recordlinkage for being stale**, on "hasn't been updated
since July 2023". Cox answers this directly: "some code really is
'done'", citing a package that "may never need to be modified again".
Staleness is a question -- is this finished, or abandoned? -- not a
verdict. Answering it means looking at the issue tracker and the
problem's nature, which I did not do.

## 4.4 What I did not have at all

**ABSTRACT THE DEPENDENCY.** "Define an interface of your own, along
with a thin wrapper implementing that interface using the dependency
... the wrapper should include only what your project needs."
GOLD-6 already chose a matcher interface, but as an architectural
preference rather than as risk management. It is both: it is what
makes replacing Splink a change to one file.

**USE THE LIBRARY AS A TEST ORACLE WHEN YOU HAND-WRITE.** Cox's own
strconv.IsPrint example, and an AWS team's write-up of dropping
buildkit, do the same thing: keep the library in the TESTS, comparing
your implementation's output against it, and ship neither the
dependency nor an unverified reimplementation. This is the missing
option in every "library or hand-write" argument I have made here,
and it fits several of them exactly.

**UPGRADE AND WATCH.** Equifax: a patched Struts released March 7,
breached May 13, 148 million people. "Every day you wait is another
day that attackers can break in." And watch for indirect dependencies
creeping in on upgrade -- the event-stream attack hid in a NEW
transitive package added by a release.

## 4.5 So: the rule for this project

  1. THE DEFAULT IS THE STANDARD LIBRARY, which carries no supply
     chain at all. statistics.quantiles over a hand-rolled percentile;
     unicodedata over a normaliser; hashlib over a digest.
  2. A NEW THIRD-PARTY DEPENDENCY REQUIRES THE INSPECTION in 4.2,
     written down in the commit that adds it. Not a vibe, a paragraph.
  3. PREFER A DEPENDENCY WE ALREADY HAVE over a new one, even when the
     new one is nicer. SQLAlchemy is already here; using it for SQLite
     adds no supply chain at all.
  4. WRAP IT behind an interface of ours, including only what we use.
  5. IF WE ONLY NEED A TINY FRACTION, hand-write it AND TEST IT
     AGAINST THE LIBRARY -- keeping the library in the test
     dependencies, not the runtime ones.
     WITH THE COUNTER-EXAMPLE IN MIND: the objection to "a little
     copying" is that copies keep bugs alive, the canonical case
     being binary search overflow. So this applies to code we can
     fully test, not to subtle algorithms.
  6. SUBTLE OR ADVERSARIAL DOMAINS ARE NOT OURS TO WRITE: statistics,
     string distance, graph algorithms, cryptography, date parsing,
     SQL generation, YAML round-tripping.
  7. PIN AND WATCH: lock files already do the first; the second means
     re-reading the inspection on upgrade, and noticing new indirect
     packages.

## 4.6 Re-scoring Parts 1-3 under this framework

  statistics.quantiles       STILL YES, and stronger: stdlib, no
                             supply chain, less code.
  SQLAlchemy for SQLite      STRONGEST OF ALL, and I under-sold it:
                             it adds NO new dependency, and identifier
                             quoting is exactly the "subtle domain"
                             of rule 6.
  cachetools                 WEAKER THAN I SAID. It is a new runtime
                             dependency to replace 52 tested lines
                             that also do something cachetools does
                             not (refuse an entry too large to cache).
                             Under rule 5 the better move is to keep
                             ours and TEST IT against cachetools'
                             semantics, if we want the assurance.
  the changelog diff         UNCHANGED: 377 ms measured, and the
                             pure function has no backend to be
                             unavailable.
  Splink                     UNCHANGED CONCLUSION, better reasons:
                             MIT, actively maintained by a government
                             team, wrapped behind our interface,
                             optional because of air-gapped
                             distribution -- not because it is large.

