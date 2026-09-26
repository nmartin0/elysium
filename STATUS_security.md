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

## Session 5 — F-12b CLOSED

**F-12b reproduces, and the claim was false in both halves.** The
comment said "a STRUCTURALLY read-only connection besides -- it
couldn't delete even if it tried". I wrote a row through the same
helper, then deleted it. Commit `2dbece9`.

`connection()` reaches `open_connection()` with `read_only` defaulting
to False, and it must: `connection_with_schema()` runs the schema and
migrations through the same handle, and `record_failure()` writes
through it on every failed login. So it is not a flag somebody forgot
-- making it genuinely read-only needs "ensure the schema" separated
from "read", which touches every caller.

The test pins the truth in the direction that catches the false claim
returning: it asserts the connection CAN write, so a future change to
make it read-only fails and sends the author to the two dependents
instead of landing half a change.

    controls   is_locked_out deletes the row  -> 1 failed, 4 passed
               disable the read-only authorizer -> 1 failed, 4 passed
    gates      ./lint.sh clean, 8/8; 2,846 unit (+5); 442 integration

**PROPOSED, NOT BUILT:** a structurally read-only handle for the
pre-auth read path is real defence in depth. It is a design change
with two dependents, so it is recorded rather than started.

---

## Session 6 — F-33 CLOSED, and a delivery defect found

**F-33 measured by mutation rather than counted by reading.** Disabling
session expiry entirely -- every expired session valid forever -- broke
exactly ONE assertion in the repository, and the integration tier
noticed nothing:

    1 failed   tests/unit/test_session_store.py
    2,845      other unit tests passed
    442        integration tests passed

The new test is at the WIRE, not beside the first: a second unit test
on SessionStore would double the count and die to the same refactor.
After it, the same mutation fails 3 tests at two layers. Commit
`85c6e7b`. F-33's other half (the ownership check) was already closed
by the approvals work's `may_claim`, eight tests at two layers.

    controls   the original mutation      -> 3 failed, 7 passed
               refuse EVERY session       -> 2 failed, 1 passed
    gates      ./lint.sh clean, 8/8; 2,846 unit; 445 integration (+3)

**AND THE HANDOVER ITSELF WAS THE DEFECT.** Three batches failed to
reach the remote and the cause was my apply script, not the patches:
`~/Downloads` still held the FIRST batch, the glob took `0001` first,
`git am` said "already exists in index", `set -e` aborted, and nothing
later ran. Reproduced against a fresh clone. Fixing it, my first skip
check was also wrong -- `format-patch` WRAPS a long Subject, so a
hand-rolled `sed` read "...are already" for "...are already fixed" and
never matched. `git mailinfo` is git's own parser for that job.

A delivery script is a deliverable, and I had only ever tested mine
against clean directories -- never the messy one real use produces.

---

## Session 7 — F-05 REPRODUCED AND PINNED; the list is now blocked

**F-05 needs narrowing.** `record_query()` is already atomic. The gap
is the SEQUENCE in `api/routes.py:3378-3380` -- check in one
transaction, record in another, with a window between them. Measured:
at 19 of 20, two callers both check, both pass, both record, count
reaches 21. Commit `a0cf84d`.

The overshoot is BOUNDED at (callers inside the window) - 1. Agent
queries run through a pool of 4 by default, so the realistic worst
case is three past the limit -- a correctness defect, not an incident.

    controls   simulate the fix       -> 5 failed, 2 passed
               remove the transaction -> 7 failed
    gates      ./lint.sh clean, 8/8; 2,853 unit (+7); 445 integration

The fix needs `api/routes.py`, which I do not own, so it is filed in
`REQUESTS_security.md` with the proposed `try_record_query()`. I did
NOT add that method -- nothing would call it.

## Session 8 — the batch landed; R50 analysed

**PATCHES 0005-0014 ARE ON THE REMOTE** at `49bf6de`, tree-identical to
what was tested. All six new test files present. The cause of the
five-round blockage was found from one paste of terminal output: the
`apply-security-patches.sh` in `~/Downloads` was the BATCH-1 copy,
still pinned to `f6c5a0b`, refusing correctly and for the right reason
from the wrong script. Two design errors of mine: the script was
pinned to a single base commit, so it was guaranteed to be wrong from
its second use onward; and the filename never changed, so a stale copy
looked exactly like a fresh one. Both fixed -- the batch range is in
the filename now, and correctness is proved by TREE HASH rather than
by a pinned base.

**R50 -- A FEEDBACK-LOOP GUARD ON THE WRITE PATH. Analysed, not built,
and the structural finding is the useful part.**

THE LOOP, CONCRETELY, and it is the write-path half of CONCERN-3:
silver standardises on the way in (NFC, trim, collapse whitespace, per
patch 337). So a source row holding `"  Ada   Okafor "` is SERVED as
`"Ada Okafor"`. A form prefilled from the served value, saved by
somebody who edited a different field, proposes `name = "Ada Okafor"`
-- and the write path puts that into the SOURCE. The customer's own
row is rewritten by a transformation no person chose, attributed to a
person who never typed it.

NOTHING TODAY WOULD NOTICE. `_expected_current_values_for()` reads
through `self._adapter_mediator`, which is bound to the SOURCE, so the
lost-update check compares source against source and passes. The
proposed value is never compared against what the caller was SHOWN.

WHAT MAKES IT FIXABLE IN ONE FILE, which I did not expect: WriteMediator
already holds BOTH readers --

    self.mediator           the read DataMediator, which since patch
                            385 reads PUBLISHED GOLD
    self._adapter_mediator  its own internal DataMediator over the
                            WRITE adapters, bound to the source

so `proposed == served AND served != source` is answerable at proposal
time without reaching outside `core/ontology/write_mediator.py`. No
new plumbing, no cross-agent change.

THE SHAPE I WOULD PROPOSE, for agreement first because it changes what
a write DOES: treat a field whose proposed value equals the SERVED
value, while the SOURCE holds something different, as UNCHANGED, and
drop it from the sub_write rather than refusing the whole action. The
caller did not edit it -- they submitted back what they were shown --
so writing it is a no-op from their point of view and preserving the
source is the conservative reading. Refusing the action instead would
block a legitimate edit to a neighbouring field, which is the common
case.

TWO THINGS I HAVE NOT CHECKED, said plainly: I have not reproduced the
loop end to end against a synced deployment, and I have not measured
the cost of one gold read per updated field at proposal time. Both
belong with the build.

## Session 9 — 004-8 CLOSED

Built after the shape sat published on the remote without objection
and the instruction to continue came again. It is entirely within
files this agent owns. Commit `c4cca37`.

The finding was narrower and different in kind from what was reported.
Not a duplicated combination: RBAC is gated once upstream, MAC per
object, which is right. The real difference was ONE AUDIT SIGNAL --
`log_security_resolution_failed()`, called from exactly one place in
`core/`, inside `check_access()`. So the write path could not emit it,
and the same orphaned object gave the signal on a READ and silence on
a WRITE.

    fix        non-create MAC now goes through check_access();
               the CREATE branch deliberately does not, because
               check_access() cannot express "no row to consult"
    docs       access_control.py's absolute claim corrected, naming
               the one exception rather than deleted
    controls   restore the inline MAC    -> 1 failed, 3 passed
               route CREATE through it   -> 1 failed, 3 passed
               check_access always allow -> 3 failed, 1 passed
    gates      ./lint.sh clean, 8/8; 2,857 unit (+4); 445 integration,
               both tiers green with NO test edited

## Session 10 — R50 CLOSED. The list is complete on my side.

Built after the shape sat published on the remote and the instruction
came again. Entirely within files this agent owns. Commit `25e9158`.

    the loop    silver standardises on the way in, so "  Ada   Okafor "
                is SERVED as "Ada Okafor". A form prefilled from the
                served value and saved writes the pipeline's
                transformation into the customer's own row.
    the rule    different from the SOURCE, identical to the SERVED
                value -> drop that field. Equal to the source is a
                no-op and kept; equal to neither is a real edit.
    refused     an update left with nothing, rather than an empty
                change set reaching the write log (F-27's lesson)
    measured    2.7 ms added at proposal for one changed field, 7.8 ms
                for three, 26.0 ms for ten, against a 2.5 ms warm gold
                read. Per proposal, on a path that waits on a model.
    controls    remove the guard          -> 4 failed, 5 passed
                drop EVERY changed field  -> 5 failed, 4 passed
                compare the WRONG reader  -> 4 failed, 5 passed
    gates       ./lint.sh clean, 8/8; 2,866 unit (+9); 445 integration

TWO THINGS CAUGHT BY EXISTING GUARDS, not by me: an invented audit
verb (`write_skipped_echo:`) that test_grant_vocabulary_consistency
correctly reads as a grant no policy could ever grant -- it has its
own audit stage now; and `field` as a loop variable shadowing the
`field` imported from dataclasses, which ruff refused.

WHAT REMAINS IS NOT MINE. Every one of the nineteen items is closed,
verified-already-fixed, or waiting on a person:

    E-02 residual   remedy decision            -> owner
    F-05 fix        two lines in api/routes.py -> backend
    F-13, F-25      backend-owned files, both look already fixed
    F-08            core/ontology/submission_criteria.py has NO OWNER
                    in 000COORDINATION.md
    R52             policy, propose before implementing

## Session 11 — R52: the imputation policy, proposed

R52 asks for one and says to propose before implementing. This is the
proposal. Nothing here is built, and on purpose.

**MEASURED FIRST: Elysium imputes NOWHERE today.** Grepped `core/` for
impute/fillna/interpolate/fill_missing: no hits outside an unrelated
comment in `write_log.py`. The only missing-value handling is silver
mapping DECLARED sentinels ("N/A", "-", "unknown", "") to NULL, which
is the OPPOSITE of imputation -- it removes a fake value rather than
inventing one, and only where a deployment declared the sentinel.

**SO THE POLICY IS FREE TO ADOPT NOW,** which is the argument for
writing it before anything needs it. There is nothing to migrate, and
it constrains work that does not exist yet: GOLD-6's survivorship, the
FUSION matcher, and the whole R51-R63 statistical band. A rule written
after the first imputation lands is not a rule, it is a migration.

### The seven rules

1. **Never impute into served data.** Gold serves an observed value or
   NULL. An estimate is never substituted into the property a reader
   believes was measured.

2. **An estimate is its OWN declared property**, with its own name and
   its own classification -- never a silent replacement of the
   observed one. This is R38's value-kinds idea applied narrowly.

3. **Every imputed value carries provenance**: that it was imputed, by
   which method, from what inputs. A value indistinguishable from an
   observation IS an observation, to everybody downstream.

4. **The agent must never be handed an imputed value as observed.** It
   writes fluent prose from whatever it is given and cannot tell the
   difference -- and LB-1 already records that it computes figures in
   prose without a check.

5. **Imputation must never touch the security field.** THIS IS THE
   SECURITY-SPECIFIC RULE AND IT IS NOT NEGOTIABLE. MAC decides which
   objects exist for a reader; an estimated compartment is an invented
   clearance, and a row whose region was guessed is a row shown to the
   wrong people. `security` is declared per type and the guess would
   be invisible at the point it mattered.

6. **An imputed value is never written back to a source.** R50's guard
   already refuses to propagate the pipeline's own output into a
   customer's row; an estimate is the worse case of the same loop,
   because it was never anybody's data at all.

7. **NULL is a legitimate answer.** "We do not know" is information,
   and a pipeline that cannot say it will say something else instead.

### The precedent, which is unusually blunt

The audit's own Part II conclusion: a 2024 VLDB evaluation of twelve
automatic data-repair algorithms found MOST INTRODUCE MORE ERRORS THAN
THEY REMOVE, and its standing recommendation across the cleaning band
is "suggest, never infer" -- the same shape as the pipeline builder,
where the machine proposes and a person decides. R57 reaches the same
conclusion from the statistical side: conformal thresholds or none,
and P27 measured our own FUSION design auto-accepting about half its
merges wrongly on the fields enterprise tables actually have.

### What I did NOT do

No code. No enforcement. Rule 5 is the one I would want enforced
first, and it is a load-time check in the ontology loader --
`core/deployment_loader.py`, which backend owns -- so even that is a
request rather than a patch. Recorded here so the rule exists before
the first thing that would break it.

## Session 12 — F-08 CLOSED, and it was mine after all

I had recorded F-08 as blocked because its fix looked like it belonged
in `core/ontology/submission_criteria.py`, which `000COORDINATION.md`
assigns to nobody. `AUDIT_CHECKLIST.csv`'s own `where` column says
`write_mediator.py` — mine — and the checklist was right. I had
checked the symptom's location rather than the fix's.

**The precondition is an ORDERING, and it holds in one of the two
places criteria are evaluated.** At propose, required-ness is
validated before any criterion runs, so a rule guarding a required
parameter cannot be dodged by omitting it. At CONFIRM the two halves
come from different moments: `_criteria_for()` deliberately reads the
CURRENT definition while `pending.parameters` was captured under the
old one.

    stored parameters : {'employee_id': 'e1'}
    new rule          : amount less_than 1000
    verdict           : PASSED -- silently skipped

A rule added today is skipped precisely because the write predates it,
which is the opposite of what `_criteria_for` promises. No audit
report raised this; it came out of reading the precondition.

    fix        refuse at confirm when an absent parameter is one the
               CURRENT definition declares required; optional-absent
               is the legitimate skip and is left alone
    controls   remove the guard        -> 2 failed, 5 passed
               refuse on ANY absence   -> 2 failed, 5 passed
    gates      ./lint.sh clean, 8/8; 2,873 unit (+7); 445 integration

Commit `b33f929`.

## A mistake worth recording: I reset onto a stale remote

Starting this session I ran `git reset --hard origin/security` without
running `git log origin/security..HEAD` first, and destroyed the
commit carrying the security-attribute proposal (patch 0022), which
had not yet been applied on the other side.

RULES.md 19 exists for exactly this and names it as having already
happened twice. Recovered from the reflog and verified tree-identical
to what was shipped, so nothing was lost — but it was lost for a
minute, and only because the reflog had it.

## Session 13 — E-12 verified; my area is swept

E-12 ("no graceful shutdown; the executor is never drained") was the
last row in `AUDIT_CHECKLIST.csv` touching a file I own that I had not
personally verified. The roadmap records it tested by patch 326; I had
taken that on trust.

**Verified by control, not by the test's existence.**
`tests/integration/test_graceful_shutdown.py` runs the app under a
REAL uvicorn on a free port, starts a confirm that takes 1.5 s,
requests shutdown mid-write, and asserts the write and both audit
entries completed. Dropping `GRACE_SECONDS` from 30 to 0:

    assert outcome.get("status") == 200   -> FAILED

So the test genuinely observes the grace period rather than passing
regardless. E-12 is closed.

ONE THING WORTH KNOWING RATHER THAN REDISCOVERING: there is no
explicit `executor.shutdown(wait=...)` anywhere. The executor is
drained INDIRECTLY, because `/query` submits to it through
`run_in_executor` and the request awaits the future -- so uvicorn
waiting for in-flight requests waits for the executor work too. That
is correct today and it is INCIDENTAL: a future path that submits to
the executor WITHOUT a request awaiting it would not be drained by
anything, and nothing would object. Recorded here rather than guarded,
because no such path exists and PRINCIPLES.md 7 says not to build for
a caller that does not exist.

### The sweep is complete

Every row in the checklist whose `where` names a file this agent owns
is now closed with a control, or verified already fixed with a
control:

    F-08  F-12b  F-21  004-8  R50            fixed here
    E-01  E-04  E-05  E-12                   verified already fixed
    E-02                                     attack closed; residual
                                             measured and needs the
                                             caller's source identity

Nothing further is buildable inside this agent's ownership.

## Session 14 — FINDINGS_security.csv: the bugs, somewhere they survive

**THE PROBLEM THIS FIXES.** Ten findings originated on this branch
that no audit raised. Until now every one lived only in prose -- nine
sections of `REQUESTS_security.md` and a handful of commit messages.
Checked: NONE of them exists as a row in `AUDIT_CHECKLIST.csv`, and
"unowned" appears in it nowhere at all. A requests file is read once,
by one agent, and then merges into nothing. That is how a finding is
lost without anybody deciding to drop it -- the same failure
`BACKLOG.md` was created to end, and the same reason the checklist is
a CSV rather than prose.

`FINDINGS_security.csv` uses the **identical schema** to
`AUDIT_CHECKLIST.csv` -- `id,set,source,severity,claim,where,probe,
status`, verified equal -- so backend can append the rows rather than
transcribe them. Ten rows: 2 HIGH, 1 SEC, 3 MED, 2 LOW, 2 INFO.

**EVERY RUNNABLE PROBE WAS RUN before the file was written**, not
after:

    SEC-01  'us-west ' -> 'us-west'
    SEC-02  customer's _silo -> 'primary_sql'
    SEC-05  hunter2 still present after expand_secrets()
    SEC-06  secret_references named in 0 ownership lists
    SEC-09  0 hits for executor.shutdown

A probe that has never been executed is a guess with a prompt in front
of it (RULES.md 1), and a register of unrunnable probes would be worse
than no register.

WHAT IT HOLDS: SEC-01 the security field standardised; SEC-02 lineage
overwriting a customer column; SEC-03 a declared _silo crashing gold;
SEC-04 a criterion added after a write, skipped (FIXED here); SEC-05
a plaintext credential reaching the lake manifest; SEC-06 two unowned
files; SEC-07 E-02's residual and why a global cap cannot work;
SEC-08 whether manage:deployment is a MAC bypass for aggregates;
SEC-09 the executor drained only incidentally; SEC-10 a flaky
concurrency test reported twice.

ONE ASK OF BACKEND: fold these into `AUDIT_CHECKLIST.csv` and this
file can go. It exists because I may not edit that one, not because
two registers are a good idea -- and two lists is the exact failure
the project already knows about.

## Session 16 — first security review of the newly-assigned files

The owner assigned eight security-load-bearing files to this agent.
No security agent had reviewed any of them. `AUDIT_CHECKLIST.csv` has
exactly ONE unverified row against the set -- R14, already half closed
-- so the checklist was not going to find anything here. This is a
direct read, with every claim checked by running it.

**NO DEFECTS FOUND.** That is a result, recorded rather than left as
silence, so the next agent knows what has been looked at and does not
repeat it.

### What was checked, and how

**`api/auth_dependency.py` -- can any route skip the session gate?**
Counted rather than eyeballed: 56 routes declared, 53 depend on
`get_current_user`. The three that do not are `/login`, `/logout` and
`/health`, all documented and correct. The `must_change_password`
allow-list is exact-match, so every near miss (a trailing slash,
different case, a `..` segment) fails CLOSED into the 403 rather than
out of it.

**`core/role_changes.py` -- is escalation actually prevented, and
WHEN?** This is the same class as F-08: a guard that runs at proposal
against state that has moved by approval. It is handled, deliberately,
and better than F-08 was. `approval_problem` re-runs at approval
against `latest_generation(request).config` -- NOT the request's pin
-- and passes `proposer_holds=_current_authority(...)`, so the
proposer's authority is re-checked against CURRENT state. The code
carries its own account of finding the pin "quietly defeating" the
lock. The escalation rule itself follows Kubernetes' `escalate` verb,
checks the AUTHOR as Kubernetes checks the requester, and considers
only what a change ADDS. `decide()` does its check-then-act in one
statement (`AND status = 'pending'`), which is the shape F-05 was
missing one layer up.

**`core/ontology/object_type_validation.py` -- is deny-by-default
real?** The project claims to be stricter than both lakehouse vendors
here, so the claim was tested rather than believed:

    declares security    -> accepted
    NO security block    -> REFUSED: Object type 'Customer' has no
                            security block declared.

It holds.

**`scripts/bootstrap_root.py`** -- `secrets.token_urlsafe(24)`,
printed once, no hardcoded default. Correctly needs no
`--yes-this-is-development` guard, which is why F-30's tripwire globs
`create_*_user*.py` and excludes it. Worth knowing and not a defect:
it passes `mac_value=None`, so the first admin can see no objects at
all until given one -- fail-safe, and undocumented.

### Not re-derived

`core/sqlite_connection.py`'s read-only authorizer was executed by an
earlier reviewer against `ATTACH` and `PRAGMA writable_schema` and
held. That is a negative control somebody already paid for; this
review did not repeat it.

## THE BRANCH IS BLOCKED, and it is not a code problem

`origin/security` has been at `a29594d` for FIVE consecutive rounds.
Eight commits of verified work sit unapplied. Two delivery defects
have been found and fixed in that time (a glob that ate stale patches,
a subject parser that mis-read wrapped lines), and neither has been
shown to be the remaining cause, because no terminal output from a run
has come back.

NOTHING FURTHER SHOULD BE STACKED until one batch lands. Every
remaining item is a decision, another agent's file, or both:

    F-05 fix      needs api/routes.py           -> backend
    004-8 fix     needs a nod on the shape      -> owner
    E-02 residual needs a remedy decision       -> owner
    F-13, F-25    live in backend-owned files   -> backend
    F-08 R50 R52  policy, propose before build  -> owner

---

## Where this leaves the list

    Closed, controlled      E-01  E-04  E-05  F-27
    Closed, not controlled  004-1        (control needs a file I don't own)
    Closed by measurement   E-08         (2,812 pass on a fresh clone)
    PARTLY closed, MINE     E-02         residual measured above

    DONE, controlled        F-30         pushed as d992843
                            F-21         commit 39f2a94
                            F-12a        commit 6e3b413
                            F-12b        commit 2dbece9
                            F-33         commit 85c6e7b
    DONE, controlled        004-8        commit c4cca37
    Reproduced and pinned   F-05         commit a0cf84d; fix needs
                                         api/routes.py -> requested
    DONE, controlled        R50          commit 25e9158
    PROPOSED                R52          seven rules, session 11
    DONE, controlled        F-08         commit b33f929
    Owner decision          E-02 residual, F-13 and F-25 (backend files)
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
