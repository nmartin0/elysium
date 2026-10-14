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
| 2. `--workers` for real | RUN, 14 Oct, `uvicorn --workers 2` on a seeded deployment, with every request on a fresh connection and each worker's pid in the access log so a check that reached one worker fails. Sessions, lockouts, proposals confirmed on another worker, and a withdrawn grant refused by every worker after one reload: all held. TWO FAULTS FOUND AND FIXED: the generation header alternated between workers (9, 10, 9, 10), so the UI refetched its schema on almost every request -- it now watches `x-elysium-configuration`, the shared reload epoch; and a starting worker's crash recovery applied a write another worker was still applying (reproduced with two processes: IntegrityError, write done but reported failed) -- applying and resuming now share an flock. `python -m scripts.check_workers` repeats the run on any machine. |
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

THE FILE ITSELF HAS NOW RUN (14 Oct): `npx playwright test`, all 16
of layout.spec.ts and shell.spec.ts passing against the built bundle,
using the Chromium already on disk through playwright.config.ts's
existing `PLAYWRIGHT_CHROMIUM_PATH`. Two setup traps worth knowing: the
layout tests log in as `debug` (scripts/create_debug_user.py), and a
run made before that user exists LOCKS IT OUT for fifteen minutes,
because failed logins count for usernames that do not exist yet.

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
| `OPEN_RISKS.md` | all five resolved or measured: 1, 2 and 5 fixed by earlier patches, 3 built and wired, 4's premise shown out of date in patch 490. Its 24 code citations now name what each risk WAS |
| `GOLD_MIGRATION_SURVEY.md` | every file it named was reworked; its proposed shape IS `build_gold_view`. Its parity test exists and passes (42) |
| `ACCESS_CONTROL_PROPOSAL.md` | not built, and a change to what a grant MEANS. Below |
| `CONFIG_ROUND_TRIP_AND_UI_KIT.md` | not built; needs a dependency decision and product direction. Below |
| `OBJECT_EXPLORER_PLAN.md` | phases 1 and 2 (backend) built, and the blocker they existed to remove is gone -- `in` and `not_in` are in the filter vocabulary. Phases 3-5 are frontend; below |
| `THIRD_PARTY_EXTENSIONS.md` | a design, unbuilt. Its finding about module federation kept below, because it is the kind of thing a later reader would otherwise rediscover the hard way |
| `TRIAGE.md` | fully absorbed: its 45 ids are CSV rows, its mutation sweep is the 70 declared controls in `scripts/check_controls.py`, its reachability sweep is the `WIRED-` rows |
| `LIVE_UPDATES_AND_PIPELINE_BUILDER.md` | nothing built; its security decision kept below because it is the reason the design is shaped as it is |
| `TRIGGERS_AND_PLUGINS.md` | part one built (patches 264-280), including the automation refusal; part two superseded by its own successor, now the plugin-API item. Its three unanswered risks are the triggers item |
| `MEDALLION_PIPELINE.md` | the pipeline is built and all five owner decisions (D1-D5) were answered in September. Its rule S1 now lives in `standardise.py`, and the test that READ this file at runtime is behavioural instead |
| `FUSION_AND_IDENTITY.md` | the backend is built -- `matching.py`, `identity.py`, `identity_decisions.py` with a `merge_decisions` table, and inference OFF by default. The reviewer screen has since been built (Identity), showing which fields agree rather than their values -- its answer to the MAC problem the old item named |
| `ELT_ROADMAP.md` | every phase it defines (0, 0b, 1) is DONE. What remains is a dependency chain, not a plan, and it is below with the measurement that corrected it |
| `HOT_RELOAD_PLAN.md` | built. Its six rules are named in the 26 places that cited step numbers; its most fragile assumption is now a test; and one of its open questions (`DeploymentConfig` not frozen) has since been answered |
| `DEV_UI.md` | **RESTORED, AND THE ROW ABOVE WAS WRONG TWICE.** It claimed 1,271 lines of interface design were "none of it buildable without a front-end agent" and pointed at an item that renumbering had long since made something else. Both halves were disproved by building from it: the measured palette, the type scale, the density ladder and the spine are being built straight out of the file. It is NOT consumed, it is not deleted, and it should not be again -- a measured fact in a deleted file is a measured fact lost, and this one cost a whole type scale reinvented wrong at every step |
| `IDEAS.md` | investigations. Most are SHIPPED or ANSWERED; what is open needs a capable model, and is the agent-loop efficiency item |
| `UI_ROADMAP.md` | 2,143 lines of front-end plan. Its one backend finding -- an unbounded search filling the model's context -- is the context-rot item, with the code evidence |
| `BACKLOG.md` | its sections are absorbed: 0c, 0d4 and 0d5 were worked in patches 475-480; section 1 is the agent-loop efficiency item; section 2's one open piece (the keyboard model's roving-focus half) has since left this file; section 5 pointed here already |
| `ROADMAP.md` | its numbered backend list is done or explicitly NOT DOING; pagination shipped as `page_token`. Its one unbuilt track, external writeback, was decided and built -- see the `write_targets` row |
| `UNIFIED_ROADMAP.md` | the file that started this method: on 21 September it read every plan against the CODE and found seven built things described as open. Its remaining entries are items 30-35; its one correction to me is in item 12 |
| `gold_history` (was item 1) | DECIDED and BUILT, patches 507-509: the owner wanted both a reader and a route. It leaves this file by its own rule -- the decision survives in the code, the `NEW-7` checklist row and the commits |
| saved selections (was item 17) | BUILT as frozen sets: `core/frozen_sets.py`, `/api/frozen-sets`, a `frozen_set` reference on every route that takes a set, and Browse's Frozen sets popover. Unblocked by precedent -- Foundry's static object sets are "a list of primary keys" -- which made "what happens when the publication is forgotten" dissolve: membership is keys, the publication is metadata. DEV_UI 11.5's write-path question about bulk ACTION is unchanged and lives with item 6 |
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
| `read:label:` grants (was item 6) | DECIDED and BUILT, 12 October: a classification label both GRANTS and RESTRICTS -- `read:label:pii` reads every pii field of a type the role can read, and a pii field is unreadable without it whatever was granted by name (demoted to `discover:`). A label never opens a type. Opt-in per deployment (`access: label_enforcement`), compiled into ordinary grants at load; `scripts/label_access_diff.py` says who gains and loses what before the switch is flipped |
| `pgserver` on Python 3.13 (was item 3) | DECIDED and BUILT, 12 October: the real-PostgreSQL tests fall back to the machine's own `initdb`/`pg_ctl` when `pgserver` has no wheel, on a unix socket only, and FAIL rather than skip when neither exists. Found because it had already happened: the gating machine is now 3.13 and 32 tests of the production read path were skipping, green. With the fallback, the same 32 pass against PostgreSQL 16 |
| `/api/events` live updates (was item 8) | DECIDED and BUILT, 12 October: GET /api/events, server-sent events carrying a type and a verb and nothing else, filtered per caller by `core/change_hints.py` (built first, while this waited). Building it found that a running server never served a new publication; `api/reload.follow_publications` now moves it, from the running configuration's own bytes. Mail delivery stays out of scope |
| `/api/help` help assistant (was item 14) | DECIDED and BUILT, 12 October, in the shape decided 5 October: `POST /api/help` answers from the caller's screens, visible schema (names and types, never a value) and own grants -- nothing they may not already know. `core/agent/help_assistant.py`; a Help drawer in the header |
| `DEP-1` to `DEP-6` (was item 1) | ALL DECIDED, 12-13 October. DEP-1 babel, built 12 October. DEP-2 hypothesis and mutmut, adopted with `tests/unit/test_properties.py` and `scripts/mutation_test.py`, whose first runs found a sync mark that could have moved backwards. DEP-3 splink was already the `identity` extra; scikit-learn approved and NOT added until something imports it. DEP-4 all four adopted, each used only where a field declares it. DEP-5 answered itself (permissive replacements), DEP-6 rejections. See their CSV rows |
---

# Blocked on a decision

## 1. Owner questions the checklist still holds

**FOUND ON 13 OCTOBER, when 59 checklist rows were checked against the
code.** This file had said nothing was waiting on a decision. The CSV
disagreed: these rows are decisions only the owner can take, each
verified still open, each with its evidence in its own row. Grouped so
they can be answered together.

**The model and where it runs**
- `D1` -- switch phi4-mini to Qwen3-4B-Instruct after the bench? The
  shipped config is still phi4-mini.
- `D2` -- stay on Ollama, or run llama-server? The OpenAI-compatible
  adapter already reaches it; prompt caching (AR-3) and speculative
  decoding (AR-8) need it.
- `D3` and `AR-9` -- may a query leave the VM for a hosted model, and
  if so on what policy? Today a deployment can swap the whole model,
  never escalate one question.
- `D6` and `AR-10` -- fine-tune a small model on Elysium's own traces?

**Access, and what a person sees**
- `R47` -- review of inferred special-category data (health, religion
  and so on). The one part of D5 not decided.

**Smaller calls**
- `R13`, the rest of erasure -- erasing a person now removes the
  mirror, memories and notes. Other stores still hold their ids:
  frozen-set membership, the write log and pending writes, paused
  questions and answer notifications, and the audit log. The audit log
  is the hard one, because a tamper-evident record and an erasure pull
  in opposite directions. Which of these should forget them?
- `E-21` -- the LICENSE says unpublished and proprietary; the
  repository's visibility should match it.

**Customers**
- `Q1` -- which regulatory regimes apply (the compliance item below
  waits on this). `Q4` -- which source databases come first
  (PostgreSQL is not yet a supported production silo).

**Blocked on:** answers. None blocks building anything else.

# Blocked on a machine or a person running something

Three of the numbered items below wait on a machine as much as on a
decision: agent-loop efficiency and context rot need a capable model
on real hardware, and row-level security needs a production
PostgreSQL silo. They are filed by what decides whether that machine
is worth having.

# Blocked because it is product direction

## 2. Thirty-odd recommendations that are not engineering questions

`R41`, `R42`, `R45`, `R48`, `R51`, `R53`, `R56` to `R62` and their
neighbours are LLM enrichment, embeddings, model predictions,
statistical matching and truth discovery. These are not "should we do
this well" questions; they are "is Elysium this product" questions,
and they should not be picked off a list by whoever is next.

**Blocked on:** a direction. Not on any of them individually -- each
is buildable -- but on whether this is the product at all, which is
why picking one off would be the wrong move rather than a slow one.

## 3. What the Query screen should contain

From `QUERY_PLAN.md`. Two of its four features are BUILT and this item
said otherwise until 14 October: example questions from the deployment
(`display: true` entries in `example_queries.yaml`, refused at load if
they name an identifier-shaped token) and the history of what this
person asked (`app-query/src/AskedBefore.tsx`, in memory for the
session, questions only -- an answer can outlive the grant it was
given under). Two remain, and both are product direction rather than
engineering:

1. **The question, read back** -- what the system understood.
2. **Follow-on questions** after an answer.

**Explicitly not to be built**, and the reasoning is worth keeping:
clarifying questions before answering (an extra model call on a system
where the model is already the slow part, for a problem nobody has
reported) and a conversation thread (Elysium answers questions about
an ontology; it is not a chat assistant, and threading makes "which
generation answered this" much harder to state).

**Blocked on:** product design.

## 4. Writing configuration from the UI

From `CONFIG_ROUND_TRIP_AND_UI_KIT.md`. Its own finding is why it is
hard: **the configuration files are mostly COMMENTS**, so a naive
load-and-dump destroys the thing that makes them readable. Its design
keeps YAML as the source of truth and round-trips through
`ruamel.yaml`, which preserves comments.

`ruamel` is not a dependency today, and it was never one of the `DEP`
items -- adopting it is its own decision, to be made with this one.

**Blocked on:** that dependency call, and on whether configuration
should be editable from the UI at all.

## 5. Object Explorer phases 3 to 5

Phases 1 and 2 are built. **The blocker they existed to remove is
gone:** the plan opens with "our filter is equality only ... so
'region is us-west OR us-east' is not expressible -- which means
clicking two bars on a chart cannot be expressed either." `core/filters.py`
now has `in` and `not_in`, so it is.

The table, the charts, and saving a selection are now built -- the last
as frozen sets. What remains is ACTING on a selection at scale, which is
DEV_UI 11.5's write-path question: one approval covering 200 changes, or
200 rows in the approvals queue. Frozen sets give it a stable thing to
act on; they do not answer it.

**Blocked on:** that write-path decision.

## 6. A plugin API, and the reason module federation is not it

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

## 7. Three questions triggers raise and nobody has answered

Triggers are built. `TRIGGERS_AND_PLUGINS.md` names three risks that
are "about volume rather than authority", and none of them is a code
gap -- each is a decision that has to be made before the first
automation runs at scale.

**Queue flooding, and the feedback loop under it (R50).** An approved
automation write changes the data, and the next sync can trip the same
condition and propose again -- every sync. Checked on 13 October: the
path is real (`core/count_condition.py`, `origin="automation"`). The
guard is one of: refuse while a proposal from the same automation is
pending; a cooldown per object; or an automation never reacting to its
own effect. Each is a few lines once chosen.

`MAX_SUB_WRITES` is 20 and `DEFAULT_TTL` is 15
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

## 8. What the interface should be

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

## 9. Agent-loop efficiency, which needs a machine with a model

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

**Blocked on:** nothing on this hardware. A GPU, or a larger model,
would reopen plan mode and constrained decoding -- both trade compute
the CPU does not have.

## 10. Context rot, and a 10,000-id search behind it

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
midpoint of a task, which needs a capable model and is the agent-loop
efficiency item's blocker too. Item 18 is the cap itself.

**Blocked on:** a model to validate the cap against, and the
`agentic_loop.py` comment beside `MAX_OBJECT_IDS` says exactly why
that matters: told its limit was 20 when given 32 ids, a real model
"came back asking for TWO, then spent the rest of its hops fetching
one object at a time until the duplicate guard stopped it". A cap
chosen without measuring is how that happens again.

## 11. PostgreSQL row-level security for MAC

Held with a trigger named, alongside column `GRANT` with `SET ROLE`.
Elysium enforces MAC in the mediator today; pushing it into the
database would make it true for any caller, not just ours.

**The hazard is already measured and recorded in the schema:**
`via_field:` CANNOT be pushed down, and `ontology_schema.yaml` says
so, because a join-shaped predicate forces a full scan. The
row-level-security guidance is "keep predicates join-free", and
Databricks' SecureView barrier forces full scans for the same reason.

**Blocked on:** PostgreSQL being a supported silo in production, which
it is not. (The other half this used to name -- no real-PostgreSQL
tests on Python 3.13 -- is gone: tests/postgres_server.py falls back to
the machine's own PostgreSQL, and fails when there is none.)


---

# Not blocked, and not here

No infrastructure recommendation is open. `R5` (bounded-memory
batched sync) was built on 13 October, `R4` (one consistent read per
silo per run) on 12 October, and `R10` (the SCD2 changelog) and `R20`
(ontology previews) before them -- see their rows in the CSV.

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

THE QUOTING RISK THIS PARAGRAPH USED TO NAME IS CLOSED, so the fold
is consolidation now, not a fix. Every name goes through `_q`, which is
SQLAlchemy's own IdentifierPreparer (tests/unit/test_identifier_
quoting.py), and SQLite's double-quoted-string misfeature is off on
every connection (CONCERN-1), so an unknown name raises rather than
reading as text. The contract both adapters keep is written on
ExternalReadAdapter (CONCERN-2). What remains is one adapter instead
of two -- worth it when the SQLite adapter next needs real work, not
before.

Write-path first, with the existing tests as the parity check. 75
files reference the SQLite adapter, most of them tests using it as the
cheap real database, and the write path is where a mistake reaches a
customer's database. Days, not hours -- but no decision, so not here.

## 12. Compliance: SOC 2, ISO 27001, HIPAA, and a penetration test

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

## 13. Owning the UI kit, and when to start

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
