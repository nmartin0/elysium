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
