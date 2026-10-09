# Blocking

**The one planning file.** Everything here is work that CANNOT be done
without a person: a decision, a judgement about the product, a machine
nobody has, or an answer only the owner holds.

Anything that could be done has been done, and the document it came
from has been deleted. That is the rule this file exists to enforce:
if an item can be built, it does not belong here -- it belongs in the
code.

## How a document leaves

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

## Run, and therefore closed

| was | what was observed |
| --- | --- |
| 17. The watch layout check | RUN AND PASSES. The item said it was "not known to be broken ... known to be unobserved, which is a different thing -- a test nobody has watched run is not evidence". It has now been watched: the recipient control computes `flexDirection: row` and measures 21px tall, against the spec's limits of `row` and under 40. A screenshot confirms the checkbox and `customer_service` sit on one line with the label. |

NOT BY THE COMMAND THE ITEM GAVE, and that is worth recording rather
than glossing. `npx playwright test` could not run: the pinned
@playwright/test wants a Chromium revision this environment cannot
download, and the one present is older. The spec's assertions were
run instead through the Python binding against the same built bundle
served by the same uvicorn -- same page, same selectors, same two
measurements. Somebody with a working `npx playwright install` should
still run the file itself; this closes the question the item asked,
which was whether the layout holds.

## Consumed so far

| document | outcome |
| --- | --- |
| `SCALABILITY.md` | both decisions already built; benchmark numbers moved into the code that cited them |
| `QUERY_PLAN.md` | four unbuilt UI features, all product direction; its deferred MAC argument kept below |
| `LAKE_METADATA_NOTE.md` | three of its four answers were built; the fourth -- a reader -- is built here. Its one deferral kept below |
| `AUDIT_INTAKE.md` | superseded by `AUDIT_CHECKLIST.csv` by its own words; all 67 findings verified present there first; its alias table folded into the ten rows it concerns |
| `AUDIT_INTAKE_PIPELINE.md` | same; 50 ids checked, every one tracked |
| the nine agent files | `HANDOVER_*`, `REQUESTS_*`, `STATUS_*` -- 8,662 lines from three agents that no longer exist. 25 SEC findings rescued into the CSV first; every other id verified already tracked |
| `000COORDINATION.md` | the protocol for four agents that no longer exist, and all four branches are merged. Its ownership table was already wrong -- `SEC-06` measured it matching 89 of 145 source files. Consuming it surfaced a real conversion that had been unblocked for forty patches |
| `LIBRARY_AUDIT.md` | 1.1 superseded by its own Part 4.6; 1.2 MEASURED AND REJECTED, with the numbers now in `request_metrics.py` and eight tests enforcing it; 1.3 is available work, below. Parts 2-4 are reasoning about when to take a dependency, kept in `PRINCIPLES.md`'s territory |
| `OPEN_RISKS.md` | all five resolved or measured: 1, 2 and 5 fixed by earlier patches, 3 built and wired, 4's premise shown out of date in patch 490. Its 24 code citations now name what each risk WAS |---
| `GOLD_MIGRATION_SURVEY.md` | every file it named was reworked; its proposed shape IS `build_gold_view`. Its parity test exists and passes (42) |
| `ACCESS_CONTROL_PROPOSAL.md` | not built, and a change to what a grant MEANS. Below |
| `CONFIG_ROUND_TRIP_AND_UI_KIT.md` | not built; needs a dependency decision and product direction. Below |
| `OBJECT_EXPLORER_PLAN.md` | phases 1 and 2 (backend) built, and the blocker they existed to remove is gone -- `in` and `not_in` are in the filter vocabulary. Phases 3-5 are frontend; below |
| `THIRD_PARTY_EXTENSIONS.md` | a design, unbuilt. Its finding about module federation kept below, because it is the kind of thing a later reader would otherwise rediscover the hard way |# Blocked on a decision
| `TRIAGE.md` | fully absorbed: its 45 ids are CSV rows, its mutation sweep is the 70 declared controls in `scripts/check_controls.py`, its reachability sweep is the `WIRED-` rows |
| `LIVE_UPDATES_AND_PIPELINE_BUILDER.md` | nothing built; its security decision kept below because it is the reason the design is shaped as it is |
| `TRIGGERS_AND_PLUGINS.md` | part one built (patches 264-280), including the automation refusal; part two superseded by its own successor, now item 9. Its three unanswered risks are item 11 |## 1. `F-02` with `F-03` -- no valid policy can authorise a cross-type action
| `MEDALLION_PIPELINE.md` | the pipeline is built and all five owner decisions (D1-D5) were answered in September. Its rule S1 now lives in `standardise.py`, and the test that READ this file at runtime is behavioural instead |
| `FUSION_AND_IDENTITY.md` | the backend is built -- `matching.py`, `identity.py`, `identity_decisions.py` with a `merge_decisions` table, and inference OFF by default. The reviewer screen is not, and its MAC problem is item 12 |**The sharpest one, and it outranks the rest.** Reproduced: the policy
| `ELT_ROADMAP.md` | every phase it defines (0, 0b, 1) is DONE. What remains is a dependency chain, not a plan, and it is below with the measurement that corrected it |validator rejects every `write:` grant, while the write path demands
| `HOT_RELOAD_PLAN.md` | built. Its six rules are named in the 26 places that cited step numbers; its most fragile assumption is now a test; and one of its open questions (`DeploymentConfig` not frozen) has since been answered |one per field. So no valid policy can authorise a cross-type action at
| `DEV_UI.md` | 1,271 lines of interface design, none of it buildable without a front-end agent. Its diagnosis, its refusals and its palette reasoning are item 13 |
| `IDEAS.md` | investigations. Most are SHIPPED or ANSWERED; what is open needs a capable model, and is item 14 |
| `UI_ROADMAP.md` | 2,143 lines of front-end plan. Its one backend finding -- an unbounded search filling the model's context -- is item 15, with the code evidence |
| `BACKLOG.md` | its sections are absorbed: 0c, 0d4 and 0d5 were worked in patches 475-480; section 1 is item 14, section 2's one open piece is item 16, section 5 pointed here already |---
| `ROADMAP.md` | its numbered backend list is done or explicitly NOT DOING; pagination shipped as `page_token`. Its one unbuilt track, external writeback, is item 17 |
| `UNIFIED_ROADMAP.md` | the file that started this method: on 21 September it read every plan against the CODE and found seven built things described as open. Its remaining entries are items 32-35; its one correction to me is in item 15 |# Blocked on a decision
| `gold_history` (was item 1) | DECIDED and BUILT, patches 507-509: the owner wanted both a reader and a route. It leaves this file by its own rule -- the decision survives in the code, the `NEW-7` checklist row and the commits |
| `write_targets` (was item 17) | DECIDED and BUILT: off by default, a separate block, existing deployments warned rather than broken |
| `check_controls` in CI (was item 4) | the 70 controls now run as their own CI job. Inert until Actions is enabled, which only the owner can do -- but the mechanism exists rather than being a suggestion |
| `AUDIT_CHECKLIST.csv`'s SEC rows (was item 3) | all 25 inherited findings closed. Three real and fixed (SEC-09, SEC-19, SEC-22), three were guards whose call sites nothing held (SEC-14, SEC-27, and the one behind SEC-04), the rest covered, moot or unactionable |
| `E-02` residual (was item 1) | BUILT from settled precedent: the peer address by default, `X-Forwarded-For` believed only from a declared proxy, rightmost hop, malformed falls back loudly. `trusted_proxies` is empty in the template |
| `on_type_mismatch`, Batch C (was item 1) | BUILT from precedent: a type mismatch quarantines the ROW and syncs the rest; an absent key keeps refusing. Measured on a real deployment -- 2 rows quarantined, 5 synced, where before the table was refused entirely. Closes ZOO-11, -12, -15, -17, -18, -21, -22, R22, R27 |
| `NEW-6` (was item 1) | BUILT, tiered: tag characters and bidi controls refused without being asked, zero-width still opt-in because emoji and several scripts use it. The compilers made the same call -- GCC ships `-Wbidi-chars=unpaired` as the default, not `any` |
| `display_safety` (was item 6) | BUILT: an example marked `display: true` may not hold an identifier-shaped token, checked at deployment load. SHAPE not existence -- an example naming `cust_999` is safe today and a leak the day that customer exists |
| `NEW-5` (was item 1) | DECIDED and BUILT: new deployments keep only declared columns; an absent key keeps everything and WARNS, naming them. Measured -- an undeclared SSN is absent from bronze under the shipped default and kept under an absent key |
| `F-02`, `F-03`, `F-12c` (item 1) | DECIDED and BUILT, option C: `execute:<Action>` plus `write:<Type>` for every type the action edits, which is Foundry's. The per-field form stays rejected because nothing checks it. `F-03`'s KeyError goes with it -- asking per type removed the `["mutations"]` access |
| `NEW-4` (was item 1) | DECIDED and BUILT: a missing gold TABLE raises `GoldPublicationMissing`, matching what `find_ids` has always done; a missing ROW still returns None, which `write_mediator`'s uniqueness check needs |
| `WIRED-1` (was item 1) | DECIDED and BUILT: `/api/saved-views` re-authorises at read time and names what it disabled. It caught a test asserting the bug on its first run -- a Customer view filtering on `amount`, a Transaction field |
| `LLM3-3` (was item 1) | DECIDED and BUILT, a third option the entry did not contain: the value is COPIED into `_security` at sync and MAC reads that, so no later stage can change who sees what by touching the data. Proven by overwriting every `region` in gold and watching MAC partition unchanged. NOT the side table -- four stages had to be told to carry the column, which is the cost a side table would not have |
| `manifest` bootstrap (was item 6) | CLOSED PERMANENTLY: the lake's manifest is read-only input and must never become configuration. The reason now lives in `read_manifests`' own docstring, where somebody would reach for it, because planning documents get consumed and a reason in a deleted list is rediscovered the hard way |
| `A6` (was item 1) | RESOLVED, not deferred: leave it. Cross-table snapshot consistency is a CATALOG feature and a REST catalog is a service to run, back up and secure for a property no wrong answer has been observed from. THE TRIGGER, recorded so it is not re-argued: when a SECOND process writes to the lake |
---

# Blocked on a decision

## 1. `DEP-1` to `DEP-6` -- five dependency adoptions

Each is a yes or no about a named library. Cheap to answer, and not
mine to answer.

**CORRECTED 4 OCTOBER.** This said `DEP-4` gates the configuration
round trip because it needs `ruamel.yaml`. THAT IS FALSE. `DEP-4` is
phonenumbers, holidays, email-validator and ftfy; `ruamel` is not a
`DEP` item at all. I invented the link in an earlier patch and it has
sat here since, making this item look like a blocker for item 7 when
it is not.

**ALL SIX ALREADY CARRY VERDICTS** in the checklist -- ADOPT, ADOPT,
ADOPT, CONDITIONAL, AVOID, REJECT. The analysis was done; what is
missing is a decision to act on it.

**`DEP-5` IS RESOLVED WITHOUT COUNSEL.** It reads "AVOID: pycountry
(LGPL); python-stdnum pending counsel". pycountry is LGPL-2.1-only on
PyPI, listed as LGPL-3.0 by one aggregator, and described as "a
permissive MIT-style license" by a third-party site that is simply
wrong -- a dependency whose licence is misreported in public is one
that must be re-explained at every audit. Permissive replacements
cover the same standards: `pycountries` (MIT, ISO 3166/4217/639),
`py-country-codes` (MIT, zero dependencies), `countrywrangler` (MIT).
Nothing imports any of them today, so this is a dependency under
consideration rather than one in use.

**Blocked on:** five yes-or-nos, `DEP-5` having answered itself.

---

# Blocked on a machine or a person running something

## 2. `--workers` for real

Patches 292-295 fixed all four blockers. It has only ever run as two
apps inside one test process.

**Blocked on:** somebody running it.

## 13a. Twenty-five inherited security findings

The security agent kept its own register because it was not allowed to
edit `AUDIT_CHECKLIST.csv`, and said so:

> ONE ASK OF BACKEND: fold these into `AUDIT_CHECKLIST.csv` and this
> file can go. It exists because I may not edit that one, not because
> two registers are a good idea -- and two lists is the exact failure
> this project keeps finding.

**That ask was never honoured while they existed.** Patch 487 did it:
all 27 `SEC-` ids are now rows. Six map onto work already done under
my numbering (`SEC-01` is `LLM3-1`, `SEC-02`/`SEC-03` are `LLM3-2`,
`SEC-05` is `PA001-A11`, `SEC-17` was rebuilt in patch 465). One was
withdrawn by its own author as overstated. The rest are open and
INHERITED -- raised by somebody who can no longer be asked what they
meant.

**Blocked on:** nothing, for the tractable ones -- they are ordinary
work now that they are on the list. Named here only because their
provenance matters: a finding whose author is gone cannot be
clarified, only reproduced or dropped.

## 3. `pgserver` on Python 3.13

There is no wheel. The only real-PostgreSQL tests cannot run on the
machine that gates every patch, and the SQLAlchemy adapter is the
production read path.

**OBSERVED PASSING, 5 October.** The container that gates every patch
runs Python 3.12, so `pgserver` installs here and the tests are NOT
skipping: `test_sqlalchemy_adapter.py` 19 passed, `test_source_type_drift.py`
13 passed, with `pgserver`, `psycopg` and `sqlalchemy` all importable
and zero SKIPPED.

Started one directly to be sure the suite was not passing vacuously:
**PostgreSQL 16.2**, a real server, over a unix socket.

So the SQLAlchemy adapter -- the production read path -- has real
PostgreSQL coverage every time the suite runs here. What is not
established is the 3.13 question: there is still no cp313 wheel, so a
3.13 environment would skip these silently.

**Blocked on:** whether the project must support Python 3.13. If 3.12
is the supported runtime, this item is CLOSED and the only change
worth making is a guard that fails rather than skips when `pgserver`
is absent -- so a 3.13 machine reports lost coverage instead of a
green suite.
# Blocked because it is product direction

## 4. Thirty-odd recommendations that are not engineering questions

`R41`, `R42`, `R45`, `R48`, `R51`, `R53`, `R56` to `R62` and their
neighbours are LLM enrichment, embeddings, model predictions,
statistical matching and truth discovery. These are not "should we do
this well" questions; they are "is Elysium this product" questions,
and they should not be picked off a list by whoever is next.

**Blocked on:** a direction. Not on any of them individually -- each
is buildable -- but on whether this is the product at all, which is
why picking one off would be the wrong move rather than a slow one.

## 5. What the Query screen should contain

Four features, none built, from `QUERY_PLAN.md`. They are product
direction rather than engineering: what a question box should offer
somebody who has never used it.

1. **Example questions from the deployment.** A deployment states what
   its data is good for; nobody else can. NOT by reusing
   `example_queries.yaml` as it stands -- its entries are user-paired
   for the runner. Either a separate `ui_examples:` key or a
   `for_display: true` marker on entries that qualify; the second is
   smaller and keeps one list.
2. **The question, read back** -- what the system understood.
3. **Follow-on questions** after an answer.
4. **History** of what this person has asked.

Its own order: 1 and the cheap half of 3 need nothing and would help
immediately.

**Explicitly not to be built**, and the reasoning is worth keeping:
clarifying questions before answering (an extra model call on a system
where the model is already the slow part, for a problem nobody has
reported) and a conversation thread (Elysium answers questions about
an ontology; it is not a chat assistant, and threading makes "which
generation answered this" much harder to state).

**Blocked on:** product design, and there is no front-end agent now.

## 6. Grant by TAG rather than by field name

From `ACCESS_CONTROL_PROPOSAL.md`. Declare a vocabulary -- `pii`,
`financial`, `internal`, `restricted` -- tag FIELDS with it, and let a
role grant `read:tag:pii` instead of enumerating every field.

**The burden it answers was counted rather than asserted**, which is
why the proposal is worth keeping whole:

        10 types x 15 fields   ->    160 grant strings PER ROLE
        50 types x 20 fields   ->  1,050 grant strings PER ROLE
       120 types x 25 fields   ->  3,120 grant strings PER ROLE

Every one hand-written, per role, per deployment. Add a property to a
type and every role that should see it needs editing.

The shape has a real safety property: a new property is UNREADABLE
until tagged, which is the deny-by-default behaviour already in place,
now at field level. It also proposes inheriting tags from the type and
declaring only exceptions.

**TWO THINGS I SAID ABOUT THIS WERE WRONG, corrected 5 October.**

I warned of a FAIL-OPEN HAZARD, citing ABAC precedent that "any
mismatch between principal and resource tags creates either silent
access denials or silent grants". THAT DOES NOT APPLY TO THIS DESIGN.
The proposal above grants BY tag, so an untagged field is covered by
no grant and is unreadable -- which the entry already said and I did
not read carefully enough. It fails closed, and the AWS hazard is
about a different shape: matching resource tags against principal tags,
where a broad policy can sweep in something nobody tagged.

I also proposed HIERARCHICAL ROLES as a simpler substitute, on the
precedent that "the best practice is to aim for reduced, manageable
roles and permissions, or the use of a hierarchy in roles for
inheritance, rather than a large number of roles". That is a real
pattern and a real answer -- to a DIFFERENT burden. Inheritance stops
one role repeating another's grants. It does nothing about the 160
grant strings a single role needs, which is what the count above
measures. The two are complementary, not alternatives.

**Blocked on:** this changes what a grant MEANS, and every existing
`policy.yaml` with it. Nothing of it is built -- no tags anywhere in
`core/` or `api/` -- so it is a decision before it is work. The
trigger stands: a deployment whose per-field grants are large enough
that nobody reads them before editing.

## 7. Writing configuration from the UI

From `CONFIG_ROUND_TRIP_AND_UI_KIT.md`. Its own finding is why it is
hard: **the configuration files are mostly COMMENTS**, so a naive
load-and-dump destroys the thing that makes them readable. Its design
keeps YAML as the source of truth and round-trips through
`ruamel.yaml`, which preserves comments.

`ruamel` is not a dependency today, so this needs one of the `DEP`
answers before it is even possible.

**Blocked on:** that dependency call, and on whether configuration
should be editable from the UI at all.

## 8. Object Explorer phases 3 to 5

Phases 1 and 2 are built. **The blocker they existed to remove is
gone:** the plan opens with "our filter is equality only ... so
'region is us-west OR us-east' is not expressible -- which means
clicking two bars on a chart cannot be expressed either." `core/filters.py`
now has `in` and `not_in`, so it is.

What remains is frontend: the table, the charts, and saving and acting
on a selection. The last of those is the same thing as item 18.

**Blocked on:** product design, and there is no front-end agent.

## 9. A plugin API, and the reason module federation is not it

`THIRD_PARTY_EXTENSIONS.md` designs third-party extensions. None of it
is built, and whether Elysium should have them at all is a product
question.

**ITS MOST IMPORTANT FINDING IS WORTH KEEPING WHOLE**, because it is
the kind of thing a later reader would otherwise rediscover by
shipping it:

> A federated module runs **in your page, in your origin**. It gets
> the same DOM, the same cookies, the same `localStorage`, and the
> same authenticated access to every `/api/*` route as Elysium itself.
> The federation frameworks say so themselves -- they "do not claim
> that same-realm JavaScript is a security sandbox".

Module federation is the obvious answer and the wrong one. The design
proposes JSON-RPC 2.0 over `postMessage` instead, a third-party
adapter as a SILO, and ontology fragments declared as DATA rather than
code.

**Blocked on:** whether to have an extension story at all. Everything
downstream of that is design work that cannot start first.

## 10. Live updates, and the decision that shapes them

Nothing is built -- no SSE, no `EventSource`, no streaming response
anywhere in `api/`. What makes the design worth keeping is its
security decision, which is quoted rather than summarised:

> **EVENTS CARRY NO DATA.** An event says "something of this kind
> changed", never what changed. The client then refetches through the
> SAME authorised endpoints it already uses, so MAC, roles and every
> permission check apply exactly as they do now.
>
> The alternative -- pushing the changed object down the stream --
> would put a second, parallel read path beside the mediator, and
> every security rule would have to be re-implemented on it
> correctly, forever. That is how leaks happen. A hint plus a refetch
> cannot leak: the refetch is the existing, tested path.

It also notes that a hint's SCOPE needs care: "a Customer changed"
tells a user that SOME customer changed, so hints name a TYPE and a
kind of change and nothing more.

**And a measured answer to a question the owner asked:** whether an
alert could arrive as MAIL. SSE cannot do that -- it pushes to an open
browser -- and Elysium has NO SMTP SUPPORT OF ANY KIND today. Mail is
a separate delivery channel, not a variation on this.

**THE SECURITY HALF IS BUILT**, `core/change_hints.py`, because it has
to be right before the transport exists rather than invented under
deadline after it. `hints_for` filters changed types by the caller's
own `visible_schema` -- deferring to the rule that already decides
which types a caller may know exist, rather than asking `discover:`
a second time -- and `describe_hint` refuses any payload beyond a type
and a verb. A count is the tempting one: "4 Customers changed" looks
harmless and maps the size and rhythm of a compartment somebody
cannot see.

**THE PRECEDENT VALIDATES THE DECISION rather than merely permitting
it.** "Rich payloads bypass authorization -- data in events is
accessible to all subscribers regardless of permission levels", while
"notification events preserve security". For regulated data the
guidance is "never in events, API with authorization only"; for
consumers with different authorization levels, "notification + API
required". Elysium authorises per field and per row.

The usual criticism of thin events -- that a consumer receiving an id
and immediately refetching "has not been decoupled from you" -- does
not apply, because here the refetch IS where authorization happens.

**Blocked on:** whether live updates are wanted enough to carry a
streaming endpoint, and separately whether mail delivery is in scope
at all. IF DECLINED, DELETE `core/change_hints.py` -- it has no other
purpose and should not sit there looking load-bearing. The vulture
whitelist says so too.

## 11. Three questions triggers raise and nobody has answered

Triggers are built. `TRIGGERS_AND_PLUGINS.md` names three risks that
are "about volume rather than authority", and none of them is a code
gap -- each is a decision that has to be made before the first
automation runs at scale.

**Queue flooding.** `MAX_SUB_WRITES` is 20 and `DEFAULT_TTL` is 15
minutes. An automation firing across a thousand objects either exceeds
the sub-write cap or creates fifty pending writes that expire before
anyone reads them. Foundry has an "execute once for all objects"
option for exactly this; there is no equivalent here, and no stated
answer for what happens when a condition matches more than the cap.

**Four-eyes against an automation.** The criteria vocabulary can say
"the approver must not be the proposer". If an automation proposes as
its OWNER, the owner cannot approve it -- arguably correct, and it
means every confirmation-required automation needs a second human
every time it fires. The document's own words: "worth deciding
deliberately rather than discovering."

**Evaluation cadence.** When conditions should be evaluated -- the
document argues for when the mirror changes rather than on a clock,
but it is not settled.

**Blocked on:** three answers. The first needs a cap policy, the
second is a product decision about how much friction an automation
should carry, and the third is a design choice with cost on both
sides.

## 12. What the interface should be

`DEV_UI.md`, written after the owner said the interface is BOTH
unfinished and disjointed. **Its diagnosis is the part worth keeping**,
because it is why a redesign would fail:

> Those are two different faults with two different fixes, and
> treating them as one is how a redesign fails: new paint on the same
> dead ends, or a new structure that still looks like a prototype.

**UNFINISHED is a craft problem** -- inconsistent spacing, tables that
are HTML tables, empty states that say nothing useful, loading that
flashes, iconography borrowed from whatever Blueprint offered.
"Nothing is wrong, and nothing looks decided." **DISJOINTED is a
structure problem**, and a different fix.

**AND A LIST OF REFUSALS**, which is the half a summary always drops:

> - An app-building platform (Workshop). An app inside an app.
> - Analysis notebooks (Contour, Quiver). Charts over a set, yes; a
>   second analytical language, no.
> - Model management, a marketplace, time-series infrastructure,
>   geospatial.
>
> Palantir has thousands of engineers and customers demanding those.
> Elysium's edge is the agent, the security model and governed writes.

One measured fact worth not relearning: white on pure black causes
**halation** -- the text bleeds across the corneal lens, worst for
readers with astigmatism and worse the longer the session. 21:1
contrast is not a target.

**Blocked on:** a front-end agent, and the owner's appetite for a
redesign rather than more features.

## 13. Agent-loop efficiency, which needs a machine with a model

`IDEAS.md`'s open investigations all need traces from a real model on
real hardware. The measurements already taken are kept because
re-taking them costs an afternoon of somebody's GPU.

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

**Blocked on:** a machine with a capable model, and about an hour of
someone's time on it.

## 14. Context rot, and a 10,000-id search behind it

`UI_ROADMAP.md` calls this "a risk to what already exists, not a
feature", and it is the only part of that file that is not front-end
work.

> **Context rot.** Current research describes "a model's effective
> recall degrading as the token count grows, WELL BEFORE the hard
> context limit is reached", driven by tool responses carrying
> metadata "beyond what is decision-relevant".
>
> Our agent accumulates `gathered` across every step and feeds it back
> each hop. A query touching many objects therefore degrades the
> answer BEFORE it errors -- the failure mode is a worse answer, not a
> crash, which is the hard kind to notice. We have never measured
> where that begins.

**CORRECTED, patch 505.** Patch 502 recorded this as an UNBOUNDED
search putting 200,000 ids into `gathered`. **That was wrong.**
`MAX_SEARCH_SCAN` is 10,000 in `mediator.py`, applied by asking for
`MAX_SEARCH_SCAN + 1` so that "we stopped looking" can be told apart
from "that was all of them", and truncating with `scan_truncated` set
on the outcome. I read `search_object`'s signature, saw no `limit`
parameter, and did not read far enough into its body.

**What is actually true is still worth recording.** The cap is 10,000
ids, `_step_search_object` builds `entry = {**step, "result":
object_ids}` and appends it whole, and `gathered` goes back to the
model on every remaining hop. Ten thousand ids is on the order of
tens of thousands of tokens re-sent per hop, against an agent that
runs eight hops.

Compare `get_object`, which IS bounded: `MAX_OBJECT_IDS = 20`, with a
refusal that names the batch and the remainder. The input side is
capped and the output side is not.

**Two things are wanted, and only one is mine to do.** Item 17 is
measurement -- task completion rate against context size at the
midpoint of a task, which needs a capable model and is item 15's
blocker too. Item 18 is the cap itself.

**Blocked on:** a model to validate the cap against, and the
`agentic_loop.py` comment beside `MAX_OBJECT_IDS` says exactly why
that matters: told its limit was 20 when given 32 ids, a real model
"came back asking for TWO, then spent the rest of its hops fetching
one object at a time until the duplicate guard stopped it". A cap
chosen without measuring is how that happens again.

## 15. PostgreSQL row-level security for MAC

Held with a trigger named, alongside column `GRANT` with `SET ROLE`.
Elysium enforces MAC in the mediator today; pushing it into the
database would make it true for any caller, not just ours.

**The hazard is already measured and recorded in the schema:**
`via_field:` CANNOT be pushed down, and `ontology_schema.yaml` says
so, because a join-shaped predicate forces a full scan. The
row-level-security guidance is "keep predicates join-free", and
Databricks' SecureView barrier forces full scans for the same reason.

**Blocked on:** PostgreSQL being a supported silo in production, which
it is not. `pgserver` has no wheel for Python 3.13 (item 3), so the
real-PostgreSQL tests cannot run on the machine that gates patches.

## 16. The help assistant

A larger design, written and unbuilt. It would be an agent explaining
Elysium itself rather than a customer's data.

**THE SHAPE IS DECIDED, 5 October.** It answers from `visible_schema`
and the caller's own grants -- not from the documentation, and not
from `config`.

Reading configuration directly would be the failure the precedent
documents repeatedly: assistants that "tried (and failed) to mirror or
enforce fine-grained enterprise permissions". Elysium already has the
non-mirrored path, and `visible_schema` already answers "which types
may this caller know exist".

The warning that applies anyway: an assistant "doesn't bypass
permissions", but "overly broad, inherited, or poorly reviewed
permissions create the risk", because it "queries faster than any
human user ever could manually". One documented incident surfaced
"workplace investigation details when a user asked Copilot about a
specific employee". So it amplifies whatever the grants already allow,
which is an argument for building it ON the existing checks rather
than beside them.

**Blocked on:** whether it is wanted. It is the one feature on the
list that competes with documentation rather than extending the
product.

## 17. Saved SELECTIONS

A set of chosen OBJECTS rather than a saved question, and what bulk
actions would operate on. `BACKLOG.md` is explicit that the UI must
not conflate it with saved explorations.

**Blocked on:** product design.

---

# Not blocked, and not here

Six infrastructure recommendations are open and buildable: `R4` (one
consistent read per silo per run), `R5` (bounded-memory batched sync),
`R10` (SCD2 changelog), `R19` (a source-mutation matrix in CI), `R20`
(Iceberg branches for previews). They are days each rather than hours,
and `R4` and `R5` conflict enough that the order matters -- but they
need no decision, so they stay out of this file until one of them
does.

**The ELT chain joins them too**, and its ORDER is the part worth
keeping, because it was re-derived from the dependencies rather than
guessed:

- the changelog diff NEEDS a query engine -- it is an anti-join;
- the changelog NEEDS durable storage, because it becomes a system of
  record: a source database holds "now" and has no record that a
  customer's region was us-west last March, so losing the changelog
  loses history nothing can return. That is the REVERSIBILITY LINE,
  the point at which the mirror stops being a cache;
- a materialised MAC column NEEDS somewhere to put it, which is the
  transform stage.

Its phase 0 is why the order is trustworthy. The measurement that
justified the original phase 1 was real and measured THE WRONG THING:
counting 50,000 transactions took 35 seconds, and a synthetic
benchmark grouped 200,000 rows in 0.3s. Profiling found **200,023
SQLite connections** -- four per object, from per-object write-log
consultation. **DuckDB would have optimised the 0.24s and left the
38.7s alone.** Fixed instead: 34.90s to 1.29s, 27x.

**`LIB-3`, folding the SQLite adapter into the SQLAlchemy one as a
dialect**, joins them, and `LIBRARY_AUDIT.md` called it the strongest
of its three because it adds NO new dependency. `sqlite_adapter.py`
builds SQL by string interpolation at 50 sites while
`sqlalchemy_adapter.py` uses the expression API for the same job.

The risk it carries is identifier quoting: every f-string
interpolating a table or column name is a place where a declared
schema controls SQL text. That is configuration rather than user
input, which is why it has not bitten -- but a library that quotes
identifiers correctly answers a CLASS of bug rather than its
instances.

Write-path first, with the existing tests as the parity check. 75
files reference the SQLite adapter, most of them tests using it as the
cheap real database, and the write path is where a mistake reaches a
customer's database. Days, not hours -- but no decision, so not here.

## 18. Compliance: SOC 2, ISO 27001, HIPAA, and a penetration test

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

**The fifth is real engineering and is not blocked:** encryption at
rest. `core/mirror/lake_permissions.py` says it is out of scope today.
`cryptography` is available; SQLCipher is not installed, which shapes
the design.

ONE DESIGN DECISION IS NEEDED BEFORE STARTING. SQLCipher encrypts the
SQLite stores transparently but adds a C dependency and a build step.
Application-level column encryption plus volume encryption for the
rest has fewer dependencies, more code, and leaves file metadata
visible. Also undecided: whether the mirror is in scope or only the
control-plane databases.

All four frameworks test an overlapping set of technical controls, and
building them is worth doing on its own merits regardless of whether
an audit is ever bought:

    encryption at rest       Elysium's own stores, and the mirror
    key management           where keys come from, rotation
    session controls         idle timeout, absolute timeout, revocation
    password policy          enforced rather than advised
    access review            export who holds what grant, as of when
    audit integrity          tamper-evidence on the existing log
    backup verification      restore tested rather than assumed

Months, not a patch.

## 19. Owning the UI kit, and when to start

**Blocked on:** nothing. This is a DECISION ALREADY TAKEN, recorded
here so the next person does not reopen it from scratch.

The question was whether to move off Blueprint to avoid depending on
one company. `CONFIG_ROUND_TRIP_AND_UI_KIT.md` Part 2 -- consumed in
patch f55eee5 -- answered it: the risk is abandonment rather than
capture, because Blueprint is Apache-2.0 and a granted licence cannot
be revoked; and a BIGGER vendor is the wrong direction. Its proposal
stands: own the twelve simple components, vendor headless primitives
for the six behavioural ones.

**WHAT WAS DONE INSTEAD, AND WHY NOT THE REST.** Three wrappers now
sit in `shell-api/components` -- `Action`, `StatusTag`, `Notice` --
covering the 97 call sites with the most repetition. They deliver the
benefit the literature actually credits to wrapping: "the gained
consistency of reducing the used API surface", not swappability, which
it names as the weak argument.

`Dialog` at two uses and `InputGroup` at three were LEFT ALONE
deliberately. A wrapper over a component used twice "will just become
a copy of the component and thus not be helpful at all".

**WHY NOT FINISH THE MIGRATION NOW.** The plan's strongest argument
was drift -- the surface widened from 22 components to 33 in a
fortnight "and nothing noticed, because nothing was looking".
`ui/src/blueprintSurface.test.ts` closed that: growth is now a diff
someone justifies, and it caught the three wrappers' type imports the
day they were written. The urgency is gone; the option is not.

Against spending the month now: Blueprint 6.20.0 shipped 2026-09-17,
so abandonment is not near. Radix, the obvious destination, has slowed
since WorkOS acquired it and shadcn/ui has already moved its default
foundation away from it. And the plan is honest that "the six
behavioural ones are the real work ... it is easy to build a dialog
that looks right and traps nobody" -- which would risk the keyboard
work just paid for.

**THE TRIGGERS THAT CHANGE THE ANSWER**, either one on its own:

1. Blueprint misses a React major release, or goes six months without
   a security fix.
2. The design language becomes a constraint -- a screen that cannot be
   built because Blueprint's components will not do it.

When either fires, the wrappers are already the call-site layer: the
implementation changes underneath them and the 97 call sites do not
move.
