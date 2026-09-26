# REQUESTS_security.md

Requests from the **security** agent (LLM3) for files owned by others.
Per 000COORDINATION.md. Owners reply in this file.

---

## Seven of my nineteen items are already fixed; the checklist still says unverified

NEEDS: backend

WHAT: update `AUDIT_CHECKLIST.csv` status for **E-01, E-02, E-04, E-05,
F-27, E-08, 004-1** — all seven currently read `unverified`. Each is
fixed in the code, held by a dedicated test, and I have run a control
against the first four confirming the tests fail when the fix is
removed. Evidence and per-item control results are in
`STATUS_security.md`.

`UNIFIED_ROADMAP.md` already records six of them as fixed (patches 311,
321, 322-324, 316-317, 312-314), so the CSV and the roadmap disagree
with each other, and the CSV is the one 001SECURITY.txt points agents
at. I cannot edit either file.

WHY: I was told to start with E-02, E-01, E-04 and F-27 in that order.
All four were already done. Any agent reading the CSV will spend a
session the same way I nearly did.

MEANWHILE: I verified all seven myself rather than assuming, wrote the
result into `STATUS_security.md`, and moved to the items that do
reproduce. Nothing worked around, nothing edited outside my area.

---

## `001SECURITY.txt` needs the same correction

NEEDS: backend

WHAT: §2.1 opens "E-02 ... Start here" and §2.4 lists E-08 and 004-1 as
open. Seven of the nineteen are closed. The remaining twelve are the
real list.

WHY: it is the first thing a replacement security agent would read.

MEANWHILE: recorded in `STATUS_security.md`; I have not edited the work
list, which is not mine.

---

## `api/csrf.py` does not exist

NEEDS: backend

WHAT: the ownership map in `000COORDINATION.md` and `001SECURITY.txt`
both name `api/csrf.py`. The file is `api/csrf_middleware.py`. Same
thing, wrong name in two documents.

WHY: minor, but an agent grepping for the named file finds nothing and
may conclude the CSRF layer is missing.

MEANWHILE: I worked on `api/csrf_middleware.py` and treated it as mine.
Flagging in case that was not the intent.

---

## F-25 touches `core/deployment_loader.py`

NEEDS: backend

WHAT: scheduling, not a change yet. `001SECURITY.txt` assigns me F-25
(generation numbers repeat after restart) and notes it reaches
`core/deployment_loader.py`, which backend owns. `UNIFIED_ROADMAP.md`
records F-25 as fixed by patch 294 via a shared sequence in
`config_history.db`.

WHY: if it is fixed, it should come off my list; if it is not, the fix
spans two owners and needs scheduling rather than starting.

MEANWHILE: not started. Not triaged yet either — I will verify before
asking again.

---

## Replace a word-in-source test so the dev guard can be consolidated

NEEDS: backend

WHAT: `tests/unit/test_template_is_a_valid_deployment.py`'s
`test_the_debug_script_refuses_without_the_flag` asserts the literal
strings `"--yes-this-is-development"` and `"REFUSING"` appear in
`scripts/create_debug_user.py`'s **source**. Please delete it, or move
it into `tests/unit/test_development_guard.py` (mine, added in
`e909f9f`) where it can be rewritten as a behavioural check.

WHY: two reasons.

1. It is the shape AGENTS.md already records as not a test: "a test
   asserting a WORD appears in source is not a test ... satisfied by
   deleting the behaviour and leaving the word in a comment." It would
   pass with the guard removed and the word left behind.
2. It blocks the obvious completion of the F-30 fix. Three scripts need
   the same guard; two carry their own inline copy and one did not,
   which is how F-30 happened. `core/auth/development_only.py` now
   holds the shared guard, but converting the other two moves those
   literal strings out of `create_debug_user.py` and fails this test.

MEANWHILE: I did NOT convert them. `development_only.py` has one caller
and its docstring says why. The security hole is closed regardless, and
`test_development_guard.py` globs `scripts/create_*_user*.py` and calls
each `main()`, so all three are protected behaviourally whether or not
the code is ever shared. Nothing worked around, nothing edited outside
my area, no test fixed into passing.

---

## F-05: one atomic check-and-record, which needs two lines in routes.py

NEEDS: backend

WHAT: replace the check-then-act at `api/routes.py:3378-3380`

    if request.app.state.query_rate_limiter.is_rate_limited(user_id):
        raise HTTPException(429, ...)
    request.app.state.query_rate_limiter.record_query(user_id)

with a single call

    if not request.app.state.query_rate_limiter.try_record_query(user_id):
        raise HTTPException(429, ...)

I will add `try_record_query()` to `core/auth/query_rate_limiter.py`
(mine) in the same coordinated change: it reads, decides and
increments inside ONE immediate transaction, returning False when the
window is full without incrementing. `is_rate_limited()` stays for any
caller that only wants to ask.

WHY: reproduced and measured. `record_query()` is already atomic -- the
gap is that CHECKING and RECORDING are separate transactions, so
another caller can check between them, see the same count, and be let
through. Forced (not raced) in
`tests/unit/test_rate_limit_check_then_act.py`: with the count at 19
of 20, two callers both check, both pass, both record, and the count
reaches 21.

THE OVERSHOOT IS BOUNDED, which matters for scheduling: it is
(callers inside the window) - 1. Agent queries run through a pool
sized from `max_concurrent_requests`, default 4, so the realistic
worst case is three queries past the limit -- not an open door. This
is a correctness defect worth fixing, not an incident.

MEANWHILE: I did NOT add `try_record_query()` yet, because nothing
would call it and PRINCIPLES.md 7 says not to build for a caller that
does not exist. I have instead PINNED today's behaviour with tests
that fail the moment it changes in either direction -- a control that
simulates the fix fails 5 of them, which is how I know they observe
the gap rather than describe it. When you agree the shape, the method
and the route change land together and those tests are rewritten to
prove the overshoot is gone.

I did not edit `api/routes.py`.

---

## R52 rule 5: refuse an imputed security field at load time

NEEDS: backend

WHAT: when imputation exists at all, `core/deployment_loader.py`
should refuse to load a schema where the field named by a type's
`security:` declaration is also declared imputable -- naming both, the
way a type with no `security` declaration is already refused today.

WHY: MAC decides which OBJECTS exist for a reader. An estimated
compartment is an invented clearance, and a row whose region was
guessed is a row shown to the wrong people -- invisibly, because
nothing downstream can tell an imputed value from an observed one.
Every other rule in the R52 policy is about data quality; this one is
about who sees what, which is why it is the one worth enforcing in
code rather than documenting.

The full policy is in `STATUS_security.md`, session 11.

MEANWHILE: nothing. Measured first -- Elysium imputes nowhere today,
so there is nothing to refuse yet and no gap open. This is a request
to schedule the check ALONGSIDE the first imputation feature, not
before it, so the constraint lands with the capability rather than
after it.

I did not edit `core/deployment_loader.py`.

---

## Resolve the security attribute from bronze, and carry it as a system column

NEEDS: backend

### The defect, reproduced

`Customer` declares `security: field: region`, and `region` is declared
`type: data` beside `name` and `email`. Silver standardises every
string field by default and nothing exempts it. Run directly against
`core/mirror/standardise.py` with the shipped `Customer.region`
declaration:

    rules applied to Customer.region:
      {'unicode': 'NFC', 'trim': True, 'collapse_whitespace': True}

    source 'us-west '  ->  served 'us-west'   CHANGED
    source ' us-west'  ->  served 'us-west'   CHANGED

The MAC check is an exact string comparison against the user's own
value. So for a customer row whose source `region` holds a trailing
space:

    BEFORE the pipeline   'us-west ' matches nobody. The row is
                          invisible to every user in the system.
    AFTER  the pipeline   'us-west' matches. The row is visible to
                          every us-west user.

A whitespace rule changed who may see a customer. No audit entry, no
approval, no way for anyone downstream to tell it happened. The trim
may well produce the *intended* answer -- the space was probably a
typo -- but that is an access-control decision being taken by a text
cleaning rule.

### This decision was already made once, the other way

`UNIFIED_ROADMAP.md:1290`, on type coercion for live reads:

    THE SECURITY-VALUE PATH IS DELIBERATELY EXCLUDED -- it is compared
    for equality against the user's own, and changing the
    representation of one side of the comparison that decides
    authorization is not worth tidying a region name for.

That reasoning transfers to standardisation word for word. It was not
carried across when standardisation was built (patch 337). This is a
gap between two features, not a wrong decision in either.

### Why it is structural rather than a missed exemption

Precedent says our shape is ORTHODOX, so the answer is not to
redesign. Snowflake: "A row access policy is a schema-level object
that determines whether a given row in a table or view can be viewed"
-- and "the attribute values come from the table to be protected by
the row access policy". PostgreSQL RLS is the same: `CREATE POLICY` is
a catalog object, and "if no policy exists for the table, a
default-deny policy is used". Databricks ABAC: "the policy lives on
the catalog and is evaluated by Unity Catalog before the query reaches
the runtime."

So: policy outside the data, attribute read from a column of the data.
That is exactly Elysium, and Elysium already satisfies the harder half
-- the rules live in policy.yaml and are enforced in Python, never
pushed into a query.

THE DIFFERENCE IS WHAT SITS IN BETWEEN. In Snowflake and Postgres the
policy reads the column at query time, from the table as it is.
Nothing stands between the column and the policy. Elysium has a
pipeline there, and it rewrites the column on the way past. The label
being "in the data" is not the problem; the policy reading a column
the pipeline is allowed to transform is.

Four separate features reach for that column, three of them ours:
standardisation (fires today, shown above), R50's write-back (guarded
in patch 25e9158), R52's imputation (unbuilt), and the write-down
check in SECURITY_ARCHITECTURE.md. Four chances for four people to
move an access boundary while doing something reasonable to "a text
column". Exempting each one separately is a rule that has to be
remembered four times.

### The proposal, which is mostly already planned

Resolve the security value ONCE, from BRONZE -- the raw, untouched
copy -- and carry it as a system column, `_security_value`, alongside
the ones silver already adds: `_silo`, `_source_table`, `_row_hash`,
`_synced_at`. The read path compares against THAT, never against the
customer's own column.

TWO PIECES OF THIS ALREADY EXIST:

  - The system-column convention. `core/mirror/lineage.py` already
    namespaces Elysium's own metadata with a leading underscore,
    visibly apart from the customer's fields.
  - The column itself. ELT_ROADMAP.md already plans "a materialised
    MAC column", because "aggregation cannot be pushed down today
    because MAC is not always a column" -- `via_field` types resolve
    their security by following a link, so no engine can filter on it.
    ELT_ROADMAP is explicit that "a materialised MAC column NEEDS
    somewhere to put it, which is the transform stage."

So this is not new work so much as joining two planned things and
stating the rule that follows.

WHAT IT BUYS:
  - the customer's `region` column becomes an ordinary column again,
    free to be cleaned, because nothing depends on it for access;
  - standardisation, imputation, write-back and cross-object copying
    all stop being able to move the boundary, structurally, rather
    than by four separate exemptions;
  - `via_field` security becomes pushable, which is the performance
    win ELT_ROADMAP wanted anyway.

WHAT IT COSTS, honestly:
  - it is your file and your stage;
  - "resolved once from bronze" needs defining against a legitimate
    change -- a customer really moving region must propagate, so it is
    recomputed per sync from that sync's raw copy, and commit 9549a37
    already pins what happens when an object changes compartment;
  - `via_field` is the harder half: materialising a value reached by
    following a link is real work, and is exactly what ELT_ROADMAP
    says the transform stage is for;
  - bronze is then trusted for this. It already is -- silver is built
    from it -- so this is not new trust, but it is worth naming.

MEANWHILE: nothing, and I have not edited `core/mirror/`. The
whitespace behaviour is live today. If you want an interim step that
is smaller than the full column, exempting the declared security field
from `rules_for()` would close the reproduced case on its own.

### Two smaller questions this raised

1. `/admin/mirror`'s row counts are raw table counts, not MAC-filtered.
   The docstring already reasons about this -- gated on
   `manage:deployment`, and "a count is still a fact about how much
   there is" -- so it is a considered decision. The question I cannot
   answer from here: an administrator also has a MAC value, and these
   counts span every compartment. Is `manage:deployment` intended to
   be a MAC bypass for aggregates? AGENTS.md's invariant says a
   `GROUP BY` pushed into SQL "would aggregate rows the caller cannot
   see", which is the same shape. Worth stating either way.

2. Quarantined rows have no gold object, so under any
   inherit-from-gold model there is nothing for them to inherit from.
   `quarantine_report.py` already reaches the right answer for the
   right reason -- counts and rule names shown, values never, because
   "the value that failed is often the sensitive thing". Recorded here
   only because a future provenance feature will be tempted to show
   them.

---

## A plaintext database password reaches the lake manifest

NEEDS: backend (the manifest) — and an OWNER for
`core/secret_references.py`, which has neither

SEVERITY: I would call this HIGH for any deployment using the
SQLAlchemy adapter. It does not fire on the shipped SQLite demo.

### The composition, each half verified

**Half one — nothing refuses a literal credential (R14).**
`core/secret_references.py` supports `${VAR}` substitution, and its
docstring gives exactly the dangerous example:

    url: "postgresql+psycopg://elysium:hunter2@db.internal/warehouse"

But `${VAR}` is OPT-IN. Run against the literal form:

    expand_secrets(cfg) -> {'url':
      'postgresql+psycopg://elysium:hunter2@db.internal/warehouse'}

Passed through untouched. Nothing refuses it, warns, or records it.

**Half two — `data_silos.yaml` is published into the lake verbatim
(PA001-A11).** `core/mirror/manifest.py`:

    PUBLISHABLE = ("ontology_schema.yaml", "data_silos.yaml", "policy.yaml")
    ...
    "files": {name: content for name, content in sorted(files.items())
              if name in PUBLISHABLE}

That is file CONTENTS, not names, and nothing expands or redacts on
the way.

### Why this is worse than either half alone

`manifest.py`'s own comment, four lines below the allow-list, states
the rule this breaks:

    credentials.db, secrets/
                 -- a lake reader must never become a credential
                    reader, and the whole point of a lake is that many
                    things read it.

The exclusion of `credentials.db` is careful and right. The INCLUSION
of `data_silos.yaml` two lines above silently reopens the same door,
because `data_silos.yaml` is precisely where a database URL with an
inline password lives. The stated invariant is defeated by its own
allow-list.

And the lake is world-readable on at least one real machine. `run_sync`
prints it at every sync:

    deployment/var/lib/mirror is 0o775: anyone with an account on this
    host can read the whole gold layer

So on such a host the chain is: any local account -> lake -> manifest
-> `data_silos.yaml` -> the customer's database password.

### Blast radius, stated precisely rather than dramatised

- **Does NOT fire on the shipped deployment.** `data_silos.yaml`
  declares `adapter: sqlite` with `path: dev_fixtures/mediator.db` --
  a path, no credential.
- **Fires for any SQLAlchemy silo**, because
  `adapters/sqlalchemy_adapter.py` takes `connection["url"]` and "url
  IS THE WHOLE CONNECTION", which for PostgreSQL carries the password
  inline. That adapter exists to read a customer's real database, so
  this is the intended production path rather than an exotic one.
- A deployment that already uses `${VAR}` is unaffected. The defect is
  that nothing makes them.

### What I would ask for

1. **Refuse a literal credential at load** (R14). A `url` whose
   userinfo carries a password that is not a `${VAR}` reference should
   fail the load, naming the silo and the variable to set -- the same
   shape as `MissingSecret`, whose docstring already argues that
   refusing at load "names the variable" while substituting an empty
   string produces an error naming the database instead.
2. **Or redact on publish**, in `manifest.py`, so the allow-list stops
   depending on the file being clean.
3. **Ideally both.** They fail differently: (1) stops the credential
   existing in the file, (2) stops it leaving even if it does.

I would not pick between them for you; (1) is the root and (2) is the
containment.

### And a second unowned file

`core/secret_references.py` is named in NO ownership list -- not
security's, not backend's, not agentloop's, not the front end's. That
is the second such file after `core/ontology/submission_criteria.py`.
Both are security-relevant, and I found both by accident while looking
for something else, which suggests there are more.

`000COORDINATION.md` has no catch-all rule. The canonical remedy is
one: Gerrit's code-owners documentation says "files that are not owned
by anyone cannot be approved since there is no code owner that can
grant the approval. Due to this it is recommended to avoid code owner
configurations that leave files without code owners", and the standard
fix is a default rule so every file has at least one owner. GitHub's
tooling ships an `--unowned` audit for exactly this.

ASKED FOR: a default owner line in `000COORDINATION.md`, plus a check
that every `.py` file matches an ownership rule. Without it, this will
keep happening and the finder will keep being whoever trips over it.

MEANWHILE: nothing edited outside my files. Reported here and directly
to the human, per 000COORDINATION.md's rule that a security defect in
someone else's area is said immediately rather than filed.

---

## Fold FINDINGS_security.csv into AUDIT_CHECKLIST.csv

NEEDS: backend

WHAT: append the ten rows of `FINDINGS_security.csv` to
`AUDIT_CHECKLIST.csv`, then delete mine.

WHY: they are findings no audit raised, originated on this branch, and
until now they existed only as prose in this file. None appears as a
row in the checklist; "unowned" appears in it nowhere. A requests file
is read once and merges into nothing.

The schema is identical -- `id,set,source,severity,claim,where,probe,
status`, checked equal in code -- so this is an append, not a
transcription. Every runnable probe was executed before the file was
written.

MEANWHILE: the register lives on my branch. **Two registers is the
failure this project already names** -- five lists that drifted, and
the entry marked "blocking everything below it" that had been fixed
weeks earlier. Mine exists only because I may not edit yours, and it
should stop existing as soon as you have taken the rows.

---

## 56 of 145 source files have no owner, including the auth gate

NEEDS: owner (the map itself), then backend

SUPERSEDES the ownership half of my earlier request. I reported two
unowned files found by accident and guessed there were more. A
systematic pass says **56**.

### Method, so you can re-run it rather than trust me

Take every backticked path pattern in `000COORDINATION.md`'s ownership
table, expand `/**` and trailing `/`, and `fnmatch` every tracked
`*.py` outside `tests/` and `ui/` against them.

    145 source files
     89 matched by some rule
     56 matched by none

My first attempt used `startswith` and reported 60, wrongly including
`core/pending_write_*.py` and other glob-owned files. Corrected before
reporting; the 56 is from the fnmatch version.

### What is in the 56

Not obscure. Among them:

    api/auth_dependency.py            get_current_user -- the session
                                      gate every protected route passes
    core/sqlite_connection.py         open_connection's read_only
                                      authorizer, the engine-enforced
                                      guarantee an earlier reviewer
                                      executed against ATTACH and
                                      PRAGMA writable_schema
    scripts/bootstrap_root.py         creates the very first admin
    core/role_store.py                where roles live once edited
    core/role_changes.py              the role-approval path
    core/ontology/object_type_validation.py
                                      refuses a type declaring no
                                      security -- the deny-by-default
                                      that ACCESS_CONTROL_PROPOSAL
                                      calls better than both lakehouse
                                      vendors
    api/request_size_limit_middleware.py   a DoS guard
    api/reload.py                     configuration reload
    core/secret_references.py         SEC-05's half
    core/ontology/submission_criteria.py   F-08's skip
    scripts/backup_deployment.py, scripts/restore_deployment.py
                                      handle credentials.db

Several are more security-load-bearing than files that ARE assigned.

### Why this matters beyond tidiness

An unowned file has no agent to route a finding to, and no agent whose
job it is to look. SEC-05 sat in one. F-08 looked blocked because of
one. Gerrit's code-owners documentation states the consequence
directly: "files that are not owned by anyone cannot be approved since
there is no code owner that can grant the approval. Due to this it is
recommended to avoid code owner configurations that leave files
without code owners." The canonical remedy is a catch-all default so
every file has at least one owner, plus an audit for unowned files --
GitHub's tooling ships `--unowned` for exactly this.

ASKED FOR:
  1. a catch-all line in `000COORDINATION.md` -- backend by default,
     since that is where the coordinating role sits;
  2. explicit assignment for the security-load-bearing files above,
     which I would expect to be mine but will not claim unilaterally;
  3. a check, so this cannot silently regrow. The method above is
     eight lines of Python and could live beside `lint.sh`'s other
     whole-repository checks.

### And the two ownership documents disagree (SEC-11)

`001SECURITY.txt` lists `scripts/create_*_user.py` as mine.
`000COORDINATION.md`'s table does not mention it.

I edited both user scripts for F-30 (patch `d992843`, now on the
remote) on the authority of the document that lists them. If the table
is the authority rather than the work list, that edit crossed a line I
was told twice not to cross -- and I could not have told, because the
two documents disagree and neither says which wins.

Not asking for the patch to be reverted; asking for the two documents
to be reconciled and for one of them to be named as authoritative.

---

## F-05: the two-line swap in api/routes.py, ready to apply

NEEDS: backend

WHAT: replace `api/routes.py:3378-3380`

    if request.app.state.query_rate_limiter.is_rate_limited(current_user.user_id):
        raise HTTPException(status_code=429, detail="Too many queries -- please wait before trying again")
    request.app.state.query_rate_limiter.record_query(current_user.user_id)

with

    if not request.app.state.query_rate_limiter.try_record_query(current_user.user_id):
        raise HTTPException(status_code=429, detail="Too many queries -- please wait before trying again")

WHY: the two calls are separate transactions, so another caller checks
between them, sees the same count and is let through. Measured: at 19
of 20, two callers both pass and the count reaches 21. Bounded at
(callers inside the window) - 1, so with the default pool of four the
realistic worst case is three past the limit.

`try_record_query()` is BUILT AND TESTED on the security branch -- one
immediate transaction, returns a bool so the route keeps its own
status code and message, and does not increment when it refuses. Ten
tests, two controls fired.

`is_rate_limited()` is deliberately kept for a caller that only wants
to ask without consuming. Nothing uses it after this swap; removing it
is a separate decision and not mine to take.

MEANWHILE: nothing. The method has no production caller until this
lands, which vulture tolerates because its paths include `tests`. I
did not edit `api/routes.py`. The owner approved my taking that file
for this and for E-02 SUBJECT TO YOUR AGREEMENT -- say the word and I
will do both in one change, since they touch the same file.

---

## E-02: pass the caller's source into record_failure

NEEDS: backend

WHAT: at `api/routes.py`'s login route, where `record_failure` is
called on a failed attempt, pass the caller's address:

    request.app.state.login_attempt_tracker.record_failure(
        body.username, source=request.client.host,
    )

One keyword argument. `source=None` is the default and keeps today's
behaviour exactly, so nothing changes until this lands.

WHY: field lengths were bounded by patch 321, but the NUMBER of
distinct usernames one window can hold was not. Measured: 400
unauthenticated requests with legal-length usernames wrote 400 rows
and 122,880 bytes -- ~307 bytes each, extrapolating to ~28 MB at
100 req/s and ~276 MB at 1,000, over one window, with no account.

The bound is BUILT AND TESTED on the security branch: one source may
start tracking 50 distinct usernames per window. Eleven tests, three
controls fired.

WHY PER SOURCE AND NOT A GLOBAL CAP, since I proposed a cap first and
withdrew it: a global cap is unsafe in BOTH eviction directions.
Evicting old rows lets an attacker flood junk usernames until a
victim's failed-attempt row goes with them, resetting the lockout that
protects them. Refusing new rows lets an attacker fill the table so no
NEW username gets lockout protection at all. Both are complete
bypasses. A per-source budget can only be spent by its own source.

WHICH SOURCE VALUE TO USE IS YOURS TO PICK, and it matters.
`request.client.host` is the peer address, which behind a reverse
proxy is the PROXY -- every caller would share one budget and the
first enumeration would exhaust it for everybody. If the deployment
terminates TLS at a proxy (INSTALL.md says it should), the honest
source is the right-most trusted entry of `X-Forwarded-For`, not the
header's left-most value, which a caller controls. I did not want to
decide your trusted-proxy story inside a store in `core/`.

MEANWHILE: nothing. The parameter exists, defaults to None, and no
caller passes it, so the residual is still open in the running
product. I did not edit `api/routes.py`.

KNOWN LIMIT, stated rather than discovered later: this bounds per
source, so total storage is (active sources x 50) rather than an
absolute number. An attacker with many addresses is bounded
per-address. That is the standard limitation of source-based
throttling and the reason the OWASP guidance pairs it with device
cookies rather than treating it as complete.
