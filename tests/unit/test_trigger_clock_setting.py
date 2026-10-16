"""check_triggers_every_minutes in config.yaml (decided 16 October):
minutes between the server's trigger checks, 0 for after syncs only."""

import pytest

from core.deployment_loader import DEFAULT_TRIGGER_CLOCK_MINUTES, _trigger_clock


def test_absent_is_a_quarter_hour():
    assert _trigger_clock(None) == DEFAULT_TRIGGER_CLOCK_MINUTES == 15


@pytest.mark.parametrize("minutes", [0, 1, 60, 1440])
def test_zero_to_a_day(minutes):
    assert _trigger_clock(minutes) == minutes


@pytest.mark.parametrize("declared", [-1, 1441, 1.5, "15", True])
def test_anything_else_stops_the_deployment_starting(declared):
    with pytest.raises(ValueError, match="check_triggers_every_minutes"):
        _trigger_clock(declared)
