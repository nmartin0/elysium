"""
The Claude adapter that runs the local `claude` CLI.

Its point is the SUBSCRIPTION path: Anthropic's Agent SDK credit
"covers Claude Agent SDK usage, the claude -p command, and third-party
apps built on the Agent SDK", and explicitly excludes API keys --
"Claude Platform accounts using an API key don't receive a credit". So
reaching Claude through the CLI and reaching it through the API are
genuinely different things, and this adapter is the first.

TESTED WITH A FAKE `claude` ON PATH, which is a real limit worth being
plain about: these prove the command Elysium builds, the environment
it builds it in, and how it reads the reply. They do NOT prove the
real CLI accepts those flags -- that needs a machine with a
subscription, and this suite has none. The flags were verified once by
hand against `claude --help`; a future CLI version could change them
without a test here noticing.

The two properties tested hardest are the two that fail SILENTLY and
expensively: leaking an API key into the subprocess (which bills the
wrong account without saying so) and leaving the agent's tools enabled
(which hands filesystem and shell access to a subprocess inside
Elysium's boundary).
"""

import json
import os
import stat

import pytest

from adapters.claude_agent_sdk_adapter import ClaudeAgentSDKAdapter


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """Puts a stand-in `claude` on PATH that records how it was called.

    Writes its argv and the environment it saw to a file, then replies
    in the CLI's own JSON envelope shape.
    """
    record = tmp_path / "invocation.json"
    script = tmp_path / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "payload = {\n"
        "    'argv': sys.argv[1:],\n"
        "    'stdin': sys.stdin.read(),\n"
        "    'saw_api_key': 'ANTHROPIC_API_KEY' in os.environ,\n"
        "    'saw_auth_token': 'ANTHROPIC_AUTH_TOKEN' in os.environ,\n"
        "    'saw_unrelated': os.environ.get('ELYSIUM_UNRELATED'),\n"
        "}\n"
        f"open({str(record)!r}, 'w').write(json.dumps(payload))\n"
        "print(json.dumps({'result': 'the model answer'}))\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return record


def _invocation(record):
    return json.loads(record.read_text())


# --- The two failures that are silent and expensive ----------------------


def test_api_credentials_are_stripped_from_the_subprocess(fake_claude, monkeypatch):
    # THE most important property here. The CLI's credential precedence
    # puts ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN ABOVE the
    # subscription OAuth token, so leaving them set makes every call
    # bill API credits while the operator believes their subscription
    # is covering it. Invisible until the invoice arrives -- one user
    # reported roughly $52 consumed unintentionally this way.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-reach-the-subprocess")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "also-should-not")

    ClaudeAgentSDKAdapter("claude-sonnet-4-6", {}).chat("sys", "hello")

    invocation = _invocation(fake_claude)
    assert invocation["saw_api_key"] is False
    assert invocation["saw_auth_token"] is False


def test_the_rest_of_the_environment_is_preserved(fake_claude, monkeypatch):
    # Stripping must be surgical. The CLI needs HOME to find the
    # operator's login, and PATH to run at all -- handing it an empty
    # environment would break authentication entirely.
    monkeypatch.setenv("ELYSIUM_UNRELATED", "kept")

    ClaudeAgentSDKAdapter("claude-sonnet-4-6", {}).chat("sys", "hello")

    assert _invocation(fake_claude)["saw_unrelated"] == "kept"


def test_all_tools_are_disabled(fake_claude):
    # `claude` is an agentic tool that can read files and run shell
    # commands. Elysium guarantees it never writes to a customer's
    # systems and reads only what the ontology declares; an
    # unconstrained agent subprocess inside that boundary would undo
    # it. An invariant, not a configuration option.
    ClaudeAgentSDKAdapter("claude-sonnet-4-6", {}).chat("sys", "hello")

    argv = _invocation(fake_claude)["argv"]
    assert "--allowed-tools" in argv
    assert argv[argv.index("--allowed-tools") + 1] == ""


# --- The command Elysium actually builds ---------------------------------


def test_the_prompt_and_model_reach_the_cli(fake_claude):
    ClaudeAgentSDKAdapter("claude-opus-4-6", {}).chat("you are a helper", "what is 2+2?")

    invocation = _invocation(fake_claude)
    argv = invocation["argv"]
    assert "-p" in argv
    assert argv[argv.index("--model") + 1] == "claude-opus-4-6"
    assert argv[argv.index("--system-prompt") + 1] == "you are a helper"
    # The user message goes on stdin, not argv: a long prompt would
    # otherwise hit the shell's argument-length limit.
    assert invocation["stdin"] == "what is 2+2?"


def test_json_mode_instructs_the_model_not_just_the_envelope(fake_claude):
    # --output-format json describes the CLI's OWN envelope, not the
    # model's answer, so the instruction to emit JSON has to reach the
    # model itself.
    ClaudeAgentSDKAdapter("claude-sonnet-4-6", {}).chat("sys", "hi", json_mode=True)

    argv = _invocation(fake_claude)["argv"]
    assert "--append-system-prompt" in argv
    appended = argv[argv.index("--append-system-prompt") + 1]
    assert "JSON" in appended


def test_json_mode_appends_rather_than_replacing_the_callers_prompt(fake_claude):
    # The caller's system prompt carries the schema the JSON must
    # match. Replacing it would discard exactly the part that makes the
    # output useful.
    ClaudeAgentSDKAdapter("claude-sonnet-4-6", {}).chat(
        "the schema is {step: string}", "hi", json_mode=True
    )

    argv = _invocation(fake_claude)["argv"]
    assert argv[argv.index("--system-prompt") + 1] == "the schema is {step: string}"


def test_no_json_instruction_when_json_mode_is_off(fake_claude):
    ClaudeAgentSDKAdapter("claude-sonnet-4-6", {}).chat("sys", "hi", json_mode=False)

    assert "--append-system-prompt" not in _invocation(fake_claude)["argv"]


# --- Reading the reply ---------------------------------------------------


def test_the_answer_is_unwrapped_from_the_cli_envelope(fake_claude):
    answer = ClaudeAgentSDKAdapter("claude-sonnet-4-6", {}).chat("sys", "hi")

    assert answer == "the model answer"


def test_unexpected_output_is_returned_rather_than_raising(tmp_path, monkeypatch):
    # A future CLI version changing its envelope should degrade to
    # "returns something the caller can try to parse", not to "raises
    # on every call".
    script = tmp_path / "claude"
    script.write_text("#!/bin/sh\necho 'not json at all'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    assert ClaudeAgentSDKAdapter("claude-sonnet-4-6", {}).chat("sys", "hi") == "not json at all"


# --- Failing usefully ----------------------------------------------------


def test_a_missing_cli_is_reported_with_the_fix(monkeypatch, tmp_path):
    # An operator hitting this needs to know what to install and that
    # they must sign in -- the whole point of this adapter is the
    # subscription login.
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(ValueError, match="npm install -g @anthropic-ai/claude-code"):
        ClaudeAgentSDKAdapter("claude-sonnet-4-6", {})


def test_a_failing_cli_surfaces_its_own_error(tmp_path, monkeypatch):
    # stderr carries the real cause -- not signed in, credit exhausted,
    # unknown model -- which is far better than anything this adapter
    # could infer from an exit code.
    script = tmp_path / "claude"
    script.write_text("#!/bin/sh\necho 'Credit balance exhausted' >&2\nexit 1\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    with pytest.raises(RuntimeError, match="Credit balance exhausted"):
        ClaudeAgentSDKAdapter("claude-sonnet-4-6", {}).chat("sys", "hi")


def test_a_hanging_cli_times_out(tmp_path, monkeypatch):
    script = tmp_path / "claude"
    script.write_text("#!/bin/sh\nsleep 30\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    adapter = ClaudeAgentSDKAdapter("claude-sonnet-4-6", {"request_timeout_seconds": 1})

    with pytest.raises(RuntimeError, match="did not respond within"):
        adapter.chat("sys", "hi")


# --- Temperature ---------------------------------------------------------


def test_a_temperature_request_warns_once_rather_than_silently_ignoring(fake_claude, caplog):
    # Both of Elysium's callers pass temperature=0 for determinism, and
    # the CLI has no control for it. Raising would make the adapter
    # unusable; ignoring silently would be the quiet substitution this
    # project avoids. Once, because a warning on every call is noise an
    # operator learns to filter out.
    import logging

    adapter = ClaudeAgentSDKAdapter("claude-sonnet-4-6", {})

    with caplog.at_level(logging.WARNING):
        adapter.chat("sys", "hi", temperature=0)
        adapter.chat("sys", "hi", temperature=0)

    warnings = [r for r in caplog.records if "temperature" in r.getMessage()]
    assert len(warnings) == 1


def test_no_warning_when_no_temperature_is_requested(fake_claude, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        ClaudeAgentSDKAdapter("claude-sonnet-4-6", {}).chat("sys", "hi")

    assert not [r for r in caplog.records if "temperature" in r.getMessage()]


def test_it_registers_as_a_deployment_provider():
    from core.deployment_loader import _LLM_ADAPTER_REGISTRY

    assert _LLM_ADAPTER_REGISTRY["claude_agent_sdk"] is ClaudeAgentSDKAdapter
