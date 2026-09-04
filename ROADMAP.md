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
1. **Schema metadata richness.** Add `description` to object type
   fields AND action parameters (currently absent from both --
   confirmed by reading the real YAML directly, not assumed). Add a
   REAL, structurally-ENFORCED `required` flag to object type fields
   -- deliberately not just a documentation-only hint, per "I want all
   schema metadata to actually be something checked by the system":
   at deployment-load time (the same moment `validate_action_types()`
   already runs), verify every `create`-operation action targeting a
   type with `required` fields actually addresses each one (a literal
   or a parameter reference). Real, honest limit: this is a
   STRUCTURAL check (was the field addressed at all), not full
   field-VALUE validation (does the value satisfy a real constraint
   like a range, pattern, or enum) -- see "Deferred, not blocking the
   near-term list" below for that fuller feature.
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
4. **A persistent, reviewer-based `PendingWriteStore` rebuild, on
   PostgreSQL specifically.** The one genuinely blocking gap for the
   Approvals inbox: today's store requires the CONFIRMING user to be
   the exact same person who proposed the write (`pop()`'s own
   `owner_user_id != requesting_user_id` check) -- there is no
   "someone else reviews this" concept anywhere in the current model.
   Also in-memory only (lost on restart; the store's own docstring
   already, honestly documents this as incompatible with a future
   multi-worker deployment) and has a 15-minute TTL, fine for "are you
   sure" but wrong for "wait for a real reviewer." Rebuilt as: real
   persistence, reviewer eligibility derived from the SAME RBAC check
   `propose_action` already uses (never a separate ACL), real listing
   by eligibility (not owner), and a real, much longer lifetime.
   Scoped to PostgreSQL specifically, not a full-system migration --
   this is the one piece that already, directly needs what Postgres
   uniquely provides (real concurrent-writer support, and a real
   shared store reachable from more than one worker process), so it's
   the natural, minimal place to start -- see "PostgreSQL scope" below
   for the fuller reasoning and the SQLite-for-dev/Postgres-for-prod
   pattern this adopts.
5. **Real query/read methods on `AuditLog`.** Currently write-only --
   plenty of real `log_*()` methods, confirmed zero methods that read
   anything back. Approvals' own "audit trail of past decisions" needs
   real `get_*()` methods added, not just more logging.

### PostgreSQL scope

Scoped narrowly and deliberately: the NEW pending-writes store above
moves to PostgreSQL; every existing SQLite file (`mediator.db`,
`write_log.db`, `credentials.db`, and the rest) stays on SQLite for
now. Revisit moving any of the others only if real concurrent-write
pressure actually shows up there -- not preemptively.

**Local dev keeps SQLite as the default, production uses Postgres for
whatever's actually been migrated to it** -- a common, well-supported
pattern, and a real, direct benefit for this project specifically:
the backend's own 562-test suite leans on how fast a SQLite file (or
in-memory DB) is to create and tear down per test, run constantly
during development. Real, honest risk that comes with this split,
not just upside: SQLite and PostgreSQL aren't perfectly identical in
behavior (date/time handling, case sensitivity, some JSON function
differences) -- something could pass locally on SQLite and break in
production on Postgres. Mitigation: keep the fast SQLite suite as the
everyday default, but also run the full suite against a real,
running Postgres instance in CI (or at minimum periodically) for
whatever part of the system actually lives there, catching divergence
before it ships rather than after.

### Deferred, not blocking the near-term list -- noted so they aren't lost

- **Full field-VALUE validation** (real constraints -- ranges,
  patterns, enum membership -- not just the structural "was this
  field addressed" check in phase 1 above). Genuinely valuable, but
  doesn't block any of the four near-term sub-apps, so it's deferred
  rather than competing with them for priority right now.
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
  principle.
- **A full Pydantic retrofit of the ontology loader's own
  validation** (as opposed to using Pydantic for new API response
  models, which is already agreed and in the build-order list above).
  Considered directly and deliberately NOT adopted, not merely
  deferred -- the schema loads exactly once, at deployment startup,
  never a hot path, so Pydantic's own real strengths (fast parsing,
  automatic coercion, tight per-request integration) don't apply
  here; the existing `validate_*` functions are real, correct,
  already-tested code, and converting their genuinely cross-
  referential checks to Pydantic's own `model_validator` hooks
  wouldn't make them simpler, only riskier to rewrite for no real
  gain.
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
3. **A Pending Changes / Approvals inbox.** The two-phase
   propose/confirm mechanism already exists (`write_log.db`,
   confirm/reject); this is giving it its own queue view across the
   whole org instead of only inline, per-submission. Reviewer
   eligibility derived from the SAME RBAC+MAC check that gates the
   underlying action -- never a separate ACL. A field-level
   before/after diff (Foundry's own convention: changed value
   highlighted, prior value muted), itself filtered through MAC so a
   reviewer never sees a field they couldn't otherwise access.
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
