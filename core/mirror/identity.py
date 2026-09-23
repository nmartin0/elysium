"""Deciding that two rows from different sources are ONE object
(GOLD-6, the deterministic half).

WHAT THIS IS FOR, AND HOW IT DIFFERS FROM GOLD-5. A type spanning two
storages that agree on the object's id is a JOIN, and fusion.py does
it. This is the other case: the customer is `c1` in the billing
database and `9f2a` in the CRM, and the only thing saying they are the
same person is a rule somebody wrote -- "they share an email".

THE DECLARED RULE IS THE PRIMARY PATH, not a fallback
(FUSION_AND_IDENTITY.md): "deterministic, auditable, no inference, no
confidence score", and "THE GOLD LAYER MUST WORK WITH ZERO
INFERENCE". Probabilistic matching, when it lands, only ever ADDS
PROPOSALS to this.

WHAT A RULE SAYS:

    identity:
      match_on: [email]        # the declared key, compared exactly
      primary: primary_sql     # whose id the entity keeps

MATCHED EXACTLY, ON STANDARDISED VALUES. Silver has already trimmed,
collapsed and NFC-normalised these (GOLD-1), so "exactly" here means
after the cleaning a deployment declared -- not after some fuzzy
comparison this module invents. Anything looser is inference, and
inference goes through proposals.

THE ENTITY ID IS DERIVED, NEVER INVENTED. It is the primary source's
id where that source has the row, and `<storage>:<id>` otherwise. A
random id would change on every build, which would make the changelog
(GOLD-4) report the entire population as deleted and recreated every
night.

AND A SECURITY DISAGREEMENT REFUSES THE MERGE (the owner's decision
D2). If two rows that a rule says are one object carry DIFFERENT
values for the field MAC reads, merging them would silently pick who
can see the result. They are left unmerged and reported, which is the
one case this module declines to answer.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IdentityRule:
    """How rows from different sources are known to be one object."""

    match_on: tuple[str, ...]
    primary: Any = None          # the storage key whose id the entity keeps


@dataclass
class Resolution:
    """Who is who, and what could not be decided."""

    # entity id -> {storage key: the row from that storage}
    entities: dict[str, dict[Any, dict]] = field(default_factory=dict)
    # (entity id, the security values that disagreed) for refused merges
    refused: list[tuple[str, dict[Any, Any]]] = field(default_factory=list)

    @property
    def merged_count(self) -> int:
        return sum(1 for rows in self.entities.values() if len(rows) > 1)


def rule_for(type_def: dict) -> IdentityRule | None:
    """The declared rule, or None when a type declares none.

    Raises on a rule that cannot work, rather than resolving nothing
    quietly: a match_on naming a field the type does not have would
    match every row against every other on a missing value.
    """
    declared = type_def.get("identity")
    if not declared:
        return None
    if not isinstance(declared, dict):
        raise ValueError(f"identity must be a mapping, got {declared!r}.")
    match_on = declared.get("match_on")
    if not match_on or not isinstance(match_on, list):
        raise ValueError("identity.match_on must be a non-empty list of field names.")
    fields = type_def.get("fields") or {}
    unknown = [name for name in match_on if name not in fields]
    if unknown:
        raise ValueError(
            f"identity.match_on names field(s) this type does not have: {unknown}."
        )
    unknown_keys = set(declared) - {"match_on", "primary"}
    if unknown_keys:
        raise ValueError(f"unknown identity key(s) {sorted(unknown_keys)}.")
    return IdentityRule(match_on=tuple(match_on), primary=declared.get("primary"))


def _value_of(row: dict, field_name: str, type_def: dict, storage_key: Any) -> Any:
    """One field's value from a source row, by the column that storage
    calls it."""
    field_config = (type_def.get("fields") or {}).get(field_name) or {}
    if field_config.get("storage", None) not in (storage_key, None):
        return None
    return row.get(field_config.get("column", field_name))


def _match_key(row: dict, rule: IdentityRule, type_def: dict, storage_key: Any):
    """The declared key's value, or None when any part is missing.

    A PARTIAL KEY MATCHES NOTHING. Two customers who both lack an email
    are not the same customer, and treating a missing value as equal is
    how identity resolution merges a whole population into one object.
    """
    values = []
    for field_name in rule.match_on:
        value = _value_of(row, field_name, type_def, storage_key)
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        values.append(str(value))
    return tuple(values)


def _entity_id(storage_key: Any, row: dict, storage: dict, primary: Any) -> str:
    object_id = row.get(storage["id_column"])
    if storage_key == primary or primary is None and storage_key is None:
        return str(object_id)
    return f"{storage_key}:{object_id}"


def _source_qualified(storage_key: Any, row: dict, storage: dict) -> str:
    """How a matcher and an approved decision name this row.

    Always `<source>:<id>`, including for the primary storage, because
    a proposal must say WHICH source it means -- unlike an entity id,
    which is the answer rather than the question.
    """
    prefix = "primary" if storage_key is None else str(storage_key)
    return f"{prefix}:{row.get(storage['id_column'])}"


def _union(groups: list[list], pairs: list[tuple[str, str]], name_of) -> list[list]:
    """Groups joined wherever an approved pair spans two of them.

    AFTER the rule has grouped, not during it: an approval says these
    two ROWS are one object, which means every row already grouped with
    either of them comes too. Doing it inside the keying would merge
    only the pair and leave their rule-mates behind.
    """
    if not pairs:
        return groups
    index = {}
    for position, members in enumerate(groups):
        for member in members:
            index[name_of(member)] = position
    parent = list(range(len(groups)))

    def root(position: int) -> int:
        while parent[position] != position:
            parent[position] = parent[parent[position]]
            position = parent[position]
        return position

    for left, right in pairs:
        if left in index and right in index:
            left_root, right_root = root(index[left]), root(index[right])
            if left_root != right_root:
                parent[right_root] = left_root

    joined: dict[int, list] = {}
    for position, members in enumerate(groups):
        joined.setdefault(root(position), []).extend(members)
    return list(joined.values())


def resolve(type_def: dict, rows_by_storage: dict[Any, list[dict]],
            rule: IdentityRule | None = None,
            approved_pairs: "list[tuple[str, str]] | None" = None) -> Resolution:
    """Group rows from every storage into entities.

    A row matching nothing is its own entity, which is what makes this
    safe to turn on: a deployment whose rule matches nothing gets
    exactly what it had before.
    """
    if rule is None:
        rule = rule_for(type_def)
    resolution = Resolution()
    if rule is None:
        return resolution

    storages: dict[Any, dict] = {None: type_def["storage"]}
    storages.update(type_def.get("additional_storage") or {})
    security_field = (type_def.get("security") or {}).get("field")

    by_key: dict[Any, list[tuple[Any, dict]]] = {}
    unmatched: list[tuple[Any, dict]] = []
    for storage_key in storages:
        for row in rows_by_storage.get(storage_key) or []:
            key = _match_key(row, rule, type_def, storage_key)
            if key is None:
                unmatched.append((storage_key, row))
            else:
                by_key.setdefault(key, []).append((storage_key, row))

    # AN APPROVED MERGE JOINS GROUPS THE RULE LEFT APART. A row the
    # rule matched nothing on is a group of one here, so an approval
    # can pick it up -- which is the whole point of the inferred half.
    grouped_rows = [[entry] for entry in unmatched] + list(by_key.values())
    unmatched = []
    for members in _union(
        grouped_rows,
        list(approved_pairs or []),
        lambda entry: _source_qualified(entry[0], entry[1], storages[entry[0]]),
    ):
        # THE ENTITY KEEPS THE PRIMARY SOURCE'S ID where the primary
        # source has the row: an id that survives a rule changing is
        # worth more than a tidy one.
        chosen = next((entry for entry in members if entry[0] == rule.primary), members[0])
        entity_id = _entity_id(chosen[0], chosen[1], storages[chosen[0]], rule.primary)

        if security_field is not None and len(members) > 1:
            seen = {}
            for storage_key, row in members:
                value = _value_of(row, security_field, type_def, storage_key)
                if value is not None:
                    seen[storage_key] = value
            if len({str(value) for value in seen.values()}) > 1:
                # D2: REFUSE AND REVIEW. Merging would silently decide
                # who can see the result.
                resolution.refused.append((entity_id, seen))
                for storage_key, row in members:
                    alone = _entity_id(storage_key, row, storages[storage_key], rule.primary)
                    resolution.entities.setdefault(alone, {})[storage_key] = row
                continue

        grouped = resolution.entities.setdefault(entity_id, {})
        for storage_key, row in members:
            # Two rows from the SAME storage matching one key is a
            # duplicate within that source, which silver's duplicate
            # handling owns (S4). The first is kept here so identity
            # resolution does not silently drop it.
            grouped.setdefault(storage_key, row)

    for storage_key, row in unmatched:
        entity_id = _entity_id(storage_key, row, storages[storage_key], rule.primary)
        resolution.entities.setdefault(entity_id, {})[storage_key] = row
    return resolution
