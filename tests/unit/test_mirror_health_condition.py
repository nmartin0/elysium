"""
The mirror's own health, as a condition somebody is told about.

WHY THIS CONDITION FIRST. The facts were already recorded and nothing
watched them. `sync_attempts` knows every refusal; the admin panel
shows staleness to whoever happens to open it. An administrator who
does not open it learns nothing -- which is the wrong way round for
the one thing that makes every read stale.

AND IT ADMITS NO ACTION EFFECT, which is the real reason it goes
first. You cannot auto-fix a refused sync. So it exercises the whole
path -- condition, effect, recipient -- needing neither the approvals
queue nor saved views server-side.
"""

from datetime import UTC, datetime, timedelta

import pytest

from core.mirror.health_condition import (
    RECIPIENT_GRANT,
    STALE_AFTER,
    notify_mirror_health,
    summarise_mirror_health,
)


@pytest.fixture
def store(tmp_path):
    from core.notifications import NotificationStore

    return NotificationStore(tmp_path / "n.db")


NOW = datetime.now(UTC)
FRESH = (NOW - timedelta(hours=1)).isoformat()
OLD = (NOW - timedelta(hours=40)).isoformat()


def _state(**overrides):
    return {
        "silo": "s", "table": "t",
        "last_synced_at": FRESH,
        "last_attempt_outcome": "synced",
        **overrides,
    }


class TestWhatCountsAsUnhealthy:
    def test_a_healthy_mirror_says_nothing(self):
        assert summarise_mirror_health([_state()], NOW) is None

    def test_a_refused_sync_is_reported(self):
        summary = summarise_mirror_health(
            [_state(last_attempt_outcome="refused")], NOW)

        assert "refused" in summary

    def test_a_stale_table_is_reported(self):
        summary = summarise_mirror_health([_state(last_synced_at=OLD)], NOW)

        assert "have not changed" in summary

    def test_a_never_synced_table_is_not_stale(self):
        """A TABLE WITH NO SNAPSHOT is a deployment that has not synced
        yet, which the panel already says plainly. Calling a fresh
        install "stale" would describe it as a fault."""
        assert summarise_mirror_health(
            [_state(last_synced_at=None, last_attempt_outcome=None)], NOW,
        ) is None

    def test_one_line_for_the_whole_mirror(self):
        """FIVE STALE TABLES ARE USUALLY ONE STUCK SYNC, and five
        notices about it teach less than one."""
        states = [
            _state(table=f"t{n}", last_synced_at=OLD) for n in range(5)
        ]

        summary = summarise_mirror_health(states, NOW)

        assert summary.count("have not changed") == 1


class TestWhoIsTold:
    def test_every_recipient_gets_one(self, store):
        told = notify_mirror_health(
            [_state(last_attempt_outcome="refused")], ["root", "ops"], store,
            NOW,
        )

        assert told == 2

    def test_a_healthy_mirror_tells_nobody(self, store):
        assert notify_mirror_health([_state()], ["root"], store, NOW) == 0

    def test_the_recipient_grant_is_the_one_that_can_fix_it(self):
        """IF YOU CAN FIX IT, YOU SHOULD HEAR THAT IT NEEDS FIXING.
        The same grant that can start a sync."""
        assert RECIPIENT_GRANT == "manage:deployment"


class TestRepeatsAreSuppressed:
    def test_the_same_problem_is_not_repeated(self, store):
        """A STANDING CONDITION IS TRUE UNTIL SOMEBODY FIXES IT. A sync
        failing for a week is still failing on the hundredth check, and
        a notification per check is a channel nobody reads by the time
        it matters."""
        states = [_state(last_attempt_outcome="refused")]
        notify_mirror_health(states, ["root"], store, NOW)

        assert notify_mirror_health(states, ["root"], store, NOW) == 0

    def test_a_worsening_problem_is_news(self, store):
        """"3 TABLES STALE" BECOMING "5 TABLES STALE" is news; the same
        text is not. The suppression compares the SUMMARY, not just
        the condition."""
        one = [_state(table="a", last_attempt_outcome="refused")]
        notify_mirror_health(one, ["root"], store, NOW)

        two = one + [_state(table="b", last_attempt_outcome="refused")]

        assert notify_mirror_health(two, ["root"], store, NOW) == 1

    def test_suppression_is_per_recipient(self, store):
        """THE SAME CONDITION MAY BE NEW TO ONE PERSON AND OLD TO
        ANOTHER -- somebody granted manage:deployment today has not
        heard it yet."""
        states = [_state(last_attempt_outcome="refused")]
        notify_mirror_health(states, ["root"], store, NOW)

        assert notify_mirror_health(states, ["root", "newcomer"], store, NOW) == 1


class TestTheThreshold:
    def test_it_is_loose_enough_for_a_daily_sync(self):
        """A TABLE THAT SYNCS NIGHTLY AND RAN LATE is not broken. A
        threshold tight enough to catch a stuck hourly sync would cry
        wolf on a daily one."""
        assert STALE_AFTER > timedelta(hours=24)

    def test_and_tight_enough_to_notice_a_missed_night(self):
        assert STALE_AFTER < timedelta(days=2)
