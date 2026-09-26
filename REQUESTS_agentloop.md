# REQUESTS_agentloop.md

Requests from the agentloop branch for changes in files it does not
own. Each names the file's owner, the exact change, and what is
already done on my side so the change is a one-liner rather than a
project.

---

## R1 -- wire RetryingLLMAdapter into the generation

**Owner:** backend (`core/deployment_loader.py`)
**Blocking:** AL-5 is inert without it. The wrapper is built, tested
and merged on `agentloop`; nothing constructs it.

**The change**, at `core/deployment_loader.py:608`:

```python
# now
return ConcurrencyLimitedLLMAdapter(adapter_class(model, config.llm_connection))

# asked for
return RetryingLLMAdapter(
    ConcurrencyLimitedLLMAdapter(adapter_class(model, config.llm_connection))
)
```

plus the import beside the existing one on line 57:

```python
from core.llm.retrying_adapter import RetryingLLMAdapter
```

**THE NESTING ORDER MATTERS AND IS NOT ARBITRARY.** Retrying must be
the OUTER wrapper:

    Retrying(ConcurrencyLimited(concrete))   correct
    ConcurrencyLimited(Retrying(concrete))   holds a slot while sleeping

The step and synthesis models usually share one Ollama capped at a
small number of concurrent requests. Sleeping through a backoff while
holding one of those slots would let a struggling backend starve the
requests that are still healthy -- turning one user's transient
failure into a queue for everyone. Please keep the order as written.

**What it does NOT change:** `RetryingLLMAdapter` re-exposes
`max_concurrent_requests` from what it wraps and passes every `chat()`
argument through unchanged, so it satisfies the same `LLMAdapter`
Protocol and nothing downstream sees a different shape. Defaults are 3
attempts and 0.5 s backoff; both are constructor arguments if you want
them configurable from `llm_connection` instead -- say so and I will
add the plumbing on my side.

**Why it is safe to land before wiring:** only
`LLMUnavailable.retryable` is retried, and only the two transport
raise sites set it. Everything else -- a passed deadline, an
unparseable response, a 4xx -- is re-raised on the first attempt,
unchanged, carrying its original cause.

---

## R2 -- the core/llm sibling-independence contract enumerates modules

**Owner:** whoever owns `pyproject.toml` (not named in
000COORDINATION; backend by default)
**Severity:** low, but it is a guard that silently does not cover new
code.

The import-linter contract reads:

    core/llm/ siblings (agent_step_prompt, concurrency_limited_adapter,
    synthesis_prompt) stay independent of each other

It names three modules. `core/llm/retrying_adapter.py` and
`core/llm/prompt_values.py` are siblings and are NOT in the list, so
the contract does not constrain them -- a new sibling importing
another would pass lint. `./lint.sh` reports "8 kept, 0 broken" either
way, which is exactly the shape of a guard that looks like it is
working.

I have not edited `pyproject.toml`. Adding `retrying_adapter` (and
`prompt_values`, which is genuinely independent today) would close it.
Alternatively an `independence` contract over the whole `core.llm`
package would stop enumerating, and then no future sibling needs
remembering -- which is the actual failure here.

---

## R3 -- LB-8 asks to reverse a documented decision. Confirm or reverse it.

**FOUNDRY PRECEDENT FOUND, and it points at option 1.** See the
"Research" section of STATUS_agentloop.md. In short: Foundry's Object
Storage V2 guarantees read-your-writes for ontology queries -- "if an
object read occurring as part of an ontology query happens after a
user modification is sent, the object read is guaranteed to contain
the user edits" -- and edits "will be visible immediately after the
action completes". The eventually-consistent search index, where a
change takes time to appear in queries, is Object Storage V1
(Phonograph), which Palantir has placed in "the legacy phase of
development" with "no additional development expected" and which "will
not be supported for any new workflows".

So the split we have -- exact search reconciles, free-text does not --
is the V1 behaviour Foundry deliberately moved away from, not a
boundary Foundry endorses. I would now take option 1 without
hesitation.


**Owner:** backend (`core/ontology/mediator.py`)
**Status:** NOT BUILT. I stopped rather than reverse a deliberate,
documented scope boundary on my own.

LB-8 says the agent looks entities up by exact-match guess although
`search_object_free_text()` exists. Both halves are true. But that
method's own docstring says it was built

> for a real end user typing a few characters of a name or email into
> a search box, not for the model's own precise, single-field
> search_object() steps (which stay completely unchanged by this
> addition)

**AND IT DOES NOT RECONCILE PENDING WRITES.** Verified, not taken from
the comment: `_reconcile_search_with_pending_writes()` is called at
`mediator.py:1200` inside `search_object()` and nowhere inside
`search_object_free_text()`. Its docstring is accurate about this and
calls the gap acceptable because it is "a discovery aid, not a
correctness-sensitive read".

**That reasoning holds for a browse box and not for the agent.** A UI
user sees a list and picks from it. An agent's search result becomes
an ANSWER. An object mid-update would be silently missing from, or
wrongly present in, a result the user never gets to eyeball.

So LB-8 is a choice between three things, and it is not mine:

1. Reconcile pending writes in `search_object_free_text()`, then
   exposing it to the agent is safe. `core/ontology/**`, yours.
2. Expose it as-is and accept the window, documented at the step.
   Cheap, and it puts a knowingly-unreconciled read in the answer
   path.
3. Confirm the boundary stands and CLOSE LB-8 as declined. Also a
   legitimate answer -- the exact-match path works when the model has
   an exact value, and LB-2 (equality-only filters) may be the better
   fix for the same underlying complaint.

I would take 1 or 3. Tell me which and I will do my half.

---

## R4 -- call resume() after a write decision

**Owner:** backend (`api/routes.py`)
**Blocking:** AL-12 is inert without it, like AL-5 without R1.

`AgentLoop.resume()` is built, tested and merged on `agentloop`.
Nothing calls it.

**What it needs from the route:**

1. When a query returns with `result.pending_write` set, persist the
   whole `AgentLoopResult` alongside the pending write. `gathered`,
   `hops_used` and `fabricated_finishes` all matter -- the first two
   are what make the resume correct rather than a fresh run.
2. After `confirm_and_execute()` returns, call:

```python
resumed = generation.loop.resume(
    previous,                      # the persisted AgentLoopResult
    user_record,
    original_query_text,
    write_outcome,                 # confirm_and_execute()'s return
    context=..., refresh_user=...,
)
```

3. `refresh_user` MUST be passed. Without it the resume skips the
   authority re-check and relies on the per-hop backstop inside the
   loop -- which fires one read too late, after `visible_schema()` has
   been computed for a user whose access may have been withdrawn.
   That is the whole point of the item.
4. Handle `resumed.stop_reason == "authority_changed"` the way the
   route already handles it for a normal run.

**Not persistence advice:** where the paused result lives is yours.
The loop deliberately stores nothing, because a loop holding state
between requests is a second place authorisation can go stale.

---

## R5 -- ordering and a limit on search_object()

**Owner:** backend (`core/ontology/mediator.py`)
**Severity:** a class of question is currently UNANSWERABLE, not slow.

`search_object()` takes conditions and returns ids. It has no
ordering and no limit. So "the five largest transactions" cannot be
answered: the agent must fetch every match and rank them itself, and
`MAX_OBJECT_IDS` caps a fetch at 20. Beyond 20 rows the question has
no correct answer available at all. **Filters cannot fix this** -- a
filter narrows, it does not rank.

**THIS IS A NAMED, UNIVERSAL PATTERN.** "Queries include sections such
as LIMIT N or FETCH FIRST N ROWS. The pushdown for such a query is
called a TOP-N PUSHDOWN." Trino, Starburst, DuckDB and Databricks all
implement it; Databricks ships `pushdown.sortLimit.enabled` for
ORDER BY plus LIMIT, enabled by default.

**And Foundry has it in the API we already model on.** Search Objects
takes `orderBy` (a list of fields each with a direction) and
`pageSize`/`pageToken`.

**Guidance written for LLM agents specifically calls our current shape
the anti-pattern:** "Ask the LLM to use query pushdown and keep the
application layer thin. Don't fetch everything and filter the results
in TypeScript. Use database aggregation for metrics and summaries
rather than computing them from raw rows."

### What I am asking for

```python
def search_object(self, user_record, object_type, conditions=None,
                  visible_schema=None, context=None, outcome=None,
                  order_by=None,   # [(field, "asc"|"desc"), ...]
                  limit=None):     # int
```

**ORDER AND LIMIT TOGETHER, not separately.** "Always combine a sort
with a LIMIT -- sort pushdown failure is most costly when there is no
limit, because the engine must sort the entire result set."

**MAC IS THE PART THAT NEEDS YOUR JUDGEMENT, not mine.** This project
applies MAC in Python per object AFTER the engine returns, deliberately
-- it is never pushed into a query. A `limit` pushed to the engine
would therefore cap the rows BEFORE MAC filters them, so a caller
could ask for 5 and receive 2, with the other 3 silently dropped for
being out of compartment. Worse, the count itself leaks: "you may see
2 of the top 5" is information about rows the caller cannot read.

I do not know which way you want that resolved -- over-fetch then
trim, or refuse to push a limit at all -- and it is squarely a
security-model decision in a file I do not own. **That is the real
content of this request.**

### My half

Once it exists, exposing it to the agent is mine: a step vocabulary
for ordering, the prompt text, and the tests. Say when.
