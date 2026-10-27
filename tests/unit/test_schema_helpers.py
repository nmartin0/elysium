"""The id ordering the object lists use (26 October)."""

from core.ontology.schema import id_sort_key, sort_key


def test_ids_of_digits_sort_as_the_numbers_they_are():
    ids = ["1", "10", "100", "2", "9", "11"]
    assert sorted(ids, key=id_sort_key) == ["1", "2", "9", "10", "11", "100"]
    # What it replaces, so a reader sees what was wrong.
    assert sorted(ids, key=sort_key) == ["1", "10", "100", "11", "2", "9"]


def test_other_ids_keep_their_text_order():
    ids = ["cust_010", "cust_002", "cust_001"]
    assert sorted(ids, key=id_sort_key) == ["cust_001", "cust_002", "cust_010"]


def test_integers_sort_with_digit_strings_and_a_tie_is_still_total():
    mixed = ["07", 7, "7", 3, None]
    ordered = sorted(mixed, key=id_sort_key)
    assert ordered[0] is None and ordered[1] == 3
    # Equal as numbers, ordered by their text, never left to chance.
    assert sorted(["7", "07"], key=id_sort_key) == ["07", "7"]


def test_digits_and_words_can_share_a_list_without_raising():
    assert sorted(["b", "10", "2", "a"], key=id_sort_key) == ["2", "10", "a", "b"]
