"""Lineage as OpenLineage events (R15).

THE SYNCED-DEPLOYMENT TESTS read the file a real sync of the shipped
deployment wrote, so what is checked is what a lineage service would
receive -- not a hand-built event shaped like one.
"""

import json
import uuid

import pytest

from core.mirror.openlineage import (
    COMPLETE,
    FAIL,
    RUN_JOB,
    START,
    LineageEmitter,
    lake_dataset,
    run_uuid,
    validate_lineage_block,
)

#: The keys OpenLineage's RunEvent requires.
REQUIRED = {"eventType", "eventTime", "run", "job", "producer", "schemaURL"}


def _events(paths):
    lines = (paths.log_dir / "lineage.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


class TestWhatASyncEmits:
    def test_every_event_is_a_run_event(self, synced_deployment):
        events = _events(synced_deployment)

        assert events
        for event in events:
            assert REQUIRED <= set(event), event
            assert event["eventType"] in {START, COMPLETE, FAIL}
            uuid.UUID(event["run"]["runId"])  # the spec requires a UUID

    def test_every_job_that_started_finished_with_the_same_run_id(self, synced_deployment):
        started, finished = {}, {}
        for event in _events(synced_deployment):
            side = started if event["eventType"] == START else finished
            side[event["job"]["name"]] = event["run"]["runId"]

        assert started == finished

    def test_the_run_the_tables_and_the_types_are_jobs(self, synced_deployment):
        jobs = {event["job"]["name"] for event in _events(synced_deployment)}

        assert RUN_JOB in jobs
        assert any(job.startswith("sync.") for job in jobs)
        assert "gold.Customer" in jobs

    def test_gold_names_the_silver_it_was_built_from_and_its_fields(self, synced_deployment):
        done = [event for event in _events(synced_deployment)
                if event["job"]["name"] == "gold.Customer" and event["eventType"] == COMPLETE]

        assert len(done) == 1
        assert all(dataset["name"].startswith("silver.") for dataset in done[0]["inputs"])
        (output,) = done[0]["outputs"]
        assert output["name"] == "gold.Customer"
        fields = {field["name"] for field in output["facets"]["schema"]["fields"]}
        assert "email" in fields

    def test_a_table_sync_reads_the_source_and_writes_bronze_and_silver(self, synced_deployment):
        event = next(event for event in _events(synced_deployment)
                     if event["job"]["name"].startswith("sync.")
                     and event["eventType"] == COMPLETE)

        assert event["inputs"][0]["namespace"].startswith("silo://")
        assert [o["name"].split(".")[0] for o in event["outputs"]] == ["bronze", "silver"]

    def test_every_child_names_the_run_as_its_parent(self, synced_deployment):
        events = _events(synced_deployment)
        run_id = next(e["run"]["runId"] for e in events if e["job"]["name"] == RUN_JOB)

        for event in events:
            if event["job"]["name"] != RUN_JOB:
                assert event["run"]["facets"]["parent"]["run"]["runId"] == run_id

    def test_no_connection_detail_leaves_in_an_event(self, synced_deployment):
        """Names, never contents -- an event travels to a service other
        people read. The silos' databases live under the data dir."""
        text = (synced_deployment.log_dir / "lineage.jsonl").read_text()

        assert str(synced_deployment.data_dir) not in text


class TestTheEmitter:
    def test_a_run_id_is_recomputable_from_the_printed_one(self):
        assert run_uuid("ab12cd34", "gold.Customer") == run_uuid("ab12cd34", "gold.Customer")
        assert run_uuid("ab12cd34", "gold.Customer") != run_uuid("ab12cd34", "gold.Account")

    def test_a_configured_url_receives_every_event_with_the_key_from_the_environment(
            self, tmp_path, monkeypatch):
        sent = []
        monkeypatch.setenv("LINEAGE_KEY", "s3cret")
        emitter = LineageEmitter(tmp_path, "r1", url="http://marquez:5000/api/v1/lineage",
                                 api_key_env="LINEAGE_KEY",
                                 post=lambda url, body, headers: sent.append((url, body, headers)))

        emitter.emit(START, "gold.X", outputs=[lake_dataset("elysium", "gold", "X")])

        assert len(sent) == 1
        assert json.loads(sent[0][1])["job"]["name"] == "gold.X"
        assert sent[0][2]["Authorization"] == "Bearer s3cret"

    def test_a_failing_service_warns_once_and_the_file_still_has_everything(
            self, tmp_path, capsys):
        def refuse(url, body, headers):
            raise ConnectionRefusedError("http://user:pw@marquez refused")

        emitter = LineageEmitter(tmp_path, "r1", url="http://marquez", post=refuse)
        emitter.emit(START, "a")
        emitter.emit(COMPLETE, "a")

        err = capsys.readouterr().err
        assert err.count("WARNING") == 1
        assert "pw@" not in err  # the kind, never the message
        assert len((tmp_path / "lineage.jsonl").read_text().splitlines()) == 2

    def test_a_failure_carries_its_message(self, tmp_path):
        event = LineageEmitter(tmp_path, "r1").emit(FAIL, "gold.X", error="audit refused")

        assert event["run"]["facets"]["errorMessage"]["message"] == "audit refused"


class TestTheConfigBlock:
    def test_absent_is_file_only(self):
        assert validate_lineage_block(None) == {}

    @pytest.mark.parametrize("block, says", [
        ({"urll": "http://x"}, "unknown key"),
        ({"url": "marquez:5000"}, "http"),
        ({"namespace": ""}, "namespace"),
        ({"api_key_env": ""}, "environment variable"),
    ])
    def test_a_mistake_is_refused_at_load(self, block, says):
        with pytest.raises(ValueError, match=says):
            validate_lineage_block(block)

    def test_a_url_in_config_yaml_reaches_the_deployment(self, synced_deployment):
        from core.deployment_loader import build_generation

        config = synced_deployment.config_dir / "config.yaml"
        config.write_text(config.read_text()
                          + "\nlineage:\n  url: http://marquez:5000/api/v1/lineage\n")
        generation = build_generation(synced_deployment.config_dir,
                                      synced_deployment.data_dir, synced_deployment.log_dir)

        assert generation.config.lineage["url"] == "http://marquez:5000/api/v1/lineage"
