"""
Where proposals come from, and what turns them into merges (GOLD-6).

TWO INDEPENDENT SWITCHES, as FUSION_AND_IDENTITY.md requires: "is
inference enabled?" is deployment config defaulting to FALSE, and
"does a proposed merge need approval?" is ALWAYS -- "never
configurable, because a setting is a thing someone turns off". Only
the first exists in the config; the second is the absence of any code
path that applies a proposal.

THE BACKEND IS NEVER ALLOWED TO BREAK A SYNC. Inference is the
optional half: if the extra is missing or the matcher throws, the
mirror and gold are still correct, so the failure is reported and the
run continues.
"""

import pytest

from core.identity_decisions import APPROVED, MergeDecisionStore
from core.mirror.matching import Candidate
from scripts.run_sync import _propose_merges

TYPE = {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "storage": {"silo": "b", "table": "customers", "id_column": "cust_pk"},
    "identity": {"match_on": ["email"],
                  "probabilistic": {"compare": ["name"], "block_on": ["region"]}},
    "fields": {
        "customer_id": {"type": "data", "column": "cust_pk"},
        "region": {"type": "data"},
        "email": {"type": "data"},
        "name": {"type": "data"},
    },
}
ROWS = {None: [{"cust_pk": "c1", "email": "a@x", "region": "us-west", "name": "Ada"},
               {"cust_pk": "c2", "email": "b@x", "region": "us-west", "name": "Ada"}]}


class _Config:
    def __init__(self, identity_inference: bool):
        self.identity_inference = identity_inference


class _Matcher:
    """Stands in for the optional backend, so these tests run
    everywhere -- what is under test is the WIRING, not the scoring."""

    def __init__(self, candidates=None, raises=None):
        self._candidates = candidates or []
        self._raises = raises

    def candidates(self, type_def, rows_by_storage):
        if self._raises is not None:
            raise self._raises
        return self._candidates


@pytest.fixture
def store(tmp_path):
    return MergeDecisionStore(tmp_path / "decisions.db")


@pytest.fixture
def matcher(monkeypatch):
    def install(instance):
        import core.mirror.matching as matching_module
        monkeypatch.setattr(matching_module, "SplinkMatcher", lambda: instance)
        return instance
    return install


class TestTheSwitch:
    def test_inference_off_proposes_nothing(self, store, matcher):
        matcher(_Matcher([Candidate("primary:c1", "primary:c2", 0.99)]))

        proposed = _propose_merges(store, _Config(False), "Customer", TYPE, ROWS)

        assert proposed == 0 and store.proposals("Customer") == []

    def test_inference_on_proposes(self, store, matcher):
        matcher(_Matcher([Candidate("primary:c1", "primary:c2", 0.99)]))

        proposed = _propose_merges(store, _Config(True), "Customer", TYPE, ROWS)

        assert proposed == 1
        assert store.proposals("Customer")[0].decision == "pending"

    def test_a_type_declaring_no_inference_proposes_nothing(self, store, matcher):
        matcher(_Matcher([Candidate("primary:c1", "primary:c2", 0.99)]))
        deterministic_only = {**TYPE, "identity": {"match_on": ["email"]}}

        assert _propose_merges(store, _Config(True), "Customer", deterministic_only, ROWS) == 0

    def test_the_deployment_default_is_OFF(self, synced_deployment):
        """A deployment that says nothing infers nothing."""
        from core.deployment_loader import load_deployment

        assert load_deployment(synced_deployment.config_dir).identity_inference is False


class TestProposingIsNotDeciding:
    def test_a_proposal_is_stored_pending_however_high_the_score(self, store, matcher):
        matcher(_Matcher([Candidate("primary:c1", "primary:c2", 1.0)]))

        _propose_merges(store, _Config(True), "Customer", TYPE, ROWS)

        assert store.approved_pairs("Customer") == []

    def test_proposing_the_same_pair_twice_adds_nothing(self, store, matcher):
        """A nightly sync re-proposing yesterday's candidate must not
        fill the queue with duplicates of a decision already made."""
        matcher(_Matcher([Candidate("primary:c1", "primary:c2", 0.99)]))
        _propose_merges(store, _Config(True), "Customer", TYPE, ROWS)

        second = _propose_merges(store, _Config(True), "Customer", TYPE, ROWS)

        assert second == 0 and len(store.proposals("Customer")) == 1

    def test_a_decided_proposal_is_not_re_proposed(self, store, matcher):
        matcher(_Matcher([Candidate("primary:c1", "primary:c2", 0.99)]))
        _propose_merges(store, _Config(True), "Customer", TYPE, ROWS)
        store.decide(store.proposals("Customer")[0].proposal_id, APPROVED, "alice")

        _propose_merges(store, _Config(True), "Customer", TYPE, ROWS)

        assert len(store.proposals("Customer")) == 1
        assert store.proposals("Customer")[0].decision == APPROVED

    def test_the_explanation_is_stored_with_the_proposal(self, store, matcher):
        """A reviewer needs to know which fields agreed, not a number."""
        matcher(_Matcher([Candidate("primary:c1", "primary:c2", 0.99,
                                     agreement={"name": True, "region": False})]))

        _propose_merges(store, _Config(True), "Customer", TYPE, ROWS)

        assert '"name": true' in store.proposals("Customer")[0].agreement


class TestFailuresNeverBreakTheSync:
    def test_a_missing_extra_is_reported_and_survived(self, store, matcher, capsys):
        from core.mirror.matching import SplinkNotInstalled
        matcher(_Matcher(raises=SplinkNotInstalled()))

        proposed = _propose_merges(store, _Config(True), "Customer", TYPE, ROWS)

        assert proposed == 0
        assert "merges could not be proposed" in capsys.readouterr().err

    def test_a_backend_that_throws_is_survived_too(self, store, matcher, capsys):
        matcher(_Matcher(raises=RuntimeError("duckdb fell over")))

        assert _propose_merges(store, _Config(True), "Customer", TYPE, ROWS) == 0
        assert "duckdb fell over" in capsys.readouterr().err


class TestTheSyncReadsDecisions:
    """WRITTEN BECAUSE A CONTROL PROVED NOTHING: the earlier tests cover
    resolve() honouring approved pairs, and _propose_merges storing
    them -- but nothing covered the SYNC reading the store and handing
    it to the build, which is the join between the two halves."""

    def test_an_approved_merge_reaches_the_gold_build(self, tmp_path, synced_deployment):
        import shutil

        import yaml

        from core.deployment_loader import RuntimePaths
        from core.mirror.iceberg_sync import IcebergMirrorSync
        from scripts.run_sync import run_sync

        config_dir = tmp_path / "etc"
        shutil.copytree(synced_deployment.config_dir, config_dir)
        schema = yaml.safe_load((config_dir / "ontology_schema.yaml").read_text())
        types = schema.get("object_types", schema)
        types["Customer"]["identity"] = {"match_on": ["email"]}
        (config_dir / "ontology_schema.yaml").write_text(yaml.safe_dump(schema, sort_keys=False))
        data_dir = tmp_path / "data"
        log_dir = tmp_path / "log"
        shutil.copytree(synced_deployment.data_dir, data_dir)
        log_dir.mkdir()
        paths = RuntimePaths(config_dir=config_dir, data_dir=data_dir, log_dir=log_dir)
        run_sync(paths)
        catalog = IcebergMirrorSync(data_dir / "mirror", {})._catalog
        before = catalog.load_table("gold.Customer").scan().to_arrow().num_rows
        store = MergeDecisionStore(data_dir / "identity_decisions.db")
        rows = catalog.load_table("gold.Customer").scan().to_arrow().to_pylist()
        first, second = sorted(row["customer_id"] for row in rows)[:2]

        store.decide(store.propose("Customer", f"primary:{first}", f"primary:{second}", 1.0),
                      APPROVED, "alice")
        run_sync(paths)

        after = catalog.load_table("gold.Customer").scan().to_arrow().num_rows
        assert after == before - 1, "the approved merge did not reach the build"


class TestFrozenConfiguration:
    def test_a_rule_survives_the_loader_freezing_it(self):
        """FOUND BY RUNNING THE PIPELINE, not by a unit test: the
        loader deep-freezes the schema, so a mapping arrives as a
        mappingproxy and a list as a TUPLE. Checking for dict and list
        rejected every real deployment while passing every test that
        built its schema by hand."""
        from core.immutable import deep_freeze
        from core.mirror.identity import rule_for
        from core.mirror.matching import settings_for

        frozen = deep_freeze(TYPE)

        assert rule_for(frozen).match_on == ("email",)
        assert settings_for(frozen).compare == ("name",)
