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
