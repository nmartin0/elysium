# Scalability: threads, inference, and what actually limits us

Audited and researched September 22, after the owner asked how much
threading support Elysium has and whether vLLM would handle more
requests than Ollama.

---

# Part 1. What Elysium does today (audited)

## 1.1 Two thread pools, deliberately separate

  api/app.py builds its OWN ThreadPoolExecutor sized from
  config.max_concurrent_requests -- "an explicit, understood
  concurrency boundary, not an ambient default", deliberately NOT
  Starlette's internal pool. Agent queries run through it.

  DEFAULT: 4.

  Separately, 51 of the route handlers are plain `def`, so Starlette
  runs them in its own thread pool (40 by default). That is why an
  ordinary read does not queue behind agent work -- the two kinds of
  request do not share a limit.

  SO THE SHAPE IS: reads scale to roughly 40 concurrent; AGENT QUERIES
  TO FOUR.

## 1.2 One property worth knowing before tuning

A ThreadPoolExecutor's size is fixed at construction, so
max_concurrent_requests is, in the code's own words, "configuration
that is unreloadable by NATURE rather than by oversight". Changing it
requires a restart, and templates/config.yaml says so where a deployer
reads it.

## 1.3 SQLite is not the bottleneck

WAL is enabled, and the measurements are recorded in
core/sqlite_connection.py: 1,312,596 reads at p50 0.002 ms, p99
0.01 ms, max 48 ms. With the caveat already documented there -- WAL
does not work over a network filesystem, and the deployment fails
loudly rather than silently if it cannot enable it.

---

# Part 2. vLLM versus Ollama, from the published benchmarks

## 2.1 The gap is entirely a CONCURRENCY story

  - AT ONE REQUEST THEY ARE NEAR-PARITY: "differences are typically
    single digits to ~20%, and Ollama is often faster on
    first-response latency because it has no scheduler queuing
    overhead".
  - PAST ROUGHLY 4-8 CONCURRENT REQUESTS vLLM pulls ahead, with
    multi-source estimates of 2x to 9x aggregate throughput at
    moderate concurrency.
  - AT SATURATION THE GAP IS LARGE. Red Hat's GuideLLM benchmark on an
    A100 measured vLLM at 793 output tokens/sec against Ollama's 41,
    with p99 latency of 80 ms versus 673 ms. An independent test found
    the same direction (up to 3.23x at concurrency 128) on different
    hardware and a different model.

## 2.2 The mechanism, which explains where it does and does not apply

Ollama is built on llama.cpp's server and CAPS PARALLEL REQUESTS --
Red Hat found the default cap at 4 -- queuing the rest. vLLM's
continuous batching inserts new requests into the in-flight batch
token by token, and PagedAttention manages the KV cache in fixed-size
pages rather than one contiguous allocation per request, so the
scheduler can pack many requests without fragmenting memory.

"That architectural difference -- not a difference in raw decode speed
-- is what produces the concurrency-scaling gap", which is also why
"the gap nearly disappears at a single concurrent user".

## 2.3 A coincidence worth noticing

Ollama's default parallel cap is FOUR. Elysium's
max_concurrent_requests default is FOUR. The numbers line up by
accident, but the consequence is real: today's deployment is tuned for
exactly the regime where Ollama is fine, and SWAPPING THE ENGINE
WITHOUT RAISING THE LIMIT WOULD CHANGE NOTHING.

## 2.4 The decision

  - vLLM IS THE RIGHT ANSWER WHEN there are concurrent agent users and
    a real GPU. It is not an improvement for a single analyst, and it
    does not target Apple Silicon at all.
  - IT IS A SMALL PIECE OF WORK, because the interface already exists:
    an LLMAdapter protocol, a concurrency-limited wrapper, and chat()
    carrying a deadline and token accounting (patches 327-328). A vLLM
    adapter is an OpenAI-compatible HTTP client.
  - SO IT BECOMES A PER-DEPLOYMENT CHOICE rather than a bet: Ollama
    for a laptop or a small team, vLLM where concurrency is real.
  - AND max_concurrent_requests SHOULD RISE FIRST, since it caps agent
    concurrency at four regardless of the engine behind it. The right
    default depends on the engine, which argues for stating the
    relationship in config rather than leaving two unrelated fours to
    line up by luck.

---

# Part 3. What actually makes the product feel slow

NOT THREADS. The interface is unresponsive to backend changes because
NOTHING PUSHES: one panel polls every 30 seconds and everything else
fetches once (measured; the design is UI-LIVE, in
LIVE_UPDATES_AND_PIPELINE_BUILDER.md part 1).

Keep the two separate when deciding what to build:

    vLLM makes the agent faster UNDER LOAD.
    Server-sent events make the whole product FEEL ALIVE.

They are independent, and the second is the one a person notices
every day.
