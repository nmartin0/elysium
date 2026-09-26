"""
The report that tells you what to declare (ZOO-08, ZOO-09, ZOO-10,
ZOO-23; PR001-R25).

FOUR OF BATCH D TURNED OUT TO BE ALREADY DECLARABLE, and finding that
out is most of this patch:

    "N/A" kept as a real value       -> standardise: null_if
    "999-999-9999" kept              -> standardise: null_if
    1900-01-01 parsed as a real date -> standardise: null_if
    2099-01-01 accepted, no range    -> constraints: min/max

Nothing was missing from the mechanism. What was missing is that
NOBODY DECLARES `null_if: ["N/A"]` FOR A VALUE THEY DO NOT KNOW IS
THERE. A rule you must already suspect is a rule for the person who
does not need it.

SUGGEST, NEVER INFER. The report reads BRONZE -- the raw copy, before
declared cleaning -- counts values that announce themselves as
disguised absences or implausible dates, and prints the exact YAML.
It writes nothing. The 2024 VLDB evaluation of twelve automatic
repair algorithms found most introduce more errors than they remove,
which is the argument for stopping at a suggestion.

BRONZE AND NOT SILVER, deliberately: silver has already had the
declared rules applied, so a value a deployment ALREADY handles would
be reported again and the operator would chase something they had
fixed.

WHAT IT CANNOT DO, stated in its own output: it finds values that
ANNOUNCE themselves, not wrong ones. A misspelled city and a
transposed figure look exactly like data.
"""

import pytest

from scripts.suggest_declarations import (
    ABSENCE,
    RANGE,
    _looks_absent,
    _suggestion,
    suspicious_values,
)


class TestWhatAnnouncesItself:
    @pytest.mark.parametrize("value", [
        "N/A", "n/a", "NA", "none", "NULL", "unknown", "not applicable",
        "TBD", "-", "?", "missing",
    ])
    def test_a_word_meaning_no_value(self, value):
        verdict = _looks_absent(value)

        assert verdict is not None
        assert verdict[0] == ABSENCE

    @pytest.mark.parametrize("value", [
        "999-999-9999", "(999) 999-9999", "test@example.com", "xxxx", "000",
    ])
    def test_a_placeholder(self, value):
        assert _looks_absent(value)[0] == ABSENCE

    @pytest.mark.parametrize("value", [
        "1900-01-01", "1899-12-30", "1970-01-01", "9999-12-31",
    ])
    def test_a_sentinel_date_is_an_ABSENCE_not_a_range(self, value):
        """The value is exact and meaningless, so `null_if` names it
        directly rather than a range catching it by accident."""
        assert _looks_absent(value)[0] == ABSENCE

    @pytest.mark.parametrize("value,kind", [
        ("1850-06-01", RANGE), ("2150-01-01", RANGE),
    ])
    def test_an_implausible_date_is_a_RANGE(self, value, kind):
        assert _looks_absent(value)[0] == kind


class TestWhatItLeavesAlone:
    @pytest.mark.parametrize("value", [
        "Ada Lovelace", "N/A-1 connector", "none of the above",
        "2024-06-01", "0.00", "nothing to report", "",
    ])
    def test_ordinary_values(self, value):
        """A whole-value match, not a substring one: 'N/A-1 connector'
        is a part number and 'none of the above' is an answer."""
        assert _looks_absent(value) is None

    def test_a_number_that_happens_to_be_zero(self):
        """`0` is a real quantity. `000` is a filled-in box."""
        assert _looks_absent("0") is None


class TestTheSuggestion:
    def test_absences_become_null_if(self):
        values = {"N/A": (3, ABSENCE, "a word meaning 'no value'")}

        yaml = _suggestion("email", values)

        assert "null_if" in yaml
        assert '"N/A"' in yaml

    def test_out_of_range_dates_become_a_constraint(self):
        values = {"2150-01-01": (1, RANGE, "a date in 2150")}

        yaml = _suggestion("when", values)

        assert "constraints" in yaml
        assert "on_violation: quarantine" in yaml

    def test_a_column_with_both_gets_both(self):
        values = {"1900-01-01": (1, ABSENCE, "sentinel"),
                   "2150-01-01": (1, RANGE, "a date in 2150")}

        yaml = _suggestion("when", values)

        assert "null_if" in yaml and "constraints" in yaml

    def test_the_kind_is_named_not_guessed_from_the_wording(self):
        """An earlier version decided which YAML to print by looking
        for the word 'date' in the explanation, so rephrasing a
        sentence would have silently changed the advice."""
        values = {"x": (1, ABSENCE, "a date-like thing that is an absence")}

        yaml = _suggestion("c", values)

        assert "null_if" in yaml
        assert "constraints" not in yaml


class TestScanningRows:
    def test_it_counts_per_column(self):
        rows = [{"a": "N/A", "b": "fine"}, {"a": "N/A", "b": "also fine"},
                {"a": "real", "b": "N/A"}]

        found = suspicious_values(rows, ["a", "b"])

        assert found["a"]["N/A"][0] == 2
        assert found["b"]["N/A"][0] == 1

    def test_a_clean_table_reports_nothing(self):
        rows = [{"a": "Ada"}, {"a": "Bram"}]

        assert suspicious_values(rows, ["a"]) == {}

    def test_non_text_values_are_skipped(self):
        """A number cannot be a disguised word, and examining it would
        only risk a false positive."""
        rows = [{"a": 0}, {"a": None}, {"a": 42}]

        assert suspicious_values(rows, ["a"]) == {}
