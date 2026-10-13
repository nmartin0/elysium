"""
Checks and tidying that need real reference data (DEP-4).

phonenumbers, email-validator, ftfy and holidays, adopted by the owner
on 13 October. Each is used ONLY where a field declares it, in the two
places every constraint already works -- a write is refused, and silver
applies the field's `on_violation` -- plus silver's standardisation,
which can rewrite a valid phone number or address to its one form.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.standardise import rules_for, standardise
from core.mirror.sync_targets import resolve_sync_targets
from core.ontology.constraints import validate_constraints, violation


def _field(data_type="string", **constraints):
    return {"type": "data", "data_type": data_type, "constraints": constraints}


class TestPhoneNumbers:
    def test_a_national_number_is_valid_for_its_declared_region(self):
        assert violation(_field(phone="US"), "(201) 555-0123") is None
        assert violation(_field(phone="GB"), "0121 234 5678") is None

    def test_a_number_that_cannot_exist_is_refused_naming_the_region(self):
        problem = violation(_field(phone="US"), "(201) 555-012")
        assert problem == "'(201) 555-012' is not a valid phone number for US."

    def test_international_form_is_demanded_when_no_region_is_declared(self):
        assert violation(_field(phone=True), "+55 11 2345-6789") is None
        assert "with its country code" in violation(_field(phone=True), "(11) 2345-6789")


class TestEmailAddresses:
    def test_syntax_is_checked(self):
        assert violation(_field(email=True), "ada@example.com") is None
        assert "is not a valid email address" in violation(_field(email=True), "ada@@example")

    def test_never_by_asking_dns(self, monkeypatch):
        """A sync or a write must not reach the network because a field
        holds an address. Any resolver call fails this test."""
        import dns.resolver

        def no_network(*_args, **_kwargs):
            raise AssertionError("DNS was queried")

        monkeypatch.setattr(dns.resolver, "resolve", no_network)
        monkeypatch.setattr(dns.resolver.Resolver, "resolve", no_network)

        assert violation(_field(email=True), "ada@no-such-domain-xyz.example") is None


class TestPublicHolidays:
    def test_a_holiday_is_named(self):
        assert violation(_field("date", not_on_holiday="US"), "2026-12-25") == \
            "datetime.date(2026, 12, 25) falls on Christmas Day, a public holiday in US."

    def test_a_subdivision_has_its_own(self):
        """Cesar Chavez Day is a California holiday, not a federal one."""
        assert violation(_field("date", not_on_holiday="US"), "2026-03-31") is None
        assert "Cesar Chavez Day" in violation(_field("date", not_on_holiday="US-CA"), "2026-03-31")

    def test_an_ordinary_day_passes(self):
        assert violation(_field("date", not_on_holiday="BR"), "2026-11-19") is None
        assert violation(_field("date", not_on_holiday="BR"), "2026-11-20") is not None


class TestRefusedAtLoad:
    @pytest.mark.parametrize("field, says", [
        (_field(email="yes"), "`email` must be true"),
        (_field(phone="XX"), "region code"),
        (_field(phone=1), "region code"),
        (_field("integer", phone="US"), "does not apply to a integer"),
        (_field("date", not_on_holiday="ZZ"), "not a country"),
        (_field("date", not_on_holiday="US-ZZ"), "not a subdivision of US"),
        (_field("string", not_on_holiday="US"), "does not apply to a string"),
    ])
    def test_a_check_that_could_never_work(self, field, says):
        with pytest.raises(ValueError, match=says):
            validate_constraints({"T": {"fields": {"f": field}}})


class TestStandardisation:
    def test_mojibake_is_repaired_before_anything_else(self):
        assert standardise("  cafÃ©  ", rules_for({"standardise": {"fix_text": True}})) == "café"

    def test_a_valid_phone_number_takes_its_one_international_form(self):
        rules = rules_for({"standardise": {"phone": "US"}})
        assert standardise(" (201) 555-0123 ", rules) == "+12015550123"
        assert standardise("+1 201-555-0123", rules) == "+12015550123"

    def test_an_invalid_one_is_left_exactly_as_it_was(self):
        """For the constraint to report, not for tidying to hide."""
        assert standardise("call reception", rules_for({"standardise": {"phone": "US"}})) == \
            "call reception"

    def test_a_sentinel_is_null_before_it_could_be_formatted(self):
        rules = rules_for({"standardise": {"phone": "US", "null_if": ["N/A"]}})
        assert standardise("N/A", rules) is None

    def test_an_email_domain_is_normalised_and_the_mailbox_is_not(self):
        rules = rules_for({"standardise": {"email": True}})
        assert standardise("Ada.Okafor@EXAMPLE.Com", rules) == "Ada.Okafor@example.com"

    def test_none_of_it_happens_undeclared(self):
        assert standardise("cafÃ© (201) 555-0123", rules_for({})) == "cafÃ© (201) 555-0123"

    @pytest.mark.parametrize("declared, says", [
        ({"fix_text": "yes"}, "fix_text must be true or false"),
        ({"email": 1}, "email must be true or false"),
        ({"phone": "XX"}, "region code"),
    ])
    def test_a_bad_rule_is_refused(self, declared, says):
        with pytest.raises(ValueError, match=says):
            rules_for({"standardise": declared})


def test_silver_tidies_and_holds_back_through_a_real_sync(tmp_path):
    source = tmp_path / "s.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE people (id TEXT PRIMARY KEY, phone TEXT, email TEXT)")
    connection.executemany("INSERT INTO people VALUES (?, ?, ?)", [
        ("good", "(201) 555-0123", "ada@example.com"),
        ("bad_email", "(201) 555-0123", "not an address"),
    ])
    connection.commit()
    connection.close()
    schema = {"Person": {
        "id_field": "id", "storage": {"silo": "s", "table": "people", "id_column": "id"},
        "fields": {
            "id": {"type": "data"},
            "phone": {"type": "data", "standardise": {"phone": "US"}},
            "email": {"type": "data", "constraints": {"email": True},
                      "on_violation": "quarantine"},
        }}}
    validate_constraints(schema)
    (target,) = resolve_sync_targets({"object_types": schema})
    sync = IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})

    sync.sync_table("s", "people", "id", target.columns, target.column_types,
                    target.fields_by_column, target.standardisation, target.expectations)

    kept = sync._catalog.load_table("s.people").scan().to_arrow().to_pylist()
    (held,) = sync._catalog.load_table("quarantine_s.people").scan().to_arrow().to_pylist()
    assert [(row["id"], row["phone"]) for row in kept] == [("good", "+12015550123")]
    assert held["object_id"] == "bad_email" and "not a valid email address" in held["reason"]
