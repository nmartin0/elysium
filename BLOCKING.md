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
| `TRIGGERS_AND_PLUGINS.md` | part one built (patches 264-280), including the automation refusal; part two superseded by its own successor, now item 12. Its three unanswered risks are item 14 |## 1. `F-02` with `F-03` -- no valid policy can authorise a cross-type action
| `MEDALLION_PIPELINE.md` | the pipeline is built and all five owner decisions (D1-D5) were answered in September. Its rule S1 now lives in `standardise.py`, and the test that READ this file at runtime is behavioural instead |
| `FUSION_AND_IDENTITY.md` | the backend is built -- `matching.py`, `identity.py`, `identity_decisions.py` with a `merge_decisions` table, and inference OFF by default. The reviewer screen is not, and its MAC problem is item 15 |**The sharpest one, and it outranks the rest.** Reproduced: the policy
| `ELT_ROADMAP.md` | every phase it defines (0, 0b, 1) is DONE. What remains is a dependency chain, not a plan, and it is below with the measurement that corrected it |validator rejects every `write:` grant, while the write path demands
| `HOT_RELOAD_PLAN.md` | built. Its six rules are named in the 26 places that cited step numbers; its most fragile assumption is now a test; and one of its open questions (`DeploymentConfig` not frozen) has since been answered |one per field. So no valid policy can authorise a cross-type action at
| `DEV_UI.md` | 1,271 lines of interface design, none of it buildable without a front-end agent. Its diagnosis, its refusals and its palette reasoning are item 16 |
| `IDEAS.md` | investigations. Most are SHIPPED or ANSWERED; what is open needs a capable model, and is item 17 |
| `UI_ROADMAP.md` | 2,143 lines of front-end plan. Its one backend finding -- an unbounded search filling the model's context -- is item 18, with the code evidence |
| `BACKLOG.md` | its sections are absorbed: 0c, 0d4 and 0d5 were worked in patches 475-480; section 1 is item 17, section 2's one open piece is item 19, section 5 pointed here already |---
| `ROADMAP.md` | its numbered backend list is done or explicitly NOT DOING; pagination shipped as `page_token`. Its one unbuilt track, external writeback, is item 20 |
| `UNIFIED_ROADMAP.md` | the file that started this method: on 21 September it read every plan against the CODE and found seven built things described as open. Its remaining entries are items 32-35; its one correction to me is in item 18 |# Blocked on a decision
| `gold_history` (was item 2) | DECIDED and BUILT, patches 507-509: the owner wanted both a reader and a route. It leaves this file by its own rule -- the decision survives in the code, the `NEW-7` checklist row and the commits |
| `write_targets` (was item 20) | DECIDED and BUILT: off by default, a separate block, existing deployments warned rather than broken |
| `check_controls` in CI (was item 6) | the 70 controls now run as their own CI job. Inert until Actions is enabled, which only the owner can do -- but the mechanism exists rather than being a suggestion |
| `AUDIT_CHECKLIST.csv`'s SEC rows (was item 5) | all 25 inherited findings closed. Three real and fixed (SEC-09, SEC-19, SEC-22), three were guards whose call sites nothing held (SEC-14, SEC-27, and the one behind SEC-04), the rest covered, moot or unactionable |
| `E-02` residual (was item 2) | BUILT from settled precedent: the peer address by default, `X-Forwarded-For` believed only from a declared proxy, rightmost hop, malformed falls back loudly. `trusted_proxies` is empty in the template |
| `on_type_mismatch`, Batch C (was item 1) | BUILT from precedent: a type mismatch quarantines the ROW and syncs the rest; an absent key keeps refusing. Measured on a real deployment -- 2 rows quarantined, 5 synced, where before the table was refused entirely. Closes ZOO-11, -12, -15, -17, -18, -21, -22, R22, R27 |
| `NEW-6` (was item 2) | BUILT, tiered: tag characters and bidi controls refused without being asked, zero-width still opt-in because emoji and several scripts use it. The compilers made the same call -- GCC ships `-Wbidi-chars=unpaired` as the default, not `any` |
| `display_safety` (was item 8) | BUILT: an example marked `display: true` may not hold an identifier-shaped token, checked at deployment load. SHAPE not existence -- an example naming `cust_999` is safe today and a leak the day that customer exists |
| `NEW-5` (was item 2) | DECIDED and BUILT: new deployments keep only declared columns; an absent key keeps everything and WARNS, naming them. Measured -- an undeclared SSN is absent from bronze under the shipped default and kept under an absent key |
| `F-02`, `F-03`, `F-12c` (item 1) | DECIDED and BUILT, option C: `execute:<Action>` plus `write:<Type>` for every type the action edits, which is Foundry's. The per-field form stays rejected because nothing checks it. `F-03`'s KeyError goes with it -- asking per type removed the `["mutations"]` access |
| `NEW-4` (was item 2) | DECIDED and BUILT: a missing gold TABLE raises `GoldPublicationMissing`, matching what `find_ids` has always done; a missing ROW still returns None, which `write_mediator`'s uniqueness check needs |
| `WIRED-1` (was item 3) | DECIDED and BUILT: `/api/saved-views` re-authorises at read time and names what it disabled. It caught a test asserting the bug on its first run -- a Customer view filtering on `amount`, a Transaction field |
---

# Blocked on a decision

## 1. `LLM3-3` -- where does the security attribute live?

Raised by the security agent before it was destroyed, and the class
behind the worst finding of the audit. Two shapes:

- **A side table** keyed by object, holding the security value.
- **A column plus a check** that the pipeline never rewrites it.

The agent leaned toward the side table without recommending it. My own
argument, recorded at the time: the column-plus-check option has the
same "must be remembered" property one level down -- every future
pipeline stage must read the carried value rather than the column --
which is an argument FOR the side table that was not in their
write-up.

**Also closes:** `R50` and `R52`, both of which sit downstream of
where the value lives.

**THE RISK IS MEASURED, AND HALF-FIXED.** Before building a migration
I checked whether the pipeline actually rewrites the value MAC reads.
It does: `transform_rows` standardised EVERY column, including that
one. With the deployment's own rules a region of `"N/A"` became None
and the object belonged to no compartment at all; `" us-west "` became
`"us-west"` and stopped matching a caller whose value kept its
spacing. Fail-closed in the first case, a silent mismatch in the
second, neither visible to anyone.

Silver now leaves the security column exactly as the source wrote it,
resolved from the type's own declaration and refusing when two types
sharing a table disagree about where their value lives. Verified
end-to-end on a real sync: both values survive.

**THAT IS NOT THE SIDE TABLE**, which the owner chose. It stops the
pipeline rewriting the column that exists today, and it produces the
evidence the migration needed. What remains of the argument for moving
the value is the one recorded above: every FUTURE pipeline stage must
remember the same rule, and a rule that must be remembered is the
thing the side table removes.

**Blocked on:** whether the side table is still worth the migration
now the column is no longer rewritten.

## 2. `A6` -- one generation serving two ages

A pinned type sees an old snapshot while an unpinned type sees the
current one, within one generation. Three options were recorded:
leave it, build an authoritative pin map including link tables, or pin
per request.

**Blocked on:** the choice. The first option is defensible and should
be taken explicitly rather than by default.

## 3. `DEP-1` to `DEP-6` -- five dependency adoptions

Each is a yes or no about a named library. Cheap to answer, and not
mine to answer.

**Blocked on:** six yes-or-nos. `DEP-4` gates item 10, because the
configuration round trip needs `ruamel.yaml` and it is not a
dependency today.

---

# Blocked on a machine or a person running something

## 4. `--workers` for real

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

## 5. `pgserver` on Python 3.13

There is no wheel. The only real-PostgreSQL tests cannot run on the
machine that gates every patch, and the SQLAlchemy adapter is the
production read path.

**Blocked on:** a 3.12 environment for those tests, or a different
PostgreSQL fixture.

---

# Blocked because it is product direction

## 6. Thirty-odd recommendations that are not engineering questions

`R41`, `R42`, `R45`, `R48`, `R51`, `R53`, `R56` to `R62` and their
neighbours are LLM enrichment, embeddings, model predictions,
statistical matching and truth discovery. These are not "should we do
this well" questions; they are "is Elysium this product" questions,
and they should not be picked off a list by whoever is next.

**Blocked on:** a direction. Not on any of them individually -- each
is buildable -- but on whether this is the product at all, which is
why picking one off would be the wrong move rather than a slow one.

## 7. What the Query screen should contain

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

## 8. Bootstrapping a deployment FROM the lake manifest

`LAKE_METADATA_NOTE.md` answered four questions about what the lake
should hold. Three were already built -- WHERE
(`_elysium/manifest-<generation>.json`, one per configuration
generation), WHEN (on configuration change, not every sync) and
SECRETS (never published; the manifest carries only the `adapter` key
per silo). The fourth, a reader that REPORTS, is built now.

**Its own deferral, kept because the reasoning is the point:**

> The stronger version -- bootstrapping a new deployment FROM the
> manifest -- is tempting and should wait. A copy that can become a
> source of truth is a copy that can disagree with one, and the whole
> reason this is a copy is to avoid that.

**Blocked on:** whether Elysium should ever configure itself from a
lake. It is a question about what the lake IS, not about code.

## 9. Grant by TAG rather than by field name

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

**Blocked on:** this changes what a grant MEANS, and every existing
`policy.yaml` with it. Nothing of it is built -- no tags anywhere in
`core/` or `api/` -- so it is a decision before it is work.

## 10. Writing configuration from the UI

From `CONFIG_ROUND_TRIP_AND_UI_KIT.md`. Its own finding is why it is
hard: **the configuration files are mostly COMMENTS**, so a naive
load-and-dump destroys the thing that makes them readable. Its design
keeps YAML as the source of truth and round-trips through
`ruamel.yaml`, which preserves comments.

`ruamel` is not a dependency today, so this needs one of the `DEP`
answers before it is even possible.

**Blocked on:** that dependency call, and on whether configuration
should be editable from the UI at all.

## 11. Object Explorer phases 3 to 5

Phases 1 and 2 are built. **The blocker they existed to remove is
gone:** the plan opens with "our filter is equality only ... so
'region is us-west OR us-east' is not expressible -- which means
clicking two bars on a chart cannot be expressed either." `core/filters.py`
now has `in` and `not_in`, so it is.

What remains is frontend: the table, the charts, and saving and acting
on a selection. The last of those is the same thing as item 24.

**Blocked on:** product design, and there is no front-end agent.

## 12. A plugin API, and the reason module federation is not it

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

## 13. Live updates, and the decision that shapes them

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

## 14. Three questions triggers raise and nobody has answered

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

## 15. The merge reviewer's screen, and the MAC problem under it

Identity inference is built and OFF by default, with every proposal
requiring approval. What is not built is the screen a reviewer uses,
and `FUSION_AND_IDENTITY.md` is specific about what it must show:

- **The two records side by side**, field by field, with agreements
  and disagreements marked -- "the reviewer's decision is made on the
  agreement PATTERN, not the score".
- **The score, and what drove it**: which fields contributed and how
  much. "A number alone cannot be argued with."
- **Provenance per field**, which silver's lineage already carries.

**AND THE PROBLEM THAT IS OURS SPECIFICALLY**, kept whole because it
is a security design rather than a UI preference:

> A REVIEWER MAY NOT BE CLEARED TO SEE THE FIELDS THAT DECIDE THE
> MATCH. Elysium is MAC-governed; the person best placed to judge
> whether two customers are the same may not be permitted to read the
> email address that settles it.

Its answer comes from privacy-preserving record linkage: **masked
clerical review**, where the display conceals the plaintext by
default, presents categorical value frequencies, and gradually
discloses selected information. A reviewer can be told that two values
AGREE, or that a value is RARE, without being shown it.

The document argues this is "a genuinely good fit for a MAC system and
worth building rather than working around", and it is right: the
comparison a reviewer needs is usually agreement, not the value.

**THE BACKEND HALF IS BUILT**, `core/masked_review.py`.
`masked_comparison` gives a verdict for every compared field and the
values only for fields the caller may read; `agreement_pattern` is the
pattern in one line; `withheld_fields` records what the reviewer
judged blind, because an approval made with three of five deciding
fields masked is a weaker artifact than one made with all five.

**WHAT IS WITHHELD IS ABSENT, not masked.** The literature states the
requirement -- "the facility responsible for the (masked) clerical
review should only have access to those plaintext attributes that are
displayed" -- so the structure never holds the hidden value at all.
The difference is invisible on a screen and total in a log, a cache or
a future refactor. A test asserts the withheld string does not appear
anywhere in the output's `repr`.

**Still blocked on:** the screen, and a route to feed it. If identity
inference is dropped, DELETE `core/masked_review.py` -- the vulture
whitelist says so.

**Blocked on:** the frontend, and on whether masked review is built
properly or the feature waits. Showing the fields would be the easy
version and would quietly defeat MAC.

## 16. What the interface should be

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

## 17. Agent-loop efficiency, which needs a machine with a model

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

## 18. Context rot, and a 10,000-id search behind it

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
midpoint of a task, which needs a capable model and is item 17's
blocker too. Item 18 is the cap itself.

**Blocked on:** a model to validate the cap against, and the
`agentic_loop.py` comment beside `MAX_OBJECT_IDS` says exactly why
that matters: told its limit was 20 when given 32 ids, a real model
"came back asking for TWO, then spent the rest of its hops fetching
one object at a time until the duplicate guard stopped it". A cap
chosen without measuring is how that happens again.

## 19. The keyboard model's roving-focus half

Gated rather than unstarted, and `BACKLOG.md` recorded both the
condition and the reason it sharpened:

> the recorded condition is that "nobody has established who uses
> Elysium daily", and the precedent sharpens it -- our results are
> cards with links, not a grid, so `role="grid"` without the full
> keyboard contract would be worse than native semantics.

**Blocked on:** knowing whether anyone uses this daily. A partial grid
contract is worse than none, so the trigger is real rather than an
excuse.

## 20. PostgreSQL row-level security for MAC

Held with a trigger named, alongside column `GRANT` with `SET ROLE`.
Elysium enforces MAC in the mediator today; pushing it into the
database would make it true for any caller, not just ours.

**The hazard is already measured and recorded in the schema:**
`via_field:` CANNOT be pushed down, and `ontology_schema.yaml` says
so, because a join-shaped predicate forces a full scan. The
row-level-security guidance is "keep predicates join-free", and
Databricks' SecureView barrier forces full scans for the same reason.

**Blocked on:** PostgreSQL being a supported silo in production, which
it is not. `pgserver` has no wheel for Python 3.13 (item 5), so the
real-PostgreSQL tests cannot run on the machine that gates patches.

## 21. The help assistant

A larger design, written and unbuilt. It would be an agent explaining
Elysium itself rather than a customer's data.

**Blocked on:** whether it is wanted. It is the one feature on the
list that competes with documentation rather than extending the
product.

## 22. The search bar's five unbuilt operators

Front-end work on a bar whose backend vocabulary is already closed and
built -- `core/filters.py` has seven operators, `in` and `not_in`
among them.

**Blocked on:** a front-end agent, and on item 11, since the operators
and Object Explorer's filter UI are the same surface.

## 23. The watch layout check, never seen to pass

Rewritten in patch 290 and never once observed passing:

    cd ui && npx playwright test -g "Watch recipient"

It is not known to be broken. It is known to be unobserved, which is a
different thing and worth keeping separate -- a test nobody has
watched run is not evidence.

**Blocked on:** somebody running it. One command.

## 24. Saved SELECTIONS

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
