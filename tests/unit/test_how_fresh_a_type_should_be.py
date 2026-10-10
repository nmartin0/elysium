"""How current an object type should be, and whether it is.

DEV_UI.md 16.6's decision, built. The rule every precedent converges
on is that freshness is derived from the DECISION THE DATA FEEDS, not
from what the pipeline can manage -- "a freshness number without a
threshold is trivia".

ANCHORED TO THE CADENCE. The deployment declares ONE number, its
expected sync interval, and every threshold is a multiple of it:
warn at 1.1x (one late run), fail at 2.1x (two consecutive misses).
An operator moving from nightly to hourly changes that number and
every threshold follows.

MEASURED FROM THE PUBLICATION, per type, because that is the clock a
reader experiences: silver records when the source was READ, gold when
a publication was MADE, and a source read hourly but published daily
is a day stale to the person looking at it.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.deployment_loader import load_deployment
from core.mirror.freshness import (
    DEFAULT_SYNC_INTERVAL_HOURS,
    EXEMPT,
    FAILING,
    FRESH,
    NEVER,
    WARNING,
    FreshnessTarget,
    default_target,
    sync_interval,
    targets_for,
    verdict,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _published(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _type(freshness=None):
    declared = {"id_field": "id", "fields": {}}
    if freshness is not None:
        declared["freshness"] = freshness
    return {"Customer": declared}


class TestTheDeploymentsOwnInterval:
    def test_it_defaults_to_nightly(self):
        """INSTALL.md leaves scheduling to the operator and nightly is
        what an unattended on-prem deployment does."""
        assert sync_interval({}) == timedelta(hours=DEFAULT_SYNC_INTERVAL_HOURS)
        assert DEFAULT_SYNC_INTERVAL_HOURS == 24

    def test_a_deployment_may_declare_its_own(self):
        assert sync_interval({"freshness": {"sync_interval_hours": 1}}) == timedelta(hours=1)

    def test_a_commented_out_block_is_not_a_declaration(self):
        """A YAML section whose every line is commented parses as None,
        which this deployment hits often enough to have an idiom for."""
        assert sync_interval({"freshness": None}) == timedelta(hours=24)

    @pytest.mark.parametrize("declared", [0, -1, "nightly", True])
    def test_a_nonsense_interval_is_refused(self, declared):
        """`true` is in the list deliberately: bool is an int in
        Python, so `sync_interval_hours: true` would otherwise mean one
        hour."""
        with pytest.raises(ValueError, match="sync_interval_hours"):
            sync_interval({"freshness": {"sync_interval_hours": declared}})


class TestTheDerivedWindow:
    def test_warn_is_ONE_LATE_RUN_and_fail_is_TWO_MISSES(self):
        """On a nightly deployment that is 26 and 50 hours. A run that
        slips by an hour is not an incident, and a channel that says it
        is becomes one nobody reads; two missed nights is."""
        target = default_target(timedelta(hours=24))

        assert target.warn_after == timedelta(hours=26.4)
        assert target.fail_after == timedelta(hours=50.4)

    def test_it_follows_the_interval_rather_than_being_absolute(self):
        """An operator who moves to hourly changes ONE number."""
        target = default_target(timedelta(hours=1))

        assert target.warn_after == timedelta(hours=1.1)
        assert target.fail_after == timedelta(hours=2.1)

    def test_it_keeps_the_existing_25_hour_judgement_almost_exactly(self):
        """The mirror has judged staleness at 25 hours since it was
        written, chosen to catch "the nightly sync did not run"
        without crying wolf on a weekly table. 26.4 is the same
        judgement, now derived from a declared cadence rather than
        picked."""
        warn = default_target(timedelta(hours=24)).warn_after

        assert timedelta(hours=24) < warn < timedelta(hours=28)

    def test_every_declared_type_gets_one_without_declaring_anything(self):
        targets = targets_for({}, _type())

        assert targets["Customer"] == default_target(timedelta(hours=24))


class TestATypeMayDeclareItsOwn:
    def test_a_tighter_pair_is_allowed_on_a_tighter_deployment(self):
        """Datadog's ratio for a critical table: 6 hours to alert, 4 to
        warn, on something that loads hourly."""
        targets = targets_for(
            {"freshness": {"sync_interval_hours": 1}},
            _type({"warn_after_hours": 4, "fail_after_hours": 6}),
        )

        assert targets["Customer"].warn_after == timedelta(hours=4)
        assert targets["Customer"].fail_after == timedelta(hours=6)

    def test_reference_data_may_declare_itself_exempt(self):
        """A type that genuinely changes quarterly generates nothing
        but false alarms otherwise, and a channel with false alarms in
        it is a channel nobody reads."""
        targets = targets_for({}, _type({"exempt": True}))

        assert targets["Customer"].exempt is True

    def test_one_type_declaring_does_not_change_another(self):
        schema = {
            "Customer": {"freshness": {"exempt": True}},
            "Transaction": {},
        }

        targets = targets_for({}, schema)

        assert targets["Customer"].exempt is True
        assert targets["Transaction"] == default_target(timedelta(hours=24))


class TestWhatIsRefusedAtLoad:
    """This deployment refuses configuration errors at load rather than
    discovering them in production."""

    def test_A_TARGET_TIGHTER_THAN_THE_SYNC_INTERVAL(self):
        """The refusal DEV_UI.md 16.6 point 6 asks for. A type
        declaring two hours on a nightly deployment is not ambitious,
        it is guaranteed to alert forever."""
        with pytest.raises(ValueError) as caught:
            targets_for({}, _type({"warn_after_hours": 2, "fail_after_hours": 6}))

        assert "2 hours" in str(caught.value)
        assert "24 hours" in str(caught.value), "it must name BOTH numbers"

    def test_the_refusal_says_which_two_things_could_fix_it(self):
        with pytest.raises(ValueError) as caught:
            targets_for({}, _type({"warn_after_hours": 2, "fail_after_hours": 6}))

        assert "sync_interval_hours" in str(caught.value)

    def test_FAIL_BEFORE_WARN(self):
        """Warning after failing is a warning nobody sees."""
        with pytest.raises(ValueError, match="later than"):
            targets_for({}, _type({"warn_after_hours": 50, "fail_after_hours": 30}))

    def test_an_equal_pair_is_not_a_window(self):
        with pytest.raises(ValueError, match="later than"):
            targets_for({}, _type({"warn_after_hours": 30, "fail_after_hours": 30}))

    def test_HALF_A_WINDOW(self):
        """One half declared would leave the other at the deployment
        default, so `fail_after_hours: 6` on a nightly deployment would
        silently pair with a warn of 26 -- a window that warns eleven
        hours after it has already failed."""
        with pytest.raises(ValueError, match="only one of"):
            targets_for({}, _type({"fail_after_hours": 30}))

        with pytest.raises(ValueError, match="only one of"):
            targets_for({}, _type({"warn_after_hours": 30}))

    def test_EXEMPT_AND_A_THRESHOLD_TOGETHER(self):
        """A contradiction rather than a precedence question. Somebody
        wrote both because they meant one, and picking for them would
        mean a type is judged, or not, by a rule nobody stated."""
        with pytest.raises(ValueError, match="exempt AND a threshold"):
            targets_for({}, _type({"exempt": True, "warn_after_hours": 30,
                                    "fail_after_hours": 60}))

    def test_A_MISSPELT_KEY(self):
        """Ignored, it would leave a type judged by the deployment
        default while its author believed otherwise, and nothing would
        ever say so."""
        with pytest.raises(ValueError, match="unknown key"):
            targets_for({}, _type({"warn_after_hour": 30, "fail_after_hours": 60}))

    def test_the_unknown_key_refusal_lists_what_is_known(self):
        with pytest.raises(ValueError) as caught:
            targets_for({}, _type({"nonsense": 1}))

        assert "warn_after_hours" in str(caught.value)

    @pytest.mark.parametrize("declared", [True, "soon", None, 0, -4])
    def test_A_NONSENSE_THRESHOLD(self, declared):
        with pytest.raises(ValueError):
            targets_for({}, _type({"warn_after_hours": declared,
                                    "fail_after_hours": 60}))

    def test_a_block_that_is_not_a_block(self):
        with pytest.raises(ValueError, match="block of settings"):
            targets_for({}, _type("24 hours"))

    def test_a_non_boolean_exempt(self):
        with pytest.raises(ValueError, match="true or false"):
            targets_for({}, _type({"exempt": "yes"}))


class TestTheVerdict:
    TARGET = FreshnessTarget(warn_after=timedelta(hours=26),
                              fail_after=timedelta(hours=50))

    def test_recently_published_is_fresh(self):
        assert verdict(_published(1), self.TARGET, NOW) == FRESH

    def test_one_late_run_warns(self):
        assert verdict(_published(30), self.TARGET, NOW) == WARNING

    def test_two_missed_nights_fails(self):
        assert verdict(_published(60), self.TARGET, NOW) == FAILING

    def test_the_boundaries_belong_to_the_worse_state(self):
        """A reader at exactly the threshold should be told, not
        reassured: the window is what the deployment said it would
        tolerate, and the moment it is reached it has been."""
        assert verdict(_published(26), self.TARGET, NOW) == WARNING
        assert verdict(_published(50), self.TARGET, NOW) == FAILING

    def test_NEVER_PUBLISHED_IS_NOT_STALE(self):
        """A type with no publication is one whose reads fail
        outright -- the server says so at startup and raises on read.
        Calling that "very stale" would put it on a scale it is not
        on."""
        assert verdict(None, self.TARGET, NOW) == NEVER
        assert verdict("", self.TARGET, NOW) == NEVER

    def test_an_unreadable_timestamp_is_not_guessed_at(self):
        """A fact about the record rather than about the data's age."""
        assert verdict("not a timestamp", self.TARGET, NOW) == NEVER

    def test_an_exempt_type_is_never_judged(self):
        exempt = FreshnessTarget(warn_after=timedelta(hours=1),
                                  fail_after=timedelta(hours=2), exempt=True)

        assert verdict(_published(1000), exempt, NOW) == EXEMPT
        assert verdict(None, exempt, NOW) == EXEMPT

    def test_a_naive_timestamp_is_read_as_UTC(self):
        """Rather than raising. Every timestamp this project writes
        carries an offset; one that does not came from somewhere older,
        and refusing to read it would turn a stale type into an
        unreadable one."""
        naive = (NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()

        assert verdict(naive, self.TARGET, NOW) == FRESH


class TestTheShippedDeployment:
    def test_it_still_loads_without_declaring_anything(self):
        """NOTHING SHIPPED DECLARES A FRESHNESS BLOCK, which is what
        makes the load-time refusal safe to add: it can only fire on a
        declaration somebody has just written."""
        config = load_deployment(Path("deployment/etc"))

        assert config.freshness_targets

    def test_every_declared_type_has_a_target(self):
        config = load_deployment(Path("deployment/etc"))

        assert set(config.freshness_targets) == set(config.schema)

    def test_they_are_the_nightly_defaults(self):
        config = load_deployment(Path("deployment/etc"))

        for target in config.freshness_targets.values():
            assert target == default_target(timedelta(hours=24))

    def test_a_BAD_declaration_stops_the_deployment_starting(self, tmp_path):
        """Wired into the load, not merely available to it."""
        import shutil

        import yaml

        etc = tmp_path / "etc"
        shutil.copytree("deployment/etc", etc)
        schema_path = etc / "ontology_schema.yaml"
        schema = yaml.safe_load(schema_path.read_text())
        schema["object_types"]["Customer"]["freshness"] = {
            "warn_after_hours": 2, "fail_after_hours": 6,
        }
        schema_path.write_text(yaml.safe_dump(schema))

        with pytest.raises(ValueError, match="tighter than the sync interval"):
            load_deployment(etc)
