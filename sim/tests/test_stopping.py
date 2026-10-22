"""Stopping a running world from outside it, tidily (22 October).

A world the control panel starts runs on its own, with no terminal to
press Ctrl-C in, so it must stop tidily two other ways: SIGTERM, which is
how systemd, a container runtime or Elysium's supervisor stops a process,
and the control channel's `stop`. Either way the run's own teardown runs
-- outages restored, the clock saved, every database server stopped --
rather than the process dying with its PostgreSQL still holding a port.
"""

import os
import signal
from concurrent.futures import Future

import pytest
from simulator import cli
from simulator.control import ControlError, Controller


def test_sigterm_ends_the_run_through_its_teardown_as_ctrl_c_does():
    with pytest.raises(cli._Interrupted):
        with cli._interruptible():
            os.kill(os.getpid(), signal.SIGTERM)
            # A signal handler runs between bytecodes; give it one.
            for _ in range(1000):
                pass


def test_sigterm_is_left_as_it_was_after_the_run():
    before = signal.getsignal(signal.SIGTERM)
    with cli._interruptible():
        pass
    assert signal.getsignal(signal.SIGTERM) is before


class _World:
    class clock:  # noqa: N801 -- a stand-in for the world's clock
        @staticmethod
        def now():
            from datetime import datetime

            return datetime(2026, 10, 22)


def test_stop_ends_the_loop_after_its_reply_is_given():
    controller = Controller(_World())
    reply: Future = Future()
    controller._queue.put(("stop", {}, reply))

    with pytest.raises(cli._Interrupted):
        cli._serve(controller)

    # ANSWERED FIRST: the operator is told it is stopping, then it stops.
    assert reply.result(timeout=1)["stopping"] is True


def test_speed_changes_a_following_world_and_refuses_one_that_is_not():
    controller = Controller(_World())
    with pytest.raises(ControlError, match="not following the clock"):
        controller._do("speed", {"compression": 60})

    controller.compression = 60.0
    assert controller._do("speed", {"compression": "120"}) == {"compression": 120.0}
    assert controller.compression == 120.0
    for bad in (0, -1, "fast", 2_000_000):
        with pytest.raises(ControlError):
            controller._do("speed", {"compression": bad})
