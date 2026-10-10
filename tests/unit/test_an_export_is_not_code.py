"""A CSV handed to a spreadsheet is code unless something stops it.

THE PROJECT'S OWN AUDIT ASKED FOR THIS FILE. `AUDIT_CHECKLIST.csv`
R35, "export-time formula escaping": "NOT APPLICABLE YET, verified:
there is no CSV or spreadsheet export anywhere in api/ or ui/.
Nothing produces a file a formula could execute in. Becomes live the
moment an export is built, and should be built WITH the escaping
rather than after."

THE ATTACK. A cell beginning `=`, `+`, `-` or `@` is a FORMULA to
Excel, LibreOffice and Google Sheets. `=cmd|' /c calc'!A1` typed into
a customer's name field becomes a command the moment somebody exports
the set and opens the file -- on THEIR machine, with THEIR
privileges, from data a stranger supplied. The export is the delivery
mechanism; the escaping is the only part of that chain this project
owns.

OWASP'S GUIDANCE, FOLLOWED RATHER THAN INVENTED
(https://owasp.org/www-community/attacks/CSV_Injection), including
its caveat that quoting ALONE "is not reliable in Microsoft Excel
after saving and re-opening the CSV file" -- which is why the prefix
is the mechanism and the quoting is only for the comma.
"""

import csv
import io

import pytest

from core.export import RISKY_PREFIXES, escape_cell, filename_for, to_csv


def _parsed(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


class TestACellCannotBecomeAFormula:
    @pytest.mark.parametrize("payload", [
        "=cmd|' /c calc'!A1",
        "=1+1",
        "+1+1",
        "-1+1",
        "@SUM(1:2)",
        "=HYPERLINK(\"http://evil\",\"click\")",
    ])
    def test_every_formula_opener_is_defused(self, payload):
        assert escape_cell(payload).startswith("'")

    @pytest.mark.parametrize("payload", ["\t=1+1", "\r=1+1", "\n=1+1"])
    def test_WHITESPACE_DISGUISES_TOO(self, payload):
        """NOT DECORATION. A leading tab or carriage return is stripped
        by the spreadsheet BEFORE it decides what the cell is, so
        "\\t=cmd" is a formula wearing a hat -- and exactly the shape a
        filter looking only for "=" waves through."""
        assert escape_cell(payload).startswith("'")

    @pytest.mark.parametrize("payload", ["＝1+1", "＋1+1"])
    def test_the_FULL_WIDTH_variants_too(self, payload):
        """U+FF1D and U+FF0B, which some locales' spreadsheet software
        normalises to their ASCII forms. A rule that cannot see them is
        one an attacker picks on purpose. OWASP names them."""
        assert escape_cell(payload).startswith("'")

    def test_the_list_matches_what_OWASP_names(self):
        for character in ("=", "+", "-", "@", "\t", "\r"):
            assert character in RISKY_PREFIXES


class TestOrdinaryTextIsLeftAlone:
    """An escaping rule that mangles normal data is one somebody turns
    off, and then none of the above matters."""

    @pytest.mark.parametrize("value", [
        "Ada Okafor",
        "ada@example.com",
        "A=B",
        "2026-01-15",
        "us-west",
        "",
    ])
    def test_it_is_returned_unchanged(self, value):
        assert escape_cell(value) == value

    def test_ONLY_THE_LEADING_CHARACTER_MATTERS(self):
        """`A=B` is not a formula; `=A1` is. Escaping every occurrence
        would break email addresses and hyphenated names for no gain."""
        assert escape_cell("A=B") == "A=B"
        assert escape_cell("ada@example.com") == "ada@example.com"

    def test_a_missing_value_is_empty_not_the_word_None(self):
        """A missing value and the string "None" are different facts,
        and a CSV has exactly one way to say the first."""
        assert escape_cell(None) == ""

    def test_a_number_survives_as_a_number(self):
        assert escape_cell(49.99) == "49.99"
        assert escape_cell(7) == "7"

    def test_A_NEGATIVE_NUMBER_IS_STILL_A_NUMBER(self):
        """A leading minus is on OWASP's list because of
        `-2+3+cmd|' /c calc'!A1`, not because of `-20`.

        PREFIXING EVERY NEGATIVE WOULD BE SAFE AND USELESS. Excel reads
        `'-20` as TEXT, so a SUM over an amount column silently skips
        every refund -- and a financial export whose totals are wrong
        is worse than no export, because it looks right.

        SEEN ON THE DEV DEPLOYMENT the first time this ran end to end:
        a refund of -20 exported as `'-20.000000000`."""
        assert escape_cell(-20) == "-20"
        assert escape_cell("-20.000000000") == "-20.000000000"
        assert escape_cell("+20") == "+20"
        assert escape_cell("-1.5e-3") == "-1.5e-3"

    def test_BUT_ARITHMETIC_IS_NOT_A_NUMBER(self):
        """`-2+3` is where a payload hides behind a minus sign. The
        rule has to let `-20` through and stop this."""
        assert escape_cell("-2+3") == "'-2+3"
        assert escape_cell("-2+3+cmd|' /c calc'!A1").startswith("'")

    def test_a_spelling_PYTHON_accepts_and_a_spreadsheet_does_not(self):
        """`float("-1_0")` is -10.0 in Python and `-1_0` is text in
        Excel, which is why this asks a regex rather than float()."""
        assert escape_cell("-1_0") == "'-1_0"


class TestTheFileItself:
    COLUMNS = ["customer_id", "name", "email"]
    ROWS = [
        {"customer_id": "cust_001", "name": "Ada Okafor", "email": "ada@example.com"},
        {"customer_id": "cust_002", "name": "=cmd|' /c calc'!A1", "email": None},
    ]

    def test_the_header_comes_first(self):
        assert _parsed(to_csv(self.COLUMNS, self.ROWS))[0] == self.COLUMNS

    def test_every_row_is_written(self):
        assert len(_parsed(to_csv(self.COLUMNS, self.ROWS))) == 3

    def test_the_columns_are_in_the_order_asked_for(self):
        assert _parsed(to_csv(["email", "name"], self.ROWS))[0] == ["email", "name"]

    def test_a_payload_in_a_row_is_defused_in_the_file(self):
        text = to_csv(self.COLUMNS, self.ROWS)

        assert "\"'=cmd" in text
        assert '"=cmd' not in text

    def test_a_missing_field_is_an_empty_cell_not_a_crash(self):
        text = to_csv(["customer_id", "nothing_here"], self.ROWS)

        assert _parsed(text)[1] == ["cust_001", ""]

    def test_a_comma_in_a_value_does_not_become_a_column(self):
        text = to_csv(["name"], [{"name": "Okafor, Ada"}])

        assert _parsed(text)[1] == ["Okafor, Ada"]

    def test_a_quote_in_a_value_survives(self):
        text = to_csv(["name"], [{"name": 'Ada "Okafor"'}])

        assert _parsed(text)[1] == ['Ada "Okafor"']

    def test_a_newline_in_a_value_does_not_become_a_row(self):
        text = to_csv(["note"], [{"note": "line one\nline two"}])

        assert len(_parsed(text)) == 2

    def test_it_ends_lines_the_way_RFC_4180_says(self):
        """CRLF, which Excel expects."""
        assert to_csv(["a"], [{"a": "b"}]).endswith("\r\n")

    def test_A_COLUMN_NAME_CANNOT_BE_A_FORMULA_EITHER(self):
        """Column names come from a deployment's own ontology, which is
        configuration rather than a stranger's input -- but a field
        named `-rate` would still be a formula, and a rule with an
        exception is a rule somebody has to remember."""
        assert "\"'-rate\"" in to_csv(["-rate"], [])

    def test_an_empty_set_is_a_header_and_nothing_else(self):
        """Not an empty file. Somebody who exports a set that matches
        nothing should get a file that says which columns matched
        nothing, rather than one they cannot open."""
        assert _parsed(to_csv(["a", "b"], [])) == [["a", "b"]]


class TestTheFilename:
    def test_it_names_the_type_and_the_instant(self):
        """A live set's membership is only true as of when it was
        taken, and somebody exporting twice in a morning has to be able
        to tell the two apart."""
        assert filename_for("Customer", "20261010-120000") == "Customer-20261010-120000.csv"

    def test_NOTHING_REACHES_THE_HEADER_THAT_COULD_SPLIT_IT(self):
        """This string ends up in Content-Disposition, where a quote or
        a newline is header injection. An object type comes from the
        deployment's own configuration today, which is an argument for
        this being cheap rather than for skipping it."""
        name = filename_for('Customer"\r\nSet-Cookie: x=1', "2026")

        assert '"' not in name
        assert "\r" not in name and "\n" not in name

    def test_a_type_of_nothing_still_gets_a_name(self):
        assert filename_for("", "2026").startswith("objects-")
