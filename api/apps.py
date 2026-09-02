"""
apps.py  (the registry backing GET /me/visible-apps)

A small, static, hand-authored list -- deliberately NOT computed by
scanning ui/src/ or anything else automatic. Every entry is a real,
independent statement of "this app exists and this is what gates it,"
matching this project's own established discipline of fully explicit
authorization (see README.md's own section 8.5: "nothing is inherited
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

VISIBLE_APPS: list[dict[str, str | None]] = [
    {"name": "Query", "path": "/query", "gating_permission": None},
    {"name": "Browse", "path": "/browse", "gating_permission": None},
    {"name": "Admin", "path": "/admin", "gating_permission": "manage:users"},
]


def visible_apps_for(user_record: UserRecord, roles: dict) -> list[dict[str, str | None]]:
    return [
        app for app in VISIBLE_APPS
        if app["gating_permission"] is None or authorize(user_record, roles, app["gating_permission"])
    ]
