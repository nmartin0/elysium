"""Reading back the values survivorship outranked.

THE PROMISE WAS WRITTEN DOWN AND NOT KEPT. `core/mirror/survivorship.py`
states the rule it exists to serve, quoting the MDM research this
project recorded: "deleting losing values destroys trust. A person
asking why the golden record says Leeds needs to see that the CRM said
Hull and was outranked -- otherwise the answer is an assertion. Losers
go to the conflicts table, not to the bin."

They went to the conflicts table. `gold.py:_write_conflicts` has
appended them since GOLD-6, append-only, "because a record that can be
rewritten is not a record". And a repository-wide search for
`gold_conflicts` found the writer, the namespace constant, and two
assertions in `test_survivorship.py`. No reader function, no route, no
screen. A table nobody can read is the bin with extra steps, and the
promise was an assertion after all.

WHY IT IS WORTH READING rather than merely tidying up: it is the ONLY
per-field, per-source record in the system. Everything else the lake
holds about origin is per ROW -- `_silo` names one source for a whole
object, `_fused_from` names every storage that contributed without
saying which contributed WHAT, and `fusion.py` admits as much in those
words. A customer fused from two databases reports one silo for every
field, including the ones that came from the other.

THROUGH A REAL BUILD, not against hand-made rows. The rows under test
have to be the ones `build_gold` actually writes -- their column names,
their stringification, their ordering -- because the defect this closes
was precisely that nothing had ever read what the writer produces.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import build_gold
from core.mirror.gold_conflicts import ConflictsNotRecorded, read_conflicts
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.survivorship import PROPERTY_CONFLICT, SECURITY_CONFLICT

TYPE = {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "storage": {"silo": "b", "table": "customers", "id_column": "cust_pk"},
    "additional_storage": {"crm": {"silo": "c", "table": "contacts",
                                    "id_column": "contact_id"}},
    "identity": {"match_on": ["email"]},
    "survivorship": {"prefer": ["crm"]},
    "fields": {
        "customer_id": {"type": "data", "column": "cust_pk"},
        "region": {"type": "data"},
        "email": {"type": "data"},
        "name": {"type": "data"},
    },
}


@pytest.fixture
def published(tmp_path):
    """Two databases that disagree, resolved into one gold table.

    THE DISAGREEMENT IS THE FIXTURE. Both systems hold a customer
    reachable by the same email, and both have a name for her -- which
    is the only shape that produces a conflict row at all. A null on
    one side writes nothing (see the test at the end of this file).
    """
    billing, crm = tmp_path / "billing.db", tmp_path / "crm.db"
    conn = sqlite3.connect(billing)
    conn.execute("CREATE TABLE customers (cust_pk TEXT PRIMARY KEY, email TEXT, "
                 "region TEXT, name TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1', 'a@x.com', 'us-west', 'Ada')")
    conn.commit()
    conn.close()

    conn = sqlite3.connect(crm)
    conn.execute("CREATE TABLE contacts (contact_id TEXT PRIMARY KEY, email TEXT, "
                 "region TEXT, name TEXT)")
    conn.execute("INSERT INTO contacts VALUES ('9f2a', 'a@x.com', 'us-west', 'Ada Okafor')")
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {
        "b": SQLiteReadAdapter({"path": billing}),
        "c": SQLiteReadAdapter({"path": crm}),
    })
    columns = ["cust_pk", "email", "region", "name"]
    sync.sync_table("b", "customers", "cust_pk", columns, dict.fromkeys(columns, "string"))
    contact_columns = ["contact_id", "email", "region", "name"]
    sync.sync_table("c", "contacts", "contact_id", contact_columns,
                    dict.fromkeys(contact_columns, "string"))
    return sync


def _build(sync, type_def=TYPE):
    silver = sync._catalog.load_table("b.customers").scan().to_arrow().to_pylist()
    crm = sync._catalog.load_table("c.contacts").scan().to_arrow().to_pylist()
    result = build_gold(sync._catalog, "Customer", type_def, silver,
                        additional_rows={"crm": crm})
    assert result.published, result.problems
    return result


class TestTheLosingValueCanBeFoundAgain:
    def test_it_says_what_the_other_source_held(self, published):
        """THE WHOLE POINT, and the sentence survivorship.py wrote: the
        CRM said Hull and was outranked, and somebody can see it."""
        _build(published)

        conflicts = read_conflicts(published._catalog, "Customer", "c1")
        name = next(row for row in conflicts if row["field"] == "name")

        # `prefer: [crm]` puts the CRM first, so its fuller name wins.
        assert name["chosen"] == "Ada Okafor"
        assert name["losing"] == "Ada"

    def test_it_says_WHICH_SOURCE_each_value_came_from(self, published):
        """The per-field half, which nothing else in the system has.
        `_silo` would say `b` for every field of this object."""
        _build(published)

        name = next(row for row in read_conflicts(published._catalog, "Customer", "c1")
                    if row["field"] == "name")

        assert name["chosen_source"] == "crm"
        assert name["losing_source"] == "primary"
        # AND ITS KIND, which the security case below turns on: the two
        # are stored in one table precisely so an operator asking "what
        # did identity resolution decline to do" finds one place.
        assert name["kind"] == PROPERTY_CONFLICT

    def test_an_object_nothing_disagreed_about_has_nothing(self, published):
        """THE CONTROL. A reader returning the whole table would satisfy
        every test above and would attach another customer's conflicts
        to this one."""
        _build(published)

        assert read_conflicts(published._catalog, "Customer", "no_such_id") == []

    def test_a_type_with_no_conflicts_table_is_a_REFUSAL_not_an_empty_list(self, published):
        """"We have never looked" and "we looked and found none" are
        different facts, and only the second is reassuring. A
        deployment declaring no identity resolution never creates the
        table; returning [] would tell its operator their sources
        agree."""
        _build(published)

        with pytest.raises(ConflictsNotRecorded):
            read_conflicts(published._catalog, "Transaction", "t1")


class TestTheArgumentHasAHistory:
    def test_every_publication_that_still_disagrees_adds_a_row(self, published):
        """APPEND-ONLY, "because a record that can be rewritten is not a
        record". Two publications over unchanged, still-disagreeing
        sources leave two of each conflict."""
        _build(published)
        _build(published)

        names = [row for row in read_conflicts(published._catalog, "Customer", "c1")
                 if row["field"] == "name"]

        assert len(names) == 2

    def test_the_newest_comes_first(self, published):
        """The current one is the only row describing what gold holds
        NOW; the rest are the history of the argument, and a reader
        scrolling from the top should meet the present."""
        _build(published)
        _build(published)

        stamps = [row["recorded_at"] for row in
                  read_conflicts(published._catalog, "Customer", "c1")]

        assert stamps == sorted(stamps, reverse=True)
        assert stamps[0] != stamps[-1], "both publications wrote the same instant"


class TestWhatItDoesNotRecord:
    def test_A_NULL_FILLED_FROM_ANOTHER_SOURCE_LEAVES_NO_TRACE(self, published, tmp_path):
        """THE GAP, PINNED RATHER THAN HIDDEN.

        survivorship.py appends a Conflict only where two sources both
        had something to say and said different things. Where the
        preferred source is SILENT and a lower one supplies the value,
        the fill happens and nothing is written -- so afterwards "the
        CRM held this" and "the CRM was empty and billing supplied it"
        are indistinguishable.

        That is `AUDIT_CHECKLIST.csv` R67(a), and it is not this
        reader's to close: there is no row to read. Asserted here so
        that whoever closes it has a test that changes when they do,
        rather than discovering the shape by reading the writer.
        """
        conn = sqlite3.connect(tmp_path / "crm.db")
        conn.execute("UPDATE contacts SET name = NULL WHERE contact_id = '9f2a'")
        conn.commit()
        conn.close()
        published.sync_table("c", "contacts", "contact_id",
                             ["contact_id", "email", "region", "name"],
                             dict.fromkeys(["contact_id", "email", "region", "name"], "string"))

        _build(published)

        # NOT MERELY "NO NAME CONFLICT" -- no conflicts table at all.
        # The fill is the only thing that happened and it wrote
        # nothing, so the type has never recorded a disagreement. That
        # is a stronger statement of the gap than I expected to be
        # able to make, and it is the first thing a reader of R67(a)
        # should know.
        with pytest.raises(ConflictsNotRecorded):
            read_conflicts(published._catalog, "Customer", "c1")

    def test_a_contested_COMPARTMENT_is_recorded_as_its_own_kind(self, published, tmp_path):
        """Not every conflict is about a field. Two sources disagreeing
        about which compartment an object belongs to has no field at
        all, and is the more serious of the two -- it is a disagreement
        about who may see the object.

        AND IT IS THE ONLY KIND THAT APPEARS, which I had to be shown.
        A first version of this test also expected the name conflict,
        on the reasoning that the two names still differ. They do, and
        it is not recorded, because D2 REFUSES THE MERGE when the
        compartments disagree -- the entities are never fused, so
        there is no property for two sources to have competed over.
        The refusal is the finding; the name disagreement is a
        disagreement between two separate objects, which is not a
        conflict at all. Recorded here because the first reading was
        wrong and the second is not obvious.
        """
        conn = sqlite3.connect(tmp_path / "crm.db")
        conn.execute("UPDATE contacts SET region = 'us-east' WHERE contact_id = '9f2a'")
        conn.commit()
        conn.close()
        published.sync_table("c", "contacts", "contact_id",
                             ["contact_id", "email", "region", "name"],
                             dict.fromkeys(["contact_id", "email", "region", "name"], "string"))

        _build(published)

        conflicts = read_conflicts(published._catalog, "Customer", "c1")
        kinds = {row["kind"] for row in conflicts}

        assert kinds == {SECURITY_CONFLICT}
        # NO FIELD, because the object as a whole is what is contested.
        assert all(row["field"] is None for row in conflicts)
        # AND IT NAMES BOTH COMPARTMENTS, which is what makes it
        # actionable: an operator has to go and ask which is right.
        security = conflicts[0]
        assert {security["chosen"], security["losing"]} == {"us-west", "us-east"}
