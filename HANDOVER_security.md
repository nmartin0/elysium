# Handover from the security agent (LLM 3)

**START HERE.** This is the security agent's map: the state of its
work, what is outstanding, and who owns each piece. It supersedes the
entries scattered through `REQUESTS_security.md`, which stay as the
record of how each item was FOUND rather than what is left to do.

**The other three files of mine, and what each is for:**

    HANDOVER_security.md    this file -- the map, read first
    FINDINGS_security.csv   29 rows, same schema as AUDIT_CHECKLIST.csv
                            so they can be appended rather than retyped
    STATUS_security.md      session by session, including what was
                            tried and abandoned and why
    REQUESTS_security.md    the asks of other agents, with the exact
                            diffs and the measurements behind each

IT LIVES ON THE BRANCH ON PURPOSE. An earlier version of this existed
only as a file handed over out of band, which is the same failure this
agent spent the branch reporting in other forms: a record that does
not survive the thing it describes. If it is on the branch, whoever
opens it next finds the map without anybody having to forward it.

Self-contained: assumes no memory of the conversation it came from.
Every claim was run, and probes are included so you can re-run them
rather than trust me.

---

## 0. State of the branch

`origin/security`, **57 commits** on top of `f6c5a0b`. Gates green on a
fresh clone: `./lint.sh` clean with 8/8 import contracts, **3,029 unit
tests**, **448 integration tests**, nothing written into `deployment/`.

The original 19-item work list is complete: 15 closed here, 2 verified
already fixed, 2 reassigned to backend files (both look already
fixed). `FINDINGS_security.csv` holds **29 rows found while working**
-- 16 closed, 13 open -- in the same schema as `AUDIT_CHECKLIST.csv`,
so the rows can be appended rather than transcribed.

---

## 1. THE ONE THING THAT CHANGES THE VALUE OF THE MERGE

**Three completed, tested fixes are inert.** Each needs one or two
lines in `api/routes.py`, which this agent may not edit. Merging
as-is delivers none of the three protections. Recorded as SEC-20.

| Fix | What is still true in the product | Where |
| --- | --- | --- |
| **F-05** | rate limiting is still check-then-act; two callers at 19 of 20 both pass | `routes.py:3378-3380` |
| **E-02** | `login_attempts` is unbounded per window -- ~28 MB at 100 req/s, unauthenticated | the login route's `record_failure` call |
| **SEC-17** | the session cookie has no `__Host-` prefix | `routes.py:636`, `:1097` |

**F-05** -- replace

```python
if request.app.state.query_rate_limiter.is_rate_limited(current_user.user_id):
    raise HTTPException(status_code=429, detail="Too many queries -- please wait before trying again")
request.app.state.query_rate_limiter.record_query(current_user.user_id)
```

with

```python
if not request.app.state.query_rate_limiter.try_record_query(current_user.user_id):
    raise HTTPException(status_code=429, detail="Too many queries -- please wait before trying again")
```

**E-02** -- one keyword argument on the failed-login path:

```python
request.app.state.login_attempt_tracker.record_failure(
    body.username, source=request.client.host,
)
```

`source=None` is the default, so nothing changes until this lands.
**Which source value to use is your call and it matters:** behind a
reverse proxy `request.client.host` is the PROXY, so every caller
would share one budget and the first enumeration would exhaust it for
everybody. If TLS terminates at a proxy -- `INSTALL.md` says it should
-- the honest source is the right-most trusted entry of
`X-Forwarded-For`, never the header's left-most value, which a caller
controls.

**SEC-17** -- the complete diff for all three files is
`SEC-17-both-halves.diff`, handed over out of band. If it is lost, the
change is small enough to rebuild from this description: a
`session_cookie_name()` in `core/auth/auth_cookies.py` returning
`f"__Host-{SESSION_COOKIE_NAME}"` when `_cookie_secure()` and the bare
name otherwise, `set_session_cookie`/`clear_session_cookie` using it,
`api/auth_dependency.py` reading `request.cookies.get(
session_cookie_name())` at call time instead of through an
import-time `Cookie(alias=...)`, and the same two reads in
`api/routes.py`. **It is atomic.** Applying only the
security half passes every test and breaks logout in production:
measured, 208 integration tests passed with the broken combination.
There is now a test that catches it
(`tests/integration/test_production_cookie_configuration.py`, SEC-18).

**Recommendation: land these three before integration.**
`AUDIT_CHECKLIST.csv` still carries F-05 as `unverified` with no note
that a tested fix exists but is unwired -- that is how someone ends up
believing the rate limiter is atomic.

---

## 2. Deployment notes -- before the merge reaches a machine

**`expand_secrets()` now refuses a plaintext credential at load.** A
deployment with an inline database password in `data_silos.yaml`
**will not start** until it moves to a `${VAR}` reference. That is the
point of the change and the one thing here that can stop a running
system coming back up. All three shipped configurations declare SQLite
paths and are unaffected.

**Pending-write `SCHEMA_VERSION` went 1 -> 2.** On deploy, approvals
proposed in the preceding fifteen minutes are REFUSED rather than
misread -- deliberate, and this module's stated preference, but worth
knowing before it happens.

**`login_attempts` gains a nullable `source` column**, applied by the
standard migration on first connection. Inert until the route passes a
source.

---

## 3. Open findings, by owner

### Backend

**SEC-01 (HIGH) -- the highest live risk on the board.**

    python -c "from core.mirror.standardise import rules_for, standardise as s; \
      print(repr(s('us-west ', rules_for({'type':'data'}))))"
    -> 'us-west'

A `Customer` whose source `region` holds a trailing space is invisible
to everyone before the pipeline and visible to every us-west user
after it. No audit entry. The same call was already made the OTHER way
for type coercion at `UNIFIED_ROADMAP.md:1290` and never carried
across. Full analysis, including the withdrawn `_security_value` proposal and
why `default=str` is the wrong shape there, is in
`FOR_BACKEND-security-attribute-in-the-pipeline.md` -- handed over out
of band, not on the branch. Everything load-bearing from it is
summarised above and in SEC-01's register row, so its loss would cost
detail rather than the finding.

**SEC-02 (MED) / SEC-03 (LOW)** -- `with_lineage()` spreads system
values AFTER the row, so a customer column named `_silo`,
`_source_table` or `_row_hash` is silently overwritten; a declared
field of that name crashes the gold build with an opaque `KeyError`. A
reserved-name check at load closes both and is worth doing regardless
of SEC-01.

**SEC-05 half two** -- `data_silos.yaml` is published VERBATIM into the
lake manifest. My half refuses the credential at load; yours would
redact on publish, catching a file edited after load.

**SEC-08 (INFO)** -- `/admin/mirror` row counts span every compartment
and an administrator has a MAC value too. `AGENTS.md` says a `GROUP BY`
pushed into SQL "would aggregate rows the caller cannot see" -- same
shape, opposite answer. Same question as R39 and R61.

**SEC-10 (INFO)** -- `test_sync_snapshot_semantics.py` fails
intermittently under full-tier load, passes 3/3 alone. Seen **three
times**. RULES.md 3: force the interleaving, do not race for it.

**F-13 / F-25** -- reassign or strike; both look already fixed. One
question nobody has asked: what happens to generation numbers after a
RESTORE from backup? etcd ships `--bump-revision` precisely so
"revisions are never decreasing after a restore".

**R52 rule 5** -- when imputation arrives, refuse a schema where a
type's `security:` field is also imputable. Nothing imputes today.

**Fold `FINDINGS_security.csv` into `AUDIT_CHECKLIST.csv` and delete
mine.** Identical schema, checked in code.

### Owner

**SEC-06 (HIGH)** -- `000COORDINATION.md`'s ownership table matches 89
of 145 source files. **56 match no rule**, including
`api/auth_dependency.py` (`get_current_user`),
`core/sqlite_connection.py` (the read-only authorizer),
`scripts/bootstrap_root.py`, `core/ontology/object_type_validation.py`.
This is why SEC-05 sat in a file nobody watched. The check is eight
lines and rebuilds from the method: take every backticked path pattern
in `000COORDINATION.md`, expand `/**` and trailing `/`, and `fnmatch`
every tracked `*.py` outside `tests/` and `ui/` against them; assert
nothing is unmatched.

**SEC-11 (MED)** -- `000COORDINATION.md` and `001SECURITY.txt` disagree
about whether `scripts/create_*_user.py` is security's. I edited those
files for F-30 on the authority of the one that lists them.

**SEC-22 (LOW)** -- `password_problem()` rejects any password
CONTAINING the username as a substring, and nothing enforces a minimum
username length, so a user named `e` cannot choose an ordinary
passphrase. **Recorded and deliberately NOT fixed: the remedy loosens
a security check**, and it needs a minimum username length decided
alongside.

### Mine, needing a design rather than a patch

**SEC-19 (MED)** -- a truncated `roles.db` silently hands authority back
to `policy.yaml` after a restart, restoring grants somebody withdrew.

    process 1: seeded -> ['admin', 'reader']
    (roles.db truncated to 0 bytes)
    process 2: load() -> None        <- use policy.yaml

**I built a fix and reverted it.** Refusing when the roles tables are
absent broke 13 integration tests, because `RoleChangeStore` SHARES
`roles.db` and "proposing creates the file without seeding it" -- so a
file with no roles tables is a NORMAL state. The right shape is a
startup integrity check against the audit trail of applied role
changes, not a guard inside `load()`.

**SEC-28 (MED)** -- `_refuse_cross_compartment` excludes CREATES from
its write set, so reading in one compartment and creating in another
is not detected as a crossing, while the identical flow via UPDATE is
refused. A create's compartment is knowable from its resolved changes.
Recorded not fixed: closing it changes that function rather than
adding a guard beside it, and SEC-27 already removed the
caller-chosen half.

**SEC-09 (LOW)** -- nothing calls `executor.shutdown(wait=)`. The
executor drains only because `/query` awaits its future. Correct today
and incidental; recorded rather than guarded because no path submits
without awaiting.

---

## 4. What was fixed here that was NOT on any audit list

Eleven of the sixteen closed rows came from reading files rather than
from a list. The ones worth knowing at integration:

**SEC-27 (HIGH)** -- a mutation could set a type's SECURITY field from a
caller-supplied parameter. The model composes parameter values and is
untrusted by this project's first principle, so the compartment of a
newly created object could be chosen by the least trusted component.
`_resolve_mutation_value`'s own comment named the hazard; nothing
enforced it. Latent -- no shipped action does it.

**SEC-05 (HIGH)** -- a plaintext database password was accepted at load
and published verbatim into the lake manifest.

**SEC-12 (MED)** -- a submission criterion comparing `amount` against a
bool PASSED, because `True < 1000`. A guard satisfied by a non-number.

**SEC-13 (MED)** -- one reviewer could approve over another's
rejection; `INSERT OR REPLACE` erased the refusal.

**SEC-14 (MED)** -- a proposer's `execute:` grant was never re-checked
at confirm, so an action revoked from a role after proposal could
still run.

**SEC-15 (MED)** -- the merge decision store leaked 54 file descriptors
per 100 calls, on a path `run_sync.py` takes every sync.

**SEC-21 (MED)** -- a corrupt password hash raised instead of returning
False, turning a uniform 401 into a 500: a username oracle louder than
the timing channel `DUMMY_HASH` exists to close.

---

## 5. Review status -- read this instead of any earlier claim

I previously wrote "14 of 14 files reviewed, the lane is closed."
**That was false**, and it is corrected on the branch as SEC-23. The
fourteen were files I had never TOUCHED; I treated the rest as
reviewed because I had been inside each for one finding. Touching a
file to fix one thing is not reading it.

Current, honest position over the **37 files this agent owns**:

    read end to end : 34 files
    partially read  :  3 files

The three, with what remains in each:

  - `core/ontology/write_mediator.py` -- decision paths all read
    (authorisation, both MAC re-checks, criteria, all three apply
    paths, eligibility). Unread: `_apply_batch`, `_apply_one_update`,
    the resume family, `visible_action_types`.
  - `core/ontology/write_log.py` -- delete index, watermark,
    `superseded`, connections read. Unread: `edit_history`,
    `get_applied_changes_since`, `pending_changes_for_ids`.
  - `core/pending_write_store.py` -- store, decisions, reservation,
    expiry read. Unread: `claim`, `duplicates_of`, `awaiting`.

All plumbing and query paths; no decision points among them. The last
five reviews produced one HIGH, one LOW and three verified-cleans -- a
declining curve.

---

## 6. Corrections I made to my own work, so you can weigh the rest

Three, all found by continuing rather than by anyone catching me:

  - **SEC-23** -- the false completion claim above.
  - **SEC-24** -- filed HIGH claiming the ordinary crash path left a
    deleted object readable. **Wrong**: both delete paths call
    `record_delete` BEFORE `mark_applied`, so the resume path indexes
    it and the sync is never load-bearing. My reproduction marked the
    row applied with raw SQL, which no product path does. Downgraded
    to LOW; the fix was kept because the bookkeeping inconsistency is
    real.
  - **SEC-25** -- the finding stands, but my recorded probe named
    `fields.<id>.data_type` when an id's type is declared as
    `storage.id_type`. Probe corrected.

Filing something is not the same as having verified it, and I did that
twice. The register shows both corrections in place rather than
quietly edited.

---

## 7. Two process notes worth keeping

**The delivery mechanism cost five handovers.** Patches sat unapplied
because the apply script was pinned to a single base commit and its
filename never changed, so a stale copy in `~/Downloads` looked
identical to a fresh one and refused correctly for the wrong reason.
Fixed by putting the batch range in the filename and proving
correctness by tree hash. **Delete old patches after each push** --
this recurred twice more even with versioned names.

**Three times the full suite corrected a premise my targeted tests
endorsed** -- SEC-19 (13 failures), SEC-14's first version (23
failures), SEC-27's first version (1 failure, on literals). Each time
the tests written alongside the fix all passed. That is the argument
for running both tiers rather than trusting a green subset, and it is
why gate numbers are quoted in every commit here.
