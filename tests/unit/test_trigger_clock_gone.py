"""The trigger clock's settings are refused, not ignored (16 October).

Two names in two days -- every trigger, then date-filtered ones, every
fifteen minutes -- both replaced by timers at the exact crossing. A key
left in config.yaml would read as governing something."""

import pytest

from core.deployment_loader import _no_trigger_clock


@pytest.mark.parametrize("key", ["check_triggers_every_minutes", "check_date_triggers_every_minutes"])
def test_either_old_name_stops_the_deployment_starting(key):
    with pytest.raises(ValueError, match=f"{key} no longer exists"):
        _no_trigger_clock({key: 15})


def test_a_config_without_them_is_untouched():
    _no_trigger_clock({"bulk_action_limit": 10})


def test_loading_a_deployment_refuses_it(tmp_path):
    """Wired into the loader, not only callable."""
    import shutil
    from pathlib import Path

    from core.deployment_loader import load_deployment

    fixtures = Path(__file__).parent.parent / "integration" / "fixtures"
    for name in ("config.yaml", "data_silos.yaml", "ontology_schema.yaml", "policy.yaml"):
        shutil.copy(fixtures / name, tmp_path / name)
    with open(tmp_path / "config.yaml", "a") as config:
        config.write("\ncheck_date_triggers_every_minutes: 15\n")

    with pytest.raises(ValueError, match="no longer exists"):
        load_deployment(tmp_path)
