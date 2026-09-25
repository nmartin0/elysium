# STATUS_agentloop.md

Branch `agentloop`, from `dev` at `f6c5a0b`.

---

## AR-1 -- verify prefix-cache reuse. MEASURED. The structural half is
## confirmed; the engine half is NOT, and needs a live Ollama.

**The claim under test** (probe P31, AUDIT_INTAKE_PIPELINE.md): 97.5%
of each hop's prompt is an exact prefix of the previous one.

**IT REPRODUCES, on the real loop over a real mediator.** Not a
reconstruction: a recording adapter sat where the model sits, so what
was measured is the exact byte sequence an engine would receive,
built by the real `_build_system_prompt()` from real `gathered`
entries produced by real mediator reads over the shipped deployment,
seeded and synced per `tests/unit/conftest.py`'s own fixture.

Seven hops of "What are Ada Okafor's transaction amounts?" --
search_object, two get_field, search_around, two more get_field,
finish:

    hop    system    user   total   shared   reuse   diverges in
      2      4502     197    4699     4574   97.3%   user message
      3      4502     311    4813     4674   97.1%   user message
      4      4502     426    4928     4788   97.2%   user message
      5      4502     563    5065     4903   96.8%   user message
      6      4502     674    5176     5040   97.4%   user message
      7      4502     785    5287     5151   97.4%   user message

**96.8%-97.4%, against 97.5% reported. The audit was right.**

THREE THINGS THE MEASUREMENT ADDS that the one-line finding does not:

**The system prompt was BYTE-IDENTICAL on every hop** -- 4502
characters, `identical=True` for all six transitions. The divergence
is always inside the user message, at the point `gathered` grows.

**So the per-hop state is ALREADY in append-only position**, which is
what AR-2 asks for. `_action_state_notes()` was moved to a trailing
section in earlier work, and the comment beside it says why: inline,
"it changed the middle of the system prompt on the exact hop a write
became relevant". That fix is in and it holds.

**Nothing in the Ollama adapter defeats reuse.** The payload is
`messages: [system, user]`, `format: json`, `think: false`,
`temperature` from the caller, `options` from config -- all constant
across hops. Nothing per-hop varies except message content, and no
`seed` is injected per call.

### What I did NOT check, and it matters

**THE ENGINE HALF IS UNVERIFIED.** A prefix-stable prompt is necessary
for reuse and not sufficient: whether llama.cpp under Ollama actually
skips re-reading it is a property of the server, not of us. There is
no Ollama in this sandbox, so I measured what we send and not what it
costs. AR-1 is therefore HALF DONE. Finishing it needs one run on the
VM: the same query twice, with `llm_bench` or by timing hop 1 against
hops 2-7, looking for the prefill/decode split MODEL_SELECTION-001
describes. **Ask me for that when a VM is available.**

**MY FIRST RUN PROVED LESS THAN IT LOOKED.** It measured the shipped
deployment, whose one action type (`RecategorizeTransactions`)
declares no `submission_criteria` -- so `_action_state_notes()`
returned `""` on every hop and the "system prompt is stable" result
was partly vacuous: it could not have detected instability in the one
section capable of causing it. Attaching a write mediator did not fix
that; the test user's `visible_action_types` was empty, so the whole
writes section never rendered either. The guard below uses a fixture
that does fire, and asserts that it fires before asserting anything
about it.

**`scripts/llm_bench.py` is still not applied.** 001AGENTLOOP §2.4
says it exists in the audit set as an unapplied patch and is
read-only and standalone. I do not have the patch file. If you want
real prefill numbers, that is the fastest route and I would like it.

### What landed

`tests/unit/test_prompt_is_stable_across_hops.py`, 4 tests.

A measurement nobody re-runs decays into a claim. This pins the
property AR-1 measured: everything before the trailing notes is
byte-identical between hops, the only difference IS the notes, and a
hop that reads nothing relevant changes nothing at all.

**CONTROLS RUN, both directions, and they fail differently:**

    control 1  per-hop notes moved to the HEAD of the system prompt
               (the pre-existing design the comment warns about)
               -> 2 failed, 2 passed
               -> and test_prompt_prefix_is_user_specific STILL PASSED,
                  which is the argument for this file existing: the
                  cross-user guard cannot see this regression

    control 2  a per-hop counter appended to the tail -- the shape
               that satisfies "the difference is at the tail" while
               destroying reuse on every hop
               -> 3 failed, 1 passed
               -> including the opposite-direction test that control 1
                  did NOT trip

Restored from a backup copy, not by hand-editing back;
`git diff core/llm/agent_step_prompt.py` is empty.

**No production code changed.** AR-1 was a measurement and the fix it
might have justified is already in.

### The tension worth stating before anyone "optimises" this

Two guards now pull in opposite directions, and both are correct:

    test_prompt_prefix_is_user_specific   two DIFFERENT users must
                                          share almost NO prefix
    test_prompt_is_stable_across_hops     one user's SUCCESSIVE HOPS
                                          must share almost ALL of it

Both hold because the cross-user divergence is at the HEAD (the
per-user filtered schema) and the cross-hop divergence is at the TAIL
(`gathered`). **AR-2 must not be implemented by moving shared
boilerplate toward the head to lengthen the common prefix.** That is
the KV-cache side channel ROADMAP.md's security backlog closed
deliberately -- two users with disjoint ontologies went from sharing
103 characters to sharing 2 -- and it is filed there as a security
regression wearing a performance win's costume. Both files say so now.

---

## Gates

    ./lint.sh                     PASS (8 contracts kept, 0 broken)
    pytest tests/unit             2847 passed, 8 skipped
                                  (2843 before; +4 is this file)
    pytest tests/integration      443 passed, 3 FAILED, 14 deselected

**The 3 integration failures are environmental, not a regression**:
all three raise `LLMUnavailable` on `localhost:11434`, connection
refused. No Ollama in this sandbox. They fail identically on an
unmodified tree.

### A discrepancy found while confirming that -- backend's call

`AGENTS.md:53` says "Integration tests marked `test_real_model_*` need
a live Ollama." **Three that need one are not named that**, and carry
only `@pytest.mark.integration`, indistinguishable from the 443 that
do not need a model:

    tests/integration/test_full_roundtrip.py
      ::test_same_region_query_returns_correct_transactions
    tests/integration/test_max_hops_e2e.py
      ::test_max_hops_exhaustion_is_reflected_in_the_real_synthesized_answer
    tests/integration/test_region_enforcement_e2e.py
      ::test_cross_region_query_returns_no_real_transaction_data

So `-k "not real_model"` does not deselect them, and anyone following
AGENTS.md will read three environmental failures as a regression --
which is what I did for a minute. The honest fix is a marker
(`@pytest.mark.needs_model`) rather than a rename, since the names
describe what they test.

`AGENTS.md` is a root document and backend-owned, and those three test
files sit outside my area. **Not touched. Flagging for backend.**

---

## LB-1 -- arithmetic in prose. REPRODUCED. Proposing the shape before
## building, because neither half is safe to ship alone.

### It reproduces

Drove the real `synthesize_insight()` with a client returning answers
the records do not support. Records given: two transactions, `49.99`
and `199.00`.

    case                                      reached the user?
    correct arithmetic ($248.99)              returned verbatim
    WRONG arithmetic ($1,248.99)              returned verbatim
    invented figure ($7,412.00)               returned verbatim
    invented count ("47 transactions")        returned verbatim
    a real value, copied ($49.99)             returned verbatim
    invented email                            WITHHELD
    citation out of range [R9]                WITHHELD

**An invented figure with a valid citation reaches the user.** The two
existing checks fire correctly on their own cases, which is what makes
this a reproduction of a gap rather than a broken harness.

### And 1b ALONE would be a regression -- measured, not assumed

The module docstring already argues against a number check: "$49.99 +
$199.00 = $248.99 is a genuinely correct answer that would never
appear verbatim in the source records -- a naive verbatim check
applied to arithmetic would wrongly flag it."

**That objection is correct.** A verbatim number check over the same
cases withholds the CORRECT total along with the wrong ones:

    correct arithmetic    ungrounded: ['248.99']    WITHHELD
    WRONG arithmetic      ungrounded: ['1,248.99']  WITHHELD
    invented figure       ungrounded: ['7,412.00']  WITHHELD
    invented count        ungrounded: ['47']        WITHHELD
    real value copied     ungrounded: []            allowed

So the dependency in the work list runs BOTH ways. It says "do not do
1a without 1b". It is equally true that **1b without 1a discards
correct answers**, which is a worse failure than the one it fixes: a
check that withholds good answers gets turned off.

**1a IS WHAT MAKES 1b SOUND.** Once the code supplies every figure the
answer needs, the model never has to compute one, and a verbatim check
over numbers becomes exactly as safe as the email check already is --
for the same stated reason: the value can then only be COPIED, never
legitimately computed.

### A trap the measurement exposed, which shapes 1b

`"Ada has 2 transactions"` PASSED the verbatim check -- not because it
was verified, but because `"2"` happens to be an `object_id` in the
records. The naive check greps the whole serialised record, so an
invented figure can be grounded by coincidence against an unrelated
identifier.

**So 1b must ground a number against the VALUES of numeric fields and
the computed figures, never against `str(record)`.** The existing
email check greps `" ".join(str(record) ...)` and is safe doing so
only because an email-shaped string cannot collide with an id. A
number can, and will.

### The shape I propose -- NOT BUILT, want agreement first

1a. `synthesize_insight()` computes deterministic aggregates over the
    records it was given -- count, sum, min, max per numeric field,
    per object type -- and appends them as their own tagged records
    (`[R3] {"computed": "sum of amount over 2 Transactions", "value":
    "248.99"}`). In `Decimal`, never float: this project added a
    `decimal` type precisely because `float()` silently loses money
    digits, and a synthesis total computed in float would reintroduce
    that at the last step.

1b. `_has_only_grounded_numbers()`, a third independent check beside
    citations and emails, failing closed the same way: every numeric
    token in the answer must appear among the field values or the
    computed figures. Same narrow scope, same "vacuously true when
    there are none", no generalisation into a pattern registry.

### Three things to decide, and they are why I stopped

**WHICH FIGURES.** Computing count/sum/min/max for every numeric field
is deterministic and needs no guess about the question. Computing only
what the question asks needs understanding of the question, which is
the model's job -- circular. I would build the first. But it is a
scope decision, not mine.

**THE COST, which AR-1 makes concrete.** Every appended record is
prefill on a call where prefill dominates (~5.4 tokens/s measured).
Aggregates over a wide result set could add meaningfully to the
synthesis prompt. **I have not measured this**, and I would measure it
before landing 1a rather than after.

**OVERLAP WITH `aggregate_object`.** The agent already HAS an
aggregate step, and LB-9/IDEAS.md record that it under-selects it.
There is a real argument that the right fix is to make the agent
aggregate properly and have synthesis refuse ungrounded numbers --
which is a different, larger piece of work touching the step prompt.
Computing in synthesis may be the correct narrow fix, or it may
paper over the loop choosing badly. Worth an opinion before I build.

Nothing committed for LB-1 beyond this record. Probes deleted.

---

## Next

Blocked on the three LB-1 decisions above. While they are open I will
start `AL-2` (the planner reads raw source data with no untrusted-data
framing), reading SECURITY_ARCHITECTURE.md first as 001AGENTLOOP §3
directs -- what the model may be trusted with is a security question,
not a prompt-engineering one.

Nothing in `REQUESTS_agentloop.md` yet -- I have needed no change
outside my area.
