# HOT_RELOAD_PLAN.md

Migrating the backend from fixed-at-boot to reloadable-while-running.

Written before anyone starts building, like OBJECT_EXPLORER_PLAN.md and
UI_ROADMAP.md's Vertex-lite record. The mechanism IS the design here;
the features that need it are comparatively simple once it exists.

**THE PROBLEM, stated once.** Elysium reads `policy.yaml`,
`ontology_schema.yaml`, `data_silos.yaml` and `config.yaml` once at
startup and never again. A deployment that gains an object type, moves
a silo, adds a role, revokes a user or changes an action must be
restarted. Restarting drops every session, every in-flight query and
every pending write.

**WHY NOW, and not as general hygiene.** The approvals inbox is the
first feature that makes a write LONG-LIVED. Everything in Elysium
today lives and dies inside one request, so a snapshot taken at request
start is indistinguishable from a live read. A pending write awaiting a
human is the first object whose validity spans a configuration change,
and building an inbox on a fixed-at-boot backend means building it
twice.

---

## What Palantir actually does

Researched directly. Six mechanisms, separable, and Elysium has none of
them.

**1. Evaluate at every point of access, never snapshot.** Their access
control documentation is explicit: "The control evaluates against the
running user's identity at every point of access."

**2. Version is a PARAMETER OF EACH REQUEST, not a global the server
swaps.** This is the most important finding and the least obvious.
Every Ontology API call carries an `ontology` identifier, and
optionally a `branch`, an `sdkPackageRid`, an `sdkVersion`, and -- in
preview -- an `OntologyTransactionId`. The server does not have "the
current ontology"; a caller names which one it is operating against,
and several can be served concurrently.

**3. Consistency semantics are documented per backend, not assumed.**
"Changes to objects or links stored in Object Storage V1 are eventually
consistent and may take some time to be visible. Edits to objects or
links in Object Storage V2 will be visible immediately after the action
completes." They publish the difference rather than papering over it.

**4. Propagation speed differs BY KIND OF CHANGE, and they say so.**
Object and property security policy changes "take effect almost
immediately", while "changes in Multipass such as group membership or
other user attributes are still cached for a short period of time."
Policy definitions propagate fast; identity lags. Notably, the older
restricted-view mechanism "require[d] a pipeline rebuild before reads
respect the new policies" -- Foundry has already made this exact
migration, and near-instantaneous policy updates is the first benefit
they list for having done it.

**5. Additive and destructive changes take different paths.** "Adding
new columns does not require a replay. However, removing columns from
an output schema is a state break that requires a replay." For the
ontology, "by default, Phonograph does not automatically accept schema
changes" -- destructive ones stop and demand a human. Additive changes
flow.

**6. A readiness gate, not an atomic swap.** Schema updates run through
a SEPARATE pipeline from data updates, and a changed object type is not
queryable until hydration completes: "Once these steps are completed,
the object type is ready for use and can be queried." New definitions
do not serve traffic until they are provably ready. Drift is also
actively watched -- a schema check warns "if columns are added or
removed, or column names and types that your pipeline relies on change
unexpectedly."

---

## What Elysium has today

`api/app.py` builds thirteen things at startup and hangs them on
`app.state`:

    artifact_store        credential_store      credentials_db_path
    config                executor              login_attempt_tracker
    loop                  mediator              pending_writes
    query_rate_limiter    session_store         synthesis_client
    user_directory        write_mediator

**THE CENTRAL INSIGHT OF THIS PLAN: those thirteen are two categories,
and a reload must treat them OPPOSITELY.**

**Configuration-derived -- must be REBUILT on reload:**

    config           DeploymentConfig: schema, users, roles,
                     silo_configs, security_attribute, model names
    mediator         holds the schema and the read adapters
    write_mediator   holds the mediator, roles, action_types
    loop             AgentLoop: holds hop limits and the step client
    synthesis_client model name and connection

**Runtime state -- must SURVIVE reload:**

    session_store            live logins
    credential_store         the user database
    user_directory           the user database
    login_attempt_tracker    lockout counters
    query_rate_limiter       rate windows
    pending_writes           IN-FLIGHT APPROVALS
    artifact_store           saved user content
    executor                 the thread pool

Rebuild the second group and every user is logged out, every lockout
counter resets (a real security regression -- an attacker could clear
their own rate limit by triggering a reload), and every pending write
vanishes. Preserve the first group and nothing has changed.

**A SECOND PROBLEM, invisible until you look at the access pattern.**
Routes read `request.app.state.mediator` and `request.app.state.config`
as SEPARATE attributes. A reload that swaps them one at a time creates
a window in which one request sees a new mediator and an old config --
a torn read, where the schema and the grants disagree. With
authorization derived from `config.roles` and data shape from
`mediator.schema`, a torn read is an authorization bug, not a
cosmetic one.

This is why the design below is an immutable BUNDLE swapped atomically,
rather than thirteen mutable attributes.

---

## The design

### One immutable bundle, one atomic swap, one pin per request

    @dataclass(frozen=True)
    class DeploymentGeneration:
        generation: int          # monotonic, starts at 1
        loaded_at: datetime
        source_digest: str       # sha256 over the four config files
        config: DeploymentConfig
        mediator: DataMediator
        write_mediator: WriteMediator
        loop: AgentLoop
        synthesis_client: LLMAdapter

`app.state.generation` holds ONE reference to this. A reload builds a
complete new instance and rebinds that single name -- an atomic
operation in CPython, requiring no lock on the read path.

**Every request pins the generation once, at entry, and uses that one
object throughout.** This is the same discipline `RequestContext`
already applies to request-scoped values, and it gives the two
properties that matter:

- **Internally consistent**: a request never sees a torn read, because
  schema, roles and adapters all come from one immutable object.
- **Fresh between requests**: the next request gets the new
  generation. Bounded staleness, exactly Foundry's model.

### Generation is stamped on everything durable

Following Palantir's "version is a parameter of the request" rather
than a hidden global:

- Every audit entry records the generation it was written under.
- Every `PendingWrite` records the generation it was PROPOSED under.
- `RequestContext` carries it, so it reaches the audit log through
  machinery that already exists.

This alone answers questions currently unanswerable: was this write
proposed under the current policy? Did the grants change between
proposal and approval? It is also the prerequisite for every later
stage, which is why it ships first and alone.

### Validate before swapping -- the hydration gate

A reload that fails validation MUST leave the running generation in
place. Elysium already has the validators: `load_deployment()`,
`validate_action_types()`, `validate_action_type_criteria()`,
`validate_policy()`. The reload path builds and validates a complete
new generation, and only rebinds on success.

This makes a broken YAML edit a NO-OP with an error, rather than an
outage. Today it would be an outage, because the only way to load new
config is to restart.

### Additive versus destructive

Copying Foundry's asymmetry rather than treating all changes alike. On
building a new generation, diff it against the current one:

- **Additive** (new object type, new field, new action, new role, new
  grant): swap freely.
- **Destructive** (field removed, type changed, object type removed,
  grant revoked, silo repointed): swap, but MARK AFFECTED PENDING
  WRITES unapplyable with a specific reason. A pending write
  referencing a field that no longer exists cannot be approved, and
  discovering that at apply time is worse than at reload time.

Note the asymmetry is about EXISTING OBLIGATIONS, not about safety of
the swap itself. Revoking a grant should take effect immediately; what
must not happen is a pending write silently applying under it.

---

## Staged migration

Each stage is independently shippable, independently valuable, and
leaves the system green. No stage requires the next.

### Stage 0 -- make staleness visible. No behaviour change.

Add `generation`, `loaded_at` and `source_digest` to the loaded bundle.
Stamp them on audit entries, `RequestContext`, and `PendingWrite`.
Nothing reloads.

Valuable alone: the audit log gains "which configuration was in force",
which is a real gap today. Cheap, and every later stage depends on it.

### Stage 1 -- collapse the thirteen into a bundle, pin per request.

Introduce `DeploymentGeneration`. Move the five configuration-derived
objects into it; leave the eight runtime-state objects where they are.
Routes read `request.state.generation` (pinned once by a dependency)
rather than five separate `app.state` attributes.

Still no reload. This is the refactor that makes one possible, and it
removes the torn-read class of bug by construction.

Cost: touches every route. Mechanical, and mypy finds all of it.

### Stage 2 -- the reload path, admin-triggered.

Build a new generation from disk, validate fully, rebind on success,
return the new generation number or the validation error. Old
generations are garbage-collected when the last request pinning them
finishes -- Python's refcounting handles this without a scheme.

**Trigger: an authenticated admin endpoint, plus SIGHUP.** NOT
file-watching -- a half-saved YAML would trigger a reload mid-write,
and the failure would be a partial read that happens to parse.

### Stage 3 -- narrow the evaluation window.

Re-resolve `UserRecord` per hop rather than per request, closing the
disable/role-change window already recorded in ROADMAP.md's security
backlog. Recompute `visible_schema` only when the generation moved,
since recomputing per hop also changes the prompt mid-query and
interacts with prefix caching.

### Stage 4 -- the silo layer.

The piece researched least and genuinely separate. Adapters hold
connections; a reload that repoints a silo must retire old connections
without killing in-flight reads. Source schema drift -- a column
disappearing from the underlying table -- is detectable at reload and
should WARN rather than fail, copying Foundry's schema-check posture.

### Stage 5 -- destructive-change handling for pending writes.

Only meaningful once the approvals inbox exists and writes are
long-lived. Deferred deliberately.

---

## Open questions

**Does a reload invalidate sessions?** A user whose role changed still
holds a session token that says what it said. Foundry caches identity
briefly and accepts the staleness. Re-resolving `UserRecord` per
request against `credentials.db` (which is runtime state, not config)
already handles role changes -- so this may be a non-issue, but it has
not been traced.

**What happens to an in-flight agent loop across a reload?** It pinned
generation N at entry and will finish under it, which is correct and
consistent. But a query taking minutes on CPU-only hardware could
finish under a configuration that no longer exists. The audit record
will say so, which may be enough.

**`DeploymentConfig` is NOT frozen -- checked, not assumed.** It is a
plain `@dataclass`, and it holds mutable dicts: `schema`, `users`,
`roles`, `silo_configs`. Nothing mutates them today, but nothing
prevents it, and a generation shared across threads must be genuinely
immutable or the atomic-swap guarantee is decorative. `frozen=True`
prevents rebinding the FIELDS; it does not freeze the dicts inside
them. Stage 1 should decide between deep-freezing on load (e.g.
`MappingProxyType`) and an import-linter-style rule -- the first is
enforced, the second is aspirational, and this project has said which
it prefers.

**No cross-request memoisation exists -- checked.** A grep for
`lru_cache`, `@cache` and memo patterns across `core/` and `api/`
returns nothing but unrelated prose. `visible_schema` is computed per
query from the mediator's schema, so a swapped generation is picked up
with no cache to invalidate. Recorded because it is the assumption most
likely to be quietly broken by a future performance fix -- an
`@lru_cache` keyed on `user_id` would survive a reload and serve stale
authorization.

**Should generations be addressable rather than just current?**
Foundry lets a caller name a branch or SDK version. Elysium almost
certainly does not need this -- but the audit log recording generation
numbers is worthless if nobody can ask what generation 7 contained.
Keeping the source digest, or the parsed config, per generation may be
worth it.

---

## The migration roadmap

Numbered steps, lettered substeps. **Each lettered substep is one
commit** and must leave the tree green -- `./lint.sh` clean and the full
suite passing -- on its own. Nothing here is a big-bang cutover.

**READ THIS FIRST.** Three ordering rules, each of which turns a safe
migration into an unsafe one if broken:

- **No reload capability exists until step 3.** Steps 1 and 2 change
  structure only. Anything that can rebind configuration before the
  bundle is immutable and pinned per request is a torn-read bug
  shipped deliberately.
- **Runtime state is never rebuilt.** The eight preserve-category
  objects above stay on `app.state` untouched through every step. If a
  substep would move one into the generation, it is wrong -- rebuilding
  `login_attempt_tracker` on reload lets an attacker clear their own
  lockout by triggering one.
- **Validation gates the swap, never follows it.** A generation that
  fails to build must leave the running one in place, in every path,
  including the signal handler.

### 1. Generation identity -- no behaviour change, nothing reloads

Ships value alone: the audit log currently cannot say which
configuration was in force for any entry.

  1a. Add `generation: int`, `loaded_at: datetime` and
      `source_digest: str` to what `load_deployment()` returns. Digest
      is a sha256 over the four config files' bytes, sorted by name, so
      two loads of identical files are identical. Generation starts at
      1 and is assigned by the loader, not by the caller.
  1b. Carry them on `RequestContext`, whose docstring already says
      fields are added there rather than passed alongside.
  1c. Stamp the generation on every audit entry, through
      `RequestContext`, which already reaches the audit log.
  1d. Stamp `proposed_under_generation` on `PendingWrite`, beside the
      provenance fields already there. Required, no default, for the
      same reason `origin` is: a default would be a guess written into
      an audit trail.
  1e. Tests: two loads of unchanged files produce the same digest; a
      changed file produces a different one; the generation reaches
      the audit log and a pending write. Control: break the digest
      input and confirm the tests fail.

### 2. Immutability and the bundle -- still nothing reloads

  2a. Make `DeploymentConfig` genuinely immutable. `frozen=True` alone
      is NOT sufficient -- it prevents rebinding fields, not mutating
      the `schema`, `users`, `roles` and `silo_configs` dicts inside
      them. Decide between deep-freezing on load and a convention;
      this project prefers enforced over aspirational, and the
      enforced option is a recursive `MappingProxyType` wrap at load.
      Its own commit, because it may surface code that mutates config
      today and nobody knows about.
  2b. Introduce `DeploymentGeneration`, frozen, holding the five
      configuration-derived objects and the three identity fields from
      1a. Build it in `load_deployment_bundle()`. Do not wire it in
      yet.
  2c. Add a FastAPI dependency that pins `app.state.generation` once
      and puts it on `request.state`. One read, at entry.
  2d. Migrate routes to the pinned generation, in batches small enough
      to review. mypy finds every site. Behaviour is identical
      throughout, because there is still exactly one generation.
  2e. Delete the now-unused `app.state.config`, `.mediator`,
      `.write_mediator`, `.loop`, `.synthesis_client`. **Deleting them
      is the point** -- while they exist, a future route can reach past
      the pin and reintroduce the torn read.
  2f. Test that a request cannot observe a torn read: with two
      generations constructed, assert that schema and roles seen
      within one request always come from the same generation.
      Control: read one from `app.state` and one from the pin, and
      confirm the test catches it.

### 3. The reload path

  3a. `build_generation(paths) -> DeploymentGeneration` -- loads,
      validates fully, and returns a complete new generation or
      raises. Pure: touches no global state, so it is testable without
      a server and cannot half-apply.

      **It must run every validator `load_deployment()` already runs**,
      which is six, not the three I first wrote from memory:
      `validate_object_types`, `validate_link_types`,
      `validate_action_types`, `validate_action_type_criteria`,
      `validate_roles` (policy_validation.py -- there is no
      `validate_policy`), `validate_function_declarations`, plus
      `validate_identifier_types` and the lockfile check. The right
      implementation REUSES `load_deployment()` rather than
      re-listing them, precisely so this list cannot drift -- a
      reload that validates less than a boot would be a hole that
      only opens under reload.
  3b. The rebind: on success, `app.state.generation = new`. One
      statement, atomic in CPython, and NO LOCK ON THE READ PATH -- a
      lock there would serialise every request to buy what a single
      atomic reference read already gives. This is read-copy-update,
      and it only works because step 2a made the shared object
      genuinely immutable.

      **CORRECTION to an earlier version of this step**, which said
      refcounting frees old generations and "no scheme is needed".
      That is true of MEMORY and false of STORAGE. Refcounting frees
      the Python object; it does nothing about the Iceberg snapshot
      that generation names, which expiry can delete out from under a
      still-running request. See 5h.
  3c. SERIALISE THE RELOAD ITSELF. SIGHUP and an admin request can
      arrive together. `_generation_lock` added in step 1a only stops
      duplicate NUMBERS -- two builds could still race to swap, and
      the loser's work is either wasted or lands second and wins.
      The whole build-validate-swap needs one lock, and it should be
      NON-BLOCKING: a second reload arriving mid-reload is rejected
      with "already in progress", not queued. Queueing would let a
      burst of SIGHUPs stack up rebuilds nobody asked for.
  3d. Failure leaves the running generation in place, and the error is
      returned to the caller with the same file-and-line detail
      `scripts/lint_deployment.py` produces. A broken YAML edit
      becomes a no-op with a message, where today it is an outage.
  3e. `POST /admin/reload`, requiring `manage:deployment` -- a NEW
      grant, not `manage:users`, because reloading configuration and
      creating accounts are different powers. Returns the new
      generation number, or the validation error.
  3f. `SIGHUP` as a second trigger, sharing 3a-3d exactly. **NOT
      file-watching**: a half-saved YAML would trigger a reload
      mid-write, and the failure mode is a partial read that happens
      to parse.
  3g. Concurrency tests, and these are the load-bearing ones for the
      whole plan: a reload during an in-flight request leaves that
      request on its pinned generation; N concurrent readers during a
      swap each see exactly one generation; a failed reload changes
      nothing observable. Run under the forced-interleaving discipline
      the existing concurrency tests already use.
  3h. Audit the reload itself -- who triggered it, from which
      generation to which, and the digest. A configuration change is a
      security-relevant event and currently has no record at all.

### A THIRD CATEGORY the two-way split missed

The plan divides app.state into configuration-derived (rebuilt on
reload) and runtime state (survives a reload). Building step 3 found a
third case the split does not cover: **runtime state that CARRIES A
SLICE OF CONFIGURATION.**

UserDirectory owns credentials.db, so it must survive a reload -- but
it also validated role names against a roles dict captured at
construction. A surviving object holding a snapshot of replaced config
is stale by construction: after a reload added a role, creating a user
with it failed "Unknown role" until the process restarted.

Its own docstring said roles "comes from the same static,
per-deployment policy.yaml that never changes across this instance's
lifetime". True when written; falsified by step 3.

**The fix generalises**: such an object reads configuration through a
CALLABLE onto the current generation rather than holding a snapshot.
It survives, and what it reads is always current.

**AUDIT DONE. Three findings, each a different kind.**

**CLEAN (five).** credential_store, session_store,
login_attempt_tracker, query_rate_limiter and artifact_store take only
a database path. A path is not configuration in the sense that matters
-- it comes from RuntimePaths, which is environment rather than
policy, and a reload cannot change where the process was told to look.
Nothing stale.

**pending_writes: NOT STALE, BUT COUPLED.** It takes
`mediator.audit_log` -- the audit log belonging to the generation in
force at startup. It survives a reload; that audit log does not get
replaced under it, so writes proposed later are audited against the
STARTUP generation's log object.

Not a correctness bug today, because every generation's AuditLog writes
to the same file and carries its own generation stamp -- so the stamp
on an expiry entry would name the startup generation rather than the
current one. That is a wrong-but-plausible value in an audit trail,
which is the category this project treats seriously. Worth fixing by
the same callable pattern, and worth fixing BEFORE the approvals inbox
makes pending writes long-lived enough to outlive several generations.

**executor: A DIFFERENT PROBLEM ENTIRELY, and the only one that is
genuinely unfixable by the callable pattern.** It is built with
`max_workers=config.max_concurrent_requests`. A reload changing that
number does nothing: a ThreadPoolExecutor's size is fixed at
construction, and rebuilding it would abandon in-flight work.

So `max_concurrent_requests` is a setting that CANNOT take effect
without a restart. The honest options are to say so where it is
declared, to reject a reload that changes it, or to accept it silently
-- and silently is the one option this project's stated discipline
rules out. Worth deciding before someone edits it, reloads, and
believes it applied.

That is a fourth category the split does not cover: **configuration
that is unreloadable by nature.** Anything sizing a pool, binding a
socket, or opening a file handle at startup belongs to it.

### 4. Narrowing the evaluation window

  4a. Re-resolve `UserRecord` per hop rather than per request, closing
      the disable-and-role-change window already recorded in
      ROADMAP.md's security backlog. Costs one `credentials.db` read
      per step.
  4b. **CLOSED BY CONSTRUCTION -- no code needed.** visible_schema has
      exactly two inputs: the mediator's schema and roles, both from
      the pinned deep-frozen generation, and the acting UserRecord,
      which 4a now stops the loop on if it changes. There is no path
      by which it can differ mid-query, so "recompute when the
      generation moves" would recompute the same answer. Asserted by a
      test rather than left as reasoning.
  4c. **ALSO CLOSED BY CONSTRUCTION.** The route takes its loop from
      the PINNED generation, and the loop holds that generation's
      mediator, so an in-flight query finishes under the configuration
      it started with. That is the finish-under-the-pinned-one option
      this step listed, and step 2 already made it the only reachable
      behaviour. Tested.

      The gap that WAS real: nothing stopped a route reading
      `app.state.generation` directly, which bypasses the pin as
      effectively as the five deleted attributes did -- it reads
      whatever is current at that instant rather than what the request
      pinned. Found by a control, and the guard now covers it. A guard
      naming five specific attributes did not generalise to the
      sixth.

### 5. The mirror, and adapting to sources that change shape

**REWRITTEN. The first version of this section was wrong, and the
error is recorded because it changed the design rather than the
wording.**

It said Elysium "queries the customer's databases live, so there is no
index to rebuild", and concluded that source schema drift should WARN
rather than adapt. Both false. ROADMAP.md's read-only mirror
architecture is largely built -- Phases 0, 1, 2 and 4 done,
core/mirror/iceberg_sync.py syncs into Iceberg, core/mirror/
mirror_adapter.py reads from it, read_from_mirror is already a config
flag. Elysium HAS the versioned internal copy Foundry has, so
hydration, readiness gates and the additive/destructive split apply
directly rather than by analogy. The mirror is ours, so drift is not
merely detected -- it is absorbed.

**WHAT ICEBERG ALREADY GIVES US**, verified against the pinned
pyiceberg 0.12: `update_schema()` (add, rename, update, delete column,
tracked by unique FIELD ID so a rename does not break readers and an
add or drop does not rewrite data); `manage_snapshots()` (create_branch,
create_tag, remove_branch); and `scan(snapshot_id=...)`.

**WHAT IT DOES NOT GIVE US AT 0.12**, and this constraint shaped the
design: `ManageSnapshots.fast_forward_branch` landed on pyiceberg main
on 10 September 2026 and is NOT in the pinned release. Branch merge
strategies generally -- merge, squash, rebase, cherry-pick,
fast-forward -- are an open upstream feature request. Any design
requiring a branch to be MERGED into main is therefore not buildable
today without an unreleased dependency or hand-rolled merge semantics.

**THE DESIGN THAT NEEDS NO MERGE.** Publishing is a CONFIG GENERATION
SWAP, not an Iceberg ref move. A generation records, per mirrored
table, the snapshot id it reads. Sync produces new snapshots; a new
generation naming them is what makes them live. Better than
branch-and-merge rather than a substitute for it:

- Uses only what 0.12 has.
- ONE atomic publish for both halves: a request pins a generation and
  gets the ontology definition AND the data snapshot that match it,
  which neither half provides alone.
- Rollback is naming an older generation, not restoring anything.
- Keeps each versioning system doing what it is good at: git versions
  the DEFINITION -- the infrastructure-as-code property Foundry users
  are asking Palantir for -- and Iceberg versions the DATA.

**WHAT THE SYNC DOES TODAY, read rather than assumed.** It fails
loudly on drift: transform_rows() detects type drift and iceberg_sync
raises ValueError(describe_drift(...)), per this project's own "fail
loudly, never silently substitute" rule. There is NO call to
update_schema() anywhere -- grepped, zero hits -- so the mirror cannot
absorb any schema change at all today, and overwrite() writes to main
directly.

  5a. Pin a snapshot on read. mirror_adapter calls load_table(...)
      .scan(...), which reads whatever is current. Passing the
      generation's snapshot id is small, and is what makes a
      generation mean anything for data.
  5b. Record per-table snapshot ids on the generation, alongside the
      config digest from step 1a. The digest answers "did the
      definition change"; these answer "which data does it describe".
      Two questions, two fields, deliberately not conflated.
  5c. Sync writes to a BRANCH and validates there, leaving main alone.
      Publishing is 5b, not a merge. create_branch exists at 0.12.
  5d. Absorb ADDITIVE source change via update_schema().add_column()
      on the branch. A new source column is not an error.
  5e. **DECIDED, following Foundry, and blocked on a capability the
      adapter contract does not have.**

      THE RULE IS NOT "ALWAYS REFUSE". In Object Storage v2 a schema
      change is breaking only if the property HAS RECEIVED USER EDITS;
      deleting one nobody ever edited is not breaking at all. The write
      log is the same thing under another name, so the verdict depends
      on what it holds:

      - column gone, NOTHING ever wrote that field -> ABSORB. No
        obligation to strand, no history to orphan. Refusing here
        freezes the mirror over a column nobody used, and a frozen
        mirror goes stale while the source moves on -- stale data that
        looks current is its own kind of wrong.
      - column gone, WRITES EXIST -> REFUSE, naming the field, the
        counts, and the options. Foundry's own instruction is "drop all
        property edits", used "when deleting a property and there is no
        new property as a replacement": a named disposition chosen by a
        human, never a default.

      THE ORPHANED-ROWS QUESTION IS ANSWERED, and it needed answering
      because leaving it undecided was the same fault the policy exists
      to fix. Applied and pending writes get DIFFERENT treatment:

      - an APPLIED write is HISTORY. The value was set, the change
        happened, and dropping the field does not unmake it. Its
        write_log row stays, exactly as Foundry keeps edit history
        separate from the index -- which is why they can migrate and
        OSv1 could not.
      - a PENDING write is an OBLIGATION. Someone proposed it, nobody
        decided, and the field it targets no longer exists, so it can
        never be applied and would sit in the queue forever. It must be
        marked unapplyable at the moment the field goes, not discovered
        at apply time. That is step 6's work and this is the trigger
        for it.

      TYPE CHANGE IS ALWAYS REFUSED and does not soften when nothing
      has been written, unlike a removal: the column is still THERE and
      still READ, so absorbing it means serving values of a type the
      ontology says they are not. That reaches every reader, not only
      writers.

      **BLOCKED ON: ExternalReadAdapter cannot report its columns.**
      read_all_rows() takes the columns it is told to read, so a
      vanished column surfaces as whatever the adapter's SELECT raises
      -- which IS the storage-dictated behaviour this policy exists to
      replace. Detecting it needs a new method on the contract,
      implemented by all three adapters. That is a separate change from
      deciding what to do, and doing both at once would land the
      decision untested against a capability added in the same commit.

      Written up rather than half-built: a drift_policy module with
      four verdicts and one reachable caller is three speculative
      functions, which is what this project deletes.

  5e-original. Absorb DESTRUCTIVE source change -- needs a decision, not just
      an implementation. A dropped source column can be dropped from
      the mirror (delete_column) or retained and nulled. Retaining is
      safer for readers on older generations and field IDs make it
      cheap. Neither should happen automatically without the operator
      seeing it.
  5f. **VERIFIED, which is what this step asked for.** Refcounting
      retires old-generation adapters for free IF they hold no
      process-global state. sqlite_adapter had been checked; the mirror
      adapter's catalog handle had not, and a reload builds a SECOND
      SqlCatalog over the same catalog.db while requests pinned to the
      previous generation are still reading through the first.

      Probed before assuming: twenty concurrent reads on an old adapter
      while ten new catalogs were built and read over the same mirror.
      No errors. Neither adapter has module-level state, no lru_cache,
      and two adapters never share a catalog object.

      Now a test rather than a one-off probe, because the property
      belongs to pyiceberg and SQLite rather than to us -- a dependency
      bump could take it away and nothing else here would notice.

      Note what this does NOT establish: that an adapter mid-read is
      safe when a silo is REPOINTED, which is 5g and is a different
      question. Coexisting over one file is not the same as surviving
      the file changing underneath you.
  5g. **NAMED AND WARNED, not refused.** Repointing a silo changes
      WHERE THE CUSTOMER'S DATA COMES FROM -- the most
      security-relevant change a reload can make -- and it was
      invisible: the audit said only that generation 7 became 8, which
      does not distinguish a model-timeout tweak from a database being
      swapped underneath the ontology. The reload entry now names the
      silos whose connection or adapter changed.

      WARNED RATHER THAN REFUSED, deliberately. Requests already in
      flight keep the OLD adapters and go on reading the OLD source,
      which is correct -- an answer assembled half from one database
      and half from another was never true anywhere. But if the
      operator repointed because the old path is being decommissioned,
      those reads are on borrowed time, and only they know which case
      it is. Refusing would be worse: a deployment that cannot be
      repointed without a restart loses what this migration is for.

      The comparison is deliberately NARROW -- connection and adapter
      only. An audit line that fires on every edit is one nobody reads,
      and there is a test asserting an ordinary reload reports nothing.
      An ADDED or REMOVED silo is not a repoint either: neither
      redirects an existing read.

      What remains for step 6 is the obligation half: a pending write
      proposed against the old source, still queued when the silo
      moves.
  5h. **SNAPSHOT RETENTION MUST RESPECT PINNED GENERATIONS**, and this
      is a data-loss gap rather than a tidiness one. Nothing expires
      Iceberg snapshots today -- grepped, zero hits -- but retention is
      ordinary practice and the moment it is added this goes live:

        1. A query pins generation N, naming snapshot 12345.
        2. Sync runs twice. 12345 is two versions back.
        3. expire_snapshots reclaims it and DELETES the Parquet files.
        4. Hop 5 of the still-running query scans 12345. Gone.

      On CPU-only hardware a query can run half an hour, so the window
      is wide.

      **REVISED. The tag-and-release design first written here was
      wrong, and structurally rather than in a detail.**

      It said a generation TAGS the snapshots it names and releases
      them when no request holds it, refcounting the data. That reads
      well and cannot work, because **expiry would run in a DIFFERENT
      PROCESS.** scripts/run_sync.py is a script; generations live in
      the server. A Python-side refcount of live generations is
      invisible to whatever does the expiring, so it protects nothing.

      Tags WOULD be visible across processes, since they live in the
      catalog -- which is why the original reached for them. But taking
      a tag is a WRITE to the mirror catalog, and the server process
      currently only READS the mirror. Giving the read path write
      access purely for bookkeeping widens what a compromised server
      can do, for a benefit with a much cheaper alternative.

      **EXPIRE BY AGE, WITH A MARGIN.** Iceberg's expiry already
      supports an age threshold. Set it comfortably longer than the
      longest possible request -- hours, not minutes -- and no
      coordination is needed at all: no cross-process protocol, no new
      write capability on the read path, no refcount to get wrong in
      either direction.

      Weaker in theory, since a request outliving the threshold would
      still break. But max_hops and the request timeout BOUND how long
      a query can run, so a threshold exceeding that bound by an order
      of magnitude makes the case unreachable rather than merely
      unlikely.

      **CHECKED AGAINST FOUNDRY AFTERWARDS, and the age-margin
      conclusion holds -- but it was incomplete.** Foundry's retention
      does offer an age selector ("selects transactions older than the
      given duration"), so age-based retention is precedent rather
      than invention. What I had missed is the rule they treat as
      PRIMARY, and it is simpler and stronger than age:

      **NEVER DELETE WHAT IS CURRENT.** "By default, retention policies
      will never delete transactions that are in the latest view of any
      branch." Overriding it is available and documented as "very
      dangerous", explicitly because it "may result in the deletion of
      current data that is still in use".

      For us that means: whatever expiry is added must never reclaim a
      table's CURRENT snapshot, regardless of age. That protects every
      request that pinned the newest snapshot -- the overwhelmingly
      common case -- absolutely rather than probabilistically, and it
      needs no threshold tuning at all. The age margin then covers the
      narrower case of a request pinned to a snapshot that a sync has
      since superseded.

      Both, not either: the structural rule handles the common case
      exactly, the age margin handles the tail.

      **ALSO WORTH COPYING, though not required: MARK, THEN DELETE.**
      Foundry marks a transaction first -- "the data in the transaction
      may be deleted at any point, and so should not be read" -- and
      performs the real deletion periodically afterwards. The gap
      between the two is a grace period, and it is what makes their
      retention safe to run against a live system rather than merely
      careful. Over-engineered for a single-process deployment today;
      the right answer if expiry ever becomes aggressive.

      **NOT BUILT, deliberately: nothing expires snapshots today** --
      grepped, zero occurrences. Building retention machinery before
      retention exists is speculative, and the protection is only
      meaningful alongside the thing it protects against. What IS built
      is a guard that fires the moment expiry appears, pointing
      whoever adds it at this decision.
  5i. **CLOSED BY CONSTRUCTION -- no code needed, asserted anyway.**
      mirror_synced_at is computed once when a generation is built and
      stored on that generation's mediator, and /data-freshness reads
      it through the pin. A sync landing mid-request cannot make the
      answer describe data the caller is not being served.

      Reading the catalog live would be WORSE than a stale number: it
      would report a sync the pinned snapshot deliberately excludes,
      saying the data is fresher than what is actually being read.

      Tested rather than struck off, because "already true" and "never
      checked" look identical in a plan. One of those assertions was
      initially hollow and a control caught it: deployment/etc reads
      LIVE, so comparing mirror_synced_at across a reload asserts
      None == None. It now asserts the pinned generation keeps its own
      MEDIATOR, which is what a live read would actually break.

  5i-original. Report freshness FOR THE PINNED GENERATION, not for the
      mediator's current state. /data-freshness already exists and
      returns source plus last_synced_at, which is the right idea --
      but once requests pin a generation, a user reading
      stale-but-consistent data should be told WHICH point in time
      they are seeing. Otherwise "consistently stale" is invisible and
      looks like being wrong.

### Retrace: is the work already committed compatible?

Checked when step 5 was rewritten, because a design change that
invalidates shipped commits is worth knowing about immediately rather
than at step 5. **It does not. Nothing needs undoing, and the reason is
structural rather than lucky.**

- **`generation` is an OPAQUE INTEGER.** It identifies a load; it does
  not encode what a load consists of. Adding per-table snapshot ids to
  the generation extends what a generation NAMES without changing what
  a generation IS, so `audit.generation` and
  `PendingWrite.proposed_under_generation` keep meaning exactly what
  they meant.
- **`source_digest` covers the four YAML files and nothing else** --
  `CONFIG_FILENAMES` names them explicitly. That is still precisely
  right: it answers "did the DEFINITION change". Snapshot ids answer
  "which DATA does it describe". Two questions, and 5b keeps them as
  two fields rather than folding data state into the digest, which
  would make "did the config change?" unanswerable whenever a sync
  ran.
- **Nothing conflates the two today** -- grepped, no generation code
  mentions snapshots or the mirror.

**THE GENERALISABLE POINT, and the reason this survived a design
reversal:** step 1 gave a load an IDENTITY rather than a DESCRIPTION.
An identity survives learning new things about what it identifies. Had
step 1a instead defined the generation as, say, a hash of the schema
contents, extending it to cover data would have been a breaking change
to every record already stamped.

Worth remembering for the steps still unbuilt: prefer naming a thing
over describing it.

### Synchronisation: what is needed, and what is deliberately not

Audited directly rather than assumed, because adding locks to a system
that already has the right ones is how throughput dies.

**ALREADY COVERED, and no hot-reload work changes it.** Striped
per-object locks in the mediator for writes; a ConcurrencyLimiter
semaphore per silo; flock(LOCK_EX) on sync.lock so two syncs cannot
overlap, released automatically on crash; a lock in PendingWriteStore;
_schema_verified_lock; a request thread pool; cancel_event for long
queries. SQLite transactions and Iceberg's atomic commits cover
storage.

**ADDED BY THIS PLAN:** the reload lock (3c) and the snapshot tag
refcount (5h). Those are the only two.

**NO READERS-WRITER LOCKS ANYWHERE, decided rather than skipped.**
Every place one would apply already has something strictly better:

- Configuration is the textbook RW case -- many readers, rare writer
  -- and is instead lock-free by immutability plus an atomic reference
  swap. Readers never block and the writer never waits. An RW lock
  would be worse on both counts. This is why step 2a mattered: RCU
  only works if the shared object genuinely cannot be mutated.
- The mirror is MVCC. A reader pinned to a snapshot is unaffected by a
  sync committing a new one, in either direction.
- Per-object locks are taken on the WRITE path only; reads never
  acquire them, so there is no contention for an RW lock to relieve.
- The remaining locks guard short read-modify-write sections, where an
  RW lock adds overhead and a writer-starvation failure mode for
  nothing.

**NO SCHEDULER.** Sync is triggered externally by run_sync.py and
reload will be admin-triggered or SIGHUP. An in-process scheduler
means a background thread -- a new concurrency surface for something
cron and systemd timers already do.

**NO LOCK IN THE ADAPTER BASE CLASS.** ExternalReadAdapter and
ExternalWriteAdapter are real ABCs, so it is mechanically possible and
still wrong three ways: the granularity is per-SILO where the mediator
already locks per-OBJECT; deciding what may overlap is an
ontology-level question the adapter cannot answer because it does not
know object identity; and the three adapters sit on three different
concurrency models -- SQLite's single-writer lock, Iceberg's snapshot
isolation, none at all -- so one policy would force a single answer
onto three different problems, and for Iceberg would REMOVE
concurrency that MVCC provides free.

### 6. Destructive changes and existing obligations

Only meaningful once writes are long-lived, i.e. once the approvals
inbox exists. Deferred deliberately, and listed so the dependency is
visible rather than discovered.

  6a. Diff a new generation against the current one and classify each
      change additive or destructive, per Foundry's own split.
  6b. On a destructive change, mark affected pending writes
      unapplyable with a specific reason -- a write referencing a
      removed field cannot be approved, and finding that out at apply
      time is worse than at reload time.
  6c. Surface it in the approvals inbox: a write invalidated by a
      configuration change is a different state from rejected, and the
      audit trail must say which.

### What is deliberately NOT in this roadmap

- **Multiple concurrent generations addressable by name.** Foundry
  serves several, because callers pin SDK versions. Elysium has one
  client and no such need. The generation NUMBER is recorded for
  audit; serving old generations on request is a different feature.
- **Branching configuration.** Foundry's branch-proposal-merge flow
  governs ontology change. Elysium's equivalent is git plus
  `scripts/lint_deployment.py`, which is already the
  infrastructure-as-code property Foundry users are asking Palantir
  for. Do not trade it away for an in-app editor.
- **Reloading `credentials.db` or any runtime state.** It is not
  configuration and never reloads; it is read live already.
