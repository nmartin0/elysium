# Elysium: sub-app roadmap

This tracks planned, future sub-apps for this project, modeled on
Palantir Foundry's own ontology-aware application suite but scoped
down to Elysium's actual architecture: a single ontology per
deployment, no multi-tenancy, no code-customization layer, a
YAML-defined schema, server-enforced field-level RBAC+MAC, a
two-phase propose/confirm writeback, and an LLM agent that queries
the ontology through tools rather than a full enterprise platform.

The comparison this is based on came from a real, structured research
pass against Palantir's own current documentation (plus third-party
critique where it existed) — see `PRINCIPLES.md`'s own "Research real
precedent before inventing a pattern" principle for why that mattered
here specifically, not just generally. This file is the durable
record of that research's conclusions; the research itself, if it
needs revisiting, should be redone rather than assumed still current
-- Foundry's own graph/branching UX was already mid-change (Quiver's
graph mode redesigned, ontology branches being sunset for Global
Branching) at the time this was written.

---

## Backend foundation work (build before the sub-apps above)

Raised directly -- "we need to work on the backend first, so that it
will support the sub-apps" -- after a real, code-level audit (not
just docs) found several genuine gaps between the current backend and
what the near-term sub-apps above actually need. Each finding below
was traced to the real, specific line of code that confirms it, not
inferred.

### In build order

0. **Convert every existing API route to a real, typed Pydantic
   `response_model`.** Most routes currently return a bare `dict`.
   Two real, independent reasons this matters, not just one: (a)
   FastAPI's own built-in OpenAPI generation only knows a route's real
   response shape from a declared `response_model` -- a `dict` return
   produces a useless, field-less generic schema, which blocks the
   TypeScript codegen item below entirely; (b) `response_model` is
   real, standard FastAPI practice for a genuine security reason
   beyond typing -- it automatically FILTERS the response, silently
   stripping any field the declared model doesn't include, before it
   ever reaches the caller. A bare `dict` has neither protection.
   Scoped as its own, first step specifically so every route built in
   the phases below is done the right way from day one, not built
   against the old pattern and retrofitted later.
1. **Define the ontology's own structural shape -- object types,
   fields, action types, parameters -- as real Pydantic models.**
   Revisited directly, not the original position: the real case for
   this isn't a performance one (the schema loads once, at startup,
   never a hot path), it's genuine DE-DUPLICATION -- one, real
   definition of "what a field looks like" instead of two
   independently-maintained ones (the raw dict shape the loader
   checks, and a separate Pydantic model the schema-viewer API would
   otherwise need of its own). These models both parse/validate the
   loaded YAML AND directly serve as, or feed, the API response shapes
   from item 0 above. `description` added to both object type fields
   and action parameters this way too (confirmed absent from both
   today by reading the real YAML directly, not assumed) -- a natural,
   optional field on the same model, not a separate addition.

   Deliberately, explicitly NOT forcing the existing, genuinely
   CROSS-REFERENTIAL checks (does an action's `object_reference`
   parameter point at a real, declared object type elsewhere in the
   same schema) into this -- confirmed directly, not guessed at, that
   this doesn't belong inside a single Pydantic model's own
   `model_validator`: those checks inherently need to see the WHOLE,
   assembled schema at once, so they stay their own, separate,
   already-correct pass (the existing `validate_action_types()`/
   `validate_object_types()`/`validate_roles()`), run AFTER Pydantic
   has structurally parsed each individual piece -- not retrofit into
   a shape they were never a natural fit for.

   A REAL, genuine "required" flag on OBJECT TYPE fields (as opposed
   to action parameters, which already have one) was investigated and
   deliberately NOT built, once real precedent was actually checked
   rather than assumed: Palantir's own real, published SDK schema for
   an action's own parameter (`ParameterDict`, in their public
   `foundry-platform-python` docs) has `required: StrictBool` -- but
   there is no equivalent anywhere on the object type's own property
   definition. `required` is exclusively an action-parameter concept
   in Palantir's own, real, time-tried model. Elysium's own existing
   convention already matches this exactly (`required` only ever
   declared on `action_types.*.parameters.*`), and confirmed directly,
   already genuinely enforced today, not just declared --
   `write_mediator.py`'s own real check
   (`if param_spec.get("required") and param_name not in parameters:
   raise ValueError(...)`) already rejects a missing required
   parameter at proposal time. A real, valuable finding that PREVENTED
   building something with no real precedent anywhere, not a gap that
   needed closing.
2. **Real aggregation/counting primitives in `DataMediator`.**
   `count_objects()`, `aggregate_by_field()`, and a count-only variant
   of the reverse-link resolver -- confirmed as a real, total gap
   today (DataMediator's entire public surface is 6 methods, none of
   them aggregation; `resolve_reverse_link()` already fetches full,
   real linked-id lists efficiently via real SQL, but has no
   count-only form). Built on the SAME MAC-safe pattern
   `search_object()` already uses and already has real test coverage
   for -- SQL pushdown for the DATA criteria, then the same
   `check_access()` every other read path uses, applied to the
   resulting id set, THEN aggregated in Python. Never push MAC itself
   into a raw SQL `WHERE`/`GROUP BY` -- confirmed directly (not
   assumed) that MAC filtering already happens in Python, per-id,
   after the SQL layer returns; a naive SQL-level aggregation would
   silently ignore it.
3. **Pagination.** Real cursor/offset support on search, replacing the
   current hard 50-result cap with `total_matches` returned but no way
   to actually fetch more -- already named as a known gap in the
   route's own existing comments.

### PostgreSQL scope

Deliberately deferred, not scoped into the build order above --
"let's defer this for now, and continue using the SQLite internally
but migrate to PostgreSQL eventually." When it IS taken up, the scope
already worked out stays the right one: NOT a full-system migration,
just the new, rebuilt pending-writes store (see "Deferred" below) --
that's the one piece that already, directly needs what Postgres
uniquely provides (real concurrent-writer support, and a real shared
store reachable from more than one worker process), confirmed
directly against the store's own docstring already, honestly
documenting incompatibility with a future multi-worker deployment.
Every existing SQLite file (`mediator.db`, `write_log.db`,
`credentials.db`, and the rest) stays on SQLite regardless, revisited
only if real concurrent-write pressure actually shows up there too --
not preemptively.

**Local dev keeps SQLite as the default, production uses Postgres for
whatever's actually been migrated to it, whenever that happens** -- a
common, well-supported pattern, and a real, direct benefit for this
project specifically: the backend's own 562-test suite leans on how
fast a SQLite file (or in-memory DB) is to create and tear down per
test, run constantly during development. Real, honest risk that comes
with this split, not just upside: SQLite and PostgreSQL aren't
perfectly identical in behavior (date/time handling, case sensitivity,
some JSON function differences) -- something could pass locally on
SQLite and break in production on Postgres. Mitigation, whenever this
is taken up: keep the fast SQLite suite as the everyday default, but
also run the full suite against a real, running Postgres instance in
CI (or at minimum periodically) for whatever part of the system
actually lives there, catching divergence before it ships rather than
after.

### Deferred, not blocking the near-term list -- noted so they aren't lost

- **Full field-VALUE validation** (real constraints -- ranges,
  patterns, enum membership -- not just the structural "was this
  field addressed" check the original required-field idea explored).
  Genuinely valuable, but doesn't block any of the four near-term
  sub-apps, so it's deferred rather than competing with them for
  priority right now.
- **A real shared-properties / interface concept** in the ontology
  schema (RDFS-style, matching what Palantir itself calls
  "Interfaces") -- e.g. a `Timestamped` interface both `Customer` and
  `Account` could `implement`, instead of declaring the same fields
  twice, independently, with no shared contract. Confirmed YAML is
  fully sufficient to represent this -- the real work is entirely in
  the loader (resolving `implements` and merging fields before
  validation runs), not a new file format. Deliberately deferred, not
  rejected -- worth real design attention once there's a second real
  need for it, matching this project's own "no speculative code"
  principle. A real, concrete design wrinkle flagged for whoever
  eventually picks this up, not resolved now: should a LINK's own
  `target` be allowed to name an interface, not just a concrete
  object type -- e.g. a hypothetical `Comment` object type with
  `subject: {type: link, target: Auditable, cardinality: one}`,
  letting one field point at EITHER a `Transaction` or an `Account`
  (whichever the comment actually concerns), if both implement a
  shared `Auditable` interface, instead of needing one separate field
  per possible concrete target type.
- **A persistent, reviewer-based `PendingWriteStore` rebuild on
  PostgreSQL, and the real `AuditLog` query methods that would back
  its own history view.** Deferred together, deliberately -- "let's
  defer this for now, and continue using SQLite internally but
  migrate to PostgreSQL eventually." This is still the one, real,
  confirmed BLOCKING gap for a real Approvals inbox (today's store
  requires the CONFIRMING user to be the exact same person who
  proposed the write, is in-memory only, and has a 15-minute TTL --
  see this file's own git history for the fuller, original finding),
  so the Approvals sub-app itself (still item 3 in "Near-term" below)
  is correspondingly on hold until this is taken up, not truly
  buildable in parallel with the rest of the near-term list above.
  When it IS taken up, the real design already worked out (reviewer
  eligibility from the SAME RBAC check `propose_action` already uses,
  real listing by eligibility not owner, real persistence, a real,
  much longer lifetime) and the PostgreSQL scoping (see "PostgreSQL
  scope" above -- just this one new store, not a full-system
  migration) both still stand.
- **PostgreSQL row-level security for MAC.** Explicitly held off --
  MAC and RBAC both stay in Python, in `check_access()`, as the one,
  single point of enforcement. Real reasons this was set aside, not
  just deferred by default: it would put the same security decision
  in two places (Python and a separate SQL policy) that could quietly
  drift apart from each other; RLS filters ROWS, not the individual,
  per-role COLUMNS Elysium's own RBAC already distinguishes; and MDOs
  (a single logical object spanning more than one physical table)
  would need coordinated policies across multiple tables for one MAC
  decision. Revisit only with a real, concrete reason (e.g. a
  compliance requirement, or a real incident the Python-only check
  wouldn't have caught) -- not preemptively.
- **Column-level `GRANT` + `SET ROLE` as a defense-in-depth layer for
  RBAC specifically** (a real, named pattern -- one real Postgres
  database role per Elysium ROLE, each granted `SELECT` on only the
  columns that role can read, assumed per-request via `SET ROLE`).
  Genuinely more promising than RLS for RBAC specifically, since RBAC
  is role-based and field-level -- exactly what column grants express
  natively -- but MAC (a per-object, per-row, data-dependent
  comparison) still couldn't be expressed this way, so this would
  only ever cover RBAC, with MAC staying in Python regardless. Same
  two-places-could-drift risk as RLS, and the same real mitigation
  it would need (generated from the same source as `policy.yaml`,
  never hand-maintained twice) before it's worth building. Held off
  for the same reason as RLS -- revisit only with a real, concrete
  need.

### A separate, later, dedicated pass -- not part of the phases above

- **A full audit of the existing Python codebase for idiomatic
  SQL/Python alignment** -- confirmed, current (2026) industry
  guidance converges cleanly: push set-based work (aggregation,
  filtering, joins, sorting) to SQL, keep business/security logic
  (like `check_access()`) in Python, and never push business logic
  into stored procedures/triggers. The reverse-link-fetch-then-count
  gap (phase 2 above) is one already-known example of Python doing
  work SQL should; the audit would look for others, AND confirm the
  new aggregation work itself doesn't accidentally cross the same
  line the other way (business logic leaking into raw SQL). Scoped as
  its own, dedicated review pass, not folded into the phases above,
  since it's a different kind of activity -- reviewing and refactoring
  EXISTING code, not building new capability.

---

## Read-only data mirror architecture

Raised directly -- "we must be able to provide a GUARANTEE that the
outside, third-party databases are READ-ONLY" -- followed by a real,
structured research pass into how Palantir Foundry itself handles the
exact same relationship (ingestion, writeback, schema drift, staleness
visibility, and cross-source joins), and a real, careful discussion of
what to adopt at Elysium's own, much smaller scale versus what would
be disproportionate. A genuinely new, real architecture initiative --
not a small addition -- covering the entire read path (`DataMediator`);
the existing write path (`WriteMediator`, `propose_action`,
`confirm_and_execute`) is explicitly, deliberately UNCHANGED by every
phase below, and stays live, direct, and exactly as correct as it is
today.

### Why this doesn't conflict with TransferFunds' own correctness

A real, resolved objection, worth recording since it shaped the whole
design: `confirm_and_execute()`'s own optimistic-concurrency check
(comparing `expected_current_values` against the real, CURRENT value
at write time) doesn't care how the original read was obtained --
live, or from a mirror synced minutes ago. It only checks whether the
value right now, at write time, still matches. A stale read can only
ever produce a real, correct rejection asking for a retry -- it can
never produce an unsafe write. Staleness in the read path is a
retry-rate question, not a correctness one; this was already true
before this whole initiative, since a human reviewing a proposal
between propose and confirm already creates a real staleness window
today.

### Phases, in real dependency order

**Phase 0 -- prerequisite refactor, discovered during scoping, not
originally planned.** `WriteMediator` does not have its own adapter
set today -- confirmed directly: it reaches into `self.mediator`'s own
adapters (`_resolve_shared_storage`, `_write_limiter_for_silo`,
`_locks_for_objects`, `_type_schema`, `_read_field_with_log_check`,
`_security_allowed`) to perform its own writes. `DataMediator` cannot
safely move to a read-only credential until `WriteMediator` has its
own, independent, still-write-capable adapters. A pure refactor --
zero behavior change, both mediators still pointing at the exact same
real database at the end of this phase, just via separate connections.
**Open question, not yet decided:** does EVERY one of those six
borrowed methods genuinely need an independent copy, or are some of
them (e.g. `_type_schema`) legitimate reads `WriteMediator` could keep
sharing safely? Deliberately not resolved yet -- worth a real, careful
look at each of the six individually, not a blanket "duplicate
everything" move.

**Phase 1 -- the real, two-layer read-only guarantee (depends on
Phase 0).** Two independent, structurally separate enforcement layers,
resolved directly, not left as a tradeoff:
- **Credential-level**: a genuinely separate, `SELECT`-only database
  credential for `DataMediator`'s own adapters specifically, documented
  as a real, required deployment step in `INSTALL.md` -- matching
  Palantir's own real, confirmed practice (their own docs: "syncs can
  change the source system if the source credentials allow it... you
  should only grant Edit access... to users whom you would also grant
  full access to the account"). The credential is the real enforcement
  point, not application code alone -- confirmed as Palantir's own
  actual practice, not assumed.
- **Code-level**: `sqlite3.Connection.set_authorizer()`, confirmed
  directly, empirically, before proposing it (a real, isolated test:
  SELECT succeeded, INSERT/UPDATE/DROP were all genuinely denied at
  the SQLite engine level itself, not just skipped by application
  code) -- a second, structurally independent layer, so a bug in
  either the credential or the authorizer callback alone still leaves
  the other holding.

**Phase 2 -- raw ingest sync module (depends on Phase 1's read-only
credential existing).** PyIceberg (confirmed directly: Apache License
2.0, from `apache/iceberg-python`'s own `pyproject.toml`) manages the
mirror's own versioned storage; a new `core/mirror/` package
(`interface.py` then a concrete `iceberg_sync.py`, matching the
established `DataSiloAdapter` interface-then-implementation
convention) reads through the Phase 1 credential and writes one raw
Iceberg table per real source table -- matching Foundry's own "ingest
as-is" philosophy. Sync cadence: a real, configurable deployment
setting (time-based, with a manual "sync now" escape hatch), not
hardcoded -- the exact default interval is not yet decided. Schema
drift: the schema is pinned at sync time; a column the ontology
expects but the sync can no longer find fails the sync loudly, leaving
the last-good mirror in place -- matching this project's own existing
"fail loudly, never silently substitute" discipline, and matching
Foundry's own real, confirmed behavior (schemas pinned at deploy,
column removal is a real, named "state-break" requiring explicit
acknowledgment). A real, automated license-scanning check (e.g.
`pip-licenses`, added to `lint.sh`) belongs in this phase specifically,
since it's the phase that actually introduces the new dependency.

**Phase 3 -- the transform pass (depends on Phase 2's raw tables
existing).** Materializes one clean, per-object-type Iceberg table
(`customer_clean`, etc.) -- the direct analog to Foundry's own
"backing dataset per object type." **Open question, leaning but not
yet finalized:** `DataMediator`'s own existing field/MDO resolution
logic should almost certainly be EXTRACTED into a shared function
both the live path and this new batch pass call, rather than a second,
parallel implementation written from scratch -- a direct DRY question,
not just a detail, given this project's own established discipline
against exactly this kind of duplication. Verification: read the same
real object both live and from the new, materialized table, and diff
them -- the real proof of correctness, not just "the batch job ran
without an error."

**Phase 4 -- repointing `DataMediator`'s actual reads (highest risk,
done last, depends on 1-3 all independently verified).** A real,
explicit config flag -- live source, or local mirror -- never an
unconditional, all-or-nothing cutover with no way back. The most
extensive testing pass of the whole project: every existing read route
(`search_object`, `get_field`, everything the LLM touches) must behave
identically under both modes, verified with a real, live, side-by-side
comparison before this is ever the default.

### The real, settled tool choices, and why

**DuckDB** (confirmed directly: MIT, from the official `duckdb/duckdb`
repository and its original creators, CWI) queries the local mirror at
read time -- genuinely fast for the aggregation-heavy work already
planned (see "Backend foundation work" above), and this is the SAME
tool already recommended there, not a second, separate choice.

**PyIceberg** (Apache License 2.0) manages the mirror's own versioned
storage specifically. Confirmed directly, not assumed, before
accepting this: every mature, real "table format" library in this
exact space (Apache Iceberg, Apache Hudi, and Delta Lake's own
tooling, including its non-JVM `delta-rs`/`deltalake` Python package)
converges on Apache 2.0, by real, structural Apache-Software-
Foundation governance necessity, not project-by-project preference --
there is no genuinely mature, MIT/BSD-licensed alternative at this
level of production-readiness. Confirmed acceptable under this
project's own real licensing rule (see `PRINCIPLES.md`'s own "Third-
party code: install and import, never modify" principle) specifically
because Elysium never modifies third-party source at all -- the one
real clause distinguishing Apache 2.0 from MIT/BSD (disclosing a
modification, if one is ever made AND redistributed) can never
actually trigger under that rule, for any dependency, on any license.

### What this actually adds, once all five phases are done

Not just an architecture change -- real, concrete new capability:
1. A real, provable, two-layer read-only guarantee (credential +
   code-level), not a promise resting on application-code discipline
   alone.
2. Resilience to the customer's own database being unreachable --
   Elysium keeps answering real questions from the last-good mirror
   instead of going dark entirely.
3. Faster query and LLM response times -- no live network round trip
   to the customer's own infrastructure on the most common path
   through the whole system.
4. A real, practical foundation for the already-planned aggregation/
   analytics work (Object Explorer parity, charts) -- this phase is
   what makes that OTHER roadmap item fast and practical to build well,
   not just a safety measure in isolation.
5. Real, visible data freshness -- a genuine "last synced at," usable
   anywhere a person needs to know how current their information is
   (the schema viewer, a pending proposal's own review screen).
6. Safe, loud failure on schema drift, instead of silent corruption.
7. A real, queryable history of the data itself, via Iceberg's own
   snapshot mechanism -- not yet built as a user-facing feature, but
   the underlying capability exists the moment the mirror does.
8. Writes stay exactly as they are today -- live, direct, immediate,
   with the same real-time correctness check already in place. This
   whole initiative is additive to the read path only.

---

## Near-term (prioritized, in build order)

Recommended order, from the original research: lowest-risk and
highest-precedent first, highest-effort/lowest-immediate-ROI last.

1. **Read-only Ontology schema viewer.** Browse the existing YAML
   schema (object types, properties, link types, cardinality) filtered
   through the same RBAC+MAC checks the API already enforces --
   restricted fields hidden or marked, never a separate permission
   model. Modeled on Swagger UI / GraphQL introspection / DBeaver's
   read-only schema navigator, deliberately NOT an editor -- editing
   the live ontology has real, separate security implications (see
   "Future / later horizon" below).
2. **Object Explorer parity for Browse.** Saved Explorations (persist
   filter/search state, re-run live) as a genuinely separate primitive
   from Saved Lists (persist a frozen set of object ids) -- Foundry's
   own users conflate these if the distinction isn't explicit. Bulk
   Actions on a result set, reusing the existing propose/confirm flow,
   with a real batch cap. A small set of filter-capable charts
   (Listogram, Histogram, Single Statistic) before anything fancier
   (maps, grid plots).
3. **A Pending Changes / Approvals inbox.** *(Currently on hold --
   its own real, blocking backend prerequisite, the `PendingWriteStore`
   rebuild, is deferred pending an eventual PostgreSQL migration; see
   "Backend foundation work" above.)* The two-phase propose/confirm
   mechanism already exists (`write_log.db`, confirm/reject); this is
   giving it its own queue view across the whole org instead of only
   inline, per-submission. Reviewer eligibility derived from the SAME
   RBAC+MAC check that gates the underlying action -- never a separate
   ACL. A field-level before/after diff (Foundry's own convention:
   changed value highlighted, prior value muted), itself filtered
   through MAC so a reviewer never sees a field they couldn't
   otherwise access.
4. **Vertex-lite: a minimal, read-only link explorer.** The schema
   already has real `link` fields (confirmed: 5 in the test fixtures,
   2 in the real deployment config) and single-hop link navigation
   already works in `ObjectDetailPanel`. This extends that to an
   explicit "Explore related" action showing link-type counts BEFORE
   expansion (so fan-out is never a surprise), starting read-only (no
   drag-to-rearrange, no styling) before ever considering an editable
   canvas.

---

## Future / later horizon

Raised directly, once the near-term list above is in place --
"those will integrate perfectly into our system once we have the
basic parts in order." Listed here honestly at different levels of
research depth, not all equally ready to scope:

- **A full Ontology Manager** (self-service schema editing, not just
  the read-only viewer above). Deliberately sequenced after the
  read-only viewer is in real use, and after a real, separate design
  conversation about who is allowed to edit the ontology itself --
  this has genuine security implications beyond the RBAC+MAC model
  covering DATA access today (indexing, backing-datasource
  permissions, and policy composition all become live concerns the
  moment schema itself is editable through the app, not just
  deployment config).
- **Quiver/Contour/Insight-style point-and-click analysis.**
  Structured, non-LLM charting/aggregation over ontology data,
  complementing `Query`'s own natural-language analysis with a
  deterministic "build me a chart" tool that doesn't depend on the
  LLM at all. Noted directly in the original research as real,
  existing Foundry capability, but NOT yet given the same close,
  structured research pass Vertex and Ontology Manager received --
  worth a dedicated, focused research pass of its own (chart types,
  aggregation UI, how results interact with the existing RBAC+MAC
  filtering) before this gets its own scoped build plan.
- **Automate.** Trigger-based automations when ontology data changes
  -- notifications, or auto-proposing actions when a condition is
  met. Not present in Elysium at all today, and like Quiver/Contour/
  Insight above, named directly in the original research as a real
  gap without yet having its own deep, structured research pass --
  needs one (trigger/condition model, how it interacts with the
  existing two-phase writeback and RBAC+MAC, notification delivery)
  before a real build plan exists.
- **Full Vertex** (beyond the near-term Vertex-lite item above).
  Styling (node fill/badges/layouts), grouping and grouping-into-
  edges for fan-out, saved/parameterized graph templates, and
  eventually simulations. Foundry's own users cite this as one of the
  platform's weaker areas ("the visualizations are poor" -- a
  recurring, if broad, third-party complaint), so this is deliberately
  the last, highest-effort item on the whole roadmap, not started
  until the minimal, read-only version has real, demonstrated use.

---

## Security hardening backlog

A separate, later, real backlog -- from the same "backend is a
kernel, frontend is userspace" hardening audit that also found and
fixed several real, confirmed bugs already (see mediator.py's,
api/routes.py's, api/app.py's, and core/llm/synthesis_prompt.py's own
AI-notes for those, plus the request-size-limit and /query rate-
limit additions -- not repeated here). These are real, considered,
but deliberately DEFERRED items, not gaps that slipped through
unnoticed:

- **`TrustedHostMiddleware` / `Host` header validation.** Not
  configured today. Investigated directly before deferring, not
  assumed low-risk by default: confirmed the `Host` header is never
  used anywhere in this codebase to construct any real output at all
  (no password-reset links, no redirects, nothing built from it) --
  the classic Host-header-injection attack it guards against
  specifically exploits apps that reflect or build output from that
  header, which this app simply doesn't do. Real, genuine reasons
  this stayed deferred rather than fixed outright, not just
  laziness: it would need a new, deployment-specific `allowed_hosts`
  config option that doesn't exist today (this project's own code
  doesn't know its own deployment's real domain name at build time),
  and Elysium is typically deployed behind a reverse proxy that
  already handles this concern at that layer. Revisit if a real,
  concrete reason emerges (e.g. a deployment that runs Elysium
  directly, with no reverse proxy in front of it at all).
