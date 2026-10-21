"""
apps.py  (the rail entries backing GET /me/visible-apps)

FROM THE MODULES, since 21 October (BLOCKING.md item 3): each sub-app's
`module.json` declares its rail entry and the permission a person needs
to be offered it, and core/modules.py loads them. This file only turns
them into the rail's {name, path, subject} entries, in subject order --
the shell's own feed (GET /api/shell/modules) carries the same modules
in the contract's shape.

A permission of None is "every signed-in person", NOT "no check at
all": the route still requires a session.

Used by: api/routes.py's my_visible_apps_route() and the help assistant.
"""

from core.intermediate_layer.auth import UserRecord
from core.modules import Modules, feed_for

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
#:              ARRIVED, not something being explored". One entry with
#:              a tab each, and every row a DOOR into its subject.
#:   SETTINGS   "the system's own configuration, visited rarely, and
#:              fine where it is."
SUBJECTS: tuple[str, ...] = ("Objects", "Ontology", "Inbox", "Settings")

# THE APPS ARE MODULES NOW (BLOCKING.md item 3, 21 October): each
# sub-app's `module.json` declares its rail entry and its permission, and
# this reads them -- the hand-written list that lived here is gone, so
# there is one declaration of an app rather than two to keep agreeing.


def visible_apps_for(user_record: UserRecord, roles: dict,
                     modules: "Modules | None") -> list[dict[str, str | None]]:
    """The rail entries this person is offered, from the deployment's
    modules (core/modules.py), each {name, path, subject}."""
    if modules is None:
        return []
    feed = feed_for(modules, user_record, roles)
    entries = [{"name": entry["title"], "path": entry["path"], "subject": entry.get("subject")}
               for module in feed["modules"] for entry in module["contributes"].get("nav", [])]
    # ORDERED BY SUBJECT, so the rail groups rather than lists. The
    # order of SUBJECTS is the order a person meets them: the objects
    # they work on, the ontology those objects are instances of, the
    # events that arrived, and the settings they rarely touch. A subject
    # this list does not know goes after them, in the modules' order.
    known = {subject: i for i, subject in enumerate(SUBJECTS)}
    return sorted(entries, key=lambda app: known.get(str(app["subject"]), len(SUBJECTS)))
