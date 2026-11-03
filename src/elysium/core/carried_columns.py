"""The columns Elysium writes into every row and carries forward.

A LEAF, AND IT HAS TO BE. `core/mirror` writes these and
`core/ontology` reads one of them, and the import contract forbids
ontology reaching into mirror -- correctly, since the mediator should
not depend on how the lake is built. So the names live below both.

WHY A NAMED SET RATHER THAN A PREFIX CONVENTION. I assumed
`startswith("_")` meant "carried", because fusion copies columns that
way. It is one call site. Measured: `_security` reached silver and was
absent from gold entirely, because gold, the gold schema builder and
the arrow conformer each name an EXPLICIT list. Four places, found by
measuring rather than reading.

They now all name this set, so a fifth stage that copies it gets the
behaviour; a fifth stage that writes its own list does not, and that
is the honest limit of the approach.
"""

#: Where a row came from (GOLD-1's rule S6).
SILO_COLUMN = "_silo"
SOURCE_TABLE_COLUMN = "_source_table"
ROW_HASH_COLUMN = "_row_hash"

LINEAGE_COLUMNS = (SILO_COLUMN, SOURCE_TABLE_COLUMN, ROW_HASH_COLUMN)

#: THE VALUE THAT DECIDES WHO MAY SEE THE ROW -- `LLM3-3`.
#:
#: Copied once, at sync, from the field a type declares in
#: `security: {field: ...}`. MAC reads THIS rather than the declared
#: column, so its input is immune to anything a later stage does to
#: the data: an enrichment that rewrites `region`, a redaction that
#: blanks it, a standardisation that folds its case.
#:
#: The measured damage before this: a region of "N/A" became None and
#: the object belonged to no compartment at all; `" us-west "` became
#: `"us-west"` and stopped matching a caller whose own value kept its
#: spacing.
#:
#: NOT LINEAGE. The security value is not provenance, and putting it
#: in LINEAGE_COLUMNS would say it was.
SECURITY_COLUMN = "_security"

#: Everything above: written by Elysium, carried by every stage.
CARRIED_COLUMNS = (*LINEAGE_COLUMNS, SECURITY_COLUMN)
