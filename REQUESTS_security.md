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
