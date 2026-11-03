# Planning history

**This file is history, not a plan.** Nothing here schedules work. It keeps,
word for word, what the single planning file `ROADMAP.md` held on 3 November
2026 that is no longer open work: its section 8 (the former planning file,
carried in full: the lake-encryption, compliance and agent-loop items, the
refactor plan with its target architecture, steps S0-S20, measurements M1-M14
and the facts carried from consumed documents), the table of where each
refactor step went, and the note on facts and judgement. Git holds every
earlier version of every planning document; `git log --follow docs/roadmap.md`
and `git log -- ROADMAP.md` find them.

Where things went:

- Open work, its status and the measurements still to take: `docs/roadmap.md`.
  Its Tier 0 items cite the step text below as `archive S<n>` when the
  line-level evidence (file:line, counts) is needed.
- Every decision (D1-D23, N1-N21 and the later ones), one entry each:
  `docs/decisions.md`. Where the text below says "decided", the decision file
  is authoritative.
- The security invariants I1-I8 are restated in `docs/roadmap.md` section 2;
  the table below is their original form with evidence tags.

Evidence tags such as `[A:14]`, `[O:21]`, `[S:23]`, `[R:90]`, `[P:96]` cite
research notes kept outside the repository. Paths such as `core/...` mean
`src/elysium/core/...` (the package moved in S2, commit 502d74ba). "This file"
and "section N" inside the text refer to the old `ROADMAP.md`.

---

## A. Where each refactor step went (old ROADMAP.md section 6.1, verbatim)



| BLK step | Here |
|---|---|
| S0 | DONE 3 November 2026: a1190049 (the roadmap), a9f99a0b (the rules) |
| S1 | PARTLY DONE: a91bcaa1 (controls anchored by content, moved/retired/ambiguous report), 0f83252b (vulture), 93b03f0b (import-linter contract for I2); the remainder is in T0.1 |
| S2 | DONE 3 November 2026: 502d74ba (packages moved into `src/elysium`) |
| S3, S4 | T0.2 |
| S5 | T0.5 |
| S6 | T0.6 |
| S7 | T0.7 |
| S8 | T0.8 |
| S9 | T0.10 |
| S10 | T0.12 (the exemplar), API-1 to API-10, the ADM API cards |
| S11 | T0.11 |
| S12 | T0.13 |
| S13 | T0.14 |
| S14 | REF-14A, REF-14B |
| S15 | T0.15, then REF-LLM |
| S16 | T0.4, then the CLI cards |
| S17 | T0.3 (paths, no fallback), INS-02 to INS-08 (changed by N1 and N10) |
| S18 | REF-18A, REF-18B, CI-07 |
| S19 | T0.1 (format, moved forward by N15), REF-19 |
| S20 | DOC-01 to DOC-08 |
| BLK item 1 | T0.9 (Q-KEY) |
| BLK item 2 | SEC-B, T0.7, OPS-06, ADM-22, Q-COMPLIANCE |
| BLK item 3 | T0.15, Q-MODEL, REF-LLM |

## B. Facts and judgement in the 3 November plan (old ROADMAP.md section 6.4, verbatim)

- **Facts** (with sources): the current state of install, configuration,
  scripts, routes and the UI (CS §1-3, checked on 3 November with `ls`, `wc`
  and `grep` as quoted); BLK's steps, invariants, decisions and measurements;
  the security findings' status as read in the code (§4.4, file:line given);
  the add-ons' asks (AST, HEL); the research findings cited in §2.2 (IS, CLI,
  CIO, each with its own sources).
- **Judgement**: the Tier 0 order and the move of the controls format, the
  CLI skeleton, the layout and the admin shell into it; every N decision; the
  card split and the waves; the defaults in section 5.
- **Estimates**: all sizes and durations. Tier 0's 6-8 months assumes one
  strong model working serially; the swarm's cards are about 129 days of work
  that can mostly run in parallel once their Tier 0 item is merged.

## C. Status line of the 3 November plan (verbatim)

**Status (3 November 2026).** Accepted. Tier 0 has not started; the owner says
when it does. S0, S1 (partly) and S2 are done (section 6.1 has the commits).

Card counts on 3 November 2026: MEAS 6, SEC 7, API 10, ADM 26, CLI 17, OPS 10,
INS 8, DOC 8, CI 8, REF 17, ADD 12: 129 cards, plus 15 Tier 0 items.

---

## D. Old ROADMAP.md section 8, verbatim

## 8. The refactor plan and the blocked items, kept in full

This section is the text of the former planning file, carried over word for word so that no measured fact, requirement or known limit is lost (its own rule: "a measured fact in a deleted file is a measured fact lost"). Sections 1 to 7 above are the order of work and win where they differ; this section is the evidence and the design detail they cite. A tag such as BLK S6, "item 1" or "item 4" means the part of this section that carries that name. Inside 8.4, "section N" means that numbered part of the refactor plan, not a section of this file. Retired mechanics of the old file (its "Blocked on" lines and its items 1 to 3 as the list of what waits on a person) are superseded by section 5.

### 8.0 How a document leaves


1. Every item in it is checked **against the code**, not taken at its
   word. The roadmap that preceded this file found SEVEN built things
   described as open, four of them still wrong when somebody later
   built against them.
2. What can be done is done, with tests and a control.
3. What cannot is moved here, with what it is blocked on and what
   would unblock it.
4. **Anything else in the file that is worth keeping moves into the
   code it describes**, as a comment beside the thing it explains. A
   measured fact in a deleted file is a measured fact lost.
5. The file is deleted, and every reference to it is rehomed.

Step 4 is the one that costs. `SCALABILITY.md` was cited six times
from `core/`, `adapters/` and `tests/`; those citations now carry the
numbers themselves.

Removing a document is not a licence to lose what it measured. The
simulator items, the module platform, the interface notes, the Triggers
and other consumed documents were removed on 3 November 2026 (S0 of the
plan under "Converge on precedent"): what each measured moved into a
comment beside the code it describes (`core/embeddings.py`,
`core/mirror/matching.py`, `core/ontology/mediator.py`,
`scripts/check_workers.py`, `ui/playwright.config.ts`,
`ui/src/blueprintSurface.test.ts`) or into `sim/docs/REAL_SOURCES.md`, or
it is carried in the roadmap item below. The record of what was consumed,
and when, is git history of the former planning file; every finding that came out of
them is a row in `AUDIT_CHECKLIST.csv`. `DEV_UI.md` is NOT consumed and
must not be deleted: it holds the measured palette, type scale and
density ladder the interface is built from.


### 8.1 Item 1: Who can read Elysium's copied data without going through Elysium


**REWRITTEN 19 October, with the owner.** This item was "PostgreSQL
row-level security for MAC": push the row check into the customer's
database so it held for any caller. It does not fit how Elysium works.
Questions are answered from Elysium's own copy (GOLD-9); the only thing
that touches the customer's database is the sync, which must read every
row to make a whole copy -- Fivetran tells its customers to grant its
account BYPASSRLS for exactly that reason. A policy in the source would
bind the sync and nobody else. The precedent draws the line the same way: its
restricted views enforce rows on the precedent's copy, at read time.

**What was built instead:** the sync now asks PostgreSQL whether
row-level security applies to its own account on each table, and warns
-- in the run and on System -> Server -> Mirror -- when it does, because PostgreSQL
with no policy for that account "returns no rows without raising an
error" and the copy would be silently partial.

**What remains, and is this item now:** the copy itself. The mediator
applies the row check to everyone who asks through Elysium; anyone who
can read the lake's files on disk gets past it. Today file permissions
(the sync warns on a mirror directory others can read) and disk
encryption are what stand in the way. Whether that is enough, or the
lake's files need their own per-compartment protection, is the
question.

**THE OWNER'S STATED TARGET, 26 October:** only Elysium reads the lake,
and the lake is portable -- an administrator can copy it for a backup or
a move to a new computer. The two pull against each other: files that
only Elysium can read are files an administrator cannot simply copy.
What exists: a dedicated service account with a 0700 directory, a
volume-encryption check, and encrypted backups
(`scripts/backup_deployment.py`, `restore_deployment.py`), which are the
portable form. What cannot be had: protection from root on the running
host, because Elysium must read the files to serve them. What could be
built: Elysium-held encryption of the lake's own files (pyiceberg
writes without table encryption, so this means encrypting around it),
and a documented, tested migration (backup, restore elsewhere, verify)
as the supported way to move.

**DECIDED 27 OCTOBER, by the owner:** Elysium-held encryption of the
lake's own files, with a key that only Elysium holds AND that can be
moved, so an installation can move and still read its lake while a
copied lake is useless without the key.

**THE SPIKE (27 October) says it can be done, and cheaply.** Every byte
pyiceberg 0.12 reads or writes goes through `FileIO.new_input(...).open()`
and `new_output(...).create()`, and a FileIO is a configuration property
(`py-io-impl`), which `open_mirror_catalog` already passes through
(`mirror.storage`). A prototype FileIO encrypting each file in 64 KiB
AES-256-GCM chunks (a per-file key wrapped by the master key, chunk
number in the nonce, a last-chunk flag against truncation) ran a real
table: 2,000,000 rows appended, scanned and filtered correctly;
data files, manifests and metadata JSON were all ciphertext, and a
unique email address appeared nowhere on disk, catalog.db included;
a wrong key, a flipped byte and a truncated file were each refused.
Cost on that table: write 0.49s against 0.42s, full read 0.16s against
0.12s. The prototype lives only in the session's scratch space; the build
is a proper module, not that file.

**THE SHAPE TO BUILD:** a master key held by Elysium outside the data
directory (a 0400 file, a KMS later), never in a backup beside the
data; a header per file holding that file's wrapped key, so ROTATING
the master key rewrites headers and not data; `export-key` and
`import-key` carrying the master key under a passphrase, which is the
portability; a migration (backup, restore elsewhere with the key,
verify) as the supported move; and Elysium refusing to start when
encryption is configured and the key is absent, rather than writing
plaintext.

**WHAT MUST BE SAID PLAINLY, and decided with the owner before the
build:** (1) LOSING THE KEY LOSES THE LAKE, and the changelog and bronze
are systems of record -- a source holds "now", not last March -- so the
setup REQUIRES a second copy of the key (a recovery key shown once,
checked back) before it will encrypt anything. (2) Root on the running
host can still read the key from the file or the process; this guards
copied files, stolen disks, backups and other accounts, not a hostile
administrator of the live machine. (3) ENCRYPTION IS REQUIRED FROM THE FIRST SYNC (decided with the plan
under "Converge on precedent", 3 November 2026): no installed lake exists,
so there is no path for turning it on for one. It lands after S7 (the new
state and lake layout); scripts that read lake files directly
(repair_catalog, the orphan-file remover) need the key too. (4) catalog.db
holds table names and file locations, not values; it stays a plain file
with the other private files.

**Blocked on:** the owner agreeing the two points above (the required
recovery key; the limit against a hostile administrator). Nothing else.


### 8.2 Item 2: Compliance: SOC 2, ISO 27001, HIPAA, and a penetration test

**Blocked on:** the owner, and on money and calendar time rather than
engineering.

Asked for directly. Four of the five things named are not engineering
deliverables and saying so once, here, is cheaper than saying it again
each time:

- **SOC 2** is an attestation a licensed CPA firm issues after
  observing controls operating. Type II needs a 3-12 month window.
  Most of what it tests is not code -- onboarding and offboarding,
  vendor management, risk assessment, incident response, change
  management.
- **ISO 27001** is a certificate from an accredited body and requires
  an ISMS: scope statement, risk assessment, Statement of
  Applicability against 93 Annex A controls, internal audit,
  management review. Roughly a fifth of it is technical.
- **A penetration test cannot be done by whoever wrote the code.** The
  value is an adversary who did not.
- **HIPAA has no certification.** There is no issuing body; "HIPAA
  compliant" means the Security Rule safeguards are implemented and
  the vendor will sign a BAA. The obligation attaches to the operator.

**The fifth was real engineering, and is DECIDED and BUILT (14
October):** the volume encrypts and Elysium checks
(`core/storage_encryption.py`, reported at startup); backups are
AES-256-GCM envelope-encrypted files with the key kept apart
(`core/encrypted_archive.py`). SQLCipher and field-level encryption
were weighed and not taken: they guard against the same
file-leaves-the-machine threat with more machinery, and neither can
reach the mirror, which pyiceberg writes without table encryption.
INSTALL.md's "Encryption at rest" has the reasoning and the sources.

All four frameworks test an overlapping set of technical controls, and
building them is worth doing on its own merits regardless of whether
an audit is ever bought:

    encryption at rest       BUILT: volume check, encrypted backups
    key management           the backup key is a file; a KMS is next
    session controls         idle timeout, absolute timeout, revocation
    password policy          enforced rather than advised
    access review            export who holds what grant, as of when
    audit integrity          tamper-evidence on the existing log
    backup verification      restore tested rather than assumed

Months, not a patch.

**THE REGIMES, ANSWERED 26 OCTOBER:** GDPR and UK GDPR, and HIPAA. THE
OWNER THEN ASKED FOR SOC 2, ISO 27001 AND A PENETRATION TEST TO BE
ADDED to the plan (26 October, later the same day). What that makes
mine: the technical controls below, the control mapping and evidence
each audit asks for, and the policies as drafts. What stays the owner's:
choosing a CPA firm, a certification body and an independent tester,
the budget, and the observation window.
For GDPR the engineering is largely built (erasure, retention,
encrypted storage and backups). For HIPAA it is the Security Rule
safeguards above, which the operator carries, and a BAA, which is a
contract and not a patch. The list's remaining rows are therefore not
optional: key management, session controls, a password policy,
access review, audit integrity and backup verification.

Erasure, for these audits, is the ledger and the `Erasable` registry of
S7 in the roadmap below: the adopt and vouch machinery, its typed phrase
and exit codes 2 and 3 are deleted there, not extended. Three limits of
the present design are kept as requirements of that step: the record never
narrows, so a column re-pointed from one type to another keeps the old
type and erasing it also removes rows of whoever now owns those values
(erasing too much is the lesser failure, and the output must say so); a
quarantine or cleaning record of a table several types keep rows in is
matched against each of those types' ids; and a gold join table whose name
two silos share is keyed by both silos' columns. While an erasure cannot
reach a table, every erasure is reported incomplete and `--write` refuses;
that stays.

The idle timeout, the audit hash chain and the access-review export ride on
S5 and S10 of the roadmap below.



### 8.3 Item 3: Agent-loop efficiency, context rot, and which model and server to ship


`IDEAS.md`'s open investigations all need traces from a real model on
real hardware. The measurements already taken are kept because
re-taking them costs an afternoon of somebody's GPU.

**The benchmark runs again after S15 of the roadmap below**, on the new
step vocabulary (one `Step` table that generates the prompt fragment, the
JSON Schema and the validator), so the unmeasured switches below are
measured once, on the code that will ship. The two commands at the end of
this item run against the present vocabulary and are only worth running if
S15 is far off. The method lessons below (a grep or a prompt theory is not
a measurement; the refusal message is what teaches the model) move into
comments beside the code when S15 lands.

**THE ANSWER WAS NEVER TIMED** (found 19 October): every run below
timed the loop's step calls and stopped, though the answer is prose
with no length limit and a person waits for it too. The bench now
writes each trial's answer and prints, per trial, where its time went
(`step 3 calls 96.0s (reading 12.0s, writing 84.0s for 126 tokens at
1.5/s); answer 1 call ...`), from the server's own durations; every
query logs the same line. `scripts/compare_models.py` puts models side
by side on it.

**TWO ANSWER SETTINGS, 19 October** (core/llm/agent_features.py): a
LIMIT on how long an answer may run, ON at 400 tokens -- a cut answer
says it was cut, from the server's own stop reason -- and
`brief_answers`, OFF until feature_bench's `brief` arm, which compares
answers written with and without it, says the answers are shorter and
still state every fact. The bench now grades the ANSWER too
(core.agent.evaluation.answer_states): it judged only what the loop
gathered, so an answer could drop the very value it was asked for and
pass. The step replies were left alone: they are already bare JSON with
no reasoning field -- 18 characters for a finish, 86 to 119 for a
search, a read or a count, as the bench cases write them -- and
shortening them means changing the step vocabulary, which a
measurement would have to justify first.

**The agent asks too many questions to answer one.** Observed, not
inferred: "how many transactions does Ada Okafor have?" took SIX
gathered entries across FIVE model calls, two of which fetched
`transaction_date` -- a field that answers nothing about how many
transactions exist. Roughly 75 seconds of a 443-second query spent on
data the question did not need.

> This is now the bottleneck, and it is a different one from where the
> week started. The loop is cheap per step and wasteful in steps.

**Aggregates not being chosen** is worth reading for its METHOD. It
was amended twice and both amendments kept, "because the reversals are
the useful part": the original blamed prompt wording, and a live run
then surfaced `unrecognized step 'aggregate_object', finishing`.

**Do the pre-flight action verdicts earn their keep?** Honestly
unresolved -- `_sub_write_validity_for_object` costs prompt tokens on
every hop and the loop already recovers without it. "There is no
evidence either way."

**BACKLOG.md specified the session that answers all of it**, and the
specification is the useful part because it is bounded: one harness,
one-shot calls against the real prompt, varying one thing at a time,
**about an hour of machine time** for four questions.

- Does the agent over-fetch, and would a different example change it?
- Are aggregates chosen when they should be?
- Do the pre-flight action verdicts earn their keep?
- Can a small model work without the schema in the prompt?

ITERATE rather than hand-writing three prompts and picking. It has
been unblocked since `aggregate_object` became reachable; what it
lacks is the machine.

**MEASURED 2026-10-11, on the deployment's own CPU model**, with
`scripts.llm_bench` (step mode, three trials each; plan mode, one):

| case | step | plan | how it failed |
| --- | --- | --- | --- |
| one_field, one_field_other_customer, typed_field, two_constraints | 3/3 | 1/1 | -- |
| link_fanout | 0/3 | 0/1 | step: asked for Transaction `cust_001` -- a Customer id -- until stopped. plan: list in a filter, then a wrapped handle |
| dependent_choice | 0/3 | 0/1 | step: the asymmetry nudge listed what each object HAD; the model re-read the complete one. plan: 26 steps against max_hops 8 |
| count_by_aggregate | 0/3 | 0/1 | step: asked for a FIELD named `count`, refused by get_object, then asked get_field, which silently returned None |

- **Are aggregates chosen? No, 0 of 4.** `aggregate_object` was
  described in prose and shown in no example -- and this file already
  records that this model does not infer a shape from prose.
- **Every failure was identical across trials** (temperature 0), so
  `--trials 3` buys nothing here; one trial per case is the measurement.
- **Prefix reuse works (AR-1's engine half).** Warm, the per-call time
  follows the call's POSITION, not its length: call 3 (6,818 chars) ran
  36 s against call 2's 56 s (6,684 chars), every trial. Seconds track
  what the model writes, not what it re-reads. The 383-1,210 s first
  calls are model loads, not prompts.
- One plan-mode call took 934 s, over the 600 s deadline -- a query a
  user would have seen fail.

**WHAT CHANGED IN RESPONSE**, each from one failure above, each in
`tests/unit/test_bench_failures_are_answered.py` replaying the bench's
own trajectory: a fourth worked example (a count); an id seen only as
another type's is refused with the link to follow and the aggregate
that counts; get_field refuses an unknown field as get_object does,
naming `aggregate_object` when the field looks like a count; the
asymmetry nudge names the missing (object, field) pairs and the one
step that fills them.

**RE-RUN THE SAME DAY with those changes, step mode: 5 of 7.**
link_fanout now PASSES -- the model took the link the refusal named.
Two still fail, differently:

- count_by_aggregate: refused "count", it asked for `transaction_id`
  -- the id field -- and was refused; it sent that step twice more and
  was told both times "You already have this". FALSE: a refused step
  gathered nothing, but its signature stayed in the duplicate guard.
  Fixed (a refused step's signature is forgotten, so a repeat is
  refused with its reason), and asking for the id field now says the
  ids are already in hand and names the aggregate.
- dependent_choice: the nudge said "1 lacks amount" and gave the step;
  the model sent it, and it was stopped as a DUPLICATE. Some earlier
  step had claimed it -- which one, the bench's summary could not say.
  `--show-steps` now prints every step and note per trial.

**THIRD RUN, with `--show-steps`: count_by_aggregate PASSES** -- refused
`transaction_id`, it read the hint and chose `aggregate_object`.
dependent_choice's trajectory showed the cause: nudged "1 lacks
amount", it read exactly that, then read it AGAIN and ran out of hops
holding a complete answer -- the nudge stayed in `Gathered so far` as
an instruction, and nothing said it was done. A genuine finish the
nudge postponed is now granted the moment its gap closes, and the note
is rewritten to say so.

Still visible in that trajectory and NOT addressed: the model read the
same two ids twice (the link, then a search), and read three fields in
three get_field calls where one get_object would do. Eight hops for a
three-hop question.

**AR-5 IS BUILT AND OFF** (`agent.constrain_steps`): every step reply,
and every plan, can be constrained to a JSON Schema generated from the
caller's visible schema. Every refused step above -- `count`,
`transaction_id`, `*`, a list in a filter, a wrapped handle, an
invented step name, a 26-step plan -- is outside it. Whether a 4B model
answers BETTER inside a grammar is the question; "Let Me Speak Freely?"
(Tam et al., 2024) found format restrictions hurt reasoning and not
structure, and a step is structure.

**FOURTH RUN, 2026-10-12: STEP MODE 7 OF 7, FREE AND CONSTRAINED.**

| arm | passed | wall clock | hops spent on refused steps |
| --- | --- | --- | --- |
| step, free JSON | 7/7 | 20.0 min | 2 (cust_001 as a Transaction id; `transaction_id`) |
| step, constrained (AR-5) | 7/7 | 32.7 min | 3 (cust_001; a date "2"; group_by a link) |

**AR-5 STAYS OFF, on that measurement.** Constraining did not pass
anything the free arm failed, and cost 60% more wall clock --
count_by_aggregate alone took 10 minutes against 3.4. The refusal
messages had already taught the model what the grammar would have
forbidden. Its two new refused steps were ones the schema ADMITTED and
the executor refused (a non-ISO date, a link as group_by); the schema
now forbids both, so a later run would be measuring a slightly better
grammar. The time cost is the finding to re-test, not the pass rate:
llama.cpp checks the grammar per token, on a CPU.

**PLAN MODE WAS NOT MEASURED.** Both plan arms timed out warming their
prefix -- three attempts of 1,800 s each -- straight after the step
runs; the plan prompt differs from the step prompt, so it is a cold
prefill, and the last one that completed took 1,210 s.

**FIFTH RUN, 2026-10-12: PLAN MODE MEASURED AT LAST**, once the cause of
every plan timeout was found -- not prefill but a RUNAWAY: uncapped,
the model wrote JSON until the 4,096-token window was full (1,210 s at
~1.5 tokens/s). JSON replies are now capped at 768 tokens and the
warm-up forced to `{}`: plan warm-up 8 s, against 30+ minutes.

| arm | passed | wall clock |
| --- | --- | --- |
| step, free JSON | 7/7 | 20.0 min |
| step, constrained | 7/7 | 32.7 min |
| plan, free JSON | 4/7 | 22.8 min |
| plan, constrained | 2/7 | 27.5 min |

**STEP MODE IS THE ANSWER ON THIS MODEL AND HARDWARE.** Plan mode was
meant to trade adaptivity for fewer, cheaper calls; here it made fewer
calls and was no faster (a plan call median 108 s against a step's
38 s, writing more per call), and lost three cases -- link_fanout and
dependent_choice on plan FORMAT (a list in a filter, a wrapped handle,
an invented step `linear_regression`), count_by_aggregate by finishing
without an aggregate. ReWOO's authors name exactly this: plan-then-
execute "may not be the best choice for tasks requiring high
adaptability".

**THE CONSTRAINED PLAN ARM IS NOT TRUSTWORTHY AS A MEASUREMENT.** It
still produced "a list of values in 'filter'" twice -- which the plan
schema cannot express, by test. So that schema did not reach the
sampler intact: Ollama most likely dropped what its grammar converter
could not compile (the `pattern`s on handles and plan ids are the
likeliest) without saying so. A grammar that is silently half-applied
is worse than none, which is one more reason AR-5 stays off. If plan
mode is ever pursued, the first step is `--mode plan --constrain
--show-plan --cases link_fanout` to see what the server enforced.

**CLOSED AS FAR AS THIS HARDWARE GOES.** The four questions above have
answers: the agent no longer over-fetches into failure (7/7); aggregates
are chosen when the hint says so; prefix reuse works (AR-1, verified);
and constraining replies does not pay on a CPU. Pre-flight action
verdicts and running without the schema in the prompt were not
measured.

**FOUR MORE ARE BUILT AND OFF, 2026-10-14** (`core/llm/agent_features.py`,
each under `agent:` in config.yaml): filter operators (F-18/LB-2), a
search-result cap (AL-3, below), a free-text `search_text` step
(LB-8), and a `remember` step honoured only when the question itself
asks (E-14). Off, the step prompt is byte for byte what it was --
measured by its sha256 before and after. `scripts/feature_bench.py`
runs one arm per switch plus a baseline of the new cases with all of
them off (25 trials, about 75 minutes at one trial each) and prints a
verdict per switch: ON only if no original case regressed and the
switch's own case passed in no more hops than without it.

**SIXTH RUN, 2026-10-14: THE FEATURE BENCH**, one trial per case, step
mode, free JSON, 273 minutes.

| arm | passed | failed, and how |
| --- | --- | --- |
| baseline (new cases, all off) | 1/4 | operators_range (invalid filter), free_text_surname (repeated an exact-name search), remember_preference |
| filter_operators | 5/9 | link_fanout, dependent_choice (repeated get_field), count_by_aggregate (invented step `count`), operators_range (wrote `{"lt": 0}` twice, after the refusal told it the forms) |
| search_result_cap = 1 | 6/7 | dependent_choice (repeated get_field) |
| free_text_search | 3/3 | -- (free_text_surname passes on, failed off) |
| remember_from_query | 2/2 | -- (remembered when asked; nothing remembered for an ordinary question) |

The bench's verdicts: **filter_operators OFF** -- solid, because
link_fanout and count_by_aggregate passed in the cap arm and failed with
the operator section in the prompt, so the longer prompt itself costs
cases; **search_result_cap OFF**; **free_text_search ON**;
**remember_from_query ON**.

TWO VERDICTS REST ON LESS THAN THEY LOOK. The ON arms re-ran two and one
of the original seven, and the operators arm shows a prompt section can
break cases it has nothing to do with -- free text and remember have
not been run against link_fanout, dependent_choice or
count_by_aggregate, nor ever TOGETHER. And the cap's only failure,
dependent_choice, failed the same way in the operators arm too; the
comparison is with 7/7 on 2026-10-12, not a baseline run today, so
whether the cap or today's run caused it is open.

AND THE RUN WAS ABOUT FOUR TIMES SLOWER than 2026-10-12: a step call's
median was 161 s in the baseline arm against 38 s then, prefix warm-ups
took up to 708 s, and two first calls passed the 600 s timeout -- queries
a person would have seen fail. Pass and fail at temperature 0 follow the
model's choices, not its speed, so the verdicts stand; the slowdown is a
finding about that machine (load, the Ollama version, keep_alive).

**SEVENTH RUN, 2026-10-15: THE CONFIRMING RUN**, at close to
2026-10-12's speed again (a later call's median 56-64 s).

| run | passed | failed, and how |
| --- | --- | --- |
| original seven, free_text_search + remember_from_query ON | 5/7 | dependent_choice (repeated get_field), count_by_aggregate (invented step `count`) |
| dependent_choice, everything OFF | 0/1 | repeated get_field, exactly as in every arm |

TWO FINDINGS. **dependent_choice fails today with everything off** -- it
reads Transaction 2's category, then asks for it again instead of
finishing -- so it is a regression since 2026-10-12 in the baseline, not
a cost of any switch, and the cap's only failure is explained: the cap
passed the other six. **count_by_aggregate is tipped over by a longer
prompt**: it passed in the cap arm and failed with the operator section
and with free text + remember, each time by inventing `count`.

WHAT WAS FIXED, 2026-10-15: an invented step name was turned into a
FINISH and answered with a generic nudge, so the model invented it
again. It is now corrected like an invalid step -- "There is no step
'count'... To count or total objects use one aggregate_object step,
e.g. {...}" -- under the same two-strike limit, and still counted as an
unusable reply. That is the mechanism 2026-10-12 credited ("the refusal
messages had already taught the model"), applied where it was missing.
It changes model behaviour, so it is measured before anything is
switched on.


**Two decisions that wait on the same machine** (merged from the former
owner-questions item, 26 October): `D1`, whether to switch phi4-mini to
Qwen3-4B-Instruct after the bench (the shipped config is still phi4-mini;
`python -m scripts.compare_models phi4-mini <other>` runs the bench's seven
questions on each and tabulates how many each got right and where a whole
question's seconds went), and `D2`, whether to stay on Ollama or run
llama-server (the OpenAI-compatible adapter already reaches it and reads
its timings; prompt caching (AR-3) and speculative decoding (AR-8) need
it, and llama.cpp's n-gram drafting (`--spec-type ngram-simple`) needs no
second model and suits replies that copy names and values out of their
prompt). They are ONE decision, "pick one stack", taken after S15, because
the roadmap keeps one inference server and one set of switches (D23).
Decided earlier and recorded in PRINCIPLES.md section 4: no question
leaves the VM (`D3`, `AR-9`), and no fine-tuning on Elysium's traces
(`D6`, `AR-10`).

**Context rot, and a 10,000-id search behind it** (merged from its own
item). A model's effective recall degrades as the context grows, well
before the hard limit, and the agent accumulates `gathered` across every
step and feeds it back each hop, so a query touching many objects gets a
worse answer before it errors. Where that begins has never been measured.
`MAX_SEARCH_SCAN` is 10,000 in `mediator.py`, applied by asking for
`MAX_SEARCH_SCAN + 1` so that "we stopped looking" can be told from "that
was all of them" (patch 502 recorded this as an unbounded search of
200,000 ids; that was wrong, corrected in patch 505). What is true:
`_step_search_object` appends the ids whole, 10,000 ids is tens of
thousands of tokens re-sent per hop against an agent that runs eight, and
`get_object` is bounded (`MAX_OBJECT_IDS = 20`) while search output is not.
`agent.search_result_cap` (off) shows the first N ids, the exact total and a
note naming `aggregate_object`. After S15 result size is bounded by
`pageSize` and the cap disappears into a constant (D23). What a measurement
must still answer is task completion against context size at the midpoint
of a task; and the `agentic_loop.py` comment beside `MAX_OBJECT_IDS` says
why a cap chosen without measuring is dangerous: told its limit was 20 when
given 32 ids, a real model "came back asking for TWO, then spent the rest
of its hops fetching one object at a time until the duplicate guard
stopped it".

**Open owner question, now part of S9:** `R47`, review of inferred
special-category data (health, religion and so on). HIPAA and GDPR's
special categories (declared under `Q1`) are the reason. The roadmap's
answer is a rule rather than a screen: an edit proposed on a
special-category field needs `approval: second_person`.

**Blocked on:** a machine with a capable model, and two runs --

    python -m scripts.llm_bench --features free_text_search,remember_from_query --cases count_by_aggregate
    python -m scripts.llm_bench --features none --cases dependent_choice --show-steps

The first says whether the correction rescues count_by_aggregate with
both switches on; if it passes, free_text_search and remember_from_query
ship, and search_result_cap (20) with them. The second prints every step
and nudge of the baseline regression, which is what diagnosing it needs.
Beyond that, nothing on this hardware: a GPU, or a larger model, would
reopen plan mode and constrained decoding.


### 8.4 Item 4: Converge on precedent: fewer mechanisms, one breaking refactor

**Owner decision, 2 November 2026: the two lists below are the roadmap. Owner
decision, 3 November 2026: the refactor plan is accepted as the roadmap, and
all 23 recommendations in its decision list (D1 to D23) are accepted.** It
replaces the phased plan that stood here.

Research into precedent (the reference ontology platform this project
models, and the other platforms that do the same job) found that Elysium's
skeleton is right and that its complexity comes from running several
parallel mechanisms per concern where precedent uses one general mechanism
each. The goal is a monolithic Python mini-clone of that precedent that is
more usable and maintainable and simpler without losing power.

**The owner's rule, 3 November 2026.** Nobody has an Elysium deployment, so
nothing is kept for compatibility: no migrations, deprecation periods,
freezes, shims or legacy formats. Any break is allowed if it makes Elysium
more usable and maintainable, and simpler without losing power. Each break
still lands with its tests and keeps the security invariants of section 2.

**Working rule: replace in place.** Each step deletes what it replaces in
the same reviewable unit, together with its callers, its tests and its
controls. There is no build-beside, no freeze and no transition window.
This is also written into AGENTS.md and PRINCIPLES.md section 8.

**How to read the evidence.** Tags such as `[A:14]`, `[O:21]`, `[S:23]`,
`[R:90]` and `[P:96]` cite line numbers of the research notes behind the
plan (API and UI, ontology and configuration, storage and operations,
roadmap scan, precedent architecture). Those notes are kept outside the
repository, as are the audit notes; code locations (`file.py:line`) were
read from them and drift as the tree changes. Every statement is labelled:
**F** is fact (measured, or read in a note or the code), **J** is
judgement, **E** is estimate, not measured. Counts re-measured on 3
November 2026: 1,166 `Control(` records in `scripts/check_controls.py`
(the 1,097 and 490 quoted elsewhere were stale), 488 unit and 111
integration test files (599 backend test files), 51 simulator test files.

What to delete, in ranked order (the original wording said "deprecate"; the
rule now is delete in the step that replaces it):

1. The seven separate approval queues, each with its own database and approval logic. They become one proposal pipeline, which is the single biggest simplification.
2. The two-step propose-then-confirm flow. It becomes one apply call with an approval policy set per action.
3. The separate routes for combining, comparing, freezing and saving sets. They become one object-set model.
4. The 17 schema preview/apply route pairs. They become one schema-change endpoint with a dry run.
5. The six trigger-condition modules. They become one condition-plus-effects model.
6. The enriched and predicted field kinds. They become functions that propose edits.
7. The ~10 overlapping value-quality vocabularies. They become value types plus one checks model.

What's missing, in ranked order:

1. API tokens and service accounts.
2. A versioned API with a published spec.
3. Composable object sets.
4. Validate-only and batch action calls.
5. Optimistic concurrency (ETags).
6. Single sign-on and multiple roles per user.
7. An automation that can propose an action.
8. Subscriptions to object sets.
9. A queryable action log.
10. An audit read API.

Kept, because they go beyond what precedent documents: per-person erasure,
the compartment write-down check, uniform denial, and re-checking the
approver's permissions at approval time.

**Goal and invariants that do not change.** Reduce the number of mechanisms
per concern to one, without losing any capability, and expose a standard,
versioned API that matches what precedent and the common open conventions
share. Writes only through actions; MAC and RBAC both required at
`check_access()`; uniform denial; authority never stored; single machine;
single tenant; SSE only; no historian; no question leaves the VM.

**Built before the plan, slice 1 of the v2 read surface (3 November 2026).**
`core/ontology/object_sets.py` is the object-set union (`base, filter,
union, intersect, subtract, searchAround, static`) and the filter grammar
(`eq, in, lt, lte, gt, gte, isNull, contains, startsWith, and, or, not`),
with named caps for depth, node count, `in` values and static keys. It
parses to a typed tree, checks it against ONE caller's visible schema (a
field the caller cannot read is refused in the same words as an unknown
one; a type the caller cannot read is the same 404 as an unknown type), and
evaluates through the mediator only: sets come from `search_object()` and
`search_around_from()`, values for filtering and sorting from
`field_values_for_ids()`, and both re-run `check_access()` on every id they
are handed. `api/v2/` serves `GET /api/v2/schema`, `GET
/api/v2/objects/{type}` and `/{pk}`, and `POST
/api/v2/objectSets/loadObjects`, `/count` and `/aggregate` (one exact
grouping; count, sum, min, max, avg over readable numeric fields), behind
the same session, CSRF check and generation pin as `/api`. Paging is
`pageSize` (default 100, max 500) / `pageToken` / `nextPageToken`; a token
is signed to the caller and the query and expires. Errors are problem
details with `errorName`, `errorInstanceId` (the request id) and
`parameters`; denial is a uniform 404.

**Known limits of the caller-facing reads, shared by v1 and v2 (third
review, November 2026).** Two things a caller can still infer, both because
they already hold for the existing search and trace:
1. A scan that reaches the scan ceiling (`MAX_SEARCH_SCAN`) where the row
   check could not be part of the query is reported by v1 as
   `scan_truncated` and refused by v2 with a fixed sentence. Either way,
   whether a type has more rows than the ceiling turns on rows the caller
   cannot see: one bit about the total, not about any row. The proper fix
   is to page the scan past the ceiling under a budget that does not depend
   on the data, so a set is either complete or refused for a reason fixed
   by its shape.
2. The timestamps of a request's trace. The trace lists only what the caller
   was granted, but each record carries a time, and a request that took
   longer than its visible result explains is a signal. The proper fix is to
   round the timestamps in the caller's trace (to the second, or to the
   request) or to omit them.
The request budget itself IS data-independent: `prepare()` charges each
leaf from the shape of the set (a search leaf is worth the scan ceiling, a
static leaf its keys) before anything runs.

**Still to build from the v2 read surface**, now steps S5 and S10: the set
kinds `reference` (a stored, named set that replaces saved views and
frozen sets) and `similarTo` (gated by its own grant); text operators
beyond `contains` and `startsWith` and filtering on computed fields;
per-type schema discovery, `expand`, link and history reads, search and
aggregate on objects, `objectSets/export`; aggregation groupings other than
exact (ranges, fixed width, duration) and distinct counts; a snapshot paging
mode; pushing more than text equality into the search so a filter over a
table larger than the scan ceiling is not cut short before it applies;
`/api/v2/openapi.json` served to authenticated callers (safe because type
names are path parameters), with the disabled `/openapi.json` unchanged.


---

#### Plan section 1. Target architecture (one page)

##### 1.1 Packages: one distribution `elysium` (src layout), one console script

| Package | Owns | Replaces today (F) |
|---|---|---|
| `elysium.metadata` | Typed, immutable `Ontology` model (types, properties, links, actions, functions, automations, checks, roles). Validators, import/export, versions and change sets. | Dict-and-mutate loader `deployment_loader.py:655` with 16 in-place passes `:715-756` [O:14]. `config_schema.py` with 143 fields typed `Any` [O:9]. `config_editing.py` 1,666 lines, `config_history.py` 276, `config_proposals.py` 141 [O:22]. |
| `elysium.access` | Principal (user, role set, security attribute, token scope). One `decide()` / `check_access()`. Label compilation. Visible schema. | `core/intermediate_layer/` (64 refs, 314 test files import it [O:167]) and `core/auth` user resolution (two resolvers [O:19]). |
| `elysium.audit` | Append-only JSONL with `v` and `category`. Read API source. | `intermediate_layer/audit.py` 826 lines, stored in the log dir and left out of the backup [S:146]. |
| `elysium.index` | Mirror: `pipeline/` (phases as data), `lake.py` (layer registry), `SyncSource` adapters, gold, erasure ledger. | `core/mirror` 16,308 lines in 58 files [S:15]. `scripts/run_sync.py` 1,374 lines [S:133]. Four adapters, two of which duplicate each other [S:138]. |
| `elysium.query` | Object sets, filter grammar, mediator facade, search, aggregate. | `object_sets.py` 977 lines (kept) [O:122], plus the read mediator. |
| `elysium.actions` | `apply(mode=validate\|propose\|execute)`, write mediator, write log, one proposals table, ETags. | 7 approval stores (1,487 lines) plus pending writes (903 lines) [O:21]. |
| `elysium.automation` | One `{condition, effects, recipients, grouping}` model on timers. Notifications. Object-set subscriptions. | 11 modules, 3,050 lines [O:25]. `live_updates.py` 228 lines [A:77]. |
| `elysium.checks` | `value_type` plus one `checks` list. Six result statuses. | 20 modules, 4,005 lines [O:23]. |
| `elysium.functions` | Registry with declared signatures. Two kinds: `query` and `edit_proposer`. | `core/functions/registry.py` (56 lines, two hard-coded entries) and the top-level `functions/` package, which is missing from `packages` [S:23]. Enriched and predicted fields: 8 modules, 2,118 lines [O:24]. |
| `elysium.agent` | Agent loop over `query` and `actions` (the same service layer, in process). One declarative step table. LLM adapters. | `agentic_loop.py` 2,195 lines, `AgentLoop` 1,576, step vocabulary written three times [O:27, O:154]. |
| `elysium.api` | `/api/v2` only. One router file per resource. `Call` context. RFC 9457 problems. OpenAPI exported at build time. | `api/routes.py` 10,644 lines, 141 routes [A:14-15]. |
| `elysium.apps` | Add-on server supervision, same-origin proxy, scoped tokens, built UI as package data. | `addon_servers.py`, `core/modules.py` 673 lines, `/api/addons` proxy [A:103]. |
| `elysium.cli` | `elysium <group> <verb>` with a shared `OperatorContext`. | 50 scripts, 19,042 lines; 130 `python -m scripts.` mentions [S:23, S:47]. |
| `elysium.db` | `schema.sql`, connection factory, `PRAGMA user_version` check. | 31 per-store `SCHEMA` strings. `connection_with_schema` and `add_column_if_missing` with 109 call sites [S:20]. |

Dependencies run one way (J): `metadata` <- `access` <- `query` <- `actions` <- {`automation`, `functions`, `agent`, `checks`} <- {`api`, `cli`, `apps`}. Enforced by import-linter contracts (pyproject already has 16 [A:158]).

The UI (`ui/`) stays an npm workspace and talks to the API only through a client generated from the committed `openapi.json` [A:53]. The simulator leaves the product package (section 5, D13).

##### 1.2 Application state: three SQLite files (recommended), plus the lake and the audit log

| File | Holds | Why separate (F) |
|---|---|---|
| `elysium.db` | All durable application state in one schema with one `user_version`: model versions (Option A), proposals, write log, users and credentials, notifications, saved sets, automations, timers. | Makes backup atomic. Today each database is snapshotted separately and the set is not mutually consistent (`backup_deployment.py:190-205`) [S:70]. |
| `erasure.db` | The erasure register, plus the key-column ledger (section 1.3). | "THE ONE STORE A RESTORE MUST NOT ROLL BACK" (`restore_deployment.py:164-193`) [S:65]. |
| `scratch.db` | Rebuildable, write-hot data: request metrics, login attempts, sync attempts, embeddings and column profiles (if decision D4 calls them caches). Not backed up. | `request_metrics.py:81-91` inserts once per request [S:66]. SQLite allows one writer per file. |

The notes disagree on the count. `[O:143]` proposes one `elysium.db`; `[S:64-67]` proposes three. Section 5, D4 sets out the one, two and three options.

The Iceberg catalog stays as pyiceberg's `SqlCatalog` [S:67]. Audit and lineage JSONL move under `state/audit/`, segmented monthly in process. They are included in backup and are never rolled back by a restore [S:147].

Each file is stamped with `user_version` at creation. On a mismatch Elysium refuses to start and prints the path with "delete this file". There is no migrator [A:97, R:293].

##### 1.3 Lake layout

- **Namespaces are layers** (F, [S:108]): `bronze`, `changelog`, `gold`, `gold_history`, plus `silver` only if it stays persisted (D9).
- **Tables** are `<silo>__<table>` in source layers and `<ObjectType>` in gold layers.
- **One module.** `elysium/index/lake.py` holds a `Layer` enum, `identifier()`, `layer_of()` and `iter_tables()`.
- **What this deletes:**
  - the silo-name prefixes, which have caused two recorded collision bugs (`lake_names.py:6-8, 44-50`) [S:110];
  - `RESERVED_SILO_*` and `NON_SOURCE_*`;
  - about 14 copies of the namespace walk [S:114].
- **Findings tables** (`quarantine`, `cleaning`, `gold_conflicts`) move to `elysium.db` if D10 agrees. In SQLite, erasing them is one DELETE instead of a rewrite, snapshot expiry and file deletion [S:116].
- **Erasure** reads a ledger of every `(silo, table, column, object_type, kind, link_target, first_generation)` ever mapped. The ledger is written when a generation is accepted and is never narrowed [S:94]. It replaces the per-table `elysium.erasure_keys` record and the partial/complete/adopt machinery [S:85-98].

##### 1.4 The ontology: a typed model, its authoring, and its versions

**Shape (F proposal, [O:63-66]).** Frozen pydantic models:

- `Ontology{types, links, actions, functions, automations, checks, roles}`
- `ObjectType{name, key, title, properties, security, backing, status, checks}`
- `Property{name, type, labels, value_type, derived, backing, status}`

The format changes are:

- `type:` means the data type.
- `derived:` is the only computed kind.
- Links are authored only as links.
- Expressions use `$param`, `$user.<attr>` and `$proposer.id`.
- Operators are the v2 grammar: `eq ne in lt lte gt gte isNull contains startsWith`.
- Every action carries `approval: none|confirm|second_person`.
- Grants are structured (examples at [O:194-283]).

Operator settings move to one file of about 10 lines, `elysium.yaml` [O:285-293].

**Authoring and versioning.** The notes present two options; the owner chooses (D1).

| | Option A: versioned data in the database (recommended, J) | Option B: canonical whole files |
|---|---|---|
| Source of truth | A `model_versions` row in `elysium.db`: `(version, parent_version, author, reason, content_json, status)` [O:89] | `model/` directory of YAML, one file per type, link, action and role set [O:181-192] |
| Change path | `POST /api/v2/admin/schemaChanges {changes[], dryRun}` and `elysium model apply <dir>`. Both create a proposal against `base_version`; a stale base is refused. | The UI writes a whole canonical file (PyYAML dump, sorted, no comments). The same proposal pipeline runs. |
| Git | `elysium model export <dir>` writes canonical YAML. An empty table is seeded from `model/` on first start. | Files are the history. |
| Deletes (F) | `config_editing.py` 1,666 (a change-set applier of about 200 lines remains), `config_history.py` 276, `config_proposals.py` 141, `role_store.py` 215, the ruamel dependency, the 9 preview/apply route pairs. About 2,000 lines net [O:93]. | ruamel and about 1,300 of the 1,666 lines [O:92]. |
| Keeps | One authority. Diff, restore and approve share one code path. Matches the precedent, where metadata is stored as data and YAML is only import/export [P:96]. | Hand edit plus reload stays possible. The dual sources stay: roles from file vs database (D9 of [O:45]) and users from file vs database (D10). There is a hand-edit race. |
| Risk | A write to the model DB can rewrite `security:` blocks. Mitigations: one audit event per version, and `manage:deployment` as the only writer [O:95]. | A load error loses its file:line only in Option A; no new risk here. |

**Identity: immutable ids vs names.** Today YAML names do the work of id, API name and display name at once, so a rename breaks stored data, audit rows and the write log [P:67] (J inference). The precedent separates three things [P:54-63]:

- an opaque immutable id,
- a client-facing API name,
- a display name.

Objects are identified by `(type, primary key)`, never by a global id [P:55].

Recommendation (J, D2): every schema element (type, property, link, action, function, role) gets a generated id at creation, `ely.<kind>.<uuid>`. Ids are stored in the write log, audit, proposals, saved sets and resolved grants. Names stay unique, user-facing and renameable through a change set. This is cheapest to do now, while nothing is stored. It fits Option A naturally; under Option B the files must carry the ids.

##### 1.5 One policy decision point

- **One entry point.** `access.check_access(principal, verb, resource)` is the only decision site (24 audited call sites today [A:158]). It ANDs MAC (one security attribute and labels) with RBAC. RBAC is the union of the user's roles; there are no deny rules [O:103].
- **Structured grants.** Grants are `Grant(verb, type, property)` tuples. `read` implies `discover`. There are no wildcards [O:283, O:335].
- **Same rules everywhere.** Submission criteria, label gates and derived-field gating all run on the union [O:106].
- **Who must go through it.** Reads, `apply`, approval, export, subscriptions, automations, functions and the agent. An import-linter contract forbids `authorize` outside `elysium.access` [O:324].

##### 1.6 One proposal pipeline

One `proposals` table [O:111]:

`(id, kind, subject, payload_json, base_version, proposer, state, decided_by, expires_at, reason, idempotency_key)`

- **Kinds:** `action`, `model_change` (absorbs role and config changes under Option A), `identity_merge`, `check_suggestion`, `function_edit`.
- **Shared code:** atomic reservation, expiry, four-eyes, re-authorisation at approval against the current generation, stale-base refusal, erasure hook.
- **Per-kind approval policy.** Each kind keeps the safeguard its old store had: escalation check, stale digest, reason required, compartment write-down, erasure respected [O:114].
- **API:** `POST /actions/{a}/apply`, `GET /proposals`, `POST /proposals/{id}/approve|reject` [A:71].

##### 1.7 One automation model

`automation {condition: {on: <ObjectSet>, when: added|removed|modified|threshold|schedule|combined}, effects: [notify|propose_action], recipients, grouping}`, running on `timers.py` [O:120, B:2701].

- Reminders become `schedule` automations.
- An automation's `propose_action` effect runs as a real owner account and always stages [O:122].
- Every condition is evaluated per recipient, under that recipient's grants.
- Subscriptions are an SSE stream of CloudEvents that carry keys, never values [A:78].

##### 1.8 One checks model

`value_type` expands into default checks. Each type has a `checks: [{target, kind, config, severity: moderate|critical, on_fail: warn|quarantine|refuse}]` list [O:134].

- Results take one of six statuses: passed, failed, warning, error, not_applicable, not_computable.
- Rule suggestions and unusual-value reviews become `check_suggestion` proposals.

##### 1.9 One CLI; packaging and install

| Area | Target | Evidence |
|---|---|---|
| CLI | `elysium serve \| sync \| lake \| user \| erase \| backup \| restore \| lint \| doctor \| init \| service install \| model \| contracts \| dev`. One exit-code table; report by default, change only with `--write`. | [S:45] |
| Packaging | `[project.scripts] elysium = "elysium.cli:main"`. The built UI ships as package data. Extras `[identity]` and `[dev]`. | [S:43] |
| Install | `pipx install elysium`, then `elysium init [--demo]`, then `elysium service install`. Two roots, `ELYSIUM_CONFIG` and `ELYSIUM_STATE`, with no relative fallback. | [S:153] |
| Dev tools | `check_controls`, the benches and the seeders move to `elysium dev` or `tools/`, outside the wheel. About 25 files and 14,000 lines leave the shipped package (E). | [S:50] |


---

#### Plan section 2. Security invariants that must survive every step

| # | Invariant | Proved by (test or control) | Where it can break | Steps at high risk |
|---|---|---|---|---|
| I1 | **Uniform denial.** An unknown or unreadable type, key, field or proposal looks exactly like a nonexistent one. | A byte-for-byte comparison of the 404 bodies for "unknown" and "denied", with no distinguishing audit write [A:160]. A parametrised test over the generated route table: a role with no grant and a role in the wrong compartment each get the unknown-response [A:159]. Per-endpoint "hidden == nonexistent" tests for schema, proposals and change sets [O:323]. | Porting v1's "200 with null fields" (`routes.py ~9309`) [A:160]. Typed errors that are more specific than "unknown". | S6, S9, S10 |
| I2 | **Authorization in one place.** | An import-linter contract: `api`, `agent`, `automation` and `functions` may import only the `query` and `actions` facades, never stores or adapters [A:158]. Only `elysium.access` may call `authorize` [O:324]. | A new v2 router reading storage directly. The multi-role union implemented twice. | S5, S6, S10, S15 |
| I3 | **MAC and RBAC on every read.** | The existing per-id `check_access` in `search_object`, `field_values_for_ids` and `search_around_from` [A:159]. The route-table denial test from I1. A model validator requiring `security` or an explicit `unrestricted: true` [O:325]. A compartment write-down test. Subscription keys filtered through `check_access` before they are emitted [A:83]. | Subscriptions, expand, links, export and history are each a new read path. `via:` chains resolved from the DB-stored model. Label and derived gating run per role instead of on the union [O:106]. | S6, S10, S12 |
| I4 | **Writes only through actions.** | A forbidden-import contract for write APIs in `api` except through `apply` [A:161]. A test that `model_versions` never writes object rows. A test that `edit_proposer` functions and `quarantine` checks land only through a system action in the write log [O:326]. | The approve route writing directly. Function proposers. Checks that quarantine. | S9, S13, S14 |
| I5 | **Re-authorisation at approval.** | Per kind: revoke the approver's grant between propose and approve, and approval returns the uniform refusal [A:162]. One test row per safeguard each old store carried, each cited by a control [O:114]. | The unified pipeline losing a per-store check: `may_confirm` (`routes.py ~10020`), `escalation_problem`, stale digest, `_refuse_cross_compartment` [A:74, O:114]. | S9 (highest) |
| I6 | **Erasure completeness.** | An `Erasable` registry, with a test that fails when a table with a data-subject id column is neither registered nor exempted [S:71, O:175]. A test that fails if any lake table's keys cannot be derived from ledger plus schema [S:101]. A table-driven `layer_of`/`iter_tables` test over every namespace the sync writes [S:114]. Keep the never-narrow union rule (`erasure.py:542-559`). | A forgotten store or namespace. The ledger written after the first sync that uses a mapping. `erasure.db` folded into the restorable database. | S7 (highest), S8 |
| I7 | **Read-only source access.** | A control proving that a write through the SQLite dialect of the SQLAlchemy adapter is refused. That adapter has no authorizer today (`sqlalchemy_adapter.py`, no `authorizer` or `mode=ro`) [S:140]. Keep `default_transaction_read_only` and the `READ ONLY` session for PostgreSQL and MariaDB (`sqlalchemy_adapter.py:235-278`). | The SQLite adapter fold (R7). | S8 |
| I8 | **No question leaves the machine.** | A test that the installed product has no adapter able to reach a hosted model (`claude_agent_sdk_adapter.py` moves to `elysium dev` benches) [O:162]. The existing no-outbound rule; no telemetry exporter. | The agent rewrite. The LLM adapter consolidation. | S15 |

Supporting invariants, carried by the same tests:

- **CSRF.** A cookie request without the CSRF header gets 403. A request with both cookie and bearer is refused. A bearer alone is allowed [A:165].
- **Constant-time compare and login throttle.** Kept in `test_csrf_constant_time.py`, and the throttle moves with the login route [A:168].
- **Pinned generation.** The scanner is extended to the whole tree [A:163].
- **No-store.** Set as the default in `Call` [A:164].
- **Audit.** Stays fail-closed and append-only [S:148].
- **The agent stages only.** Its handlers call `apply(mode=propose)` [O:155].

**Rule for every step (J).** A step may delete a control only together with the code it guards. Each step's review lists the controls it deleted, the controls it added, and which invariants (I1-I8) it touched. A step touching I5 or I6 gets a second fresh-reader review aimed only at that invariant.

---

#### Plan section 3. Ordered refactor steps

Each step is one reviewable unit of a few commits, and each deletes what it replaces. Line counts are F where they cite a note, otherwise E. Effort figures are J.

##### Phase 0. Mechanical moves that make later steps cheaper

**S0. Rules and roadmap reset (docs only). DONE, 3 November 2026.**
- Deleted: PRINCIPLES.md section 8 as written; the AGENTS.md section "Schema changes are breaking", its three-deployments premise and the fixture-schemas sentence; the "old spellings" message rule; this item's compatibility sentences ("additive", the build-beside phases, "Freeze the v1 routes"); the stale silver-drop recipe, the "Pending writes survive a restart" narrative and the development-state recovery narrative in CLAUDE.md; the consumed-documents tables and the items that were built.
- Replaced with: the rule that no deployment exists, so break freely, replace in place, no shims, migrations or transition periods, each break landing with its tests and keeping the security invariants of section 2. Without it, agents keep asking for authorization on every break [R:368].
- Tests: `tests/unit/test_roadmap_is_intact.py` no longer pins the consumed-documents table or the "Not blocked" heading.
- Risk: none.

**S1. Tooling preconditions. PARTLY DONE, 3 November 2026** (a91bcaa1 content anchoring and the moved/retired/ambiguous report, 0f83252b vulture decorators, 93b03f0b import-linter contract for I2; the rest is T0.1).
- Deletes:
  - the `check_controls` defect that remains: a control citing a test that does not exist must not pass (only the failed-exit-code half is built);
  - the 141 `_route` names in `vulture_whitelist.py` [A:132].
- Replaces with:
  - a runner that requires pytest's failure exit code and checks that every cited test exists;
  - content anchoring: when `path` no longer holds `old`, the runner searches the package for the unique occurrence and reports a control whose anchor vanished as "retired", needing an explicit deletion. Without this, the 1,166 records (`routes.py` alone holds 198) need hand edits after every move [S:24, A:174];
  - `ignore_decorators = ["@router.*"]` in the vulture config;
  - import-linter contracts for I2.
- Together with: nothing.
- Tests: the runner gets its own tests.
- Preconditions: none.
- Risk: low.

**S2. Package rename (rename only, no behaviour change). DONE, 3 November 2026.** Kept under `src/elysium/`: `core`, `api`, `adapters`, `functions`, `scripts` (regrouping into the section 1.1 packages is the later steps); `core/intermediate_layer` is now `core/access`; `elysium.cli` is a stub. Paths elsewhere in this file still say `core/...` and mean `src/elysium/core/...`.
- Deletes: top-level `core`, `api`, `adapters`, `scripts` and `functions` (`functions` is missing from `packages` [S:23]); the name `core/intermediate_layer`.
- Replaces with: `src/elysium/...`, with `intermediate_layer` renamed `access` [O:167]; a `[project.scripts]` stub.
- Together with: 743 files of imports [S:23]; 27 `mock.patch("core....")` strings [S:56]; 1,166 control paths, handled by S1's anchoring; pyproject import-linter layers (`pyproject.toml:189-204, 405-427`) [O:167].
- Tests: import lines only. 314 test files import `intermediate_layer` [O:167].
- Preconditions: S1.
- Risk: none to invariants. Do it with a script (libcst or sed) so the diff is purely a rename.

**S3. Pure subtraction of compatibility code**
- Deletes (F):

  | Item | Evidence |
  |---|---|
  | Tri-states D5-D8, D11, D13, D15: `write_targets` absent = all writable, `ingest_undeclared_columns`, `on_type_mismatch`, default module list, `read_from_mirror`, delete `mutations: []`, required agent keys. About 105-350 lines in total. | [O:41-51, O:148, O:314] |
  | `on_suspected_rename: serve_empty` | [R:158] |
  | The gold `DATA_AS_OF` fallback for older publications | [R:160] |
  | `DEFAULT_RETAINED_PUBLICATIONS` "0 = old behaviour" | [R:371] |
  | `MOVED_MODULES` (about 45 lines), its test class, and the 124-line e2e spec | [A:105] |
  | `add_column_if_missing` (30 call sites in 10 files) and 2 inline migrations (`core/auth/database.py:81,89`) | [S:19] |
  | Older-server optionals in the UI (`api.ts` 1088, 1233, 1238, 1244, 1698, 3105; `useInboxCounts.ts:59`; `typeHealth.ts:52,88`) and old localStorage keys (`Shell.tsx:48,71-75`) | [A:96, A:140-141] |
  | `scripts/split_ontology_bindings.py` 93 lines, `find_fabricated_creates` 88, `rebuild_deleted_index` 58 | [S:49] |
  | `label_enforcement` as a switch (it becomes always on) and `scripts/label_access_diff.py` | [R:258] |
  | `/me/visible-apps`, `/logout-all`, `countObjects`, `searchAround` and their routes (no UI caller, 100-130 lines) | [A:145] |

- Replaces with: safe defaults (`write_targets` absent means no writes); a `user_version` stamp per file with refusal on mismatch [A:97].
- Together with: `add_column_if_missing` and the `user_version` rule land in one commit [A:188].
- Tests: the migration tests and the tests of the "absent" branches are deleted.
- Preconditions: owner decisions D11 (`ingest_undeclared_columns`) and D15 (label enforcement).
- Risk: low. The `write_targets` flip is a security gain [O:150]. Do not delete `TestAdoptingALegacyTable`: it tests domain behaviour, not a shim [A:100].
- Size (E): about 700-1,000 lines out.

**S4. Test builders**
- Adds:
  - `make_ontology()` and model builders;
  - a parser in `tests/` only that turns `"read:Customer.email"` into structured grants (test tooling, not product compatibility) [O:105];
  - one `app_db` fixture [S:73];
  - a route-table test scaffold.
- Why: later steps then touch helpers instead of hundreds of literals. 120 test files mention `object_types`, 141 mention `storage`, 241 mention `allowed_actions`, and 250 touch `.db` paths [O:28, O:17, S:21].
- Preconditions: S2.
- Risk: none.

**S5. v2 plumbing, the OpenAPI spec, the client generator, sessions and tokens**
- Deletes (on v2, and never ported from v1): the per-route patterns of 138 `Depends(get_current_user)`, 153 `_generation()` calls, 93 `_no_store` decorators, 22 store builders and 50 try/except blocks [A:18, A:64]; the v2 problem handler's fall-through to v1's handlers [A:17]; `/logout` and the `/me/*` duplicates.
- Replaces with:
  - router-level `authenticated` with a three-route public router;
  - `Depends(require(grant))` on each route;
  - `Call.stores` and `Call.visible_type()`;
  - pure-ASGI middleware in one ordered list;
  - a request-id middleware;
  - a build-time `openapi.json` with a test that it is current;
  - the generated client skeleton with one middleware for CSRF, generation notice, 401 handling and problem parsing [A:53, A:62-65];
  - `POST/GET/DELETE /session`;
  - bearer API tokens (argon2id) and service principals, where token power = scopes AND grants [A:87, B:2688].
- Together with: the login UI and `scripts/check_workers.py` (`/api/login`, `/api/me`) [A:25].
- Tests: the CSRF and session tests; the route-table tests (auth required, grant listed, no-store).
- Preconditions: S2. Owner decision D20 (service principals) for the token half.
- Risk: **high on the session half (I2, CSRF)**. Keep constant-time compare. Never accept a bearer token and a cookie together [A:90].

##### Phase 1. The breaking core

**S6. Typed ontology, new format, roles and renames (one program, landed together)** (HIGH RISK: I1, I3)
- Deletes:
  - the raw-dict model and its 16 mutation passes;
  - 143 `Any` fields and about 16 `_resolve_*` functions (about 370 lines) [O:65];
  - `bindings.py` 155 lines, `_merged_with_bindings` 31, the wrapper handling (D1);
  - per-field link authoring (D3);
  - the `step_model` / `synthesis_model` split (D4, 40 lines);
  - the `object_reference` / `object_reference_list` duality (D12) and action-level `submission_criteria` (D14);
  - four of five operator vocabularies (D16) and the `type` vs `data_type` overload (D17) [O:37-53];
  - string-prefix grants and `_validate_one_grant` (141 lines) [O:101];
  - single `role_name` (173 lines, 135 test files) [O:18];
  - `policy.yaml users:` with `resolve_user_record` (17 call sites) [O:19];
  - `tools:` and the `tool:` grant (50 lines) [O:128];
  - any special message for a removed or renamed key: the strict-key check already says "did you mean" [R:343].
- Replaces with:
  - the models of section 1.4;
  - `UserRecord(user_id, security_value, roles: frozenset)`;
  - immutable element ids if decision D2 says so;
  - `property` as the authored word if D5 says so;
  - one user source (the credentials database);
  - a generated JSON Schema for editors;
  - `scripts/lint_deployment.py` (405 lines) reduced to a thin CLI over the same models [O:67].
- Together with: BC1, BC2, BC4 and the renames in one window [O:307-308]. A translation layer between old and new would itself be compatibility code. The four shipped configuration sets (ontology 867 lines, policy 554 lines [O:16]) are rewritten by script, and become two (templates and test fixtures) plus a generated demo [S:153].
- Tests: about 120 + 141 + 241 + 135 test files, overlapping, through the S4 builders. `object_type_validation.py` (556), `action_types.py` (799), `link_types.py` (227), `derived_fields.py` (372), `field_types.py` (582) and the readers in `mediator.py` (3,083) and `write_mediator.py` (2,570) are rewritten against attributes, not keys [O:69].
- Oracle: for each of the four old configuration sets, diff `visible_schema` and effective grants before and after the translation [O:81].
- Preconditions: S2, S3, S4; owner decisions D1, D2, D3, D5, D7.
- Risk:
  - every `security:`, `via` and classification block must survive the translation;
  - the escalation check must evaluate the union of roles;
  - an unknown role is logged and denied;
  - `discover` stays strictly weaker than `read` [O:106].
- Size (E): about 900 lines of validators deleted [O:316]. Effort 3-5 weeks [O:69].

**S7. Application state, lake layout, erasure ledger, audit directory (one design pass)** (HIGH RISK: I6)
- Deletes:
  - 32 database files and 31 per-store schemas, moved into `schema.sql`;
  - `connection_with_schema` and `_schema_verified` (about 90 lines);
  - `OWNED_DATABASES` (28 names) and its inventory test;
  - `internal_storage.py` (73 lines) [S:61, S:76];
  - the layer-in-silo-name scheme and `lake_names.py` (58 lines);
  - the reserved-name checks and about 14 namespace walks [S:108-114];
  - from `erasure.py`, the per-table `erasure_keys` record with its three decode forms and the adopt machinery: about 400 of its 1,319 lines [S:98];
  - about 150 of the 374 lines of `scripts/erase.py` (`--adopt*`, the typed phrase, exits 2 and 3) [S:98];
  - `_record_erasure_keys_before` (`routes.py:3299-3340`) and its 3 call sites;
  - `removal.py:167-182`;
  - the hand-written list of 9 stores in `forget_beyond_the_mirror` (`erasure.py:1244-1319`) [S:71];
  - the logrotate unit [S:148].
- Replaces with: the three files of section 1.2; `lake.py`; the ledger in `erasure.db`; the `Erasable` registry; `state/audit/` with `v`, `category` and monthly segments.
- Together with: R2, R3 and R4 land together. Ledger rows are keyed by the new identifiers, and the ledger lives in the new state layout [S:178]. Findings layers move to SQLite here if D10 says so. Only tables that survive S9-S13 are squashed; there is no deployment, so `schema.sql` is simply edited later [S:78].
- Tests: `test_erasure_removed_types.py` (580 lines) and `test_erasure_after_removal.py` (585 lines) are rewritten against the ledger [S:98]; 328 layer-name mentions in 61 test files [S:22]; 250 `.db` test files through `app_db`.
- Preconditions: S3 (`ingest_undeclared_columns` false makes "partial" impossible by construction [S:91]); S6 (identifiers and types); owner decisions D4, D10, D12; measurements M6 and M7.
- Risk:
  - the ledger must be written before any sync uses a new mapping, on every path: loader, `build_generation`, reload, restore and CLI;
  - keep the write log's read-only authorizer handle (`sqlite_connection.py:133`);
  - keep `incomplete` only for unreadable tables [S:101-103].
- Size (E): about 1,000-1,300 lines out.

**S8. Pipeline into the package, silver decision, source adapters** (HIGH RISK: I7)
- Deletes:
  - the pipeline living in `scripts/run_sync.py` (1,374 lines; `run_sync()` 336, `_build_gold` 260);
  - `IcebergMirrorSync.sync_table`'s 577 lines and 12 parameters;
  - the sync thread inside the web server (`routes.py:6003-6107`);
  - the api-to-scripts import (`routes.py:6103`) [S:133, S:57];
  - if silver becomes transient (D9): the silver layer, the `rebuild` flag, the `rebuilding` state, retype's drop-silver refusal and CLAUDE.md's "CHANGING A FIELD'S data_type NEEDS SILVER DROPPED" section [S:129];
  - `sqlite_adapter.py` (728 lines);
  - the six `_gold_only` stubs and the pushdown surface on source adapters [S:138-142];
  - `SQLiteWriteAdapter`, if D16 says so;
  - the `serve_empty` remnants.
- Replaces with:
  - `elysium/index/pipeline/` with `PHASES` and `after=` edges;
  - `elysium sync`, which the panel launches as a subprocess;
  - a `SyncSource` interface implemented by SQLAlchemy (including its SQLite dialect with an authorizer or `mode=ro`), CSV and REST;
  - `GoldConnector` as the only query surface;
  - gold provenance = bronze snapshot id + transform hash [S:126].
- Together with: R5 and R6 land together, because the stage boundary is the same code [S:179].
- Tests: 247 `sync_table` call sites in 92 test files; 61 imports of `scripts.run_sync` [S:134].
- Preconditions: S7; measurements M1-M5; owner decisions D9 and D16.
- Risk:
  - gold must never publish from a partial read (`iceberg_sync.py:1533-1545`);
  - erasures run before embeddings (encoded as an edge);
  - the read-only control on SQLite (I7).
- Size (E): 700-900 lines from the adapters [S:142]; silver is unmeasured.

**S9. One proposal pipeline, model versions, the schema-change endpoint, actions and proposals on v2** (HIGHEST RISK: I4, I5)
- Deletes:
  - 7 stores (1,487 lines) and the `pending_write_*` code (903 lines) [O:21];
  - `auto_execute`, `owner_may_approve_automation` and three "absent means" defaults (`action_types.py:557, 581, 620`) [O:112];
  - Option A deletions (section 1.4, about 2,000 lines) or Option B deletions (about 1,300 lines);
  - the 17 schema preview/apply pairs (`routes.py:1942-3533`) [B:2603, O:22];
  - v1 `/writes/*`, `/merge-proposals/*`, `/enrichment-recipes/*/decide`, `/prediction-proposals/*/decide`, `/admin/rule-suggestions/*/decide`, `/unusual-review/decide`, `/admin/config-proposals/*`, `/roles/changes/*` and direct `/actions/{a}` [A:70];
  - the UI's five decision-queue tabs and their clients (`app-approvals` 1,154 lines, `app-identity` 516, `app-inbox` 165) [A:73];
  - the Inbox slot mechanism [R:59].
- Replaces with: section 1.6; `POST /api/v2/actions/{a}/apply|applyBatch` (cap 20); `GET /api/v2/proposals`; approve and reject; `POST /api/v2/admin/schemaChanges {changes[], dryRun}` over the existing impact reports (`removal.py`, `used_by.py`, `who_can_see.py`, `role_impact.py`) [O:94]; ETags with 412 and 428; one Inbox list filtered by kind; the queryable action log from `write_log.py`.
- Together with: stores, routes and the Inbox UI in one step [A:73, A:185]. Model versions are a proposal kind [O:309].
- Tests: 68 non-test call sites and 123 test files for `propose_action` and `confirm_and_execute`; 130 test files that touch pending writes [O:113]; 35 config-edit test files [O:93].
- Preconditions: S5, S6, S7; owner decisions D1, D17 (per-action approval), D8 (deprecate-first).
- Risk: write the per-kind safeguard table first, one row per safeguard, each with a control. Approve calls the same write mediator, never a write of its own [A:74].
- Size (E): net 1,500-2,000 lines from the stores [O:111], plus the Option A or B deletions.

**S10. The rest of v2, resource by resource; v1 deleted; UI on the generated client** (HIGH RISK: I1, I3)
- Deletes: `api/routes.py` (10,644 lines, 185 classes, 114 `*Response` models, 129 helpers [A:43]); `api.ts`'s 104 hand-written types and 145 wrappers (2,500-3,000 of its 3,197 lines) [A:55]; `messageFromErrorBody`; 93 copies of `handleIfSessionExpired`; 21 unencoded interpolations [A:52]; `saved_views.py` (260) and `frozen_sets.py` (239) [R:174]; the `conditions` string/JSON duality (`routes.py:8913, 9101`) [A:117]; the `/api` mount (`app.py:799`).
- Replaces with: one router per resource (`api/v2/{schema, objects, object_sets, queries, notifications, users, roles, tokens, admin_*, addons, modules, health}.py`, models next to routes [A:131]); stored object sets (`reference` kind); `{data, nextPageToken}` on every list; the audit read API; `useApi` and `useAction` hooks [A:59].
- Order of commits [A:196]:
  1. schema, objects, objectSets (moves Browse);
  2. users, roles, sessions (Admin);
  3. stored sets;
  4. admin config and history;
  5. mirror, silos, system;
  6. shell, modules, add-ons;
  7. delete `routes.py` once it is empty.
- Together with: each resource lands with its v2 router, regenerated client, UI call sites, tests and the deletion of its v1 routes [A:184].
- Tests: 87 backend test files with 1,046 path literals; `test_api.py` (4,574 lines) split by resource; 18 files that monkeypatch `api.routes.*`; 76 UI test files; `api.test.ts` (919 lines) [A:24, A:206].
- Preconditions: S5, S9; measurement M9 for each resource.
- Risk: do not port v1's three denial conventions. The route-table tests from I1 and I3 must pass for every new route before the v1 counterpart is deleted.
- Size (E): net 5,000-6,500 lines from `routes.py` [A:46]; 2,500-3,000 from `api.ts`.

**S11. UI platform collapse (only if owner decision D6 says collapse)**
- Deletes: the indirection in the generic `shell/` package (4,947 lines, 14 test files [A:112]); import maps and CSP hashes; per-module bundles; `describeModule` overrides and `module.conformance.json`; `scripts/conformance_report.py`; safe mode; the module manager; `modules.yaml`; `SYSTEM_MODULES`; `MODULE_API_VERSION`; `compatibleFeed`; `_API_RANGE`; `ui/MODULE_API.md`; `ui/module-api.report.md` (1,808 lines) and its currency test [R:54-64, A:56, A:103].
- Replaces with: one SPA with route-level code splitting; the add-on server supervisor and proxy (kept); add-on permissions as plain config [R:384].
- Together with: S10's shell and modules resources; sim/panel rebuilt [A:57].
- Tests: the conformance suite becomes a shared page helper [R:56].
- Preconditions: S10 in progress.
- Risk: low to invariants. The proxy's "offered to you" check stays in one function [A:106].
- Size: the platform beyond `shell/` is unmeasured.

**S12. One automation model and subscriptions**
- Deletes: 11 modules (3,050 lines): triggers, declared_triggers, trigger_states, trigger_runs, trigger_windows, count_condition, projected_condition, reminders, deprecation_alerts (plus `deprecation.py` and the `deprecation_lead_days` key if D8 says so) [O:25, R:383]; `api/trigger_checks.py`, `api/reminders.py`, `api/deprecation_alerts.py`; `GET /api/events` with its hint vocabulary, `core/change_hints.py`, and `liveUpdates.ts` (107 lines) [A:77]; the add-on file outbox (150-250 lines), once scoped tokens exist [A:107].
- Replaces with: section 1.7; `PUT /subscriptions/{streamId}` and an SSE `GET /subscriptions/stream`, both built on sse-starlette; `/automations` and `/notifications` routers.
- Together with: the UI consumers of the hints (Browse refresh, Inbox badge) in one commit [A:187]; outbox removal together with add-on back-calls on tokens [A:186].
- Tests: 49 test files [O:25]; the live-update tests.
- Preconditions: S9 (`proposal.decided`, `propose_action`), S10 (object sets); owner decisions D18 and D19.
- Risk: I3. Keys are filtered per recipient before emission. The stream keeps a maximum duration so a revoked grant stops within minutes [A:79]. Notification bodies stay free of unreadable data.
- Size (E): about 1,500 lines net [O:316].

**S13. One checks model**
- Deletes: 20 modules (4,005 lines) of overlapping vocabularies; the field keys `constraints`, `on_violation`, `standardise`, `outliers`; the type keys `rules`, `dependencies`, `unusual`, `freshness` [O:23, O:133]; `rule_suggestions` and `unusual_flags` (already gone as stores in S9).
- Replaces with: section 1.8; a checks engine (about 800 lines, E); `check_suggestion` proposals.
- Together with: the silver and gold stages that call these (`expectations.py`, `standardise.py`, `outliers.py`, `integrity.py` 687, `freshness.py` 240) [O:135].
- Tests: more than 40 test files.
- Preconditions: S6, S8, S9.
- Risk: quarantined rows stay invisible to anyone without read access. The invisible-text and misleading-text refusals stay on the display path [O:135].
- Size (E): about 2,000 lines net [O:316].

**S14. Functions in place of enriched and predicted fields**
- Deletes: the `enriched:` and `predicted:` blocks and 8 modules (2,118 lines) [O:24]; scikit-learn and statsmodels as core dependencies (they become extras); the scripts `propose_prediction`, `compile_enrichment` and the `suggest_*` reports, unless the owner keeps those features [S:49]; inferred identity matching from the main line (to an add-on, per D14).
- Replaces with: the function registry with declared signatures and the kinds `query` and `edit_proposer`. Edits from an `edit_proposer` land as `function_edit` proposals through a system action [O:127]. The agent step `use_tool` becomes `call_function`.
- Together with: removal of the Inbox Enrichment and Predictions tabs (already merged in S9).
- Tests: 25 test files.
- Preconditions: S9; owner decision D14.
- Risk: I4. The "never a classified input" rule becomes a validator on the function declaration [O:129].
- Size (E): about 1,800 lines net [O:316].

**S15. Agent on the same service layer** (I2, I8)
- Deletes:
  - the agent's direct mediator calls (about 12 methods) [O:154];
  - the step vocabulary written three times (prompt text, `step_schema.py` 257 lines, validators);
  - `agent_features.py` (108 lines) with its six switches and the byte-for-byte prompt check [A:121, R:90];
  - `/query` with its NDJSON streaming and the 499 convention (`_answer_query` 229 lines, `_streamed_query` 67) [A:126];
  - `claude_agent_sdk_adapter.py` (300 lines) from the product [O:162];
  - the inference server adapter the owner does not choose [R:34].
- Replaces with: one `Step` table that generates the prompt fragment, the JSON Schema and the validator; handlers that call `query` and `actions.apply(mode=propose)` in process, which is the same service layer, not an HTTP loopback [R:341]; `POST /agent/sessions` and `/continue` over SSE; `filter_operators` as the public grammar; result size bounded by `pageSize`, so the search-result cap of item 3 disappears [R:100].
- Together with: QueryPanel (718 lines) [A:126].
- Tests: the agent tests; the bench on the new vocabulary (M11).
- Preconditions: S9, S10, S12 (one streaming idiom); owner decision D19 (which switches); a model machine for M11.
- Risk: the agent acts as the calling user; the step grammar is generated from the caller's visible schema; the re-verification after the answer is preserved [A:126, O:157].

##### Phase 2. Operations

**S16. One CLI**
- Deletes: about 17 operator scripts as separate entry points; 11 triple-setups; 130 mentions of `python -m scripts.` [S:47-54]; four user-creation scripts plus the ceremony of `--yes-this-is-development` (collapsed to `elysium user create --dev-fixture`); the developer recovery scripts, collapsed into `elysium dev reset` [R:365].
- Replaces with: section 1.9 and `OperatorContext`, which makes the `show_history.py:64` class of bug impossible [S:45].
- Tests: the script tests become CLI tests.
- Preconditions: S8 (the pipeline lives in the package).
- Risk: `erase` keeps `--write` gating and the sync lock [S:56].

**S17. Install**
- Deletes: `install/install.sh` (213 lines); `deployment/var`; `deployment/logrotate`; the demo-as-production template; the silent relative fallback in `resolve_runtime_paths()` (`deployment_loader.py:1752-1764`); the third environment variable (64 mentions) [S:152-154]; the install-inventory tests [S:166].
- Replaces with: `pipx install`, `elysium init [--demo]`, `elysium service install` (a unit file with `EnvironmentFile=` and `ExecStartPre=elysium lint`, plus sync and backup timers), and `elysium doctor`.
- Tests: the install tests are rewritten.
- Preconditions: S16, S7.
- Risk: `secrets_dir` stays at mode 700 [S:154]. Lake encryption (item 1 above) can now be required from the first sync, if the owner agrees [R:110].

**S18. Simulator and test layout**
- Deletes: `sim/` as part of the product tree's configuration (the shared `pytest.ini:8-25`, the mypy list, the vulture paths, 85 controls) [S:170].
- Replaces with: `packages/elysium-sim/` (own pyproject, own test job) or a separate repository (D13). Tests are split by cost (`tests/fast`, `tests/api`, `tests/lake`, `tests/live`) and run in parallel in CI after M10 [S:166].
- Preconditions: S2.
- Risk: none to invariants. Elysium must never import the simulator.

##### Phase 3. Cleanup

**S19. Controls regenerated**
- Deletes: `scripts/check_controls.py` as 9,726 lines of Python records [S:24], and the records whose target code is gone (150-250, E) [S:161].
- Replaces with: TOML under `controls/<area>.toml` and a runner of about 150 lines, kept as a dev tool. Records are anchored by exact string, with an optional marker [S:159].
- Preconditions: everything else is done.
- Risk: every invariant in section 2 must still have at least one control. A coverage table from I1-I8 to controls is part of this step.

**S20. Docs and planning file**
- Rewrites:
  - the planning file, which became this one (ROADMAP.md) on 3 November 2026: the cards and Tier 0 are the unfinished steps of this item, and section 5 holds what needs a person;
  - AGENTS.md, SECURITY_ARCHITECTURE.md and README.md (stale counts, and the `write:` grant at README.md:315, 426, 452-455 [R:312]);
  - INSTALL.md (619 lines, down to the CLI flow) [S:152];
  - `templates/README.md`;
  - the SDK docstring, and the add-on contract as part of the OpenAPI document.
- Risk: none.

---

#### Plan section 5. Decided (owner, 3 November 2026: all recommendations accepted)

One line each: the question and the chosen option. Conditional choices
say what settles them; the measurements are in section 6.

- **D1** Where the ontology lives: versioned data in the database (`model_versions` in `elysium.db`), with YAML import and export (option A). Blocks S6, S9.
- **D2** Schema element ids: immutable generated ids (`ely.<kind>.<uuid>`) for types, properties, links, actions, functions and roles; names stay unique and renameable; objects stay `(type, pk)`. Blocks S6.
- **D3** Storage bindings: inline `backing:` last in each type file. This reverses the 2 November "separate bindings file" decision. Blocks S6.
- **D4** State files: three (`elysium.db`, `erasure.db`, `scratch.db`), confirmed by measurement M8. Blocks S7.
- **D5** Naming: "property" (not "field") in the model, API and UI. Blocks S6.
- **D6** UI platform: "app" (not "module"); collapse to one SPA; keep add-on supervision, the proxy and scoped tokens. Blocks S10, S11.
- **D7** Roles: additive only, a union with no deny rules; escalation is checked on the union. Blocks S6.
- **D8** Schema evolution: drop deprecate-first and its dated alerts; keep the "used by" guard and the migration choices `drop_edits|move_edits|cast`. Blocks S9, S12.
- **D9** Silver: a transient stage between bronze and gold, if measurements M1 to M3 confirm; otherwise stays persisted. Blocks S8.
- **D10** Findings layers (quarantine, cleaning, conflicts): SQLite tables in `elysium.db`, if M6 shows they are small. Blocks S7.
- **D11** `ingest_undeclared_columns`: removed; the lake always drops undeclared columns. Blocks S3, S7.
- **D12** S3-style lake (`mirror.storage`, `durability.py`, `lake_permissions.py`): dropped; local lake only. Blocks S7.
- **D13** Simulator: an in-tree package with its own pyproject and CI job. Blocks S18.
- **D14** Enrichment, prediction and inferred identity matching: re-express enrichment and prediction as `edit_proposer` functions only if wanted when S14 is reached, otherwise delete; inferred identity moves to an add-on; deterministic identity and survivorship stay. Blocks S9, S14.
- **D15** Label enforcement: always on; `label_access_diff.py` deleted. Blocks S3.
- **D16** Write-back to a source database (`SQLiteWriteAdapter`): deleted, after M5 confirms nothing relies on it. Blocks S8.
- **D17** Approval: a per-action policy, `approval: none|confirm|second_person`; agent and automation calls are always at least `confirm`. Blocks S9.
- **D18** Automations: may propose an action (`propose_action` effect); it always stages and runs as a real owner account. Blocks S12.
- **D19** Email notices: content-free only, off by default. Blocks S12.
- **D20** Service principals: yes, as real user records with explicit grants; token power is scopes AND grants. Blocks S5.
- **D21** Security attributes: one for now; `UserRecord` holds a mapping so a second is additive later. Blocks S6.
- **D22** Path: keep `/api/v2` once v1 is gone. Blocks S5.
- **D23** Agent switches and server: `filter_operators` on; `search_result_cap` becomes a constant; the other switches are deleted unless M11 shows value; one inference server. Blocks S15.


---

#### Plan section 6. Measurements to take before specific steps

| # | Measure | How | Decides | Before |
|---|---|---|---|---|
| M1 | Silver derivation cost: wall time and peak memory for the largest table, compared with the whole sync. A known data point: 200 MB of a 650 MB peak for 200,000 rows held as dicts [S:128]. | Profile one sync on the simulator's largest table. | D9: is a transient silver affordable? | S8 |
| M2 | Readers of silver other than gold (`suggest_*`, `quarantine_report`, `profiles.py`, `duplicates.py`, `retype_count.py`). | A call trace during a full sync and the test suite, plus grep. | D9: what must read bronze plus transform, or gold, instead. | S8 |
| M3 | How often gold is rebuilt with no bronze change. | Count over simulator runs. | Whether a fingerprint skip (bronze snapshot plus transform hash) is needed. | S8 |
| M4 | Whether any production path reaches the pushdown methods on source adapters (`_clause_for`, `find_ids`, reverse links). | A runtime call trace over the API tests and a live run [S:139]. | Delete the query surface from source adapters. | S8 |
| M5 | Whether `SQLiteWriteAdapter` write-back is relied on (`write_mediator.py:621, 650, 950`). | Call trace. | D16. | S8 |
| M6 | Row counts and bytes of the quarantine, cleaning, conflicts and changelog tables on a realistic lake. | Simulator lake after a week of drift. | D10. | S7 |
| M7 | Rebuild cost of `embeddings.db` and `column_profiles.db`. | Time a rebuild. | Whether they go in `scratch.db` or `elysium.db`. | S7 |
| M8 | Write contention with one file: per-request inserts against the approval path. | Load test with and without `scratch.db`. | D4. | S7 |
| M9 | The real v1 caller set: dynamic paths and test helpers missed by the literal grep [A:220-221]. | Log every `/api/` path during the e2e and integration runs. | Whether each resource can be deleted in its S10 commit. | each S10 commit |
| M10 | Test durations. | `pytest --durations`. | The test split and pytest-xdist. | S18 |
| M11 | Agent quality and latency on the new step vocabulary (needs a model machine). | `scripts/llm_bench.py` after S15. | D23 and the stack choice in item 3. | after S15 |
| M12 | Controls that die with deleted code, counted per record. | Runner report after each step (S1's "retired" list). | The size of S19; checks that no invariant lost its last control. | every step, S19 |
| M13 | Callers of `pending_write_store.claim()` [A:144] and of `change_hints.py` outside `live_updates.py` [A:223]. | grep and call trace. | Whether either is deleted outright in S9 and S12. | S9, S12 |
| M14 | Recount of stale numbers. DONE 3 November 2026: 1,166 `Control(` records; 488 unit and 111 integration test files (599, not 604); 51 simulator test files. | Commands. | Accurate baselines in the commit messages. | S0 |

---

#### Plan section 7. Estimated size of the change

**Every figure in this section is an estimate (E).** The inputs are measured section sizes from the notes, not trial refactors. Product Python today is about 97,000 lines (core 60,238, api 14,639, adapters 3,355, scripts 19,042) [S:15].

| Area | Deleted | Added | Net | Source |
|---|---|---|---|---|
| v1 API (`routes.py` 10,644, F) | 10,644 | 4,000-5,500 | -5,000 to -6,500 | [A:46] |
| v2 plumbing | (about 600 lines of repetition never ported) | about 150 | — | [A:65] |
| UI `api.ts` (3,197, F) | 2,500-3,000 | generated code (not counted) | -2,500 to -3,000 | [A:55] |
| UI decision queues and live updates | about 2,000 (approvals 1,154, identity 516, inbox 165, `liveUpdates.ts` 107: F) | about 800 | about -1,200 | [A:73, A:77] |
| Module platform (if D6 = collapse) | `shell/` 4,947 (F) plus unmeasured parts | small | about -5,000 or more | [A:112] |
| Core: loader and validators | 600-900 | — | -600 to -900 | [O:68] |
| Core: config editing, history, proposals, `role_store` | about 2,300 | about 200 | about -2,000 | [O:93] |
| Core: proposal stores | 2,390 (F) | about 500-800 | -1,500 to -2,000 | [O:111] |
| Core: automation | 3,050 (F) | about 1,500 | about -1,500 | [O:316] |
| Core: checks | 4,005 (F) | about 800-2,000 | about -2,000 | [O:316] |
| Core: enriched and predicted | 2,118 (F) | about 300 | about -1,800 | [O:316] |
| LLM adapters and agent switches | about 400-550 | — | -250 to -550 | [O:163] |
| Migrations and compatibility branches | 700-1,000 | about 50 | about -800 | S3 |
| Erasure adopt machinery | about 550 | about 150 (ledger) | about -400 | [S:98] |
| State and lake plumbing | about 300 (`lake_names`, `internal_storage`, `connection_with_schema`, walks) | about 300 (`lake.py`, `db/`) | about 0 to -300 | [S:76, S:114] |
| Source adapters | 700-900 | — | -700 to -900 | [S:142] |
| Silver (if transient) | unmeasured | — | unmeasured | [S:129] |
| Scripts: deleted | about 240 or more (F for three scripts) | — | -240 or more | [S:49] |
| Scripts: moved out of the wheel | about 14,000 moved, not deleted (`check_controls` 9,726: F) | — | 0 | [S:50] |
| `install.sh` and logrotate | 213 or more (F) | about 200 (`init`, `service`) | about 0 | [S:154] |
| Simulator moved out | 33,069 moved (F) | — | 0 | [S:15] |
| **Product total** | | | **about -20,000 to -27,000 lines net (20-28% of product Python plus UI client code), about 47,000 lines moved** | |

**Files.** About 740 Python files see the rename (S2) [S:23]. About 300-400 product files change in substance. About 60 UI source files change import (63 import `shell-api` [A:56]).

**Tests.** Most of the 599 backend test files are edited at least mechanically, because the overlapping sets are large: 241 use `allowed_actions`, 250 touch `.db` paths, 141 mention `storage`, 135 use `role_name`, 130 touch pending writes, 123 call propose or confirm, 120 mention `object_types`, and 87 hold v1 paths [O:17-28, S:21, A:24]. About 2,500 test lines are rewritten in substance for erasure and the API split alone: `test_api.py` 4,574 split, the erasure tests 1,165 rewritten. Across everything, perhaps 20,000-35,000 test lines change. On the UI side, 76 test files are re-mocked [A:23]. Controls: 150-250 of 1,166 retire, about 50-100 are added for new guards, and all are converted to TOML in S19 [S:161].

**Effort (J).** About 6-8 weeks of focused work for S6-S9 alone, using the notes' figures: S6 3-5 weeks [O:69], S9 3 weeks [O:314]. S10 is the largest piece by line count [A:48]. The whole plan is roughly 4-6 months of sequential steps, with S16-S18 able to run in parallel after S8.


---

#### Facts and requirements carried from items removed on 3 November 2026

Items 2 (enrichment and statistics), 3 (modules), 4 (the interface), 9
(the UI kit), 10 and 11 (the simulator) and the consumed-documents tables
were built, and left this file by its own rule. What they measured and
decided, and that a step above must keep, is here; the rest is in the code
and in `sim/docs/REAL_SOURCES.md`.

**Requirements of S9, S10 and S12 from the add-ons (Astrolabe, Heliograph).**
Where both ask, the signal is strong; one asking is weak and waits. Ranked
for design: live push through the add-on proxy; the kit's time-series chart
(OHLC, zoom, several series); event subscription and triggers on arriving
data; audit for live data (per subscription, not per row); jobs (a record
with owner, state, progress, cancel and result, outliving the tab); source
terms and feed health as data; large results; secret references and add-on
data under backup. What an add-on's first slice found Elysium lacks: a way
to put objects in (idempotency key, retract); delivery of a confirmed
action back to the add-on; `user.user_id` and the approver as a mutation
value so `decided_by` can be stored; a single-step action for low-risk
single-user actions; a module declaring a gated resource and asking
whether a person may open it, the answer audited. Open owner questions:
whether paper positions and equity are Elysium objects or only a published
SQLite read as a silo (the decision so far: accounts, positions, signals
and decisions are objects, the equity history is a time series that
references the account). Already decided: a signal is an object a source
creates and "took it" and "skipped" are actions on it; Elysium governs
ACCESS to market data and does not hold the bars. Time-series reads that
exist: `duration` (ISO 8601, aligned as TimescaleDB aligns its buckets from
midnight on 3 January 2000, in the zone asked for, `core/periods.py`),
`time_zone`, `first` and `last` per bucket, the assistant's `period`, and
`measures`. Still to build: a declared time property per type, a tail
cursor, and `timeseries_ref` (points read through
`/objects/{t}/{pk}/timeseries/{field}/points`, authorised against the owning
object and proxied to the add-on; Elysium stores no series; not a type-wide
as-of read, because erasure drops older snapshots and gold keeps 30
publications). WebSocket pass-through and timer callbacks wait for an
add-on that calls them. The add-on contract also needs: `module.json`
`ontology:` fragments (schema only, never data, validated at load,
optional type-name prefix); add-ons calling `/api/v2` with scoped tokens,
ingestion as an action applied with an idempotency key; confirmed-action
delivery (an action may name a loopback add-on effect, invoked after
commit, best-effort, keyed by write id).

**What the add-on proxy must keep when the module platform collapses
(S11).** The server is started, watched, restarted with back-off (1 s
doubling to 60 s) and stopped (SIGTERM then SIGKILL at `stopSeconds`) by one
supervising worker chosen by flock, with another taking over if it dies;
standard input is a pipe whose closing tells the server Elysium has gone.
`/api/addons/{id}/...` forwards only for someone the add-on is offered to,
adds `X-Elysium-Identity` (a JWT, a secret per add-on per start, good for a
minute), never forwards cookies, `Authorization` or the CSRF token, never
returns `Set-Cookie`, and serves what comes back sandboxed. Event streams
pass (at most 8 open per worker, each ended after 10 minutes). Declared
permissions are granted as `module:<id>:<permission>` and shown by the role
editor; a grant from a module no longer listed is kept, grants nothing, and
is shown as such. Untrusted third-party code is a different question: module
federation is the wrong answer ("a federated module runs in your page, in
your origin"); the isolation layer is a sandboxed iframe (`allow-scripts`
WITHOUT `allow-same-origin`) speaking the same API as JSON-RPC 2.0 over
`postMessage`. A third-party data source is a silo and an ontology fragment
is data, not code. Measured when the shared-library import map existed:
sharing Blueprint's core and the router took the first load from 131 KB to
229 KB compressed, and sharing `@blueprintjs/icons` put 1.4 MB on every
first load. A conformance suite checks a page, and "a check on a page is a
check on everything the page mounts": a hand-over of an expired session
that a nested panel makes by itself hides a page that ignores it.

**Interface decisions to keep (S10, S11).** The diagnosis that the
interface is BOTH unfinished (a craft problem) and disjointed (a structure
problem), and that treating them as one fails. The refusals: no
app-building platform, no analysis notebooks, no model management,
marketplace, time-series infrastructure or geospatial; the precedent has
thousands of engineers on those and Elysium's edge is the agent, the
security model and governed writes. "Not permitted" and a real null look
different on every surface; "Restricted" is deliberately not a third state,
because MAC withholds whole objects and a link to a hidden object reads as
null (marking it would disclose that it exists). A change to access
labels, or a configuration version put back, that lets anyone read, know of
or run more waits for a second holder of `manage:roles`; anything else
applies at once. Retype refusals: not retypable from the screen are a link
field, a computed field, a type's identifier and the field its row security
reads, judged on the loaded schema and per column (a column that is any
sync target's id or security column, or that a link joins on, is refused
whatever it is called).

**Facts for S7, S8 and S9 from the retype and rebuild work.**
`gold_history` keeps each row as JSON in one text column, so retyping a
field breaks nothing there and old entries keep their old-typed values; the
gold rebuild a type change causes drops only `gold.<Type>`, publication
tags restart, the first publication afterwards records no diff, and the
changelog stays. While silver is refused for a changed declared type the
sync SKIPS gold of that type, so gold keeps its old column type and tags
while reads already use the new declared type. The "values that will not
convert" count is taken in bronze with the rebuild's own conversion and is
never a guessed zero (a missing table or column, an unreadable mirror and a
table over 2,000,000 rows are each said to be not counted). Approving a
proposal while any type it touches is rebuilding is held with a 409 and the
reservation released; a state that cannot be told holds the write. These
rules go with silver if D9 makes it transient; the held-while-rebuilding
rule and the "never a guessed zero" rule stay in some form either way. The
deprecation alert design (daily timer, content-free: a count of references,
never names, because a name in a notice reaches people who may not be
allowed to discover it) is dropped by D8, but the "never a name in a
notice" rule is S12's. A "used by" report lists configuration references
only; saved views, frozen sets, recipes, proposals and notes were never
listed and should be, in S9.

**Surviving rules from the enrichment, prediction and statistics work
(S14).** Never a classified input; served everywhere and marked inferred;
approved before it applies; one model per security compartment (a guess
must not be shaped by records its reader cannot see, and the rule stays
absolute unless a compartment proves too small to learn from); an answer
resting on an inference says so by code. The unusual-record score is the
modified z-score above 3.5, chosen over an Isolation Forest after measuring
both (`core/unusual.py`). None of enrichment, prediction or forecasts was
measured on a real deployment's records.

**Decided NOs, so they are not re-argued.** No separate vector server
(measured in `core/embeddings.py`; revisit near a million declared rows). No
MCP server letting outside models call Elysium's search: a question does not
leave the VM; if ever reopened, every call as the asking person under the
same checks as the routes (MCP's own record, tool poisoning, CVE-2025-6514
and the NSA's May 2026 note that its spread "outpaced the development of
its security model", is the reason to start from that rule). No REST
catalog for the lake until a SECOND process writes to it. The lake's
manifest is read-only input and must never become configuration. DuckDB was
considered for the changelog diff and rejected: profiling found 200,023
SQLite connections behind a 35-second count, not a slow query engine
(`core/ontology/write_log.py`).

**The ELT dependency order, kept because it was derived rather than
guessed.** The changelog diff needs a query engine (it is an anti-join);
the changelog needs durable storage because it becomes a system of record (a
source holds "now", and has no record that a customer's region was us-west
last March), which is the REVERSIBILITY LINE where the mirror stops being a
cache; a materialised MAC column needs somewhere to put it, which is the
transform stage. Folding `sqlite_adapter.py` into the SQLAlchemy adapter
(LIB-3) adds no dependency; 75 files reference the SQLite adapter, mostly
tests using it as the cheap real database, and the write path is where a
mistake reaches a customer's database, so the existing tests are the parity
check. Quoting is closed (`tests/unit/test_identifier_quoting.py`; SQLite's
double-quoted-string misfeature is off on every connection).

**Details of the earlier phased plan that the steps above do not repeat.**
Submission criteria gain `all/any/none` nesting and a `current_user` check
with the operator set fixed (S6). Per-object ETag is the gold publication
plus the latest write-log entry; `If-Match` or `expectedVersions` gives 412
and `require_versions` gives 428; approval re-validates (S9). A later
single-object undo of the most recent edit comes from the queryable action
log (S9). An automation's `propose_action` carries an idempotency key on
the event id and is at-least-once; recipients are users, roles or a
user-reference field, evaluated per recipient (S12). Schema changes encode
precedent's breaking changes (datasource change, key change, type change,
and rename, delete or retype of a field that has write-log edits) and
require a migration choice (`drop_edits | move_edits | cast`) before apply;
an edit and source merge policy per type, `edits: win` (default) or
`edits: most_recent` with a timestamp field (S9). `artifact_store.py` folds
into a notes table and the help assistant into the agent loop (S15).
Subscriptions are `PUT /api/v2/subscriptions/{streamId}` with
CloudEvents-shaped events carrying keys and change state, never values, and
a `refresh` event (S12).

**Blocked on:** nothing from the owner; every decision is made. Each step
needs its listed measurements (section 6) and its preconditions, and the
owner's agreement to a step's shape before it is built (CLAUDE.md: agree the
shape for anything larger than one commit). Step S0 (the rules and this
file) is done.

**Further findings from the same research (owner, 2 November 2026: add to the
roadmap).**

1. Fourteen API conventions are shared by three or more precedents and are adopted wholesale in S5, S9 and S10: field selection; a structured filter with and/or/not; sort; paging that returns a continuation (cursor); expanding along links; named operations separate from create/read/update/delete; a validate-only dry run; optimistic concurrency (If-Match, 412 on mismatch, 428 when required and missing); batch requests; 201 with Location on create, 204 on delete, 202 with Location for work that completes later; one structured error body (RFC 9457 problem details); a change feed; a typed event envelope (id, type, time, source); discoverable schema. The last shared convention, permissions enforced on the caller inside the API, is already Elysium's strongest point.
2. The deliberate refusals mostly survive: single machine, SSE only, writes only through actions, no general expression language, single tenant, and row security evaluated in Python rather than pushed into storage are all supported by precedent. No historian also survives: precedent's own time-series property is a reference to data held elsewhere, so the fit is a `timeseries_ref` field whose points an add-on serves, authorised against the owning object, with Elysium storing no series.
3. Four refusals were put to the owner and are decided (D17 to D21): approval is a per-action policy (precedent applies a person's own edits directly and stages only agent and automation edits); an automation may propose an action that a person still approves; service principals are real user records with explicit grants, which does not break "nothing synthesised"; email is content-free ("you have 3 items") and off by default.
4. Schema change: precedent names seven breaking changes (datasource change, key change, data type change, and rename, delete or retype of a field or struct field that has user edits) and refuses to save until a migration is chosen for each (drop edits, move edits, cast, backfill or revert), with a cap of 500 migrations at once and none on the primary key. An active item cannot be removed or renamed until it has been deprecated, with a reason and a deadline; D8 keeps the migration choices and the "used by" guard and drops the deprecation clock. The retype work (R1 to R4) already follows this pattern; S9 extends it to every schema change.
5. The agent should be a client of the public service layer. Today it has read paths of its own beside the UI's; S15 moves it onto `query` and `actions` in process, which removes the duplicate paths and gives it the same permission checks for free.
6. Not worth building yet: interfaces (precedent's own support is partial), an app builder (Browse already does the the object browser's job), and a pipeline builder (the fixed bronze/silver/gold pipeline is enough).
7. Storage, judgement rather than precedent and therefore "measure first": about 32 separate SQLite files sit beside the lake; D4 merges them into three, and D9 makes silver a transient stage rather than a stored layer, subject to M1 to M3.
8. Built but switched off and waiting on a measurement: six agent-loop switches, label enforcement, identity inference, enrichment, prediction and semantic search. D15 turns label enforcement on for good, D14 moves inferred identity to an add-on and decides enrichment and prediction, and D23 removes the unmeasured switches.
9. README.md was stale: it gave 459 unit files, 82 integration files and 490 controls, named a `tools/` directory that is `functions/`, and documented a `write:<Type>.<field>` grant that the code rejects. The counts and the directory were fixed in 5e79226e; measured on 3 November 2026 the counts are 488 unit files, 111 integration files and 1,166 controls. The `write:` grant text at README.md lines 315, 426 and 452 to 455 is rewritten in S20.
10. The largest single lever is S9: one proposal pipeline removes seven stores and their duplicated four-eyes code, and both the automation work (S12) and the add-ons' requests depend on it.

**Audit of the codebase for simplifications that keep every function (2 November 2026; owner: fix the defects now, add the rest to the roadmap).** Evidence with file and line is in the audit notes kept outside the repository; the counts here were measured.

Defects, all six BUILT (3 November 2026):

1. BUILT, 395bb6bd. An action-level `submission_criteria` loaded cleanly and was never enforced; it is refused at load.
2. BUILT, 1593944a. `Cache-Control: no-store` is the default for every `/api` response. (S5 still replaces the per-route `_no_store` decorators with the default in `Call`.)
3. BUILT, a25f4e00. `scripts/check_controls.py` counted any non-zero pytest exit as "fires"; only a failed test counts now. (S1 still adds the existence check and content anchoring.)
4. BUILT, b146cc91 and 5e79226e. `install/install.sh` copies `functions/` and installs from the lockfiles. (S17 deletes the script.)
5. BUILT, 8e9ce837. One list of the names the pipeline reserves; a silo named for any is refused.
6. BUILT, c102d6be. Unknown or misspelt keys are refused in the configuration files, naming the nearest valid key. (S6 carries this to the typed model with file and line.)

Naming, decided (owner, 2 November 2026: unify and break now, no transition period): one comparison-operator vocabulary, the one the `/api/v2` filter grammar uses (`eq`, `in`, `lt`, `lte`, `gt`, `gte`, `isNull`, `contains`, `startsWith`); one model setting (`llm.model` versus `step_model` and `synthesis_model`); storage bindings inline as `backing:` in each type (D3 reverses the earlier choice of a separate bindings file); one name for callable functions (`functions`, replacing `tools:` and the `tool:` grant); one name for what plugs into the shell: "app" (D6). A misspelt or removed key is refused by the strict-key check, whose "did you mean" names the new spelling; there is no special old-spelling message.

Simplifications, in a suggested order, each now landing in the step named:

1. API (S5, S10): authentication as the router default with a small public router (the login dependency is repeated 138 times); one request-context dependency in place of 153 `_generation()` calls and 22 store-builder helpers; domain errors mapped once (50 hand-written try/except blocks); a request-id middleware so every response carries an id; then replace `api/routes.py` (10,644 lines) resource by resource.
2. UI (S10): one data-loading hook in place of four patterns and 93 copies of the session-expiry catch; `getJson` and `sendJson` helpers in `shell-api/src/api.ts`, which also fix 21 calls that put names into URLs unencoded; one shared change dialog in place of eight schema dialogs (2,860 lines); the shared `EmptyState` used everywhere; sub-app styles out of the shared kit; internal file and layer names kept out of user-facing text.
3. Operator surface (S16, S17): one `elysium` command with subcommands in place of 45 scripts, with one dry-run and exit-code convention; the four user-creation scripts become one command; install reduced from 17 manual steps (an environment file, shipped sync and backup timers, a configuration lint before start, a `doctor` command); production no longer installed from the demo configuration; no silent fallback to a relative runtime tree.
4. Mirror (S7, S8): one layer registry and one table iterator in place of 14 copies of the namespace walk and hand-built layer names; `sync_table` (577 lines, 12 parameters) takes one target; the pipeline moves from `scripts/run_sync.py` into the package and its post-sync steps become data; the panel's "sync now" stops running the sync inside the web server, as the documented separate-process design says; one read-only view of the storage layout; table property names in one registry.
5. Core (S6, S7, S9): erasure fans out through a registry of stores, with a test that fails if a store that holds personal data is left out; configuration errors collected all at once with file and line, shared by startup and the lint script, and a JSON Schema generated for editors; defaults for the three required agent keys so a minimal `config.yaml` is about ten lines, and the two undocumented options documented; the read mediator (2,665 lines) split behind one facade that stays the single access-check site.
6. Tooling and docs (S1, S18, S19, S20): one root `./check.sh`; unit and integration tests as parallel jobs; the simulator tests and `shell/` covered by CI; controls that find their anchor by content, since 198 of them sit in `api/routes.py`; rules that repeat across AGENTS.md, RULES.md, PRINCIPLES.md and CLAUDE.md said once; stale statements corrected.

**Libraries and standards (research, 3 November 2026; owner: add them all).** Library facts rest on registry release dates and licences; the notes behind this paragraph are kept outside the repository. Most hand-written code here is tied to Elysium's own model or its single-machine rule and stays.

Libraries. Adopt: PyJWT in place of the hand-built HS256 token in `core/addons.py` (`sign_identity()`), BUILT first (0a693d06). Consider: one place in the request function for session expiry (about 149 hand-written catches in the UI), then a pilot of TanStack Query on one screen; a typed client generated by openapi-typescript and openapi-fetch from a `/api/v2` spec exported at build time and committed rather than served; sse-starlette for disconnect and ping handling in live updates; tenacity for the REST adapter's retries only (the LLM retry adapter's deadline semantics are deliberate); one schema-version rule for the SQLite stores: stamp `PRAGMA user_version` at creation and refuse to start on a mismatch, with no upgrade path (71 `CREATE TABLE` statements in 35 files have no version today, which has already caused one shipped bug; Alembic is too heavy and nothing is installed that would need migrating); pytest-xdist once slow tests have been measured with `--durations`; pip-audit and npm audit or OSV-Scanner as a scheduled CI job; the browser tests in CI; a small Makefile over `lint.sh`, pytest and the UI scripts. Check: the splink 5 upgrade (Elysium pins below 5). Keep ours: the CLI parsing, login lockout and rate limiting (SQLite-backed so workers share state; the library alternative needs Redis), timers, file locking, add-on supervision, in-product notifications, the closed filter vocabulary, the audit log, data quality (no library fits), no OpenTelemetry exporter (no outbound network), the ontology canvas.

Standards. Already used: OpenLineage events (`core/mirror/openlineage.py`; check the pinned schema version) and ODCS v3 data contracts (`core/mirror/data_contracts.py`; current is v3.2.0). Adopt: OpenAPI 3.1 for `/api/v2`; RFC 9110 conditional requests (ETag, If-Match, 412, 428); RFC 9457 problem details, including its `type`, `title` and `status` members; the Idempotency-Key header, labelled an IETF draft until it is an RFC; CloudEvents 1.0 envelopes on the SSE stream; OpenID Connect login with the authorization-code flow and PKCE (OAuth 2.1 is still a draft, so it is not claimed); W3C Trace Context for request ids (accept an incoming `traceparent`, always issue a fresh span id so a caller cannot forge log correlation); JSON Schema 2020-12 as an export of object types and action parameters. Align, as exports only: LinkML as a bridge to OWL, SHACL and Schema.org; an OCSF export of the audit log, with JSONL kept as the source of truth; the W3C Data Privacy Vocabulary for classification labels; data-quality results in the OpenLineage and ODCS quality formats; optional `Link` headers for paging. Not adopted: OData, JSON:API and GraphQL as wire formats (a second parallel surface works against one mechanism per concern); JSON Patch and Merge Patch (writes go through actions); SCIM for now; Cedar, OPA and XACML as policy engines (a second evaluator beside `check_access()` would drift from it, and the compartment write-down check and uniform denial need Elysium's own logic), though Cedar's principal, action and resource vocabulary is borrowed in the docs and the audit log; CADF and ISO/IEC 27701 as engineering formats.
