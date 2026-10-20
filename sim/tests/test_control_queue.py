"""The control queue, without a world (simulator/control.py)."""

import pytest
from simulator import control
from simulator.control import ControlError, Controller


def test_a_command_the_caller_gave_up_on_is_not_carried_out(monkeypatch):
    # Found in review: a timed-out command stayed queued and ran later,
    # after the operator had been told it failed -- so a retry did it
    # twice (two renames, or a clock moved twice as far).
    monkeypatch.setattr(control, "REPLY_TIMEOUT_SECONDS", 0.05)
    controller = Controller(world=None)
    carried_out = []
    monkeypatch.setattr(controller, "_do", lambda *a: carried_out.append(a))

    with pytest.raises(ControlError, match="nothing was done"):
        controller.submit("advance", {"duration": "3d"})
    controller.serve()

    assert carried_out == []
