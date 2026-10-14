"""The switch bench, run end to end without a model.

scripts/feature_bench.py decides the four agent switches on the
deployment's own model -- a session of an hour or more on a CPU. A
bench that crashes, or whose cases cannot be answered, costs that hour.
So everything but the model is real here: the shipped deployment synced
into a temporary directory, the loop, the mediator, the grader, and the
verdicts. The stand-in answers each case the way a model using the
switch would, which is also the proof each case is REACHABLE with it.
"""

import contextlib
import io
import json

import pytest

from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record
from core.llm.prompt_values import render_value
from scripts import feature_bench, llm_bench
from scripts.llm_bench import FEATURE_CASES, USER_ID, parse_features
from tests.unit.test_llm_bench import Scripted

#: What a model using each switch would send, in order, per case.
WITH_SWITCH = {
    "operators_in": [
        {"step": "search_object", "object_type": "Customer",
         "filter": {"name": {"in": ["Ada Okafor", "Bram Feldman"]}}},
        {"step": "get_object", "object_type": "Customer",
         "object_ids": ["cust_001", "cust_002"], "field_names": ["email"]},
    ],
    "operators_range": [
        {"step": "search_object", "object_type": "Transaction",
         "filter": {"customer_id": "cust_002", "amount": {"max": 0}}},
        {"step": "get_field", "object_type": "Transaction", "object_id": 4,
         "field_name": "category"},
    ],
    "free_text_surname": [
        {"step": "search_text", "object_type": "Customer", "text": "Feldman"},
        {"step": "get_field", "object_type": "Customer", "object_id": "cust_002",
         "field_name": "email"},
    ],
    "remember_preference": [
        {"step": "search_object", "object_type": "Customer", "filter": {"name": "Ada Okafor"}},
        {"step": "remember", "object_type": "Customer", "object_id": "cust_001",
         "text": "Prefers to be contacted by email."},
    ],
}


class SwitchUser(Scripted):
    """The original cases as llm_bench's stand-in answers them; the
    switch cases with the steps above, restarting at each new trial."""

    def __init__(self):
        super().__init__()
        self._next: dict[str, int] = {}

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
             deadline=None, usage=None, cancel=None):
        if user_message == "Reply with {}":
            return "{}"
        for case in FEATURE_CASES:
            if case.query in user_message:
                if "Gathered so far: []" in user_message:
                    self._next[case.name] = 0
                steps = WITH_SWITCH[case.name]
                index = self._next.get(case.name, 0)
                self._next[case.name] = index + 1
                return json.dumps(steps[index] if index < len(steps) else {"step": "finish"})
        return super().chat(system_prompt, user_message, json_mode, temperature,
                            deadline=deadline, usage=usage, cancel=cancel)


@pytest.fixture
def scripted_generations(synced_deployment, monkeypatch):
    """Every generation the bench builds answers through SwitchUser."""
    built = []

    def build(*args):
        generation = build_generation(*args)
        generation.loop.client = SwitchUser()
        built.append(generation)
        return generation

    monkeypatch.setattr(llm_bench, "build_generation", build)
    return synced_deployment, built


def test_every_switch_case_names_a_fact_the_deployment_holds(synced_deployment):
    generation = build_generation(synced_deployment.config_dir, synced_deployment.data_dir,
                                  synced_deployment.log_dir)
    user = resolve_user_record(generation.config.users, USER_ID,
                               generation.config.security_attribute)
    for case in FEATURE_CASES:
        for fact in case.expected_facts:
            value = generation.mediator.get_field(user, fact.object_type, fact.object_id,
                                                  fact.field_name)
            assert str(render_value(value)) == fact.value, f"{case.name}: {fact}"


def test_the_whole_session_runs_and_decides(scripted_generations, monkeypatch, capsys):
    paths, built = scripted_generations
    monkeypatch.setattr("sys.argv", [
        "feature_bench", "--config", str(paths.config_dir), "--data", str(paths.data_dir),
        "--log", str(paths.log_dir)])

    assert feature_bench.main() == 0

    written = json.loads((paths.log_dir / "feature_bench.json").read_text())
    arms = written["arms"]
    # WITH every switch on, every case of every arm passes...
    for arm in ("operators", "cap", "free_text", "remember"):
        assert all(entry["passed"] == entry["trials"] for entry in arms[arm].values()), arm
    # ...and with them off the new steps are refused. (The operator cases
    # can still pass off: refused, the stand-in reads the ids it already
    # knows -- which is why the verdict compares hops, not only passes.)
    assert arms["baseline"]["free_text_surname"]["passed"] == 0
    assert arms["baseline"]["remember_preference"]["passed"] == 0
    verdict = {v["switch"]: v["verdict"] for v in written["verdicts"]}
    assert verdict == {"filter_operators": "ON", "search_result_cap": verdict["search_result_cap"],
                       "free_text_search": "ON", "remember_from_query": "ON"}
    assert verdict["search_result_cap"].startswith("ON")
    assert "filter_operators: true" in capsys.readouterr().out


def test_the_bench_leaves_no_memory_behind(scripted_generations, monkeypatch):
    """THE CONTROL that the remember arm wrote one: without the cleanup
    the memory would still be there."""
    paths, built = scripted_generations
    monkeypatch.setattr("sys.argv", [
        "feature_bench", "--arms", "remember", "--config", str(paths.config_dir),
        "--data", str(paths.data_dir), "--log", str(paths.log_dir)])
    with contextlib.redirect_stdout(io.StringIO()) as printed:
        feature_bench.main()

    assert "removed 1 memory" in printed.getvalue()
    assert built[0].memory.store.about("Customer", "cust_001") == []


def test_an_arm_that_breaks_an_original_case_is_off():
    results = {"operators": {name: {"passed": 1, "trials": 1, "hops": [1], "seconds": [1]}
                             for name in (*feature_bench.ORIGINAL, "operators_in",
                                          "operators_range")}}
    results["operators"]["link_fanout"]["passed"] = 0

    [(switch, verdict, why)] = feature_bench.verdicts(results)
    assert (switch, verdict) == ("filter_operators", "OFF") and "original" in why


def test_more_hops_with_the_switch_than_without_is_off():
    """NEEDED, not merely working: if the model answers as fast without
    it, the switch is prompt for nothing."""
    row = {"passed": 1, "trials": 1, "seconds": [10]}
    results = {
        "baseline": {"free_text_surname": {**row, "hops": [2]}},
        "free_text": {"free_text_surname": {**row, "hops": [3]},
                      "one_field": {**row, "hops": [2]}, "two_constraints": {**row, "hops": [2]}},
    }
    [(_, verdict, _)] = feature_bench.verdicts(results)
    assert verdict == "OFF"


@pytest.mark.parametrize("names, cap, expected", [
    ("", None, None),
    ("none", None, ()),
    ("filter_operators,free_text_search", None, ("filter_operators", "free_text_search")),
    ("", 3, ("search_result_cap=3",)),
])
def test_the_switch_flags(names, cap, expected):
    features = parse_features(names, cap)
    assert (features if features is None else features.names_on) == expected


def test_an_unknown_switch_is_refused():
    with pytest.raises(ValueError, match="Known"):
        parse_features("filter_operator", None)


def test_an_unreachable_model_decides_nothing(scripted_generations, monkeypatch, capsys):
    """Found by running it with no model: the warm-up failed, the arm
    collected nothing, and the verdict printed was "OFF" -- a verdict
    about the outage, not the switch."""
    from core.llm.interface import LLMUnavailable

    class Gone:
        max_concurrent_requests = 1

        def chat(self, *args, **kwargs):
            raise LLMUnavailable("no model")

    paths, built = scripted_generations
    real_build = llm_bench.build_generation

    def build(*args):
        generation = real_build(*args)
        generation.loop.client = Gone()
        return generation

    monkeypatch.setattr(llm_bench, "build_generation", build)
    monkeypatch.setattr("sys.argv", [
        "feature_bench", "--config", str(paths.config_dir), "--data", str(paths.data_dir),
        "--log", str(paths.log_dir)])

    feature_bench.main()

    written = json.loads((paths.log_dir / "feature_bench.json").read_text())
    assert written["verdicts"] == [] and written["arms"] == {}
    assert list(written["unfinished"]) == ["baseline"], "the session should stop at once"
    assert "no arm finished" in capsys.readouterr().out
