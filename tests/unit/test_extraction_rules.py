"""Rules that take a value out of free text: the shapes, the distance
rule, typing through the sync's own converter (17 October)."""

import datetime
import time
from decimal import Decimal

import pytest

from core.ontology.extraction_rules import describe, same_value, take, tokens, typed


def _rule(after, take_shape, within=2, **extra):
    return {"field": "body", "after": after, "within": within, "take": take_shape, **extra}


class TestShapes:
    @pytest.mark.parametrize("text, shape, expected", [
        ("Your order number: INV-2024-0012, thanks", "code", "INV-2024-0012"),
        ("order number A1234.", "code", "A1234"),
        ("order number 4412", "code", "4412"),
        ("refund of 1,234.50 please", "number", "1,234.50"),
        ("refund of -12 please", "number", "-12"),
        ("arrived on 2026-03-12 at noon", "date", "2026-03-12"),
        ("arrived on 12/03/2026 at noon", "date", "12/03/2026"),
        ("colour: Teal, size large", "word", "Teal"),
    ])
    def test_each_shape_takes_its_kind_of_value_as_written(self, text, shape, expected):
        after = {"code": ["order number"], "number": ["refund of"], "date": ["arrived on"],
                 "word": ["colour"]}[shape]
        assert take(_rule(after, shape), text) == expected

    @pytest.mark.parametrize("text, shape", [
        ("order number pending", "code"),       # a code has a digit
        ("refund of some money", "number"),
        ("arrived on 12/03/26", "date"),        # a two-digit year is not a date
        ("colour: 42", "word"),
    ])
    def test_a_value_of_another_shape_is_not_taken(self, text, shape):
        after = {"code": ["order number"], "number": ["refund of"], "date": ["arrived on"],
                 "word": ["colour"]}[shape]
        assert take(_rule(after, shape), text) is None

    def test_words_stop_at_punctuation_and_at_max_words(self):
        rule = _rule(["product"], "words", within=1, max_words=3)
        assert take(rule, "About the product Acme Router X2, which broke") == "Acme Router X2"
        assert take(rule, "product Acme Router X2 Pro Max broke") == "Acme Router X2"
        assert take(rule, "product Acme. Then") == "Acme"


class TestWhereTheValueIs:
    def test_punctuation_between_is_skipped_and_words_are_counted(self):
        rule = _rule(["order number"], "code", within=2)
        assert take(rule, "order number: #4412") == "4412"
        assert take(rule, "order number is 4412") == "4412"
        assert take(rule, "order number is still 4412") is None, "three words away"

    def test_the_first_occurrence_with_a_value_gives_it(self):
        rule = _rule(["order number"], "code", within=1)
        assert take(rule, "no order number yet; order number 77, not order number 88") == "77"

    def test_any_phrase_of_the_rule_may_introduce_it_in_any_case(self):
        rule = _rule(["order no", "order number"], "code")
        assert take(rule, "ORDER NO. 9") == "9"

    def test_nothing_in_nothing_out(self):
        rule = _rule(["order number"], "code")
        assert take(rule, None) is None
        assert take(rule, "") is None


class TestTyping:
    """Through field_types.coerce and the declared locale (DEP-1)."""

    def test_numbers_are_read_by_the_sources_locale_and_never_guessed(self):
        assert typed("1,234.50", "decimal", "en_US") == Decimal("1234.50")
        assert typed("1.234,50", "decimal", "pt_BR") == Decimal("1234.50")
        assert typed("1,234.50", "decimal", None) is None, "machine formats only, undeclared"
        assert typed("1.5", "decimal", "pt_BR") is None, "strict grouping"
        assert typed("4412", "integer", None) == 4412

    def test_dates_are_iso_or_the_locales_order(self):
        assert typed("2026-03-12", "date", None) == datetime.date(2026, 3, 12)
        assert typed("02/01/2024", "date", "pt_BR") == datetime.date(2024, 1, 2)
        assert typed("02/01/2024", "date", "en_US") == datetime.date(2024, 2, 1)
        assert typed("02/01/2024", "date", None) is None

    def test_text_is_the_span_with_its_spacing_tidied(self):
        assert typed(" Acme   Router ", "string", None) == "Acme Router"
        assert typed(None, "string", None) is None

    def test_values_are_compared_as_their_type(self):
        assert same_value("INV-7", "inv-7")
        assert same_value(Decimal("1234.50"), Decimal("1234.5"))
        assert not same_value("4412", "4413")
        assert not same_value(None, None), "two blanks are not an agreement"


def test_the_rule_reads_as_a_sentence():
    assert describe(_rule(["order number", "order no"], "code")) == (
        "In body, after 'order number' or 'order no' (within 2 words), take a code")
    assert describe(_rule(["product"], "words", within=1, max_words=3)) == (
        "In body, after 'product' (next word), take up to 3 words")


def test_tokenizing_cannot_backtrack():
    """A pattern that could backtrack would take far longer on the
    longer input; this one scales with it."""
    def seconds(n):
        text = "a-" * n + "!"
        started = time.perf_counter()
        tokens(text)
        return time.perf_counter() - started

    small, large = seconds(20_000), seconds(200_000)
    assert large < 2.0
    assert large < small * 40, (small, large)
