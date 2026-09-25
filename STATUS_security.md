# STATUS_security.md

Agent: security (LLM3). Branch: `security`, from `dev` at `f6c5a0b`.

---

## Session 1, CORRECTED. One of my four "already fixed" calls was wrong.

My first report said E-02, E-01, E-04 and F-27 were all closed. That was
based on: the fix present in the code, a dedicated test file, and a
control that made the test fail. **That evidence was not sufficient, and
the owner was right to doubt it.**

A control proves a test is coupled to the line you broke. It does not
prove the original attack is closed. For three of the four it was; for
**E-02 it was not**. Recorded here in full, because the wrong claim is
more useful than the corrected one alone.

---

## E-02 — PARTLY closed. The residual is measured, unauthenticated, and mine.

**The audit's specific attack is dead.** Ran it against the real login
route and measured `credentials.db` on disk, not a row count:

    10 requests, 20,000-char usernames + 200,000-char passwords
      credentials.db : 45,056 -> 45,056 bytes   (delta 0)
      login_attempts : 0 -> 0 rows
      every response : 401 "Invalid username or password"

From 16.3 MB to zero bytes. That half is genuinely fixed.

**What is NOT fixed is the class.** The bound is on field LENGTH. Nothing
bounds the NUMBER of distinct usernames inside one 15-minute window, and
the expiry `DELETE` only removes rows already past `WINDOW`. Measured:

    400 requests, distinct usernames of LEGAL length (108 chars)
      credentials.db : 45,056 -> 167,936 bytes  (delta 122,880)
      login_attempts : 0 -> 400 rows
      ~307 bytes per row

      extrapolated over one 15-min window:
        at   100 req/s ->  ~28 MB
        at 1,000 req/s -> ~276 MB

Still unauthenticated, still just the login endpoint. A ~5,300x
reduction per request, which is real — and not the same as closed.

**The fix is constrained by a decision I must not break.** Keying
`login_attempts` by the RAW username is deliberate: it stops throttling
from revealing which accounts exist. So "only write a row for a username
that exists" is not available. The remedy has to be a global bound — a
row cap with oldest-first eviction, or per-source throttling ahead of
the tracker. That is a design choice; **proposing before implementing.**

---

## E-01, E-04, F-27, E-05 — confirmed closed, harder than last time

**E-01.** Nine shapes across five endpoints, hunting for the secret
anywhere in the response: flat body, nested dict, deep list, wrong
types, `/api/me/password`, `/api/users`, an unknown route, a query
string, and a 5 MB oversized body. **No leak in any of them.** Errors
carry only `loc` and `msg`; the oversized body gets a bare
`413 {"detail":"Request body too large"}`.
*Not exercised:* a 422 on query parameters — the route I tried returned
404 before validation, so that shape is untested by me.

**E-04.** `secrets.compare_digest` on bytes is the **only** token
comparison in the entire tree — grepped `api/` and `core/` for any `==`
or `!=` against a CSRF token and found none. Exemptions are safe methods
and `/api/login` only, which is correct: login has no session yet.

**F-27.** There are **TWO** dispatch sites, and my first control only
covered one. Both are now controlled:

    entry-level (:710)  delete -> create  ->  2 failed, 10 passed
    batch-level (:673)  delete -> create  ->  2 failed,  5 passed

One of the tests is named `test_and_the_log_records_a_delete_not_a_create`,
which holds the fabrication claim directly. Closed at both sites.

**E-05.** Now controlled, which it was not in my first report: removing
the header line gives **3 failed, 1 passed**.

**I WAS WRONG ABOUT AN INCONSISTENCY.** My first report flagged the two
F-27 comments as contradicting each other — one saying a delete fell
into the `update` branch, the other into `create`. They describe two
DIFFERENT dispatch sites, each accurately. There is no inconsistency and
the comments are correct. Correcting it here rather than leaving it.

---

## E-08, 004-1 — unchanged, with the gap named

**E-08** does not reproduce: **2,812 unit tests pass, 13 skip, 0 fail**
on an unseeded clone, and `git status --porcelain --ignored deployment/`
is empty afterwards. Both halves closed.

**004-1** reads fixed — `lint.sh` uses `STATUS=1` at every step and a
comment at :63 names the old `FAILED=1` bug. **NOT CONTROLLED:** the
control needs lockfile drift, which means editing `lint.sh` or
`requirements*.txt`, both backend-owned. Reading it is the most I can
honestly do.

---

## Session 2 — F-30 CLOSED

**F-30 was worse than its one-line claim.** It is described as
"`create_colleague_user.py` bypasses `create_debug_user.py`'s safety
guard". It does not merely bypass it -- it creates *the same account*,
`debug` / `a` with every grant the deployment defines, so the guard on
the other script was advisory rather than enforced. Reproduced, fixed,
tested, three controls run, all gates green. Commit `e909f9f`.

    reproduction   create_debug_user refuses; create_colleague_user
                   creates debug/a AND colleague/a, no flag
    fix            the guard, on the script that lacked it, before it
                   touches a deployment
    also fixed     create_debug_user ran its role check BEFORE its
                   guard, so a run certain to refuse still loaded a
                   deployment and created a directory. Found by my own
                   test, not by reading.
    test           tests/unit/test_development_guard.py -- globs
                   scripts/create_*_user*.py and calls each main(), so
                   a FOURTH script is covered the day it is written.
                   Asserts row counts, not exit codes.
    controls       guard removed      -> 3 failed, 11 passed
                   never refuses      -> 3 failed, 11 passed
                   ALWAYS refuses     -> 1 failed, 13 passed
    gates          ./lint.sh clean, 8/8 contracts; 2,826 unit passed
                   (+14); 442 integration passed; deployment/ clean

**NOT DONE, DELIBERATELY:** the guard now exists in
`core/auth/development_only.py` with ONE caller. Converting
`create_debug_user.py` and `create_e2e_users.py` to it breaks a
backend-owned word-in-source test. Filed in `REQUESTS_security.md`
rather than fixed into passing. The behavioural tripwire covers all
three either way, so the consolidation is tidiness, not safety.

---

## Session 3 — F-21 CLOSED

`entries_for_request()` bounded the PARSE and not the READ, and said
so in a docstring that was the opposite of true. Commit `39f2a94`.

    measured    100,000 entries  634 ms /  26.6 MB -> 633 ms / 0.3 MB
                400,000 entries  981 ms / 105.3 MB -> 628 ms / 0.3 MB
                800,000 entries 1440 ms / 210.3 MB -> 631 ms / 0.3 MB
    fix         _tail_lines() walks back in 64 KiB blocks, rejoining a
                line that straddles a boundary
    test        COUNTS BYTES READ -- timing is flaky and a memory
                threshold is a judgement call; bytes read is the
                property and it is an integer
    controls    restore readlines()       -> 2 failed, 9 passed
                ignore max_scan           -> 3 failed, 8 passed
                drop the remainder rejoin -> 1 failed, 10 passed
    gates       ./lint.sh clean, 8/8; 2,837 unit (+11); 442 integration

THREE THINGS I GOT WRONG, all caught by running rather than reasoning:
the property is "bounded by max_scan", not "stops at the first match",
so at the default cap a correct read is still ~10 MB; entries come
back OLDEST first, deliberately; and vulture found a constant in my
own test file that nothing used.

---

## Session 4 — F-12a CLOSED, and 004-8 analysed

**F-12a closed**, commit `6e3b413`. The audit said the docstring omits
`manage:deployment`; it omitted THREE -- `manage:roles`,
`manage:escalation` and `manage:deployment`. Fixed at the root: the
heading states no count at all, and the literals are no longer a
second list beside `EXACT_GRANTS`. Four controls fired, including one
that caught my own test being wrong -- it looked for the words
anywhere and so fired against the corrected file, because the
docstring deliberately quotes its former wrong claim.

**004-8 ANALYSED, NOT BUILT -- and it is narrower and different from
what the audit describes.** The claim is that `WriteMediator` calls
`_security_allowed()` directly rather than `check_access()`, so the
documented single enforcement point is not single. What the code
actually does:

    RBAC is gated ONCE, upstream, at write_mediator.py:1183 --
    authorize(user, roles, "execute:<Action>"), logged with
    mac_allowed=None, raising on refusal.

    MAC is gated PER OBJECT in _authorize_sub_write (:982), which
    receives the already-decided rbac_allowed purely so its per-object
    audit line is accurate. By the time it runs, rbac_allowed is
    always True.

So it is not two implementations of one combination. It is RBAC at the
ACTION level and MAC at the OBJECT level, which is the right shape --
the grant is about the action, and re-deciding it per sub_write would
be redundant.

THE REAL DIFFERENCE IS ONE LINE, AND IT IS AN AUDIT GAP THE AUDIT DID
NOT FIND. `check_access()` calls `log_security_resolution_failed()`
when a MAC denial turns out to be an object whose security value could
not be resolved AT ALL -- an orphaned MDO record, a genuine
data-integrity signal, distinct from an ordinary mismatch. The write
path does not. So the same broken object produces that signal on a
READ and produces nothing on a WRITE.

TWO OTHER SITES ALREADY SHOW THE INTENDED SHAPE. Approver eligibility
(:1420) solves the identical "a create has no object to check" problem
by branching to authorize() for create and check_access() otherwise,
and its docstring says reuse "means eligibility here cannot drift from
eligibility anywhere else". The proposer site inlines it instead.

PROPOSED, for agreement before building, because this is the write
authorization path:
  1. Route the non-create branch through check_access(), matching
     :1420. Gains the resolution-failure signal, and future-proofs
     against a third gate -- SECURITY_ARCHITECTURE's write-down check
     is exactly such a candidate and would otherwise reach reads only.
  2. Keep the create branch as it is: check_access() cannot express
     "no row exists to consult", and inventing a skip-MAC parameter
     for it would weaken the chokepoint to fix a docstring.
  3. Correct access_control.py's claim either way. Even after (1) the
     create branch bypasses it, so the absolute wording stays false.

Cost: check_access() recomputes RBAC per sub_write. Same answer,
already known True -- one dict lookup, not a query.

---

## Where this leaves the list

    Closed, controlled      E-01  E-04  E-05  F-27
    Closed, not controlled  004-1        (control needs a file I don't own)
    Closed by measurement   E-08         (2,812 pass on a fresh clone)
    PARTLY closed, MINE     E-02         residual measured above

    DONE, controlled        F-30         pushed as d992843
                            F-21         commit 39f2a94
                            F-12a        commit 6e3b413
    Analysed, needs a nod   004-8        shape proposed above
    Reproduced, open, mine  (none -- next is 004-8's build)
    Need one measurement    F-05  F-12b
    Not yet triaged         F-33 F-13 F-12a F-25 F-08 R50 R52

**F-30 and F-21 are closed** (above). Next is **004-8**: the write
path calls `_security_allowed()` directly at `write_mediator.py:1000`
while `check_access()` is used at :1425, so the "single enforcement
point" docstring and the code disagree. That one needs a call on which
side moves before it is written.

---

## What I did not check

- `./lint.sh` and the integration tier whole. No source change has been
  committed, so neither has had anything to judge.
- A 422 on query parameters (E-01).
- 004-1's control.
- Whether F-05 reproduces under forced interleaving.
- Both probe scripts were throwaway and are deleted; `git diff` is clean.
