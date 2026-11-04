"""card_packet prints the brief, the card's workstream, the card and its contracts."""

from pathlib import Path

import card_packet
import pytest

ROOT = Path(__file__).resolve().parents[2]
ROADMAP = """# Elysium roadmap

## 1. Start here

### 1.1 The worker brief
BRIEF TEXT

### 1.2 The card header
HEADER FORMAT

### 1.3 Working in parallel
PARALLEL TEXT

### 1.4 Conventions
CONVENTIONS TEXT

## 3. Contracts

<a id="c-one"></a>

### C-ONE · First
ONE BODY

<a id="c-two"></a>

### C-TWO · Second
TWO BODY

## 4. Tier 0

### T0.5 An item

```card
id: T0.5
wave: T0
status: OPEN
size: L
model: Sonnet
depends: -
contracts: C-TWO
owns:
  - x
```
- **Spec.**
  1. **First.** first text
     more first
  2. **Second.** (a) a (b) b
  3. **Third.** third text

### T0.6 Next item

## 5. Task cards

### 5.1 Workstreams

| Workstream | Section | Cards |
|---|---|---|
| ADM: admin | 5.2 | 2 |

### 5.2 ADM: admin in the UI
ADM INTRO

#### ADM-01 · One

```card
id: ADM-01
wave: 1
status: OPEN
size: S
model: Sonnet
depends: -
contracts: C-ONE
owns:
  - y
```
ADM-01 BODY

#### ADM-02 · Two

ADM-02 BODY
"""


def test_a_card_gets_the_brief_the_workstream_the_card_and_its_contracts_in_order():
    out = card_packet.packet(ROADMAP, "ADM-01")

    order = [out.index(w) for w in ("BRIEF TEXT", "PARALLEL TEXT", "CONVENTIONS TEXT", "ADM INTRO",
                                    "ADM-01 BODY", "ONE BODY")]
    assert order == sorted(order)
    assert "HEADER FORMAT" not in out
    assert "ADM-02 BODY" not in out
    assert "TWO BODY" not in out
    assert "ADM-01 BODY" in out and "ADM-01 BODY\n\n" not in out.split("ONE BODY")[0][-30:]


def test_a_tier_zero_step_is_marked():
    out = card_packet.packet(ROADMAP, "T0.5", "2")

    marked = [line for line in out.splitlines() if line.startswith(">>>")]
    assert any("Second" in line for line in marked)
    assert not any("First" in line or "Third" in line for line in marked)
    assert "TWO BODY" in out and "ADM INTRO" not in out
    assert "Next item" not in out


def test_a_lettered_step_marks_the_numbered_step_that_holds_it():
    out = card_packet.packet(ROADMAP, "T0.5", "2b")

    assert any("Second" in line for line in out.splitlines() if line.startswith(">>>"))


@pytest.mark.parametrize("args", [["NOPE-1"], ["T0.5", "9"], ["ADM-01", "1"]])
def test_unknown_things_exit_1(args, tmp_path, capsys):
    path = tmp_path / "r.md"
    path.write_text(ROADMAP)

    assert card_packet.main([*args, "--roadmap", str(path)]) == 1
    assert "card_packet:" in capsys.readouterr().err


def test_every_card_of_the_real_roadmap_has_a_packet():
    import plan_check

    text = (ROOT / "docs/roadmap.md").read_text()
    for cid in plan_check.Plan(text).headers:
        out = card_packet.packet(text, cid)
        assert f"id: {cid}\n" in out, cid
        assert "The worker brief" in out, cid
