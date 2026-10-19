"""scripts/compare_models.py: D1 and D2 as one table (19 October).

Driven end to end on scripted models, since no model runs here: each
named model is a different scripted speed, and the table must say which
is faster, how many each got right, and where the time went.
"""

import contextlib
import dataclasses
import io
import json

import scripts.compare_models as compare
import scripts.llm_bench as bench
from core.request_context import TokenUsage
from tests.unit.test_llm_bench import Scripted  # noqa: F401 - the shared scripted model

SPEED = {"fast-model": 6.0, "slow-model": 1.5}


class _AtSpeed:
    """Scripted steps that write 12 tokens at the named model's speed."""

    max_concurrent_requests = 1

    def __init__(self):
        self.model = "configured"
        self._script = Scripted()

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
             deadline=None, usage=None, cancel=None):
        if usage is not None:
            writing = 12 / SPEED.get(self.model, 1.0)
            usage.add(1000, 12, seconds=writing + 1, reading_seconds=1.0, writing_seconds=writing,
                      cached_input_tokens=900)
        return self._script.chat(system_prompt, user_message, json_mode, temperature)


class _Answer:
    max_concurrent_requests = 1

    def __init__(self):
        self.model = "configured"
        self.models_used = []

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
             deadline=None, usage=None, cancel=None):
        self.models_used.append(self.model)
        if usage is not None:
            writing = 60 / SPEED.get(self.model, 1.0)
            usage.add(2000, 60, seconds=writing, writing_seconds=writing)
        return "Ada Okafor's email address is ada.okafor@example.com [R1]."


def _compare(monkeypatch, synced_deployment, argv):
    from core.deployment_loader import build_generation

    answers = []

    def generation_for(*_):
        generation = build_generation(synced_deployment.config_dir, synced_deployment.data_dir,
                                      synced_deployment.log_dir)
        generation.loop.client = _AtSpeed()
        answer = _Answer()
        answers.append(answer)
        return dataclasses.replace(generation, synthesis_client=answer)

    monkeypatch.setattr(bench, "build_generation", generation_for)
    monkeypatch.setenv("ELYSIUM_CONFIG_DIR", str(synced_deployment.config_dir))
    monkeypatch.setenv("ELYSIUM_DATA_DIR", str(synced_deployment.data_dir))
    monkeypatch.setenv("ELYSIUM_LOG_DIR", str(synced_deployment.log_dir))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = compare.main(argv)
    return status, out.getvalue(), answers


def test_each_model_is_run_and_the_faster_one_shows_it(monkeypatch, synced_deployment):
    status, out, _ = _compare(monkeypatch, synced_deployment,
                              ["slow-model", "fast-model", "--cases", "one_field"])

    assert status == 0
    table = out.split("======== MODELS ========")[1]
    slow = next(line for line in table.splitlines() if line.strip().startswith("slow-model"))
    fast = next(line for line in table.splitlines() if line.strip().startswith("fast-model"))
    assert "1/1" in slow and "1/1" in fast
    assert slow.split()[7] == "1.5" and fast.split()[7] == "6.0"   # write/s, as the server said
    assert slow.split()[2] == "1/1"   # said: the answer stated the email
    saved = json.loads((synced_deployment.log_dir / "compare_models.json").read_text())
    # WHAT THE SERVER REPORTED, not the clock: a scripted model is no
    # slower in wall time, but says it wrote four times faster.
    assert saved["models"]["fast-model"]["step_seconds"] < saved["models"]["slow-model"]["step_seconds"]
    assert saved["models"]["fast-model"]["answer_seconds"] < saved["models"]["slow-model"]["answer_seconds"]
    # 900 of each step call's 1,000 prompt tokens reused. The answer call
    # said nothing of reuse, and a call that did not say is left out.
    assert saved["models"]["fast-model"]["reused"] == 0.9


def test_one_answer_model_for_all(monkeypatch, synced_deployment):
    status, out, answers = _compare(monkeypatch, synced_deployment,
                                    ["slow-model", "fast-model", "--cases", "one_field",
                                     "--answer-model", "fast-model"])

    assert status == 0 and "every answer written by fast-model" in out
    assert [answer.models_used for answer in answers] == [["fast-model"], ["fast-model"]]


def test_an_unknown_case_is_refused(monkeypatch, synced_deployment):
    status, out, _ = _compare(monkeypatch, synced_deployment, ["m", "--cases", "nope"])

    assert status == 2 and "Unknown case" in out


def test_not_told_is_a_dash_not_zero():
    usage = TokenUsage()
    usage.for_part("step").add(None, None, seconds=3.0)
    row = compare.summarise([], [("c", usage, 3.0)])

    assert row["write_per_second"] is None and row["reused"] is None
    assert "-" in compare.table({"m": row})
