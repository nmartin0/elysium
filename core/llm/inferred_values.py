"""An answer resting on inferred values says so, and code makes sure (R63).

"THE AGENT READS EVALUATION RESULTS, CODE ENFORCES THEM" -- the audit's
recommendation for every statistical output that reaches the model. It
came with a measurement: on the fields enterprise tables actually have,
about half the automatic merges at threshold 0.5 were wrong, and only
the calibrated method had the sense to refuse. A model told "this value
is a guess" may still state it as fact; a footer written by code cannot
be left out.

THE STATISTICAL OUTPUTS THAT REACH THE AGENT ARE ENRICHMENT (R41): a
field filled by rules a model wrote and a person approved, scored when
it was approved against the model's own answers on held-out records;
AND PREDICTION (R48): a field a model guesses where the answer is not
recorded, approved per compartment only after beating the naive guess
on records it never learned from.
Merges reach it too, but every one was approved by a person, record by
record (R57 ticks, a person presses); that is a decision, not an
estimate. Source track records and votes (R60) are about which source to
trust, not about a value the agent reads.

SO, FOR ANY ANSWER WHOSE DATA HOLDS AN INFERRED VALUE:

  THE MODEL READS IT. The data handed to synthesis is followed by which
  of its fields are inferred, from what, and how the rules scored.

  CODE ENFORCES IT. After the answer passes the checks that already
  guard it (figures, citations, emails), a note naming those fields is
  APPENDED by code, whatever the model wrote. Fail-closed is the wrong
  shape here -- an inferred value is approved and may be served -- so
  the enforcement is that the reader is always told, not that the
  answer is withheld.

"INFERRED" MEANS PRESENT IN THE DATA, by any route: a field read, an
object read with it, a search filtered on it ("customers whose segment
is Retail" selects BY the inference), or an aggregate grouped by it.

THE SCORE IS AGREEMENT WITH THE MODEL, NOT ACCURACY: the held-out
records were labelled by the same model, and the note says so in
those words rather than calling it a success rate.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InferredField:
    object_type: str
    field: str
    # "inferred from subject, body" -- Enrichment.describe()
    source: str
    # From the approved recipe's held-out evaluation; None when it has
    # none recorded.
    agreed: "int | None" = None
    covered: "int | None" = None
    # R48: a model's guess, not rules' choice -- said in its own words.
    predicted: bool = False

    def label(self) -> str:
        return f"{self.object_type}.{self.field}"

    def how(self) -> str:
        if self.predicted:
            return "guessed by a model a person approved, only where it is not recorded"
        return "chosen by rules a person approved"

    def score(self) -> str:
        if self.predicted:
            # PER COMPARTMENT, so no one number is the reader's: the rule
            # every approval met is what can be said of them all.
            return ("it was approved only after beating the naive guess on records it never "
                    "learned from, and is measured again whenever it is retrained")
        if self.agreed is None or not self.covered:
            return "no held-out score was recorded when they were approved"
        return (f"when approved, they agreed with the model's own answers on "
                f"{self.agreed} of {self.covered} held-out records")


def inferred_fields(schema: Mapping[str, Any], recipes: Any = None
                    ) -> dict[tuple[str, str], InferredField]:
    """Every enriched field in the schema, with its approved recipe's
    held-out score when `recipes` (an EnrichmentRecipeStore) has one; and
    every predicted field (R48)."""
    from core.ontology.enriched_fields import declaration_hash, enrichment_of
    from core.ontology.predicted_fields import prediction_of

    found = {}
    for object_type, type_def in (schema or {}).items():
        fields = (type_def or {}).get("fields") or {}
        for field_name, field_info in fields.items():
            prediction = prediction_of(field_info, fields)
            if prediction is not None:
                found[(object_type, field_name)] = InferredField(
                    object_type, field_name, prediction.describe(), predicted=True)
                continue
            enrichment = enrichment_of(field_info)
            if enrichment is None:
                continue
            held = None
            if recipes is not None:
                held = recipes.approved_evaluation(
                    object_type, field_name,
                    declaration_hash(object_type, field_name, enrichment))
            found[(object_type, field_name)] = InferredField(
                object_type, field_name, enrichment.describe(),
                agreed=(held or {}).get("agreed"), covered=(held or {}).get("covered"))
    return found


def _fields_named(item: Mapping[str, Any]) -> set[str]:
    """Every field a gathered step read, filtered on or grouped by."""
    names: set[str] = set()
    if isinstance(item.get("field_name"), str):
        names.add(item["field_name"])
    names.update(n for n in item.get("field_names") or () if isinstance(n, str))
    if isinstance(item.get("group_by"), str):
        names.add(item["group_by"])
    if isinstance(item.get("filter"), Mapping):
        names.update(k for k in item["filter"] if isinstance(k, str))
    result = item.get("result")
    if item.get("step") == "get_object" and isinstance(result, Mapping):
        # {id: {field: value}} or {field: value}
        for value in result.values():
            if isinstance(value, Mapping):
                names.update(k for k in value if isinstance(k, str))
            else:
                names.update(k for k in result if isinstance(k, str))
                break
    return names


def inferred_in(records: Iterable[Mapping[str, Any]],
                inferred: Mapping[tuple[str, str], InferredField]) -> list[InferredField]:
    """The inferred fields the data behind an answer touches, in a fixed
    order."""
    if not inferred:
        return []
    found = {}
    for item in records:
        object_type = item.get("object_type")
        for name in _fields_named(item):
            hit = inferred.get((object_type, name))  # type: ignore[arg-type]
            if hit is not None:
                found[hit.label()] = hit
    return [found[key] for key in sorted(found)]


def for_the_model(found: list[InferredField]) -> str:
    """Appended to the data synthesis reads."""
    if not found:
        return ""
    lines = "\n".join(f"- {f.label()}: {f.source}, {f.how()}; {f.score()}." for f in found)
    return ("\n\nSome values above are INFERRED, not recorded. Say so if your answer "
            f"relies on them:\n{lines}")


def for_the_reader(found: list[InferredField]) -> str:
    """Appended to the answer by code, whatever the model wrote."""
    if not found:
        return ""
    lines = "\n".join(f"- {f.label()} was {f.how()} ({f.source}); {f.score()}."
                      for f in found)
    return f"\n\nInferred, not recorded -- this answer's data includes:\n{lines}"
