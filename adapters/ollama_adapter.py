"""
ollama_adapter.py  (Ollama-specific -- the only place Ollama's API shape exists)

Implements core/llm/interface.py's LLMAdapter contract. Constructed from
(model, connection: dict) -- connection comes straight from this
deployment's config.yaml llm.connection block (e.g. {"base_url": ...,
"request_timeout_seconds": ...}), opaque to core/, meaningful only here
-- same pattern as adapters/sqlite_adapter.py's SQLiteAdapter.

Used by: core/deployment_loader.py's build_llm_adapter() factory
"""

import logging
from typing import Any

import requests

from core.llm.interface import LLMUnavailable

logger = logging.getLogger(__name__)

# WHEN A PROMPT IS TOO BIG TO TRUST, as a fraction of the window.
#
# 0.8 IS THE PUBLISHED PRACTICE. AWS's agentic-AI lens names
# exactly this: "alarms when context window utilization exceeds
# 80%, triggering summarization or pruning workflows before the
# limit becomes a hard wall".
#
# THE WALL IS NOT AN ERROR, which is why it matters. A model given
# more than it can hold does not refuse -- it TRUNCATES, and
# answers from what survived. A worse answer, not a crash.
CONTEXT_WARNING_FRACTION = 0.8

# ROUGHLY FOUR CHARACTERS PER TOKEN, the usual figure for English
# and JSON. Deliberately approximate: a real tokeniser would mean
# shipping one per model, and this says "you are near the wall"
# rather than counting.
_CHARS_PER_TOKEN = 4


class OllamaAdapter:
    def __init__(self, model: str, connection: dict):
        self.model = model
        self.base_url = connection["base_url"]
        self.timeout_seconds = connection.get("request_timeout_seconds", 180)
        # Real capacity limit on THIS hardware -- one local model, one
        # inference at a time. A hosted API adapter would declare a
        # much higher number, or None.
        self.max_concurrent_requests = connection.get("max_concurrent_requests", 1)
        # PROVIDER OPTIONS, passed through opaquely. Anything Ollama
        # accepts under its own "options" key -- num_ctx, num_thread,
        # num_batch, seed, and so on -- is a deployment decision, not a
        # code change: different hardware genuinely needs different
        # values, and enumerating Ollama's option names in core/ would
        # both break llm_connection's deliberate opacity and go stale.
        #
        # NAMESPACED UNDER "options", NEVER MERGED INTO THE PAYLOAD.
        # This is a security property, not a style choice. Ollama's
        # "messages" and "format" are TOP-LEVEL keys; a blind
        # payload.update(config) would let a config file rewrite the
        # conversation itself or silently disable JSON mode. Config
        # supplies inference parameters and nothing else.
        #
        # The cost of opacity, stated plainly: a misspelled option name
        # is ignored by Ollama at request time rather than rejected at
        # load, which is weaker than this project's usual "fail loudly
        # at startup" discipline. Accepted because validating the names
        # here would require core/ to carry Ollama's option list.
        self.options = dict(connection.get("options") or {})
        # Whether the model stays resident between requests. Ollama's
        # own default evicts after five minutes; -1 pins it. On CPU-only
        # hardware a reload has been measured at 12-47 seconds, paid
        # once per query or worse, so this is worth a deployment being
        # able to set.
        self.keep_alive = connection.get("keep_alive")

    def _warn_if_context_is_tight(self, system_prompt: str,
                                  user_message: str) -> None:
        """Says so when a prompt is close to the window it must fit.

        MEASURED, on the shipped deployment with num_ctx 4096: the
        system prompt alone is about 1,138 tokens (28% of the
        window), one heavy hop reaches 50%, four reach 114% and the
        default max_hops of eight reaches 200%.

        So the loop can exceed its own configured window at HOP
        FOUR, well before it stops on its own.

        A WARNING, NOT A REFUSAL. Truncation may still produce a
        fine answer, and a deployment that raises num_ctx or asks
        narrower questions never sees this. Refusing would turn a
        degraded answer into no answer, which is worse.

        THIS IS THE INSTRUMENTATION HALF of the context-rot item.
        What to DO about it -- summarise older hops, cap what
        enters `gathered`, raise the window -- is a separate
        decision that needed this measurement first.
        """
        window = self.options.get("num_ctx")
        if not window:
            # A DEPLOYMENT THAT DOES NOT STATE ONE gets no warning
            # rather than a guessed threshold: the server's own
            # default is not knowable from here.
            return

        estimated = (
            len(system_prompt) + len(user_message)
        ) // _CHARS_PER_TOKEN
        if estimated < window * CONTEXT_WARNING_FRACTION:
            return

        logger.warning(
            "a prompt of roughly %d tokens is %.0f%% of num_ctx %d. "
            "Past the window the server TRUNCATES rather than failing, "
            "so the answer may be built from part of what was gathered.",
            estimated, estimated / window * 100, window,
        )

    def chat(self, system_prompt: str, user_message: str,
              json_mode: bool = False, temperature: float | None = None) -> str:
        # Raises requests.RequestException on network/timeout failure --
        # callers decide what "failure" should mean for them (e.g. the
        # agent loop fails closed to "finish"; synthesis returns an
        # error string), so this method doesn't swallow the exception.
        #
        # Explicitly dict[str, Any] -- without this, mypy infers a
        # narrower type from the literal dict below (a mix of str,
        # list[dict[str, str]], and bool), then the two conditional
        # assignments further down (adding a str, then a dict[str,
        # float]) don't structurally fit that inferred type either,
        # surfacing as an incompatibility against requests.post()'s
        # own json parameter stub (JsonType) -- a real, environment-
        # dependent finding: only visible with types-requests actually
        # installed, which is why this went unnoticed until checked
        # against an environment that had it.
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        }
        self._warn_if_context_is_tight(system_prompt, user_message)
        if json_mode:
            payload["format"] = "json"
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive
        # THE CALLER'S TEMPERATURE WINS over a configured one,
        # deliberately. next_step() passes temperature=0 because a step
        # has to parse as one specific JSON shape; a deployment quietly
        # raising it would make step selection erratic and the audit
        # trail harder to reason about. Config sets a default for calls
        # that express no opinion, never an override for those that do.
        # DELIBERATION OFF BY DEFAULT, for the same reason the caller's
        # temperature wins above: a reasoning model emits a chain of
        # thought BEFORE its answer, and neither call here wants one. A
        # step has to parse as a specific JSON shape; synthesis has a
        # human waiting.
        #
        # THE COST IS THE WHOLE STORY ON THIS HARDWARE. Measured on
        # this deployment, asked to reply with a single word: phi4-mini
        # emitted 2 tokens, gemma4:e2b 84, qwen3.5:2b 370. At ~1.5
        # tokens/sec that is under a second against six minutes, and
        # think=false cut qwen3.5:2b from 370 tokens back to 2.
        #
        # NOTHING IS PAID TODAY -- no configured model reasons -- and
        # that is exactly why this is worth sending now. The newest
        # small models increasingly reason BY DEFAULT, so the first
        # deployment to configure one would inherit a several-hundred-
        # token surprise per hop with nothing in its config mentioning
        # it. The failure would look like the deployment being slow.
        #
        # A DEPLOYMENT CAN STILL ASK FOR IT, by setting think in its own
        # llm_connection options -- which is why this is applied BEFORE
        # the passthrough rather than after. The Ollama-specific key
        # objection is answered by where this lives: an Ollama key in
        # the Ollama adapter is that adapter's job, and a provider
        # without the concept simply never sees it.
        payload["think"] = False

        options = {**self.options}
        if temperature is not None:
            options["temperature"] = temperature
        if "think" in self.options:
            # An explicit deployment choice wins. `think` is not an
            # Ollama *option*, it is a top-level payload key, so a
            # deployment naming it in connection options means the
            # payload rather than the options block.
            payload["think"] = self.options["think"]
            options.pop("think", None)

        if options:
            payload["options"] = options

        try:
            response = requests.post(self.base_url, json=payload, timeout=self.timeout_seconds)
        except requests.RequestException as e:
            # Translated at the boundary so callers never need to know
            # this adapter uses `requests` -- see LLMUnavailable.
            raise LLMUnavailable(f"Could not reach the model at {self.base_url}: {e}") from e
        response.raise_for_status()
        return response.json()["message"]["content"]
