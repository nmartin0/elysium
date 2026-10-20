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
| Object Explorer phases 3-5 (was item 5) | DECIDED 14 October, and ALREADY BUILT: one proposal per bulk action via an `object_reference_list` parameter, driven by Browse's selection bar. The decision set the limit: 256 by default (`bulk_action_limit`), 1,024 at most. See the `BULK-1` row |
| `R58` (was item 1) | DECIDED by precedent and BUILT, 14 October: a pair whose approval would join records already approved together shows the whole group on its card ("Approve the group of 3") and the server refuses the approval (409) unless it names exactly that group -- Informatica MDM's "pre-merge review", Tamr's cluster-level verification. Records the reviewer cannot see are counted, not named; a bulk approval skips chains and says why |
| `R13`, the rest of erasure (was item 1) | DECIDED and BUILT, 14 October: every store but the audit log forgets an erased person -- frozen-set membership (and criteria that named them), the write log, waiting writes (withdrawn, audited by id and proposer only), paused questions (the asker told, not about whom), answer notifications (found by the objects they were built from), and merge proposals naming them with their decisions. The audit log keeps a `stage: erasure` entry: who asked, counts per type, never an id. One call, `forget_beyond_the_mirror`, serves both an erasure and a restore |
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
  shipped config is still phi4-mini. NOW A MEASUREMENT (19 October):
  `python -m scripts.compare_models phi4-mini <other>` runs the bench's
  seven questions on each, answers included, and tabulates how many
  each got right and where a whole question's seconds went -- steps
  and answer, reading and writing, as the server reported them.
- `D2` -- stay on Ollama, or run llama-server? The OpenAI-compatible
  adapter already reaches it, and reads its timings; prompt caching
  (AR-3) and speculative decoding (AR-8) need it -- llama.cpp's n-gram
  drafting (`--spec-type ngram-simple`) needs no second model, and
  suits replies that copy names and values out of their prompt. Run
  compare_models once per server, with --config naming each.
- `D3` and `AR-9` -- may a query leave the VM for a hosted model, and
  if so on what policy? Today a deployment can swap the whole model,
  never escalate one question.
- `D6` and `AR-10` -- fine-tune a small model on Elysium's own traces?

**Access, and what a person sees**
- `R47` -- review of inferred special-category data (health, religion
  and so on). The one part of D5 not decided.

**Smaller calls**
- `E-21` -- the LICENSE says unpublished and proprietary; the
  repository's visibility should match it.

**Customers**
- `Q1` -- which regulatory regimes apply (the compliance item below
  waits on this). (`Q4`, which source databases come first, was
  answered on 19 October: PostgreSQL and MariaDB, then CSV files, then
  REST; see "The simulator as Elysium's live test" below.)

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

**THE DIRECTION WAS GIVEN** (the owner, 14 October: "we'll build each
of them", in the order LLM enrichment, statistical matching, a plugin
API).

**LLM ENRICHMENT IS BUILT, choices only** (R41, R42, R38; decided 15
October: approve first, data rules never code, no classified input,
served everywhere and marked inferred). A field declares `enrich: {from,
instruction, choices}`; `scripts/compile_enrichment.py` has the model
label a sample from one security compartment, write rules from half of
it and be scored on the other half; the rules wait in Inbox →
Enrichment; once approved, the next sync fills the field in gold.
SEVERAL CANDIDATES MAY VOTE (17 October, EVAPORATE-Code+): rule sets
better than even odds on the examples are weighted by their log-odds,
and the vote is kept only when it beats the best single set there; the
approver sees every set and its weight. A VALUE TAKEN FROM THE TEXT
(17 October): `extract: true` with the field's data_type (string,
integer, decimal, date); rules are context words plus a fixed shape the
model picks but never writes, the value is always a span of the row, and
numbers and dates are typed by the source's declared locale. Dates
relative to something, times of day, and dates or numbers written in
words each wait for their own decision. SEARCH BY MEANING (R45, 17
October): a type declares `semantic_search: {from: [fields]}`; the sync
embeds changed rows with `llm.embedding_model` through the local Ollama,
within a time budget, versioned by the model's digest; Browse shows
"Related in meaning" beside a search's word matches -- never inside
them, since the word matches are the set counts and triggers share --
and "Similar records" on an object. Never a classified input (D3), only
for someone who may read every input, no vector or score ever served.
Since 18 October: any embedding server through the OpenAI-style
/v1/embeddings request, and the task prefixes nomic-embed-text's card
requires (missing from the first version); and a search_meaning step
for Query's agent behind `agent.meaning_search`, through the same rules
Browse ranks by -- not yet measured on a real model, as the other
switches were (scripts/llm_bench.py); and smaller vectors through
`llm.embedding_dimensions`, whose cost in quality on a deployment's own
data is unmeasured. Its use for statistical
matching and enrichment is not built.

**MODEL PREDICTIONS: THE FIRST LEVEL IS BUILT** (R48; the owner, 18 October: all
three levels -- a prediction per record, forecasts of totals, learned
checks -- with scikit-learn, retrained when gold is rebuilt, and the
score broken down by a group the approver chooses). A field declares
`predict: {of, from, chance_of?}`: the chance of one answer, the most
likely answer, or a likely number, filled only where the answer is not
known, never from or about a classified field, readable only by someone
who may read the answer and every input, and marked "predicted from …".
Training and measuring are built: a fifth of the known records held out,
skill against the naive guess, the score per group, which inputs
matter, and a warning when a score is too good to be true.
`scripts/propose_prediction.py Type.field --group-by F` measures and
proposes; Inbox → Predictions approves, refusing anything no better than
the naive guess or without its group breakdown. ONE MODEL PER SECURITY
COMPARTMENT (the owner, 17 October): a guess must not be shaped by
records its reader cannot see -- Foundry's "mandatory controls propagate
through derivation" -- so each is learned from one compartment, fills
only it, and is approved by someone in it. Learning across compartments
would be a deliberate, per-field owner opt-in; not built, and worth it
only if a compartment proves too small. Once approved, gold trains the
model again whenever it is rebuilt -- and only then -- measures it again,
and fills the field only if the skill is above 0 and within 0.05 of the
approved one (a judgement, not a measurement); otherwise it stays empty
and the run log says why. An answer resting on a prediction says so, by
code (R63). Not yet measured on a real deployment's records.

**FORECASTS OF TOTALS ARE BUILT** (R68; the owner, 18 October:
statsmodels, triggers on totals per period, no approval). A date field
is counted or summed per day, week or month and drawn as a line in
Browse, the period still running marked "so far"; a Forecast switch
extends it, dashed, with an 80% range -- exponential smoothing in the
form AICc chooses, tested from four past points against carrying the
last period on, and not drawn when it does not beat that. Worked out per
request from what the viewer may see, so it crosses no compartment and
is never stored. A trigger may watch a view "per week, projected above
50": told once when the forecast line -- not the top of its range --
passes the line, as each recipient from their own totals, and silent
while the forecast is not trusted. Checked when triggers are, not at the
turn of a period with no new data. Not yet measured on a real
deployment's records.

**UNUSUAL RECORDS ARE BUILT** (R51; the owner, 19 October: shown to
every reader of the fields and queued for review, judged within context
by a published cut-off). A type declares `unusual: {numbers: [amount],
within: [category]}`; each number is compared with the records sharing
its `within` values, per compartment, by Iglewicz and Hoaglin's modified
z-score above 3.5 -- chosen over an Isolation Forest after measuring both
on planted oddities: the forest flagged 48% of records at its default
threshold, changed its picks with the random seed, and missed most
amounts ordinary for the table but wrong for their kind, all of which
the within-kind score caught. Found when a type's gold is rebuilt, at
most 50 per type and compartment, each with its reason in words.
Marked on the row and under the field in Browse for whoever may read the
type, the number and every field it was compared within, in the
compartment it was judged in; decided in the Inbox's Unusual tab by
someone who may also edit the type -- "expected" clears the marker for
everyone until the value changes, "worth a look" keeps it -- each
decision audited. What is left needs a person: LLM-WRITTEN RULES, the
other half of R51, need a decision on what a rule may say and who
approves one. A calibrated cut-off
(conformal, as the merge thresholds are) needs records known to be
normal; people's "expected" decisions will be that set.

**NOT BUILT, BY THE OWNER'S CHOICE (18 October)**, each with what would
change that:

- A SEPARATE VECTOR SERVER (Qdrant was the design: Apache-2.0, a single
  program, filtering by compartment while it searches, Elysium's own
  access check still deciding). Not worth running at this size --
  "built for the sake of being built". Exact search in-process measured
  10.8 ms a question at 100,000 rows of 768 numbers, 38 ms at 500,000
  of 512, 52 ms at a million of 256; speed does not force it. MEMORY
  would: every server process holds its own copy of the vectors (977 MB
  at a million of 256), where a vector server holds one. Revisit when a
  declared table nears a million rows, or several processes each hold
  a large copy.
- AN MCP SERVER, letting outside language models call Elysium's search
  as a tool. Waits on D3 -- whether Elysium's data may reach a model
  outside this machine at all -- since that is its whole purpose. If
  built: every call as the asking person, under the same access checks
  as the routes; MCP's own record (tool poisoning, CVE-2025-6514, the
  NSA's May 2026 note that its spread "outpaced the development of its
  security model") is the reason to start from that rule.

**STATISTICAL MATCHING HAS ITS YARDSTICK** (R59, 15 October):
`scripts/evaluate_matching.py` measures the matcher against synthetic
copies, a labels file or reviewers' decisions, with intervals. Its first
run on the development deployment found recall of 0% at the review
threshold -- comparison is exact-match only, so one typo loses a
duplicate -- and an auto-propose threshold two compared fields can
never reach.

**PRE-SELECTION IS CALIBRATED** (R57, decided and built 15 October):
reviewers' rejections calibrate `auto_propose_above` only, leaving out
pairs shown pre-selected, at a declared `false_merge_rate`; the
Identity screen says UNCALIBRATED until there are enough. The cascade
gets NO LLM stage (owner, 15 October): fuzzy comparison levels first,
an LLM only if the harness shows a band they cannot settle, and then
as a note on the card, never a score.

**THE CASCADE IS BUILT** (R56, 15 October): rule, blocking, scoring with
an optional CLOSE level per field, a person. Recall on the development
deployment's copies went from 15% to 65% at the review threshold. One
edit is the default because two halved precision on a crowded
population -- a deployment allowing more should run the harness on its
own rows first.

**WHICH SOURCE TENDS TO BE RIGHT IS SHOWN, NOT APPLIED** (R60, 15
October): when two sources' disagreement ends, the one that changed to
match the other is recorded; the Provenance panel shows a rounded share
from ten such endings. Where three or more sources hold a field, they
vote, with a source that looks like a copy of another counted once.

**AN ANSWER RESTING ON AN INFERENCE SAYS SO** (R63, 15 October): the
model is told which values were inferred and how their rules scored,
and code appends a note naming them to every such answer.

**Statistical matching is done** (R56, R57, R59, R60, R63).

**Blocked on:** nothing for the plugin API (item 3), which is next.

## 3. A plugin API, and the reason module federation is not it

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

## 4. Triggers: both questions answered and built, 16 October

Kept as the record of what was decided, with the precedent.

**Four-eyes against an automation -- EACH ACTION DECIDES.** An
automation proposes as its owner, so under a four-eyes rule the owner
cannot approve it, and that stays the default: GitHub closed the same
loophole after people used their automations to "satisfy the 'Required
approvals'" rule with code "that no other person reviewed". An action
declaring `owner_may_approve_automation: true` lets the owner's review
suffice for what a condition proposed (the automation stands as the
proposer for the user_id comparison only; role and compartment stay
the owner's). Refused beside `automatable: false`. The Watch dialog
says, while an action is being chosen, when each proposal will need
someone else.

**Evaluation cadence -- WHEN WHAT IT COUNTS CAN HAVE CHANGED.**
Revised twice the same day with the owner. A count changes when its
data changes or when a record crosses the edge of a date window, so:
every trigger after each sync; the triggers watching the types a saved
change wrote, straight after it; a new trigger when it is made; and a
date-filtered trigger at the moment a record next crosses its window,
by a TIMER it sets after every evaluation (core/trigger_windows.py).
Foundry's live monitoring runs "within minutes of an object change
appearing in the Ontology" and cannot monitor "relative time
conditions", which fall back to a schedule; a timer at the crossing is
sooner than any schedule and idle in between. The fifteen-minute clock
of the first two versions is gone, and its settings are refused.

**Timers -- ONE SERVICE, decided with the owner 16 October.** Anything
that must act AT a time registers "call me back then" (core/timers.py)
rather than growing its own loop; one loop in the server fires them
(api/timer_service.py), persisted, keyed, at least once, retried then
dropped -- Temporal's durable timer at the size of one table. This
reverses, for this one purpose, the project's two refusals of a
standing loop in the API process for RARE work: proposal expiry,
session expiry and "the sync has not run" stay checked on read, where
noticing late loses nothing. A notification written in the server now
also reaches its recipient's open tabs at once, as a data-free "your
inbox changed" signal on the live-updates stream.

**Timers people make -- REMINDERS, decided with the owner 17 October.**
Once, or repeating (every N minutes, or weekdays at a time in the
owner's zone, staying on their clock across a daylight-saving change;
optionally until a moment), listed and cancelled by their owner alone,
in Inbox -> Notifications -> Reminders. Each timer carries HOW LATE IS
TOO LATE (Quartz's misfire instructions, Kubernetes'
startingDeadlineSeconds): a reminder more than an hour late, by default,
is reported missed rather than delivered as if on time, and a repeating
one catches up at most once -- the latest occurrence still in time is
delivered, the earlier ones counted. Trigger timers fire however late,
because they re-check current state. Each occurrence carries a key, and
the notice it writes uses it, so a firing delivered twice is one
notice. 100 per person; repeats no more often than every 5 minutes.

**Combined triggers -- built 17 October** (core/trigger_states.py):
all or any of up to ten conditions, each one of the owner's views above
or at most a count (Datadog's composite monitors, no nesting); true for
at least a while (Prometheus' `for`), on time by a hold timer; or
checked only on a schedule and told every time it is true then (Foundry
Automate's combined time and object conditions), a missed check said.
Conditions are STATES: gaining and losing stay single. Each person's
own state and latch -- fires once when it becomes true, a baseline when
made. Notify only for now: which objects an action would receive from
several views is not decided -- REVERSED the same day: they propose
too. The maker names which condition's view supplies the objects (its
own by default), Foundry's "the type of the action parameter needs to
align with the type of the exposed condition effect input"; proposed as
the owner when the owner's state fires, less what already waits.
Declared triggers in config.yaml do all of it too (`also:`, `combine:`,
`hold_minutes:`, `schedule:` with `timezone:`, `action: objects_from:`),
checked at load by the same rules; their schedules are set at start and
after each reload, and cancelled when removed.

**Queue flooding (R50)** was decided and built 14 October, and the cap
on how many objects one proposal may name is bulk actions' (256 unless
a deployment says, 1,024 at most).

**Blocked on:** nothing.

## 5. What the interface should be

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

**THE REDESIGN IS UNDERWAY, decided 14 October**: foundations first,
then the shell; dark by default; the agent inside Browse AND in Query;
one Inbox. Built so far, each checked in a real browser:

- DEV_UI 8.3's navy palette and Blueprint retinted onto it, IBM Plex
  self-hosted, 9.5's radii, elevation by step, a dot on every state.
- One DataTable for every table -- hairlines, hover, sticky header,
  right-aligned numbers, no zebra -- with the reader's row density
  (9.3) in the user menu; Browse's results are a real table.
- The four states: loading by expected wait (a skeleton after a second,
  rows dimming under 1s), EmptyState requiring a reason.
- One Inbox with three tabs, a count in the header (15.3), and each
  object in a write under review a door to its page.
- "Ask about this set" as a panel in Browse sending the set itself.
- 15.3's approvals ergonomics: no approve without the diff open, sort
  by consequence, a pending marker on the object and on the set.
- Notification rows as doors to the objects they concern; sortable
  DataTable headers.
- The E4 partial state as one component (FieldValue): "Not permitted"
  and a real null look different on every surface. "Restricted" -- a
  readable field withheld for one object -- is deliberately NOT a third
  state: MAC withholds whole objects, and a link to a hidden object
  reads as null, because marking it would disclose that it exists.
- The command palette beyond "go to": object types, saved views, the
  actions on the object in front of you (greyed with the reason when
  your role may not run one), the shell's own settings, and a search
  of each type for whatever was typed. Scoped to where you are, as
  GitHub's palette is.
- Section 14's ontology canvas: layered (dagre), orthogonal edges, a
  moved type kept per person apart from the declaration, actions as a
  count on the type, subject areas (the ontology's own groups offered
  first), and security chains on a layer for manage:roles.
- 13.3's "who can see this?", on each type's card in the Object types
  catalogue, for manage:roles: per role, its people, whether it reads
  the type, which fields it reads, only knows exist or cannot see, and
  which actions on the type it may run; and which OBJECTS a person
  sees, as one sentence followed through any compartment chain. Asked
  of visible_schema per role, so it cannot disagree with what people
  are served.
- 13.5's "what would this change do?", on the Roles screen: a change
  in ACCESS terms ("can now read Account", "can no longer read
  Customer.email", "can now run UpdateCustomerName", and how many
  people hold the role) -- previewed under the editor as grants are
  ticked, and on every waiting change for the approver. Gains carry the
  warning colour (13.6). The proposed grants are compiled as the
  mediators compile them, so a label grant shows as the fields it opens.
- 13.7's describing the ontology, from the schema map's preview and each
  type's card, for manage:deployment: a type's name, plural,
  description, group and title field, and each field's name and
  description, written to ontology_schema.yaml line by line with every
  comment kept, the loader run on the result before it lands, reloaded
  and recorded as a generation. Applied at once (decided 16 October):
  it changes what things are called, not who sees what. The allowlist
  is the server's and cannot reach `security`, storage or a field's
  type.
- Access labels on fields, from the same places, decided 16 October: a
  change that lets anyone read, know of or run more -- asked of the
  permission code, NOT of the edit's direction, because with enforcement
  on, ADDING a label opens a field to a role holding that label's grant
  -- waits, with a reason, for a holder of manage:roles who did not
  propose it (Foundry: removing a marking needs "the Expand Access
  permission on the marking itself"; Purview asks a reason to lower a
  label). Anything else applies at once, which with enforcement off is
  everything. The approver sees, on Roles, who asked and why, what it
  does to each role recomputed against what runs now, and the exact
  lines; a file moved since is STALE, refused rather than merged.
- "Put this version back" on configuration history, decided 16
  October: a version's files written back as a NEW generation (Grafana,
  Terraform: history grows, never rewinds), at once unless anyone could
  read more -- then the same queue and the same second person as a
  label. The preview shows the ontology's lines and only NAMES any other
  file, as /admin/config-history always has, because data_silos.yaml
  says where each source is. Refused rather than half-done: a field's
  data type going back (the lake cannot follow without a rebuild), a
  file that would have to be added or deleted, or nothing to do. Roles
  in the role store are in no version, and it says so.
- STILL TO DESIGN: the ontology's shape (a new type or field, a data
  type), which also touches bindings and the mirror.

THE NODE NOW CARRIES 14.5's COUNT AND HEALTH, and properties at close
zoom (16 October): how many objects of the type the reader can see
(GET /me/type-counts, one request, MAC applied, readable types only),
a dot for whether its data is current against its own window (from
/data-freshness: fresh, later than expected, overdue, a ring for never
published, nothing for exempt), and from 1.5x its fields, the key
first, in place of the summary -- the box keeps its size, because rows
are 40 apart and a taller box would land on its neighbour.

WHAT THE CANVAS DOES NOT DO YET, each buildable: edges are not routed
AROUND other types, so two types dragged far apart can draw a line
across a third ("Auto-layout" undoes it); and the layout is per person,
with no deployment-wide default -- small, and not yet asked for.

**Blocked on:** nothing.

## 6. Agent-loop efficiency, which needs a machine with a model

`IDEAS.md`'s open investigations all need traces from a real model on
real hardware. The measurements already taken are kept because
re-taking them costs an afternoon of somebody's GPU.

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
search-result cap (AL-3, item 9), a free-text `search_text` step
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

**Blocked on:** two runs --

    python -m scripts.llm_bench --features free_text_search,remember_from_query --cases count_by_aggregate
    python -m scripts.llm_bench --features none --cases dependent_choice --show-steps

The first says whether the correction rescues count_by_aggregate with
both switches on; if it passes, free_text_search and remember_from_query
ship, and search_result_cap (20) with them. The second prints every step
and nudge of the baseline regression, which is what diagnosing it needs.
Beyond that, nothing on this hardware: a GPU, or a larger model, would
reopen plan mode and constrained decoding.

## 7. Context rot, and a 10,000-id search behind it

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

**THE CAP IS BUILT AND OFF** (`agent.search_result_cap`): over it, the
model is shown the first N ids, the exact total, and a note naming
`aggregate_object` or a narrower filter -- the alternative the
MAX_OBJECT_IDS story below says a bare limit fails to offer. The
feature bench's `cap` arm runs the original seven under a cap of 1, the
only cap that truncates anything on the fixture data.

**Blocked on:** a model to validate the cap against (the feature
bench's `cap` arm is the first half of that), and the
`agentic_loop.py` comment beside `MAX_OBJECT_IDS` says exactly why
that matters: told its limit was 20 when given 32 ids, a real model
"came back asking for TWO, then spent the rest of its hops fetching
one object at a time until the duplicate guard stopped it". A cap
chosen without measuring is how that happens again.

## 8. Who can read Elysium's copied data without going through Elysium

**REWRITTEN 19 October, with the owner.** This item was "PostgreSQL
row-level security for MAC": push the row check into the customer's
database so it held for any caller. It does not fit how Elysium works.
Questions are answered from Elysium's own copy (GOLD-9); the only thing
that touches the customer's database is the sync, which must read every
row to make a whole copy -- Fivetran tells its customers to grant its
account BYPASSRLS for exactly that reason. A policy in the source would
bind the sync and nobody else. Foundry draws the line the same way: its
restricted views enforce rows on Foundry's copy, at read time.

**What was built instead:** the sync now asks PostgreSQL whether
row-level security applies to its own account on each table, and warns
-- in the run and on Admin -> Mirror -- when it does, because PostgreSQL
with no policy for that account "returns no rows without raising an
error" and the copy would be silently partial.

**What remains, and is this item now:** the copy itself. The mediator
applies the row check to everyone who asks through Elysium; anyone who
can read the lake's files on disk gets past it. Today file permissions
(the sync warns on a mirror directory others can read) and disk
encryption are what stand in the way. Whether that is enough, or the
lake's files need their own per-compartment protection, is the
question.

**Blocked on:** a decision about the threat -- who, beside Elysium,
can reach that disk.

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

## 9. Compliance: SOC 2, ISO 27001, HIPAA, and a penetration test

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

## 10. Owning the UI kit, and when to start

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

## 11. The simulator as Elysium's live test, and five kinds of source

**AGREED WITH THE OWNER, 19 October.** Mostly built since: Elysium reads
all five kinds, and a running world can be operated from outside it
(item 12, step 1). What is left is the control panel as a page.

**THE SIMULATOR STAYS OUTSIDE ELYSIUM.** `sim/` operates real
PostgreSQL, MariaDB, SQLite, CSV-folder and REST sources for a
simulated organisation, changing their contents on a clock and their
structure on a schedule. Its founding rule -- "the databases are the
only interface", and it "does not import [Elysium], depend on it, or
know it exists" (sim/README.md, sim/AGENTS.md) -- is kept: an Elysium
that controlled the world it reads would know a rename was coming,
and a product shipping a way to create and alter databases is a
product with one more door. So:

- A CONTROL PANEL SERVED BY THE SIMULATOR ITSELF, its own page on its
  own port: start and stop, speed, choose a pack, and each database's
  connection details to copy. THE CHANNEL UNDER IT IS BUILT
  (sim/simulator/control.py, 20 October): POST /control on loopback
  with a token kept in an owner-only `control.json`, carrying status,
  pause, resume, advance, live drift, outage and restore per source, and
  the oracle as JSON; `simulator pause`, `outage ops` and the rest send
  to it. The page is what remains, and it would call the same commands.
  It may borrow Elysium's look; it is not part of the product.
- Elysium keeps reading only the databases, wired by an ordinary
  `data_silos.yaml`.

**THE SIMULATOR AS A LIVE TEST OF ELYSIUM.** Point a deployment at a
running world and check, from outside, that what Elysium serves follows
what the world did -- rows that arrive, change and vanish, and the
drifts a pack schedules or an operator applies live. The
simulator's own oracle (`verify`, `watches`) is the yardstick.

**ELYSIUM SHOULD READ ALL FIVE KINDS** -- PostgreSQL, MariaDB, SQLite,
CSV files and REST. Since 19 October PostgreSQL and MariaDB are read
through the SQLAlchemy adapter, checked against the simulator's real
servers and tested against real ones (tests/postgres_server.py,
tests/mariadb_server.py): read-only sessions, a server-side time limit
on both, a column's time zone reported as part of its type. A FOLDER OF
CSV FILES since 19 October too (`adapter: csv_folder`): each table's
files chosen by a pattern, `latest` or `combined`, a broken line
stopping the table by name -- checked against the simulator's weekly
supplier files, which matched the till's own rows exactly. And a REST
API (`adapter: rest`), with declared pagination, retries that honour
Retry-After, and a refused login stopping at once -- checked against the
simulator's bookkeeping API, whose 26 invoices matched its PostgreSQL
exactly. ALL FIVE KINDS ARE NOW READ. Writes reach SQLite alone.

**Found on the way, both closed:** a live drift crashed the running
world on its next write -- fixed 20 October, the simulated business now
follows renames and drops (sim/simulator/lineage.py); and shared
reference data is now declarable (`security: unrestricted`,
SECURITY_ARCHITECTURE.md).

**Blocked on:** nothing but order: the page comes after item 12, whose
runs will show which controls an operator actually reaches for.

## 12. Make the simulator's sources behave like real ones, then run Elysium over it

**AGREED WITH THE OWNER, 19 October.** Next up once the item above
(five kinds of source: CSV and REST still to build) is complete. Two
halves, in this order.

**1. Polish the simulator until each source behaves authentically.** For
each kind it operates -- PostgreSQL, MariaDB, SQLite, a CSV drop folder,
a REST API, and a lagged replica (`replicates:`) -- research how the real
thing behaves, probe the simulated one, and close the differences.
Research first, from primary sources (vendor documentation, the
connector guides of Fivetran, Airbyte and Foundry), then write the
expected behaviours down as the checklist the probes are run against.
Starting points, each to be confirmed by that research rather than
assumed:

- *Server databases:* real accounts and grants (a SELECT-only reader, an
  owner, row-level security that can be switched on), idle-connection
  limits, statement time limits, isolation and what a long read sees
  while writes continue, server-side defaults (time zones, collation,
  charset), types as each engine reports them.
- *Schema change:* renames, drops, added columns and changed types, both
  scheduled in a pack and triggered live -- today a live `simulator
  drift` crashes the running world on its next write to a moved column,
  and no shipped pack declares `migrations`.
- *CSV drops:* how real exports arrive -- partial files mid-write,
  late and duplicate files, encodings and byte-order marks, delimiters,
  quoting, header changes, Excel-style dates.
- *REST:* authentication and expiring tokens, page and cursor pagination,
  rate limits with 429 and Retry-After, transient 5xx, eventual
  consistency, changed response shapes.
- *Operations:* a pause (missing), outages and slow responses on demand,
  and the control panel this file's item above asks for.

Each difference found is fixed in `sim/`, keeping its founding rule:
the databases are the only interface, and it does not know Elysium
exists.

**2. Run Elysium over it, and debug both.** Point a deployment at a
running world covering every kind, sync on a schedule while time passes
and the pack's changes land, and compare what Elysium serves against
the simulator's own oracle (`verify`, `watches`). Every disagreement is
a bug in one or the other, and is fixed where it lives. The runs on 19
October already found four in Elysium and one in the simulator: a
column's time zone dropped from its reported type; a rename recorded as
a plain success; an empty read whose refusal advised accepting the
deletions; row-level security hiding rows silently; and the live-drift
crash above.

**Progress, 20 October.** The checklist is `sim/docs/REAL_SOURCES.md`.
Step 1 of the order agreed for it -- the simulator's own bugs and
controls -- is done: a world now has a control channel (`control.json`,
owner-only, never in `connections.json`) with pause, resume, advance,
live drift, per-source outages and the oracle as JSON; a live rename no
longer crashes it, because the simulated business follows renames and
drops (`sim/simulator/lineage.py`) and keeps that record across a
resume; migrations no longer repeat after a resume; MariaDB no longer
reads the host's configuration; the REST rate limit rolls over and
says when; and, found in review, a world with a replica can be
resumed at all. One behaviour changed on purpose: a pack migration that
drops a column its own events still write used to crash the world, and
now the business stops writing it, as an application shipped with its
migration does.

**Step 2 done, 20 October: realism options per source**, each a pack
option, off unless set, so existing packs read exactly as before. REST:
expiring client-credentials tokens, server errors and latency at a set
rate, an If-Modified-Since filter. CSV drops: a Windows code page,
semicolons and decimal commas, Excel's own conversions, reordered
columns, zips, half-written, re-sent, late and expiring files.
PostgreSQL: no default privileges for later tables, row-level security
with no policy, statement and idle limits on the reader. MariaDB: idle
and statement limits on consumer accounts, zero dates. Both servers'
time zones are now pinned to UTC rather than the host's. A replica must
run its source's engine. Next: step 3, Elysium over a world with all of
it on.

**Step 3 begun, 20 October: Elysium over a world, and what it found.**
`scripts/live_world.py` starts a world as an operator would, configures a
deployment from its `connections.json` alone, and each round syncs and
compares every object type with an independent plain reader of the same
source, and the watched totals with the simulator's oracle. Over
field_service and retail with every realism option on -- expiring tokens,
API faults and an outage, Windows-encoded, semicolon, decimal-comma,
zipped, Excel-saved, reordered, re-sent and late files, zero dates,
row-level security, a column dropped mid-run -- every table ends in
agreement or in a refusal that names its reason. (Half-written files
were on too, but no round happened to meet one; see the limit below.)
What it took:

- Elysium: a deployment reading anything but SQLite without a
  `write_targets` line failed to LOAD ("Unknown adapter type 'rest'");
  the API reader had no login for tokens that expire (OAuth client
  credentials, added); the CSV reader could not open a zip or gzip
  (added); a first sync under row-level security with no policy
  PUBLISHED AN EMPTY TABLE, the warning in the log its only sign
  (refused now); MariaDB's zero dates refused a whole table with no way
  through (`zero_dates_as_null: true`, declared per silo); and the
  refusal of a time with no zone did not say to declare one.
- The simulator: a replica did not carry its source's grants, so
  withheld pay lines were readable through `office`; and `zero_dates`
  wrote none for the columns an application leaves out.

**Decided 21 October, with the owner, after the precedent:**

- A suspected rename -- a column the ontology reads gone, and a column
  that was not there last sync arrived -- HOLDS the table at its last
  good copy, saying why, until the field is repointed or removed.
  Fivetran and Airbyte carry on by default, but Fivetran keeps the old
  values and blanks only new rows; Elysium serves the current state, so
  carrying on blanked every row. dlt's `freeze`, Auto Loader's
  `failOnNewColumns` and Airbyte's "Pause connection" stop instead.
  `on_suspected_rename: serve_empty` in config.yaml is the old answer.
  ONE RENAME IS NOT CAUGHT: one made in two releases -- the new column
  added and filled in one, the old dropped in the next. By the drop the
  new column is not new, and cannot be told from one that was always
  there, so the field is served empty as on a plain drop; the sync's
  message names the undeclared columns its values may be in. An API
  source never holds, since a key it leaves out may only be null.
- A CSV ending part-way through a line is REFUSED, the table keeping its
  last good copy: cut inside its last value, nothing else about it looks
  wrong. No tool found does this check -- the precedent says the reader
  cannot be sure and the writer's write-then-rename is the defence -- so
  a silo whose writer never ends its last line says
  `allow_unterminated_last_line: true`. "Done" marker files, the next
  best defence, are not built: no deployment has asked.

**Next in step 3:** longer runs, the pack-scheduled migrations, a
SQLite source (no pack declares one), and the replica's lag.

**Blocked on:** nothing; in progress.
