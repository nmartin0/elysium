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


def test_every_stored_kind_is_the_computed_one():
    assert cl.main(["--check"]) == 0
