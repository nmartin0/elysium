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
      statement, atomic in CPython, no lock on the read path. Old
      generations are freed when the last request pinning them
      finishes; refcounting handles this and no scheme is needed.
  3c. Failure leaves the running generation in place, and the error is
      returned to the caller with the same file-and-line detail
      `scripts/lint_deployment.py` produces. A broken YAML edit
      becomes a no-op with a message, where today it is an outage.
  3d. `POST /admin/reload`, requiring `manage:deployment` -- a NEW
      grant, not `manage:users`, because reloading configuration and
      creating accounts are different powers. Returns the new
      generation number, or the validation error.
  3e. `SIGHUP` as a second trigger, sharing 3a-3c exactly. **NOT
      file-watching**: a half-saved YAML would trigger a reload
      mid-write, and the failure mode is a partial read that happens
      to parse.
  3f. Concurrency tests, and these are the load-bearing ones for the
      whole plan: a reload during an in-flight request leaves that
      request on its pinned generation; N concurrent readers during a
      swap each see exactly one generation; a failed reload changes
      nothing observable. Run under the forced-interleaving discipline
      the existing concurrency tests already use.
  3g. Audit the reload itself -- who triggered it, from which
      generation to which, and the digest. A configuration change is a
      security-relevant event and currently has no record at all.

### 4. Narrowing the evaluation window

  4a. Re-resolve `UserRecord` per hop rather than per request, closing
      the disable-and-role-change window already recorded in
      ROADMAP.md's security backlog. Costs one `credentials.db` read
      per step.
  4b. Recompute `visible_schema` only when the pinned generation
      differs from the one the loop started with. Not per hop --
      that also changes the prompt mid-query and interacts with prefix
      caching, which is measured and load-bearing.
  4c. Decide what an in-flight agent loop does when the generation
      moves underneath it. Options: finish under the pinned one
      (consistent, possibly stale), or abort and report. Leaning
      finish-and-record, since the audit entry will say which
      generation applied.

### 5. The silo layer

  5a. Connection lifecycle across a reload: retire adapters from the
      old generation without killing in-flight reads. Refcounting
      gives this for free IF adapters hold no process-global state --
      **verify that before relying on it**, do not assume it.
  5b. Detect source schema drift at reload: a column named in
      `ontology_schema.yaml` that no longer exists in the table. WARN
      rather than fail, copying Foundry's schema-check posture -- a
      deployment should not become unbootable because one unused
      column was dropped.
  5c. Repointing a silo (path or credentials change) is a destructive
      change for anything holding an open connection. Treat it as
      such in step 6.

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
