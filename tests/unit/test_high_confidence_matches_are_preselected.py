"""
A match at or above `auto_propose_above` is PRE-SELECTED for a person to
approve (WIRED-3, decided by the owner 14 Oct).

The key was validated and did nothing: every candidate above
`review_above` landed in one inbox. Now the listing flags the ones at or
above the type's own `auto_propose_above`, and the Identity screen ticks
them for one bulk approval. A person still presses it -- the classic
record-linkage zones (match / possible match / non-match), with the top
zone confirmed rather than applied.

A FLAG, NEVER THE SCORE. The listing deliberately leaves the number out,
because a number invites deference to the matcher.
"""

from types import SimpleNamespace

from api.routes import _preselection

TYPE = {"fields": {"name": {"type": "data"}, "postcode": {"type": "data"}},
        "identity": {"match_on": ["email"],
                     "probabilistic": {"compare": ["name", "postcode"],
                                       "review_above": 0.8, "auto_propose_above": 0.9}}}


def _proposal(score, object_type="Customer"):
    return SimpleNamespace(object_type=object_type, score=score, decision="pending",
                           proposal_id="p1", provenance="")


class _NoDecisions:
    """No past decisions, so nothing is calibrated and the declared
    threshold is the whole rule -- what these tests are about. R57's
    calibrated half is test_match_calibration.py's."""

    def proposals(self, object_type=None, decision=None):
        return []


def _is_high_confidence(schema, proposal):
    return bool(_preselection(schema, _NoDecisions(), proposal, {}).get("high_confidence"))


def test_at_or_above_the_declared_threshold_is_high_confidence():
    schema = {"Customer": TYPE}
    assert _is_high_confidence(schema, _proposal(0.9))
    assert _is_high_confidence(schema, _proposal(0.97))


def test_below_it_is_not():
    assert not _is_high_confidence({"Customer": TYPE}, _proposal(0.89))


def test_the_TYPES_threshold_not_the_default():
    """The deleted `disposition` compared against the default 0.95; a
    type declaring 0.9 must be judged by 0.9."""
    assert _is_high_confidence({"Customer": TYPE}, _proposal(0.92))


def test_a_type_without_inference_never_is():
    assert not _is_high_confidence({"Customer": {"fields": {}}}, _proposal(0.99))


def test_a_malformed_block_is_not_this_listings_failure():
    broken = {"Customer": {**TYPE, "identity": {"probabilistic": {"compare": "name"}}}}
    assert not _is_high_confidence(broken, _proposal(0.99))


def test_the_declared_rule_says_so_and_is_shown_uncalibrated():
    found = _preselection({"Customer": TYPE}, _NoDecisions(), _proposal(0.95), {})

    assert found["preselected_by"] == "declared"
    assert found["calibration"] == {"status": "uncalibrated", "false_merge_rate": 0.05}


def test_a_decided_proposal_is_not_pre_selected():
    """Only a waiting pair can be ticked; the flag on a decided one
    meant nothing and the screen ignored it."""
    decided = SimpleNamespace(**{**vars(_proposal(0.97)), "decision": "approved"})

    assert not _is_high_confidence({"Customer": TYPE}, decided)
