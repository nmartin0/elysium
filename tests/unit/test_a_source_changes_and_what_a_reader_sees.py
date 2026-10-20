"""
The upstream team changed the database. What do the users see?

`AUDIT_CHECKLIST.csv` R19 asks for a "source-mutation matrix and
live-parity suite in CI". Two thirds of that existed and were checked
rather than assumed: `test_gold_matches_the_source.py` is the
live-parity suite, comparing gold against SQLite itself on the
cross-silo shape the older parity file lacked, and
`.github/workflows/ci.yml` runs lint, the unit suite, the integration
suite, `scripts/check_controls` and the frontend. Anything in this file
runs in CI by being in this directory.

THE MATRIX DID NOT EXIST, and the gap had a sharper shape than "no
matrix". Roughly twenty files mutate a source -- a dropped column, a
type that stopped matching, a mass deletion, duplicate ids -- and NOT
ONE of them asks what a reader gets afterwards. They stop at the
sync's return value, at silver's schema, or at the raised ValueError.
Those are the pipeline's own vital signs. The question a deployment is
actually judged on is downstream of all of them: an operator whose
upstream team dropped a column needs to know what is on their users'
screens, and no test in this repository answered that.

SO EVERY CASE HERE ENDS IN A READ, through the mediator, as an
authorized user, against published gold -- the same path a browser
takes.

THE INVARIANT, stated once and asserted case by case: A SOURCE CHANGE
NEVER MAKES A READER SEE A WRONG VALUE. Exactly three landings are
permitted, and every mutation has to be in one of them:

    ABSORBED  the reader sees the new truth
    REFUSED   the reader sees the LAST GOOD data, unchanged
    WITHHELD  the reader sees nothing where the source became
              ambiguous -- never a guess at which row was meant

What is forbidden is a fourth: a half-applied table, a stale value
dressed as current, or one of two rows claiming the same id chosen
arbitrarily.

A PARAMETRISED TABLE RATHER THAN SEVEN FILES, deliberately, and it is
the only reason this is a matrix. The existing coverage is per-defect:
each file was written when something broke, with its own fixture and
its own idea of what to assert, so there is no place to add the eighth
mutation and no way to see which ones have never been tried. A table
makes the next row cheap and the empty cells visible.

AND IT FOUND SOMETHING ON ITS FIRST RUN. A column RENAME -- which
nothing in this repository had ever run against the sync, though
`sim/simulator/drift.py` implements one for the simulator's own oracle
-- was absorbed, and the mirror began serving NULL for a field whose
values were still in the source under the new name. The log said
"remove it from ontology_schema.yaml when convenient", advice that
deletes a live field. See `TestARenamedColumn`.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.intermediate_layer.auth import UserRecord
from core.mirror.gold import build_gold, published_snapshot_ids
from core.mirror.gold_connector import GoldConnector
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.ontology.gold_view import build_gold_view
from core.ontology.mediator import DataMediator

SCHEMA = {
    "Customer": {
        "id_field": "id",
        "security": {"field": "region"},
        "storage": {"silo": "p", "table": "customers", "id_column": "id"},
        "fields": {
            "id": {"type": "data"},
            "name": {"type": "data"},
            "region": {"type": "data"},
            # A DECLARED TYPE, so the type-drift row of the matrix has
            # something to violate. Stored as TEXT in SQLite and
            # declared integer here, which is the ordinary shape of a
            # mirror: the source is loose and the ontology is not.
            "score": {"type": "data", "data_type": "integer"},
        },
    }
}
COLUMNS = ["id", "name", "region", "score"]
COLUMN_TYPES = {"id": "string", "name": "string", "region": "string", "score": "integer"}
FIELDS_BY_COLUMN = {"name": "name", "region": "region", "score": "score"}

# THE READER IS IN ONE COMPARTMENT, so every assertion below is about
# what an authorized person actually gets rather than about raw rows.
# c3 is in the other region and must never appear.
WEST = UserRecord(user_id="w", security_value="us-west", role_name="r")
ROLES = {"r": {"allowed_actions": ["read:Customer"] + [f"read:Customer.{f}" for f in SCHEMA["Customer"]["fields"]]}}

ROWS = [
    ("c1", "Ada", "us-west", "10"),
    ("c2", "Bram", "us-west", "20"),
    ("c3", "Chidi", "us-east", "30"),
]

# WHAT A HEALTHY DEPLOYMENT SERVES, before anything is mutated. Every
# "unchanged" assertion in this file is against this, so it is written
# once rather than restated per case.
INTACT = {"ids": ["c1", "c2"], "c1": {"name": "Ada", "score": 10}}


class _NoWrites:
    """A write log that has never been written to.

    REQUIRED, NOT A CONVENIENCE. A sync constructed WITHOUT a write log
    cannot check what depends on a vanished column, and drift_policy
    refuses rather than absorbing on a check that did not happen -- so
    without this, every removal case below would test the refusal path
    and the absorb path would be unreachable.
    """

    def edits_touching_field(self, object_type, field_name):
        return {"applied": 0, "pending": 0}


class Deployment:
    """A source, a mirror, and a way to ask what a reader sees."""

    def __init__(self, tmp_path):
        self.source = tmp_path / "source.db"
        conn = sqlite3.connect(self.source)
        # NO PRIMARY KEY on id, deliberately: the duplicate-id row of
        # the matrix needs a source that permits one, and a real
        # customer database routinely has a "key" the database does not
        # enforce. Declaring it UNIQUE here would make that mutation
        # untestable and would be testing SQLite rather than Elysium.
        conn.execute("CREATE TABLE customers (id TEXT, name TEXT, region TEXT, score TEXT)")
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?)", ROWS)
        conn.commit()
        conn.close()
        self.sync = IcebergMirrorSync(
            tmp_path / "mirror",
            {"p": SQLiteReadAdapter({"path": self.source})},
            write_log=_NoWrites(),
        )

    def execute(self, *statements):
        """Change the source, as an upstream team would."""
        conn = sqlite3.connect(self.source)
        for statement in statements:
            conn.execute(statement)
        conn.commit()
        conn.close()

    def sync_and_publish(self, **kwargs):
        """Both halves, and ASSERTS NEITHER.

        A first version asserted the publication succeeded, which made
        the accept-deletions case fail in the fixture rather than in
        the test -- and hid the finding it was failing on. The two
        layers have separate guards and a case is entitled to expect
        either one of them to stop.
        """
        result = self.sync.sync_table(
            "p", "customers", "id", COLUMNS, COLUMN_TYPES, FIELDS_BY_COLUMN, **kwargs
        )
        silver = self.sync.catalog.load_table("p.customers").scan().to_arrow().to_pylist()
        # THE SAME FLAG REACHES GOLD, as run_sync now carries it (R66):
        # the one table here is Customer's primary storage.
        gold = build_gold(self.sync.catalog, "Customer", SCHEMA["Customer"], silver,
                          accept_deletions=kwargs.get("accept_deletions", False))
        return result, gold

    def sync_and_publish_cleanly(self, **kwargs):
        """For the cases where both layers are expected to accept."""
        result, gold = self.sync_and_publish(**kwargs)
        assert gold.published, f"gold refused: {gold.problems}"
        return result

    def what_a_reader_sees(self):
        """Through the mediator, as a person, against published gold.

        A FRESH MEDIATOR EVERY TIME, because `published_snapshot_ids`
        is read at construction: a reused one would answer from the
        snapshot it was built with and every case would pass by reading
        pre-mutation gold.
        """
        view, excluded = build_gold_view(SCHEMA)
        assert excluded == {}, "the gold view dropped a type; the fixture is wrong"
        mediator = DataMediator(
            view,
            {"gold": GoldConnector(self.sync.catalog, published_snapshot_ids(self.sync.catalog, view))},
            {"Customer": "gold"},
            ROLES,
        )
        return {
            "ids": sorted(mediator.search_object(WEST, "Customer")),
            "c1": mediator.get_object(WEST, "Customer", "c1", ["name", "score"]),
        }


@pytest.fixture
def deployment(tmp_path):
    """Synced and published once, so every case starts from a mirror
    that is serving correctly."""
    live = Deployment(tmp_path)
    live.sync_and_publish_cleanly()
    assert live.what_a_reader_sees() == INTACT, "the fixture does not serve; nothing below proves anything"
    return live


# ---------------------------------------------------------------------
# ABSORBED -- the reader sees the new truth.
# ---------------------------------------------------------------------


class TestAChangeTheMirrorAbsorbs:
    def test_AN_ORDINARY_UPDATE_REACHES_THE_READER(self, deployment):
        """THE CONTROL FOR THE WHOLE FILE, and the reason it is first.

        Every case below asserts either a new value or an UNCHANGED
        one, and a pipeline that had silently stopped propagating
        anything at all would satisfy every "unchanged" assertion
        perfectly. This is the one that fails if the mirror has quietly
        become a photograph.
        """
        deployment.execute("UPDATE customers SET score = '99' WHERE id = 'c1'")

        deployment.sync_and_publish_cleanly()

        assert deployment.what_a_reader_sees()["c1"] == {"name": "Ada", "score": 99}

    def test_a_column_nobody_declared_changes_nothing(self, deployment):
        """An upstream team adding a column is the commonest change
        there is, and a mirror that refused one would refuse most
        weeks. It must reach nobody: the field has no grant and no read
        path."""
        deployment.execute("ALTER TABLE customers ADD COLUMN internal_notes TEXT")

        deployment.sync_and_publish_cleanly()

        assert deployment.what_a_reader_sees() == INTACT

    def test_a_dropped_column_reads_as_absent_not_as_its_last_value(self, deployment):
        """THE HONEST ANSWER WHEN DATA GENUINELY GOES AWAY.

        Absorbed, because refusing here freezes the mirror over a
        column nobody used and a frozen mirror goes stale while the
        source moves on -- drift_policy's own argument. What the reader
        must NOT get is the value the column held before it was
        dropped, which is the shape a cache would produce and which
        would be a wrong answer wearing a current timestamp.
        """
        deployment.execute("ALTER TABLE customers DROP COLUMN score")

        deployment.sync_and_publish_cleanly()

        seen = deployment.what_a_reader_sees()
        assert seen["ids"] == ["c1", "c2"], "dropping one column must not lose the rows"
        assert seen["c1"] == {"name": "Ada", "score": None}


# ---------------------------------------------------------------------
# REFUSED -- the reader sees the last good data, unchanged.
# ---------------------------------------------------------------------


class TestAChangeTheMirrorRefuses:
    def test_a_type_that_stopped_matching_leaves_the_reader_untouched(self, deployment):
        """ONE BAD CELL, AND THE WHOLE TABLE HOLDS.

        `score` is declared integer and the source starts holding
        "N/A". Absorbing would mean serving values of a type the
        ontology says they are not; a partial absorb would mean one
        reader seeing the new row and another the old. So the mirror
        does not move, and c1 -- which was never touched -- still reads
        exactly as it did.
        """
        deployment.execute("UPDATE customers SET score = 'N/A' WHERE id = 'c2'")

        with pytest.raises(ValueError, match="no longer holds the type"):
            deployment.sync_and_publish()

        assert deployment.what_a_reader_sees() == INTACT

    def test_a_mass_deletion_leaves_the_reader_untouched(self, deployment):
        """A PARTIALLY FAILED READ LOOKS EXACTLY LIKE A MASS DELETION,
        and the two cannot be told apart from here. Applying it when it
        was a failed read deletes a customer's data from the mirror; it
        is the one source change where doing nothing is clearly safer
        than doing the obvious thing.
        """
        deployment.execute("DELETE FROM customers WHERE id IN ('c2', 'c3')")

        with pytest.raises(Exception, match="partial"):
            deployment.sync_and_publish()

        assert deployment.what_a_reader_sees() == INTACT

    def test_the_escape_gets_the_deletion_into_SILVER(self, deployment):
        """THE CONTROL FOR THE TEST ABOVE. A refusal nothing could
        override would make a genuine mass deletion unsyncable
        forever, so the escape is per-run and per-table and a person
        has to type it.
        """
        deployment.execute("DELETE FROM customers WHERE id IN ('c2', 'c3')")

        result, _ = deployment.sync_and_publish(accept_deletions=True)

        assert result.row_count == 1, "the flag did not reach silver"

    def test_AND_GOLD_TOO_SO_THE_READER_SEES_IT(self, deployment):
        """R66, FOUND BY THIS MATRIX AND NOW CLOSED.

        `accept_deletions` used to reach the SYNC and nothing else:
        build_gold's own 50%-of-the-last-publication guard was
        unconditional, so the documented remedy moved silver, left gold
        refusing, and left every reader on the pre-deletion rows. This
        test pinned that, and recorded why it was not fixed in passing:
        the flag names `silo.table` and gold is keyed by object type.

        THE RULE CHOSEN (scripts/run_sync.deletions_accepted_for): a
        type's guard yields when every table deciding WHICH OBJECTS IT
        HAS was accepted -- its primary storage, and for an identity-
        resolved type every storage. Here that is `p.customers`, the
        one table.
        """
        deployment.execute("DELETE FROM customers WHERE id IN ('c2', 'c3')")

        _, gold = deployment.sync_and_publish(accept_deletions=True)

        assert gold.published, gold.problems
        assert deployment.what_a_reader_sees()["ids"] == ["c1"]

    def test_gold_s_guard_still_holds_without_the_flag(self, deployment):
        """THE CONTROL: silver is let through, gold is asked WITHOUT the
        flag, and refuses -- the door opens only for the operator who
        typed it, at each layer."""
        deployment.execute("DELETE FROM customers WHERE id IN ('c2', 'c3')")
        deployment.sync.sync_table("p", "customers", "id", COLUMNS, COLUMN_TYPES,
                                   FIELDS_BY_COLUMN, accept_deletions=True)
        silver = deployment.sync.catalog.load_table("p.customers").scan().to_arrow().to_pylist()

        gold = build_gold(deployment.sync.catalog, "Customer", SCHEMA["Customer"], silver)

        assert not gold.published
        assert any("of the last publication is gone" in problem for problem in gold.problems)
        assert deployment.what_a_reader_sees() == INTACT


# ---------------------------------------------------------------------
# WITHHELD -- the reader sees nothing rather than a guess.
# ---------------------------------------------------------------------


class TestAChangeTheMirrorWITHHOLDS:
    def test_two_rows_claiming_one_id_mean_the_reader_sees_NEITHER(self, deployment):
        """THE ONLY HONEST ANSWER TO AN AMBIGUOUS KEY.

        Two rows both claiming to be c1, with different values. Any
        rule that picked one -- first, last, highest -- would serve a
        value that is only as true as the ordering it came from, and
        would look exactly like a correct answer. So both copies are
        quarantined, named by key, and c1 leaves the set.

        THE UNAFFECTED ROW SURVIVES, which is the half that makes this
        a withholding rather than a refusal: c2 is not ambiguous and
        goes on being served.
        """
        deployment.execute("INSERT INTO customers VALUES ('c1', 'Ada the second', 'us-west', '77')")

        result = deployment.sync_and_publish_cleanly()

        assert result.quarantined == 2, "both copies are held, not one"
        seen = deployment.what_a_reader_sees()
        assert seen["ids"] == ["c2"]
        assert seen["c1"] == {"name": None, "score": None}


# ---------------------------------------------------------------------
# The case the matrix was built to find.
# ---------------------------------------------------------------------


class TestARenamedColumn:
    """A RENAME IS NOT A SHAPE A SOURCE CAN REPORT. No database records
    that `score` became `risk_score`. A sync sees one declared column
    gone and one column present that was not there last time, in the
    same table in the same run, and that is the entire evidence.

    HELD SINCE 21 OCTOBER, with the owner. Until then the table carried
    on and served `score` empty in every row while the values sat in the
    source under the new name; see drift_policy.verdict_for_removed_column
    for the precedent on both sides.
    """

    def test_a_rename_holds_the_table_at_its_last_good_copy(self, deployment):
        deployment.execute("ALTER TABLE customers RENAME COLUMN score TO risk_score",
                           "UPDATE customers SET name = 'Ada L.' WHERE id = 'c1'")

        with pytest.raises(ValueError) as held:
            deployment.sync_and_publish()

        assert deployment.what_a_reader_sees() == INTACT, "the last good copy, not empties"
        said = str(held.value)
        assert "risk_score" in said and "RENAMED" in said and "repoint" in said
        assert "on_suspected_rename: serve_empty" in said, "the way through is named"

    def test_serve_empty_is_the_old_answer_when_a_deployment_asks_for_it(
            self, deployment, caplog):
        deployment.sync._on_suspected_rename = "serve_empty"
        deployment.execute("ALTER TABLE customers RENAME COLUMN score TO risk_score")

        with caplog.at_level("WARNING"):
            deployment.sync_and_publish_cleanly()

        seen = deployment.what_a_reader_sees()
        assert seen["ids"] == ["c1", "c2"], "a rename must not lose the rows"
        assert seen["c1"] == {"name": "Ada", "score": None}
        drift = "\n".join(record.getMessage() for record in caplog.records)
        assert "RENAMED" in drift and "serving null" in drift

    def test_a_column_that_was_always_there_is_no_suspect(self, deployment, caplog):
        """THE CONTROL: only a column NEW since the last sync suggests a
        rename. One that has always been there and was never declared
        would otherwise hold the table at every later removal, for good."""
        deployment.execute("ALTER TABLE customers ADD COLUMN notes TEXT")
        deployment.sync_and_publish_cleanly()
        deployment.execute("ALTER TABLE customers DROP COLUMN score")

        with caplog.at_level("WARNING"):
            deployment.sync_and_publish_cleanly()

        drift = "\n".join(record.getMessage() for record in caplog.records)
        assert "is gone" in drift and "RENAMED" not in drift
        assert deployment.what_a_reader_sees()["c1"] == {"name": "Ada", "score": None}

    def test_an_ordinary_DROP_is_not_described_as_a_possible_rename(self, deployment, caplog):
        """A removal with nothing new beside it is absorbed, as before:
        the source no longer holds the value, so empty is the truth."""
        deployment.execute("ALTER TABLE customers DROP COLUMN score")

        with caplog.at_level("WARNING"):
            deployment.sync_and_publish_cleanly()

        drift = "\n".join(record.getMessage() for record in caplog.records)
        assert "is gone" in drift, "the removal itself must still be reported"
        assert "RENAMED" not in drift
        assert "repoint" not in drift.lower()


class TestARenameAfterTheFirstSync:
    """What a hold does next, and the cases review found (21 October)."""

    def test_the_hold_lasts_until_the_field_is_repointed(self, deployment):
        deployment.execute("ALTER TABLE customers RENAME COLUMN score TO risk_score")
        for _ in range(2):
            with pytest.raises(ValueError, match="RENAMED"):
                deployment.sync_and_publish()

        repointed = {**FIELDS_BY_COLUMN, "risk_score": "score"}
        del repointed["score"]
        result = deployment.sync.sync_table(
            "p", "customers", "id", ["id", "name", "region", "risk_score"],
            {**COLUMN_TYPES, "risk_score": "integer"}, repointed)

        assert result.row_count == 3, "repointed, the table syncs again"

    def test_with_no_record_of_earlier_columns_it_says_so(self, tmp_path):
        """A deployment from before the record existed: it cannot tell
        which undeclared column is new, and must not claim they all are."""
        live = Deployment(tmp_path)
        live.execute("ALTER TABLE customers ADD COLUMN notes TEXT",
                     "ALTER TABLE customers DROP COLUMN score")

        with pytest.raises(ValueError) as held:
            live.sync_and_publish()

        assert "no record of this source's earlier columns" in str(held.value)
        assert "were not there before" not in str(held.value)

    def test_a_rename_in_two_releases_names_where_the_values_may_be(
            self, deployment, caplog):
        """THE LIMIT: absorbed as a plain drop, since by the drop the new
        column is not new. The most that can be said is where to look."""
        deployment.execute("ALTER TABLE customers ADD COLUMN risk_score TEXT",
                           "UPDATE customers SET risk_score = score")
        deployment.sync_and_publish_cleanly()
        deployment.execute("ALTER TABLE customers DROP COLUMN score")

        with caplog.at_level("WARNING"):
            deployment.sync_and_publish_cleanly()

        drift = "\n".join(record.getMessage() for record in caplog.records)
        assert "renamed in an earlier release" in drift and "'risk_score'" in drift

    def test_an_apis_missing_key_is_not_taken_for_a_rename(self, deployment):
        """An API leaves out a key whose value is null: a key gone and
        another back is not evidence. Absorbed, as before."""
        deployment.sync.adapters["p"].columns_from_records = True
        deployment.execute("ALTER TABLE customers RENAME COLUMN score TO risk_score")

        deployment.sync_and_publish_cleanly()

        assert deployment.what_a_reader_sees()["c1"]["score"] is None

    def test_the_sources_columns_are_asked_for_once(self, deployment):
        adapter = deployment.sync.adapters["p"]
        asked = []
        original = adapter.columns_present
        adapter.columns_present = lambda table: asked.append(table) or original(table)

        deployment.sync_and_publish_cleanly()

        assert asked == ["customers"]


class TestTheRenameSetting:
    @pytest.mark.parametrize(("config", "means"), [
        ({}, "hold"), ({"on_suspected_rename": "serve_empty"}, "serve_empty"),
        ({"on_suspected_rename": " HOLD "}, "hold"), ({"on_suspected_rename": None}, "hold"),
    ], ids=["absent", "serve_empty", "spelled_loosely", "left_blank"])
    def test_what_config_yaml_says(self, config, means):
        from core.deployment_loader import _resolve_suspected_rename

        assert _resolve_suspected_rename(config) == means

    def test_anything_else_is_refused_at_load(self):
        from core.deployment_loader import _resolve_suspected_rename

        with pytest.raises(ValueError, match="on_suspected_rename must be one of"):
            _resolve_suspected_rename({"on_suspected_rename": "absorb"})

    def test_the_sync_is_given_it(self):
        import inspect

        from scripts import run_sync

        assert "on_suspected_rename=config.on_suspected_rename" in inspect.getsource(run_sync)


class TestAnAbsorbedColumnIsRecorded:
    """FOUND AGAINST THE SIMULATOR (19 October): a renamed column blanked
    every order total while the attempt history read plain "synced" with
    no detail -- and the Mirror screen reads that history. The policy's
    explanation now travels on the result and onto the attempt."""

    def test_the_result_carries_the_explanation(self, deployment):
        deployment.sync._on_suspected_rename = "serve_empty"
        deployment.execute("ALTER TABLE customers RENAME COLUMN score TO risk_score")

        result = deployment.sync_and_publish_cleanly()

        assert result.absorbed_drift and "risk_score" in result.absorbed_drift

    def test_and_a_sync_that_lost_nothing_carries_none(self, deployment):
        deployment.execute("UPDATE customers SET name = 'Ada L.' WHERE id = 'c1'")

        assert deployment.sync_and_publish_cleanly().absorbed_drift is None

    def test_the_attempt_records_it_beside_its_outcome(self, deployment):
        from scripts.run_sync import _detail_for, _outcome_for

        deployment.sync._on_suspected_rename = "serve_empty"
        deployment.execute("ALTER TABLE customers RENAME COLUMN score TO risk_score")
        result = deployment.sync_and_publish_cleanly()

        assert _outcome_for(result) == "synced"
        assert "RENAMED" in _detail_for(result)


class TestWhichTablesLicenseAType:
    """R66's rule, as a function: the tables deciding which objects a
    type HAS must all be accepted."""

    def _accepted(self, type_def, accepted):
        from scripts.run_sync import deletions_accepted_for

        return deletions_accepted_for(type_def, set(accepted))

    PLAIN = {"storage": {"silo": "p", "table": "customers"}}
    JOINED = {"storage": {"silo": "p", "table": "customers"},
              "additional_storage": {"risk": {"silo": "r", "table": "risk"}}}
    RESOLVED = {**JOINED, "identity": {"match_on": ["email"]}}

    def test_a_plain_type_follows_its_table(self):
        assert self._accepted(self.PLAIN, ["p.customers"])
        assert not self._accepted(self.PLAIN, [])

    def test_a_joined_type_follows_its_primary_only(self):
        """An additional storage adds fields to rows the primary has; it
        cannot shrink the type, so accepting it alone licenses nothing."""
        assert self._accepted(self.JOINED, ["p.customers"])
        assert not self._accepted(self.JOINED, ["r.risk"])

    def test_an_identity_resolved_type_needs_every_source(self):
        assert not self._accepted(self.RESOLVED, ["p.customers"])
        assert self._accepted(self.RESOLVED, ["p.customers", "r.risk"])
