"""check_date_triggers_every_minutes in config.yaml (revised 16
October): minutes between the server's checks of date-filtered
triggers, 0 for none."""

import pytest

from core.deployment_loader import DEFAULT_TRIGGER_CLOCK_MINUTES, _trigger_clock


def test_absent_is_a_quarter_hour():
    assert _trigger_clock({}) == DEFAULT_TRIGGER_CLOCK_MINUTES == 15


@pytest.mark.parametrize("minutes", [0, 1, 60, 1440])
def test_zero_to_a_day(minutes):
    assert _trigger_clock({"check_date_triggers_every_minutes": minutes}) == minutes


@pytest.mark.parametrize("declared", [-1, 1441, 1.5, "15", True])
def test_anything_else_stops_the_deployment_starting(declared):
    with pytest.raises(ValueError, match="check_date_triggers_every_minutes"):
        _trigger_clock({"check_date_triggers_every_minutes": declared})


def test_the_old_name_is_refused_with_the_new_one():
    """It checked every trigger; the setting now governs only date-
    filtered ones. Honouring the old key would change what it means
    without anybody being told."""
    with pytest.raises(ValueError, match="now check_date_triggers_every_minutes"):
        _trigger_clock({"check_triggers_every_minutes": 15})
