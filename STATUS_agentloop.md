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

## Next

`LB-1` (arithmetic in prose -- 1a compute in code, 1b a number check
that fails closed; not 1a without 1b), then `AL-2` (the planner reads
raw source data with no untrusted-data framing). I will read
SECURITY_ARCHITECTURE.md before AL-2, as 001AGENTLOOP §3 directs.

Nothing in `REQUESTS_agentloop.md` yet -- I have needed no change
outside my area.
