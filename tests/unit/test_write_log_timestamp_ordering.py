"""`superseded()`'s string comparison orders write_log entries
correctly (SEC-29).

`created_at` is written with a plain `datetime.now(UTC).isoformat()`,
which OMITS microseconds when they happen to be zero. `superseded()`
then compares those strings with SQL `>`. So a whole second and a
fraction of the same second are compared as:

    2026-01-01T10:00:00+00:00      vs   2026-01-01T10:00:00.500000+00:00

That orders correctly only because "+" is 0x2B and "." is 0x2E, so the
whole second sorts first. It is a coincidence of the offset format,
not a property anyone chose.

NORMALISE THE OFFSET TO "Z" AND IT SILENTLY INVERTS. "Z" is 0x5A,
above ".", so `...:00Z` would sort AFTER `...:00.5Z`. A resumed delete
would then supersede an operation that actually came first, and
deletes would start losing races with earlier writes. Nothing would
fail loudly -- which is why this file exists.

`core/pending_write_store.py`'s `_stamp()` pins
`timespec="microseconds"` for exactly this reason and says so. This
store relies on the coincidence instead. Changing the stored format is
a migration, so the dependency is documented at `superseded()` and
pinned here rather than altered.
"""

from datetime import UTC, datetime, timedelta

import pytest


def _written_the_way_the_write_log_writes_it(moment: datetime) -> str:
    """Exactly what log_pending_update and friends store."""
    return moment.isoformat()


class TestLexicalOrderMatchesTimeOrder:
    def test_a_whole_second_sorts_before_its_own_fractions(self):
        """The case that only works because of the offset character."""
        whole = _written_the_way_the_write_log_writes_it(
            datetime(2026, 1, 1, 10, 0, 0, 0, tzinfo=UTC))
        fraction = _written_the_way_the_write_log_writes_it(
            datetime(2026, 1, 1, 10, 0, 0, 500_000, tzinfo=UTC))

        assert whole < fraction
        assert "+00:00" in whole, "the offset format this ordering depends on has changed"

    def test_the_separator_really_is_what_makes_it_work(self):
        """Pinned explicitly, so the reason is visible and not folded
        into the case above. If a future formatter emits 'Z', this is
        the assertion that says why the ordering broke."""
        assert ord("+") < ord("."), "the whole premise of the comparison"
        assert ord("Z") > ord("."), "which is why 'Z' would invert it"

    @pytest.mark.parametrize("microseconds", [0, 1, 500_000, 999_999])
    def test_later_always_sorts_later_across_precisions(self, microseconds):
        earlier = datetime(2026, 1, 1, 10, 0, 0, microseconds, tzinfo=UTC)
        later = earlier + timedelta(seconds=1)

        assert (_written_the_way_the_write_log_writes_it(earlier)
                < _written_the_way_the_write_log_writes_it(later))

    def test_across_a_minute_and_an_hour_boundary(self):
        moments = [
            datetime(2026, 1, 1, 9, 59, 59, 999_999, tzinfo=UTC),
            datetime(2026, 1, 1, 10, 0, 0, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 10, 0, 0, 1, tzinfo=UTC),
            datetime(2026, 1, 1, 10, 0, 1, 0, tzinfo=UTC),
        ]
        written = [_written_the_way_the_write_log_writes_it(m) for m in moments]

        assert written == sorted(written)

    def test_a_zulu_formatter_would_break_it(self):
        """THE CONTROL, as a test. This is the change that would
        silently invert same-second ordering, and it is written down so
        the next person proposing it sees the consequence."""
        whole = "2026-01-01T10:00:00Z"
        fraction = "2026-01-01T10:00:00.500000Z"

        assert not (whole < fraction), (
            "if this starts passing, a Z-formatted timestamp now orders correctly "
            "and superseded()'s comment can be simplified"
        )
