"""A folder of CSV files as a source (19 October).

    supplier:
      adapter: csv_folder
      connection:
        path: "feeds/supplier"      # relative to the data directory, as SQLite's
        tables:
          sold:
            files: "sold_*.csv"     # which files make this table
            shape: combined         # or: latest
        # encoding: utf-8-sig       # the default; a byte-order mark is optional
        # delimiter: ","
        # null_values: [""]

HOW THE PRECEDENT SHAPED IT, checked with the owner (Fivetran's file
connectors, Airbyte's file-based sources, Foundry's file-based syncs,
BigQuery and Snowflake loads):

  - A PATTERN PICKS THE FILES, and many files make one table -- every tool
    does this.
  - TWO SHAPES, chosen per table, as every tool offers both (Foundry's
    SNAPSHOT and APPEND, BigQuery's WRITE_TRUNCATE and WRITE_APPEND):
      latest    each file is a whole export; only the newest counts, so a
                row deleted at the source leaves Elysium too.
      combined  each file is a slice (the simulator's weekly sales); all
                of them together are the table, and where a record is in
                two files the NEWER FILE WINS -- Fivetran's recommended
                "upsert by primary key". A record that stops appearing
                STAYS: a slice cannot say "deleted" from "not this week",
                and no tool claims to (Airbyte: "Replicate Incremental
                Deletes: No"; Fivetran: a deleted file's data "remains").
  - A BROKEN LINE STOPS THE TABLE, naming the file and line, and the
    mirror keeps its last good copy -- the bulk loaders' default
    (BigQuery: "The default value is 0, which requires that all records
    are valid"; Snowflake COPY: ABORT_STATEMENT). Skipping the line would
    serve a table missing a row nobody was told about.
  - HALF-WRITTEN FILES ARE NOT READ: the convention is write-then-rename
    (Spring Integration's `.writing`, the simulator's `.part`), so
    temporary names are skipped. No tool documents a "minimum age" rule,
    and a delay "does not prove completion" (Files.com), so there is none.
    AND WHAT IT CANNOT CATCH: a file written in place and read mid-write
    can stop inside a row's last value, every row still the header's
    width -- "2;4567,00" read as "2;456". Its last line has no line
    ending, but RFC 4180 lets a sound file end that way too, so it is not
    refused (found running over a simulated world, 20 October;
    BLOCKING.md records the judgement).
  - COMPRESSED FILES ARE READ (20 October), as Fivetran's file connectors
    read CSV "compressed with gzip, zip, bz2, or zstd": a file named
    `.gz` or `.zip` is opened, the pattern matching the archive's own name.
    A zip must hold ONE file -- which of several is "the table" is a
    guess, so more is a broken file, stopping the table like a broken
    line. Found missing by the first run of Elysium over a simulated
    world, whose drops can be zipped.
  - ONE LISTING PER SYNC: inside a consistent read, a table's files are
    listed once, so the columns checked and the rows read come from the
    same files, and a file arriving mid-sync waits for the next one.

EVERY VALUE ARRIVES AS TEXT, as every tool does; the ontology's declared
data_type converts it in silver, and the silo's `locale` and
`excel_dates` apply because CSV columns are text columns.

READ ONLY, and only for the sync. Questions are answered from gold
(GOLD-9), so the per-object methods the mediator once called on a source
are refused with a message rather than half-implemented.
"""

import csv
import fnmatch
import gzip
import io
import os
import zipfile
import zlib
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.ontology.interface import ExternalReadAdapter, StorageUnavailable

SHAPES = ("latest", "combined")
DEFAULT_ENCODING = "utf-8-sig"
#: Names a writer uses while a file is incomplete (write-then-rename), and
#: Excel's lock file. Never read.
TEMPORARY = (".part", ".tmp", ".temp", ".writing", ".partial", ".crdownload", ".filepart")


class BadLine(ValueError):
    """A line that cannot be part of the table: the table's sync stops."""


class CsvFolderAdapter(ExternalReadAdapter):
    max_concurrent_reads = None
    #: Nothing is pushed: the sync reads whole tables, and nothing else
    #: reads a source.
    pushable_operators = frozenset()

    def __init__(self, connection: dict):
        if "path" not in connection:
            raise ValueError("csv_folder: connection.path, the folder, is required.")
        self.folder = Path(connection["path"])
        self.encoding = connection.get("encoding", DEFAULT_ENCODING)
        try:
            "".encode(self.encoding)
        except LookupError as e:
            raise ValueError(f"csv_folder: unknown encoding {self.encoding!r}.") from e
        self.delimiter = connection.get("delimiter", ",")
        if not isinstance(self.delimiter, str) or len(self.delimiter) != 1:
            raise ValueError(f"csv_folder: delimiter must be one character, got {self.delimiter!r}.")
        nulls = connection.get("null_values", [""])
        if not isinstance(nulls, (list, tuple)) or not all(isinstance(n, str) for n in nulls):
            raise ValueError("csv_folder: null_values must be a list of strings.")
        self.null_values = frozenset(nulls)
        tables = connection.get("tables")
        # MAPPINGS, NOT DICTS: the loaded configuration is deep-frozen,
        # so these arrive as read-only mappings -- found on the first run
        # against a real deployment, which a test passing dicts never saw.
        if not isinstance(tables, Mapping) or not tables:
            raise ValueError("csv_folder: connection.tables must name each table and its files.")
        self.tables: dict[str, dict] = {}
        for name, spec in tables.items():
            if not isinstance(spec, Mapping) or not isinstance(spec.get("files"), str):
                raise ValueError(f"csv_folder: table {name!r} needs `files`, a pattern such as "
                                 f"'{name}_*.csv'.")
            if "/" in spec["files"] or "\\" in spec["files"]:
                raise ValueError(f"csv_folder: table {name!r}: `files` is a name pattern within "
                                 f"the folder, not a path.")
            shape = spec.get("shape", "latest")
            if shape not in SHAPES:
                raise ValueError(f"csv_folder: table {name!r}: shape must be one of {SHAPES}, "
                                 f"got {shape!r}.")
            self.tables[name] = {"files": spec["files"], "shape": shape}
        self._pinned: dict[str, list[Path]] | None = None

    # ---- the folder ------------------------------------------------------

    def _spec(self, table_name: str) -> dict:
        spec = self.tables.get(table_name)
        if spec is None:
            raise StorageUnavailable(
                f"csv_folder {self.folder}: no table {table_name!r} is declared under "
                f"connection.tables (declared: {sorted(self.tables)}).")
        return spec

    def _files(self, table_name: str) -> list[Path]:
        """The table's files, oldest first, by modification time then name.

        Inside a consistent read, listed ONCE per table and kept."""
        if self._pinned is not None and table_name in self._pinned:
            return self._pinned[table_name]
        pattern = self._spec(table_name)["files"]
        try:
            entries = list(os.scandir(self.folder))
        except OSError as e:
            raise StorageUnavailable(f"csv_folder {self.folder}: {type(e).__name__}") from e
        chosen = []
        for entry in entries:
            name = entry.name
            if (not entry.is_file() or name.startswith((".", "~$"))
                    or name.lower().endswith(TEMPORARY)
                    or not fnmatch.fnmatchcase(name, pattern)):
                continue
            chosen.append((entry.stat().st_mtime_ns, name, Path(entry.path)))
        files = [path for _, _, path in sorted(chosen)]
        if self._pinned is not None:
            self._pinned[table_name] = files
        return files

    def _in_use(self, table_name: str) -> list[Path]:
        """The files that make the table: the newest, or all of them."""
        files = self._files(table_name)
        if not files:
            raise StorageUnavailable(
                f"csv_folder {self.folder}: no file matches {self._spec(table_name)['files']!r} "
                f"for table {table_name!r}.")
        return files[-1:] if self._spec(table_name)["shape"] == "latest" else files

    @staticmethod
    def _bytes(path: Path) -> bytes:
        """A file's contents, opened if it is compressed."""
        raw = path.read_bytes()
        name = path.name.lower()
        if name.endswith(".gz"):
            try:
                return gzip.decompress(raw)
            except (OSError, EOFError, zlib.error) as e:
                raise BadLine(f"{path.name}: is not a whole gzip file ({e}).") from e
        if name.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    # Hidden entries are not the table: macOS adds
                    # __MACOSX/._<name> to every archive it makes.
                    members = [m for m in archive.infolist() if not m.is_dir()
                               and not m.filename.rsplit("/", 1)[-1].startswith(".")]
                    if len(members) != 1:
                        raise BadLine(
                            f"{path.name}: holds {len(members)} files; an archive is read "
                            f"when it holds one, because which of several is the table "
                            f"would be a guess.")
                    return archive.read(members[0])
            except zipfile.BadZipFile as e:
                raise BadLine(f"{path.name}: is not a whole zip file ({e}).") from e
        return raw

    def _read(self, path: Path) -> tuple[list[str], list[tuple[int, dict]]]:
        """(header, [(line number, row)]) for one file, or BadLine."""
        try:
            text = self._bytes(path).decode(self.encoding)
        except UnicodeDecodeError as e:
            raise BadLine(f"{path.name}: is not {self.encoding} text (byte {e.start}). Set "
                          f"connection.encoding to what the file is written in.") from e
        except OSError as e:
            raise StorageUnavailable(f"csv_folder {path.name}: {type(e).__name__}") from e
        if text.startswith("﻿"):
            text = text[1:]                     # a BOM under an encoding that kept it
        delimiter, skipped = self.delimiter, 0
        first, _, rest = text.partition("\n")
        if first.rstrip("\r").lower().startswith("sep=") and len(first.rstrip("\r")) == 5:
            # EXCEL'S `sep=` LINE names the delimiter and is not the header.
            delimiter, text, skipped = first.rstrip("\r")[4], rest, 1
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        try:
            header = next(reader)
        except StopIteration:
            raise BadLine(f"{path.name}: is empty -- it has no header line.") from None
        except csv.Error as e:
            raise BadLine(f"{path.name}, line {1 + skipped}: {e}") from e
        header = [name.strip() for name in header]
        if len(set(header)) != len(header) or "" in header:
            raise BadLine(f"{path.name}: the header names a column twice, or leaves one "
                          f"unnamed: {header}.")
        rows = []
        try:
            while True:
                # THE LINE A RECORD STARTS ON, not the one it ends on: a
                # quoted value spanning lines was reported at its last line
                # (found in review, 19 October).
                line = reader.line_num + 1 + skipped
                try:
                    record = next(reader)
                except StopIteration:
                    break
                if not record:
                    # A BLANK LINE, as at the end of a file. Not [""]: in a
                    # one-column file that is an empty VALUE, and dropping it
                    # lost a row (found in review).
                    continue
                if len(record) != len(header):
                    raise BadLine(
                        f"{path.name}, line {line}: {len(record)} values where the header "
                        f"names {len(header)}. Nothing from this table was synced, and the "
                        f"mirror still serves its last good copy.")
                rows.append((line, {name: (None if value in self.null_values else value)
                                    for name, value in zip(header, record, strict=True)}))
        except csv.Error as e:
            raise BadLine(f"{path.name}, line {line}: {e}") from e
        return header, rows

    def _rows(self, table_name: str, id_column: "str | None") -> list[dict]:
        files = self._in_use(table_name)
        if self._spec(table_name)["shape"] == "latest" or id_column is None:
            return [row for path in files for _, row in self._read(path)[1]]
        # COMBINED: the newest file holding a record decides it. Within ONE
        # file every line is kept, so a duplicate id there reaches the
        # sync's own duplicate guard rather than being chosen between here.
        newest: dict[Any, list[dict]] = {}
        no_id: list[dict] = []
        for path in files:
            this_file: dict[Any, list[dict]] = {}
            for _, row in self._read(path)[1]:
                key = row.get(id_column)
                if key is None:
                    no_id.append(row)
                else:
                    this_file.setdefault(key, []).append(row)
            newest.update(this_file)
        return [row for rows in newest.values() for row in rows] + no_id

    # ---- what the sync calls --------------------------------------------

    @contextmanager
    def consistent_read(self):
        """One listing of each table's files for the whole sync: yields True."""
        if self._pinned is not None:
            yield True
            return
        self._pinned = {}
        try:
            yield True
        finally:
            self._pinned = None

    def health_check(self) -> None:
        if not self.folder.is_dir():
            raise FileNotFoundError(f"csv_folder: {self.folder} is not a folder")
        os.scandir(self.folder).close()

    def columns_present(self, table_name: str) -> set[str]:
        """The NEWEST file's header: the table's shape now. Older files of a
        combined table may lack a column added since; their rows read it
        as empty."""
        return set(self._read(self._in_use(table_name)[-1])[0])

    def source_column_types(self, table_name: str) -> dict[str, str]:
        return {}                               # a CSV says nothing about types

    def read_all_rows(self, table_name: str, columns: list[str], type_config: dict) -> list[dict]:
        id_column = (type_config.get("storage") or {}).get("id_column")
        return [{name: row.get(name) for name in columns}
                for row in self._rows(table_name, id_column)]

    def iter_all_rows(self, table_name: str, columns: list[str], type_config: dict,
                      batch_size: int = 50_000):
        rows = self.read_all_rows(table_name, columns, type_config)
        for start in range(0, len(rows), batch_size):
            yield rows[start:start + batch_size]

    # ---- not called on a source since GOLD-9 ----------------------------

    def _gold_only(self, *_args, **_kwargs):
        raise NotImplementedError(
            "csv_folder is read only by the sync; questions are answered from gold.")

    find_ids = _gold_only
    find_ids_matching_text = _gold_only
    get_raw_field = _gold_only
    resolve_reverse_links_batch = _gold_only
    read_fields_for_ids = _gold_only
    resolve_reverse_link = _gold_only
