"""classify_controls decides mechanical or semantic from the edit alone."""

import classify_controls as cl
import pytest


@pytest.mark.parametrize("old,new", [
    ("    if name in links:", "    if True:"),
    ("    if name in links:", "    if False:"),
    ("get_link_target(raw) in self.declared\n", "True\n"),
    ("    audit.write(entry)", "    pass"),
    ("        raise Denied(name)", "        return"),
    ("    if a > b:", "    if a >= b:"),
    ("x = values[0]", "x = values[1]"),
    ("elapsed < limit", "elapsed > limit"),
])
def test_mechanical_edits(old, new):
    assert cl.classify(old, new) == "mechanical"


@pytest.mark.parametrize("old,new", [
    ("    return pa.concat_tables([kept, changed])", "    return changed"),
    ("        caps.in_values.spend(len(value))\n", ""),
    ("met = all(met_each) if trigger.combine == 'all' else any(met_each)", "met = any(met_each)"),
    ("a = f(x)\nb = g(y)", "a = g(x)\nb = f(y)"),
    ("x = foo(1)", "x = bar.baz(1)"),
])
def test_semantic_edits(old, new):
    assert cl.classify(old, new) == "semantic"


def test_toml_strings_read_back_exactly():
    import tomllib

    for text in ["", "plain", "it's", "two\nlines\n", "\nstarts with newline", "ends with ''",
                 "tab\there", 'quote " and \\ backslash', "bell\x07", "del\x7f", "caf\u00e9"]:
        assert tomllib.loads("v = " + cl.toml_string(text))["v"] == text


def test_module_names():
    assert cl.module_name("src/elysium/core/x.py") == "elysium.core.x"
    assert cl.module_name("sim/simulator/drift.py") == "sim.simulator.drift"
    assert cl.module_name("install/install.sh") == "install.install"


def test_invariant_is_read_from_the_description():
    assert cl.guess_invariant("an erasure leaves no copy") == "I6"
    assert cl.guess_invariant("a withheld table is not listed") == "I3"
    assert cl.guess_invariant("the parser skips blank lines") == "none"


def test_convert_legacy_writes_files_that_round_trip(tmp_path):
    import tomllib

    runner = tmp_path / "legacy.py"
    runner.write_text(
        "from dataclasses import dataclass, field\n"
        "@dataclass\nclass Control:\n    describes: str\n    path: str\n    old: str\n    new: str\n"
        "    tests: list = field(default_factory=list)\n"
        "CONTROLS = [\n"
        "    Control(describes='x', path='src/elysium/a.py', old='if a:\\n    b',\n"
        "            new='if True:\\n    b', tests=['t::a']),\n"
        "    Control(describes='y', path='src/elysium/a.py', old='c', new='d', tests=['t::b']),\n"
        "]\n")

    counts = cl.convert_legacy(tmp_path / "out", runner)

    assert counts == {"elysium.a": 2}
    records = tomllib.loads((tmp_path / "out" / "elysium.a.toml").read_text())["control"]
    assert [r["id"] for r in records] == ["LEG-0001", "LEG-0002"]
    assert [r["kind"] for r in records] == ["mechanical", "mechanical"]
    assert records[0]["old"] == "if a:\n    b"


def test_check_flags_a_wrong_kind_and_write_fixes_it(tmp_path, monkeypatch):
    directory = tmp_path / "controls" / "api"
    directory.mkdir(parents=True)
    file = directory / "T.toml"
    file.write_text(
        '[[control]]\nid = "A-1"\ndescribes = "d"\ninvariant = "none"\nkind = "semantic"\n'
        "path = 'p.py'\nold = 'if a:'\nnew = 'if True:'\ntests = ['t::a']\nexpect = \"fails\"\n")
    monkeypatch.setattr(cl, "CONTROLS_DIR", tmp_path / "controls")
    monkeypatch.setattr(cl, "ROOT", tmp_path)

    assert cl.main(["--check"]) == 1
    assert cl.main(["--write"]) == 0
    assert 'kind = "mechanical"' in file.read_text()
    assert cl.main(["--check"]) == 0
