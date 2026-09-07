"""
claude_agent_sdk_adapter.py  (LLM backend -- Claude, via the local CLI)

Runs `claude -p` as a subprocess rather than calling an HTTP API. That
shape is deliberate and is the whole point of this adapter: it
authenticates with the operator's existing Claude subscription login,
drawing on the monthly Agent SDK credit that Pro, Max, Team and
Enterprise plans include, rather than on separately-billed API credits.

Anthropic's own documentation for that credit says it "covers Claude
Agent SDK usage, the claude -p command, and third-party apps built on
the Agent SDK", and that such usage "no longer counts toward your
Claude plan's usage limits" -- it is a separate pool. Their API-key
path is explicitly excluded: "Claude Platform accounts using an API
key don't receive a credit."

So there are two genuinely different ways to reach Claude, and this is
the subscription one. An API-key adapter would be faster and simpler
and would cost money per token; this trades latency for a bill the
operator has already paid.

REQUIRES the `claude` CLI installed and logged in. This adapter does
not manage authentication and deliberately cannot: it never sees a
credential, it just runs a command the operator has already
authorised.

THREE THINGS THIS ADAPTER GETS RIGHT THAT ARE EASY TO GET WRONG:

1. It STRIPS ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN from the
   subprocess environment. The CLI's credential precedence puts those
   ABOVE the subscription OAuth token, so leaving them set makes every
   call bill API credits silently while the operator believes their
   subscription is covering it. This is a real, reported failure --
   one user reported roughly $52 consumed unintentionally that way --
   and it is invisible until the invoice arrives.

2. It DISABLES ALL TOOLS. `claude` is an agentic tool that can read
   files and run shell commands. Elysium's central guarantee is that
   it never writes to a customer's systems and reads only what the
   ontology declares; handing an unconstrained agent a subprocess
   inside that boundary would undo it. Not a configuration option --
   an invariant, asserted by a test.

3. It CANNOT honour temperature, and says so rather than pretending.
   See chat() below.
"""

import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

DISALLOWED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class ClaudeAgentSDKAdapter:
    """Talks to Claude through the local `claude` CLI in print mode."""

    def __init__(self, model: str, connection: dict):
        self.model = model
        self.executable = connection.get("executable", "claude")
        self.timeout_seconds = connection.get("request_timeout_seconds", 300)
        # Default 1, not higher. Each call spawns a Node process, and
        # the subscription credit is a shared monthly pool rather than
        # a per-second rate limit -- so concurrency buys little and
        # risks exhausting the credit faster than an operator expects.
        self.max_concurrent_requests = connection.get("max_concurrent_requests", 1)
        self._warned_about_temperature = False

        if shutil.which(self.executable) is None:
            raise ValueError(
                f"The {self.executable!r} command was not found on PATH. This adapter runs "
                f"Claude through the local CLI so that it draws on your Claude subscription's "
                f"Agent SDK credit; install it with "
                f"`npm install -g @anthropic-ai/claude-code` and sign in with `claude login`."
            )

    def _environment(self) -> dict:
        """The subprocess environment, with API credentials removed.

        Removed rather than overridden: an empty ANTHROPIC_API_KEY is
        still an ANTHROPIC_API_KEY as far as the CLI's precedence
        rules are concerned.
        """
        environment = dict(os.environ)
        for name in DISALLOWED_ENV:
            environment.pop(name, None)
        return environment

    def _command(self, system_prompt: str, json_mode: bool) -> list[str]:
        command = [
            self.executable,
            "-p",
            "--model", self.model,
            "--system-prompt", system_prompt,
            "--output-format", "json",
            # NO TOOLS. See this module's own docstring: an
            # unconstrained agent subprocess inside Elysium's boundary
            # would undo the guarantee that it reads only what the
            # ontology declares.
            "--allowed-tools", "",
        ]
        if json_mode:
            # The CLI's --output-format json describes its own envelope,
            # not the model's answer, so the instruction to emit JSON
            # has to reach the model itself. Appended rather than
            # replacing the caller's system prompt, which already
            # carries the schema the JSON must match.
            command += [
                "--append-system-prompt",
                "Respond with a single valid JSON object and nothing else. "
                "No prose before or after it, and no markdown code fence.",
            ]
        return command

    def chat(self, system_prompt: str, user_message: str,
              json_mode: bool = False, temperature: float | None = None) -> str:
        # TEMPERATURE IS NOT SUPPORTED, and that is a real behavioural
        # difference rather than a detail. Both of Elysium's callers ask
        # for temperature=0 because they want deterministic output --
        # agent_step_prompt.py in particular needs parseable JSON steps
        # -- and the CLI exposes no temperature control at all (verified
        # against `claude --help`). Answers will therefore vary more
        # between identical requests than Ollama's do.
        #
        # Warned ONCE at first use rather than raised. Raising would
        # make this adapter unusable, since every existing caller
        # passes temperature=0; and the agent loop already recovers
        # from a malformed step, so the variance degrades quality
        # rather than breaking correctness. Warned rather than ignored
        # because silently accepting a determinism request this adapter
        # cannot meet is the kind of quiet substitution that makes a
        # system untrustworthy.
        #
        # Once, not per call: a warning on every request is noise an
        # operator learns to filter out, which is the same as no
        # warning at all.
        if temperature is not None and not self._warned_about_temperature:
            self._warned_about_temperature = True
            logger.warning(
                "%s ignores temperature=%r: the claude CLI exposes no control for it, "
                "so responses will vary more between identical requests than a "
                "temperature-honouring backend's would.",
                type(self).__name__, temperature,
            )

        try:
            completed = subprocess.run(
                self._command(system_prompt, json_mode),
                input=user_message,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=self._environment(),
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"The {self.executable!r} command did not respond within "
                f"{self.timeout_seconds}s."
            ) from e

        if completed.returncode != 0:
            # stderr carries the CLI's own message, which names the real
            # cause -- not signed in, credit exhausted, unknown model --
            # far better than anything this adapter could infer.
            raise RuntimeError(
                f"The {self.executable!r} command failed (exit {completed.returncode}): "
                f"{completed.stderr.strip() or 'no error output'}"
            )

        return self._extract_text(completed.stdout)

    @staticmethod
    def _extract_text(stdout: str) -> str:
        """The model's answer, out of the CLI's JSON envelope.

        Falls back to the raw output if it is not the envelope this
        expects. A future CLI version changing its shape should degrade
        to "returns something the caller can try to parse" rather than
        to "raises on every call".
        """
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout.strip()

        if isinstance(envelope, dict):
            for key in ("result", "text", "content"):
                value = envelope.get(key)
                if isinstance(value, str):
                    return value.strip()
        return stdout.strip()
