# HANDOVER — agentloop (LLM 2)

Rebased onto `origin/dev` at handover. **15 commits ahead, rebased
cleanly, no conflicts.** Gates on the rebased branch:

    ./lint.sh          PASS — 8 contracts kept, 0 broken
    pytest tests/unit  3666 passed, 8 skipped

Both re-run on a **fresh clone of `dev` with all 16 commits applied**,
not only on my worktree, and the applied tree is byte-identical to the
one tested.

**The pre-rebase branch is `origin/agentloop` as it stood before this
series** -- that is the backup, and it is somewhere you can actually
reach. An earlier draft of this line pointed at a bundle in my own
sandbox, which you cannot get to: a backup nobody else can open is not
a backup. To see the original commits:

    git log --oneline f6c5a0b..origin/agentloop

The rebase was clean, so the 16 commits here are the same changes with
new parents, not a rewrite.

**Two things you told me, both verified against dev rather than taken
on trust:**

- **AL-R1 is done.** `RetryingLLMAdapter` is constructed at
  `core/deployment_loader.py:722`. AL-5 is no longer inert. Your
  reasoning about the limiter is right and matches mine:
  `ConcurrencyLimitedLLMAdapter.chat` holds the slot across the call,
  so a retry nested inside would sleep holding it.
- **The gold-history defect is fixed.** I ran two consecutive syncs on
  dev: no warning. Patch 421 works. My report measured the fork point
  and I did not check whether dev had moved — I had `git fetch` in my
  hands and used it only for my own branch.

---

## 1. FINISHED — what changed, and exactly how to verify it

Everything below is verifiable with **one command and no model**
unless it says otherwise. Run from the branch root.

### The whole set at once

    ./lint.sh && python3 -m pytest tests/unit -q

3666 passing is the number to expect. Anything less means something
did not survive consolidation.

**Every filename below was checked to exist.** I wrote the first draft
from memory and six of them were wrong -- a handover whose commands do
not run wastes exactly the time it is meant to save, so they are now
resolved by grepping for each feature's own identifiers rather than by
guessing at names.

### Item by item

| Item | What changed | Verify |
|---|---|---|
| **LB-3 / AL-6** | One named stop reason per ending; `AgentLoopResult` booleans derived | `pytest tests/unit/test_stop_reason_is_named.py` |
| **AL-2 step 1** | Untrusted-data framing below the schema (above it is a KV-cache timing attack); invisible chars arrive as visible `\uXXXX` | `pytest tests/unit/test_planner_data_is_untrusted.py` |
| **LB-5** | Synthesis renders values through `render_gathered()`, not `f"{record}"`; the email check is grounded against the same rendering | `pytest tests/unit/test_synthesis_renders_values.py` |
| **AL-5** | `RetryingLLMAdapter`, `LLMUnavailable.retryable` set only at transport raise sites | `pytest tests/unit/test_retrying_adapter.py` — **now live**, see AL-R1 |
| **F-17** | `object_reference_list` renders as a list of ids; scalars stay quoted | `pytest tests/unit/test_action_example_shapes.py` |
| **AR-4** | Titles beside ids, from `title_field` in `visible_schema`; each title is an authorised read | `pytest tests/unit/test_search_results_carry_names.py` |
| **AR-2** | `_build_system_prompt()` cannot see `gathered` — notes moved to the user message | verified below, and the signature has no `gathered` parameter |
| **AL-8** | `pass_hat_k` (unbiased), fact-based `grade()`, per-case `aggregate()`, `is_degenerate()` | `pytest tests/unit/test_agent_evaluation.py` |
| **LB-1a** | `functions/calculator.py` — exact `Decimal`, AST walk, closed whitelist | `pytest tests/unit/test_calculator_function.py` — **still unreachable, see §3** |
| **LB-1b** | Synthesis withholds ungrounded figures | `pytest tests/unit/test_synthesis_grounds_numbers.py` — **causes a live regression, see §3** |
| **AL-12** | `AgentLoop.resume()`, re-resolves the user before any read | `pytest tests/unit/test_resume_after_write_decision.py` — **inert, no caller** |
| **AL-7** | OTel GenAI spans, optional import, closed attribute list | `pytest tests/unit/test_tracing_carries_no_content.py` — **inert, no dependency** |
| **LB-2 (part)** | Schema states each field's declared type; undeclared → `DEFAULT_FIELD_DATA_TYPE` | `pytest tests/unit/test_schema_states_field_types.py` |
| **AL-4** | Plan-then-execute, four commits: handles, planning call, executor, re-plan gate | `pytest tests/unit/test_plan_handles.py tests/unit/test_next_plan.py tests/unit/test_plan_executor.py tests/unit/test_run_planned.py` |

### Three that are not on your list and should be

| | | |
|---|---|---|
| **Decimal filter crash** | A model writing `{"amount": "$100"}` crashed `/query` with an uncaught `decimal.InvalidOperation`. **Live path, not plan mode.** | `pytest tests/unit/test_bad_filter_values.py` |
| **Filter boundary check** | Filter values coerced against the declared type **from the visible schema**, before the query | same file |
| **Ungrouped aggregate** | A count was shown to the model as `{"null": 2}` | `pytest tests/unit/test_ungrouped_aggregate.py` |

The first of those is the most serious thing I found in my own area:
a 500 on `/query` reachable from ordinary model output, because a
date field's bad value raised `ValueError` (caught) and a decimal
field's raised `ArithmeticError` (not).

### Needs a model (VM), for completeness

    python3 -m pytest tests/integration/test_prompt_injection_e2e.py -m integration
    python3 -m scripts.llm_bench --mode plan
    python3 -m scripts.diagnose_slow_call

---

## 2. UNFINISHED — your 19, honestly

**Four of these are done and your list is stale.** Said first, because
you asked.

### Already done — please close

- **AL-3** — DONE as a measurement. Claimed 48,704 chars/9 hops;
  measured **64,527**. Characters, not tokens (tiktoken was blocked by
  the network allowlist). Nothing to build; the number is the
  deliverable and it is in `STATUS_agentloop.md`.
- **AR-1** — DONE, both halves. Structural: hops 2–5 share
  97.4–97.7% of their prefix. Engine: **call 1 at 520.89s for 6,535
  chars, call 3 at 50.58s for 6,817 chars — a longer prompt, 90.7%
  less time.** llama.cpp reuses the prefix. Measured by time;
  `prompt_eval_count` reports total context and cannot detect a cache
  hit.
- **AL-9** — CLOSED as a duplicate of AL-4. Palantir's stated cost of
  prompted tool calling ("can only call a single tool at a time") *is*
  AL-4's complaint. Building both would be building one thing twice.
- **AL-11** — DECLINED with reasoning. Mid-hop cancellation: the
  in-flight model call is the expensive part and cannot be
  interrupted, so the boundary is documented rather than moved.

### Started, and where they stopped

- **AL-4** — **complete and verified**: 5 of 5 bench cases, handles
  used correctly in every one, fan-out verified end to end, both
  injection tests passed. **Still a sibling entry point
  (`run_planned()`), not the default**, deliberately — see §4.
- **LB-2** — the data-type half is shipped. The **operator
  vocabulary** (`in`, `range`, `contains`, `date_range`,
  `relative_date`, `not_in`) is specified and measured at +504 chars
  but **not built**: it is F-18 on the roadmap, owner's priority, and
  I proposed rather than built it. `mediator.search_object()` already
  accepts `conditions: list[FieldFilter]`, so the six operators are
  supported downstream — **only the agent is restricted**, by
  `as_equality_conditions()`.
- **LB-6** — measured, then **closed as not-worth-cutting**. Today's
  number on dev: **85.8% procedure, 816 chars of schema in 5,731**. I
  proposed cutting the three worked examples (~1,148 chars, ~119s of
  a cold call) with the literature behind me, ran both arms, and **the
  cut lost**: plan mode went 3/3 → 3/5, and `link_fanout` passed with
  them and failed without. Every failure was a *format* error. The
  prompt is mostly load-bearing.
- **AR-5** — **recommend closing as declined.** Our own 19.7% → 11.0%
  plus literature up to 27 points of degradation on small models. The
  remedy (scratchpad, constrain only the final step) needs thinking
  mode, which D1's target model does not support.
- **AR-7** — **recommend deferring.** Semantic caching needs an
  embedding model; this hardware cannot afford a second resident
  model. Rule-based routing (LB-9) first.

### Not started

- **AL-10** — token budget. Researched; no canonical answer for
  local single-tenant. **One trap worth recording:**
  `TokenUsage.unreported` means a budget computed from reported
  tokens **fails open silently**.
- **AR-3, AR-6, AR-8, AR-9, AR-10** — all need llama-server, GEPA
  tooling, or hardware decisions (D2/D3/D6) that were never made.
- **LB-7** — folded into AL-4. Handles *are* by-reference arguments.
- **LB-8** — depends on R3 (see §3).
- **LB-9** — rule-based routing only. Recommended, never ruled on.
- **LB-10** — correct that AL-2's prompt instruction is insufficient.
  AL-4 is the structural answer, and the injection tests now measure
  both.

---

## 3. BUGS FOUND, NOT FIXED — outside my area

### Zero roles can invoke any tool

`_step_use_tool` authorises `f"tool:{tool_name}"`. **No role in
`deployment/etc/policy.yaml` holds a single `tool:` grant** — the one
match is a comment on line 35.

So `linear_regression` sits in `tools.enabled` and **cannot be invoked
by anyone**, and nothing would show it: the refusal is deliberately
identical to "unknown tool", because a caller must not learn a tool
exists by being refused it.

**This makes LB-1 a live regression I shipped.** LB-1b withholds
figures that do not appear in the records — correct — but the
calculator that would ground them is unreachable, so a *correct* total
is withheld today with no way for the model to be right. Two parts
needed, and I only ever asked for the first:

    tools.enabled:  + calculator
    some role:      + tool:calculator

**My open question for whoever owns policy:** is
`linear_regression`'s missing grant a bug or a deliberate parking? The
answer decides whether this is one fix or two. **If you would rather
not enable the calculator, gate LB-1b off instead** — either is fine;
the current pairing is not.

### The dev deployment's timeout is below its own cold call

`deployment/etc/config.yaml` sets `request_timeout_seconds: 600`. A
cold call on the plan prompt is 6,154 chars at a measured 0.104
s/char ≈ **640s**. **Every first query after a model load, or after
five minutes idle, fails** — the query a person is most likely to be
watching.

The config's comment reasons from "~5.4 tokens/sec"; the VM measured
**2.4**. Three options: a larger timeout, a shorter prompt, or
accepting the failure. **The third is what happens today, silently,
and it is the only one nobody has chosen.**

### Integration fixtures run two models with no keep_alive

`tests/integration/fixtures/config.yaml` uses `qwen3:4b` for steps and
`qwen2.5:3b` for synthesis, with no `keep_alive`. `deployment/etc`
argues against exactly this: "Two models mean Ollama loading and
evicting between them — measured at 12–47 seconds per load".

**I tried setting `keep_alive: -1` and it made things worse** — the
suite went 662s → 857s → 1147s. `-1` means *never evict*, and pinning
three models on a 2-core box is memory pressure, not a warm cache.
Reverted, with the reasoning in the file. **Collapsing to one model is
probably the real fix and is not mine to make**: every integration
test runs against that pair.

### A mirror is not portable between worktrees

The Iceberg catalog stores **relative** paths, so a mirror built in
`~/elysium` cannot be read from `~/elysium-agentloop`, whatever
`--data` says. The failure is a `FileNotFoundError` deep in pyarrow
naming a path that looks absolute and is not.

That is a consequence of a deliberate decision (commit `555868a`) and
correct for its own reasons. But with four agents in four worktrees,
"point at the other checkout's data" is a thing people will try. Worth
a line in `INSTALL.md`.

### Still open from my requests

- **R3** — `search_object_free_text` does not reconcile pending
  writes; `search_object` does (verified by AST on dev today).
  Foundry OSv2 guarantees read-your-writes; our split is deprecated V1
  behaviour.
- **R4** — nothing calls `resume()`. **Must pass `refresh_user`** or
  the authority check is skipped, which is the entire point of the
  feature.
- **R5** — no `order_by` on `search_object()`. **"The five largest
  transactions" is unanswerable beyond 20 rows**, not merely slow — a
  filter narrows, it does not rank. The security question is answered
  with precedent: **order in the engine, do not push the limit, scan
  in bounded pages and MAC each page.** A pushed limit caps rows
  *before* MAC and the shortfall itself leaks how many were withheld.

---

## 4. WHAT I WOULD DO NEXT — the shape of it

The agent loop is no longer short of features. It is short of
**evidence per unit of wall-clock**, and every remaining decision is
gated on runs that take twenty minutes each.

**First: make the loop measurable, because everything else waits on
it.** A cold call costs ~10 minutes and the variance is 8.8× on
identical prompts. That is the real constraint. Faster hardware or a
smaller model changes more than any code change on this list. Until
then, every "does X help?" question costs a session and answers at
n=1.

**Second: decide AL-4's status, and it is close.** Five of five cases,
handles used correctly every time, fan-out verified, injection passed
in both modes, one model call where the loop uses three. The honest
remaining gap is `dependent_choice` — the adaptivity case ReWOO's own
authors name as plan-then-execute's weakness. **The model already
found the right chain** (aggregate for the maximum, then filter on
that handle — adaptivity without the planner seeing data) and buried
it in a seven-step plan with a broken step. One clean run of that case
decides it.

**Third: the security work is the strongest part and should be
finished, not extended.** The dual-LLM shape is real — the planner
provably never sees a value — and both injection tests pass. But it is
**one attack, one phrasing, one model, n=1**, and the literature is
explicit that static-benchmark validation is what made twelve earlier
defences look strong before adaptive attacks broke them. More attack
phrasings against the existing harness is worth more than another
feature.

**Fourth: stop adding prompt text without measuring it.** I proposed
two prompt changes and was wrong about both. The examples removal was
simply wrong and the run said so. The prompt is mostly load-bearing.

**What I would NOT do:** build LB-2's operator vocabulary, AL-10, or
anything in the AR-3/6/8/9/10 block until there is hardware to measure
on. They are all "this might help" items, and this codebase now has a
harness that can tell you — but only if a run is affordable.

---

## 5. WHAT I COULD NOT CHECK

**I cannot run a model.** No Ollama in my sandbox — every model result
in `STATUS_agentloop.md` came from a command you typed. That was the
bottleneck for the last third of this work, not the decisions.

Specifically unverified:

- **`dependent_choice`** — never completed a run. Attempt 1 produces a
  plan with the right idea; the revision timed out twice.
- **pass^k** — every run was degenerate (all trials agreeing) at
  temperature 0. That is the *expected* result and it closes the
  question: **this loop does not vary, so pass^k will not
  distinguish anything here** unless something changes.
- **AL-4 against a second model** — the inverse scaling law says a
  more capable model is *more* susceptible to injection, so the
  injection tests are a **D1 gate**, not a one-off.
- **Wall-clock claims.** I quoted "64% faster" and then "73% faster"
  for plan mode off n=1 each. **Neither number is trustworthy** — the
  variance is 8.8×. The direction (one call instead of three) is
  solid; the percentage is not.

### The measurements from the wrong-user session — you asked, so:

The failure mode was that `resolve_user_record("alice", ...)` returns
an **empty** `UserRecord` rather than raising: no role, no region,
every read denied, empty schema — and the run still looks healthy.

**I re-ran the three that need no model, on dev, just now:**

| | Recorded then | On dev now | Verdict |
|---|---|---|---|
| **LB-6** procedure share | 87.5% | **85.8%** | **Sound.** The wrong user gives 0 chars of schema and **100%** procedure — so any figure below 100% was measured with a valid user. The drift is dev's prompt changing. |
| **AR-2** prompt stability | byte-identical per hop | **byte-identical across 9 builds, and `gathered` is not a parameter** | **Sound**, and now structural rather than observed. |
| **AL-3** total chars | 64,527 / 9 hops | system prompt 5,731 × 9 = 51,579 + user messages | **Directionally sound, numerically stale.** The prompt has shrunk since. Re-measure before quoting it. |

**The one I cannot re-run is AR-1's engine half** — 520.89s cold
against 50.58s warm. That came *after* the correction and used
`user_alice`, and the schema in that run was non-empty (the prompt was
6,535 chars, not 4,915), so it was not the empty-schema case. **But it
is n=1 on a box with 8.8× variance**, and I would not quote the
specific seconds without a repeat. The *finding* — that a longer
prompt took 90% less time — is robust to that variance in a way the
numbers are not.

**And one honest admission about the pattern.** The wrong-user run
looked healthy because the prompt still grew hop by hop. The same
shape recurred three more times: "warm the model" and "warm the
prefix" were quietly different things twice, and I raised a timeout
twice before measuring what the call was actually spending time on.
**Each time I had the measurement already and applied it in one place
and not the other.** If anything in `STATUS_agentloop.md` looks too
clean, that is the failure mode to suspect.
