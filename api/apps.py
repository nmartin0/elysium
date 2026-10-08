"""
apps.py  (the registry backing GET /me/visible-apps)

A small, static, hand-authored list -- deliberately NOT computed by
scanning ui/src/ or anything else automatic. Every entry is a real,
independent statement of "this app exists and this is what gates it,"
matching this project's own established discipline of fully explicit
authorization (see README.md's own section 3.5: "nothing is inherited
from anything else").

gating_permission is None for an app available to every logged-in
user with no additional grant required (Query, Browse today) -- NOT
the same as "no check at all." authorize() is never called for a None
entry; the check IS "are you authenticated," already enforced by
get_current_user() on this route like every other one.

"path" exists so the frontend can render a real link -- not something
explicitly requested, but the endpoint is not functionally complete
without it: a nav entry with no URL to point to isn't usable. Kept as
plain, hand-authored data alongside name/gating_permission, not a
separate lookup the frontend maintains independently, which would
risk silently drifting out of sync with this list.

Used by: api/routes.py's my_visible_apps_route()
"""

from core.intermediate_layer.auth import UserRecord, authorize

#: WHAT A PERSON IS WORKING ON, not which feature built the screen.
#:
#: DEV_UI.md 12: "Elysium has six apps -- browse, query, approvals,
#: notifications, schema, admin -- which is a decomposition BY FEATURE,
#: the way software gets built, not BY WHAT THE USER IS WORKING ON.
#: That is why moving between them feels like changing tools rather
#: than changing view."
#:
#: Sorted by subject there are three things, plus two that are not
#: subjects at all:
#:
#:   OBJECTS    instances. Narrow, understand, act. Today this is split
#:              across browse and query, which 12 says should become one
#:              workspace with MODES -- table, graph, chart -- where
#:              switching mode does not lose the set. Not merged yet;
#:              grouped so the rail stops claiming they are unrelated.
#:   ONTOLOGY   types, not instances. "Going from '1,284 customers' to
#:              'the Customer type' is a change of KIND, not of filter."
#:   PIPELINE   the process producing both. Not built.
#:
#:   INBOX      approvals, notifications, merge proposals: "EVENTS THAT
#:              ARRIVED, not something being explored". Every row should
#:              be a DOOR into a subject, which they are not yet.
#:   SETTINGS   "the system's own configuration, visited rarely, and
#:              fine where it is."
SUBJECTS: tuple[str, ...] = ("Objects", "Ontology", "Inbox", "Settings")

VISIBLE_APPS: list[dict[str, str | None]] = [
    {"name": "Browse", "path": "/browse", "subject": "Objects",
     "gating_permission": None},
    {"name": "Query", "path": "/query", "subject": "Objects",
     "gating_permission": None},
    {"name": "Schema", "path": "/schema", "subject": "Ontology",
     "gating_permission": None},
    {"name": "Approvals", "path": "/approvals", "subject": "Inbox",
     "gating_permission": None},
    {"name": "Notifications", "path": "/notifications", "subject": "Inbox",
     "gating_permission": None},
    {"name": "Identity", "path": "/identity", "subject": "Inbox",
     "gating_permission": None},
    {"name": "Admin", "path": "/admin", "subject": "Settings",
     "gating_permission": "manage:users"},
]


def visible_apps_for(user_record: UserRecord, roles: dict) -> list[dict[str, str | None]]:
    # ORDERED BY SUBJECT, so the rail groups rather than lists. The
    # order of SUBJECTS is the order a person meets them: the objects
    # they work on, the ontology those objects are instances of, the
    # events that arrived, and the settings they rarely touch.
    permitted = [
        app for app in VISIBLE_APPS
        if app["gating_permission"] is None
        or authorize(user_record, roles, app["gating_permission"])
    ]
    return sorted(permitted, key=lambda app: SUBJECTS.index(str(app["subject"])))
