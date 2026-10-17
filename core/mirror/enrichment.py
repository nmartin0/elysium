"""Approved enrichment recipes, brought to the gold build (R41).

run_sync hands build_gold a copy of each type with every enriched
field's approved rules attached; gold_arrow.with_enriched applies them.
Kept here, in the mirror, so the recipe store stays a store.
"""

import logging

from core.enrichment_recipes import EnrichmentRecipeStore

logger = logging.getLogger(__name__)


def with_approved_recipes(object_type: str, type_def, store: EnrichmentRecipeStore,
                          locale: "str | None" = None) -> dict:
    """A plain copy of the type with each enriched field's APPROVED rules
    attached, for build_gold. A type with no enriched field comes back
    as the same object -- nothing to copy, and the gold digest of every
    other type unchanged."""
    from core.mirror.gold_arrow import APPROVED_LOCALE, APPROVED_RULES
    from core.ontology.enriched_fields import (
        check_recipe,
        declaration_hash,
        enriched_fields,
    )

    enriched = enriched_fields(type_def)
    if not enriched:
        return type_def
    fields = {name: dict(field) for name, field in (type_def.get("fields") or {}).items()}
    for field_name, enrichment in enriched.items():
        rules = store.approved_rules(object_type, field_name,
                                     declaration_hash(object_type, field_name, enrichment))
        if rules is None:
            continue
        try:
            # CHECKED AGAIN ON THE WAY OUT: the store holds what was
            # checked when proposed, and this is the last place before a
            # value is published.
            # One rule set or a weighted vote of several.
            fields[field_name][APPROVED_RULES] = check_recipe(rules, enrichment)
            if enrichment.extract is not None:
                # The locale rides with the rules, so a change to it is
                # a change to what gold is built from, and republishes.
                fields[field_name][APPROVED_LOCALE] = locale
        except ValueError as e:
            logger.warning("%s.%s: its approved rules no longer check (%s); left empty",
                           object_type, field_name, e)
    return {**type_def, "fields": fields}
