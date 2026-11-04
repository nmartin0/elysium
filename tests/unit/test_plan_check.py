"""plan_check finds every kind of broken plan and passes the real one."""

from pathlib import Path

import plan_check
import pytest

ROOT = Path(__file__).resolve().parents[2]


def header(cid, wave="1", status="OPEN", depends="-", contracts="C-X", owns=("src/a.py",), size=None):
    size = size or ("L" if cid.startswith("T0.") else "S")
    lines = ["```card", f"id: {cid}", f"wave: {wave}", f"status: {status}", f"size: {size}",
             "model: Sonnet", f"depends: {depends}", f"contracts: {contracts}", "owns:"]
    return "\n".join(lines + [f"  - {p}" for p in owns] + ["```"])


def card(cid, **kw):
    return f"#### {cid} · title\n\n{header(cid, **kw)}\n\nbody\n"


def item(cid, **kw):
    kw.setdefault("wave", "T0")
    kw.setdefault("owns", (f"tools/{cid}.py",))
    return f"### {cid} title\n\n{header(cid, **kw)}\n\nbody\n"


def build(cards=(), items=None, rows=None):
    """A roadmap with the 17 Tier 0 items, the given cards and a wave table."""
    ids = plan_check.TIER0_IDS
    items = items or {}
    text = "# Elysium roadmap\n\n## 4. Tier 0\n\n" + "".join(items.get(i) or item(i) for i in ids)
    text += "\n## 5. Task cards\n\n" + "".join(cards)
    text += "\n### C-X · A contract\n\ntext\n"
    if rows is None:
        rows = [("0a", "now", "-", ["DOC-00"]), ("1", "T0.4 merged and wave 0a closed", "T0.5", ["A-1"])]
    text += "\n## 6. Waves\n\n| Wave | Opens when | Tier 0 beside it | Cards | Count |\n|---|---|---|---|---|\n"
    text += "".join(f"| **{w}** | {o} | {t} | {', '.join(c)} | {len(c)} |\n" for w, o, t, c in rows)
    return text + "\n## 7. Blocked\n"


def good():
    return build([card("DOC-00", wave="0a", owns=("docs/x.md",)),
                  card("MEAS-1", wave="1", depends="DOC-00", owns=("docs/m.md",))],
                 rows=[("0a", "now", "-", ["DOC-00"]), ("1", "T0.4 merged and wave 0a closed", "T0.5", ["MEAS-1"])])


def test_a_good_plan_passes():
    assert plan_check.check(good()) == []


def test_the_real_roadmap_passes():
    assert plan_check.check((ROOT / "docs/roadmap.md").read_text()) == []


def broken(old, new, text=None):
    text = text or good()
    assert old in text, old
    return text.replace(old, new, 1)


M1 = "status: OPEN\nsize: S\nmodel: Sonnet\ndepends: DOC-00"
ROW1 = "| **1** | T0.4 merged and wave 0a closed | T0.5 | MEAS-1 | 1 |"


def extra_card(text, cid, **kw):
    return text.replace("## 5. Task cards\n", "## 5. Task cards\n\n" + card(cid, **kw), 1)


def two_in_wave_1(text):
    text = extra_card(text, "MEAS-2", wave="1", owns=("docs/**",))
    return text.replace("| MEAS-1 | 1 |", "| MEAS-1, MEAS-2 | 2 |")


CASES = {
    "key order": (lambda t: broken("model: Sonnet\ndepends: DOC-00", "depends: DOC-00\nmodel: Sonnet"),
                  "header keys"),
    "bad status": (lambda t: broken(M1, M1.replace("OPEN", "WAITING")), "bad status"),
    "bad model": (lambda t: broken("model: Sonnet\ndepends: DOC-00", "model: Opus\ndepends: DOC-00"), "bad model"),
    "defined twice": (lambda t: extra_card(t, "DOC-00", wave="0a", owns=("docs/y.md",)), "DOC-00: defined twice"),
    "missing header": (lambda t: broken("#### MEAS-1 · title\n\n```card", "#### MEAS-1 · title\n\ntext\n\n```card"),
                       "MEAS-1: no header block"),
    "undefined dependency": (lambda t: broken("depends: DOC-00", "depends: DOC-99"),
                             "depends on DOC-99, which is not defined"),
    "undefined contract": (lambda t: broken("contracts: C-X\nowns:\n  - docs/m.md",
                                            "contracts: C-NOPE\nowns:\n  - docs/m.md"), "contract C-NOPE"),
    "same wave dependency": (lambda t: broken("depends: DOC-00", "depends: MEAS-1"), "MEAS-1: depends on MEAS-1"),
    "later tier 0": (lambda t: broken("depends: DOC-00", "depends: T0.5"),
                     "depends on T0.5, not merged when wave 1 opens"),
    "overlapping owns": (two_in_wave_1, "MEAS-1 and MEAS-2 both own"),
    "owns beside tier 0": (lambda t: broken("  - docs/m.md", "  - tools/T0.5.py"), "which T0.5 beside it owns"),
    "wave row disagrees": (lambda t: broken(ROW1, ROW1.replace("MEAS-1 | 1", "- | 0")),
                           "MEAS-1 (wave 1) is not listed"),
    "wrong count": (lambda t: broken("MEAS-1 | 1 |", "MEAS-1 | 4 |"), "count 4"),
    "post status": (lambda t: broken(M1, M1.replace("OPEN", "POST-1.0")), "post-1.0"),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_violation_fails_with_its_message(name):
    mutate, message = CASES[name]
    problems = plan_check.check(mutate(good()))

    assert any(message in p for p in problems), (name, problems)


@pytest.mark.parametrize("a,b,expected", [
    ("src/a.py", "src/a.py", True),
    ("src/a.py", "src/b.py", False),
    ("src/**", "src/a/b.py", True),
    ("ui/x/**", "ui/y/**", False),
    ("pyproject.toml#tool.a", "pyproject.toml#tool.b", False),
    ("pyproject.toml#tool.a", "pyproject.toml", True),
    ("pyproject.toml#tool.a", "pyproject.toml#tool.a", True),
])
def test_overlap_rules(a, b, expected):
    assert plan_check.overlap(a, b) is expected


def test_an_exclusion_removes_the_overlap():
    text = build([card("DOC-00", wave="0a", owns=("src/**", "!src/legacy/")),
                  card("MEAS-1", wave="0a", owns=("src/legacy/x.py",))],
                 rows=[("0a", "now", "-", ["DOC-00", "MEAS-1"])])

    assert plan_check.check(text) == []


def test_next_lists_open_cards_whose_dependencies_are_done():
    text = build([card("DOC-00", wave="0a", status="DONE abcdef1", owns=("docs/x.md",)),
                  card("MEAS-1", wave="0a", depends="DOC-00", owns=("docs/m.md",)),
                  card("MEAS-2", wave="0a", depends="MEAS-1", owns=("docs/n.md",)),
                  card("MEAS-3", wave="0a", status="IN PROGRESS", owns=("docs/o.md",))],
                 rows=[("0a", "now", "-", ["DOC-00", "MEAS-1", "MEAS-2", "MEAS-3"])])

    assert plan_check.next_cards(text) == ["MEAS-1 (wave 0a)"]


def test_next_waits_for_the_wave_to_open():
    text = build([card("DOC-00", wave="0a", owns=("docs/x.md",)),
                  card("MEAS-1", wave="1", owns=("docs/m.md",))],
                 rows=[("0a", "now", "-", ["DOC-00"]), ("1", "T0.4 merged and wave 0a closed", "T0.5", ["MEAS-1"])])

    assert plan_check.next_cards(text) == ["DOC-00 (wave 0a)"]


def test_the_command_exits_1_and_lists_violations(tmp_path, capsys):
    path = tmp_path / "roadmap.md"
    path.write_text(broken("depends: DOC-00", "depends: DOC-99"))

    assert plan_check.main(["--roadmap", str(path)]) == 1
    assert "DOC-99" in capsys.readouterr().out
    path.write_text(good())
    assert plan_check.main(["--roadmap", str(path)]) == 0
