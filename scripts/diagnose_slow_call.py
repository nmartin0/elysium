#!/usr/bin/env python3
"""
diagnose_slow_call.py  (why is a call slow: loading, or reading?)

I have guessed twice about why the integration suite's first call
exceeds its timeout -- the timeout itself, then keep_alive -- and been
wrong twice. The second guess made it slower. This stops guessing and
measures the two things that could be responsible, separately.

    MODEL LOAD     Ollama pulling weights into memory. Paid when a
                   model is not resident. dev's config measures this
                   at 12-47 seconds on this hardware.

    PROMPT EVAL    Reading the prompt at ~5.4 tokens/s with nothing
                   cached. AR-1 measured 520.89s cold against 50.58s
                   warm on a LONGER prompt.

They look identical from the outside -- one slow POST -- and they have
completely different fixes. Loading is keep_alive and how many models
are resident. Reading is prompt size and prefix reuse.

WHAT IT DOES

Three calls to the SAME model, in order, timed:

    1. tiny prompt, cold      load + a few tokens
    2. tiny prompt, again     no load, same few tokens
    3. the REAL prompt        no load, full prompt-eval

  (1) - (2) is roughly the model load.
  (3) - (2) is roughly the prompt evaluation.

If (1)-(2) is tens of seconds and (3)-(2) is hundreds, the problem is
the prompt and no timeout will fix it. If (1)-(2) is itself hundreds,
the box cannot hold the model and the two-model split is the problem.

RUN IT WHEN NOTHING ELSE IS USING THE MODEL, and paste the whole
output. `ollama ps` before and after is printed too, because how many
models are resident is the thing neither of my guesses checked.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from adapters.ollama_adapter import OllamaAdapter  # noqa: E402
from core.llm.interface import LLMUnavailable  # noqa: E402

TINY_SYSTEM = "You answer with one word."
TINY_USER = "Say ok."


def _ollama_ps(label: str) -> None:
    print(f"\n--- ollama ps ({label}) ---")
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True,
                             timeout=30)
        print(out.stdout.strip() or "(nothing resident)")
        if out.stderr.strip():
            print("stderr:", out.stderr.strip())
    except (OSError, subprocess.SubprocessError) as e:
        print(f"(could not run: {e})")


def _timed(adapter: OllamaAdapter, system: str, user: str, label: str) -> float:
    print(f"\n{label}")
    print(f"  prompt: {len(system) + len(user)} chars")
    started = time.monotonic()
    try:
        reply = adapter.chat(system, user, json_mode=False, temperature=0)
    except LLMUnavailable as e:
        elapsed = time.monotonic() - started
        print(f"  FAILED after {elapsed:.1f}s: {e}")
        return elapsed
    elapsed = time.monotonic() - started
    print(f"  {elapsed:.1f}s   reply: {reply[:60]!r}")
    return elapsed


def main() -> int:
    config_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        REPO / "tests" / "integration" / "fixtures"
    )
    config = yaml.safe_load((config_dir / "config.yaml").read_text())
    llm = config["llm"]
    connection = dict(llm["connection"])
    model = llm.get("step_model") or llm.get("model")

    print(f"config      {config_dir}")
    print(f"model       {model}")
    print(f"keep_alive  {connection.get('keep_alive', '(unset -- Ollama default)')}")
    print(f"timeout     {connection.get('request_timeout_seconds', 180)}s")

    # GENEROUS, so a slow call REPORTS rather than times out. The point
    # is to learn the number, and a timeout tells us only that it is
    # bigger than the timeout -- which is what we already know.
    connection["request_timeout_seconds"] = 1800
    adapter = OllamaAdapter(model, connection)

    _ollama_ps("before")

    cold = _timed(adapter, TINY_SYSTEM, TINY_USER, "1. tiny prompt, cold")
    warm = _timed(adapter, TINY_SYSTEM, TINY_USER, "2. tiny prompt, again")

    # The real system prompt, built the way the loop builds it.
    from core.llm.agent_step_prompt import _build_system_prompt

    schema = yaml.safe_load((config_dir / "ontology_schema.yaml").read_text())
    visible = {
        name: {"id_field": spec.get("id_field"), "fields": spec.get("fields", {})}
        for name, spec in schema.get("object_types", {}).items()
    }
    real_system = _build_system_prompt(visible, [], False, {})
    real_user = ("Question: What is the email address of the customer named "
                 "Ada Okafor?\n\nGathered so far: []\n\nWhat is the next step?")
    full = _timed(adapter, real_system, real_user, "3. the REAL step prompt")

    _ollama_ps("after")

    print("\n=== WHAT THIS SAYS ===")
    print(f"  model load        ~{cold - warm:>7.1f}s   (call 1 minus call 2)")
    print(f"  prompt evaluation ~{full - warm:>7.1f}s   (call 3 minus call 2)")
    print()
    if full - warm > (cold - warm) * 3:
        print("  THE PROMPT DOMINATES. No timeout fixes this; the prompt is")
        print("  the cost. LB-6 measured the system prompt as 87.5% fixed")
        print("  procedure, which is where the reduction would come from.")
    elif cold - warm > 120:
        print("  THE LOAD DOMINATES. The box is struggling to hold the model.")
        print("  dev's config runs ONE model for every call for this reason;")
        print("  this config runs two.")
    else:
        print("  NEITHER DOMINATES at this size. If the suite is still slow,")
        print("  the cost is elsewhere -- concurrency, or another process.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
