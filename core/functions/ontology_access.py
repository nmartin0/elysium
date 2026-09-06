"""
ontology_access.py  (the capability a function receives)

A query object bound to ONE caller and restricted to the object types a
function declared. This is what lets a function search the ontology
dynamically without the function author -- or the LLM choosing its
arguments -- being able to reach past the caller's own permissions.

WHY A CAPABILITY RATHER THAN A MEDIATOR. Handing a function the
mediator plus a UserRecord would make every function author
responsible for MAC correctness, and an LLM picks the arguments.
Foundry does not do this either: their own documentation states there
is "no way to get the executing user's ID within a function without
passing it as a parameter" -- function authors cannot write permission
checks because they never learn who is calling. The platform enforces
it beneath them. This class is that platform layer.

TWO INDEPENDENT RESTRICTIONS, both enforced here:
  - The caller's own MAC and RBAC, unchanged. Every method below is a
    thin pass-through to DataMediator, so a function sees exactly what
    the calling user would see reading directly -- never more, and
    with the same audit logging.
  - The DECLARED object types. A function that declared Customer
    cannot read Account, even if the caller could. This is defence in
    depth beyond what Foundry offers: it bounds what a compromised or
    buggy function can reach to what its author said it would.

Deliberately exposes the SAME operations the HTTP surface does --
search, search-around, aggregate, count, read -- rather than a
parallel set. A function should be able to do what a UI can do, and
nothing a UI cannot.
"""

from typing import Any


class OntologyAccess:
    """Read-only ontology access, scoped to one caller and one
    function's declared object types."""

    def __init__(self, mediator, user_record, allowed_object_types: list[str]):
        self._mediator = mediator
        self._user_record = user_record
        self._allowed = set(allowed_object_types)

    def _check(self, object_type: str) -> None:
        # Raises rather than returning empty, unlike the read paths
        # themselves. A function reaching for an undeclared type is an
        # AUTHORING error -- the declaration and the code disagree --
        # not a permission denial, and silently returning nothing would
        # hide the bug behind plausible-looking empty results.
        if object_type not in self._allowed:
            raise ValueError(
                f"This function did not declare {object_type!r} in reads_object_types "
                f"-- declared: {sorted(self._allowed)}"
            )

    def search(self, object_type: str, criteria: dict | None = None) -> list:
        """Ids of matching objects the CALLER can see."""
        self._check(object_type)
        return self._mediator.search_object(self._user_record, object_type, criteria or {})

    def get_object(self, object_type: str, object_id: Any, field_names: list[str]) -> dict:
        """Field values for one object. Ungranted fields come back None,
        exactly as they would for a direct read."""
        self._check(object_type)
        return self._mediator.get_object(self._user_record, object_type, object_id, field_names)

    def count(self, object_type: str, criteria: dict | None = None) -> int:
        self._check(object_type)
        return self._mediator.count_objects(self._user_record, object_type, criteria or {})

    def aggregate(self, object_type: str, aggregate: str, field: str | None = None,
                   group_by: str | None = None, criteria: dict | None = None) -> dict:
        self._check(object_type)
        return self._mediator.aggregate_by_field(
            self._user_record, object_type, criteria or {},
            group_by=group_by, aggregate=aggregate, field_name=field,
        )

    def search_around(self, object_type: str, link_field: str,
                       criteria: dict | None = None) -> list:
        """Follows a link from every matching object. The TARGET type is
        checked too -- traversing a link must not become a way to reach
        a type this function never declared."""
        self._check(object_type)
        target_type = (
            (self._mediator.schema.get(object_type) or {})
            .get("fields", {}).get(link_field, {}).get("target")
        )
        if target_type is not None:
            self._check(target_type)
        return self._mediator.search_around(
            self._user_record, object_type, criteria or {}, link_field
        )
