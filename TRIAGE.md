# TRIAGE.md -- what is actually left, and how it groups

Written after 26 items were worked one at a time. That pace was right
for the severe ones and is wrong for the rest: a third of what I
checked turned out to be **already fixed**, and many of the remainder
are the same fix wearing different numbers.

This is a triage pass over the 169 open items nominally mine. Checks
here are CHEAP -- a probe, a grep, a single run -- not the full
reproduce-fix-test cycle. **A triage verdict is weaker evidence than a
reproduction**, and this document says which is which. Two findings in
this audit (G1, G3) looked fixed from inspection and needed a real
reproduction to be sure; two others (M1, and my own patch-408
regression) looked fine and were not.

## The headline

| | Count | What it means |
| --- | --- | --- |
| Recommendations and dependency decisions | 63 | Not defects. They need PRIORITISING, not checking. |
| Other agents' items | 45 | LLM2 (agent loop) 29, LLM3 (security) 16. |
| Defects, mine | 61 | Triaged below -- and they collapse into **8 pieces of work**. |

**The 61 defects are not 61 jobs.** Twenty-three of them are one
dirty-data probe reported cell by cell, and they resolve into four
decisions. Grouping them is the whole point of this document.

## Batch A -- numbers that are silently wrong (REAL, small, do first)

Verified by running `transform_rows` on each value:

    ZOO-19  "NaN"  -> nan accepted into a `number` column
    ZOO-20  "inf"  -> inf accepted into a `number` column
    ZOO-13  "１２３"  -> silently becomes 123 (full-width digits)
    ZOO-14  "007"  -> silently becomes 7, losing a code's leading zeros

**Why together:** one function, one policy decision ("what is a
number?"), one patch. **Why first:** these are SILENT. A NaN poisons
every sum computed from that column for ever, and nothing reports it.
PR001-R26 is the same item.

## Batch B -- text that lies to the reader (REAL, security-flavoured)

    ZOO-03  Unicode tag characters survive into gold. The AGENT reads
            them; a human reviewer cannot see them.
    ZOO-04  bidi override survives (Trojan Source).
    ZOO-01  mojibake undetected
    ZOO-02  zero-width space kept
    ZOO-05  Cyrillic homoglyph not flagged
    ZOO-06  C0 control / ESC sequence kept
    ZOO-07  HTML entity undetected

All confirmed present. 03 and 04 are the serious pair: text that reads
one way to a person and another to the model, in a system whose whole
purpose is answering questions from that text. This is PR001-R23, and
the agent-boundary half overlaps LLM2's LB-10 -- **coordinate before
starting**.

## Batch C -- one bad cell refuses the whole table (DESIGN DECISION)

    ZOO-11  "N/A" in an integer column  -> TABLE REFUSED
    ZOO-12  "1,234"                      -> TABLE REFUSED
    ZOO-15  "1e3"                        -> TABLE REFUSED
    ZOO-17  "5%"                         -> TABLE REFUSED
    ZOO-18  "3,14"                       -> TABLE REFUSED
    ZOO-21  "01/02/2024"                 -> TABLE REFUSED
    ZOO-22  "45000" (Excel serial)       -> TABLE REFUSED

Seven symptoms, two causes: no ROW-level expectation (PR001-R22) and
no DECLARED PARSE FORMAT (PR001-R27). Both are policy questions before
they are code, and the audit is emphatic that automatic repair is the
wrong answer -- a 2024 VLDB evaluation of 12 algorithms found most
introduce more errors than they remove.

**Needs the owner** before any code: should one unparseable cell
quarantine the ROW and let the table through?

## Batch D -- values that are missing but do not look it (FEATURE)

    ZOO-08  "N/A" kept as a real value in a string column
    ZOO-09  "999-999-9999" kept
    ZOO-10  "1900-01-01" parsed as a real date
    ZOO-23  "2099-01-01" accepted with no range check
    ZOO-24  email has no canonical form or match key

PR001-R25 and R28. Detection only -- **suggest, never infer**.

## Batch E -- gold changes types (REAL, verified)

    PA001-G6   silver holds integer 7; gold serves the string '7'
    PA001-G7   the link check compares ids without normalising type,
               latent until G6 is fixed on one side
    E-07       a link's id type depends on the read path (OWNER)

Measured directly. One fix, and **G7 becomes live the moment G6 moves**
-- so they go together or the link audit starts disagreeing with
itself.

## Batch F -- the integrity check cries wolf (REAL, verified, important)

    PA001-I1   every gold and quarantine table is reported as broken
               silver. Measured on a HEALTHY deployment:
                 "gold.Thing: no bronze table, so its rows cannot be
                  traced back to what the source said"
    PA001-A18  the declared-column check ignores additional_storage and
               matches tables by bare name, so it can pick a QUARANTINE
               table
    PA001-A17  "unchanged" is never recorded; a degraded run is
               recorded as "synced"

**Why this matters more than its MEDIUM rating.** The audit's own
sentence: "a check that always reports problems on a healthy
deployment trains operators to ignore it, which is how F1 and F2 go
unnoticed". F1 and F2 were real, and that is exactly how they hid.

## Batch G -- the pipeline singles (mostly unverified)

Each is its own patch; none groups usefully.

    PA001-A6    HIGH  served snapshots frozen until reload, and pins can
                      MIX -- next in line
    PA001-A15   MED   one refused table freezes all of gold. LIKELY
                      ALREADY FIXED by patch 424 (per-type skipping) --
                      check before working
    PA001-A10   MED   a declared type change has no path forward
    PA001-A12   MED   bronze copies every column (CONFIRMED:
                      columns_present drives it)
    PA001-A14   MED   ~2.6 KB/row peak, ~10 whole-table copies per sync
    PA001-A16   MED   repair_catalog --write takes no sync lock
                      (CONFIRMED: no lock in the file)
    PA001-G8    MED   the link check depends on build order
    PA001-G10   LOW   a silo named `gold` collides silently (CONFIRMED:
                      no reserved-name guard)
    PA001-S2    MED   SQLAlchemy `str()` puts Python repr in bronze
    PA001-F6.2  MED   six stale docstrings
    PA001-F6.3  MED   the manifest is published BEFORE the sync loop
                      (CONFIRMED)
    PA001-F6.4  MED   layers identified by name prefix (CONFIRMED)

## Batch H -- code quality, not defects (LOW, and two have GROWN)

    F-06   DeploymentConfigResponse duplicates DeploymentConfig
    F-07   identical via_table destructuring at four sites
    F-10   `_generation(request)` called where a Depends() exists --
           the audit counted 31. IT IS NOW 55.
    F-11   the mediator fixture duplicated -- the audit counted 7.
           IT IS NOW 21 FILES.
    F-16   9 unit test files contain no `assert` at all

**F-10 and F-11 nearly doubled while we worked on other things**,
which is the argument for doing them at all: they are cheap now and
they compound.

## What belongs to other agents

    LLM2 agentloop  29  LB-*, AL-*, AR-*, F-04, F-17, F-24
    LLM3 security   16  E-01..E-14, 004-*, F-05, F-08, F-12b, F-13,
                        F-21, F-25, F-27, F-30, F-33

Two on that list are mine to hand over rather than assume: **F-25**
(generation numbers) touches `core/deployment_loader.py` and **004-1**
(the lint.sh lockfile step) touches a shared file.

## Suggested order

1. **Batch A** -- silent numeric corruption, small, no decision needed.
2. **PA001-A6** -- the last HIGH in my area.
3. **Batch F** -- stop the health check lying, so the next real fault
   is visible.
4. **Batch E** -- gold type fidelity (G6 + G7 together).
5. **Batch B** -- text hygiene, coordinating with LLM2 on the boundary.
6. **Batch C** -- after the owner answers the row-versus-table
   question.
7. **Batch G** singles, cheapest first, checking A15 before starting.
8. **Batch H** -- code quality, or never; say which deliberately.
9. **Batch D** and the 63 recommendations -- by priority, once the
   defects are drained.

## Honest limits of this pass

- **Verdicts marked CONFIRMED were probed.** Everything else is
  inspection, and inspection has been wrong twice in this audit
  already -- in both directions.
- **"Likely already fixed" is not "fixed".** A15 gets a reproduction
  before anyone decides it is done.
- **I did not triage the 63 recommendations at all.** They are
  proposals; judging them is a different activity from checking a
  defect, and mixing the two is how a recommendation gets implemented
  because it was on a list.


---

# The recommendations, judged (added after the defects were drained)

The defect triage above is done: every batch closed, the HIGH band
gone, the MED band gone apart from what waits on an owner decision.
What is left is 63 recommendations, and TRIAGE.md's own note said I
had not judged them because "judging a proposal is a different
activity from checking a defect". That was right then. It is now the
only thing left, so here it is.

## Eleven already have a verdict

Not because anyone worked from this list, but because fixing defects
kept landing on them:

| | |
| --- | --- |
| R23 | DONE. Two declared text rules, patches 446 and 456. |
| R24 | DONE. Mojibake and markup residue, patch 456. |
| R25 | DONE. `suggest_declarations`, patch 447. |
| R26 | DONE. Numeric sanity, patch 431. |
| R3 | PARTLY. `bronze_text` (437) covers the loss cases, not the declared-encoding design. |
| R18 | PARTLY. Targets-first ordering (440), not the cycle-safe graph. |
| R1 | SUBSTANTIALLY MET for the pipeline. |
| R14 | LIKELY DONE on the `security` branch; not verifiable until it merges. |
| R9 | NOT STARTED, verified: no `run_id` exists anywhere. |
| R22 | BLOCKED on the row-versus-table decision. |
| R35 | NOT APPLICABLE: there is no export path to escape formulas in. |

**R35 is worth a moment.** It asks for formula escaping at export time,
against CSV injection. There is no CSV or spreadsheet export anywhere
in `api/` or `ui/` -- so nothing can execute a formula today, and the
recommendation is not open so much as PREMATURE. The useful form of it
is a note on whoever builds the first export: build it WITH the
escaping, because retrofitting it means finding every writer.

## What the remaining 55 actually are

They are not one queue. Four kinds, and only one of them is a
near-term engineering question:

**BLOCKED ON A DECISION ALREADY RAISED (4).** R22 and R27 are Batch C
-- the row-versus-table question -- wearing different numbers. R52
(imputation) and R50 (feedback-loop guard) both sit downstream of
LLM3-3, the security-attribute carrier: whether a pipeline stage may
write a value depends on where the security value lives. Answering
those two decisions closes four recommendations.

**INFRASTRUCTURE, UNBLOCKED, SIZEABLE (6).** R4 (one consistent read
per silo), R5 (bounded-memory batched sync), R9 (one run id), R10
(SCD2 changelog), R19 (source-mutation matrix in CI), R20 (Iceberg
branches for previews). Each is a design change to the sync with
consequences for the changelog diff and the partial-read guard, both
of which compare WHOLE tables today. Any of them is days, not hours,
and R5 and R4 conflict enough that the order matters.

**PRODUCT DIRECTION, NOT ENGINEERING (30+).** R41, R42, R45, R48, R51,
R53, R56-R62 and their neighbours are LLM enrichment, embeddings,
model predictions, statistical matching and truth discovery. These are
not "should we do this well" questions, they are "is Elysium this
product" questions. They should not be picked off a list by whoever is
next.

**DEPENDENCY ADOPTIONS (5).** DEP-1 to DEP-6 name specific packages to
adopt, condition or reject. Pure owner calls, and cheap ones: each is
a yes or no about a named library.

## What I would do next, if asked

1. **Answer Batch C.** One question, four recommendations, seven ZOO
   findings.
2. **Answer LLM3-3.** One question, two recommendations, and the
   security-attribute class.
3. **R9, the run id.** The smallest of the infrastructure six, with
   no conflicts, and it makes every other investigation cheaper --
   three times this week I correlated a sync's layers by timestamp
   because nothing else connects them.
4. **DEP-1 to DEP-6**, whenever. Five yes-or-no answers.

## What I would not do

Pick a P1 off the list because it is a P1. R38, R39, R12 and R8 are
all P1 and all large, and starting one without the two decisions above
risks building on a shape that is about to change.


---

# Re-analysis: what must actually be done

Asked to look at every remaining point again, rather than work down
the list. The answer changes what "194 of 302" meant, so it is worth
stating plainly.

## The 109 rows without a verdict are not 109 jobs

| | | |
| --- | --- | --- |
| 17 | **already done on an unmerged branch** | stale rows, now marked |
| 47 | recommendations | judged as a group; individually unjudged |
| 32 | other agents' open items | theirs to close |
| 7 | Batch C | ONE decision |
| 5 | dependency calls | five yes-or-nos |
| 1 | mine and open | ZOO-24, a matching feature (R28) |

**ONE row in the entire backlog is mine, open, and actionable** --
ZOO-24, an email canonical form and match key. It is R28, a matching
feature, and guessing that two spellings are one person is exactly the
inference this design refuses to make on its own. It needs a design
decision, not an afternoon.

## The 17 matter more than their number

These are items an agent has DONE and my checklist still called
`unverified`:

    agentloop   AL-2, AL-4, AL-5, AL-6, AL-7, AL-8, AL-12,
                AR-2, AR-4, LB-1a, LB-1b, LB-3, F-04, F-17
    security    F-08, F-21, F-30, F-33, 004-8

This is COORD-1 repeating. LLM3 lost most of a session to seven rows
that said `unverified` about work already done; LLM2 root-caused a
defect fixed three days earlier; LLM4 reported five as "fixed before I
started". Now there are seventeen more, and every one of them is a
session somebody could waste.

They are marked as REPORTED DONE with the agent's own words and the
branch, and explicitly NOT as verified -- because they are not
verifiable from here until those branches merge, and the difference
between "reported" and "verified" is the whole lesson.

## So the single highest-value action is a merge, not a fix

`security` is 15 commits ahead of `dev`, `agentloop` 7, `frontend` 2.
Merging them:

  - turns 17 reported-done rows into verifiable ones
  - lets the shared-file work (F-06, F-07, F-10, F-11) proceed, which
    is blocked only by three agents working in the same tree
  - stops the fourth round of re-finding

Nothing I can do alone comes close to that in value.

## What is genuinely blocked on a decision

Two answers close eleven rows between them:

  **Batch C** -- should one unparseable cell quarantine the ROW rather
  than refuse the TABLE? Closes 7 ZOO rows and R22 and R27.

  **LLM3-3** -- where does the security attribute live? Closes R50 and
  R52, and settles the class that produced the worst finding of the
  audit.

Then five dependency yes-or-nos (DEP-1 to DEP-6), and the 30-odd
product-direction recommendations that should not be picked off a list
by whoever is next.

## What I would NOT do now

Start one of the six infrastructure recommendations. R4 and R5
conflict, R9 is done, and the rest are days each with consequences for
the changelog diff and the partial-read guard -- both of which compare
WHOLE tables today. Starting one while three branches are unmerged
means designing against a tree that is about to change.


---

# Mutation sweep: does the suite catch a broken fix?

Started because TEST-1 looked like a test that passed with the thing
it tested removed, and I did not know how many others shared that
property. A test that cannot fail is worse than a missing one: it
shows up as coverage.

## TEST-1 was my mistake

The test pins an OLD generation to stage a lost update. Removing the
pin does not disable a fix -- it removes the SCENARIO, so the
assertions pass trivially. That is not a control.

The valid control is reverting the FIX. With `latest_generation()`
inside the approval lock changed back to the pinned `_generation()`,
exactly that test fails. It is a real, working test.

**A CONTROL MUST BREAK THE PROTECTION, NOT THE SETUP.** Writing that
down because I have now made the opposite mistake twice in two days --
the other was restoring a bug's LINE rather than its BEHAVIOUR in
patch 462.

## What the sweep has verified so far

Each of these was reverted at source and the suite genuinely failed:

| behaviour | failures |
| --- | --- |
| the sync lock, in `run_sync` | 1 |
| the sync lock, in `repair_catalog` | 1 |
| silver's security-field exclusion (LLM3-1) | 7 |
| the approval lock | 2 |
| the approval re-read inside the lock | 1 |
| the CSRF token comparison | 3 of 5 |

**No uncovered behaviour found yet.**

## The method has a trap, and I fell in it twice

A mutation that survives proves nothing unless the WHOLE suite ran.
Twice I selected the tests I thought were relevant, saw them pass, and
briefly believed I had found a hole:

  - CSRF "always equal" passed 230 tests -- because the file that
    covers it, `test_csrf_constant_time.py`, was not in my selection.
  - two lock mutations reported "no result", which was a SYNTAX ERROR
    from my own mutation, not a test outcome.

So each real mutation costs a full suite run, about eight minutes
here. That is the honest price of this evidence, and it is why this is
a sweep rather than an exhaustive pass.

## Where to take it next

The behaviours worth the eight minutes are the ones where a silent
pass costs most and where the fix is recent: the write-path
chokepoint, quarantine policy (warn/quarantine/refuse), the drift
refusal, the partial-read guard, session expiry, and the two opt-in
text rules. Each needs a full-suite run against a reverted fix.
