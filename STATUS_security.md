# STATUS_security.md

Agent: security (LLM3). Branch: `security`, from `dev` at `f6c5a0b`.

---

## Session 1 — triage before building. Nothing fixed, because nothing needed fixing yet.

**THE FIRST FOUR ITEMS ON MY LIST ARE ALREADY FIXED, AND HELD BY
CONTROLS.** E-02, E-01, E-04 and F-27 were all reproduced-against
rather than taken at their word, per step 2. Each is fixed in the code,
each has a dedicated test file, and I broke each fix deliberately to
confirm the tests are not decorative.

Environment: a clean clone of `origin/security`, no seeding, no sync,
dependencies from `requirements.txt` on Python 3.12.3.

### The controls, and what each cost

| Item | Fix in code | Test | Control applied | Result |
| --- | --- | --- | --- | --- |
| E-02 | `core/auth/limits.py` (128 / 1024), enforced `api/routes.py:1038` and `core/user_directory.py:128`; expired rows deleted in `record_failure()` | `tests/integration/test_prelogin_bounds.py` | raised both bounds to 10**6 | **2 failed, 11 passed** |
| E-01 | `api/app.py:174` `RequestValidationError` handler dropping `input`/`ctx` | same file | changed the filter to drop nothing | **3 failed, 10 passed** |
| E-04 | `api/csrf_middleware.py:95` `secrets.compare_digest`, as bytes | `tests/integration/test_csrf_constant_time.py` | replaced with `!=` | **2 failed, 3 passed** |
| F-27 | exhaustive 3-way dispatch, `write_mediator.py:709-715`, plus `_resume_one_delete_entry` | `tests/integration/test_resume_deletes.py`, `tests/unit/test_find_fabricated_creates.py` | routed `delete` into the create branch | **2 failed, 10 passed** |

Every control failed the *specific* tests for its item and left the
others passing, so none of them is broken setup. Each file was restored
from a backup copy, never hand-edited back; `git diff` is clean.

E-04's two tests are source-level tripwires rather than timing tests.
That is the right shape and AGENTS.md says so — no timing test here can
be made reliable, so the mechanism is pinned at source instead.

**I did NOT re-derive the six negative controls an earlier reviewer
already paid for** (SQL injection through field and type names, the
engine-enforced read-only connection, the login timing channel at 0.7%,
lockout at MAX_ATTEMPTS, uniform denial, CSRF as middleware). Nothing I
did touches them.

### Two more, checked while I was there

- **E-05** — fixed. `api/app.py:260` sets `Permissions-Policy`;
  `tests/integration/test_permissions_policy.py` holds it.
- **E-08** — does not reproduce. The whole unit tier is **2812 passed,
  13 skipped, 0 failed** on a genuinely fresh clone, and
  `git status --porcelain --ignored deployment/` is empty afterwards, so
  both halves of E-08 (the failures and the writes) are closed. My
  worktree was *not* seeded by any setup script, which is the clean
  checkout the work list asked for.
- **004-1** — fixed. `lint.sh` uses `STATUS=1` at every step, including
  the lockfile check, and a comment at line 63 names the old `FAILED=1`
  bug.

---

## What IS open — reproduced, in my area, ready to work

Checked against the code, not against a list.

**F-30 — `create_colleague_user.py` has no safety guard at all.**
`create_debug_user.py` refuses to run without
`--yes-this-is-development` and explains why (a known password is a back
door). `create_colleague_user.py` has no argv check, no refusal, no
exit — it creates a known-password account unconditionally. This is the
most severe genuinely-open item on my list and I intend to take it
first unless told otherwise.

**F-21 — `entries_for_request()` loads the whole audit log.**
`core/intermediate_layer/audit.py:222` is `lines = f.readlines()`
followed by `lines[-max_scan:]`. `max_scan` bounds the parse loop, not
the read, so the bound does not do what its own docstring at line 197
says it does.

**004-8 — the single enforcement point is not single.**
`write_mediator.py:1000` calls `self._adapter_mediator._security_allowed(...)`
directly while `check_access()` is imported and used at 1425. Either
route it through `check_access()` or correct the claim in
`access_control.py`'s docstring — but the two must stop disagreeing.

**F-05 — the rate limiter still checks and increments separately.**
`is_rate_limited()` opens its own `connection()`; `record_query()` opens
a separate `immediate_transaction()`. Classic check-then-act. Not yet
reproduced under concurrency — and per RULES.md a concurrency test must
*force* the interleaving rather than race threads and hope.

**F-12b — needs one more measurement before I call it either way.** The
"STRUCTURALLY read-only" claim the audit flagged is still present at
`login_attempt_tracker.py:92`. It may now be *true* —
`core/sqlite_connection.py:132` does `set_authorizer(_deny_all_writes)`
when `read_only=True`. I have not yet confirmed which way the tracker
opens its connection. Saying so rather than guessing.

Not yet triaged: F-33, F-13, F-12a, F-25, F-08, R50, R52.

---

## What I did not check

- The integration tier. I ran the unit tier (2812) and the five test
  files covering my first six items. I have not yet run
  `pytest tests/integration` whole.
- `./lint.sh`. Not run this session — no source change was made, so
  there was nothing for it to judge.
- Whether F-05 reproduces under real concurrency.
- Anything outside my ownership map.

---

## One inconsistency worth recording

`write_mediator.py:707` says F-27's pre-fix behaviour was that a DELETE
"fell into the **update** branch". `UNIFIED_ROADMAP.md:570` and the
audit both say it fell into the **create** branch and fabricated a
`create` entry. There are two dispatch sites (a batch-level one at
:678, an entry-level one at :710), so both may be true of different
sites — but as written, one of the two descriptions is wrong, and the
`find_fabricated_creates.py` script only makes sense for the create
story. Recorded, not resolved; it changes no behaviour.
