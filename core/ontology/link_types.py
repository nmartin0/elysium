"""
link_types.py  (link types as first-class ontology entities)

Foundry's model, adopted directly: a link type is "the schema
definition of a relationship between two object types" -- an entity in
its own right, not an attribute of a field. It names both object
types, their cardinality, and how the relationship is backed.

WHAT THIS REPLACES, and why the old form had to go rather than be
extended. Links were previously declared as field attributes, once per
DIRECTION:

    Customer.transactions: {type: link, target: Transaction, ...}
    Transaction.customer_id: {type: link, target: Customer, ...}

Those two entries describe ONE relationship but were unrelated
declarations. Four real limitations followed:
  - No many-to-many. Both forms assumed a foreign key on the far side,
    so a join table with two foreign keys could not be expressed at
    all.
  - The directions could DRIFT. Changing one silently broke the other,
    with nothing structurally connecting them.
  - No link metadata. Object types and fields got display names in
    Point 10; links got none, so a UI rendered "owner_customer_id".
  - No place for a relationship's own identity or status.

BACKING MECHANISMS, matching Foundry's own two:
  - foreign_key (one-to-one, one-to-many): "a property of one object
    type (the foreign key) refers to the primary key property of the
    other object type".
  - join_table (many-to-many): "a table containing pairs of primary
    keys defines the links between two objects... along with mapping
    these keys".

Foundry's third, object-backed links (a join carrying its own
properties), is deliberately NOT adopted -- see ROADMAP.md. It is
already expressible as two ordinary one-to-many links through a real
object type, which is arguably clearer, and their own documentation
notes that a join table carrying extra information "is no longer a
many-to-many relation but two separate many-to-one relations".

EXPANSION, and why the internal form stays field-shaped. Every read
path -- DataMediator, both adapters, the sync -- already resolves
links from per-field entries, and does so correctly. Rather than
rewrite thirty call sites, expand_link_types() generates those entries
from the link type declarations at load. The AUTHORING surface is
fully replaced; the internal representation is one the code already
handles well.
"""


CARDINALITIES = ("one_to_one", "one_to_many", "many_to_many")


def validate_link_types(link_types: dict, object_types: dict) -> None:
    """Checks every link type against the ontology, at load time."""
    for name, link in (link_types or {}).items():
        _validate_one(name, link, object_types)


def _validate_one(name: str, link: dict, object_types: dict) -> None:
    for side in ("source", "target"):
        if side not in link:
            raise ValueError(f"Link type {name!r}: missing {side!r}.")
        side_def = link[side]
        for key in ("object_type", "api_name"):
            if key not in side_def:
                raise ValueError(f"Link type {name!r}: {side}.{key} is required.")
        if side_def["object_type"] not in object_types:
            raise ValueError(
                f"Link type {name!r}: {side}.object_type {side_def['object_type']!r} is not a "
                f"declared object type -- known types: {sorted(object_types)}."
            )

    cardinality = link.get("cardinality")
    if cardinality not in CARDINALITIES:
        raise ValueError(
            f"Link type {name!r}: cardinality must be one of {list(CARDINALITIES)}, "
            f"got {cardinality!r}."
        )

    if cardinality == "many_to_many":
        join = link.get("join_table")
        if not join:
            raise ValueError(
                f"Link type {name!r}: many_to_many requires a join_table -- Foundry's own "
                f"rule, since neither object can hold the other's key without duplicating rows."
            )
        for key in ("table", "source_column", "target_column"):
            if key not in join:
                raise ValueError(f"Link type {name!r}: join_table.{key} is required.")
        if "foreign_key_column" in link:
            raise ValueError(
                f"Link type {name!r}: many_to_many is backed by a join_table and must not "
                f"declare a foreign_key_column."
            )
    else:
        if "foreign_key_column" not in link:
            raise ValueError(
                f"Link type {name!r}: {cardinality} requires a foreign_key_column -- the "
                f"column on the target's table referencing the source's id."
            )
        if "join_table" in link:
            raise ValueError(
                f"Link type {name!r}: {cardinality} is backed by a foreign key and must not "
                f"declare a join_table."
            )

    # A link's two api_names become fields on their object types, so a
    # collision with a real data field would silently shadow it.
    # Each side's api_name becomes a field on ITS OWN object type --
    # Customer.orders lives on Customer. A first version paired each
    # api_name with the other side's type, which meant the check
    # looked at the wrong object entirely and passed a real collision.
    for side in ("source", "target"):
        owner = link[side]["object_type"]
        api_name = link[side]["api_name"]
        declared = (object_types.get(owner) or {}).get("fields", {})
        if api_name in declared:
            raise ValueError(
                f"Link type {name!r}: {side}.api_name {api_name!r} collides with a field "
                f"already declared on {owner!r}."
            )


def expand_link_types(link_types: dict, object_types: dict) -> dict:
    """Generates the per-field link entries the read paths consume.

    Returns object_types with link fields added. Both directions come
    from ONE declaration, which is the whole point: they can no longer
    drift apart.
    """
    expanded = {name: dict(type_def) for name, type_def in object_types.items()}
    for type_def in expanded.values():
        type_def["fields"] = dict(type_def.get("fields") or {})

    for name, link in (link_types or {}).items():
        source, target = link["source"], link["target"]
        cardinality = link["cardinality"]
        shared = {
            "type": "link",
            "link_type": name,
            "display_name": link.get("display_name"),
            "description": link.get("description"),
        }

        if cardinality == "many_to_many":
            join = link["join_table"]
            # BOTH directions traverse the join table; they differ only
            # in which column is matched and which is returned.
            forward = {
                **shared, "target": target["object_type"], "cardinality": "many",
                "via_table": join["table"], "via_column": join["source_column"],
                "via_target_column": join["target_column"],
            }
            backward = {
                **shared, "target": source["object_type"], "cardinality": "many",
                "via_table": join["table"], "via_column": join["target_column"],
                "via_target_column": join["source_column"],
            }
        else:
            foreign_key = link["foreign_key_column"]
            # The TARGET holds the foreign key, so the source side
            # traverses the target's own table to find matches, and the
            # target side reads its own column directly.
            forward = {
                **shared, "target": target["object_type"],
                "cardinality": "one" if cardinality == "one_to_one" else "many",
                "via_table": (object_types[target["object_type"]]["storage"]["table"]),
                "via_column": foreign_key,
            }
            backward = {
                **shared, "target": source["object_type"], "cardinality": "one",
                "column": foreign_key,
            }

        expanded[source["object_type"]]["fields"][source["api_name"]] = _clean(forward)
        expanded[target["object_type"]]["fields"][target["api_name"]] = _clean(backward)

    return expanded


def _clean(field_info: dict) -> dict:
    """Drops keys whose value is None, so an undeclared display_name
    falls back to humanize() rather than overriding it with null."""
    return {key: value for key, value in field_info.items() if value is not None}
