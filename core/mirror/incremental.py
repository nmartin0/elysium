"""Reading only what changed since the last sync (R2).

    # data_silos.yaml
    data_silos:
      primary_sql:
        adapter: sqlite
        connection: {path: ...}
        incremental:
          transactions:
            cursor: updated_at        # a column the source moves on every change
            full_read_every: 7d       # default 7d; catches deletions
            lookback: 5m              # default 0; timestamp cursors only

WITHOUT THIS every sync reads every row of every table. With it, a
declared table is read `WHERE cursor >= <highest value seen last time>`
and those rows are merged into bronze by id; everything after bronze
(silver, the changelog diff, gold) runs exactly as it does after a full
read, because bronze still holds the whole table.

THE PRECEDENT is the cursor-field incremental sync every ELT tool ships.
Airbyte's documentation states its two properties plainly: an "at least
once" guarantee -- the boundary is INCLUSIVE, so a row sharing the last
cursor value is read again rather than missed, and the merge by id
makes reading it twice harmless -- and that incremental mode "will
never delete" anything. That second one is the catch the owner was
asked about on 13 October:

  A DELETED ROW IS NEVER SEEN by a cursor read; it simply stops
  appearing. So a FULL READ still happens on a schedule
  (`full_read_every`, a week by default), and that read is the one that
  notices deletions -- through the same diff and the same mass-deletion
  guard as any full read. The owner chose this over "changed rows
  only".

WHAT ELSE A CURSOR CANNOT SEE, stated so it is not discovered:

  - a row whose cursor is NULL (it matches no `>=`) -- seen on full
    reads only, and the sync counts and reports them;
  - a change committed AFTER a later one was read, carrying an EARLIER
    cursor value -- PostgreSQL's now() is the transaction's START time,
    so a long transaction can do exactly this. `lookback` re-reads that
    much before the mark; the full read repairs whatever it misses;
  - a change that did not move the cursor (a trigger that forgot, a bulk
    UPDATE that bypassed it). Only the full read sees these.

WHERE THE MARK LIVES: on the bronze table itself, as Iceberg table
properties, beside the source types bronze already records. No second
store to drift from the data it describes, and dropping bronze drops the
mark with it -- which forces the full read that rebuilding needs.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

#: Bronze table properties. The cursor NAME is kept beside its mark so
#: that changing the declared cursor forces a full read rather than
#: comparing one column against another column's value.
CURSOR_PROPERTY = "elysium.incremental.cursor"
MARK_PROPERTY = "elysium.incremental.mark"
FULL_READ_PROPERTY = "elysium.incremental.last_full_read"
#: Which columns arrived as TEXT across every read bronze holds (DEP-1).
#: An incremental read sees only the changed rows, so the answer is
#: carried forward rather than recomputed from them.
TEXT_COLUMNS_PROPERTY = "elysium.source.text_columns"

DEFAULT_FULL_READ_EVERY = timedelta(days=7)
_KEYS = frozenset({"cursor", "full_read_every", "lookback"})
_DURATION = re.compile(r"^\s*(\d+)\s*([smhd])\s*$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


@dataclass(frozen=True)
class IncrementalPolicy:
    cursor: str
    full_read_every: timedelta = DEFAULT_FULL_READ_EVERY
    lookback: timedelta = timedelta(0)


def parse_duration(value, where: str) -> timedelta:
    """`30s`, `5m`, `12h`, `7d`. A bare number is refused: seconds or
    days, nobody reading the file could tell."""
    match = _DURATION.match(str(value)) if isinstance(value, str) else None
    if match is None:
        raise ValueError(f"{where} must be a duration such as 30s, 5m, 12h or 7d, got {value!r}.")
    return timedelta(**{_UNITS[match.group(2)]: int(match.group(1))})


def incremental_policies(silos: dict, known_tables: "set[tuple[str, str]] | None" = None) -> dict:
    """{(silo, table): IncrementalPolicy} from data_silos.yaml.

    A TABLE NAME THE SYNC DOES NOT READ IS REFUSED when `known_tables`
    is given: a typo would otherwise leave that table quietly on full
    reads, which is the cost this exists to remove."""
    policies = {}
    for silo_name, silo in (silos or {}).items():
        declared = (silo or {}).get("incremental")
        if declared is None:
            continue
        where = f"data_silos.yaml {silo_name}.incremental"
        if not hasattr(declared, "items"):
            raise ValueError(f"{where} must map table names to {{cursor: column}}.")
        for table_name, entry in declared.items():
            here = f"{where}.{table_name}"
            if not hasattr(entry, "get"):
                raise ValueError(f"{here} must be a mapping with at least `cursor`.")
            unknown = sorted(set(entry) - _KEYS)
            if unknown:
                raise ValueError(f"{here}: unknown key(s) {unknown}; known: {sorted(_KEYS)}.")
            cursor = entry.get("cursor")
            if not isinstance(cursor, str) or not cursor.strip():
                raise ValueError(f"{here}.cursor must name the column the source moves on "
                                 f"every change, such as updated_at.")
            full_every = (parse_duration(entry["full_read_every"], f"{here}.full_read_every")
                          if "full_read_every" in entry else DEFAULT_FULL_READ_EVERY)
            if full_every <= timedelta(0):
                raise ValueError(f"{here}.full_read_every must be longer than zero: a full "
                                 f"read is what notices deletions.")
            lookback = (parse_duration(entry["lookback"], f"{here}.lookback")
                        if "lookback" in entry else timedelta(0))
            if known_tables is not None and (silo_name, table_name) not in known_tables:
                tables = sorted(table for silo, table in known_tables if silo == silo_name)
                raise ValueError(f"{here}: the sync reads no table {table_name!r} from "
                                 f"{silo_name}; it reads {tables}.")
            policies[(silo_name, table_name)] = IncrementalPolicy(cursor, full_every, lookback)
    return policies


# -- the mark, kept with its type -----------------------------------------
#
# A MARK MUST GO BACK TO THE SOURCE AS THE TYPE IT CAME OUT AS. A
# timestamp compared against its own string form works in some
# databases and fails or mis-sorts in others; an integer compared as
# text puts 10 before 9. So the type travels with the value.

def encode_mark(value) -> "str | None":
    if isinstance(value, bool):
        return None  # a boolean cursor moves twice in its life; not a cursor
    if isinstance(value, datetime):
        return json.dumps({"type": "datetime", "value": value.isoformat()})
    if isinstance(value, date):
        return json.dumps({"type": "date", "value": value.isoformat()})
    if isinstance(value, int):
        return json.dumps({"type": "int", "value": value})
    if isinstance(value, Decimal):
        return json.dumps({"type": "decimal", "value": str(value)})
    if isinstance(value, float):
        return json.dumps({"type": "float", "value": value})
    if isinstance(value, str):
        return json.dumps({"type": "str", "value": value})
    return None


def decode_mark(text: "str | None"):
    if not text:
        return None
    try:
        mark = json.loads(text)
        kind, value = mark["type"], mark["value"]
    except (ValueError, KeyError, TypeError):
        return None
    decoders: dict[str, Callable[[Any], Any]] = {
        "datetime": datetime.fromisoformat, "date": date.fromisoformat, "int": int,
        "decimal": Decimal, "float": float, "str": str,
    }
    decoder = decoders.get(kind)
    return decoder(value) if decoder is not None else None


def read_from(mark, lookback: timedelta):
    """Where the next read starts: the mark itself (inclusive), less the
    lookback for a timestamp cursor. A lookback on any other kind of
    cursor is meaningless and ignored -- the loader cannot know the
    column's type, so this is where it is decided."""
    if lookback and isinstance(mark, datetime):
        return mark - lookback
    return mark


def higher(current, candidate):
    """The larger of two cursor values, None and incomparable values
    ignored -- a mixed-type column has no single mark, and the full read
    is what covers it."""
    if candidate is None or isinstance(candidate, bool):
        return current
    if current is None:
        return candidate
    try:
        return candidate if candidate > current else current
    except TypeError:
        return current


def full_read_reason(policy: "IncrementalPolicy | None", properties, now: datetime,
                     columns, force: bool = False) -> "str | None":
    """Why this sync must read the whole table, or None to read changes.

    Every reason is one where a changed-rows read would be WRONG, not
    merely slower -- each answer is printed, so an operator can see why
    a table they declared incremental read everything."""
    if policy is None:
        return "not declared incremental"
    if force:
        return "a full read was asked for"
    if policy.cursor not in columns:
        return f"the source has no column {policy.cursor!r}"
    if properties is None:
        return "first sync"
    if properties.get(CURSOR_PROPERTY) is None:
        return "first read since it was declared incremental"
    if properties.get(CURSOR_PROPERTY) != policy.cursor:
        return "the cursor column changed"
    if decode_mark(properties.get(MARK_PROPERTY)) is None:
        return "no mark recorded yet"
    try:
        last_full = datetime.fromisoformat(properties.get(FULL_READ_PROPERTY) or "")
    except ValueError:
        return "no full read recorded yet"
    if now - last_full >= policy.full_read_every:
        return f"scheduled ({describe_span(policy.full_read_every)} since the last full read)"
    return None


def describe_span(span: timedelta) -> str:
    """7 days, 12 hours, 5 minutes, 30 seconds -- the largest unit that
    divides it, which is the unit it was very likely declared in."""
    seconds = int(span.total_seconds())
    for size, unit in ((86_400, "day"), (3_600, "hour"), (60, "minute"), (1, "second")):
        if seconds and seconds % size == 0:
            count = seconds // size
            return f"{count} {unit}{'s' * (count != 1)}"
    return "0 seconds"


def now_utc() -> datetime:
    return datetime.now(UTC)
