"""
lake_names.py  (the names the pipeline gives its own namespaces)

ONE PLACE. The mirror writes layers as catalog namespaces named after
the silo (`bronze_p`, `changelog_p`, `quarantine_p`, `cleaning_p`, and
`p` itself for silver) and a few of its own (`gold`, `gold_history`,
`gold_conflicts`), plus a `_elysium` directory of manifests beside the
tables. A silo called any of them collides with a layer: silver and
gold became the same table, with no error, when a silo was named
`gold`.

These names used to be written out in several places that disagreed:
the loader refused `gold` and `gold_history` but not `gold_conflicts`
or `_elysium`, the integrity check kept its own list, and erasure and
the classification reader spelled them as literals. They all read this
file now, and tests/unit/test_a_silo_may_not_be_named_after_a_layer.py
scans the mirror code for any namespace prefix that is not declared
here.

A leaf module: it imports nothing, so the loader, the ontology layer
and the mirror can all use it.
"""

# Namespaces the pipeline writes for itself, whole.
GOLD_NAMESPACE = "gold"
GOLD_HISTORY_NAMESPACE = "gold_history"
GOLD_CONFLICTS_NAMESPACE = "gold_conflicts"

#: Everything starting with this is a gold layer (history, conflicts).
GOLD_PREFIX = "gold_"

# Where manifests live, under a name no silo can have. Not a catalog
# namespace but a directory in the warehouse root; a silo of the same
# name would be written into it.
MANIFEST_PREFIX = "_elysium"

# Per-silo layer prefixes: `<prefix><silo>` is that silo's namespace.
BRONZE_PREFIX = "bronze_"
CHANGELOG_PREFIX = "changelog_"
QUARANTINE_PREFIX = "quarantine_"
CLEANING_PREFIX = "cleaning_"

#: A silo may not be called one of these.
RESERVED_SILO_NAMES = (
    GOLD_NAMESPACE, GOLD_HISTORY_NAMESPACE, GOLD_CONFLICTS_NAMESPACE, MANIFEST_PREFIX,
)

#: Nor start with one of these (it would share a namespace with another
#: silo's layer).
RESERVED_SILO_PREFIXES = (BRONZE_PREFIX, CHANGELOG_PREFIX, QUARANTINE_PREFIX, CLEANING_PREFIX)

#: Namespaces that hold something other than a copy of a source table:
#: every derived layer. (Bronze is a copy of the source and is not
#: here.) Whole names are compared whole and prefixes as prefixes; the
#: integrity check used to test `startswith("gold")` for all of them,
#: which also took a silo called `goldmine` for a derived layer.
NON_SOURCE_NAMES = (GOLD_NAMESPACE, GOLD_HISTORY_NAMESPACE, GOLD_CONFLICTS_NAMESPACE)
NON_SOURCE_PREFIXES = (CHANGELOG_PREFIX, CLEANING_PREFIX, QUARANTINE_PREFIX)
