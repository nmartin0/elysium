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

0. **DONE (Point 11).** Every route now declares a `response_model`;
   the work also closed a fourth instance of the internal-config leak
   this item existed to prevent. Reasoning kept below because the
   *why* still governs any route added later.

   **Convert every existing API route to a real, typed Pydantic
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
1. **NOT DOING -- the case for this evaporated.** The argument was
   de-duplication: one definition of "what a field looks like" instead
   of the loader's dict shape and a separate Pydantic model the API
   would otherwise need. Checked directly, those are not two
   definitions of one thing. `SchemaFieldResponse` exposes five keys;
   a real field definition carries twelve, and the difference --
   `storage`, `column`, `via_table`, `data_type`, `link_type` -- is
   exactly the internal-config leak `response_model` was added to
   close. They did not drift apart; they were pulled apart
   deliberately, and merging them would reintroduce the leak.

   The other half of the rationale was that `description` would come
   along "as a natural, optional field on the same model". It was
   added by hand instead. Only action PARAMETERS still lack one, which
   is a ten-line addition rather than a schema refactor.

   What would have been left: five structural validators replaced by
   models, four cross-referential ones (`_validate_security` walks
   link chains with cycle detection) kept regardless, and both
   maintained. Better error POSITIONS looked like a real gain, and
   turned out to be a separate fix that needed no Pydantic at all --
   see the per-entry object-type collection in
   scripts/lint_deployment.py.

2. **DONE (Points 6, 7, 11, 17).** `count_objects()`,
   `aggregate_by_field()` and `search_around()` exist, are exposed over
   HTTP, and are reachable by the agent. The MAC constraint described
   below is exactly why they are mediator methods rather than pushed-
   down SQL, and still governs anything analytical added later.

   **Real aggregation/counting primitives in `DataMediator`.**
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

Deliberately deferred, and the scope narrowed since this was first
written -- the earlier version said the rebuilt pending-writes store
"directly needs what Postgres uniquely provides". Re-examined, it does
not.

The stated reasons were real concurrent-writer support and a store
reachable from more than one worker process. Neither requires
Postgres:

- The shipped service runs a single uvicorn process -- no `--workers`
  flag -- so there is one writer today.
- SQLite already backs `write_log.db` and `credentials.db` under
  concurrent writers, through `immediate_transaction()` and a real
  concurrency suite that forces the interleavings rather than hoping
  for them.
- A file-backed store is reachable from several processes; SQLite's
  locking handles that, which is the case the in-memory store cannot
  handle at all.

So the pending-writes rebuild is blocked on its DESIGN -- who may
approve, whether a proposer may self-approve, what expiry means when a
human is slow -- and not on a database. Those two were conflated, and
separating them means the Approvals inbox does not have to wait for a
migration that has no other driver.

WHAT WOULD ACTUALLY JUSTIFY POSTGRES: sustained concurrent write
pressure that SQLite's single-writer lock cannot absorb, or a
deployment genuinely running multiple workers against one store. Both
are measurable, and neither has been measured because neither exists
yet. Every existing SQLite file stays on SQLite until one of them
does.

Row-level security and column-level GRANT (both in the deferred list
below) remain genuinely Postgres-dependent, since SQLite has neither
concept -- they are waiting on an adapter that does not exist, which
is a different kind of blocked from this.

### Deferred, not blocking the near-term list -- noted so they aren't lost

- **Large reads are bounded by AUDIT VOLUME, not by authorization or
  the engine.** This entry has now been wrong twice, each time because
  a fix moved the bottleneck somewhere the previous profile could not
  see.

  It began as "Elysium lacks the Spark fallback Foundry uses for
  search-arounds over 100,000 objects". Profiling showed the engine
  was never the problem: 82% was per-object `check_access`. Batching
  security resolution then fixed that, and the entry was rewritten to
  say the remaining ceiling was per-object authorization.

  Re-profiled after that fix, a 200,000-object search-around now
  spends its time here:

      _io.open      1.21s   (200,006 calls -- audit logging)
      file close    0.71s
      SQL query     0.66s
      json encode   0.56s

  Authorization no longer appears at all. Roughly 2.5s of it is
  writing 200,006 audit records, one file open apiece, against 0.66s
  of actual query.

  THE QUESTION IS NO LONGER PERFORMANCE. One user ran one
  search-around; the log now holds 200,006 near-identical records of
  it. Whether that is the right granularity is an audit DESIGN
  question -- Foundry logs actions, not every row a query touched --
  and answering it wrongly in either direction is worse than the
  current cost: too coarse and a real access becomes invisible, too
  fine and the log is unreadable exactly when someone needs to read
  it.

  The persistent-handle optimisation stays rejected for the reason
  already recorded: it breaks log rotation. That was measured at 3x
  and would not change the granularity question at all.

- **No password reset, and no way to set a known password.** The user
  directory has create, disable, enable and delete, but nothing to
  change an existing password, and `scripts/bootstrap_root` generates
  a random one it prints once. An operator whose user forgets theirs
  must delete and recreate the account.

  That loses nothing today, since an account carries no history of its
  own -- the audit log keys on user_id, which survives recreation. It
  stops being acceptable the moment anything is owned BY an account
  rather than merely recorded against it.

  Found while setting up local testing, where the same gap makes a
  known-password account impossible without deleting one first. A
  `--password` flag on bootstrap_root would fix the development half;
  the operational half wants a real reset path with its own audit
  entry.

- **No password policy at all.** Any string is accepted, including one
  character. Deliberate for a beta where the operator creates every
  account by hand, and wrong for a deployment that ever lets someone
  choose their own. Not fixed now because where the policy lives is a
  product decision -- a hardcoded minimum, a config option, or
  delegated entirely to an external identity provider are three
  different answers, and picking one silently would be the worst of
  them.

- **No statement timeout on a write, and the object lock is held for
  its duration.** `lock.acquire()` takes no timeout, and the lock is
  held across the adapter write. A pathologically slow statement
  therefore queues every other write to that object -- and, since
  locks are striped, to any object sharing its stripe.

  INVESTIGATED, AND SMALLER THAN IT FIRST LOOKED. I reported this as
  an unbounded wait and then measured it: SQLite's busy timeout is 5
  seconds by default and RAISES rather than hanging, so a contended
  write fails cleanly and the `finally` releases the lock. What
  remains is a genuinely slow-but-valid statement -- a large scan, a
  stalled disk -- which has no bound.

  Not fixed, because every fix needs a number nobody can justify yet.
  A lock timeout too low breaks legitimate slow writes; too high does
  not help. The useful version is a metric -- how long writes wait --
  and that belongs with real deployment data rather than a guess.

  Striping slightly widened the blast radius here, which is the cost
  recorded when it was chosen: false contention is slow where the leak
  it replaced was fatal.

- **The request executor is never explicitly shut down.** No lifespan
  handler calls `shutdown()` on `app.state.executor`.

  ALSO INVESTIGATED AND ALSO A NON-ISSUE, measured rather than
  assumed. A `/query` handler awaits `run_in_executor`, so the ASGI
  request stays pending and uvicorn's own graceful shutdown already
  waits for it. On SIGTERM the process exits immediately -- verified
  directly, 0.0s with a 30-second task in flight -- and an in-flight
  WRITE killed that way is exactly what the write log's resume path
  exists to recover.

  Recorded rather than fixed: adding `shutdown()` would duplicate what
  uvicorn already does and change nothing observable.

- **Three uncovered blocks remain in the mirror adapter**, all
  pre-existing rather than from the filter work:
  `resolve_reverse_links_batch`'s join-table path (lines 170-187),
  `read_all_rows` (218-223), and two early returns. The adapter sits
  at 77%, up from 63% once the filter translation was tested.

  Recorded rather than fixed here because they are a different piece
  of work from the audit that found them, and because each needs a
  mirror fixture with a join table -- the existing one has none.

  The measurement that found them is worth keeping: `coverage run -m
  pytest`, then ranking PRODUCTION files by coverage rather than
  reading the top of the list. The backend is at 96% overall, which
  hides a 63% file entirely.

- **No container.** Dependencies are locked with hashes and the lint
  fails on drift, so builds are reproducible from a checkout. What is
  still missing is a reproducible RUNTIME: the OS layer and the Python
  interpreter come from whatever the host provides.

  Worth being precise, since a container is the obvious next thought:
  it freezes those two and nothing else. A Dockerfile running an
  unpinned install still produces a different image each build --
  which is why the lockfile came first and is the larger half.

  Deferred because install.sh plus the service unit already work, and
  because this needs a release process to be worth its maintenance.
  One real side benefit if it does arrive: the entrypoint becomes a
  reviewable file in this repository rather than whatever an operator
  writes, which is exactly the path require_assertions_enabled() was
  added to defend.

- **Snapshot pagination: CLOSED, and harder than the storage layer
  makes it look.** Foundry offers two consistency behaviours: their
  DEFAULT "returns the latest results" and "may lead to duplicate
  entries or missing items as data changes between page requests";
  their opt-in SNAPSHOT mode "captures data at a specific point in
  time before pagination begins". Elysium implements the default,
  which is what they ship -- not a deviation.

  The earlier note said building it means "holding a result set across
  requests with an expiry policy". That was wrong in both directions.

  It is EASIER than that on the storage side: PyIceberg's `scan()`
  already takes a `snapshot_id`, so a mirror-backed read could pin a
  point in time by passing a parameter. No session state, no expiry,
  no cleanup -- Iceberg already holds the snapshot.

  It is HARDER than that on the consistency side, which is the real
  blocker. Elysium's reads merge the write log over adapter data so a
  caller sees their own uncommitted-to-mirror writes
  (`_read_field_with_log_check`). Pinning the mirror while that
  overlay stays live produces a half-pinned view: historical for
  everything the mirror holds, current for everything the write log
  does. That is not a snapshot; it is a mixture, and one whose
  inconsistency would be invisible to the caller who asked for
  consistency.

  Resolving it means deciding what "as of T" should mean for a write
  applied after T -- excluded, which breaks read-your-writes, or
  included, which breaks the snapshot. Foundry does not face this
  because their edits are indexed INTO the same store they read from,
  so one snapshot covers both. Elysium's write log is deliberately
  separate.

  REOPEN IF a caller genuinely needs it -- an export or reconciliation
  job -- and with that question answered first, not during
  implementation. It is a semantics decision, not a plumbing one.

- **Object-backed link types: CLOSED, verified rather than asserted.**
  Foundry's third link backing lets a join carry its own properties --
  their example is a FlightManifest linking Aircraft and Flight while
  holding Pilot and First Mate. Elysium supports the other two,
  foreign key and join table.

  The claim that this is already expressible was previously an
  assertion. It has now been built: their exact example declares
  cleanly as FlightManifest as a real object type with `pilot` and
  `first_mate` as ordinary fields, plus two one_to_many link types
  (Aircraft -> FlightManifest, Flight -> FlightManifest). It
  validates, expands both directions, and the manifest's own
  properties are reachable by search_around from either side.

  Foundry's own modelling guidance agrees this is the right shape,
  not a workaround: a join table carrying extra information "is no
  longer a many-to-many relation but two separate many-to-one
  relations". Their object-backed option exists to let the Ontology
  Manager present that pair as one link in a UI, which is a
  presentation concern rather than a modelling capability.

  REOPEN IF a UI genuinely needs the pair presented as a single link
  -- at which point the work is display metadata over two existing
  links, not a third backing mechanism.

- **Function versioning is deliberately absent, with a real trigger for
  revisiting.** Foundry publishes functions with SemVer and lets
  applications depend on version ranges, because their functions live
  in separate code repositories and are consumed by independently
  deployed applications -- "Workshop, Actions, and Automate can now
  depend on functions at version ranges", and a consumer that picks up
  a breaking change is told to "pin your Function dependency to the
  last working version". That is a DISTRIBUTED DEPENDENCY problem: the
  function author and the application author are different people on
  different release cadences, and nobody can update both atomically.

  Elysium has no such problem. Functions are Python modules inside the
  deployment, shipped with it, called by an agent loop in the same
  codebase, and already versioned by git at the deployment level.
  Change a signature and you change its one caller in the same commit.
  Adding SemVer would mean maintaining metadata nothing reads.

  **REVISIT when any PERSISTED artifact references a function by
  name** -- a saved chart, dashboard, or derived column. That
  reference outlives the deployment that created it, which
  reintroduces exactly the independent-cadence problem versioning
  exists to solve. Foundry's own function-backed columns are this
  pattern, so it is a plausible piece of UI work rather than a
  hypothetical.

- **Functions cannot make ontology edits, deliberately.** Foundry
  allows it, but routes function edits through ACTIONS, so their
  validation and approval still apply. Elysium already has that path
  in propose_action(); a function editing directly would bypass
  submission criteria and the confirm step. Revisit only alongside a
  design for how a function-authored edit would be reviewed.

- **Functions cannot call external systems.** Foundry supports this
  explicitly ("querying external systems to enrich objects in the
  Ontology through external functions"). Ours cannot, and that is what
  keeps an LLM-invoked function safe: it reaches only what its
  declared object types allow, under the calling user's own
  permissions, and the model cannot widen that by choosing arguments.

  STATED PRECISELY, because "zero ambient authority" overstates it.
  The capability object holds a mediator privately -- it must, to do
  anything -- and Python privacy is a convention, so a function COULD
  reach past it. That is not the threat this defends against. A
  function is code the deployment ships, so a hostile author already
  has full execution; the property that matters is that a function
  using the capability it was given cannot exceed its caller, and that
  the LLM choosing arguments cannot widen it.

  The surface all of this rests on is now pinned by tests
  (tests/unit/test_ontology_access.py): the capability exposes exactly
  five scoped reads, never returns the mediator, and the agent loop
  passes nothing besides it. Three entries in this list depend on
  that; if it changes, they become wrong silently.

- **Incremental (APPEND) syncs: CLOSED, with the cost measured and
  the trigger named.** Elysium is SNAPSHOT-only: every sync re-copies
  each table in full. Foundry offers APPEND because "if the dataset
  grows over time, the time to sync the data as a SNAPSHOT increases",
  and a failed APPEND sync "will result in a minimal amount of
  duplicated work rather than requiring a complete re-run".

  The limit is real but distant. Measured directly:

      10,000 rows   0.24 s
      100,000 rows  0.57 s
      500,000 rows  2.46 s

  Linear, and cheap. Extrapolating, ten million rows is roughly a
  minute -- unremarkable for a cron-driven sync. It starts to matter
  somewhere around a hundred million.

  THE COST IS CORRECTNESS, NOT COMPLEXITY, which is why this is closed
  rather than queued. SNAPSHOT propagates deletes: a row removed at the
  source disappears from the mirror, asserted by
  tests/unit/test_sync_snapshot_semantics.py. APPEND cannot see a
  deleted row at all. It is correct only for append-only sources, so
  adopting it means a per-table declaration that a table never deletes
  -- and if an operator gets that declaration wrong, deletes silently
  stop propagating and the mirror drifts from the source with nothing
  detecting it.

  Trading a guarantee that holds today for speed not needed today, with
  a silent failure mode, is the wrong trade. REOPEN IF a real
  deployment has a table large enough for sync duration to matter AND
  can state truthfully that it is append-only.

- **YAML value coercion: CLOSED for mutation values.** A literal
  written into a mutation is retyped by YAML before any code here sees
  it, and afterwards is indistinguishable from a value someone meant
  that way. Now rejected when the target field declares
  `data_type: string`.

  The original note said fixing this "needs a schema-aware check that
  knows where a value is expected". It was right, and the schema now
  knows -- fields carry a declared data_type, which they did not when
  this was written.

  It was also wrong on the specifics, found by testing rather than
  reading: `1e2` is NOT coerced (it stays a string), while `yes` ->
  True and `1.20` -> 1.2 both are, and neither was listed.

  Still uncovered: a field with no declared data_type, where there is
  no expectation to violate and inventing one would reject valid
  schemas. Declaring data_type is how an author opts into the check.

- **Partial-overlap duplicate detection: CLOSED, and it must NOT be
  added.** The observation was that a `get_field` followed by a wider
  `get_object` including that field is not flagged as duplicate work.
  True, and correct.

  A detected duplicate is REJECTED, not merely noted: the step does
  not execute, the model is told it repeated itself, and enough of
  them stop the loop. So flagging a wider `get_object` as a duplicate
  of an earlier `get_field` would reject a step that returns data the
  model does not have -- the other fields -- and then stop the loop
  for persisting. A correctness bug traded for one redundant field
  read, which since the per-read security prefetch is a single query.

  The exact-subset case (`get_object` for precisely one already-
  fetched field) is genuinely missed and genuinely wasteful, but it
  requires the model to ask for a one-field `get_object` after a
  `get_field` for that same field. Narrow enough that special-casing
  it costs more clarity in `_step_signature()` than it saves in
  steps.

  The entry conflated the two cases. Only one is safe to catch, and it
  is the one that almost never happens.

- **Grant-pattern drift, and why the obvious check does not work.**
  If a new grant prefix is added at an `authorize()` call site,
  `_validate_one_grant()` needs a matching branch, and nothing ties
  the two together.

  Attempted as a source-scanning test and ABANDONED, because both
  attempts were wrong in opposite directions and the second only
  surfaced because a negative control caught the first:

  - Scanning the text syntactically inside `authorize(...)` missed
    every grant built into a variable first (`action = f"tool:{name}"`
    then `authorize(..., action)`), which made a LIVE prefix look like
    dead vocabulary. I drew conclusions from that before checking.
  - Scanning every `<word>:` literal instead caught `silo:` from
    /health's own response keys, which is not a grant at all.

  Distinguishing a grant literal from any other colon-prefixed string
  needs real parsing -- resolving the variable handed to `authorize()`
  back to its assignment. That is an AST-walking exercise, not the
  cheap lint this was filed as. A hand-maintained list of prefixes
  would be a third thing that can drift, which is the problem
  restated rather than solved.

  Worth doing properly with an AST visitor, or not at all. Shipping a
  scanner that cannot see the case it exists to catch is worse than
  having none, because it reads as coverage.

  ONE HALF OF THIS IS NOW MOOT. The drift the abandoned check found --
  `write:` accepted by the validator and used by no authorize() call --
  has been removed rather than tolerated. That prefix is now rejected
  outright, with a message naming `execute:<ActionType>` as the real
  way to permit a write.

- **Full field-VALUE validation** -- real constraints (ranges,
  patterns, enum membership), not the structural "was this field
  addressed" check. The old note deferred it as "doesn't block any of
  the four near-term sub-apps", which is true and not the useful
  framing.

  THE TRIGGER IS AN ACTION FORM. A UI rendering `TransferFunds` needs
  to know that `new_from_balance` is a number and what range is
  acceptable, or every action form is free text validated only by the
  server rejecting it afterwards. Parameters already carry a `type`
  and, since display metadata landed, a description; constraints are
  the missing third piece and belong in the same place.

  Deferred until an action form exists, because the shape of the
  constraint vocabulary should follow what a form actually needs to
  render rather than being guessed at first.

- **Interfaces / shared properties: still open, and the design
  question is the whole of it.** An interface both `Customer` and
  `Account` could `implement`, instead of declaring the same fields
  twice with no shared contract. YAML represents it fine; the loader
  work -- resolving `implements` and merging fields before validation
  -- is straightforward.

  NO SECOND NEED HAS MATERIALISED. Checked rather than assumed: across
  the fixture ontology, exactly two field names appear on more than one
  object type (`region` on two, `currency` on two), and `region` is
  there because it is the security field, not because a shared
  contract is missing. Two duplicated names in a demo schema is not
  the evidence this was waiting for.

  THE FIELD MERGE IS NOT THE FEATURE, which is the part worth
  recording. Foundry's interfaces earn their keep by being TARGETABLE:
  a link can point at an interface, so one field reaches any object
  implementing it -- a `Comment` whose `subject` is either a
  `Transaction` or an `Account`, without one field per concrete type.
  Their interfaces also carry their own display metadata, the same way
  object types do. Shipping only the merge would deliver the name
  without the capability, which is worse than not shipping it.

  POINT 16 RESHAPED THE OPEN QUESTION. When this was written, links
  were field attributes, so "can a link target an interface" was a
  question about a field's `target`. Link types are now first-class
  entities with their own source and target object types, so it is a
  question about what a `link_type` may name -- and the answer has to
  cover how `search_around` traverses to a set of concrete types
  rather than one.

  Worth real design attention when a deployment has genuinely shared
  structure. Not before, and not merged-fields-only when it happens.

- **A persistent, reviewer-based `PendingWriteStore`.** Still the one
  confirmed blocker for an Approvals inbox, and the framing needed
  correcting: today's store is in-memory, has a 15-minute TTL, and
  only the PROPOSING user can confirm their own pending write
  (`owner_user_id != requesting_user_id` returns None).

  THAT LAST ONE IS A SECURITY PROPERTY, NOT A LIMITATION TO REMOVE.
  In the current model a pending write is the continuation of one
  person's session, so refusing to let anyone else confirm it is
  correct -- it stops a second user completing a write a first user
  proposed and abandoned. An Approvals inbox deliberately INVERTS
  that: it wants a different person to confirm.

  So this is not "make the store persistent". It is designing a
  second model alongside the first, and the questions are:
  who may approve what (a reviewer grant, distinct from execute:),
  whether a proposer may approve their own write (segregation of
  duties), what expiry means when a human is expected to be slow, and
  what the audit trail records about both parties.

  The storage change is the small half. SQLite would serve it as it
  already serves the write log and credential store -- the earlier
  "on PostgreSQL" framing conflated this with the separate database
  question and is not a real dependency.

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

- **SQL/Python alignment: one pass done, worth repeating.** The
  principle is settled -- push set-based work (filtering, aggregation,
  joins, sorting) into the engine, keep business and security logic in
  Python, never push business logic into stored procedures. A pass
  over the read paths found one real violation:
  `_read_fields_for_ids()` read a whole table and discarded the rest
  in Python, so fetching three objects out of 200,004 read every one
  of them.

  What REMAINS in Python is there because it has to be, and each case
  is documented where it lives: MAC is applied per object after the
  engine returns, because a security value can chain across silos;
  aggregation groups in Python for the same reason; substring search
  and link resolution on the mirror filter after a projected scan
  because Iceberg's expression language has no IN predicate over an
  arbitrary list.

  Worth re-running when a new read path is added, since the failure
  mode is always the same shape: a bulk read plus a Python filter that
  looks harmless at fixture scale.

---

## Read-only data mirror architecture

Raised directly -- "we must be able to provide a GUARANTEE that the
outside, third-party databases are READ-ONLY" -- followed by a real,
structured research pass into how Palantir Foundry itself handles the
exact same relationship (ingestion, writeback, schema drift, staleness
visibility, and cross-source joins), and a real, careful discussion of
what to adopt at Elysium's own, much smaller scale versus what would
be disproportionate. A genuinely new, real architecture initiative --
not a small addition -- covering the entire read path (`DataMediator`).
The existing write path (`WriteMediator`, `propose_action`,
`confirm_and_execute`) is NOT left unchanged, as originally scoped --
see "External writeback" below for the real, since-settled design
covering it, developed later in the same conversation as everything
above.

### The three real roles, once the mirror and the writeback toggle both exist

Settled directly, and worth stating plainly since it resolves an
open question below: once this whole initiative is done, there are
exactly three real roles, not the two (read/write) this project has
had until now -- **external read** (the sync module, reading the
customer's live database, structurally read-only, covered by Phases
1-4 below), **internal read** (any of Elysium's own storage --
the new mirror AND the pre-existing internal SQLite databases alike
-- always gated by full RBAC/MAC), and **internal write** (the sync/
transform pipeline populating Elysium's own storage, AND
`WriteMediator`'s own confirmed actions applying to Elysium's own
internal state -- see "External writeback" below). External writes
(actually reaching the customer's real, live database) are NOT a
fourth, default role at all -- confirmed directly: "we will never be
doing external writes" as the default; they're a real, separate,
admin-toggled, off-by-default feature, covered in its own section
below, not baked into `WriteMediator`'s normal operation.

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
today. The same real mechanism, re-applied at the actual moment of an
external push (not just at original approval time), is also what
makes "external writeback: off by default" safe -- see below.

### Phases, in real dependency order

**Phase 0 -- prerequisite refactor. DONE.** `WriteMediator` now
builds its own `_adapter_mediator`, a separate `DataMediator` over
the WRITE adapters, rather than reaching into the caller's read-side
one. The original finding, kept because it is why the refactor
existed: `WriteMediator` did not have its own adapter set -- confirmed directly: it reaches into `self.mediator`'s own
adapters (`_resolve_shared_storage`, `_write_limiter_for_silo`,
`_locks_for_objects`, `_type_schema`, `_read_field_with_log_check`,
`_security_allowed`) to perform its own writes. `DataMediator` cannot
safely move to a read-only credential until `WriteMediator` has its
own, independent, still-write-capable adapters. A pure refactor --
zero behavior change, both mediators still pointing at the exact same
real database at the end of this phase, just via separate connections.
**Resolved, no longer open:** all six borrowed methods need real,
independent copies, not a partial split. Working through the three
real roles above made this unambiguous -- `WriteMediator`'s own
connection is now structurally a genuinely different thing from
whatever `DataMediator` connects to (live source today, or the mirror
after Phase 4), for every one of the six, not just some of them; the
earlier doubt came from thinking of this as one blurry read/write
line rather than clean, separate roles.

**Phase 1 -- the real, two-layer read-only guarantee (depends on
Phase 0). CODE-LEVEL HALF DONE; credential half documented, pending a
real server-backed adapter.** Two independent, structurally separate
enforcement layers, resolved directly, not left as a tradeoff:
- **Code-level: DONE.** `sqlite3.Connection.set_authorizer()`, via
  `core/sqlite_connection.py`'s own `open_connection(read_only=True)`,
  now used by `SQLiteReadAdapter`'s own `_connection()`. Confirmed
  directly, empirically, and covered by a real, dedicated test file
  (`tests/unit/test_external_read_adapter_is_read_only.py`) proving a
  raw UPDATE/DELETE/DROP issued straight through the reader's own
  connection is refused by the engine itself -- not merely absent from
  its public methods (that was Phase 0, true by type alone).
  `SQLiteWriteAdapter` overrides `_connection()` to stay genuinely
  write-capable, since it inherits the reader's four real read
  implementations for WriteMediator's own optimistic-concurrency
  check.
- **Credential-level: CLOSED as far as it can go, not pending.** A
  separate SELECT-only credential is not deferred work -- it is
  IMPOSSIBLE with the adapter that ships. SQLite has no database user
  and no GRANT; a connection is a file path. There is nothing to
  implement until a server-backed adapter exists, and the requirement
  is already recorded as deployment guidance in INSTALL.md section 9
  so it is not discovered late.

  Kept as an entry rather than removed because it becomes real the
  moment a PostgreSQL or MySQL adapter lands, and it is the enforcement
  point that matters -- the code-level authorizer below is the second
  layer, not the first.

- **Credential-level: original note.** A
  genuinely separate, `SELECT`-only database credential for
  `DataMediator`'s own adapters -- matching Palantir's own real,
  confirmed practice (their own docs: "syncs can change the source
  system if the source credentials allow it... you should only grant
  Edit access... to users whom you would also grant full access to the
  account"). The credential is the real enforcement point, not
  application code alone. Confirmed directly why this cannot be
  implemented yet rather than deferred vaguely: SQLite has no concept
  of a database user or GRANT at all -- a "connection" is just a file
  path -- and Elysium currently ships a SQLite adapter only. Recorded
  as real, actionable deployment guidance in `INSTALL.md`'s own
  "Data-access security" section so the requirement isn't discovered
  late; becomes directly implementable the moment a real server-backed
  adapter (PostgreSQL or similar) exists.

**Phase 2 -- raw ingest sync module. DONE.** The stated dependency on
"Phase 1's read-only credential existing" did not hold and was never
satisfied: that credential is impossible with the SQLite adapter (no
database user, no GRANT) and is closed on those grounds, yet the sync
module shipped and works. The real dependency was Phase 1's CODE-level
read-only guarantee, which does exist -- the engine-level authorizer
on the reader's own connection. The credential is a second,
independent layer, not a prerequisite for reading. PyIceberg (confirmed directly: Apache License
2.0, from `apache/iceberg-python`'s own `pyproject.toml`) manages the
mirror's own versioned storage; a new `core/mirror/` package
(`interface.py` then a concrete `iceberg_sync.py`, matching the
established `DataSiloAdapter` interface-then-implementation
convention) reads through the Phase 1 credential and writes one raw
Iceberg table per real source table -- matching Foundry's own "ingest
as-is" philosophy.

**Process shape -- SETTLED: a separate CLI process, not an in-process
background thread.** A new `scripts/run_sync.py` performs ONE sync and
exits; scheduling is external (cron, systemd timer, Kubernetes
CronJob). Three real reasons, decided directly rather than by default:
it matches how this project already works (`scripts/run_deployment.py`
and `scripts/serve_requests.py` are already standalone entry points
sharing the same `core/`); a sync copies entire tables, which is
genuinely heavy work that would otherwise compete with request
handling in the same process (and, under Python's GIL, measurably slow
it), while a badly-failing sync in-process could take the web server
down with it -- separate processes fail independently; and it matches
the real precedent already researched, since Foundry itself runs syncs
as scheduled builds, entirely separate from the service answering
queries. The honest cost, named rather than glossed: it is a second
thing to deploy and schedule, which for a single-machine deployment is
genuinely more setup than "it just happens."

Sync cadence: a real, configurable deployment
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

**Phase 3 -- the transform pass. Deferred after examining the real
code, then REOPENED on a different justification after checking
Foundry's own architecture properly.**
The original plan: materialize one clean, per-object-type Iceberg
table (`customer_clean`, etc.), reusing `DataMediator`'s own
field/MDO resolution via an extracted shared function.

Two separate conclusions, and they did not survive equally. The
shared-function extraction was correctly abandoned and stays
abandoned. The DEFERRAL OF THE PHASE ITSELF was wrong, and is
reversed below -- the reasoning rested entirely on join performance,
which is not why a transform stage exists.

**Why the shared-function extraction was abandoned.** `get_field()`
is not a resolution function with access control bolted on -- it is
genuinely INTERLEAVED: RBAC/MAC checks, per-user audit logging of
unknown references (running deliberately INDEPENDENTLY of the access
check, fixing a real ordering bug documented in its own comments), a
write-log check that serves a reader the INTENDED value mid-update,
reverse-link dispatch to a DIFFERENT type's adapter, and MDO storage
resolution. A batch transform needs almost none of that: no user, so
no RBAC/MAC and no per-user audit trail; no write-log consultation
(the mirror should reflect the SOURCE, not one user's pending edit);
and whole-table processing rather than one field for one object.
Extracting a shared function would mean pulling apart logic
interleaved for real reasons, then adding parameters to switch off
the parts batch mode doesn't want -- the kind of DRY that makes both
callers harder to understand, which is the opposite of what this
project's own DRY principle is for.

**Why the phase was deferred -- and why that reasoning was WRONG.**
The deferral argued: Phase 3 pre-computes an MDO join; what makes MDO
expensive today is crossing separate databases; the mirror already
eliminates that, so the join becomes ordinary local work; therefore
the phase solves an unconfirmed performance problem.

Every step of that is about JOIN PERFORMANCE, and that was the
mistake. Checked against Foundry's own documented architecture rather
than assumed, a transform stage exists for reasons that have nothing
to do with join cost:

- **Type casting.** Foundry's own build guidance says to "explicitly
  cast the column types in the raw -> clean transform, even if the
  schema inference from the data connection has chosen correct
  values," specifically because it "will help catch breaking changes
  from the source system if a column type changes or an invalid value
  creates an incorrect inference during the sync." That is drift
  DETECTION, not speed.
- **Ingest stays dumb on purpose.** Their Data Connection layer
  "deliberately offer[s] minimal options for transforming the data
  before it arrives in the destination dataset (the starting point of
  the Foundry pipeline)" -- the raw dataset is the pipeline's START,
  not its end.
- **The clean -> ontology step is recommended unconditionally.** Their
  own words: clean datasets "typically resemble raw data closely and
  as such may contain many more columns than we need for our Ontology
  object and link types," and "this intermediate transform step
  (clean -> ontology) is always recommended, even in cases where it
  initially feels like a formality."

So the real shape is raw -> clean -> ontology, and Elysium currently
has only the first stage. There is already a concrete symptom: the
`data_type` mechanism added in Phase 4 does type-casting work INSIDE
core/mirror/iceberg_sync.py, which is exactly the "raw -> clean"
responsibility bolted onto the ingest stage. It works, but it is in
the wrong place, and the sync is meant to stay as dumb as Foundry's.

**REOPENED as a real transform stage, not a materialization.** The
justification is drift detection, explicit typing, and column pruning
-- not pre-computing joins. MDO itself stays exactly as it is: checked
directly against Foundry, MDOs remain a first-class concept there even
though every Foundry datasource is already internal, because the
concept is about column-level access control and provenance, not about
crossing database boundaries. Our mirror already preserves that (one
Iceberg namespace per silo), so there is nothing to rename or unwind.

**Phase 4 -- repointing `DataMediator`'s actual reads. DONE.** A
`MirrorReadAdapter` is a registered adapter satisfying the same
`ExternalReadAdapter` contract, selected per silo in deployment
config, so a deployment reads from the mirror by configuration rather
than by a code path. Read-your-writes is layered over it. **Phase 4 -- repointing `DataMediator`'s actual reads. THE ADAPTER AND
CONFIG FLAG ARE DONE; a real blocker found before it can be the
default.** Implemented as `core/mirror/mirror_adapter.py` -- a real
`MirrorReadAdapter` satisfying the same four-method
`ExternalReadAdapter` contract, plus a `mirror.read_from_mirror`
config flag (False by default). The cutover turned out to be
genuinely just "which adapters does `DataMediator` hold": confirmed
directly by reading the code first, every read resolves its adapter
through `_adapter_for()` or `_resolve_shared_storage()`, so
`search_object()`, `get_field()`, MDO resolution and reverse links all
work unchanged, with no branch threaded through any read path. Verified
live: a real server with the flag on serves real reads from the mirror
while writes still go live to the real database and succeed.

**THE BLOCKER, found by the side-by-side verification rather than in
production: type fidelity.** `core/mirror/iceberg_sync.py` deliberately
stores every column as a string (see its own docstring: inferring types
per-sync would let a table's mirror schema CHANGE between runs purely
because its data changed). The real, measured consequence, confirmed
against a running server: reading `Account.balance` returns `900.0`
(float) live but `'500.0'` (string) from the mirror. That is not a
cosmetic difference -- any caller doing arithmetic, comparison or
formatting on a numeric field gets different behavior depending on a
config flag, which is exactly the kind of silent divergence this
project's own discipline rejects.

**RESOLVED, via ontology-declared field types.** The fix as first
proposed did not survive contact with the schema: the ontology declared
only `type: data` or `type: link` -- a STRUCTURAL distinction, never a
data-type one -- so there was nothing to derive Arrow types from.
Closing the gap properly meant adding real type declarations to the
ontology itself (`data_type: number`, see core/ontology/field_types.py),
validated at load time, and having the sync build a genuinely typed
Arrow schema from them. Confirmed fixed by the same measurement that
found it: `Account.balance` now reads as `500.0` (float) from BOTH the
live and mirror paths. Genuinely optional and defaulting to string, so
every schema predating it stays valid and behaves exactly as before.

The alternative -- reading types from the source database at sync time
(SQLite's own PRAGMA table_info) -- was rejected deliberately: it makes
the mirror's own shape depend on the source's, and it rests on
something untrue, since SQLite's declared column types are advisory
rather than enforced. The ontology is this project's semantic source of
truth, and "what type is this field" is a semantic question.

**A SECOND type bug, found later by exercising the FULL stack rather
than individual pieces.** Reverse links (`Customer.transactions`)
returned `[1, 2]` live but `['1', '2']` from the mirror. The cause:
an object type's `id_field` is NOT an entry under `fields` at all (a
separate, top-level key -- see core/ontology/schema.py's own
get_column_for_field() docstring), so the field-walking `data_type`
mechanism never saw id columns. It mattered more than an ordinary
field because reverse links return LISTS OF IDS. Fixed by declaring
`id_type` on the STORAGE block, beside the `id_column` it describes --
following this project's own settled position that identity is a
property of storage, never MDO-overridden, and giving each
`additional_storage` its own (Customer is keyed by `customer_id` in
primary but `cust_ref` in `risk_db`). Worth noting honestly: the
earlier side-by-side verification could not have caught this, because
its own fixtures used string ids.

The 17 tests in `tests/unit/test_mirror_read_adapter.py` are written
as side-by-side comparisons against the real `SQLiteReadAdapter` on the
same data, deliberately -- asserting against hardcoded expectations
would prove only that the mirror adapter does something; comparing
against the live adapter proves it does the SAME thing, which is the
only property that makes a cutover safe. That is also what surfaced
the type issue above.

A real,
explicit config flag -- live source, or local mirror -- never an
unconditional, all-or-nothing cutover with no way back. The most
extensive testing pass of the whole project: every existing read route
(`search_object`, `get_field`, everything the LLM touches) must behave
identically under both modes, verified with a real, live, side-by-side
comparison before this is ever the default.

**Phase 4's own read-your-writes requirement -- researched directly,
and a real correction to an earlier, worse proposal.** Once reads come
from the mirror, a confirmed write would otherwise not be visible
until the next scheduled sync: a person approves a change and then
doesn't see it. An earlier proposal here -- have the sync do a
targeted re-sync of the affected rows immediately after a confirmed
write -- was investigated against Foundry's own real behavior and
abandoned as the wrong shape.

Foundry solves this with THREE layers, not two (confirmed directly
from their own documentation, not assumed): the source datasets; a
LIVE INDEX that serves queries and receives edits immediately; and a
persistent writeback/materialized dataset that catches up on a
schedule. Their own docs are explicit about both halves -- when an
Action is applied, "the data-modification logic is immediately applied
to the index in the object databases," and "if an object read
occurring as part of an ontology query happens after a user
modification is sent, the object read is guaranteed to contain the
user edits" -- while the persistent copy lags deliberately, written
"into the writeback dataset when it is built," with automatic
propagation running at "a latency of a few minutes." The live index is
explicitly ephemeral and rebuildable ("all indexed data in object
databases are considered ephemeral, requiring persistent storing of
all Ontology data in other ways"), never the source of truth.

**That earlier claim -- that `WriteLog`'s existing masking already
solved this -- turned out to be WRONG, and testing is what caught it.**
`get_pending_changes()` masks writes that are still IN FLIGHT; once
`confirm_and_execute()` succeeds the entry is marked applied and the
pending list is empty, so there is nothing left to mask. Measured
directly: after a confirmed write of 900, a mirror read still returned
500. Foundry's live index and this project's write log are not the
same kind of thing -- theirs is a durable serving layer edits are
applied INTO, ours was transient protection for an in-progress write.

**DONE, via a separate, additive overlay.** `WriteLogReader` gained
`get_applied_changes_since()` / `get_all_applied_changes_since()` --
deliberately separate methods rather than a flag on the existing ones,
since the two answer genuinely different questions and crash recovery
(`get_pending_batches()`) depends on the existing meaning exactly as
it is. `DataMediator` consults the overlay after the in-flight check,
bounded by the mirror's own last-sync timestamp, so each sync narrows
it and a live deployment (timestamp None) disables it entirely.
Verified end to end: a confirmed write is immediately visible from the
mirror, and a re-sync empties the overlay, with the value then coming
from the mirror itself. The mirror stays sync-written, sole writer the
sync -- anything else creates two sources of truth for the same fact,
which the next sync would then overwrite.

**A real constraint on the DuckDB side, verified rather than
recalled.** DuckDB genuinely CAN write to Iceberg -- full read support
and initial write support shipped in v1.4.0, with delete and update
added in v1.4.2, correcting an earlier, stale assumption that it was
read-only. But their own docs draw a sharp line that matters here:
individual tables read directly from storage "require no catalog and
are read-only," while writing requires attaching an Iceberg REST
catalog (Polaris, Lakekeeper, S3 Tables). This project deliberately
chose a SQLite catalog specifically to avoid running a separate
catalog SERVICE, so DuckDB writes are not available without adopting
exactly the infrastructure already ruled out as disproportionate. The
practical division therefore stands -- PyIceberg writes, DuckDB reads
-- but for this real reason, not because DuckDB lacks the capability.

**RE-CONFIRMED after building the analytical layer, on far better
evidence than the first decision had.** Point 8 of the machinery audit
revisited this once Points 6 and 7 existed -- real aggregation
primitives and Search Around -- so that the question could be measured
against genuine analytical queries rather than a substring search.

Profiling `aggregate_by_field()` over 20,000 objects: 6.25s total, of
which 6.10s is `check_access()`. **98% of an analytical query is MAC,
not the query engine.** Split another way: 4.47s resolving row-level
security, 0.05s reading and grouping the data. An engine that made the
data half INFINITELY FAST would save 1%.

That is the real finding, and it is not about DuckDB's merits. MAC
cannot move into any query engine, because a security value is reached
by following `security.via_field` chains that cross silos -- the
reason this layer is a service rather than exposed SQL, and the same
reason Foundry built OSS rather than a SQL endpoint. So the bottleneck
is structurally outside the engine's reach.

**The genuinely useful optimization is batching MAC resolution**, now
recorded in the deferred list above. That is worth real work; a second
query engine is not, until it is measured against a workload where the
data half actually dominates.

**DECIDED: DuckDB is NOT adopted, and the "DuckDB reads" half of that
division is dropped.** Point 4 of the machinery audit went looking for
what DuckDB would actually do, and found nothing it needs to. All five
methods MirrorReadAdapter implements are already served by PyIceberg
with real predicate pushdown and column projection. The one genuinely
Python-side operation is substring search, which Iceberg's expression
language cannot express -- so it was measured rather than assumed.

Measured properly (both paths warmed, best of three, same Arrow table):
100,000 rows searched across two columns takes 16ms in Python and 12ms
in DuckDB. At 1,000 and 10,000 rows Python is FASTER, because DuckDB's
per-query overhead dominates. A first, careless measurement suggested a
9x DuckDB win; that was a cold DuckDB against an unwarmed Python path,
with the Arrow-to-Python conversion counted on one side only, and it is
recorded here because it is exactly the kind of number that would
otherwise have justified a dependency on its own.

A 4ms difference at 100,000 rows does not justify a new dependency, a
second query engine, two ways to express every read, or the
Arrow-to-DuckDB registration on every call. If substring search ever
becomes a real bottleneck against real data, the honest first move is
an index or a search-specific column, not a second engine. Revisit with
measurements, not by default.

### External writeback: off by default, real precedent, stricter than Foundry's own model

A real, separate design track from Phases 1-4 above (only depends on
Phase 0's adapter separation, not on the mirror itself existing) --
"we can retain writing to external databases, but this should be off
by default. It is a feature that should have to be toggled by an
admin, and never ship pre-configured. We'll follow Foundry's
precedent."

**What "off" actually means.** A confirmed action applies to
Elysium's OWN internal state immediately, regardless of the toggle --
this was a real, resolved ambiguity, not assumed: Foundry itself has
two real Webhook modes ("side effect" -- internal change applies
immediately, external push is best-effort and asynchronous afterward;
"writeback" -- external push happens FIRST, internal change is gated
on its success), and Foundry's own DEFAULT is "side effect," not
"writeback." Elysium matches that default specifically: with external
writes off, nothing about `confirm_and_execute()`'s own, existing
internal-apply behavior changes at all -- what's OFF is only the
separate, additional push to the customer's real system.

**The Outbox Pattern -- a real, named, well-established mechanism,
not an invented one.** Confirmed directly via real, established
distributed-systems precedent (the Transactional Outbox Pattern):
every confirmed action, in addition to applying internally, also gets
a row in a new, dedicated outbox table -- explicitly NOT merged into
`write_log.db`, which stays pure audit history; the outbox is "what
still needs pushing externally," a genuinely different responsibility.
A background relay process drains this table -- but only runs at all
once external writes are enabled.

**When external writes ARE enabled -- the stricter "writeback" mode,
as requested.** For each outbox item, at the ACTUAL moment the relay
attempts to push it (not when it was originally approved), the
SAME, already-existing optimistic-concurrency check
(`confirm_and_execute()`'s own real, current-value comparison) runs
again, against the customer's real, live, CURRENT value, right before
the push. Only if that still matches does the real, external write
proceed. This is deliberately stricter than a naive "just replay
everything in the backlog" -- confirmed directly why that naive
version would be unsafe: Elysium is not necessarily the only writer to
the customer's real database (the same real fact that motivates the
existing optimistic-concurrency check in the first place), so an
item queued for hours or days could easily be stale relative to a
REAL, independent, external change that happened in the meantime; a
blind replay would silently clobber it. Re-validating at actual push
time, not at original approval time, is the real fix -- and is
already a genuine, confirmed improvement over Foundry's own model,
which evaluates its own "writeback" webhook synchronously, only once,
at the moment an action is approved, with no equivalent later re-check
for anything that had to wait.

**Resuming a backlog, once external writes are turned on -- a real,
established distributed-systems idiom, not a bespoke design.**
Confirmed directly against the Outbox Pattern's own established
practice: neither "flush everything at once" nor "only affects items
from now on" -- the standard, correct behavior is a continuous,
ORDERED drain, oldest item first, that simply resumes exactly where
it left off the moment the relay is enabled (whether for the first
time, or after being off for a while). Each item's own real push is
independently subject to the re-validation above -- one item failing
its own, real, current-value check gets flagged for a human to review
again (the same, already-existing rejection path), not blocked on the
whole backlog, and not silently skipped either. Retries on a genuine,
transient failure (the customer's own system briefly unreachable) use
real, established exponential backoff with jitter, matching the
Outbox Pattern's own standard practice -- not a tight, immediate retry
loop. The actual push logic itself needs to be genuinely idempotent
(safely re-sendable without double-applying), matching the pattern's
own real, standard "at-least-once delivery" semantics.

**A real, separate, narrow permission for observing the outbox
itself.** Raised directly -- "an external read data flow should only
ever pipe into Elysium with nobody gaining permission to see the flow
coming in, perhaps with the exception of a privilege to see that data
flow." The sync/outbox processes themselves are internal
infrastructure, not business data -- they should never be visible
through the normal, business-data RBAC/MAC paths at all. A new, real,
narrow permission (something like `observe:sync`) lets an admin
specifically opt into watching sync/outbox health -- a genuinely
different KIND of grant than `read:Customer.name`, since it's about
infrastructure visibility, not data access. Not yet designed in
detail -- worth its own, real design pass once Phase 0 and the outbox
table itself exist.

### The real, settled tool choices, and why

**DuckDB -- considered and REJECTED.** It was listed here as the
mirror's read-time query engine before anything needed one. Point 4 of
the machinery audit checked what it would actually do and found
PyIceberg already serves every read the mirror performs, with real
predicate pushdown and column projection. The one operation Iceberg
cannot express is substring search, and measured properly that is
16ms in Python versus 12ms in DuckDB over 100,000 rows -- with Python
FASTER at smaller sizes, where DuckDB's per-query overhead dominates.
Not adopted; see the decision under Phase 4 above for the full
measurements, including a careless first result that would have
justified it wrongly.

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

### What this actually adds, once everything above is done

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
8. A real, admin-toggleable, off-by-default path for Elysium to
   actually push an approved change out to the customer's real,
   external system -- something Elysium could not do at all before
   this initiative -- with its own, real safety property re-validating
   each item against the customer's live, current data at the actual
   moment of push, not just at original approval time (a genuine
   improvement over Foundry's own equivalent mechanism, which only
   ever checks once, synchronously, at approval). With external writes
   left off (the required default), `confirm_and_execute()`'s own
   internal-apply behavior is completely unchanged from today.

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

- **`TrustedHostMiddleware` / `Host` header validation. CLOSED, not
  deferred.** Re-examined rather than left open, and both original
  premises still hold, one more strongly than recorded.

  The `Host` header is still never used to construct any output --
  no redirects, no links, nothing built from it. The only use of
  `request.url` anywhere is the CSRF middleware reading a PATH.
  Host-header injection exploits apps that reflect that header;
  this one does not have such a path to exploit.

  And the deployment does not merely *tend* to sit behind a proxy:
  install/elysium.service binds uvicorn to `127.0.0.1`, so it cannot
  be reached without one. The original note said "typically deployed
  behind a reverse proxy"; the shipped unit makes that structural.

  Implementing it anyway would mean a new `allowed_hosts` option that
  no deployment sets, defaulting to permit everything -- middleware
  that looks like a control and enforces nothing. That is worse than
  its absence, because it invites the belief that the concern is
  handled.

  REOPEN IF the service unit is changed to bind a public interface,
  since that is the single change that makes the header reachable.