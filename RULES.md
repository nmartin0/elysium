# RULES

The working method, in one place. Distilled from `PRINCIPLES.md`,
`AGENTS.md` and `CLAUDE.md`, which hold the same rules mixed with
this project's specifics. **This file is the generic part** -- what
would still apply on a different codebase.

Every rule here was learned by getting something wrong. Where the
mistake is instructive it is named, because a rule without its reason
gets worked around the first time it is inconvenient.

---

## 1. Verify directly. Never assume.

**Read the code before describing it. Run the command before
recommending it. Measure the cost before claiming it.**

The recurring failure is asserting a general case from a check of a
specific one. Examples from one project, all caught by a test that
took under two minutes:

- "This needs no special handling" -- said after checking that a
  declaration was sufficient to INTERPRET a value, concluding it was
  sufficient FULL STOP. Three cases changed meaning silently.
- A roadmap entry claiming a sync reported only the first drifted
  column. It reported every one.
- A roadmap entry claiming caches grew without bound. They were
  cleared on every use.
- A `curl` diagnostic handed over without running it. The endpoint was
  deliberately disabled and returned 404 at every path.
- A `sqlite3` command handed over to someone who did not have it
  installed.

**A diagnostic that has never been executed is a guess with a prompt
in front of it.**

### The corollary: your own notes decay

Planning documents are claims like any other. Three entries in one
project were wrong on inspection, all in the same direction --
**describing a defect that reading the code would have ruled out.**
Re-verify before building from a note you wrote a month ago.

---

## 2. Audit your own work before delivering it

**After the work is done and before the patch is handed over, read
what you actually changed as though somebody else wrote it.**

**The tests passing is not the audit. It is an input to the audit.**
The audit also asks whether the message's claim matches what the code
does, whether a control was run (rule 4), and what was NOT checked --
which belongs in the hand-over rather than in the author's head. This
rule caught its own restatement: an attempt to add "research precedent
and audit your work" as a NEW rule 18 was a duplicate of this rule and
rule 5, found by grepping this file before committing.

Specifically:

- `git diff` the whole change. Not the parts you remember editing --
  all of it. Edits land in the wrong place more often than anyone
  expects.
- **And `git status`, because `git diff` does not show new files.**
  Found while auditing the commit that added this rule: the new file
  was invisible in the diff it was being reviewed from.
- Re-read every comment you wrote against the code beside it. A
  comment that describes an earlier draft is worse than no comment.
- Check that every claim in the commit message is one you MEASURED,
  not one you inferred.
- Confirm the tests you added would fail if the change were reverted.
  If you have not run that control, you do not know.
- Look for the thing you built that nothing calls. A function whose
  body is `return value` is a comment with parentheses.

**This is a separate step, not a feeling.** The work being finished
and the work being correct are different states, and the gap between
them is where most defects live.

---

## 3. Real tests, with real negative controls

**A test that passes when the feature is removed tests nothing.**

The control is not a final check. **It is how you find out whether you
wrote a test or a decoration**, and it belongs in the loop: write the
test, break the thing, watch it fail, restore, watch it pass.

### The control must fail for the RIGHT reason

Check what the failure says. A control that fails because of a syntax
error, an import cycle, or a missing fixture has proved nothing about
the thing under test.

### A control that cannot fail is the real hazard

Three ways this happens, all seen:

**The environment hides it.** A timezone test in a UTC container
cannot see a timezone bug. Pin a non-UTC zone for tests -- one behind
UTC so date slippage shows, and one observing daylight saving so a
fixed-offset mistake shows.

**The case is missing rather than the check.** A test asserting "this
direction is handled" says nothing about the other direction. If a
guard has two sides, test both.

**The assertion is too weak to notice.** Comparing sizes when you
should compare contents: two sets merging and two sets replacing can
produce the same count.

### When the change is about COST, not behaviour, use a tripwire

Some changes cannot be caught behaviourally. Reading a row count from
metadata instead of scanning returns the same number. Copying a
database with a consistent snapshot instead of a file copy produces
the same file when nothing is writing.

**Pin the mechanism at source level** -- assert the code calls what it
must call -- and say in the test why a behavioural control could not
work.

---

## 4. Measure before and after, and report both

**"This is faster" is not a finding. "858ms and 66MB became 49ms and
3.2MB" is.**

Measure the thing that will actually bite, not the thing that is easy
to measure. And when a measurement surprises you, measure again with
the steps separated -- a first reading showing an 80x improvement
turned out to be a warm cache, and separating the calls showed the
real saving was 9%.

**State what a measurement does NOT cover.** A sync benchmark against
local SQLite measures your time, not the load on a customer's
production database.

---

## 5. Research precedent before inventing a pattern

**Check what an established system does first, and quote it.**

This is not deference. It is that a problem with a name has usually
been solved badly several times already, and the failure modes are
written down. Terms found this way in one project: predicate pushdown
and residual predicates, the Bell-LaPadula \\*-property, medallion
bronze/silver/gold, schema drift severity tiers, context rot,
principle of least authority.

**Naming a thing correctly means the next person recognises it.**

### Reverse a committed decision when research contradicts it

Reversals belong in the record. A design document that hides its
wrong turns teaches nobody.

### It applies to DESIGN and to PATCHES, always, not when convenient

The owner made this explicit on September 22: research precedent
before any answer that requires designing, and before code patches
too. It is not a step for unfamiliar problems only.

The evidence for making it unconditional is that every design decision
in this project that held up came from somebody else's written
experience, and it was consistently NARROWER than the principle that
would have been reasoned out -- twice it contradicted the plan
outright. Foundry's writeback dataset settled where an edit to a fused
object goes. Iceberg's reader semantics settled what happens when the
mirror changes mid-read. Databricks and dbt between them settled
warn-versus-fail. APCA settled a palette that WCAG had already passed.

So: prefer the source that says what WENT WRONG -- a postmortem beats
a feature page. Say plainly when the precedent contradicts the plan.
And say plainly when there is NO precedent, because that is a real
finding and it changes how confident the design should sound.

### And check the precedent applies

An established pattern has a context. Module federation is the
standard way to load remote UI code -- and it provides NO isolation,
which disqualifies it entirely if the code is untrusted. The
precedent was right and the context was different.

---

## 6. Say what is still open

**Nothing ships without an honest account of what it does not do.**

Every feature has an edge it does not reach. Write it down in the
commit, in the code comment, and in the roadmap -- not because it is
required, but because the alternative is somebody discovering it
under pressure.

Examples worth the words: a bound that is incidental rather than
declared; a check that covers fields but not meanings; a guarantee
that narrows a window rather than closing it; a mechanism that works
on one database and not another.

---

## 7. No speculative code

**Do not build for a caller that does not exist.**

If nothing calls it, it is not tested by use, and the first real
caller will want it shaped differently. The linter flagging a function
as unused is usually right.

---

## 8. Read the signature before you call it

**Invented method names and guessed argument shapes are the single
most common avoidable error.**

The tools catch them, which is fine, but each costs a cycle. Check:
the method exists, the arguments are in that order, the return type is
what you think, and the fixture has the data your assertion needs.

**A test built with real constructor arguments catches what a mock
hides.** One project found an existing field named exactly what it was
about to add -- because the constructor raised for five missing
arguments.

---

## 9. Do not truncate the output you are diagnosing from

`tail -1` discards the failure name. `head -3` hides the second error.
When something fails, read the whole thing before deciding what it
says.

**And read the log you already have.** A 404 sitting in a paste was
read as a stale server when it meant a wrong URL, costing a round
trip.

---

## 10. Layers are enforced, not aspirational

**If an architecture says one layer must not reach into another, a
tool should fail when it does.**

When an exception is genuinely needed, name it individually rather
than weakening the rule. A list of five specific allowed imports is a
boundary; a disabled check is not.

---

## 11. Security is explicit and fail-safe

**Refuse rather than guess.** A missing environment variable must stop
the load, not substitute an empty string -- an empty password produces
a connection that looks valid and fails somewhere else entirely.

**Re-evaluate authority at the point of use.** Never store a decision
about what somebody may do; store what they asked for and decide
again.

**Attenuation only.** No mechanism may let a request do something the
requesting user could not already do. Anything else is a confused
deputy.

**Never let a credential into an error message.** An error is the most
likely place for a secret to reach a log somebody pastes.

**And filtering-after-assembly is where systems leak**, because the
unfiltered thing existed. Compute per-recipient rather than computing
once and redacting.

---

## 12. Comments explain WHY, and stay honest

A comment that says what the code does is noise. A comment that says
why it does it that way -- and what was tried first -- is the most
valuable thing in the file.

**Write down the wrong turn.** "A first version used X and failed
because Y" stops the next person, possibly you, from trying X again.

**And correct a comment when the code changes.** A stale comment is
worse than none, because it is believed.

---

## 13. One change per commit, and the message carries the reasoning

**The commit message is where the reasoning lives**, not the pull
request, not a chat log. It should say what was measured, what was
tried and rejected, what is still open, and which controls fired.

Somebody reading `git log` in a year should be able to reconstruct the
decision without finding you.

---

## 14. Run the feature before committing it

**Tests passing is not the same as the feature working.** Start the
thing, use it the way a person would, and look at what comes back.

A panel that renders in a test can still be unreachable in the
product. An endpoint that answers in a test client can still be
serving stale code to a browser.

---

## 15. Know what the environment hides

**A container is not the target machine.** Things that differ and have
each caused a real failure:

- **Python version.** A wheel published for 3.12 and not 3.13 breaks
  an install entirely.
- **Installed tools.** `sqlite3` may not be there.
- **Timezone.** UTC hides every timezone bug.
- **Disk.** Filling it mid-run produces failures that look like code
  defects.
- **A running process does not reload on `git pull`.** New code on
  disk and an old process serving it is indistinguishable from a bug,
  and the symptom is not always an error -- a new response field
  arriving as `undefined` renders as an empty state.

---

## 16. When handing work to someone else, hand over everything

If a change needs a rebuild, a restart, a migration or a new
dependency, **that goes in the same block as the command that applies
it** -- not in a sentence afterwards, and not as a trailing comment.

A step written as prose beside a command block is a step that gets
skipped.

---

## 17. Prefer the boring order

When a list contains one interesting item and several dull blocking
ones, **the dull ones come first.** The interesting item will still be
interesting later; the blocking ones will still be blocking.

Order work by what depends on what, and write that ordering down
separately from the grouping by subject -- they are different
questions and the dependency one is more useful once a phase is
half-done.

