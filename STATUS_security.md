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

## Where this leaves the list

    Closed, controlled      E-01  E-04  E-05  F-27
    Closed, not controlled  004-1        (control needs a file I don't own)
    Closed by measurement   E-08         (2,812 pass on a fresh clone)
    PARTLY closed, MINE     E-02         residual measured above

    Reproduced, open, mine  F-30  F-21  004-8
    Need one measurement    F-05  F-12b
    Not yet triaged         F-33 F-13 F-12a F-25 F-08 R50 R52

**F-30 remains the most severe genuinely-open item**:
`create_colleague_user.py` has no `--yes-this-is-development` guard at
all, where `create_debug_user.py` refuses without one. It creates a
known-password account unconditionally.

---

## What I did not check

- `./lint.sh` and the integration tier whole. No source change has been
  committed, so neither has had anything to judge.
- A 422 on query parameters (E-01).
- 004-1's control.
- Whether F-05 reproduces under forced interleaving.
- Both probe scripts were throwaway and are deleted; `git diff` is clean.
