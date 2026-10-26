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
| `Triggers` (item 4) | all of it built, 14-17 October: four-eyes per action (`owner_may_approve_automation`), evaluation after each sync and at a date window's crossing, one durable timer service, reminders with how-late-is-too-late, combined triggers, queue flooding. Checked 26 October against `core/timers.py`, `core/trigger_windows.py`, `core/trigger_states.py` and `api/timer_service.py`, which already carry the precedent (Temporal, Quartz, Prometheus, Foundry Automate, GitHub's four-eyes loophole). Nothing was open |
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

**DECIDED 26 OCTOBER, by the owner:**
- `D3` and `AR-9` -- NO. A question never leaves the VM for a hosted
  model, and no escalation path is built. A deployment may still run a
  whole different model; that is its own choice. Recorded in
  PRINCIPLES.md section 4.
- `D6` and `AR-10` -- NO. Elysium does not fine-tune on its own
  traces, which hold customers' data.
- `E-21` -- left to the owner: the repository and the LICENSE stay as
  they are, and the owner decides when to change either. Nothing
  waits on it.
- `Q1` -- GDPR and UK GDPR, and HIPAA. SOC 2 and ISO 27001 are not
  declared. What this changes is in the compliance item below.

**Still the owner's, and measurements rather than opinions**
- `D1` -- switch phi4-mini to Qwen3-4B-Instruct after the bench? The
  shipped config is still phi4-mini. A MEASUREMENT (19 October):
  `python -m scripts.compare_models phi4-mini <other>` runs the bench's
  seven questions on each, answers included, and tabulates how many
  each got right and where a whole question's seconds went -- steps
  and answer, reading and writing, as the server reported them.
- `D2` -- stay on Ollama, or run llama-server? The OpenAI-compatible
  adapter already reaches it, and reads its timings; prompt caching
  (AR-3) and speculative decoding (AR-8) need it -- llama.cpp's n-gram
  drafting (`--spec-type ngram-simple`) needs no second model, and
  suits replies that copy names and values out of their prompt. Run
  compare_models once per server, with --config naming each. BOTH WAIT
  ON A MACHINE with a capable model (the agent-loop item below).

**Access, and what a person sees**
- `R47` -- review of inferred special-category data (health, religion
  and so on). The one part of D5 not decided. HIPAA and GDPR's special
  categories, now declared under `Q1`, are the reason to decide it.

**Blocked on:** `R47`, and the machine that `D1` and `D2` need. None blocks building anything else.

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
words are NOT BUILT, BY THE OWNER'S CHOICE (26 October): each needs its
own rule on what "relative to" means and how wrong it may be, and
nothing asks for them. SEARCH BY MEANING (R45, 17
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
is NOT BUILT, BY THE OWNER'S CHOICE (26 October): the rule stays
absolute, to be reopened only if a compartment proves too small to
learn from. Once approved, gold trains the
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
decision audited. LLM-WRITTEN RULES, the other half of R51, are
NOT BUILT, BY THE OWNER'S CHOICE (26 October): the measured score
stays. A calibrated cut-off
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
  as a tool. DECIDED NO (26 October, with D3: a question does not leave
  the VM), since reaching an outside model is its whole purpose. If the
  owner ever reopens D3: every call as the asking person, under the same
  access checks as the routes; MCP's own record (tool poisoning,
  CVE-2025-6514, the NSA's May 2026 note that its spread "outpaced the
  development of its security model") is the reason to start from that
  rule.

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

**Blocked on:** nothing. Every question this item held is answered
(26 October); what remains unmeasured is on a real deployment's records,
which is a machine and data rather than a decision. (The plugin API this
line used to say was next is item 3, done.)

## 3. Modules: a generic shell, and every sub-app an equal

**AGREED WITH THE OWNER, 21 October.** Elysium is a CORE -- sign-in, the
ontology and its security, the mirror and sync, the write path and its
approvals, audit, configuration -- and its API is the ONE API every
sub-app uses. Everything else is a module, and modules are equals:

- A SUB-APP FOR A SYSTEM COMPONENT (Query, Browse, Schema, Admin, the
  Inbox) has no server of its own; it is the GUI for core functions
  and calls the core API, management included.
- AN ADD-ON may bring its own server, run as its own process, which
  Elysium starts, watches, restarts and stops. Its frontend talks to
  it; both may call the core API.
- "SYSTEM" IS NOT A TIER. Management calls are permissions in the same
  API; any sub-app may declare them, and the signed-in user's role
  decides. No sub-app has code inside Elysium's server -- so loading,
  unloading and refreshing are live everywhere (Python cannot truly
  unload code: "restarting the entire process is the only generally
  reliable way to get a clean state").
- TRUSTED FOR NOW, as Backstage, JupyterLab and Grafana treat their
  plugins by default: in the page and sharing one React. The shell can
  only ADVISE which API a module declared; enforcement stays where it
  is, the user's role on the server. Untrusted third-party code needs
  the isolation layer below, later.
- CORE INTERFACE IS THE SHELL ONLY -- frame, sign-in, session, palette,
  the module manager and a SAFE MODE that loads no modules. All seven
  of today's sub-apps become modules, each failing safely when
  unloaded (approvals wait in their queue; links to an object page with
  no module to open it say so).

**THE GENERIC SHELL, `shell/` (`@shell/*`)**, a top-level package that
knows nothing about Elysium; Elysium and the simulator depend on it, it
depends on neither. Its backend contract is plain HTTP: the session
and how to sign in; a FEED of modules filtered for the user (id,
version, bundle address and integrity, shared-library versions,
static contributions -- Piral's feed service lists `name`, `version`,
`link`, `integrity`, `config`); change events; and enable, disable and
refresh, authorised by the backend. It replaces api/apps.py.

**DECIDED IN DISCUSSION:**
- CONTRIBUTIONS ARE STATIC, CODE IS LAZY: a manifest declares routes,
  navigation entries and commands -- VS Code's `contributes`, "static
  declarations" -- and the bundle's `activate(context)` runs when one
  is first used; `deactivate()` on unload.
- SHARED LIBRARIES ARE FIXED AT PAGE LOAD (React, the router,
  Blueprint, `@shell/*`, the backend's client), by import map: import
  maps follow "initialization is finalization". A module needing a
  version the page lacks is refused until a reload, and the module
  manager says why.
- SLOTS -- a module adding a tab or section inside another module's
  screen, Backstage's `attachTo` -- come later in step 1, after pages,
  navigation and commands.
- UNLOADING removes a module's contributions and unmounts it; the
  browser keeps its imported code until the next page load.

**BUILD ORDER:** (1) `shell/` and the contract, Elysium implementing
it, then the Schema graph as the first module through the feed, then
the module manager and safe mode, then slots; (2) the SIMULATOR as a
loadable sub-app with its own server -- first to test the API's shape,
then for simulation itself (it need not run without Elysium); (3) the
remaining sub-apps moved one at a time; (4) the sub-app API written
down and versioned from what (1)-(3) used.

**THE FRAME AND THE SUB-APP, agreed with the owner 21 October.** The
shell owns the FRAME -- the rail and the header. A sub-app owns
everything inside the content area: its own panes or none, its own
canvas, its own libraries. It touches the frame only two ways:

- DECLARED, for what appears in the frame, which the shell draws in its
  own style: rail tabs, palette commands, a badge on its tab, help
  text. No sub-app renders into the rail or the header.
- REQUESTED, for what the frame does: navigate, a notice or a
  confirmation, who is signed in, the page title, the theme, and
  FULL SCREEN -- which the shell grants, controls and always offers a
  way back from. A sub-app never hides the frame itself.

TODAY'S SHELL BREAKS THIS IN THREE PLACES, written before sub-apps were
modules; step 1.3 fixes them, and they are its test of being generic:
(a) the palette knows Browse -- `Shell.tsx` checks for `/browse` and
builds object-type commands, saved views and search suggestions itself;
they become Browse's declared commands; (b) the Inbox button and its
count are wired into the header -- the Inbox declares a tab with a
badge, and if it keeps a place in the header the shell offers that
place generically; (c) the shell is handed Elysium's schema -- a generic
shell does not know what an object type is.

**THE SHELL AND THE SERVER EACH HAVE A SYSTEM SUB-APP**, the hybrid
applied to the two central components. THE SHELL'S holds the frame's
controls: the module manager (load, unload, refresh), safe mode, which
tabs appear and in what order, the theme, and grants such as full
screen; the frame itself only draws what it configured. THE SERVER'S
holds Elysium's server controls: configuration and reload, silos and
the mirror, add-on processes and their logs -- much of today's Admin,
which splits into the server and people-and-roles.

THIS REFINES "SYSTEM IS NOT A TIER" AND "A SAFE MODE THAT LOADS NO
MODULES" rather than reversing them. System sub-apps are built like
any other and call the same API; they differ only in being PINNED: they
load in safe mode and cannot be unloaded from the interface, because
safe mode exists for when a module breaks the page, and a module must
not be able to take away the tool that fixes it. Safe mode therefore
loads the pinned system sub-apps and nothing else. The last resort is
still `modules.yaml`, from a terminal.

**THE LOOK: A BASELINE EVERY SUB-APP INHERITS, AND MAY OVERRIDE INSIDE
ITSELF.** Three layers: (1) DESIGN TOKENS -- colour, font, type sizes,
spacing, radii -- as CSS custom properties defined for light and dark,
promised as a public, versioned part of the API rather than internals;
(2) THE KIT -- table, chart, forms, empty, loading and error states --
built on the tokens, so a sub-app using it looks native for free; (3)
THE SUB-APP'S OWN overrides and libraries, scoped to its own root. Its
obligations: overrides derive from the tokens or supply both themes;
no global CSS, no styling of `body`; no reaching into another
module's DOM (that is what slots are for). VS Code is the precedent:
webviews inherit theme colours as `--vscode-*` variables and style
their own content freely, without touching the workbench.

**LIBRARIES: SHARED OR PRIVATE.** Shared libraries are the page's,
fixed by the import map (React, the router, the kit and whatever else
the API promises -- ECharts, Blueprint); a module uses those copies or
hooks and context break. Anything else -- a trading chart, a graph
editor -- a module BUNDLES PRIVATELY, loaded only when one of its pages
opens, so nothing Elysium does pays for it and Elysium never adopts a
domain library. Open for step 1.2: whether a module's bundle and assets
are served by Elysium from its folder or by an add-on's own server
through the proxy (self-contained, but needs the proxy).

**TESTING FOLLOWS THE LAYERS, agreed 21 October.** The shell is the
PROVIDER; each sub-app, system ones included, is an entity of its own
that uses the provider's API and has its own tests. Today all seven
sub-app packages already import only `@elysium/shell-api` -- none
imports another -- but none can test alone: one root config runs them
all under the host's `ui/src/setupTests.ts`, and 52 test files each
mock the API by hand. The layers:

1. THE SHELL (`shell/`) -- its own suite (it has one, 13 tests).
2. THE PROVIDER'S API AND KIT -- its own suite, and it SHIPS A TEST
   HOST: fakes for every declared and requested frame call and for the
   API client, so a sub-app's tests render inside a faithful frame
   instead of hand-mocking. Backstage's precedent exactly:
   `renderInTestApp` with `mockApis`, where a mock "returns a working
   fake" and its `.mock()` form makes "every method ... a
   `jest.fn()`".
3. EACH SUB-APP -- its own package, test config and setup (a preset the
   provider ships, carrying today's act-warning guard), runnable alone,
   depending only on the provider's public API and test host, never on
   the host app or another sub-app; including a check that its
   `module.json` is valid against the contract.
4. THE HOST (`ui/src`) -- composition only: the feed becomes routes and
   a rail, safe mode, the frame's grants.
5. THE FAKES ARE CHECKED AGAINST THE REAL THING. One conformance suite
   runs against the test host AND the real shell, so a fake cannot
   drift -- this project's oldest failure, "a fixture that does not
   match the API is a test that proves nothing". For the backend half,
   Pact's provider verification is the model: "each request generates
   a response that contains at least the data" the consumer described;
   Elysium's HTTP tests of the shell routes are that side today.
6. IN A REAL BROWSER, per sub-app, with fixtures the shell provides for
   the frame -- Grafana's `@grafana/plugin-e2e` precedent, whose APIs
   are "guaranteed to work with all the latest minor versions" so a
   plugin's tests need not track the host's markup.

**COMMON BEHAVIOUR IS TESTED ONCE, BY DEFAULT, UNTIL OVERRIDDEN --
agreed 21 October.** Measured first: the problem is less duplication
than GAPS. Of the seven sub-app packages, three test an expired
session, two a loading state, two an error state, four cleanup on
unmount -- the same behaviours, tested in some sub-apps and not others.
So the baseline is INHERITED, never copied: a template is copied once
and drifts, while an inherited baseline carries every fix to every
sub-app. A template (a generator, as Backstage's `new`) only STARTS a
package. Three inherited layers:

1. A CONFIG PRESET the provider ships -- environment, the non-UTC time
   zone, the act-warning guard (now `ui/packages/testing/src/setup.ts`), the test
   host -- which a sub-app's config extends in a few lines. Vitest's
   projects are the mechanism: options "are merged with the project's
   own options", and `setupFiles` "are concatenated, not overridden",
   so a sub-app adds its setup to the provider's. Backstage's CLI is
   the same shape: "a default configuration included in the CLI".
2. A CONFORMANCE SUITE generated from each `module.json` and run on
   EVERY PAGE IT DECLARES, ON BY DEFAULT -- Storybook's precedent, where
   "a basic story is also a smoke test" and every story carries the
   `test` tag implicitly. Candidate checks: renders in the test host;
   a loading state while the API is pending; an announced error when it
   fails; asks to sign out on an expired session; leaves nothing behind
   when unmounted; automated accessibility checks; no global CSS; a
   valid manifest.
3. THE SUB-APP'S OWN LOCAL TESTS, for everything specific to it.

OVERRIDES, from the same precedents. Each check is `error`, `todo` or
`off` -- Storybook's accessibility test: "'todo': Run accessibility
tests; violations return a warning", "'error': ... a failing test" --
set for all sub-apps, one sub-app or one page, the NARROWEST WINNING
(Storybook's tags cascade project, component, story, and `!` removes
one). `todo` and `off` need a written reason. A sub-app may SUPPLY A
CHECK'S INPUTS -- how to make its own API fail -- as RSpec's
`it_behaves_like "auditable"` takes a block providing the subject; or
REPLACE a check with a stronger test of its own, naming it, and the
suite verifies the named test exists, so the behaviour stays covered.
ONE REPORT lists every softened or replaced check and its reason, as
WITHHELD_FROM_CONFIG_RESPONSE does for the config panel.

THE SUITE IS TESTED ITSELF: a deliberately broken sample sub-app must
fail each check, or a check that cannot fail passes every sub-app for
ever. AND THE SAME SHAPE FOR ADD-ON SERVERS: Elysium ships a pytest
plugin of its HTTP-contract checks (health, stop within the deadline,
honouring the identity header) that an add-on runs against its own
server in its own repository.

ADOPTION, `todo` FIRST: the Schema graph adopts the preset and suite in
step 1.2, the rest as they move in step 3. An existing sub-app that
fails a check today starts with that check as `todo`, reason written,
listed in the report -- so the suite runs from the first day and the
list only shrinks. A NEW sub-app starts with every check at `error`.

An ADD-ON'S SERVER is tested in its own repository; Elysium tests only
the HTTP contract it offers add-ons. The Inbox, still in `ui/src`,
no longer imports its three queues (slots, step 1.5b) and can become a
package.
The Schema graph, the first separately built module (step 1.2), is
the first sub-app to run its tests alone.

**GENERIC SERVICES FOR ADD-ONS, from Heliograph's request (21
October), recorded with the owner.** Heliograph, a trading-signal
add-on, asked for sixteen features; checked against the code, most
have a base already. What is generic and worth building, by step:

- STEP 2, with the simulator, which needs each one: who the user is,
  told to an add-on's server (a signed header from the proxy); a
  SAME-ORIGIN PROXY to add-on servers that passes SSE and WebSocket
  upgrades through (Elysium keeps SSE for itself); a written
  LIFECYCLE contract (health, restart with back-off, logs, config and
  secrets at start, stop with a deadline -- sim/simulator's control,
  health and lifecycle are the precedent); POSTING TO THE INBOX for
  kinds the manifest declares, with the existing `dedupe_key`;
  declared permissions listed in the manifest for the role editor;
  a manifest field naming the contract version a module was built for.
- ASYNC AT THE EDGES, NOT IN THE CORE: request handling stays
  synchronous (audit context cannot leak between requests); add-ons
  have their own processes and loops. What they need: JOBS -- a record
  with owner, state, progress, cancel and result, outliving the tab
  (mirror sync's polled status is the base; its docstring's objection
  to "a job id nobody would poll" falls away once add-ons run long
  work); TIMER CALLBACKS to an add-on's server for its own kinds
  (`/api/reminders` is the one kind on HTTP today); and an EVENT
  SUBSCRIPTION -- tell an add-on's server when a trigger fires, a sync
  finishes or an object changes -- which Heliograph did not ask for
  and every add-on with a server would want.
- TIME-SERIES READS OVER WHAT ELYSIUM ALREADY MIRRORS -- still not
  infrastructure: no historian, no high-rate ingest, no store add-ons
  write into. `/aggregate` already buckets by day, ISO week and month,
  labelled by start, gaps honest, the filling period kept apart
  (`/forecast`'s `running`). To add: hour and minute buckets, a time
  zone, FIRST and LAST -- with min and max, a candlestick is first, max,
  min, last per bucket, so OHLC is generic -- several series at once, a
  declared time property per object type, `period` in the agent's
  aggregate step (the real gap for trend questions), and a tail cursor.
  NOT a type-wide as-of read from snapshots: erasure drops older
  snapshots "time travel included", and gold keeps 30 publications;
  per-object change history already answers "what did we know".
- THE KIT: a time-series chart (Browse's `OverTimeChart` promoted, with
  a time axis, several series and zoom), a virtualised table, forms from
  JSON Schema, a job panel. Later: a profile needing no model (storage
  is already SQLite; the mandatory `llm:` block is the gap).

What stays in an add-on is its domain: Heliograph keeps market data,
bars, indicators, its charts, strategies, backtests and signals. The
reply sent to its developer is "Building Heliograph for Elysium"
(PDF, 21 October).

**AND STILL TRUE FROM THE EARLIER DESIGN (THIRD_PARTY_EXTENSIONS.md,
consumed):** for UNTRUSTED code, module federation is the wrong answer
-- "a federated module runs in your page, in your origin" with the same
cookies and API access; the isolation layer is a sandboxed iframe
(`allow-scripts` WITHOUT `allow-same-origin`) speaking the same API as
JSON-RPC 2.0 over `postMessage`, as MCP Apps do ("all UI content runs
in sandboxed iframes"). A third-party data source is a SILO, and an
ontology fragment is DATA, not code.

**DEFERRED, by the owner:** separating the simulator from Elysium at
the code level (tests importing it, its contracts in pyproject.toml,
its controls in scripts/check_controls.py) waits until modules work.

**WHERE IT STANDS (21 October):** step 1's first part is built. `shell/`
holds `@shell/core` -- the contract (shell/README.md), the registry and
the routes -- and Elysium serves `GET /api/shell/session` and `GET
/api/shell/modules` from a `module.json` beside each shipped sub-app,
with `modules.yaml` choosing which load (core/modules.py). The rail and
every route in `ui/src/App.tsx` now come from the feed; the code is
still built into the page, found through `BUILT_IN_PAGES`. ONE CHANGE
OF BEHAVIOUR, on purpose: someone without `manage:users` who opens
/admin is now sent home, because the module is not in their feed --
before, the route existed for everyone and the panel refused inside it.

**STEP 1.2, PART A BUILT (22 October): THE SHARED LIBRARIES.** Decided
with the owner on 21 October: Elysium serves a module's bundle from the
module's folder; development loads the built bundle too (one path); the
shared set is the kit's own dependencies. `@shell/build` registers the
PAGE'S OWN copies (one instance, so the kit's module-level state is one)
and serves a shim per library through the import map
(shell/README.md). Proved in Chromium both ways: a separately built
module renders with the page's React, router, Blueprint and kit; the
same module with a private React throws and renders nothing
(ui/e2e/sharedLibraries.spec.ts). MEASURED COST: the first load went
from 131 KB to 229 KB compressed, because Blueprint's core and the
router are shared whole; libraries load lazily, so ECharts costs
nothing until a module asks; `@blueprintjs/icons` is NOT shared, since
sharing it put 1.4 MB on every first load (ui/src/sharedLibraries.ts).
FOUND ON THE WAY: `npm run dev` could not load @shell/core at all since
the commit adding it -- Vite answered 403 for ../shell -- now allowed and
tested against a real dev server (ui/src/devServer.test.ts).

**STEP 1.2, PARTS B AND D BUILT (22 October): THE SCHEMA GRAPH IS A
MODULE.** It builds its own bundle (packages/app-schema/vite.config.ts,
`@shell/build/moduleBuild`), Elysium serves it at
`/api/modules/schema/files/` -- only to someone the module is offered to,
only from its bundle's directory, a uniform 404 otherwise -- and the
shell's loader (`@shell/core/moduleLoader`) fetches it when /schema is
first opened, adds its stylesheet and mounts the page its `activate`
returns. Elysium's page no longer imports or depends on it; what it used
to pass as props it PUBLISHES through the kit's host store
(`@elysium/shell-api/host`), which a module reads with a hook. Checked in
Chromium against the real server, signed in: all 26 browser tests pass,
the ontology canvas's included.

FOUND BY THAT TEST, AND FIXED: the import map had never worked against
Elysium itself. It is an inline script, and the Content-Security-Policy
(`default-src 'self'`) refused it, so no shared library resolved; part A's
browser test used a static server that sends no policy. Now allowed by
its hash, recomputed when the built page changes (api/app.py). Part A
shipped with this -- harmless then, since nothing used the map, but every
page load logged a CSP error.

AND BY AN INDEPENDENT REVIEW, FIXED BEFORE SHIPPING: the browser imports
an address once per page, so a rebuilt bundle at the same address would
have been the old code -- the feed now adds a fingerprint of the file
(`?v=`); a module unloaded while loading could be activated with no
`deactivate` to follow -- now cancelled; a failed page retried and
remounted on every render -- now it stays until the feed is next
applied; module pages read empty host values in their first render --
now staged during the page's render; `react-router` itself was not
shared, so a module importing it would have had a second router.

DEFERRED, ON PURPOSE: INTEGRITY. A bundle served by Elysium from its own
disk gains nothing from an integrity check, and the import map is fixed
at build, before the server knows which modules are installed. It
matters when bundles come from elsewhere -- add-on servers, step 2 --
and is to be built then, with the map's `integrity` key (Chrome 127,
Safari 18, Firefox 138) written by the server.

**STEP 1.2, PART C BUILT (22 October): THE TEST BASELINE.** Three
inherited layers, as agreed. THE PRESET is `@shell/build/testPreset`
(generic: environment, the New York time zone, threads, timeouts, with
the measurements behind each moved there from `ui/vite.config.ts`); the
page and the Schema graph both call it, as Vitest projects of one run --
`npx vitest run --project app-schema` runs the module alone. THE KIT is
a new package, `@elysium/testing`: the provider's setup file (the old
`ui/src/setupTests.ts`, moved), the TEST HOST (`renderInTestHost`, the
shell's frame with the host values published; `stubServer`, the server
stubbed at `fetch` so one switch makes every call hang, fail or find the
session expired) and the CONFORMANCE SUITE, `describeModule({ folder,
activate })`: manifest, renders, loading, error, session-expired,
unmount (no interval or listener left running) and layered-css, on every
declared page. Overrides are `module.conformance.json`, levels todo /
off / replaced with a reason, the narrowest winning; a todo that passes
FAILS, so the list only shrinks; a replacement must name a test that
exists. Each check is shown to fail a sample page built to fail it.
`python -m scripts.conformance_report` lists every exception, and a
Python test refuses a bundled module with no conformance test.

THE SCHEMA GRAPH ADOPTED IT with two exceptions: `loading` replaced by
its own spinner test (its schema is the host's to load), and `error` as
todo -- its own reads (who can see each type, the descriptions) fail
silently and the graph never says something is missing.

FOUND BY THE SUITE ON ITS FIRST RUN, AND FIXED: the kit's `AsyncPanel`
showed a failure WITHOUT `role="alert"`, so ten panels across five
sub-apps never announced one. And a test that failed intermittently
(ObjectDetailPanel's slow-response race) resolved its promises outside
`act`; it failed on most runs of the file alone.

NOT YET BUILT, of the agreed design: a sub-app SUPPLYING a check's
inputs (the server is stubbed at `fetch`, which covers every sub-app
today, so nothing needs it yet); automated accessibility checks; the
fakes checked against the real shell (the frame calls they would fake
arrive with step 1.3); per-sub-app browser fixtures. The other sub-apps
adopt as they become modules, in step 3.

THE ADD-ON CONTRACT CHECKS ARE BUILT (23 October), the "pytest plugin"
of step 2: sdk/python/elysium_addon_checks.py, a class an add-on's tests
subclass -- health; the identity token honoured and a good one taken;
loopback only; SIGTERM ends it within its deadline with status 0;
standard input closing ends it. Elysium runs it against the example
add-on and against that add-on broken one way per check; the
simulator's panel runs it from its own copy.

**STEP 1.3, IN THREE PARTS, agreed with the owner 21 October:** (a)
the frame moves into `@shell/core`, looking and behaving exactly as it
did; (b) a module SUPPLIES palette commands and search suggestions from
its code, loading when the palette opens (VS Code's activation events),
and Browse's move out of the shell -- which also ends the shell being
handed the schema; (c) a rail entry declares a BADGE whose number the
module's code supplies, loading at startup, and the Inbox's count
becomes its badge. Decided: THE INBOX KEEPS NO HEADER BUTTON -- the rail
is present at every width, so its badge is on every screen, and the
header has no module slots at all; and Blueprint is the shell's peer
dependency, being a library the page already shares.

**STEP 1.3a BUILT (21 October): THE FRAME IS THE SHELL'S.**
`@shell/core/Frame` draws the rail, the header and the command palette
(the palette and its matching moved from Elysium's kit with it) and owns
their behaviour: grouping by subject, collapsing and its narrow-screen
rules, Ctrl/Cmd+B, Ctrl/Cmd+K, navigation commands. The host supplies
the brand, the header's actions, overlays, icons, its commands, the
loading fallback and the storage key. `ui/src/Shell.tsx` is now
Elysium's composition of it; its 96 tests with App's pass unchanged,
and the shell has 21 tests of its own for the frame, each behaviour
with a control. Styled by the host for now, through the frame's stable
class names.

**STEP 1.3b BUILT (21 October): BROWSE SUPPLIES ITS OWN COMMANDS.** A
module's manifest may name ACTIVATION EVENTS (`onPalette`; VS Code's
`activationEvents`), carried by the feed, refused by Elysium at load when
misspelt and ignored by the shell when unknown. Its code may return a
palette HOOK (`usePalette({ open })` -> commands before and after
navigation, and suggestions), which the frame mounts in a component of
its own the first time the palette opens. Browse's types, saved views,
actions-in-scope and searches moved from `ui/src` into
`packages/app-browse` (`palette.ts`), with the fetch-on-open; its
manifest names `onPalette`, and App imports its hook only when the shell
asks. VIOLATIONS (a) AND (c) ARE GONE: `Shell.tsx` no longer knows
Browse's routes, and the shell is no longer handed the schema -- Browse
reads it from the host values like any module. A Python test refuses a
module whose palette the page supplies without `onPalette`.

**STEP 1.3c BUILT (21 October): THE INBOX'S COUNT IS ITS RAIL BADGE.**
A second activation event, `onStartup`, activates a module as soon as
the frame is drawn; its code may return `useBadges()`, badges keyed by
the paths of ITS OWN rail entries (a badge for another module's entry is
ignored), each a count and words for a screen reader. The frame draws it
on the entry's icon, so a collapsed rail shows it, announces it after
the name ("Inbox, 3 waiting"), shows nothing for zero and "99+" above
99. The header's Inbox button is gone (the owner's decision); the
Inbox's manifest names onStartup and its `badges.ts` (now in
ui/packages/app-inbox, step 3) supplies the count. VIOLATION (b) IS GONE, AND WITH IT ALL THREE: `Shell.tsx`
holds nothing of any sub-app.

ONE WAY IN FOR BOTH: the host passes the frame the feed and an
`activate(module)` (`@shell/core/activation`) -- its bundle's
activation, or the host's own code for a module built into the page --
and the shell decides when, by the events the manifest names, and reads
`usePalette` or `useBadges`. This replaced 1.3b's palette-only prop
before it shipped. Checked in Chromium: the badge is drawn, on top and
inside the rail, open and collapsed.

FOUND BY THAT BROWSER TEST, AND FIXED BEFORE SHIPPING: the count's words,
first put in a visually hidden span, made Chrome name the entry
"Inbox , 3 waiting" -- it computes an absolutely positioned element as a
block of its own -- where jsdom gave "Inbox, 3 waiting". The entry now
takes an aria-label built from its own title when it has a badge.

AND IN THE PYTHON SUITE, which 1.3b's commit had not fully run: the API
test freezing the feed's key set did not know `activationEvents`; fixed
in that commit. A full run made while the browser tests and a build ran
beside it failed 67 tests and errored 208; rerun alone, 248 of the 249
it selected passed, the 249th being that key-set test -- load, not code.
The Python suite is best not run beside other work.

**STEP 1.4, IN FOUR PARTS, agreed with the owner 22 October.**
Precedent: Firefox's Troubleshoot Mode, which disables add-ons and is
temporary ("These changes are temporary"), entered from a menu or by
holding Shift; VS Code's extension bisect, which "starts the first round
by disabling all extensions"; Grafana, where installing a plugin is a
server administrator's power apart from configuring one. (a) the
shell's system sub-app, PINNED, with a Modules page; (b) SAFE MODE, this
browser only and temporary, loading only pinned modules, reached from
the user menu, from any "could not be loaded" message (a link -- it
never switches on by itself, the owner's choice) and at `/?safe`; (c)
the module manager CHANGES THE DEPLOYMENT -- on, off, order, home,
refresh -- by writing modules.yaml through the existing validated,
atomic, audited settings path, for manage:deployment; and (d) BOTH,
SEPARATELY (the owner's choice): anyone may also hide a tab for
themselves. The system sub-app sits LAST on the rail, under "System".
Per-person tab ORDER and full screen wait until after slots.

**STEP 1.4a BUILT (22 October): THE SYSTEM SUB-APP, PINNED.** Elysium
always loads its system sub-apps (`SYSTEM_MODULES`, today
`ui/src/system`), after every module modules.yaml names; modules.yaml
cannot list one, a module cannot take one's id, and a manifest cannot
pin itself -- the backend decides. The feed says `pinned`. The page is
the shell's, generic (`@shell/core/ModulesPage`): every module offered,
its version, its code (own bundle, or built into the page) and its
state in this browser, live from the loader. Offered with
manage:deployment; a browser-test user, `opsuser`, holds it.

FOUND ON THE WAY: the Schema graph's API names asked for Blueprint 4's
`--pt-font-family-monospace`, gone since Blueprint 6, and rendered in
the browser's default monospace rather than IBM Plex Mono. theme.test.ts
now refuses any variable a stylesheet reads that nothing defines.

**STEP 1.4b BUILT (22 October): SAFE MODE.** `@shell/core/safeMode`:
the page with only the pinned modules, in THIS TAB, until left -- the
switch is the tab's session storage, nothing on the server changes, and
other tabs load everything. Entering and leaving reload the page,
because a module's imported code stays until a reload (Firefox restarts
for the same reason). Reached from the user menu ("Reload in safe
mode"), the palette, a link in every "could not be loaded" message --
never switched on by itself -- and `/?safe`, read once at load and taken
out of the address. A strip above every page says so, with "Leave safe
mode"; the Modules page marks what it left out. Someone offered no
pinned module gets the frame and the way out. Checked in Chromium: the
reload, the rail reduced to Modules, persistence across a reload, the
way out, and a second tab unaffected.

**STEP 1.4c BUILT (22 October): THE MODULE MANAGER CHANGES THE
DEPLOYMENT.** For manage:deployment, on the Modules page: each module
on or off, up or down, where people land, saved as one -- through
`GET`/`PUT /api/shell/modules/arrangement`, which writes modules.yaml by
the same path as every configuration edit: the candidate loaded first
(home opening nothing is refused, nothing written), written atomically,
reloaded, put back if the reload fails, audited either way, and a save
against an arrangement that has since changed refused rather than
merged. It applies at once, with no second person: turning a module on
widens nothing anyone may read or run, every call still being checked.
Every open page notices on its next request (it carries the new
generation) and fetches the feed again; "Refresh modules" does the same
on request, which also loads a rebuilt bundle from its new address.
modules.yaml gains `disabled:`, marking which of the listed modules are
off -- in their place, so one turned on again comes back where it was.

FOUND ON THE WAY: YAML 1.1 reads a bare `off:` key as the boolean
false, so that name would have meant nothing in a hand edit -- the key
is `disabled`, and `off:` is refused by name. And the first format kept
turned-off modules in a list apart, so turning one off and on sent it to
the end of the rail; seen in a screenshot, fixed. The browser test that
saves an arrangement WRITES modules.yaml, so it runs only against a
server on a copy of the configuration, opted into with
E2E_MAY_WRITE_CONFIG=1, one test at a time.

**STEP 1.4d BUILT (22 October): YOUR OWN RAIL TABS.** Anyone can hide
a tab from their own rail -- "Your rail tabs…" in the user menu, applied
as ticked, remembered per person in this browser like the theme. The
RAIL ONLY: the palette still offers a hidden tab's pages and their
addresses still open them, so hiding never loses anything; pinned tabs
cannot be hidden, even by a preference that names one. The frame takes
the hidden paths (`hiddenPaths`) and the dialog is the shell's
(`@shell/core/RailTabsDialog`). Per-person ORDER waits, as agreed.

STEP 1.4 IS DONE.

**STEP 1.5, SLOTS, IN TWO PARTS, agreed with the owner 22 October:** (a)
the mechanism; (b) the Inbox as the first slot owner, with Approvals,
Notifications and Identity made modules of their own (the owner's
choice), each contributing its tabs, so each can be turned off on its
own and the Inbox stops importing them. The OWNER decides the order of
its slot (the owner's choice: the Inbox keeps today's tab order), and a
contribution it does not list follows in feed order. Precedent:
Backstage's extension inputs and `attachTo`; Grafana's extension points,
whose extensions must be listed in plugin.json.

**STEP 1.5a BUILT (22 October): SLOTS.** A manifest declares the slots
its pages offer (`slots: [{id, order?}]`) and its contributions to
others' (`into: [{slot, id, title, icon?}]`), statically, so the shell
and the module manager know every contribution without loading code.
Elysium refuses at load a contribution to a slot no module declares, a
slot declared twice, or a contribution declared twice by one module; a
slot whose owner is turned off keeps its contributions, unshown. The
owner draws its slot with `useSlot(id)` (`@shell/core/slots`), from the
modules the feed offers -- permissions and safe mode applying untouched
-- and each contribution's component comes from its module's code on
first showing, inside an error boundary of its own, so a failing one
says so in its place and leaves the page standing.

**STEP 1.5b BUILT (22 October): THE INBOX'S TABS ARE A SLOT.** The Inbox
declares `inbox.tabs`, with today's order; Approvals (four tabs:
Approvals, Enrichment, Predictions, Unusual), Notifications and Identity
are modules of their own -- shipped by default, no rail entry, each
switchable alone in the module manager -- and contribute them, their
code in each package's `contributions.ts` (since step 3, in each one's
own bundle). The Inbox no longer imports
any of them. A queue module turned off, or not offered, has no tab, and
the rest stand. A Python test holds every declared contribution to its
code and back. Moving the Inbox itself into a package -- the step this
file said slots would allow -- is now possible and not yet done.

STEP 1.5 IS DONE, and with it STEP 1.

**STEP 2, AGREED WITH THE OWNER 22 October:** ELYSIUM STARTS an add-on's
server (rather than a person starting it beside Elysium), A SIGNED TOKEN
tells it who is asking (rather than trusting loopback), and the
simulator's panel lives in `sim/`, its bundle served by Elysium like any
module's. In four parts: 2.1 the proxy and who-is-asking, 2.2 the
lifecycle, 2.3 the simulator's panel as a module, 2.4 posting to the
Inbox and the contract-version field. WebSocket pass-through waits for
an add-on that uses one.

**2.1 AND 2.2 ARE BUILT.** A module may declare `server` in its
manifest; `addons.yaml` gives each its options, `${VAR}` filled from the
environment (core/modules.py, core/addons.py). Elysium starts it with a
port, a start file and a bare environment, checks `/health`, restarts it
with back-off (1 s doubling to 60 s), keeps its log, and stops it with
SIGTERM then SIGKILL at its `stopSeconds`; one worker supervises each,
by flock, and another takes over if that worker dies; standard input is
a pipe whose closing tells the server Elysium has gone
(api/addon_servers.py). `/api/addons/{id}/...` forwards to it for anyone
the module is offered to, adding `X-Elysium-Identity`, an HS256 JWT made
with a secret per add-on per start, good for a minute; cookies,
`Authorization` and the CSRF token never reach it, `Set-Cookie` never
comes back, and what comes back is served sandboxed. Event streams pass
(at most 8 open per worker, each ended after 10 minutes, as /api/events
does). `sdk/python/elysium_addon.py` is the contract and a verifier
needing only the standard library, for an add-on that may not import
Elysium. The System sub-app has an Add-on servers page: state, log,
Restart (audited). Checked live under two uvicorn workers: one server,
reached from both; the supervising worker killed with SIGKILL, the old
server left by itself and the other worker started a new one; a
graceful stop exited 0.

**2.3 IS BUILT, the owner's two answers of 22 October with it.**

PERMISSIONS A MODULE DECLARES: "loadable modules [should] have their
own permissions that dynamically get added to Elysium's permissions
list". A module.json lists `permissions` (`{id, description}`), granted
as `module:<module id>:<id>`. One REGISTRY -- Elysium's own grants and
every listed module's -- worked out from the manifests at each load (the
owner chose that over a stored table), offered by the role editor in a
group per module with each description. Checked as every grant is; one
from a module no longer listed is kept, grants nothing, and is shown as
such rather than stopping the load. An add-on's token says which of its
own permissions the person holds.

THE WORLD RUNS ON ITS OWN: Elysium "should be able to be probed as if
it went offline while the remote resources continued on their
functioning per normal". The panel's server (sim/panel/server.py)
starts `simulator run --follow` in a session of its own and keeps
nothing about it in memory; killing Elysium -- the panel's server's
whole process group, SIGKILL -- leaves the world running, and the next
panel finds it through control.json. It stops on Stop, `simulator
stop`, or SIGTERM, each through the run's teardown. A run lock held for
a run's whole life says "busy" while building or tidying up.

THE PANEL (sim/panel, module `simulator`, offered to
`module:simulator:operate`): start from a pack or resume the stopped
world with its own pack, pause, move on, speed, take a database offline
and restore it, each database's connection details to copy, the run's
log, discard. Its page's source is in sim/panel/web, built by ui/'s
build into sim/panel/dist; the simulator carries no Node packages and
imports nothing of Elysium's (its copy of the SDK is checked identical).
Drift from the panel waits, the owner's choice.

**2.4 IS BUILT, AND WITH IT STEP 2 (23 October).** An add-on posts to
the Inbox by dropping a file in an OUTBOX folder Elysium gives it (the
owner's choice over an HTTP call: no new door, and a notice written
while Elysium is offline arrives when it is back). Delivered only to
people offered the module -- named, or "everyone" -- each notice tagged
in the Inbox with the module's name; a file Elysium cannot take moved
aside with the reason in the add-on's log; a file read twice delivered
once, its name the dedupe key (api/addon_servers.deliver_outbox; the
SDK's `post()`). The simulator's panel watches its world and tells
everyone who may operate it when it is running, when it crashed (even
while Elysium was down) and when it never got going; a stop someone
asked for says nothing.

DOUBLE-CHECKED WITH THE OWNER AND DROPPED: notification kinds declared
in module.json (a label kept in two places; Android's channels earn
theirs by letting a person mute one, which Elysium has no use for) and
a per-module contract version, moved to step 4 -- the feed already
carries one, and versioning is designed when there is a version 2.

STEP 2'S LAST AGREED PIECE, the add-on contract checks, followed on 23
October (above, under the conformance suite).

**STEP 3, AGREED WITH THE OWNER 23 October:** the remaining sub-apps
move one per patch, smallest first -- Identity, Notifications,
Approvals, Query, the Inbox (into a package), Admin, Browse -- each to
its own bundle, its host values from the kit, its palette, badges and
tabs from its own `activate()`, its own test project and the
conformance suite (`todo` with a reason for what fails today).

**STEP 3, IDENTITY MOVED (23 October):** its own bundle, loaded when the
Inbox first shows its tab; its styles out of the kit's stylesheet and
into its own; its own test project; and the conformance suite, which
now checks a module's slot CONTRIBUTIONS as it checks pages -- rendered
with the context Elysium's slots give, `onSessionExpired` -- passing
every check with no exceptions. The page no longer imports or depends
on it.

**NOTIFICATIONS MOVED (23 October)**, the same way, passing every check.
Breaking it on purpose found what the suite cannot see: it checks a tab
as a whole, and this tab also mounts its Watching and Reminders panels,
which hand over an expired session by themselves -- so a notification
list that ignored one passed, hidden behind them. Its own test now
covers its list alone. The suite's limit stands, said here: a check on a
page is a check on everything the page mounts.

**APPROVALS MOVED (23 October)**, its four Inbox tabs (Approvals,
Enrichment, Predictions, Unusual) in one bundle, passing every check.
It was the last sub-app whose slot code Elysium's page carried, so
App.tsx's table of built-in contributions is gone, and a Python test now
refuses any module that fills a slot without a bundle of its own.
Approvals is the Inbox's first tab, so its bundle arrives when the Inbox
opens rather than when a tab is clicked.

**QUERY MOVED (23 October)**, the first page rather than a tab: it reads
the session hand-over from the host store, as Schema does. It is where a
person lands, so its bundle is asked for straight after login. The suite
running on it found one real fault, fixed: an expired session found
while fetching the example questions was swallowed with every other
failure of them, so the person learnt of it only on asking. Its other
two exceptions are deliberate and replaced by tests of their own: the
page waits on nothing, so has no spinner, and a failure of the examples
is not shown, since it must not stand between someone and their
question.

**THE INBOX MOVED (23 October)**, into a package of its own
(ui/packages/app-inbox, from ui/src/inbox and ui/src/InboxPanel.tsx) and
from there to its own bundle, with its badge. Its manifest names
`onStartup`, since the count is on every screen, so the bundle comes as
the frame is drawn; the tabs' code still waits for their own bundles.
With it the page's table of built-in badges is gone. A modules.yaml
naming the old folder is read as naming the new one, with a warning
saying which file to change (the owner's choice, 23 October, over
refusing the file); the module manager writes the new folder on its
next save (core/modules.py, MOVED_MODULES). Its conformance exceptions
are all its tabs': the Inbox draws no data of its own, and its counts
are quiet on failure by design.

**ADMIN SPLIT (24 October)**, before it moves, as this file planned
("much of today's Admin, which splits into the server and
people-and-roles"). The owner's decision, after the analysis: the
server's views -- Deployment, Silos, Metrics, Mirror, Cleaning -- are
the System sub-app's Server page (ui/src/system/ServerPage.tsx, at
/system/server, the view in `?view=`), pinned and offered on
manage:deployment; Admin keeps Users and Roles. Before, the five sat in
Admin, offered on manage:users, so an account administrator was shown
Metrics, Mirror and Cleaning and refused by the server, and an operator
was not shown them at all. The server's checks followed the same day,
in a patch of their own (below, after step 4). A fresh install's `root`
(manage:users only) no longer sees these views; INSTALL.md, "Seeing
the server's own pages", says how to give manage:deployment, and the
installer says so when it finishes. ConfigProposals, used by both
sides, is the kit's now.

**ADMIN MOVED (24 October)**, Users and Roles in its own bundle, loaded
when /admin is first opened, passing every check with no exceptions. Its
own rules (the user table, the create-user form, the roles editor) moved
with it; what it shares with the kit -- a role change's impact, the
waiting configuration changes -- kept theirs there.

**BROWSE MOVED (24 October), AND WITH IT STEP 3 IS DONE.** Its own
bundle: a small entry carrying its palette commands, which the shell
asks for when the palette first opens, and each of its two pages a chunk
of its own beside it (React's `lazy`), fetched when first opened -- so
opening the palette on Query fetches 3 KB of Browse, not all of it, as
when the page held it. Its 134 rules moved into browse.css; what it
shares with the kit (data tables, field values, the filter bar) kept
theirs. Elysium's page now carries no module's code: its tables of
built-in pages and palettes hold only the System sub-app's pages, and a
Python test refuses any module naming an activation event without a
bundle.

TWO THINGS THE MOVE FOUND, both fixed:
- "Ask about this set" had drawn its subject line as a sunken box since
  19 October, when the question-in-progress rules were pasted in between
  `.ask-panel__subject,` and `.ask-panel__note {`. The pair is back
  together, and the progress rules, which are the kit's QuestionProgress
  component's, stayed in the kit.
- The tokens test read only the kit's and Schema's stylesheets, so every
  rule moved in step 3 had gone unchecked for raw colours and undefined
  tokens. It now finds every package's stylesheet itself.

THE CONFORMANCE SUITE NOW HANDLES A PAGE LOADED ON DEMAND: the test host
renders inside a Suspense boundary, as the frame does, and each check
first waits for the page's code to arrive, so no check sees the
fallback and passes for it. And a module may give the suite its host
values -- Browse gives a schema with one type, without which its search
page reads nothing. Both of Browse's pages pass every check. The suite's
known limit holds there too: breaking Search's own hand-over of an
expired session did not fail its check, because the panels it mounts
hand over themselves. Search's own test does catch it.

**STEP 4, AGREED WITH THE OWNER 24 October**, in three patches: the
public surface is WHAT MODULES USE TODAY (measured: 194 names from 38
entry points of the kit and the shell, by the eight modules and the
simulator's panel), plus the manifest, `activate()`, host values, tokens
and the add-on contract; everything else the kit exports is internal.
Written down as an API REPORT with a short guide -- API Extractor's
precedent, which Backstage runs on every package -- and versioned by ONE
number each module.json declares, as VS Code's `engines.vscode` ("the
versions of VS Code that the extension is compatible with").

**4.1, THE REPORT, BUILT (24 October):** ui/module-api.report.md,
generated by scripts/module_api_report.py from the declarations
TypeScript 7 emits: every name a module imports, and every declaration
those lead to (a public function's options type, say), signatures only.
A test fails while it is stale -- so a public signature changed, or a
module importing a name no module used before, arrives as a diff of the
report; a change to an internal export does not touch it. Not API
Extractor itself: it bundles TypeScript 5.9 and drives the compiler
through a JavaScript API TypeScript 7 does not have, and it reports
whole entry points where the agreed surface is the names used.

**4.2, THE VERSION, BUILT (24 October):** the page offers module API
1.0 (`MODULE_API_VERSION`, shell/core/src/contract.ts), MAJOR.MINOR --
an addition raises the minor, a change or removal the major. Each
module.json says what it needs, `"api": "^1.0"`, VS Code's `engines`
form; every shipped one, the System sub-app's and the simulator's panel
say ^1.0. A module needing one the page does not offer, or naming none,
is left out of the routes, the rail and activation (compatibleFeed),
and the Modules page lists it with why ("Not loaded: it needs the module
API ^2.0, and this page offers 1.0") -- refused as a module, never as
Elysium's start. The server refuses a version written wrong at load, as
it does a misspelt activation event. The conformance suite requires a
loadable `api`, and the report heads itself with the version.

THE ADD-ON SERVER'S START FILE keeps its own `"contract": 1`, which the
SDK checks: it is the wire format of one file, and the module's `api`
already says which API its server was built for. Folding it in would
change the SDK every add-on carries for no reader who needs it now.

**4.3, THE GUIDE, WRITTEN (24 October), AND WITH IT STEP 4 AND ITEM 3'S
BUILD ORDER ARE DONE.** ui/MODULE_API.md, for someone writing a module:
the version rules, the manifest's keys and what the server checks,
`contributes`, activation events, what `activate()` returns, the host
values, the shared libraries, styles (tokens, the `components` layer,
a module's own stylesheet), building and testing with the conformance
suite, and the add-on server's contract, pointing at the SDK's
docstring for the whole of it. A GUIDE DRIFTS where a report does not,
so tests/unit/test_the_module_api_guide_matches_the_code.py holds its
LISTS -- manifest keys, contributions, events, what activate returns,
host values, shared libraries, the version, every file it names -- to
the code that decides them.

What this item offered and deferred is unchanged: WebSocket pass-through,
jobs, timer callbacks, event subscriptions, time-series buckets, kit
components (above, "GENERIC SERVICES FOR ADD-ONS"); drift from the
simulator's panel.

**/config AND /silos RE-GATED (24 October), with the owner:** both need
manage:deployment, the grant the System sub-app's Server page is
offered on, where they had kept manage:users from August, "the same
grant Admin uses", when it was the only administrative grant. ONE THING
DEPENDED ON THE OLD GATE: /config was how an account administrator
learnt the roles' names, to put people in them and to name any as a
Watch's recipient (core/triggers.recipient_problem). That is
GET /roles/names now, names only, on manage:users; the Watch dialog
reads it. Tests now hold the boundary itself -- an account-only role
refused the server's state, an operator-only role refused the names --
which the existing ones, using the debug role holding both, could not.

**THE ADD-ON SERVICES, CHOSEN 26 October, with the owner:** time-series
reads first, then the kit's time chart, then event subscriptions. Jobs,
timer callbacks and WebSocket pass-through wait for an add-on that
calls them. The time-series reads come in four parts, buckets written as
ISO 8601 durations as Foundry's aggregate takes them (the owner's
choice): (1) `duration` and `time_zone` on the aggregate; (2) first and
last per bucket; (3) the assistant's aggregate step taking a period;
(4) several measures in one request. A time property declared per type
and a tail cursor wait for a caller.

PART 1 IS BUILT: `duration` (PT15M, PT1H, P3D) beside `period`, and
`time_zone` for either, aligned as TimescaleDB aligns its buckets --
from midnight on 3 January 2000, in the zone asked for -- with the
autumn's repeated hour holding both and the spring's skipped hour never
offered (core/periods.py).

PART 2 IS BUILT: `first` and `last`, the value at the earliest and
the latest moment of each time bucket, as TimescaleDB's are; two at one
moment told apart by id, so the answer does not depend on read order;
refused outside time buckets, where there is no time to order by.

PART 3 IS BUILT: the assistant's aggregate step takes a `period`
(day, week or month) for a type with a date, so a trend is one step
rather than one per period. The grammar offers it only where there is a
date, the parser finishes on a period it does not know, each period is
named by the ISO date it starts on (JSON cannot key on a date), and the
account of the work says "per week". It takes a period, not a
duration: the model has been given the three words it can use well.

PART 4 IS BUILT, and it broke `/aggregate` on purpose (no installation
depends on it): `measures` -- a list of {name, aggregate, field}, up to
eight, names unique plain identifiers -- replaces the single `aggregate`
and `field`, and the answer is `rows`, each {group, metrics}, from ONE
read of the set. After Foundry's aggregate (aggregation list in;
`group` and `metrics` per row out), except that metrics are an object
keyed by name rather than a list: a name is an identifier, so the object
is never reordered. A LIST of rows rather than an object keyed by group,
because JavaScript reorders integer-like keys (`{"b":1,"10":2,"2":3}`
reads back 2, 10, b) and a year or a status code is one; and group values
keep their types. The mediator's `aggregate_by_field` is the same code
with one measure, so its callers are unchanged; the charts ask for one
count and read it with `countsByGroup`. The assistant's step still takes
one measure -- it gets more when something needs them.

**Blocked on:** nothing. Next: the kit's shared time chart.

## 4. What the interface should be

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

Edges are routed AROUND the types in their way (a search over grid lines
beside the nearby types, fewest bends first). WHAT THE CANVAS DOES NOT DO
YET, buildable: the layout is per person, with no deployment-wide
default -- small, and not yet asked for.

**Blocked on:** nothing.

## 5. Agent-loop efficiency, which needs a machine with a model

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

## 6. Context rot, and a 10,000-id search behind it

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

## 7. Who can read Elysium's copied data without going through Elysium

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

## 8. Compliance: SOC 2, ISO 27001, HIPAA, and a penetration test

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

**THE REGIMES, ANSWERED 26 OCTOBER:** GDPR and UK GDPR, and HIPAA. SOC 2
and ISO 27001 are not declared, so neither attestation is being bought.
For GDPR the engineering is largely built (erasure, retention,
encrypted storage and backups). For HIPAA it is the Security Rule
safeguards above, which the operator carries, and a BAA, which is a
contract and not a patch. The list's remaining rows are therefore not
optional: key management, session controls, a password policy,
access review, audit integrity and backup verification.

## 9. Owning the UI kit, and when to start

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

## 10. The simulator as Elysium's live test, and five kinds of source

**AGREED WITH THE OWNER, 19 October.** Mostly built since: Elysium reads
all five kinds, and a running world can be operated from outside it
(item 11, step 1). What is left is the control panel as a page.

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

**THE PANEL IS BUILT** (item 3, step 2.3): sim/panel, loaded as a module,
its server started by Elysium, the world running on its own.

**SCHEMA CHANGES FROM THE PANEL, 26 October, with the owner** (after
item 11's runs, which used every kind): a database, a table and one of
the eight changes the pack vocabulary has, its details, Apply; and the
list of what has changed, scheduled or not, read from the history table
each database keeps. Laid out as Gremlin lays out an experiment ("Select
the type of target ... click on the experiment name ... Click Run
Experiment", then "view reports of historical experiments"). Only what
exists can be picked: the world's new `schema` command gives each
silo's tables as they are now, a replica left out since its source's
change reaches it. A breaking change asks twice, and which are breaking
is the world's word, from each change's class -- every one but the two
additions, a rescale included, because every value means something else
after it. None can be undone; only discarding the world goes back.
(sim/panel/web/src/SchemaChanges.tsx, sim/simulator/control.py.)

**Blocked on:** nothing; built. Superseded wording below kept for its
reasons:

**Was blocked on:** nothing but order: the page comes after item 11, whose
runs will show which controls an operator actually reaches for.

## 11. Make the simulator's sources behave like real ones, then run Elysium over it

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

**Two weeks with five migrations, 21 October.** `--migration` adds to a
pack's timeline. Over field_service with every realism option on: a
RESCALE of invoice totals by 100 was served -- it is what the source now
says -- and flagged by the profile monitor ("average 8.167e+04, was
842.4 (214.1 standard deviations)"); a decimal column retyped to integer
was named ("CHANGED from NUMERIC(19, 4) to INTEGER ... a value may still
parse and mean something else"); an added table was left alone; a
renamed and a dropped table kept their last good copies. Every round
agreed or refused with a reason. What it took:

- Elysium: the reason a renamed or dropped table gave was "could not
  read the columns of 'skills': skills" -- and on SQLite "source column
  'id' ... is gone". The sync now says the table has gone and names the
  source's tables the mirror does not hold, where a renamed table's new
  name is.
- The simulator: a type change that did not say `nullable` made the
  column nullable in the declared schema while the engine kept NOT
  NULL, and the world stopped on its own check.

**NOT DONE, AND WHY:**

- A SQLite SOURCE. The simulator's SQLite silo cannot hold tables: it
  has no SQL dialect, and every relational silo there assumes a server
  with roles, grants and named databases. Elysium's SQLite reader is
  the one most of its own suite reads through; driving it from a live
  simulated application would need a SQLite dialect and session in the
  simulator, which is buildable.

**Replica lag, 21 October.** The simulator's replica can now be a real
PostgreSQL standby (`replication: streaming`, made by pg_basebackup),
with replay paused and resumed through the control channel. The time a
sync records is when its read began, and it means "everything
committed before this is in the copy" -- freshness is shown from it,
and the overlay rests on it. A lagging standby broke both: its data
stops at the last change it replayed. A PostgreSQL source now says
whether it is a standby that has received more than it has replayed --
received against replayed rather than against the clock, which reads an
idle primary as lag -- and the copy is dated from its last replayed
change, with the reason on the Mirror screen. Over field_service with
`office` a standby and replay paused for two rounds, it froze, Elysium
said so, and every table agreed. What it cannot see: WAL not yet
received ("the replica doesn't know the current transaction position of
the primary"); measuring that needs the primary, which Elysium does not
reach. Long reads cancelled by `max_standby_streaming_delay` are not
provoked; a cancelled read is an ordinary failed read, keeping the
last good copy.

THE OVERLAY RUNS PER TYPE since 21 October, with the owner. It ran
from one time for the whole deployment, the oldest of every table's,
so a standby with replay paused held it back for everything, and in a
type read from a current source a write Elysium made earlier was laid
over a newer change made at the source. Each gold publication now
records when the data it was built from was read
(core/mirror/gold.py, DATA_AS_OF_PROPERTY), and a type's overlay runs
from that -- also right where silver's time was wrong, a refused gold
build having left gold older than its silver. A publication from
before the record uses the deployment's time, as before. And a write
is now timed by when it was APPLIED, not asked for: a sync whose read
began between the two held a copy without it yet counted as newer, so
it was hidden until the next sync -- older than this change, but the
deployment-wide hold-back had mostly masked it (found in review).

One limit, conservative: a running server takes a type's new data
time when its gold PUBLISHES. A build that finds gold unchanged moves
the time forward without a new publication, and a running server only
notices new publications, so until the next one or a restart that
type's overlay runs wider than it need be -- never narrower.

**THE SIMULATOR'S SQLITE SOURCE HOLDS TABLES (24 October), with the
owner:** a SQLite dialect and session in sim/, so a SQLite silo is
provisioned, written, read back and drifted through the same relational
layer as the servers. Written as an ordinary application writes (the
owner's choice over STRICT tables): declared types as hints, money by
NUMERIC affinity (19.99 a double, 20.00 the integer 20), booleans 1/0,
times as ISO text in UTC; a retype is SQLite's documented rebuild, in
one transaction; no accounts, so `withheld` is refused and `simulator
verify` checks a read-only reader instead.

**THE FIELD-SERVICE PACK HAS A PARTS DESK (26 October), with the
owner:** its fifth system, a desktop stock program on the office PC,
in SQLite. A finished job books out a part against its work order id
-- the desk's only link to dispatch, by convention -- and takes it off
the shelf, never below zero; a merchant delivery every two days puts a
line back; a part is discontinued fortnightly, marked and kept. A
fitted part keeps the cost it was fitted at. The tests reconcile every
part's count against the shelf at the start, deliveries and usage
(sim/tests/test_field_service.py).

**A FULL RUN OVER EVERY SOURCE KIND, 26 October.** Field service (two
PostgreSQL servers, one a replica, a REST API, a CSV folder and the
SQLite parts desk) and retail (MariaDB, PostgreSQL, a CSV folder), five
rounds each with every realism option on: every table agrees, or is
refused with its reason -- pay lines withheld from the reader, a weekly
file not yet arrived. What the first run found was the harness's, not
Elysium's, and Elysium's own refusal said how to fix it: SQLite keeps
a time as text with no zone, refused as an instant until the zone is
declared (`timezone: UTC`, as for MariaDB). It also showed that a
deployment without `write_targets` lets a confirmed write reach any
SQLite silo -- here another program's database. The harness declares
`write_targets: []`; Elysium's default, kept deliberately and warned
about at load, is unchanged.

**Step 3 is done**, and with it this item; item 10's drift controls,
which these runs were to inform, are built.

**Blocked on:** nothing.
