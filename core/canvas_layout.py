"""Where a person put the ontology's types on the canvas (DEV_UI 14).

PRESENTATION, KEPT APART FROM THE DECLARATION. BPMN 2.0 "separates the
semantic model from its diagrammatic representation", and the payoff is
the one wanted here: "purely visual changes in the diagram, such as
adjusting the layout of elements, have no impact on execution
behaviour". XPDL, which it replaced, kept both in one element -- and
then "it is up to the tool -- or the modeler -- to maintain
consistency". So nothing in this file is read by anything that decides
what a type MEANS, and ontology_schema.yaml never acquires a coordinate
or a grouping.

PER PERSON, decided 14 October. "Two people can hold different views of
the same ontology", which BPMN supports by design.

AND A SHARED STARTING ARRANGEMENT UNDERNEATH IT, asked for by the owner
on 26 October: left alone, two people start from different pictures,
because each is laid out from only the types they may see. A person who
manages the deployment can save the arrangement they are looking at as
the one everybody starts from; it holds positions only, merges into
what is already saved (a manager who sees fewer types than the last one
does not erase theirs), and a person's own moves lie over it. It is
cut to the types each reader may see on the way out, as their own is,
so the gaps in a picture say nothing a name would not.

WHAT IT HOLDS:
  positions   {type: {x, y}} for the types a person has MOVED. A type
              with no entry is placed by the automatic layout; the
              14.1 finding is that a moved node must "stick forever",
              and one never moved must keep following the layout.
  areas       [{name, types}] -- SUBJECT AREAS, "a named subset of
              types, for navigation" (ERwin's subject areas, 14.4).
              Never a grouping that changes what anything means.

KEPT TO WHAT THE PERSON MAY SEE, both ways. A name they cannot see is
dropped on the way in, so this cannot be used to store a probe; and on
the way out, so a type whose grant was withdrawn is not named back to
them. Dropped, not refused: an error for an invisible type would say
there is one (uniform denial).
"""

import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

#: Generous for a canvas of 120 types and still a bound on what one
#: request may store.
MAX_AREAS = 50
MAX_AREA_NAME = 80
#: Further than anyone drags, and keeps a coordinate an ordinary number.
MAX_COORDINATE = 100_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS canvas_layouts (
    owner_user_id TEXT PRIMARY KEY,
    document TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS canvas_shared (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    document TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL
);
"""


class CanvasLayoutError(ValueError):
    """The layout is not one this endpoint will store."""


def _coordinate(value) -> float:
    # bool is an int in Python, and True is not a coordinate.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanvasLayoutError("a position needs numeric x and y")
    if not math.isfinite(value) or abs(value) > MAX_COORDINATE:
        raise CanvasLayoutError(f"a coordinate must be within ±{MAX_COORDINATE}")
    return float(value)


def clean_layout(document, visible_types) -> dict:
    """The layout as it may be stored or shown to this person.

    Raises CanvasLayoutError for something malformed -- the wrong
    shape, a coordinate that is not a finite number, too many areas.
    Quietly drops every type this person may not see.
    """
    if not isinstance(document, dict):
        raise CanvasLayoutError("a layout is an object")
    visible = set(visible_types)

    positions_in = document.get("positions", {})
    if not isinstance(positions_in, dict):
        raise CanvasLayoutError("positions must be an object keyed by type")
    positions = {}
    for type_name, point in positions_in.items():
        if not isinstance(point, dict):
            raise CanvasLayoutError("a position is {x, y}")
        x, y = _coordinate(point.get("x")), _coordinate(point.get("y"))
        if type_name in visible:
            positions[type_name] = {"x": x, "y": y}

    areas_in = document.get("areas", [])
    if not isinstance(areas_in, list):
        raise CanvasLayoutError("areas must be a list")
    if len(areas_in) > MAX_AREAS:
        raise CanvasLayoutError(f"at most {MAX_AREAS} subject areas")
    areas, names = [], set()
    for area in areas_in:
        if not isinstance(area, dict):
            raise CanvasLayoutError("a subject area is {name, types}")
        name = area.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CanvasLayoutError("a subject area needs a name")
        name = name.strip()
        if len(name) > MAX_AREA_NAME:
            raise CanvasLayoutError(f"a subject area's name is at most {MAX_AREA_NAME} characters")
        # BY NAME, as saved views are: two areas called "Billing" would
        # be one area a person cannot tell apart from the other.
        if name.casefold() in names:
            raise CanvasLayoutError(f"two subject areas are called {name!r}")
        names.add(name.casefold())
        types = area.get("types", [])
        if not isinstance(types, list) or not all(isinstance(t, str) for t in types):
            raise CanvasLayoutError("a subject area's types are a list of names")
        # An area whose every type became invisible is KEPT, empty: the
        # name is the person's own, and losing it because a grant moved
        # would be losing their work for a reason they cannot see.
        areas.append({"name": name, "types": sorted({t for t in types if t in visible})})

    return {"positions": positions, "areas": areas}


class CanvasLayoutStore:
    """One layout per person. There is no call that returns another's."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def get(self, owner_user_id: str) -> dict:
        """Their stored layout, or an empty one. Not yet cleaned against
        what they may see -- the route does that, with their schema."""
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT document FROM canvas_layouts WHERE owner_user_id = ?",
                    (owner_user_id,),
                ).fetchone()
        except Exception as e:  # noqa: BLE001 - a layout is a convenience
            logger.warning("could not read the canvas layout for %s: %s", owner_user_id, e)
            return {}
        if row is None:
            return {}
        try:
            document = json.loads(row["document"])
        except (TypeError, json.JSONDecodeError):
            return {}
        return document if isinstance(document, dict) else {}

    def put(self, owner_user_id: str, document: dict) -> None:
        """Replaces their layout. Raises on a storage failure, so a save
        that did not happen is not reported as one."""
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO canvas_layouts (owner_user_id, document, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(owner_user_id) DO UPDATE SET "
                "document = excluded.document, updated_at = excluded.updated_at",
                (owner_user_id, json.dumps(document), datetime.now(UTC).isoformat()),
            )
            conn.commit()


    def get_shared(self) -> dict:
        """The shared starting positions {type: {x, y}}, not yet cut to
        what a reader may see -- the route does that, with their schema."""
        try:
            with self._connection() as conn:
                row = conn.execute("SELECT document FROM canvas_shared WHERE id = 1").fetchone()
            document = json.loads(row["document"]) if row else {}
        except Exception as e:  # noqa: BLE001 - a layout is a convenience
            logger.warning("could not read the shared canvas layout: %s", e)
            return {}
        return document if isinstance(document, dict) else {}

    def merge_shared(self, positions: dict, user_id: str) -> dict:
        """Saves these positions over the shared ones, keeping the types
        they do not mention. Returns what is now shared."""
        merged = {**self.get_shared(), **positions}
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO canvas_shared (id, document, updated_at, updated_by) VALUES (1, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET document = excluded.document, "
                "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (json.dumps(merged), datetime.now(UTC).isoformat(), user_id),
            )
            conn.commit()
        return merged

    def clear_shared(self) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM canvas_shared WHERE id = 1")
            conn.commit()


def security_chains(schema: dict, visible_schema: dict) -> list[dict]:
    """How each visible type gets its security value, for the canvas's
    security layer (DEV_UI 13.3, 14.5: "SECURITY CHAINS in another
    [visual language] ... the view that would have made F-19 obvious").

    `via` -- the value is borrowed through a link field from another
    type; `field` -- the type carries its own. Only where every name in
    the entry is one this caller may see: a chain through a type or
    field they cannot see is left out rather than half-drawn.

    THE ROUTE GATES THIS ON manage:roles. It is the permission model's
    structure, the same thing the roles editor reveals.
    """
    chains = []
    for type_name, visible_type in sorted(visible_schema.items()):
        security = (schema.get(type_name) or {}).get("security") or {}
        fields = (visible_type or {}).get("fields") or {}
        # `field` FIRST, the order the mediator resolves them in, so the
        # picture can never show a chain the read path does not follow.
        if "field" in security:
            if security["field"] in fields:
                chains.append({"type": type_name, "kind": "field", "field": security["field"]})
        elif "via_field" in security:
            via = security["via_field"]
            target = (fields.get(via) or {}).get("target")
            if via in fields and target in visible_schema:
                chains.append({"type": type_name, "kind": "via", "field": via, "target": target})
    return chains
