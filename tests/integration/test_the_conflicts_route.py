"""
GET /objects/{type}/{id}/conflicts.

`core/mirror/survivorship.py` states the promise and had no way to keep
it: "deleting losing values destroys trust. A person asking why the
golden record says Leeds needs to see that the CRM said Hull and was
outranked -- otherwise the answer is an assertion." The losing values
have been appended to `gold_conflicts.<Type>` since GOLD-6 and nothing
could read them back.

THE ROWS ARE WRITTEN DIRECTLY HERE, and that is deliberate rather than
lazy. `tests/unit/test_why_the_golden_record_says_that.py` proves the
WRITER's output through a real two-database build with real identity
resolution; no fixture deployment declares `identity:` or
`survivorship:`, so reproducing that here would mean standing up a
second deployment to test a route's FILTERING. What this file is for is
the three things only a route can get wrong: who may ask, whose objects
they may ask about, and which values come back.
"""

from datetime import UTC, datetime

import pyarrow as pa

from core.mirror.gold import CONFLICT_NAMESPACE, CONFLICT_SCHEMA
from tests.conftest import with_roles


def _login(client, username, role, region="us-west"):
    client.app.state.user_directory.create_user(username, "pw", region, role)
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def _catalog(client):
    """The same lake the route reads."""
    from pyiceberg.catalog.sql import SqlCatalog

    mirror_dir = client.app.state.runtime_paths.data_dir / "mirror"
    return SqlCatalog(
        "elysium_mirror",
        uri=f"sqlite:///{mirror_dir / 'catalog.db'}",
        warehouse=f"file://{mirror_dir / 'warehouse'}",
    )


def _record(client, *, entity_id="cust_001", field="name", kind="property",
            chosen="Ada Okafor", losing="Ada"):
    """One disagreement, in the shape `_write_conflicts` writes."""
    catalog = _catalog(client)
    identifier = f"{CONFLICT_NAMESPACE}.Customer"
    try:
        catalog.create_namespace(CONFLICT_NAMESPACE)
    except Exception:  # noqa: BLE001 - already there is the normal case
        pass
    try:
        table = catalog.load_table(identifier)
    except Exception:  # noqa: BLE001 - first write creates it
        table = catalog.create_table(identifier, schema=CONFLICT_SCHEMA)
    table.append(pa.Table.from_pylist([{
        "entity_id": entity_id, "kind": kind, "field": field,
        "chosen": chosen, "chosen_source": "crm",
        "losing": losing, "losing_source": "primary",
        "recorded_at": datetime.now(UTC).isoformat(),
    }], schema=CONFLICT_SCHEMA))


#: manage:users AND enough read grants to see the object and its
#: fields. A DEDICATED ROLE rather than a grant added to `admin`: the
#: fixture's own discipline is that a new grant on an already-tested
#: role silently changes what every test relying on it sees.
LINEAGE_ADMIN = {"allowed_actions": [
    "manage:users", "read:Customer", "read:Customer.customer_id",
    "read:Customer.name", "read:Customer.region", "read:Customer.email",
]}

#: The same, minus one field. For the masking half: `email` is NOT
#: readable, so a conflict about it must still be reported and must not
#: carry either address.
LINEAGE_ADMIN_NO_EMAIL = {"allowed_actions": [
    "manage:users", "read:Customer", "read:Customer.customer_id",
    "read:Customer.name", "read:Customer.region",
]}


class TestWhoMayAsk:
    def test_an_ordinary_reader_is_refused(self, client):
        """GATED AS /provenance IS. `chosen_source` and `losing_source`
        name the customer's own systems, which /silos already treats as
        admin-only."""
        _login(client, "clerk", "editor")

        response = client.get("/api/objects/Customer/cust_001/conflicts")

        assert response.status_code == 403, response.text

    def test_it_refuses_before_it_looks(self, client):
        """Otherwise the status code is an existence oracle for
        somebody who may not ask at all."""
        _login(client, "clerk2", "editor")

        real = client.get("/api/objects/Customer/cust_001/conflicts")
        unreal = client.get("/api/objects/Customer/no_such_id/conflicts")

        assert real.status_code == unreal.status_code == 403


class TestMACSTILLAPPLIES:
    """manage:users IS NOT PERMISSION TO READ EVERY OBJECT, which is
    where this route differs from /provenance beside it. That one
    returns four opaque identifiers -- a silo name, a table name, a
    hash, a snapshot id -- and no customer data. This one returns
    VALUES, so an administrator in one compartment learning what two
    systems said about an object in another would be a MAC bypass
    dressed as an admin feature."""

    def test_an_administrator_in_another_compartment_gets_nothing(self, client):
        with_roles(client.app, lineage_admin=LINEAGE_ADMIN)
        _record(client)
        _login(client, "east", "lineage_admin", region="us-east")

        response = client.get("/api/objects/Customer/cust_001/conflicts")

        assert response.status_code == 200
        assert response.json() == []

    def test_and_their_own_compartment_answers(self, client):
        """THE CONTROL. A route returning [] unconditionally would pass
        the test above and would be indistinguishable from one that
        worked."""
        with_roles(client.app, lineage_admin=LINEAGE_ADMIN)
        _record(client)
        _login(client, "west", "lineage_admin", region="us-west")

        body = client.get("/api/objects/Customer/cust_001/conflicts").json()

        assert len(body) == 1
        assert body[0]["field"] == "name"

    def test_an_unknown_object_looks_exactly_like_a_forbidden_one(self, client):
        """UNIFORM DENIAL. Both are an empty list, so an administrator
        cannot use this route to find out which objects exist outside
        their compartment."""
        with_roles(client.app, lineage_admin=LINEAGE_ADMIN)
        _record(client)
        _login(client, "west2", "lineage_admin", region="us-west")

        forbidden = client.get("/api/objects/Customer/cust_003/conflicts")
        unreal = client.get("/api/objects/Customer/no_such_id/conflicts")

        assert forbidden.json() == unreal.json() == []


class TestTheLosingValueComesBack:
    def test_it_says_what_the_other_source_held_and_where_each_came_from(self, client):
        """The sentence survivorship.py wrote, answerable at last."""
        with_roles(client.app, lineage_admin=LINEAGE_ADMIN)
        _record(client)
        _login(client, "west3", "lineage_admin")

        entry = client.get("/api/objects/Customer/cust_001/conflicts").json()[0]

        assert entry["chosen"] == "Ada Okafor"
        assert entry["losing"] == "Ada"
        assert entry["chosen_source"] == "crm"
        assert entry["losing_source"] == "primary"
        assert entry["readable"] is True

    def test_a_type_that_has_never_disagreed_is_an_empty_answer(self, client):
        """NOT A 404, and not a fault: a deployment declaring no
        identity resolution never creates the table at all."""
        with_roles(client.app, lineage_admin=LINEAGE_ADMIN)
        _login(client, "west4", "lineage_admin")

        response = client.get("/api/objects/Customer/cust_001/conflicts")

        assert response.status_code == 200
        assert response.json() == []


class TestAFieldTheyMayNotRead:
    """THE VERDICT IS SAFE AND THE VALUES ARE NOT, which is the same
    rule `masked_comparison` follows for a merge candidate: a reader
    can be told two sources disagreed about `email` without being shown
    either address."""

    def test_the_disagreement_is_still_reported(self, client):
        with_roles(client.app, no_email=LINEAGE_ADMIN_NO_EMAIL)
        _record(client, field="email", chosen="ada@crm.example", losing="ada@billing.example")
        _login(client, "masked", "no_email")

        entry = client.get("/api/objects/Customer/cust_001/conflicts").json()[0]

        assert entry["field"] == "email"
        assert entry["chosen_source"] == "crm"
        assert entry["readable"] is False

    def test_and_neither_value_is_anywhere_in_the_body(self, client):
        """ABSENT, not nulled. Asserted against the raw text rather
        than the parsed structure, because the requirement is that the
        value never reaches the caller at all."""
        with_roles(client.app, no_email=LINEAGE_ADMIN_NO_EMAIL)
        _record(client, field="email", chosen="ada@crm.example", losing="ada@billing.example")
        _login(client, "masked2", "no_email")

        body = client.get("/api/objects/Customer/cust_001/conflicts").text

        assert "ada@crm.example" not in body
        assert "ada@billing.example" not in body

    def test_a_READABLE_field_is_not_swept_up_with_it(self, client):
        """THE CONTROL. Withholding everything would pass both tests
        above and would make the route useless."""
        with_roles(client.app, no_email=LINEAGE_ADMIN_NO_EMAIL)
        _record(client, field="name")
        _login(client, "masked3", "no_email")

        entry = client.get("/api/objects/Customer/cust_001/conflicts").json()[0]

        assert entry["readable"] is True
        assert entry["chosen"] == "Ada Okafor"


class TestAContestedCompartment:
    def test_it_is_reported_even_though_it_names_no_field(self, client):
        """A security conflict has `field: null`, so no field grant
        could admit it. It is served because an administrator deciding
        whether to trust a golden record has to know its compartment
        was contested -- and the values are security labels, which the
        Users screen already shows this same grant holder."""
        with_roles(client.app, lineage_admin=LINEAGE_ADMIN)
        _record(client, kind="security", field=None, chosen="us-west", losing="us-east")
        _login(client, "west5", "lineage_admin")

        entry = client.get("/api/objects/Customer/cust_001/conflicts").json()[0]

        assert entry["kind"] == "security"
        assert entry["field"] is None
        assert entry["readable"] is True
        assert {entry["chosen"], entry["losing"]} == {"us-west", "us-east"}


class TestTheTrackRecord:
    """R60: whose value held when these two sources disagreed before --
    rounded to ten per cent, from ten ended disagreements, never a count
    (owner, 15 October)."""

    def _ended(self, client, crm_held, primary_held, field="name"):
        from core.mirror.source_record import Ended, SourceRecordStore

        store = SourceRecordStore(client.app.state.runtime_paths.data_dir / "source_record.db")
        store.record("Customer", [Ended(f"e{i}", field, "t", "crm", "primary")
                                  for i in range(crm_held)]
                     + [Ended(f"p{i}", field, "t", "primary", "crm")
                        for i in range(primary_held)])

    def _ask(self, client):
        with_roles(client.app, lineage_admin=LINEAGE_ADMIN)
        _record(client)
        _login(client, "west", "lineage_admin", region="us-west")
        [conflict] = client.get("/api/objects/Customer/cust_001/conflicts").json()
        return conflict

    def test_ten_ended_disagreements_show_a_rounded_share(self, client):
        self._ended(client, crm_held=8, primary_held=3)  # 8 of 11 is 73%

        assert self._ask(client)["track_record"] == {"source": "crm", "about_percent": 70}

    def test_nine_are_not_enough(self, client):
        self._ended(client, crm_held=7, primary_held=2)

        assert self._ask(client)["track_record"] is None

    def test_another_fields_record_is_not_this_ones(self, client):
        self._ended(client, crm_held=10, primary_held=0, field="email")

        assert self._ask(client)["track_record"] is None

    def test_no_record_kept_creates_no_file(self, client):
        assert self._ask(client)["track_record"] is None
        assert not (client.app.state.runtime_paths.data_dir / "source_record.db").exists()


class TestTheVote:
    """R60's voting half: where three or more sources hold the field,
    which of this object's sources the majority sides with, which look
    like copies, and rounded agreement rates."""

    def _voted(self, client):
        from core.mirror.source_record import SourceRecordStore
        from core.mirror.source_vote import vote

        current = {"cust_001": {"name": {"crm": "Ada Okafor", "primary": "Ada",
                                         "erp": "Ada"}}}
        # Ten more objects so the rates clear the minimum.
        current.update({f"x{i}": {"name": {"crm": "N", "primary": "N", "erp": "N"}}
                        for i in range(10)})
        SourceRecordStore(client.app.state.runtime_paths.data_dir / "source_record.db"
                          ).replace_vote("Customer", vote(current))

    def _ask(self, client):
        with_roles(client.app, lineage_admin=LINEAGE_ADMIN)
        _record(client)
        _login(client, "west", "lineage_admin", region="us-west")
        [conflict] = client.get("/api/objects/Customer/cust_001/conflicts").json()
        return conflict

    def test_the_majority_of_this_objects_sources_is_named(self, client):
        self._voted(client)

        conflict = self._ask(client)

        assert conflict["vote"] == {"majority": ["erp", "primary"],
                                    "sources": ["crm", "erp", "primary"], "copies": []}

    def test_agreement_rates_are_rounded_and_never_counts(self, client):
        self._voted(client)

        # crm sided with the majority on 10 of 11, primary on 11 of 11.
        assert self._ask(client)["agreement"] == {"crm": 90, "primary": 100}

    def test_no_vote_where_fewer_than_three_sources_hold_it(self, client):
        conflict = self._ask(client)

        assert conflict["vote"] is None and conflict["agreement"] is None
