"""Lineage as OpenLineage events (R15).

NOT core/mirror/lineage.py, which is the per-ROW lineage columns the
sync writes into every table (`_silo`, `_synced_at`...). This is the
per-RUN record of which job read and wrote which table, for tools
outside the deployment.

WHAT IT IS FOR. The lake already knows its own lineage -- a silver
table is read from one source table, a gold table from one or more
silver tables -- but only this project can read that knowledge, and
only by reading code. OpenLineage is the open standard every lineage
tool reads (Marquez, DataHub, OpenMetadata, Atlan, Purview, Egeria):
a run of a job, its START and its COMPLETE or FAIL, and the datasets
it read and wrote. Emitting it lets a deployment's existing catalog
show this mirror beside everything else it tracks, without anyone
writing an integration.

THE SHAPE IS THE SPEC'S RunEvent, nothing added:

    {"eventType": "START" | "COMPLETE" | "FAIL",
     "eventTime": ISO-8601,
     "run":  {"runId": UUID, "facets": {...}},
     "job":  {"namespace": ..., "name": ...},
     "inputs":  [{"namespace": ..., "name": ...}],
     "outputs": [{"namespace": ..., "name": ..., "facets": {...}}],
     "producer": URI, "schemaURL": URI}

THE JOBS, one per thing the sync does that reads one dataset and
writes another:

    elysium.sync                 the whole run, the parent of the rest
    sync.<silo>.<table>          source table -> bronze and silver
    gold.<ObjectType>            silver table(s) -> gold

RUN IDS ARE DERIVED, NOT RANDOM. The spec requires a UUID, the sync's
own run id is eight hex characters printed and grepped for, and START
and COMPLETE must carry the same one. uuid5 of the sync's run id and
the job name gives all three: the same job in the same run always has
the same UUID, and a person holding the printed run id can recompute
it. The child runs name the parent through the spec's `parent` facet,
which is how a lineage UI groups them.

TWO TRANSPORTS, as the owner decided (2026-10-12):

  ALWAYS a file -- one JSON event per line, `lineage.jsonl` in the log
  directory, which is OpenLineage's own file transport. A deployment
  with no lineage service still has the record, and one that adds a
  service later can replay it.

  OPTIONALLY a URL -- `lineage: url:` in config.yaml, POSTed one event
  at a time, which is the HTTP transport Marquez and its peers accept
  at /api/v1/lineage. An API key, when the service needs one, is named
  by ENVIRONMENT VARIABLE (`api_key_env`), never written into the
  YAML: configuration is versioned and diffed, and a secret in it is a
  secret in every backup of it.

NEVER THE SYNC'S VERDICT. Lineage is a description of work, not the
work. A service that is down, slow or refusing costs a WARNING line
and the event stays in the file; it never fails a table or a type,
and it cannot delay a sync by more than its timeout per event.
"""

import json
import os
import sys
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

START = "START"
COMPLETE = "COMPLETE"
FAIL = "FAIL"

#: The spec version these events are written against.
SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
#: WHO WROTE THE EVENT. The spec wants a URI and suggests a git URL; a
#: URN says "this software" without publishing where its source lives
#: to every lineage service a deployment points at.
PRODUCER = "urn:elysium:sync"
_PARENT_FACET = "https://openlineage.io/spec/facets/1-0-1/ParentRunFacet.json#/$defs/ParentRunFacet"
_SCHEMA_FACET = "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json#/$defs/SchemaDatasetFacet"
_ERROR_FACET = ("https://openlineage.io/spec/facets/1-0-1/ErrorMessageRunFacet.json"
                "#/$defs/ErrorMessageRunFacet")

DEFAULT_NAMESPACE = "elysium"
FILE_NAME = "lineage.jsonl"
#: Per event. A sync with forty tables and a dead service waits at most
#: this times the number of events, and then carries on.
HTTP_TIMEOUT_SECONDS = 5.0

#: The job every other job in one run is a child of.
RUN_JOB = "elysium.sync"


@dataclass(frozen=True)
class Dataset:
    """One thing a job read or wrote."""

    namespace: str
    name: str
    #: [(field name, type)] -- written as the spec's schema facet.
    fields: tuple = ()

    def as_event(self) -> dict:
        out: dict = {"namespace": self.namespace, "name": self.name}
        if self.fields:
            out["facets"] = {"schema": {
                "_producer": PRODUCER, "_schemaURL": _SCHEMA_FACET,
                "fields": [{"name": name, "type": kind} for name, kind in self.fields],
            }}
        return out


def source_dataset(silo: str, table: str) -> Dataset:
    """A table in a source system. The namespace names the silo, never
    its connection details, as /config does -- an event may travel to a
    service other people read."""
    return Dataset(f"silo://{silo}", table)


def lake_dataset(namespace: str, layer: str, name: str, fields: tuple = ()) -> Dataset:
    """A table in this deployment's lake: bronze, silver or gold."""
    return Dataset(f"{namespace}://mirror", f"{layer}.{name}", fields)


def run_uuid(run_id: str, job: str) -> str:
    """The same UUID for the same job in the same run, recomputable
    from the printed run id."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"elysium:{run_id}:{job}"))


def gold_fields(object_type: str, schema) -> tuple:
    """The schema facet for a gold table: the columns its data contract
    promises (R16), with their physical types -- one description of
    gold's shape, not two that can disagree."""
    from core.mirror.data_contracts import data_contract

    properties = data_contract(object_type, schema)["schema"][0]["properties"]
    return tuple((prop["name"], prop["physicalType"]) for prop in properties)


class LineageEmitter:
    """Writes every event to the file and, when configured, the URL."""

    def __init__(self, log_dir: Path, run_id: str, namespace: str = DEFAULT_NAMESPACE,
                 url: str | None = None, api_key_env: str | None = None,
                 post=None):
        self.path = Path(log_dir) / FILE_NAME
        self.run_id = run_id
        self.namespace = namespace
        self.url = url
        self.api_key_env = api_key_env
        # INJECTABLE so a test can see what would have been sent
        # without a server; the default is urllib, no dependency.
        self._post = post or _post_json
        # ONE WARNING PER RUN about a failing service, not one per
        # event: forty identical lines bury the rest of the output.
        self._warned = False

    def emit(self, event_type: str, job: str, inputs=(), outputs=(),
             error: str | None = None, parent: bool = True) -> dict:
        run: dict = {"runId": run_uuid(self.run_id, job), "facets": {}}
        if parent and job != RUN_JOB:
            run["facets"]["parent"] = {
                "_producer": PRODUCER, "_schemaURL": _PARENT_FACET,
                "run": {"runId": run_uuid(self.run_id, RUN_JOB)},
                "job": {"namespace": self.namespace, "name": RUN_JOB},
            }
        if error:
            run["facets"]["errorMessage"] = {
                "_producer": PRODUCER, "_schemaURL": _ERROR_FACET,
                "message": error, "programmingLanguage": "python",
            }
        event = {
            "eventType": event_type,
            "eventTime": datetime.now(UTC).isoformat(),
            "run": run,
            "job": {"namespace": self.namespace, "name": job},
            "inputs": [dataset.as_event() for dataset in inputs],
            "outputs": [dataset.as_event() for dataset in outputs],
            "producer": PRODUCER,
            "schemaURL": SCHEMA_URL,
        }
        self._write(event)
        if self.url:
            self._send(event)
        return event

    def _write(self, event: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(event, sort_keys=True) + "\n")
        except OSError as exc:
            self._warn(f"lineage not written to {self.path.name}: {exc}")

    def _send(self, event: dict) -> None:
        if not self.url:
            return
        headers = {"Content-Type": "application/json"}
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        try:
            self._post(self.url, json.dumps(event).encode(), headers)
        except Exception as exc:  # noqa: BLE001 - lineage is never the sync's verdict
            # THE KIND, NOT THE MESSAGE, as the Silos screen reports a
            # failure: a URL error's text can carry the address and a
            # header echo, and this line lands in logs other people read.
            self._warn(f"lineage service did not accept events ({type(exc).__name__}); "
                       f"they are still in {self.path.name}")

    def _warn(self, message: str) -> None:
        if not self._warned:
            print(f"WARNING {message}", file=sys.stderr)
            self._warned = True


def _post_json(url: str, body: bytes, headers: dict) -> None:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310
        response.read()


def validate_lineage_block(block) -> dict:
    """The `lineage:` block of config.yaml, checked at load.

    REFUSED RATHER THAN IGNORED, as freshness refuses an unknown key: a
    misspelt `urll:` silently ignored is lineage nobody receives while
    its author believes otherwise.
    """
    if block is None:
        return {}
    if not hasattr(block, "get"):
        raise ValueError(f"config.yaml lineage: must be a block of settings, not {block!r}.")
    known = {"url", "namespace", "api_key_env"}
    unknown = sorted(set(block) - known)
    if unknown:
        raise ValueError(f"config.yaml lineage: unknown key(s) {unknown}; known: {sorted(known)}.")
    url = block.get("url")
    if url is not None and (not isinstance(url, str) or not url.startswith(("http://", "https://"))):
        raise ValueError(f"config.yaml lineage.url must be an http(s) URL, got {url!r}.")
    namespace = block.get("namespace", DEFAULT_NAMESPACE)
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError(f"config.yaml lineage.namespace must be a name, got {namespace!r}.")
    key_env = block.get("api_key_env")
    if key_env is not None and (not isinstance(key_env, str) or not key_env):
        raise ValueError(f"config.yaml lineage.api_key_env must name an environment variable, "
                         f"got {key_env!r}.")
    return {"url": url, "namespace": namespace, "api_key_env": key_env}
