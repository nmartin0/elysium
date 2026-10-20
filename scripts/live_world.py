"""Run Elysium over a simulated world, and say where the two disagree.

BLOCKING.md, "Make the simulator's sources behave like real ones, then
run Elysium over it", step 3. The simulator (sim/) operates real
PostgreSQL, MariaDB, SQLite, CSV-folder and REST sources for a simulated
business; this points an ordinary Elysium deployment at one, syncs it
while time passes, and checks what a reader is served.

FROM THE OUTSIDE, ON BOTH SIDES. The world is started as a separate
process with the command an operator would type and steered only through
its control channel (`control.json`); the deployment is configured only
from `connections.json`, the file a consumer is meant to configure itself
from, plus the pack's declared schema -- what an operator would know
about their own business's tables. Nothing here imports `simulator`,
and the simulator does not know Elysium exists (sim/AGENTS.md).

EACH ROUND: the world stands still (a world started without --follow
only moves when told to), Elysium syncs, and every object type is read
through the mediator as a user with read access to all of it. That is
compared with an INDEPENDENT PLAIN READER of the same source at the same
moment -- SQL through the reader account, the API drained page by page,
the CSV files parsed with their declared encoding. Then the world is
advanced and the round repeats.

WHAT COUNTS AS AGREEMENT is Elysium's own promise, stated in
tests/unit/test_a_source_changes_and_what_a_reader_sees.py: a source
change never makes a reader see a wrong value. A table that synced must
serve what the source holds; one whose sync was refused or failed must
serve exactly what it served before (the last good data). Anything else
-- a missing row, an extra one, a different value, stale data with no
refusal -- is a disagreement, and a bug on one side or the other.

    python -m scripts.live_world sim/packs/field_service.yaml \\
        --work /home/sim/live --rounds 5 --realism

Runs as a user that is not root: the simulator starts PostgreSQL itself,
and PostgreSQL refuses to run as root.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import fnmatch
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

REPOSITORY = Path(__file__).resolve().parent.parent
SIMULATOR = REPOSITORY / "sim"

#: Each kind's realism options (sim/docs/REAL_SOURCES.md, step 2), all at
#: once: the point of step 3 is a world misbehaving the way real ones do.
#: Rates are high enough to be met in a few rounds.
REALISM: dict[str, dict] = {
    "postgresql": {"reader_statement_timeout_ms": 30000,
                   "reader_idle_session_timeout_ms": 20000},
    "mariadb": {"reader_wait_timeout_seconds": 20, "reader_max_statement_seconds": 30,
                "zero_dates": True},
    "rest": {"token_lifetime_seconds": 1800, "fault_rate": 0.1, "latency_ms": 20,
             "latency_jitter_ms": 10},
    "filedrop": {"encoding": "cp1252", "delimiter": ";", "decimal_comma": True,
                 "reorder_columns": True, "duplicate_rate": 0.3, "late_rate": 0.3,
                 "late_seconds": 43200, "atomic_writes": False},
}

#: The pack's column types, as the ontology declares them.
DATA_TYPES = {"text": "string", "integer": "integer", "bigint": "integer",
              "decimal": "decimal", "boolean": "boolean", "date": "date",
              "timestamp": "timestamptz"}

ROLE = "live_reader"


# -- the pack -------------------------------------------------------------

def overlay(pack: Path, out: Path, realism: bool, extra: dict | None = None,
            kinds: dict | None = None, migrations: list | None = None) -> Path:
    """The pack with each silo's realism options switched on; `kinds`
    runs a silo as another kind of database (no pack declares SQLite),
    and `migrations` adds to the pack's own timeline of schema changes."""
    spec = yaml.safe_load(pack.read_text())
    for name, kind in (kinds or {}).items():
        if name not in spec["silos"]:
            raise SystemExit(f"--kind {name}={kind}: the pack has no silo {name!r}; "
                             f"it has {sorted(spec['silos'])}")
        spec["silos"][name]["kind"] = kind
        if kind == "sqlite":
            spec["silos"][name].pop("database", None)      # one file, no databases
    if migrations:
        spec["migrations"] = [*(spec.get("migrations") or []), *migrations]
    for silo in (spec.get("silos") or {}).values():
        options = dict(silo.get("options") or {})
        if realism:
            options.update(REALISM.get(silo["kind"], {}))
        options.update((extra or {}).get(silo["kind"], {}))
        if options:
            silo["options"] = options
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(spec, sort_keys=False))
    return out


@dataclass
class Table:
    """One table an operator would point Elysium at."""
    silo: str
    name: str
    columns: dict[str, str]          # column -> pack type
    id_column: str
    # Files: the pattern that picks them. API: the collection.
    files: str | None = None
    collection: str | None = None

    @property
    def object_type(self) -> str:
        return "".join(part.title() for part in f"{self.silo}_{self.name}".split("_"))


def tables_of(spec: dict) -> list[Table]:
    """Every table in the world: the SQL silos' schemas (a replica's are
    its source's), and what the pack's events publish to files and API."""
    silos, schemas = spec["silos"], spec.get("schemas") or {}
    found: list[Table] = []

    def columns_of(silo: str, table: str) -> dict[str, str]:
        return {name: column["type"]
                for name, column in schemas[silo]["tables"][table]["columns"].items()}

    def key_of(silo: str, table: str) -> str:
        return next(name for name, column in schemas[silo]["tables"][table]["columns"].items()
                    if column.get("primary_key"))

    for name, silo in silos.items():
        source = silo.get("replicates") or name
        if silo["kind"] in ("postgresql", "mariadb", "sqlite") and source in schemas:
            for table in schemas[source]["tables"]:
                found.append(Table(name, table, columns_of(source, table),
                                   key_of(source, table)))
    for event in (spec.get("events") or {}).values():
        for emit in event.get("emits") or []:
            target = emit.get("publish") or emit.get("expose")
            if not target:
                continue
            source_silo, source_table = emit["rows_from"].split(".")
            all_columns = columns_of(source_silo, source_table)
            chosen = {c: all_columns[c] for c in emit.get("columns") or all_columns}
            key = key_of(source_silo, source_table)
            if "expose" in emit:
                found.append(Table(target, emit["collection"], chosen, key,
                                   collection=emit["collection"]))
            else:
                pattern = emit["filename"].get("pattern") or emit["filename"].get("value")
                files = re.sub(r"\{[^}]*\}", "*", pattern)
                found.append(Table(target, files.split("*")[0].rstrip("_-") or source_table,
                                   chosen, key, files=files))
    return found


# -- the world ------------------------------------------------------------

class World:
    """A world running in its own process, steered through control.json."""

    def __init__(self, pack: Path, directory: Path, days: int, seed: int):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.log = (directory / "world.log").open("ab")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "simulator", "run", str(pack), "--dir", str(directory),
             "--days", str(days), "--seed", str(seed)],
            cwd=SIMULATOR, stdout=self.log, stderr=subprocess.STDOUT,
            start_new_session=True)
        self._await()

    def _await(self, timeout: float = 900) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"the world stopped; see {self.log.name}")
            with contextlib.suppress(Exception):
                if (self.directory / "control.json").exists() and self.send("status"):
                    return
            time.sleep(2)
        raise RuntimeError(f"the world did not come up; see {self.log.name}")

    def send(self, command: str, **arguments: Any) -> Any:
        found = json.loads((self.directory / "control.json").read_text())
        request = urllib.request.Request(
            f"{found['url']}/control", method="POST",
            data=json.dumps({"command": command, **arguments}).encode(),
            headers={"Authorization": f"Bearer {found['token']}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                return json.loads(response.read())["result"]
        except urllib.error.HTTPError as refused:
            # THE WORLD'S OWN REASON, which a bare "HTTP Error 400" hid.
            raise RuntimeError(f"the world refused {command!r}: "
                               f"{refused.read().decode(errors='replace')[:500]}") from None

    @property
    def connections(self) -> dict:
        return json.loads((self.directory / "connections.json").read_text())["silos"]

    def close(self) -> None:
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGINT)
            try:
                self.process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
        self.log.close()


# -- the deployment -------------------------------------------------------

def _env(name: str) -> str:
    return "LIVE_" + re.sub(r"[^A-Z0-9]", "_", name.upper())


def configure(tables: list[Table], connections: dict, config_dir: Path,
              options: dict | None = None) -> dict[str, str]:
    """Write an Elysium deployment for these tables. Returns the
    environment it needs: credentials, which Elysium refuses inline."""
    config_dir.mkdir(parents=True, exist_ok=True)
    env: dict[str, str] = {}
    silos: dict[str, dict] = {}
    for name in sorted({t.silo for t in tables}):
        found = connections[name]
        kind = found["kind"]
        mine = [t for t in tables if t.silo == name]
        if kind in ("postgresql", "mariadb"):
            env[_env(f"{name}_password")] = found["password"]
            driver = "postgresql+psycopg" if kind == "postgresql" else "mariadb+pymysql"
            query = "" if kind == "postgresql" else "?charset=utf8mb4"
            silos[name] = {"adapter": "sqlalchemy", "connection": {
                "url": f"{driver}://{found['user']}:${{{_env(f'{name}_password')}}}"
                       f"@{found['host']}:{found['port']}/{found['database']}{query}"}}
            if kind == "mariadb":
                # What Elysium's refusal of a zero date says to declare, for
                # an application that writes 0000-00-00 meaning "no date".
                silos[name]["zero_dates_as_null"] = True
        elif kind == "sqlite":
            silos[name] = {"adapter": "sqlite", "connection": {"path": found["path"]}}
        elif kind == "filedrop":
            zipped = ".zip" if found.get("format") == "zip" else ""
            connection: dict[str, Any] = {
                "path": found["path"],
                "tables": {t.name: {"files": f"{t.files}{zipped}", "shape": "combined"}
                           for t in mine},
                "encoding": found.get("encoding", "utf-8-sig")}
            if found.get("delimiter"):
                connection["delimiter"] = found["delimiter"]
            silos[name] = {"adapter": "csv_folder", "connection": connection}
            if found.get("delimiter") == ";":
                # A semicolon file is a comma-decimal locale's export.
                silos[name]["locale"] = "de_DE"
            elif (options or {}).get(name, {}).get("excel_conversions"):
                # Saved through US Excel: m/d/yyyy dates. The operator knows
                # who makes the file, and says so.
                silos[name]["locale"] = "en_US"
        elif kind == "rest":
            auth: dict[str, Any]
            if found.get("auth") == "oauth_client_credentials":
                env[_env(f"{name}_secret")] = found["client_secret"]
                auth = {"type": "oauth_client_credentials", "token_url": found["token_url"],
                        "client_id": found["client_id"],
                        "client_secret": f"${{{_env(f'{name}_secret')}}}"}
            elif found.get("auth") == "bearer":
                env[_env(f"{name}_token")] = found["token"]
                auth = {"type": "bearer", "token": f"${{{_env(f'{name}_token')}}}"}
            else:
                auth = {}
            silos[name] = {"adapter": "rest", "connection": {
                "base_url": f"{found['base_url']}/v1",
                **({"auth": auth} if auth else {}),
                "tables": {t.name: {"path": f"/{t.collection}", "records": "data",
                                    "pagination": {"type": "cursor", "cursor_field": "cursor",
                                                   "cursor_param": "cursor"}}
                           for t in mine}}}
    types, grants = {}, []
    for t in tables:
        # MariaDB's DATETIME has no zone, and the world's MariaDB writes
        # UTC: declared so, as Elysium's refusal of the bare type says to.
        zoned = connections[t.silo]["kind"] == "mariadb"
        fields = {c: {"type": "data", "data_type": DATA_TYPES[kind],
                      **({"timezone": "UTC"} if zoned and kind == "timestamp" else {})}
                  for c, kind in t.columns.items() if c != t.id_column}
        types[t.object_type] = {
            "storage": {"silo": t.silo, "table": t.name, "id_column": t.id_column},
            "id_field": t.id_column, "security": "unrestricted", "fields": fields}
        grants += [f"read:{t.object_type}", f"read:{t.object_type}.{t.id_column}",
                   *(f"read:{t.object_type}.{c}" for c in fields)]
    base = REPOSITORY / "tests" / "integration" / "fixtures" / "other_deployment"
    (config_dir / "config.yaml").write_text((base / "config.yaml").read_text())
    (config_dir / "data_silos.yaml").write_text(yaml.safe_dump({"data_silos": silos}))
    (config_dir / "ontology_schema.yaml").write_text(yaml.safe_dump({"object_types": types}))
    (config_dir / "policy.yaml").write_text(yaml.safe_dump({
        "security_attribute": "region", "roles": {ROLE: {"allowed_actions": grants}},
        "users": {}}))
    return env


# -- reading ---------------------------------------------------------------

def canonical(value: Any, kind: str) -> Any:
    """One spelling per value, so the two readers can be compared."""
    if value is None or value == "":
        return None
    if kind == "decimal":
        text = str(value).strip()
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        try:
            return Decimal(text).normalize()
        except InvalidOperation:
            return f"unreadable:{value!r}"
    if kind in ("integer", "bigint"):
        try:
            return int(value)
        except (TypeError, ValueError):
            return f"unreadable:{value!r}"
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        return {"true": True, "t": True, "1": True, "false": False, "f": False,
                "0": False}.get(str(value).strip().lower(), f"unreadable:{value!r}")
    if kind == "date":
        text = str(value)
        if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text):
            return f"{m.group(3)}-{int(m.group(1)):02}-{int(m.group(2)):02}"   # US Excel
        text = text[:10]
        return None if text == "0000-00-00" else text
    if kind == "timestamp":
        if str(value).startswith("0000-00-00"):
            return None                                  # MariaDB's "no date"
        if isinstance(value, dt.datetime):
            moment = value
        else:
            try:
                moment = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return f"unreadable:{value!r}"
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=dt.UTC)       # the world writes UTC
        return moment.astimezone(dt.UTC).isoformat()
    return str(value)


def _rows(table: Table, records: list[dict]) -> dict[str, dict]:
    out = {}
    for record in records:
        key = str(record[table.id_column])
        out[key] = {c: canonical(record.get(c), kind) for c, kind in table.columns.items()
                    if c != table.id_column}
    return out


def read_source(table: Table, found: dict) -> dict[str, dict] | str:
    """What a plain, independent reader gets from the source now; or why
    it cannot read it."""
    try:
        kind = found["kind"]
        if kind == "postgresql":
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(host=found["host"], port=found["port"],
                                 dbname=found["database"], user=found["user"],
                                 password=found["password"], row_factory=dict_row) as conn:
                return _rows(table, conn.execute(f'SELECT * FROM "{table.name}"').fetchall())
        if kind == "mariadb":
            import pymysql

            conn = pymysql.connect(host=found["host"], port=found["port"],
                                   database=found["database"], user=found["user"],
                                   password=found["password"],
                                   cursorclass=pymysql.cursors.DictCursor)
            try:
                with conn.cursor() as cursor:
                    cursor.execute(f"SELECT * FROM `{table.name}`")
                    return _rows(table, list(cursor.fetchall()))
            finally:
                conn.close()
        if kind == "sqlite":
            import sqlite3

            # READ ONLY, as Elysium's own reader opens it.
            conn = sqlite3.connect(f"file:{found['path']}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                return _rows(table, [dict(r) for r in conn.execute(
                    f'SELECT * FROM "{table.name}"').fetchall()])
            finally:
                conn.close()
        if kind == "rest":
            return _rows(table, _drain(found, table.collection or table.name))
        if kind == "filedrop":
            return _read_files(table, found)
    except Unverifiable as why:
        return f"UNVERIFIABLE: {why}"
    except Exception as error:  # noqa: BLE001 -- a refusal is a finding, not a crash
        return f"{type(error).__name__}: {error}"
    return f"no reader for {found['kind']}"


def _drain(found: dict, collection: str) -> list[dict]:
    headers = {}
    if found.get("auth") == "bearer":
        headers["Authorization"] = f"Bearer {found['token']}"
    elif found.get("auth") == "oauth_client_credentials":
        form = urllib.parse.urlencode({"grant_type": "client_credentials",
                                       "client_id": found["client_id"],
                                       "client_secret": found["client_secret"]}).encode()
        token = _retrying(lambda: urllib.request.urlopen(
            urllib.request.Request(found["token_url"], data=form, method="POST"), timeout=30))
        headers["Authorization"] = f"Bearer {json.loads(token)['access_token']}"
    records, cursor = [], None
    while True:
        url = f"{found['base_url']}/v1/{collection}"
        if cursor:
            url += f"?cursor={cursor}"
        page = json.loads(_retrying(lambda u=url: urllib.request.urlopen(
            urllib.request.Request(u, headers=headers), timeout=30)))
        records += page["data"]
        cursor = page.get("cursor")
        if not cursor:
            return records


def _retrying(call, attempts: int = 8) -> bytes:
    for attempt in range(attempts):
        try:
            with call() as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            time.sleep(float(error.headers.get("Retry-After") or 0.2))
    raise AssertionError("unreachable")


class Unverifiable(Exception):
    """The source cannot be read for certain right now."""


def _read_files(table: Table, found: dict) -> dict[str, dict]:
    """Every file the pattern picks, newest last, newer winning -- the
    `combined` shape.

    A FILE ENDING MID-LINE IS BEING WRITTEN: the simulator ends every
    row, so one that stops part-way is a half-written upload. Its rows
    may all have the header's width -- cut inside the last field, "2;4567"
    becomes "2;456" -- so this reader cannot tell its last value from a
    true one (found in review, 20 October). Elysium refuses such a file
    since 21 October; if it ever publishes from one, the round is
    reported as unverifiable rather than as agreement.
    A file whose rows are not all the header's width is skipped."""
    folder = Path(found["path"])
    zipped = found.get("format") == "zip"
    pattern = table.files + (".zip" if zipped else "")
    names = sorted((p for p in folder.iterdir() if fnmatch.fnmatch(p.name, pattern)
                    and p.is_file()), key=lambda p: (p.stat().st_mtime_ns, p.name))
    records: list[dict] = []
    for path in names:
        raw = path.read_bytes()
        if zipped:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                raw = archive.read(archive.namelist()[0])
        if raw and not raw.endswith((b"\n", b"\r")):
            raise Unverifiable(f"{path.name} ends mid-line: it is still being written")
        text = raw.decode(found.get("encoding", "utf-8-sig"))
        rows = list(csv.reader(io.StringIO(text), delimiter=found.get("delimiter", ",")))
        if not rows or any(len(row) != len(rows[0]) for row in rows[1:]):
            continue
        records += [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]
    return _rows(table, records)


def read_elysium(mediator, user, table: Table) -> dict[str, dict]:
    ids = mediator.search_object(user, table.object_type)
    fields = [c for c in table.columns if c != table.id_column]
    out = {}
    for object_id in ids:
        got = mediator.get_object(user, table.object_type, object_id, fields) or {}
        out[str(object_id)] = {c: canonical(got.get(c), table.columns[c]) for c in fields}
    return out


# -- comparing --------------------------------------------------------------

@dataclass
class Finding:
    round: int
    table: str
    what: str

    def __str__(self) -> str:
        return f"round {self.round}  {self.table}: {self.what}"


def differences(served: dict[str, dict], truth: dict[str, dict], limit: int = 3) -> list[str]:
    said = []
    missing = sorted(set(truth) - set(served))
    extra = sorted(set(served) - set(truth))
    if missing:
        said.append(f"{len(missing)} row(s) at the source not served, e.g. {missing[:limit]}")
    if extra:
        said.append(f"{len(extra)} row(s) served that the source does not have, "
                    f"e.g. {extra[:limit]}")
    wrong = [(key, column, served[key][column], truth[key][column])
             for key in sorted(set(served) & set(truth))
             for column in truth[key] if served[key].get(column) != truth[key][column]]
    if wrong:
        columns = sorted({column for _, column, _, _ in wrong})
        key, column, mine, theirs = wrong[0]
        said.append(f"{len(wrong)} value(s) differ in {columns}, e.g. {key}.{column}: "
                    f"served {mine!r}, source {theirs!r}")
    return said


@dataclass
class Outcomes:
    """What one sync said about each table, from its own output."""
    synced: set = field(default_factory=set)       # "silo.table"
    failed: dict = field(default_factory=dict)     # label -> reason
    refused: dict = field(default_factory=dict)    # object type -> reason

    @classmethod
    def parse(cls, text: str) -> Outcomes:
        found = cls()
        for line in text.splitlines():
            line = line.strip()
            if m := re.match(r"synced\s+(\S+?):", line):
                found.synced.add(m.group(1))
            elif m := re.match(r"FAILED\s+(\S+?):\s*(.*)", line):
                found.failed[m.group(1)] = m.group(2)
            elif m := re.match(r"REFUSED\s+gold\.(\S+?):\s*(.*)", line):
                found.refused[m.group(1)] = m.group(2)
        return found

    def stopped(self, table: Table) -> str | None:
        """Why this table kept its last good data, if it did."""
        label = f"{table.silo}.{table.name}"
        for key, reason in self.failed.items():
            if key in (label, table.silo, table.object_type, f"gold.{table.object_type}"):
                return reason
        return self.refused.get(table.object_type)


def oracle_findings(number: int, oracle: dict, tables: list[Table],
                    served: dict[str, dict], stopped: set[str]) -> list[Finding]:
    """The simulator's own watched totals, against Elysium's.

    THE CHECK THE PLAIN READER CANNOT MAKE: it reads through the same
    account Elysium does, so rows that account cannot see -- row-level
    security, a grant taken back -- are missing from both and they agree.
    The oracle is computed by the business itself, as the superuser.
    """
    said = []
    for name, samples in oracle.items():
        m = re.fullmatch(r"(sum|count|min|max)\((\w+)\.(\w+)\.(\w+)\)", name)
        if not m or not samples or not samples[-1].get("ok"):
            continue
        aggregate, silo, table_name, column = m.groups()
        table = next((t for t in tables if (t.silo, t.name) == (silo, table_name)), None)
        if table is None or table.object_type in stopped \
                or table.object_type not in served:
            continue
        rows = served[table.object_type]
        if aggregate == "count":
            mine: Any = Decimal(len(rows))
        else:
            values = [Decimal(str(r.get(column))) for r in rows.values()
                      if r.get(column) is not None]
            mine = (sum(values, Decimal(0)) if aggregate == "sum"
                    else (min(values) if values else None) if aggregate == "min"
                    else (max(values) if values else None))
        theirs = samples[-1]["value"]
        theirs = Decimal(theirs) if theirs is not None else None
        if (mine is None) != (theirs is None) or (mine is not None and mine != theirs):
            said.append(Finding(number, table.object_type,
                                f"{name} is {theirs} by the simulator's oracle, "
                                f"{mine} by what Elysium serves"))
    return said


def sync(paths, env: dict) -> tuple[int, str]:
    from scripts.run_sync import run_sync

    os.environ.update(env)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        failed = run_sync(paths)
    return failed, out.getvalue() + err.getvalue()


def run(pack: Path, work: Path, rounds: int, advance: str, realism: bool, days: int,
        seed: int, extra: dict | None = None, events: dict | None = None,
        report=print, kinds: dict | None = None,
        migrations: list | None = None) -> list[Finding]:
    from core.deployment_loader import RuntimePaths, load_deployment_bundle
    from core.intermediate_layer.auth import UserRecord

    spec_path = overlay(pack, work / "pack.yaml", realism, extra, kinds, migrations)
    spec = yaml.safe_load(spec_path.read_text())
    tables = tables_of(spec)
    findings: list[Finding] = []
    world = World(spec_path, work / "world", days, seed)
    try:
        connections = world.connections
        config_dir, data_dir = work / "config", work / "data"
        (work / "log").mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        env = configure(tables, connections, config_dir,
                        {name: silo.get("options") or {} for name, silo in spec["silos"].items()})
        os.environ.update(env)
        paths = RuntimePaths(config_dir=config_dir, data_dir=data_dir, log_dir=work / "log")
        user = UserRecord(user_id="live", security_value="any", role_name=ROLE)
        last: dict[str, dict] = {}
        for number in range(1, rounds + 1):
            kept: set[str] = set()
            for command, arguments in (events or {}).get(number, []):
                # Before the sync, so this round meets it: what changed
                # upstream since Elysium last looked.
                report(f"round {number}: {command} {json.dumps(arguments)} -> "
                       f"{json.dumps(world.send(command, **arguments))[:160]}")
            clock = world.send("status")["clock"]
            failed, output = sync(paths, env)
            (work / f"sync-{number}.log").write_text(output)
            outcomes = Outcomes.parse(output)
            _, mediator, _ = load_deployment_bundle(config_dir, data_dir)
            report(f"round {number} at {clock}: sync reported {failed} failure(s)")
            for table in tables:
                truth = read_source(table, connections[table.silo])
                stopped = outcomes.stopped(table)
                try:
                    served = read_elysium(mediator, user, table)
                except Exception as error:  # noqa: BLE001
                    # Never published and the sync said why: there is no
                    # last good data to serve. Anything else unreadable is
                    # a finding.
                    if stopped is None or table.object_type in last:
                        findings.append(Finding(number, table.object_type,
                                                f"could not be read: {error}"))
                    else:
                        report(f"  {table.object_type:32} never published: {stopped[:100]}")
                    continue
                if stopped is not None:
                    if served != last.get(table.object_type, {}):
                        findings.append(Finding(number, table.object_type,
                                                f"sync stopped ({stopped[:120]}) but what is "
                                                f"served changed: "
                                                + "; ".join(differences(
                                                    served, last.get(table.object_type, {})))))
                    kept.add(table.object_type)
                    report(f"  {table.object_type:32} kept last good: {stopped[:100]}")
                elif isinstance(truth, str) and truth.startswith("UNVERIFIABLE"):
                    # Elysium published from a source that cannot be told
                    # whole: whatever it serves may be wrong, unseen.
                    findings.append(Finding(number, table.object_type,
                                            f"served {len(served)} rows from a source that "
                                            f"cannot be checked -- {truth[14:]}"))
                    report(f"  {table.object_type:32} UNVERIFIABLE: {truth[14:120]}")
                elif isinstance(truth, str):
                    findings.append(Finding(number, table.object_type,
                                            f"the plain reader cannot read the source "
                                            f"({truth[:120]}), yet the sync reported nothing"))
                else:
                    said = differences(served, truth)
                    findings += [Finding(number, table.object_type, s) for s in said]
                    report(f"  {table.object_type:32} {len(served):6} served  "
                           + ("agrees" if not said else "DISAGREES"))
                last[table.object_type] = served
            found = oracle_findings(number, world.send("oracle"), tables, last, kept)
            findings += found
            for finding in found:
                report(f"  ORACLE {finding.table}: {finding.what}")
            if number < rounds:
                world.send("advance", duration=advance)
    finally:
        world.close()
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pack", type=Path)
    parser.add_argument("--work", type=Path, required=True,
                        help="a directory for the world, the deployment and the logs")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--advance", default="1d", help="simulated time between rounds")
    parser.add_argument("--days", type=int, default=7, help="days simulated before round 1")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--realism", action="store_true",
                        help="switch on every realism option the sources have")
    parser.add_argument("--option", action="append", default=[], metavar="KIND.KEY=JSON",
                        help="one more source option, e.g. filedrop.zipped=true")
    parser.add_argument("--event", action="append", default=[],
                        metavar="ROUND:COMMAND[:JSON]",
                        help="a control command before a round's sync, e.g. "
                             "2:outage:{\"silo\":\"books\"} or "
                             "3:drift:{\"operation\":\"drop_column\",...}")
    parser.add_argument("--kind", action="append", default=[], metavar="SILO=KIND",
                        help="run a silo as another database, e.g. till=sqlite")
    parser.add_argument("--migration", action="append", default=[], metavar="JSON",
                        help="one more scheduled schema change, as a pack writes it, e.g. "
                             "{\"at\":\"9d\",\"operation\":\"rescale_column\",...}")
    arguments = parser.parse_args(argv)
    kinds = dict(kind.split("=", 1) for kind in arguments.kind)
    migrations = [json.loads(m) for m in arguments.migration]
    extra: dict[str, dict] = {}
    for option in arguments.option:
        key, _, value = option.partition("=")
        kind, _, name = key.partition(".")
        extra.setdefault(kind, {})[name] = json.loads(value)
    events: dict[int, list] = {}
    for event in arguments.event:
        number, command, *rest = event.split(":", 2)
        events.setdefault(int(number), []).append(
            (command, json.loads(rest[0]) if rest else {}))
    findings = run(arguments.pack.resolve(), arguments.work.resolve(), arguments.rounds,
                   arguments.advance, arguments.realism, arguments.days, arguments.seed,
                   extra, events, kinds=kinds, migrations=migrations)
    print(f"\n{len(findings)} disagreement(s)")
    for finding in findings:
        print(f"  {finding}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
